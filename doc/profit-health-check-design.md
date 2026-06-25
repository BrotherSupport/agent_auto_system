# 利潤健檢 Copilot — Design & Implementation Plan

A new automation job type (`profit_health_check`) for the Agent Auto System. A Shopee
seller uploads 4 CSV files; a chain of LLM agent nodes validates, corrects, analyzes,
and advises; the system returns a profit & ops health report as JSON (Traditional Chinese).

Source concept: [`shopee/plan/draft.txt`](../shopee/plan/draft.txt) (第一名：AI 利潤與營運健檢 Copilot).
Sample data: [`shopee/sample_data/`](../shopee/sample_data).

## Decisions (locked)

| # | Decision | Choice |
|---|---|---|
| 1 | CSV delivery | **Upload endpoint** (`POST /api/uploads`, multipart) — not inline-in-payload |
| 1b | File selection | **Single multi-file upload, auto-classified by filename** (v2) — seller drops all CSVs in one `files` field; the server routes each by keyword (`cost`→cost, `sales`→sales, `ad`/`廣告`→ads, `return`/`refund`→returns). No per-slot pickers. See `_classify` / `_ROLE_KEYWORDS` in `src/routers/uploads.py`. |
| 2 | Report output | **JSON + PDF** (v2) — the crew still returns JSON; a deterministic renderer then prints it to PDF (json → html → pdf), served at `GET /api/runs/{id}/report.pdf`. `pdf_url` is injected into the result. |
| 3 | Language | **Traditional Chinese** |
| 4 | Schema handling | **Strict** to the 4 sample-file schemas (semantic adapter is a v2) |
| 5 | Analysis engine | **Multi-agent LLM crew** (validator → corrector → analyzer → advisor) |
| — | Math + rendering | **Deterministic** — `profit_calc` tool does the arithmetic; `report_render` does the layout/PDF. Agents decide *what* to flag and *what* to advise; Python does the numbers and the presentation. |

## Architecture

```
UI: pick all CSVs ─multipart(files[])─▶ POST /api/uploads ─▶ classify each by filename,
                                                              save to uploads/<uuid>/, return {upload_id, classified}
UI: POST /api/jobs {job_type:"profit_health_check", payload:{upload_id}} ──▶ run (existing path)
Flow validate_payload: read CSVs from uploads/<uuid>/ ──▶ ProfitHealthCrew.kickoff(inputs={csv strings})
Crew (sequential): 驗證 ▶ 修正 ▶ 分析 ▶ 建議 ──▶ JSON report
Flow render_pdf: report JSON ─▶ render_report_html ─▶ html_to_pdf (headless Chromium) ─▶ reports/<run_id>.pdf
                  inject pdf_url into result (fail-soft: render errors never fail the run)
```

### v2 renderer (`src/automation/report_render.py`)

`render_report_html(report)` builds a self-contained HTML page mirroring the on-screen
demo — four summary cards (本週總入帳 / 淨利 / 獲利 SKU / 虧損 SKU), a per-SKU table sorted by
margin with bars + AI 判斷 chips, and a prioritised 下週優先行動 list (recommendations →
priority badges). `html_to_pdf` prints it with the Playwright Chromium already vendored
for `form_fill` (no new dependency). Kept out of the crew because rendering is pure
presentation — same input → same bytes.

Why an upload endpoint rather than inlining CSV text in the JSON payload: the seller
data can be large, and an explicit upload step keeps the job payload small and the
files re-readable. Trade-off: re-runs depend on the uploaded files still existing on
disk under `uploads/<uuid>/` (acceptable for the MVP; persisted under the project).

## Agent nodes (sequential CrewAI crew)

CSVs are embedded into the first task via `{sales_csv}` / `{cost_csv}` / `{ads_csv}` /
`{returns_csv}` interpolation. Each agent's output becomes `context` for the next.

| # | Agent (zh) | Role | Output |
|---|---|---|---|
| 1 | **資料驗證員** Data Validator | Check the 4 files match the expected sample schemas (columns, types, SKU coverage across files); list anomalies / missing data | `validation: {ok, issues[]}` |
| 2 | **資料修正員** Data Corrector | Normalize / repair: coerce numbers, reconcile SKU mismatches, drop unusable rows, note what changed | `corrections: {applied[], dropped[]}` |
| 3 | **利潤分析師** Profit Analyzer | Per-SKU 銷售額 / 成本 / 廣告 / 退款 / 淨利 / 淨利率; flag 最賺錢 · 假爆品 · 廣告吃利潤 · 退貨異常. Uses the `profit_calc` tool for all arithmetic | `skus[]`, `flags{}` |
| 4 | **行動建議員** Action Advisor | 停賣 / 漲價 / 補貨 / 改圖 / 改組合 建議 + 下週優先行動清單 | `recommendations[]`, `action_items[]` |

The final task emits the complete JSON report, matching the 6 outputs in `draft.txt:14-19`.

### Why the analyzer keeps a deterministic tool

A profit tool that hallucinates numbers is dangerous (see
[`shopee/system_design.md`](../shopee/system_design.md), Approach 5 cons). The
`profit_calc` tool runs the arithmetic in Python so numbers are trustworthy; the agent
still decides *what* counts as a 假爆品 or 廣告吃利潤 SKU. Analysis stays LLM-driven;
only the math is deterministic.

## File-by-file change map

### New files
1. `src/routers/uploads.py` — `POST /api/uploads` (FastAPI `UploadFile`, multipart).
   Validates the 4 CSVs, size-caps each (~2 MB), saves to
   `uploads/<uuid>/{sales,cost,ads,returns}.csv`, returns `{upload_id}`.
   `sales` + `cost` required; `ads` + `returns` optional.
2. `src/automation/flows/profit_health_flow.py` — `ProfitHealthState` (fields:
   `upload_id` + the mandatory `run_id, usage, llm_provider, llm_model, previous_error`).
   `@start()` resolves `upload_id` → reads CSVs from disk; `@listen` resolves the LLM,
   runs `ProfitHealthCrew`.
3. `src/automation/crews/profit_health_crew/crew.py` + `config/agents.yaml` (4 agents)
   + `config/tasks.yaml` (4 tasks, `Process.sequential`, chained `context`). Plain
   class, no `@CrewBase` (per project invariant).
4. `src/automation/tools/profit_calc_tool.py` — deterministic per-SKU math for agent 3.

### Edits
5. `src/main.py` (~lines 13, 30) — import + `include_router(uploads.router, prefix="/api")`.
6. `src/automation/executor.py:68` — add to `_FLOW_MAP`:
   `"profit_health_check": ("src.automation.flows.profit_health_flow", "ProfitHealthFlow", "解析 CSV，計算利潤...")`.
7. `src/automation/harness/validator.py:12` — add a `profit_health_check` check, e.g.
   `bool(r.get("skus") or r.get("action_items"))`.
8. `src/routers/system.py:17` — catalog entries (4 agents, 1 crew, 1 flow, 1 tool) for
   the System page.
9. `ui/app.js` — new job type; form with 4 `<input type="file">`; submit handler does
   the **two-step** flow (await `/api/uploads` → then create job with `{upload_id}`);
   add `FLOW_STEPS` / `TYPE_META` entries for the run page.

## MVP constraints baked in
- **Strict schemas:** analyzer targets the exact sample headers (`賣家實際入帳`,
  `單位總成本`, `商品SKU`, …) and skips the `##` comment row in `ads_discount.csv`.
  Semantic schema adaptation is a v2.
- **JSON output:** the final task's `expected_output` is a fixed JSON shape; the flow
  returns it raw and the executor's `_parse_result` handles fences/parsing.
- **uploads/ lifecycle:** files persisted under the project so re-runs work; add
  `uploads/` to `.gitignore`.

## Expected CSV schemas (sample data, strict)

| File | Key columns (subset) |
|---|---|
| `shopee_sales_report.csv` | 訂單編號, 訂單狀態, 商品SKU, 數量, 商品原價(NTD), 賣家實際入帳(NTD), 蝦皮手續費(NTD) |
| `product_cost.csv` | 商品SKU, 單位總成本(NTD) |
| `ads_discount.csv` | (skip `##` row) 商品SKU, 廣告花費(NTD), 廣告銷售額(NTD), ROAS |
| `order_return_refund.csv` | 訂單編號, 商品SKU, 退款金額(NTD), 退貨/退款狀態 |

## Report JSON shape (draft)

```json
{
  "summary": "本週營運健檢摘要…",
  "skus": [
    {"sku": "...", "name": "...", "revenue": 0, "cost": 0,
     "ad_spend": 0, "refunds": 0, "net_profit": 0, "margin_pct": 0,
     "flags": ["假爆品", "廣告吃利潤"]}
  ],
  "flags": {
    "most_profitable": ["..."],
    "fake_hits": ["..."],
    "ad_eats_profit": ["..."],
    "high_return_rate": ["..."]
  },
  "recommendations": [
    {"sku": "...", "action": "漲價", "reason": "..."}
  ],
  "action_items": ["下週優先：..."],
  "validation": {"ok": true, "issues": []}
}
```

---

## Implementation Plan

Five phases, back-end first so each layer is testable before the UI exists. Phases 1–4
can be built and merged independently; Phase 5 wires the UI on top. The `profit_calc`
tool (Phase 3) is the only piece with non-trivial logic — build and unit-test it first
within the phase.

### Phase 0 — Scaffolding & contracts ✅
*Goal: lock the data contracts so later phases don't churn.*
- [x] Decide the report JSON schema and freeze field names → `ProfitReport` in `src/automation/profit_health_schema.py`.
- [x] Define the `profit_calc` tool input/output shape → `ProfitCalcInput` / `ProfitCalcResult` (+ shared `SkuMetrics`, `ProfitFlags`).
- [x] Add `uploads/` to `.gitignore`.
- [x] Register the job type string → `JOB_TYPE = "profit_health_check"` constant; strict CSV column lists + zh flag labels also live in the schema module. Later phases import from here.

**Done when:** schemas are written down; no code paths reference an undefined field. ✅
(`src/automation/profit_health_schema.py` imports and constructs cleanly.)

### Phase 1 — Upload endpoint ✅
*Files: `src/routers/uploads.py` (new), `src/main.py` (edit)*
- [x] `POST /api/uploads` accepts 4 multipart `UploadFile`s: `sales`, `cost`, `ads`, `returns`.
- [x] Require `sales` + `cost` (`File(...)` → `422` if missing); `ads` + `returns` optional.
- [x] Validate `.csv` extension (`400`); reject empty (`400`); size-cap each file at 2 MB (`413`).
- [x] Save to `uploads/<uuid>/{sales,cost,ads,returns}.csv`; return `{"upload_id", "files"}` with `201`.
- [x] Register router in `main.py` (`include_router(uploads.router, prefix="/api")`).

**Test:** TestClient posts the 4 sample CSVs → `201` + a new `uploads/<uuid>/` dir with the files;
error cases verified (missing→422, non-csv→400, oversize→413). Full suite green (218 passed).
**Done when:** sample files upload and the dir is created; oversized/missing-required files rejected. ✅
(Note: returns `201 Created` to match the existing `POST /jobs` convention, not `200`.)

### Phase 2 — Flow skeleton (no crew yet) ✅
*Files: `src/automation/flows/profit_health_flow.py` (new), `src/automation/executor.py` (edit)*
- [x] `ProfitHealthState`: `upload_id` + loaded CSV fields + mandatory `run_id, usage, llm_provider, llm_model, previous_error`.
- [x] `@start() validate_payload`: resolve `upload_id` → read CSVs from `uploads/<uuid>/`; raise on missing dir / missing required `sales.csv`+`cost.csv`.
- [x] `@listen execute_crew`: stub returns `{stub, summary, files:{rows,cols}}` (skips the `##` row in ads) so the flow runs end-to-end.
- [x] Add `_FLOW_MAP["profit_health_check"]` entry in `executor.py`.

**Test:** upload sample CSVs → create job `{upload_id}` → `execute_run` → `success`; stub counts
correct (sales 49×18, cost 10×7, ads 18×12, returns 5×9). Bad `upload_id` → `failed` with clear error. Suite green (218).
**Done when:** the full create-job → run → result loop works against the upload from Phase 1. ✅

### Phase 3 — Deterministic `profit_calc` tool ✅
*Files: `src/automation/tools/profit_calc_tool.py` (new), `src/automation/profit_health_schema.py` (edit)*
- [x] Parse the 4 CSVs strictly to the sample schemas; ads parser reads the 廣告 block only (stops before the 折扣 block).
- [x] Join on `商品SKU`; compute per-SKU 銷售額 / 成本 (數量 × 單位總成本) / 廣告花費 / 退款 / 淨利 / 淨利率 / ROAS; exclude 不成立 orders.
- [x] Derive flags: 最賺錢 (top-N net), 假爆品 (units ≥ 3 & margin < 10%), 廣告吃利潤 (ad_spend > net), 退貨異常 (return_count ≥ 2 or rate ≥ 20%).
- [x] Return `ProfitCalcResult` (Phase 0 contract); added `return_count`/`return_rate` to `SkuMetrics` (backward-compatible refinement).
- [x] **12 unit tests** in `tests/unit/test_profit_calc.py` with hand-verified numbers + edge cases (cancelled orders, optional files, 折扣-block isolation).

**Test:** `pytest tests/unit/test_profit_calc.py` — 12 passed; numbers match manual calc
(e.g. CHG-WL-15W net 2160, CASE-IP15-BLK 假爆品 @ 5.5% margin, BT-EAR 3 returns). Full suite 230 passed.
**Done when:** arithmetic is correct and deterministic for the sample data. ✅

### Phase 4 — Multi-agent crew ✅
*Files: `src/automation/crews/profit_health_crew/` (crew.py + config/agents.yaml + config/tasks.yaml), `src/automation/flows/profit_health_flow.py` (wire crew), `src/automation/tools/profit_calc_tool.py` (upload_id mode), `src/automation/harness/validator.py` (edit)*
- [x] `agents.yaml`: 資料驗證員, 資料修正員, 利潤分析師, 行動建議員 (Traditional Chinese).
- [x] `tasks.yaml`: 4 tasks, `Process.sequential`, chained `context`; CSVs interpolated into the validate task.
- [x] Attach `profit_calc` to the 利潤分析師 only. **Tool now takes `upload_id`** (reads files itself) so the LLM never copies CSV rows into a tool call.
- [x] `crew.py`: plain class (no `@CrewBase`), builds Agent/Task/Crew fresh, `llm=` via constructor.
- [x] Final task `expected_output` = the full report shape (keys described in prose, no literal braces — CrewAI `.format()` safe); flow returns it raw.
- [x] Replaced the Phase 2 stub: `execute_crew` resolves the LLM (temp 0.2) and runs the crew.
- [x] Added `profit_health_check` check in `validator.py`.

**Test:** live run against sample data (openai/gpt-4o-mini) → `success`; report has all 6 keys,
Traditional Chinese; analyzer numbers match Phase 3 exactly (CHG-WL-15W net 2160, CASE-IP15-BLK 5.49%
margin → 假爆品); recommendations sensible (停賣 BAG-WATER-L, 改圖 BT-EAR, 漲價 CABLE-MAG). Full suite 230 passed.
**Done when:** a full run produces a valid Traditional-Chinese JSON report; validation passes. ✅
(Note: `tokens: 0` — `extract_usage` reads `usage_metrics`, but CrewOutput exposes `token_usage`;
pre-existing across all flows, not introduced here.)

### Phase 5 — UI ✅
*Files: `ui/index.html` (edit), `ui/app.js` (edit), `src/routers/system.py` (edit), `src/automation/crews/profit_health_crew/crew.py` (task_callback), `src/automation/flows/profit_health_flow.py` (pass run_id)*
- [x] New 利潤健檢 type card + `fields-profit_health_check` group with 4 `<input type="file" accept=".csv">` (sales/cost required, ads/returns optional).
- [x] Submit handler: **two-step** — `await fetch('/api/uploads', FormData)` → then create job with `{upload_id}`.
- [x] Client-side guards: require sales + cost; per-file 2 MB check; upload errors surfaced via `showToast`.
- [x] Added `ALL_TYPES`, `TYPE_META` (chip 利潤健檢), `AUTO_CATALOG`, and `FLOW_STEPS` (Start→Load→驗證→修正→分析→建議→QA→Done).
- [x] Per-agent progress: crew `task_callback` logs each agent's completion (run page lights up all 4 nodes).
- [x] Catalog entries in `system.py`: 4 agents, 1 tool (profit_calc), 1 crew, 1 flow.
- [ ] *(optional, deferred)* nicer rendering of the report JSON in the run detail — JSON viewer already shows it.

**Test:** simulated UI path (upload → create job → run) → `success`; all 4 per-agent logs fire
matching FLOW_STEPS triggers; `/api/system` returns the new entries; `node --check ui/app.js` clean; suite 230 passed.
**Done when:** a non-technical user can upload and get a report without touching the API. ✅

### Cross-cutting / acceptance ✅
- [x] `uv run pytest tests/unit tests/integration -m "not e2e"` green (230 passed).
- [x] Live e2e against `shopee/sample_data/` produces a sensible report (BT-EAR-A1-WHT → 退貨異常; CABLE-MAG-2M / CASE-IP15-BLK → 廣告吃利潤; analyzer numbers match the deterministic tool).
- [x] No `@CrewBase`; LLM injected via constructor; state fields declared as Pydantic fields (project invariants honored).
- [x] Updated `CLAUDE.md` "Adding a New Job Type" with the file-upload note (POST /api/uploads → payload `{upload_id}`).

### Suggested commits / PRs
1. `feat(uploads): add POST /api/uploads multipart endpoint` (Phase 1)
2. `feat(profit): add profit_health_check flow skeleton + executor wiring` (Phase 2)
3. `feat(profit): add deterministic profit_calc tool + unit tests` (Phase 3)
4. `feat(profit): add profit_health_crew (validator→corrector→analyzer→advisor)` (Phase 4)
5. `feat(ui): add 利潤健檢 upload form + system catalog entries` (Phase 5)
