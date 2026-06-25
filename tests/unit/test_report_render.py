"""The deterministic JSON → HTML report renderer (PDF step's first half).

PDF generation itself drives headless Chromium and is exercised by the smoke
path / e2e, not here — these tests pin the HTML content so layout regressions
and number formatting are caught cheaply.
"""
from src.automation.report_render import render_report_html

_REPORT = {
    "summary": "本週獲利穩健。",
    "skus": [
        {"sku": "A", "name": "賺錢王", "units": 8, "revenue": 2272, "net_profit": 1666, "margin_pct": 73.3, "flags": ["最賺錢"]},
        {"sku": "B", "name": "虧損品", "units": 2, "revenue": 342, "net_profit": -329, "margin_pct": -96.2, "flags": ["廣告無效"]},
    ],
    "recommendations": [
        {"sku": "B", "action": "停賣", "reason": "持續虧損"},
    ],
    "action_items": ["備貨補倉"],
}


def test_summary_cards_aggregate():
    html = render_report_html(_REPORT)
    assert "NT$2,614" in html          # total revenue 2272 + 342
    assert "+NT$1,337" in html         # total net 1666 - 329
    assert "本週總入帳" in html and "虧損 SKU" in html


def test_sku_rows_sorted_and_formatted():
    html = render_report_html(_REPORT)
    # Winner (margin 73.3) appears before the loss-maker (-96.2).
    assert html.index("賺錢王") < html.index("虧損品")
    assert "+73.3%" in html and "−96.2%" in html      # signed, U+2212 minus
    assert "−NT$329" in html


def test_flags_and_action_cards_render():
    html = render_report_html(_REPORT)
    assert 'chip-good' in html and 'chip-bad' in html
    assert "下週優先行動" in html
    assert "停賣" in html and "立即處理" in html        # action → priority badge


def test_empty_report_is_safe():
    html = render_report_html({})
    assert "AI 利潤健檢報告" in html
    assert "NT$0" in html


def test_non_numeric_cells_do_not_crash():
    """LLM-emitted garbage values must render (as 0) rather than raise."""
    html = render_report_html({"skus": [
        {"sku": "X", "name": "壞資料", "units": "N/A", "revenue": "120 NTD",
         "net_profit": None, "margin_pct": "n/a", "flags": []},
    ]})
    assert "壞資料" in html
    assert "NT$0" in html
