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
| 2 | Report output | **JSON** (for now) |
| 3 | Language | **Traditional Chinese** |
| 4 | Schema handling | **Strict** to the 4 sample-file schemas (semantic adapter is a v2) |
| 5 | Analysis engine | **Multi-agent LLM crew** (validator → corrector → analyzer → advisor) |
| — | Math | **Deterministic `profit_calc` tool** for the analyzer agent — agent decides *what* to flag, Python does the *arithmetic* |

## Architecture

```
UI: pick 4 CSVs ──multipart──▶ POST /api/uploads ──▶ saves to uploads/<uuid>/, returns {upload_id}
UI: POST /api/jobs {job_type:"profit_health_check", payload:{upload_id}} ──▶ run (existing path)
Flow: read 4 CSVs from uploads/<uuid>/ ──▶ ProfitHealthCrew.kickoff(inputs={4 csv strings})
Crew (sequential): 驗證 ▶ 修正 ▶ 分析 ▶ 建議 ──▶ JSON report
```

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

### Phase 0 — Scaffolding & contracts
*Goal: lock the data contracts so later phases don't churn.*
- [ ] Decide the report JSON schema (the "Report JSON shape" above) and freeze field names.
- [ ] Define the `profit_calc` tool input/output shape (per-SKU metrics dict).
- [ ] Add `uploads/` to `.gitignore`.
- [ ] Register the job type string `profit_health_check` everywhere it's referenced.

**Done when:** schemas are written down; no code paths reference an undefined field.

### Phase 1 — Upload endpoint
*Files: `src/routers/uploads.py` (new), `src/main.py` (edit)*
- [ ] `POST /api/uploads` accepts 4 multipart `UploadFile`s: `sales`, `cost`, `ads`, `returns`.
- [ ] Require `sales` + `cost`; `ads` + `returns` optional.
- [ ] Validate `.csv` content-type/extension; size-cap each file (~2 MB) → `413` if over.
- [ ] Save to `uploads/<uuid>/{sales,cost,ads,returns}.csv`; return `{"upload_id": "<uuid>"}`.
- [ ] Register router in `main.py` (`include_router(uploads.router, prefix="/api")`).

**Test:** `curl -F` the 4 sample CSVs → assert `200` + a new `uploads/<uuid>/` dir with the files.
**Done when:** sample files upload and the dir is created; oversized/missing-required files rejected.

### Phase 2 — Flow skeleton (no crew yet)
*Files: `src/automation/flows/profit_health_flow.py` (new), `src/automation/executor.py` (edit)*
- [ ] `ProfitHealthState`: `upload_id` + mandatory `run_id, usage, llm_provider, llm_model, previous_error`.
- [ ] `@start() validate_payload`: resolve `upload_id` → read the CSVs from `uploads/<uuid>/`; raise on missing dir/required files.
- [ ] `@listen execute_crew`: for now return a stub dict (e.g. echo column counts) so the flow runs end-to-end.
- [ ] Add `_FLOW_MAP["profit_health_check"]` entry in `executor.py`.

**Test:** create a job with `{upload_id}` → run → run reaches `success` with the stub result.
**Done when:** the full create-job → run → result loop works against the upload from Phase 1.

### Phase 3 — Deterministic `profit_calc` tool
*Files: `src/automation/tools/profit_calc_tool.py` (new)*
- [ ] Parse the 4 CSVs strictly to the sample schemas (skip the `##` comment row in `ads_discount.csv`).
- [ ] Join on `商品SKU`; compute per-SKU 銷售額 / 成本 (數量 × 單位總成本) / 廣告花費 / 退款 / 淨利 / 淨利率 / ROAS.
- [ ] Derive flag candidates: 最賺錢, 假爆品 (高銷量低/負淨利), 廣告吃利潤 (廣告花費 > 淨利), 退貨異常.
- [ ] Return a compact metrics dict matching the Phase 0 contract.
- [ ] **Unit tests** against `shopee/sample_data/` with hand-checked expected numbers.

**Test:** `pytest tests/unit/test_profit_calc.py` — numbers match a manual spreadsheet on the sample data.
**Done when:** arithmetic is correct and deterministic for the sample data.

### Phase 4 — Multi-agent crew
*Files: `src/automation/crews/profit_health_crew/` (crew.py + config/agents.yaml + config/tasks.yaml), `src/automation/flows/profit_health_flow.py` (wire crew), `src/automation/harness/validator.py` (edit)*
- [ ] `agents.yaml`: 資料驗證員, 資料修正員, 利潤分析師, 行動建議員 (Traditional Chinese role/goal/backstory).
- [ ] `tasks.yaml`: 4 tasks, `Process.sequential`, chained `context`; CSVs interpolated into task 1.
- [ ] Attach `profit_calc` tool to the 利潤分析師 agent only.
- [ ] `crew.py`: plain class (no `@CrewBase`), build Agent/Task/Crew fresh, accept `llm=` in constructor.
- [ ] Final task `expected_output` = the report JSON shape; flow returns it raw.
- [ ] Replace the Phase 2 stub: `execute_crew` resolves the LLM and runs the crew.
- [ ] Add the `profit_health_check` check in `validator.py`.

**Test:** run against sample data with a real provider → JSON parses, contains `skus`/`flags`/`action_items`, numbers match Phase 3.
**Done when:** a full run produces a valid Traditional-Chinese JSON report; validation passes.

### Phase 5 — UI
*Files: `ui/app.js` (edit), `src/routers/system.py` (edit)*
- [ ] New job type in the run form; 4 `<input type="file" accept=".csv">` fields.
- [ ] Submit handler: **two-step** — `await POST /api/uploads` (FormData) → then create job with `{upload_id}`.
- [ ] Client-side guards: require sales + cost; surface size/format errors via `showToast`.
- [ ] Add `FLOW_STEPS` + `TYPE_META` entries so the run page shows the 4 crew steps.
- [ ] Add catalog entries (4 agents, 1 crew, 1 flow, 1 tool) in `system.py` for the System page.
- [ ] *(optional)* nicer rendering of the report JSON in the run detail.

**Test:** end-to-end in the browser — pick the 4 sample CSVs, run, see the JSON report and progress steps.
**Done when:** a non-technical user can upload and get a report without touching the API.

### Cross-cutting / acceptance
- [ ] `uv run pytest tests/unit tests/integration -v -m "not e2e"` green.
- [ ] Manual e2e against `shopee/sample_data/` produces a sensible report (BT-EAR-A1-WHT should surface as 退貨異常; ad-heavy SKUs as 廣告吃利潤).
- [ ] No `@CrewBase`; LLM injected via constructor; state fields declared as Pydantic fields (project invariants).
- [ ] Update `CLAUDE.md` "Adding a New Job Type" note if any new step is introduced (e.g. the upload endpoint).

### Suggested commits / PRs
1. `feat(uploads): add POST /api/uploads multipart endpoint` (Phase 1)
2. `feat(profit): add profit_health_check flow skeleton + executor wiring` (Phase 2)
3. `feat(profit): add deterministic profit_calc tool + unit tests` (Phase 3)
4. `feat(profit): add profit_health_crew (validator→corrector→analyzer→advisor)` (Phase 4)
5. `feat(ui): add 利潤健檢 upload form + system catalog entries` (Phase 5)
