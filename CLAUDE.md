# CLAUDE.md

## Commands

```bash
uv sync                                              # install deps
uv run playwright install chromium                   # needed for form_fill

uv run uvicorn src.main:app --reload --port 8000     # dev server
kill -9 $(lsof -ti:8000)                             # kill port 8000

uv run pytest tests/unit tests/integration -v        # all tests
uv run pytest tests/unit/test_flow.py::test_name -v  # single test
uv run pytest tests/unit tests/integration -v -m "not e2e"  # skip e2e
```

## Architecture

```
POST /api/jobs           → create Job row (stores payload JSON)
POST /api/jobs/{id}/run  → create Run (pending), asyncio.create_task → 202
Background task          → executor.execute_run() → Flow → Crew → Tool(s)
GET /api/runs/{id}/stream → SSE, polls DB every 0.5 s until terminal status
```

| Layer | File(s) | Role |
|---|---|---|
| Executor | `src/automation/executor.py` | `_FLOW_MAP` dispatch, retry loop, `_update_run()` |
| Harness | `src/automation/harness/` | `provider.py` (LLM), `validator.py` (quality), `costs.py` (pricing) |
| Flows | `src/automation/flows/*_flow.py` | `crewai.Flow[StateModel]`; each calls `harness.provider.resolve()` |
| Crews | `src/automation/crews/*/crew.py` | Plain Python classes — **no `@CrewBase`** (see below) |
| Registry | `src/automation/registry.py` | asyncio task dict for run cancellation |
| UI | `ui/app.js` | `LLM_MODELS` dict drives the provider→model dropdown |

## Key Invariants

**No `@CrewBase` decorators.** `@CrewBase`, `@agent`, `@task`, `@crew` use a module-level memoize cache keyed by `id(self)`. CPython reuses addresses after GC → stale LLM instances on subsequent runs. Each crew is a plain class:

```python
class MyCrew:
    def __init__(self, llm=None): self._llm = llm
    def crew(self) -> Crew: ...  # build Agent/Task/Crew fresh each call
```

**LLM injection** — pass via constructor `MyCrew(llm=llm)`, never post-init.

**Flow state** — `llm_provider` and `llm_model` must be declared as Pydantic fields in the state model to survive `kickoff(inputs=...)`.

**DB migrations** — add new columns in `database.init_db()` as `ALTER TABLE ADD COLUMN` wrapped in try/except. Runs on startup, idempotent.

**Stats** — `get_stats()` does a single SQL pass; keep it that way.

## Adding a New Job Type

Touch exactly these 6 files:

1. `src/automation/executor.py` — add to `_FLOW_MAP`
2. `src/automation/flows/<name>_flow.py` — `Flow[StateModel]` subclass
3. `src/automation/crews/<name>_crew/` — YAML configs + `crew.py`
4. `src/routers/system.py` — add to `_CATALOG`
5. `ui/app.js` (+ `ui/index.html` fields) — add to the UI form
6. `src/settings_store.py` — add to `ALL_AUTOMATIONS` (**required or the job type is
   invisible in the UI and blocked server-side** by `is_automation_enabled` /
   `assert_can_run` — this list is the allowlist, not just docs)

**File-upload job types** (e.g. `profit_health_check`) — the UI POSTs files to `POST /api/uploads` (multipart, saved under `uploads/<uuid>/`), then creates the job with a small `{upload_id}` payload; the flow reads the files from disk. Keeps the payload JSON-only and re-runnable. See [doc/profit-health-check-design.md](doc/profit-health-check-design.md).

---

See [doc/dev-notes.md](doc/dev-notes.md) for PostgreSQL deployment, scalability roadmap, and deeper harness internals.
