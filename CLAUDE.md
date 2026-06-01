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

Touch exactly these 5 files:

1. `src/automation/executor.py` — add to `_FLOW_MAP`
2. `src/automation/flows/<name>_flow.py` — `Flow[StateModel]` subclass
3. `src/automation/crews/<name>_crew/` — YAML configs + `crew.py`
4. `src/routers/system.py` — add to `_CATALOG`
5. `ui/app.js` — add to the UI form

---

See [doc/dev-notes.md](doc/dev-notes.md) for PostgreSQL deployment, scalability roadmap, and deeper harness internals.
