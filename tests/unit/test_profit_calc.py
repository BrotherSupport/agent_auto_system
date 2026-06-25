"""Unit tests for the deterministic profit_calc tool (Phase 3).

Expected numbers are hand-verified against shopee/sample_data/. See the model
documented in src/automation/tools/profit_calc_tool.py.
"""
from pathlib import Path

import pytest

from src.automation.profit_health_schema import (
    FLAG_AD_EATS_PROFIT,
    FLAG_FAKE_HIT,
    FLAG_HIGH_RETURN,
    FLAG_MOST_PROFITABLE,
)
from src.automation.tools.profit_calc_tool import ProfitCalcTool, compute_profit

_SD = Path(__file__).resolve().parents[2] / "shopee" / "sample_data"


@pytest.fixture(scope="module")
def result():
    return compute_profit(
        (_SD / "shopee_sales_report.csv").read_text(encoding="utf-8"),
        (_SD / "product_cost.csv").read_text(encoding="utf-8"),
        (_SD / "ads_discount.csv").read_text(encoding="utf-8"),
        (_SD / "order_return_refund.csv").read_text(encoding="utf-8"),
    )


@pytest.fixture(scope="module")
def by_sku(result):
    return {m.sku: m for m in result.skus}


def test_all_skus_present(result):
    # 10 SKUs have completed sales (CASE-IP14-CLR's only valid order is completed;
    # SKUs whose only order is 不成立 would be excluded — none here).
    assert len(result.skus) == 10


def test_chg_wl_15w_arithmetic(by_sku):
    m = by_sku["CHG-WL-15W"]
    assert m.units == 5
    assert m.revenue == 3230          # 646+646+1292+646
    assert m.cost == 950              # 5 × 190
    assert m.ad_spend == 120
    assert m.refunds == 0
    assert m.net_profit == 2160       # 3230 − 950 − 120
    assert m.margin_pct == pytest.approx(66.87, abs=0.01)


def test_case_ip15_blk_is_fake_hit(by_sku):
    """Best-seller by units (18) but thin margin → 假爆品 + 廣告吃利潤."""
    m = by_sku["CASE-IP15-BLK"]
    assert m.units == 18
    assert m.revenue == 2952
    assert m.cost == 1530             # 18 × 85
    assert m.ad_spend == 1260
    assert m.net_profit == 162
    assert m.margin_pct == pytest.approx(5.49, abs=0.01)
    assert FLAG_FAKE_HIT in m.flags
    assert FLAG_AD_EATS_PROFIT in m.flags


def test_bt_ear_returns(by_sku):
    """3 return records (2 已退款 realized, 1 退款申請中) → 退貨異常."""
    m = by_sku["BT-EAR-A1-WHT"]
    assert m.units == 5               # 5 完成; the 不成立 order is excluded
    assert m.revenue == 6080
    assert m.refunds == 2560          # only the 2 已退款 rows, not the pending one
    assert m.return_count == 3
    assert m.net_profit == 890        # 6080 − 2150 − 480 − 2560
    assert FLAG_HIGH_RETURN in m.flags


def test_cancelled_orders_excluded(by_sku):
    """POWER-MAG-10K has a 不成立 order (row 34) that must not inflate units/cost."""
    m = by_sku["POWER-MAG-10K"]
    assert m.units == 3               # rows 13,28,42 only; row 34 (不成立) excluded
    assert m.revenue == 4245          # 1415 × 3
    assert m.cost == 1689             # 3 × 563


def test_ad_eats_profit_flag(by_sku):
    """CABLE-MAG-2M: 2100 ad spend on 2326 revenue → negative net."""
    m = by_sku["CABLE-MAG-2M"]
    assert m.ad_spend == 2100
    assert m.net_profit < 0
    assert FLAG_AD_EATS_PROFIT in m.flags


def test_grouped_flags(result):
    flags = result.flags
    assert flags.most_profitable == ["POWER-MAG-10K", "CHG-WL-15W", "STAND-DESK-ADJ"]
    assert "CASE-IP15-BLK" in flags.fake_hits
    assert "CABLE-MAG-2M" in flags.ad_eats_profit
    assert "BT-EAR-A1-WHT" in flags.high_return_rate


def test_roas_parsed(by_sku):
    assert by_sku["BT-EAR-A1-WHT"].roas == pytest.approx(10.67, abs=0.01)


def test_most_profitable_labels_mirrored(by_sku):
    assert FLAG_MOST_PROFITABLE in by_sku["POWER-MAG-10K"].flags


def test_ads_discount_block_ignored():
    """The 折扣 block after the ads block must not be parsed as ad rows."""
    ads = (_SD / "ads_discount.csv").read_text(encoding="utf-8")
    res = compute_profit(
        (_SD / "shopee_sales_report.csv").read_text(encoding="utf-8"),
        (_SD / "product_cost.csv").read_text(encoding="utf-8"),
        ads, "",
    )
    # 折扣 rows reference SKUs too, but only ads-block spend should appear.
    m = {x.sku: x for x in res.skus}["CASE-IP15-BLK"]
    assert m.ad_spend == 1260  # not polluted by the 折扣 block's 3322/990 numbers


def test_optional_files_absent():
    """sales + cost only — ads/returns optional, must not crash."""
    res = compute_profit(
        (_SD / "shopee_sales_report.csv").read_text(encoding="utf-8"),
        (_SD / "product_cost.csv").read_text(encoding="utf-8"),
    )
    m = {x.sku: x for x in res.skus}["CASE-IP15-BLK"]
    assert m.ad_spend == 0
    assert m.refunds == 0
    assert m.net_profit == 2952 - 1530  # no ads, no refunds


def test_tool_handles_utf8_bom(tmp_path, monkeypatch):
    """Shopee/Excel exports often carry a UTF-8 BOM; the tool must still parse —
    including recognizing the ads file's leading '## ...' comment line."""
    import src.routers.uploads as uploads_mod

    monkeypatch.setattr(uploads_mod, "UPLOAD_ROOT", tmp_path)
    dest = tmp_path / "bom1"
    dest.mkdir()
    for src_name, dst_name in (
        ("shopee_sales_report.csv", "sales.csv"),
        ("product_cost.csv", "cost.csv"),
        ("ads_discount.csv", "ads.csv"),
        ("order_return_refund.csv", "returns.csv"),
    ):
        text = (_SD / src_name).read_text(encoding="utf-8")
        (dest / dst_name).write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))  # prepend BOM

    from src.automation.tools.profit_calc_tool import compute_profit_from_upload
    res = compute_profit_from_upload("bom1")
    by_sku = {m.sku: m for m in res.skus}
    # If the BOM weren't stripped, the SKU key would be "﻿商品SKU" and this would fail.
    assert "CASE-IP15-BLK" in by_sku
    # If the ads BOM broke comment detection, ad_spend would be wrong/zero.
    assert by_sku["CASE-IP15-BLK"].ad_spend == 1260
    assert by_sku["CHG-WL-15W"].net_profit == 2160


def test_tool_run_reads_upload(tmp_path, monkeypatch):
    # The tool reads the 4 CSVs from uploads/<upload_id>/ given an upload_id.
    import src.routers.uploads as uploads_mod

    monkeypatch.setattr(uploads_mod, "UPLOAD_ROOT", tmp_path)
    dest = tmp_path / "abc123"
    dest.mkdir()
    for src_name, dst_name in (
        ("shopee_sales_report.csv", "sales.csv"),
        ("product_cost.csv", "cost.csv"),
        ("ads_discount.csv", "ads.csv"),
        ("order_return_refund.csv", "returns.csv"),
    ):
        (dest / dst_name).write_text((_SD / src_name).read_text(encoding="utf-8"), encoding="utf-8")

    out = ProfitCalcTool()._run(upload_id="abc123")
    assert isinstance(out, dict)
    assert "skus" in out and "flags" in out
    assert len(out["skus"]) == 10
