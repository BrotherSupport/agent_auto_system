"""Deterministic per-SKU profit math for the 利潤健檢 automation (Phase 3).

The arithmetic lives here, in Python — never in an LLM prompt — so the numbers
are trustworthy (see doc/profit-health-check-design.md). The analyzer agent
(Phase 4) calls this tool and decides *what* to flag; this code decides the
*numbers*.

Model (strict to the sample_data schemas):
  revenue    = Σ 賣家實際入帳(NTD)   over 已完成 orders
  units      = Σ 數量                over 已完成 orders
  cost       = units × 單位總成本(NTD)
  ad_spend   = 廣告花費(NTD)         (ads block only)
  refunds    = Σ 退款金額(NTD)       where 退貨/退款狀態 == 已退款 (realized)
  net_profit = revenue − cost − ad_spend − refunds
  margin_pct = net_profit / revenue × 100
"""

import csv
import io

from crewai.tools import BaseTool
from pydantic import BaseModel

from src.automation.profit_health_schema import (
    ADS_COMMENT_PREFIX,
    FLAG_AD_EATS_PROFIT,
    FLAG_FAKE_HIT,
    FLAG_HIGH_RETURN,
    FLAG_MOST_PROFITABLE,
    ProfitCalcResult,
    ProfitFlags,
    SkuMetrics,
)

# --- flag thresholds (documented, tunable) ---------------------------------
MOST_PROFITABLE_TOP_N = 3       # top SKUs by net_profit (must be > 0)
FAKE_HIT_MIN_UNITS = 3          # "sells well" floor
FAKE_HIT_MARGIN_PCT = 10.0      # but margin below this → 假爆品
HIGH_RETURN_RATE_PCT = 20.0     # return_count / completed_orders ≥ this → 退貨異常
HIGH_RETURN_MIN_COUNT = 2       # ...or this many returns outright

_COMPLETED_STATUS = "已完成"
_REFUNDED_STATUS = "已退款"


def _num(value) -> float:
    """Parse a CSV cell to float; blank/garbage → 0.0."""
    if value is None:
        return 0.0
    s = str(value).strip().replace(",", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_ads(ads_csv: str) -> dict[str, dict]:
    """Parse the 廣告 block only. The file also holds a 折扣 block after a blank
    line + second '##' header — stop before it."""
    rows: dict[str, dict] = {}
    header: list[str] | None = None
    for line in ads_csv.splitlines():
        s = line.strip()
        if not s or s.startswith(ADS_COMMENT_PREFIX):
            if header is not None:
                break  # blank/comment after the ads header ends the block
            continue
        cells = next(csv.reader([line]))
        if header is None:
            header = cells
            continue
        rec = dict(zip(header, cells))
        if rec.get("區塊") and rec["區塊"] != "廣告":
            break
        sku = (rec.get("商品SKU") or "").strip()
        if sku:
            rows[sku] = rec
    return rows


def compute_profit(
    sales_csv: str, cost_csv: str, ads_csv: str = "", returns_csv: str = ""
) -> ProfitCalcResult:
    # --- cost table: SKU → unit cost / name ---
    cost_by_sku: dict[str, float] = {}
    name_by_sku: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(cost_csv)):
        sku = (row.get("商品SKU") or "").strip()
        if not sku:
            continue
        cost_by_sku[sku] = _num(row.get("單位總成本(NTD)"))
        name_by_sku[sku] = (row.get("商品名稱") or "").strip()

    # --- ads table ---
    ads_by_sku = _parse_ads(ads_csv) if ads_csv.strip() else {}

    # --- returns table: realized refund amount + return count per SKU ---
    refund_by_sku: dict[str, float] = {}
    return_count_by_sku: dict[str, int] = {}
    if returns_csv.strip():
        for row in csv.DictReader(io.StringIO(returns_csv)):
            sku = (row.get("商品SKU") or "").strip()
            if not sku:
                continue
            return_count_by_sku[sku] = return_count_by_sku.get(sku, 0) + 1
            if (row.get("退貨/退款狀態") or "").strip() == _REFUNDED_STATUS:
                refund_by_sku[sku] = refund_by_sku.get(sku, 0.0) + _num(row.get("退款金額(NTD)"))

    # --- aggregate completed sales per SKU ---
    revenue: dict[str, float] = {}
    units: dict[str, int] = {}
    orders: dict[str, int] = {}
    for row in csv.DictReader(io.StringIO(sales_csv)):
        if (row.get("訂單狀態") or "").strip() != _COMPLETED_STATUS:
            continue  # skip 不成立 (cancelled) orders
        sku = (row.get("商品SKU") or "").strip()
        if not sku:
            continue
        revenue[sku] = revenue.get(sku, 0.0) + _num(row.get("賣家實際入帳(NTD)"))
        units[sku] = units.get(sku, 0) + int(_num(row.get("數量")))
        orders[sku] = orders.get(sku, 0) + 1
        name_by_sku.setdefault(sku, (row.get("商品名稱") or "").strip())

    # --- build per-SKU metrics ---
    skus: list[SkuMetrics] = []
    for sku in sorted(revenue.keys()):
        rev = round(revenue[sku], 2)
        u = units.get(sku, 0)
        cost = round(u * cost_by_sku.get(sku, 0.0), 2)
        ad = round(_num(ads_by_sku.get(sku, {}).get("廣告花費(NTD)")), 2)
        refunds = round(refund_by_sku.get(sku, 0.0), 2)
        net = round(rev - cost - ad - refunds, 2)
        margin = round(net / rev * 100, 2) if rev else 0.0
        rc = return_count_by_sku.get(sku, 0)
        completed = orders.get(sku, 0)
        roas = ads_by_sku.get(sku, {}).get("ROAS")
        skus.append(SkuMetrics(
            sku=sku, name=name_by_sku.get(sku, ""),
            revenue=rev, cost=cost, ad_spend=ad, refunds=refunds,
            net_profit=net, margin_pct=margin, units=u,
            roas=_num(roas) if roas not in (None, "") else None,
            return_count=rc,
            return_rate=round(rc / completed * 100, 2) if completed else 0.0,
        ))

    flags = _derive_flags(skus)
    # Mirror the grouped flags onto each SKU's own flag list.
    for m in skus:
        if m.sku in flags.most_profitable:
            m.flags.append(FLAG_MOST_PROFITABLE)
        if m.sku in flags.fake_hits:
            m.flags.append(FLAG_FAKE_HIT)
        if m.sku in flags.ad_eats_profit:
            m.flags.append(FLAG_AD_EATS_PROFIT)
        if m.sku in flags.high_return_rate:
            m.flags.append(FLAG_HIGH_RETURN)

    return ProfitCalcResult(skus=skus, flags=flags)


def _derive_flags(skus: list[SkuMetrics]) -> ProfitFlags:
    flags = ProfitFlags()

    # 最賺錢: top N by net_profit among profitable SKUs
    profitable = sorted([m for m in skus if m.net_profit > 0],
                        key=lambda m: m.net_profit, reverse=True)
    flags.most_profitable = [m.sku for m in profitable[:MOST_PROFITABLE_TOP_N]]

    for m in skus:
        # 假爆品: sells (≥ min units) but thin/negative margin
        if m.units >= FAKE_HIT_MIN_UNITS and m.margin_pct < FAKE_HIT_MARGIN_PCT:
            flags.fake_hits.append(m.sku)
        # 廣告吃利潤: ad spend exceeds the net profit it left behind
        if m.ad_spend > 0 and m.ad_spend > m.net_profit:
            flags.ad_eats_profit.append(m.sku)
        # 退貨異常: high return rate or repeated returns
        if m.return_count >= HIGH_RETURN_MIN_COUNT or m.return_rate >= HIGH_RETURN_RATE_PCT:
            flags.high_return_rate.append(m.sku)

    return flags


def compute_profit_from_upload(upload_id: str) -> ProfitCalcResult:
    """Read the 4 CSVs from uploads/<upload_id>/ and compute metrics.

    Imported lazily so the pure compute_profit() core has no dependency on the
    upload-storage location.
    """
    from src.routers.uploads import UPLOAD_ROOT

    base = UPLOAD_ROOT / upload_id

    def _rd(name: str) -> str:
        # utf-8-sig strips a UTF-8 BOM if present (common in Shopee/Excel exports);
        # critical so the ads file's leading "## ..." comment line is recognized.
        p = base / name
        return p.read_text(encoding="utf-8-sig", errors="replace") if p.is_file() else ""

    return compute_profit(_rd("sales.csv"), _rd("cost.csv"), _rd("ads.csv"), _rd("returns.csv"))


class _ProfitCalcArgs(BaseModel):
    upload_id: str


class ProfitCalcTool(BaseTool):
    name: str = "profit_calc"
    description: str = (
        "Compute deterministic per-SKU profit metrics for an uploaded data set. "
        "Pass the upload_id; the tool reads the 4 Shopee CSVs (sales, cost, ads, "
        "returns) and returns each SKU's revenue, cost, ad_spend, refunds, "
        "net_profit, margin_pct, units, roas, return_count/rate, plus grouped flags "
        "(最賺錢/假爆品/廣告吃利潤/退貨異常). Use this for ALL arithmetic; never compute "
        "numbers yourself."
    )
    args_schema: type[BaseModel] = _ProfitCalcArgs

    def _run(self, upload_id: str) -> dict:
        return compute_profit_from_upload(upload_id).model_dump()
