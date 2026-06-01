# Dev Notes

Extended reference for topics that don't belong in the day-to-day CLAUDE.md.

---

## PostgreSQL (Production)

Set `DATABASE_URL=postgresql+psycopg2://user:pass@host/db` in `.env`. SQLModel/SQLAlchemy handles the dialect switch automatically.

```bash
uv add psycopg2-binary
```

The `ALTER TABLE` migrations in `init_db()` are SQLite-specific. For Postgres use `ADD COLUMN IF NOT EXISTS` instead.

---

## Harness Internals

### provider.py

Two functions:
- `normalize(provider, model)` — resolves `(provider, model)` strings to `(effective_provider, effective_model)` with no API call, no key check. Used by the executor for logging/metrics.
- `resolve(provider, model, temperature)` — creates a `crewai.LLM` instance; raises `OSError` if the API key env var is missing. Called by each flow's `execute_crew`.

`_CATALOG` is the single source of truth for supported providers and models.

### validator.py

`_CHECKS` dict maps job type → validation function. Called after every crew execution. On failure + retries remaining, the executor re-runs the flow and injects `previous_error` into the payload so the LLM can self-correct.

### costs.py

Pricing table keyed by bare model name (strips `gemini/` prefix). `estimate_cost(model, tokens_in, tokens_out)` returns USD float.

### tracker.py (removed)

`update_run_metrics()` was merged into `executor._update_run()` via `**metrics` kwargs so metrics and status are written in a single DB session.

---

## Scalability Roadmap

### Task queue

`asyncio.create_task` keeps all automation in-process. For horizontal scaling or crash resilience, migrate to ARQ (Redis-backed) or Dramatiq. The executor interface `execute_run(run_id, job_type, payload)` is already queue-friendly.

### Job scheduling

`Job.schedule` stores a cron expression (e.g. `"0 8 * * *"`) but no scheduler runs yet. Wire up APScheduler in the `lifespan` context (`src/main.py`) to poll for due jobs and call `execute_run`. The `JobCreate.schedule` field already exposes this via the API and UI.
