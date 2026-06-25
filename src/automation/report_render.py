"""Render a 利潤健檢 ProfitReport (JSON) → styled HTML → PDF.

Deterministic by design — no LLM. Layout/maths here mirror the on-screen demo
report (summary cards, per-SKU table with margin bars + AI 判斷 badges, and a
prioritised next-week action list). Kept out of the crew because rendering is
pure presentation: same input → same bytes, consistent with the project's
"deterministic maths stays in tools, not agents" invariant.

`render_report_html(report)` builds a self-contained HTML string; `html_to_pdf`
prints it via the Playwright Chromium that's already vendored for form_fill, so
no new dependency and faithful CJK + flexbox rendering.
"""

from html import escape
from pathlib import Path

# src/automation/report_render.py → parents[2] is the project root.
REPORTS_ROOT = Path(__file__).resolve().parents[2] / "reports"

# Per-SKU flag → (label, css class). Covers the deterministic profit_calc flags
# plus the richer labels the advisor agent may emit. Unknown flags fall back to a
# neutral chip so the report never drops information.
_FLAG_STYLE = {
    "最賺錢": "good", "優質": "good", "獲利": "good",
    "假爆品": "warn", "滯銷庫存": "warn", "滯銷": "warn", "低毛利": "warn",
    "廣告吃利潤": "bad", "廣告虧損": "bad", "廣告無效": "bad",
    "退貨異常": "bad", "退貨危機": "bad", "虧損": "bad",
}

# Recommendation action → priority chip class + label. Drives the action cards.
_ACTION_STYLE = {
    "停賣": ("urgent", "立即處理"),
    "改圖": ("urgent", "立即處理"),
    "漲價": ("soon", "本週執行"),
    "改組合": ("soon", "本週執行"),
    "補貨": ("scale", "備貨補倉"),
    "加碼": ("scale", "擴大規模"),
}


def _safe_float(value, default: float = 0.0) -> float:
    """Coerce a (possibly LLM-emitted) cell to float; blank/garbage → default.

    The report dict is re-emitted by the advisor agent, so a stray "N/A" or
    "120 NTD" must not crash rendering.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _nt(value: float) -> str:
    """Format a number as NT$ with thousands separators, no decimals."""
    return f"NT${round(_safe_float(value)):,}"


def _signed_nt(value: float) -> str:
    v = round(_safe_float(value))
    sign = "+" if v > 0 else ("−" if v < 0 else "")  # − for negatives
    return f"{sign}NT${abs(v):,}"


def _signed_pct(value: float) -> str:
    v = _safe_float(value)
    sign = "+" if v > 0 else ("−" if v < 0 else "")
    return f"{sign}{abs(v):.1f}%"


def _flag_chip(flag: str) -> str:
    cls = _FLAG_STYLE.get(flag, "neutral")
    return f'<span class="chip chip-{cls}">{escape(flag)}</span>'


def render_report_html(report: dict, *, title: str = "AI 利潤健檢報告") -> str:
    """Build a self-contained HTML report from a ProfitReport-shaped dict."""
    report = report or {}
    skus = list(report.get("skus") or [])
    summary = report.get("summary") or ""
    recommendations = list(report.get("recommendations") or [])
    action_items = list(report.get("action_items") or [])

    total_revenue = sum(_safe_float(s.get("revenue")) for s in skus)
    total_net = sum(_safe_float(s.get("net_profit")) for s in skus)
    profitable = sum(1 for s in skus if _safe_float(s.get("margin_pct")) > 50)
    losing = sum(1 for s in skus if _safe_float(s.get("net_profit")) < 0)

    # Sort SKUs by margin desc so winners lead and loss-makers sink — matches demo.
    skus_sorted = sorted(skus, key=lambda s: _safe_float(s.get("margin_pct")), reverse=True)

    rows = []
    for s in skus_sorted:
        margin = _safe_float(s.get("margin_pct"))
        net = _safe_float(s.get("net_profit"))
        # Bar width: clamp |margin| to 0..100; colour by profit sign.
        width = max(0, min(100, abs(margin)))
        bar_cls = "bar-good" if net >= 0 else "bar-bad"
        net_cls = "pos" if net >= 0 else "neg"
        flags = "".join(_flag_chip(f) for f in (s.get("flags") or [])) or '<span class="chip chip-neutral">—</span>'
        rows.append(f"""
        <tr>
          <td><div class="sku-name">{escape(str(s.get('name') or s.get('sku', '')))}</div>
              <div class="sku-code">{escape(str(s.get('sku', '')))}</div></td>
          <td class="num">{int(_safe_float(s.get('units')))}</td>
          <td class="num">{_nt(s.get('revenue', 0))}</td>
          <td class="num {net_cls}">{_signed_nt(net)}</td>
          <td><div class="margin-cell"><div class="bar"><div class="bar-fill {bar_cls}" style="width:{width:.0f}%"></div></div>
              <span class="margin-pct {net_cls}">{_signed_pct(margin)}</span></div></td>
          <td>{flags}</td>
        </tr>""")

    # Action cards: prefer structured recommendations, fall back to action_items.
    action_cards = []
    for i, rec in enumerate(recommendations, start=1):
        action = str(rec.get("action", "")).strip()
        cls, badge = _ACTION_STYLE.get(action, ("soon", action or "建議"))
        sku_name = next((s.get("name") or s.get("sku") for s in skus if s.get("sku") == rec.get("sku")), rec.get("sku", ""))
        head_cls = "urgent" if cls == "urgent" else ("scale" if cls == "scale" else "soon")
        action_cards.append(f"""
        <div class="action-card ac-{head_cls}">
          <div class="ac-num">{i}</div>
          <div class="ac-body">
            <div class="ac-title">{escape(action)} · {escape(str(sku_name))}<span class="ac-badge ab-{head_cls}">{escape(badge)}</span></div>
            <div class="ac-reason">{escape(str(rec.get('reason', '')))}</div>
          </div>
        </div>""")
    if not action_cards:
        for i, item in enumerate(action_items, start=1):
            action_cards.append(f"""
        <div class="action-card ac-soon">
          <div class="ac-num">{i}</div>
          <div class="ac-body"><div class="ac-reason">{escape(str(item))}</div></div>
        </div>""")

    summary_html = f'<p class="summary">{escape(summary)}</p>' if summary else ""

    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><title>{escape(title)}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: "PingFang TC", "Microsoft JhengHei", "Noto Sans CJK TC", "Heiti TC", sans-serif;
          color: #1f2430; margin: 0; padding: 32px 36px; background: #fff; font-size: 13px; }}
  .head {{ display:flex; align-items:center; gap:12px; margin-bottom:22px; }}
  .head h1 {{ font-size: 22px; margin: 0; font-weight: 700; }}
  .badge-demo {{ background:#f97316; color:#fff; font-size:12px; font-weight:600; padding:3px 10px; border-radius:6px; }}
  .cards {{ display:flex; gap:14px; margin-bottom:26px; }}
  .card {{ flex:1; border:1px solid #e6e8ee; border-radius:12px; padding:18px 20px; }}
  .card.green {{ border-color:#86e0b8; }}
  .card.red {{ border-color:#f1a9a0; }}
  .card .big {{ font-size:26px; font-weight:800; line-height:1.1; }}
  .card.green .big {{ color:#10b981; }}
  .card.red .big {{ color:#ef4444; }}
  .card .lbl {{ color:#6b7280; font-size:12px; margin-top:8px; }}
  .section-title {{ font-size:15px; font-weight:700; border-left:4px solid #10b981; padding-left:10px; margin:24px 0 14px; }}
  .section-title small {{ color:#9aa1ad; font-weight:400; margin-left:8px; }}
  .summary {{ color:#4b5563; line-height:1.7; margin:0 0 18px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ text-align:left; color:#9aa1ad; font-weight:600; font-size:12px; padding:10px 8px; border-bottom:1px solid #eceef2; }}
  td {{ padding:13px 8px; border-bottom:1px solid #f1f3f6; vertical-align:middle; }}
  th.num, td.num {{ text-align:left; }}
  .num {{ font-variant-numeric: tabular-nums; font-weight:600; }}
  .sku-name {{ font-weight:700; }}
  .sku-code {{ color:#9aa1ad; font-size:11px; margin-top:2px; font-family:ui-monospace,monospace; }}
  .pos {{ color:#10b981; }}
  .neg {{ color:#ef4444; }}
  .margin-cell {{ display:flex; align-items:center; gap:10px; }}
  .bar {{ width:64px; height:6px; background:#eceef2; border-radius:4px; overflow:hidden; }}
  .bar-fill {{ height:100%; border-radius:4px; }}
  .bar-good {{ background:#10b981; }}
  .bar-bad {{ background:#ef4444; }}
  .margin-pct {{ font-weight:700; font-variant-numeric: tabular-nums; }}
  .chip {{ display:inline-block; font-size:11px; font-weight:600; padding:3px 9px; border-radius:6px; margin:1px 2px; }}
  .chip-good {{ background:#e6f7ef; color:#0f9d6b; }}
  .chip-warn {{ background:#f3eafe; color:#8b5cf6; }}
  .chip-bad {{ background:#fdecea; color:#e8543c; }}
  .chip-neutral {{ background:#f1f3f6; color:#6b7280; }}
  .action-card {{ display:flex; gap:14px; border:1px solid #e6e8ee; border-left-width:4px; border-radius:10px; padding:14px 16px; margin-bottom:12px; }}
  .ac-urgent {{ border-left-color:#ef4444; background:#fef4f2; }}
  .ac-soon {{ border-left-color:#f59e0b; background:#fffaf2; }}
  .ac-scale {{ border-left-color:#10b981; background:#f1fbf6; }}
  .ac-num {{ flex:0 0 26px; height:26px; border-radius:7px; background:#fff; border:1px solid #e6e8ee;
             text-align:center; line-height:26px; font-weight:700; color:#6b7280; }}
  .ac-title {{ font-weight:700; font-size:14px; margin-bottom:5px; }}
  .ac-badge {{ font-size:11px; font-weight:600; padding:2px 8px; border-radius:5px; margin-left:8px; }}
  .ab-urgent {{ background:#fdecea; color:#e8543c; }}
  .ab-soon {{ background:#fef3da; color:#c4801a; }}
  .ab-scale {{ background:#e6f7ef; color:#0f9d6b; }}
  .ac-reason {{ color:#4b5563; line-height:1.6; }}
</style></head>
<body>
  <div class="head"><h1>{escape(title)}</h1></div>
  <div class="cards">
    <div class="card"><div class="big">{_nt(total_revenue)}</div><div class="lbl">本週總入帳</div></div>
    <div class="card green"><div class="big">{_signed_nt(total_net)}</div><div class="lbl">扣除所有成本後淨利</div></div>
    <div class="card green"><div class="big">{profitable}</div><div class="lbl">獲利 SKU（毛利率 &gt;50%）</div></div>
    <div class="card red"><div class="big">{losing}</div><div class="lbl">虧損 SKU（需立即處理）</div></div>
  </div>

  <div class="section-title">本週 SKU 獲利分析 <small>廣告費 · 退貨損失 · 折扣補貼全部計入</small></div>
  {summary_html}
  <table>
    <thead><tr><th>商品名稱</th><th class="num">銷量</th><th class="num">實收入帳</th>
      <th class="num">真實淨利</th><th>毛利率</th><th>AI 判斷</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>

  {'<div class="section-title">下週優先行動</div>' + ''.join(action_cards) if action_cards else ''}
</body></html>"""


def html_to_pdf(html: str, out_path: Path) -> Path:
    """Render an HTML string to a PDF file via headless Chromium (Playwright)."""
    from playwright.sync_api import sync_playwright

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_context().new_page()
            page.set_content(html, wait_until="networkidle")
            page.emulate_media(media="print")
            page.pdf(
                path=str(out_path),
                format="A4",
                print_background=True,
                margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
            )
        finally:
            browser.close()
    return out_path


def render_report_pdf(report: dict, out_path: Path, *, title: str = "AI 利潤健檢報告") -> Path:
    """Convenience: ProfitReport dict → PDF at out_path. Returns the path."""
    return html_to_pdf(render_report_html(report, title=title), out_path)
