# 利潤健檢 — 測試資料情境集

The flat CSVs in this folder (`shopee_sales_report.csv`, `product_cost.csv`,
`ads_discount.csv`, `order_return_refund.csv`) are the **original baseline** sample
used by the unit tests.

The `scenario_*/` subfolders are **5 self-contained datasets**, each tuned to
exercise a different profit-health pattern end-to-end. Every folder holds a full
CSV set whose filenames the upload classifier routes automatically
(`*sales*`→sales, `*cost*`→cost, `*ad*`/`*discount*`→ads, `*return*`/`*refund*`→returns).

To use one: in the UI's 利潤健檢 form, select **all** CSVs inside a scenario folder
at once and run. (Re)generate + self-verify the whole set with:

```bash
uv run python shopee/sample_data/_generate_scenarios.py
```

The flag thresholds being exercised live in `src/automation/tools/profit_calc_tool.py`
(最賺錢 = top-3 net profit · 假爆品 = units≥3 & margin<10% · 廣告吃利潤 = ad_spend>net ·
退貨異常 = ≥2 returns or rate≥20%).

| # | Folder | 情境 | What it triggers |
|---|---|---|---|
| 1 | `scenario_1_healthy/` | 健康獲利店 — 高毛利、廣告效率佳、無退貨 | 3× **最賺錢**, no warnings (clean baseline; returns file is header-only) |
| 2 | `scenario_2_ad_burn/` | 廣告燒錢店 — 多檔廣告花費 > 淨利、ROAS 偏低 | **廣告吃利潤** ×3 (incl. one with 0 ROAS), 1 healthy control |
| 3 | `scenario_3_return_crisis/` | 退貨危機店 — 多檔 ≥2 筆退貨、已退款侵蝕利潤 | **退貨異常** ×3 (incl. 退款申請中 not counted as realized refund) |
| 4 | `scenario_4_fake_hits/` | 假爆品店 — 高銷量但折扣/免運壓垮毛利 | **假爆品** ×2 (e.g. 15 units, −2.4% margin), 2 healthy controls |
| 5 | `scenario_5_new_seller_minimal/` | 新賣家簡易資料 — 只有銷售+成本兩份檔 | Optional-file-absent path (no ads/returns); all healthy |

### Notes on edge cases covered
- **不成立 (cancelled) orders** appear in scenarios 5 and are excluded from revenue/units.
- **退款申請中** (refund pending) in scenario 3 counts toward `return_count` but **not**
  the realized refund total — only **已退款** reduces net profit.
- **免運 + 賣家折扣** (scenario 4) flow through `蝦皮手續費` + `運費補貼-賣家負擔` exactly as
  the real Shopee export, so margins reflect true take-home.
- Scenario 1's `order_return_refund.csv` is intentionally **header-only** (a clean week)
  to test the empty-but-present optional file path.

> `_generate_scenarios.py` is the source of truth — it writes these folders and prints
> a per-SKU verification table. Edit the `SCENARIOS` dict there to tune economics.
