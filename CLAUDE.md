# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Install Playwright browser (required for form_fill automation)
uv run playwright install chromium

# Start dev server (auto-reload)
uv run uvicorn src.main:app --reload --port 8000

# Kill whatever is on port 8000
kill -9 $(lsof -ti:8000)

# Run all tests (unit + integration)
uv run pytest tests/unit tests/integration -v

# Run a single test file
uv run pytest tests/unit/test_flow.py -v

# Run a single test by name
uv run pytest tests/unit/test_flow.py::test_name -v

# Skip e2e tests (they require real API keys + browser)
uv run pytest tests/unit tests/integration -v -m "not e2e"
```

## Architecture

### Request lifecycle

```
POST /api/jobs        → create Job row (stores payload JSON)
POST /api/jobs/{id}/run → create Run row (status=pending), spawn asyncio.create_task
                          returns 202 immediately
Background task       → executor.execute_run() → harness → Flow → Crew → Tool(s)
GET /api/runs/{id}/stream → SSE, polls DB every 1s, yields diffs until terminal status
```

### Harness layer (`src/automation/harness/`)

The harness sits between the executor and CrewAI. It owns four concerns:

- **`provider.py`** — resolves `(provider, model)` strings to a `crewai.LLM` instance. Raises `EnvironmentError` if the required API key env var is missing. `_CATALOG` is the single source of truth for supported models.
- **`validator.py`** — per-job-type result quality checks (`_CHECKS` dict). Called after every crew execution; on failure + retries remaining, the executor re-runs the flow.
- **`costs.py`** — pricing table keyed by bare model name (strips `gemini/` prefix). Used to estimate USD cost from token counts.
- **`tracker.py`** — `update_run_metrics()` is now merged into `executor._update_run()` via `**metrics` kwargs, so metrics and status are written in a single DB session.

### Executor (`src/automation/executor.py`)

`_FLOW_MAP` dict drives dispatch — add a new automation type here plus its flow. The executor:
1. Pops `llm_provider`, `llm_model`, `max_retries` from payload before passing to flows
2. Passes `effective_provider`/`effective_model` through flow state (not as instance attrs — CrewAI Flow doesn't preserve arbitrary attrs across `kickoff()`)
3. Retries up to `max_retries` (default 1) on validation failure or exception
4. Writes all metrics + status in a single `_update_run()` call at the end

### Flows (`src/automation/flows/`)

Each flow is a `crewai.Flow[StateModel]` subclass. The state model carries `llm_provider` and `llm_model` as plain strings. Each `execute_crew` method calls `harness.provider.resolve()` to build the LLM and passes it to the crew constructor.

Shared helper: `flows/utils.py::extract_usage()` — extract token counts from `CrewOutput.usage_metrics`.

### Crews (`src/automation/crews/*/crew.py`)

**Do not use `@CrewBase`, `@agent`, `@task`, or `@crew` decorators.** These decorators use a module-level memoize cache keyed by `id(self)`. CPython reuses memory addresses after GC, causing stale OpenAI agents to be returned for subsequent runs on different providers. Each crew is a plain Python class:
- YAML configs loaded **once at module level** into `_AGENTS` and `_TASKS`
- `__init__(self, llm=None)` stores the LLM
- `crew()` builds `Agent`, `Task`, `Crew` objects directly and returns the `Crew`

### Database

SQLite via SQLModel. Schema migrations are `ALTER TABLE ADD COLUMN` statements in `database.init_db()` — add new columns there. Run table harness columns: `llm_provider`, `llm_model`, `tokens_in`, `tokens_out`, `cost_usd`, `retry_count`. Job table has a `schedule` column (cron expression string, nullable).

**Production deployment (PostgreSQL)**: Set `DATABASE_URL=postgresql+psycopg2://user:pass@host/db` in `.env`. SQLModel/SQLAlchemy handles the dialect switch automatically. WAL mode (SQLite default for writes) is not needed with Postgres. Run `uv add psycopg2-binary` to install the driver. The `ALTER TABLE` migration DDL is SQLite-specific; for Postgres use `ADD COLUMN IF NOT EXISTS` instead.

### UI (`ui/`)

Single-page vanilla JS app, no build step. `LLM_MODELS` dict in `app.js` controls the provider→model dropdown. `updateModelOptions()` is called on provider change and on form reset. The UI modal injects `llm_provider` and `llm_model` into the job payload.

## Key invariants

- **LLM injection**: always pass via crew constructor `HNDigestCrew(llm=llm)`, never via post-init attribute assignment. The `@CrewBase` metaclass pre-builds agents during `__init__`, making post-init assignment too late.
- **Flow state**: `llm_provider`/`llm_model` must be declared as fields in each flow's state Pydantic model to survive `kickoff(inputs=...)` population.
- **DB migrations**: `init_db()` in `database.py` runs on startup and is idempotent — each `ALTER TABLE` is wrapped in a try/except that ignores "column already exists".
- **Stats endpoint**: `get_stats()` does a single pass over all runs; keep it that way to avoid N+1-style multi-pass patterns.
- **schedule field**: `Job.schedule` stores a cron expression (e.g. `"0 8 * * *"`). No scheduler runs yet — this field is reserved for future APScheduler integration. Expose it through `JobCreate.schedule` so the UI can persist it.

## Adding a new job type

To add a job type today you must touch these five places:
1. `src/automation/executor.py` — add entry to `_FLOW_MAP`
2. `src/automation/flows/` — create `<name>_flow.py` with `Flow[StateModel]` subclass
3. `src/automation/crews/<name>_crew/` — create crew package (YAML configs + `crew.py`)
4. `src/routers/system.py` — add entry to `_CATALOG`
5. `ui/app.js` — add job type to the UI form

A future registration-based approach (each flow module declares its own metadata) would reduce this to one or two files.

## Future scalability notes

- **Task queue**: `asyncio.create_task` keeps all automation in-process. For horizontal scaling or crash resilience, migrate to ARQ (Redis-backed) or Dramatiq. The executor interface (`execute_run(run_id, job_type, payload)`) is already queue-friendly.
- **Job scheduling**: `Job.schedule` (cron string) is persisted but not yet acted on. Wire up APScheduler in the `lifespan` context to poll for due jobs and call `execute_run`.
