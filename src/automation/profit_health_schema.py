"""Frozen contracts for the 利潤健檢 (profit_health_check) automation.

Single source of truth shared across phases:
  - the job-type string             → executor _FLOW_MAP, validator, system catalog
  - strict CSV column expectations  → profit_calc tool (Phase 3)
  - the profit_calc tool I/O shape  → tool + analyzer agent (Phase 3/4)
  - the report JSON shape           → crew final task + validator (Phase 4)

Importing from here keeps field names consistent so later phases don't churn.
See doc/profit-health-check-design.md.
"""

from pydantic import BaseModel, Field

# --- job type ---------------------------------------------------------------

JOB_TYPE = "profit_health_check"

# --- strict CSV schemas (sample_data) --------------------------------------
# Key columns each uploaded file must contain. The MVP is strict to the sample
# headers; semantic adaptation is a v2 (see design doc).

SALES_COLUMNS = [
    "訂單編號", "訂單狀態", "商品SKU", "數量",
    "商品原價(NTD)", "蝦皮手續費(NTD)", "賣家實際入帳(NTD)",
]
COST_COLUMNS = ["商品SKU", "單位總成本(NTD)"]
ADS_COLUMNS = ["商品SKU", "廣告花費(NTD)", "廣告銷售額(NTD)", "ROAS"]
RETURNS_COLUMNS = ["訂單編號", "商品SKU", "退款金額(NTD)", "退貨/退款狀態"]

# The ads_discount.csv sample begins with a "## ..." comment row that must be
# skipped before the header row is read.
ADS_COMMENT_PREFIX = "##"

# --- flag labels (Traditional Chinese) -------------------------------------
# Used both as values inside SkuMetrics.flags and as the keys of ProfitFlags.

FLAG_MOST_PROFITABLE = "最賺錢"
FLAG_FAKE_HIT = "假爆品"
FLAG_AD_EATS_PROFIT = "廣告吃利潤"
FLAG_HIGH_RETURN = "退貨異常"

# --- shared per-SKU metrics -------------------------------------------------


class SkuMetrics(BaseModel):
    """One row of computed truth for a single SKU.

    Produced deterministically by the profit_calc tool; quoted (never
    recomputed) by the analyzer agent in the final report.
    """

    sku: str
    name: str = ""
    revenue: float = 0.0       # 銷售額 — 賣家實際入帳 合計
    cost: float = 0.0          # 成本 — 數量 × 單位總成本
    ad_spend: float = 0.0      # 廣告花費
    refunds: float = 0.0       # 退款額
    net_profit: float = 0.0    # 淨利 = revenue − cost − ad_spend − refunds
    margin_pct: float = 0.0    # 淨利率 = net_profit / revenue × 100
    units: int = 0             # 數量 合計
    roas: float | None = None  # 廣告銷售額 / 廣告花費
    return_count: int = 0      # 退貨筆數 (all return records)
    return_rate: float = 0.0   # return_count / 已完成訂單數 × 100
    flags: list[str] = Field(default_factory=list)


class ProfitFlags(BaseModel):
    """SKU lists grouped by signal. Each list holds SKU codes."""

    most_profitable: list[str] = Field(default_factory=list)
    fake_hits: list[str] = Field(default_factory=list)
    ad_eats_profit: list[str] = Field(default_factory=list)
    high_return_rate: list[str] = Field(default_factory=list)


# --- profit_calc tool I/O (Phase 3) ----------------------------------------


class ProfitCalcInput(BaseModel):
    """Raw CSV text for each uploaded file. sales + cost required."""

    sales_csv: str
    cost_csv: str
    ads_csv: str = ""
    returns_csv: str = ""


class ProfitCalcResult(BaseModel):
    """Deterministic output of the profit_calc tool."""

    skus: list[SkuMetrics] = Field(default_factory=list)
    flags: ProfitFlags = Field(default_factory=ProfitFlags)


# --- report shape (Phase 4) -------------------------------------------------


class Recommendation(BaseModel):
    sku: str
    action: str  # 停賣 / 漲價 / 補貨 / 改圖 / 改組合 ...
    reason: str = ""


class Validation(BaseModel):
    ok: bool = True
    issues: list[str] = Field(default_factory=list)


class ProfitReport(BaseModel):
    """The final JSON report returned by the crew. Traditional Chinese."""

    summary: str = ""
    skus: list[SkuMetrics] = Field(default_factory=list)
    flags: ProfitFlags = Field(default_factory=ProfitFlags)
    recommendations: list[Recommendation] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    validation: Validation = Field(default_factory=Validation)
