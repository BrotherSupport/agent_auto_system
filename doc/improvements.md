# Improvement Opportunities

> Audit date: 2026-05-27  
> Scope: code quality, AI/LLM layer, reliability, performance, security, testing, observability, architecture, UI/UX, tooling

---

## 1. Code Quality

### 1.1 Dead code — `tracker.py`
`src/automation/harness/tracker.py::update_run_metrics()` is never called. CLAUDE.md confirms its logic was merged into `executor._update_run()`. The file should be deleted to avoid confusion.

### 1.2 Redundant `_is_app_failure` vs `validator.validate`
Both `executor._is_app_failure()` and `harness/validator.py::validate()` check `"error" in result`. The duplication means a job type could have subtly different failure semantics depending on which path evaluates first. Consolidate the "is this a failure?" logic entirely into `validate()`.

### 1.3 `validate_payload` boilerplate in every flow
All five flows share the exact same `@start() def validate_payload` pattern: build a list of missing fields, raise `ValueError`, append a log entry. This is a strong candidate for a shared base class or a small helper that flows can call:

```python
class BaseFlow(Flow):
    def _check_required(self, *fields):
        missing = [f for f in fields if not getattr(self.state, f, "")]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")
```

### 1.4 `EmailSenderState` missing `llm_provider`/`llm_model` fields
Every other flow state declares `llm_provider: str = ""` and `llm_model: str = ""` so the executor can write them back. `EmailSenderState` omits them. If a user passes those fields in the payload they are silently dropped rather than stored.

### 1.5 `HNFetchInput` has no field-level validation
`HNFetchInput.limit: int = 5` has no `Field(ge=1, le=10)` constraint. The bound is enforced in the flow's `validate_payload` but not at the tool input level, so calling the tool directly bypasses it.

### 1.6 Inconsistent resolution path — `resolve_llm` called in both executor and flows
`executor.execute_run` calls `resolve_llm` once to get the effective provider/model (for logging and metrics). Each flow's `execute_crew` then calls `resolve_llm` again internally. Two LLM instances are created per run. One call site would be cleaner — pass the already-resolved LLM into the flow rather than re-resolving it inside.

---

## 2. AI / LLM Layer

### 2.1 No prompt caching
Anthropic's cache-control API and OpenAI's semantic caching can reduce costs by 50–90% for repeated runs with the same agent system prompts. None of the crews use prompt caching. For HN digest (same system prompt every run), this is a quick win.

### 2.2 No temperature control
`LLM(model=..., api_key=...)` uses provider defaults (usually ~1.0). For deterministic tasks (form fill, email send), `temperature=0` would reduce hallucination. For generative tasks (digest, X profile summary), a moderate value (0.3–0.7) could be explicitly set per crew type.

### 2.3 No structured output enforcement
Flows rely on the LLM returning valid JSON inside its raw text output. If the model adds a preamble or explanation, `json.loads()` fails and falls back to `{"message": raw_text}`, which then fails validation. Using CrewAI's `output_pydantic` or LiteLLM's JSON mode would make output parsing deterministic.

### 2.4 Retry logic doesn't tell the LLM what went wrong
On validation failure, the executor re-runs the entire flow with the same inputs. The LLM has no idea why it is being retried. Injecting the validation reason into the retry inputs (e.g. `"previous_error": vr.reason`) would let the LLM correct itself.

### 2.5 All crews are single-agent
Every crew has exactly one agent. For richer tasks, multi-agent patterns could improve quality:
- **HN Digest**: fetcher agent + analyst/writer agent
- **Form Fill**: inspector agent + submitter/verifier agent
- **Web Scraper**: fetcher agent + summarizer agent

### 2.6 No agent memory
CrewAI supports short-term, long-term, and entity memory (`memory=True` on `Crew`). Long-term memory would be valuable for the HN digest crew — it could track which stories it has already covered and avoid repetition across runs.

### 2.7 Gemini 3.x model names are unverified
`provider.py` lists `gemini-3.5-flash`, `gemini-3.1-flash-lite`, `gemini-3-flash-preview`. As of 2026-05, Gemini public API only exposes 2.x models. These names should be verified against the Gemini API before advertising them in the UI. Stale/wrong model names will produce `EnvironmentError` or API 404s at runtime.

### 2.8 No fallback provider
If the configured provider's API key is missing or the API returns an error, the run fails immediately. A provider fallback chain (try primary → try secondary) would improve resilience for production deployments.

---

## 3. Reliability & Error Handling

### 3.1 Stale `running` runs after server restart
When the server restarts mid-run, any in-flight `asyncio` tasks are cancelled but the DB rows stay at `status="running"` forever. A startup reconciliation pass in `init_db()` (or a `lifespan` hook) should detect and mark stale running rows as `failed`.

### 3.2 `append_log` silently swallows all DB errors
If the DB write in `progress.py::append_log` fails, the exception is caught by the caller or swallowed. Lost log entries make debugging hard. At minimum, `logging.warning(...)` should record the failure.

### 3.3 `GmailSendTool` doesn't handle SMTP exceptions
If `smtplib.SMTP` connection or login fails, the exception propagates raw. Wrapping in `try/except` and returning `{"sent": False, "error": ...}` would be consistent with the success path and avoid ugly tracebacks in the run log.

### 3.4 `WebScraperTool` has no response size limit
`urllib.urlopen(...).read()` will buffer the entire response. A 500 MB page or a tarpit server could exhaust memory or block a thread indefinitely. Add a `maxsize` read cap and a `Content-Length` check.

### 3.5 X Scraper nitter instance list is hardcoded
Public nitter instances go offline frequently. Hardcoding them in source means a code change + deploy is required to update the list. Move to `NITTER_INSTANCES` env var (comma-separated) with the current list as the fallback default.

### 3.6 HN tool fetches stories serially
With `limit=10`, the tool makes 11 sequential HTTP calls. Using `concurrent.futures.ThreadPoolExecutor` (or `asyncio.gather` via `asyncio.to_thread`) would reduce wall-clock time from ~10 s to ~1 s.

### 3.7 No job cancellation
Once `asyncio.create_task` fires, there is no way to cancel a running job from the UI or API. Adding a `DELETE /runs/{id}` path that also cancels the underlying task (via a task registry dict keyed by `run_id`) would enable this.

---

## 4. Performance

### 4.1 `append_log` is one DB write per log line
Every `append_log(run_id, msg)` opens a session, reads the run, appends to a JSON array, and commits. A flow with 8 steps does 8 separate round-trips. Options:
- Buffer logs in memory and flush in a single write at the end of each flow step.
- Use a separate `RunLog` table with one row per entry (avoids the read-modify-write pattern).

### 4.2 `get_stats` loads all runs into memory
`session.exec(select(Run)).all()` fetches every run row. With thousands of historical runs, this becomes slow and memory-heavy. Replace with SQL aggregation (`COUNT`, `SUM`, `AVG`, `GROUP BY`) to compute stats server-side.

### 4.3 SSE stream polls DB every 1 second
`stream_run` sleeps 1 s between polls. For short-lived runs (< 2 s), clients see stale status for up to 1 s. An `asyncio.Queue` per run that the executor writes to directly would allow sub-second latency with zero polling.

### 4.4 No database indexes
Frequently queried columns (`Run.job_id`, `Run.status`, `Run.started_at`) have no explicit indexes. As the run table grows, queries in `list_runs`, `get_stats`, and `bulk_delete_runs` will do full table scans.

```python
# example: add in init_db()
conn.execute(text("CREATE INDEX IF NOT EXISTS ix_run_job_id ON run(job_id)"))
conn.execute(text("CREATE INDEX IF NOT EXISTS ix_run_status ON run(status)"))
conn.execute(text("CREATE INDEX IF NOT EXISTS ix_run_started_at ON run(started_at)"))
```

---

## 5. Security

### 5.1 No authentication
The entire API is unauthenticated. Any client on the network can create jobs, read all run results (which may contain scraped data or sent email contents), and trigger new runs that consume LLM credits. Add at minimum a static API key check via `Authorization: Bearer <token>` header, or HTTP Basic Auth behind a reverse proxy.

### 5.2 SSRF via `WebScraperTool`
`WebScraperTool._run(url)` makes an outbound request to any URL. An attacker could pass `http://169.254.169.254/latest/meta-data/` (AWS metadata) or internal network addresses. Add a URL allowlist or blocklist for RFC-1918 / link-local ranges.

### 5.3 No rate limiting
The `POST /api/jobs/{id}/run` endpoint has no rate limiting. A client could flood run creation and exhaust LLM budget or overload the database. Add per-IP rate limiting (e.g. `slowapi` middleware).

### 5.4 HTML injection in email body
`GmailSendTool` sends the body as HTML if `"<" in body`. A user-controlled body could inject arbitrary HTML/CSS into emails. Since the tool is called with LLM-generated content, this is a low-severity risk, but sanitising the body with `bleach` or restricting to a whitelist of tags would be safer.

### 5.5 No startup validation of required env vars
The app starts successfully with no API keys configured. The `EnvironmentError` for missing keys only fires when a run actually executes. A startup check (warn/log which providers are configured) would surface misconfigurations immediately.

---

## 6. Testing

### 6.1 No tests for executor retry logic
The retry loop in `executor.execute_run` (validation fail → retry → eventual success/fail, exception path) has no unit tests. This is the most complex orchestration code in the project.

### 6.2 No tests for `harness/` modules
`validator.py`, `costs.py`, and `provider.py` have zero test coverage. The `_CHECKS` dict dispatch and the `estimate_cost` calculation are easy to unit-test and likely to break silently if model names change.

### 6.3 No tests for `x_scraper_flow` or `hn_digest_flow`
These two flows follow the same pattern as the tested flows but are not covered. They should have at minimum the same three test cases as `test_flow.py` (empty inputs, missing required field, correct crew invocation).

### 6.4 Integration tests don't assert on run outcomes
`tests/integration/test_runs_api.py` tests the API surface but doesn't assert that a triggered run actually transitions to `success`/`failed`. An integration test that patches the executor and checks the final status would give higher confidence.

### 6.5 Test coverage tooling not configured
`pyproject.toml` has no `pytest-cov` or coverage configuration. Add:
```toml
[tool.pytest.ini_options]
addopts = "--cov=src --cov-report=term-missing"
```

---

## 7. Observability

### 7.1 No structured application logging
The server uses no Python `logging` calls. Only CrewAI's `verbose=False` stdout output and the DB-backed `append_log` exist. Add `logging.getLogger(__name__)` calls in the executor, harness, and routers to emit structured logs for errors and key lifecycle events.

### 7.2 No health-check detail
`GET /health` returns `{"status": "ok"}` unconditionally. A richer check that tests DB connectivity and reports which LLM providers are configured (keys present vs missing) would make it useful for readiness probes.

### 7.3 No Prometheus/metrics endpoint
`GET /stats` returns aggregate stats from the DB but is not Prometheus-compatible. Adding `prometheus-fastapi-instrumentator` would expose `/metrics` for Grafana dashboards without extra code.

---

## 8. Architecture & Scalability

### 8.1 SQLite under concurrent writes
SQLite's WAL mode handles concurrent reads well, but concurrent writes serialize. Multiple simultaneous long-running crews will contend on the DB. `DATABASE_URL` already supports swapping to PostgreSQL — documenting this as the path for production deployments and testing it would be valuable.

### 8.2 In-process background tasks
`asyncio.create_task` keeps all automation inside the FastAPI process. Crashes lose in-flight runs. A lightweight task queue (e.g. `ARQ` with Redis, or `Dramatiq`) would:
- Persist jobs across server restarts
- Enable horizontal scaling (multiple workers)
- Provide built-in retry with backoff

### 8.3 No job scheduling / cron
There is no way to schedule a job to run in the future or on a recurring schedule. Adding a `schedule` field to `Job` (cron expression or datetime) and a background scheduler (APScheduler) would unlock automated recurring tasks (e.g. daily HN digest email).

### 8.4 Adding a new job type requires 5+ file changes
To add a job type today you must edit: `executor._FLOW_MAP`, create a new `flows/` file, a new `crews/` package, `system.py`'s `_CATALOG`, and `ui/app.js`. A registration-based approach (each flow module declares its metadata) would reduce this to one or two files.

---

## 9. UI / UX

### 9.1 No auto-open stream after triggering a run
After clicking "Run Job," the user is taken to the Runs tab, but must manually click on the new run to open its log stream. Auto-opening the stream for the most recently triggered run would improve the experience.

### 9.2 No "Retry" button on failed runs
To re-run a failed job, the user must navigate to the Jobs tab, find the job, and click Run again. A "Retry" button directly on the failed run row would be much faster.

### 9.3 Runs list has no pagination UI
The API supports `offset`/`limit` but the UI always fetches the first 50 runs with no "Load more" or pagination control.

### 9.4 No confirmation before bulk delete
The "Delete All" button in the runs tab has no confirmation dialog. Accidental clicks permanently delete all run history.

---

## 10. Tooling & Developer Experience

### 10.1 No linter/formatter
`pyproject.toml` has no `ruff`, `black`, or `isort` configuration. Adding ruff (covers both lint and format) would enforce consistent style:
```toml
[tool.ruff]
line-length = 100
select = ["E", "F", "I", "UP"]
```

### 10.2 No static type checking
No `mypy` or `pyright` configuration. Type errors like passing `None` where a `str` is expected would be caught before runtime.

### 10.3 No pre-commit hooks
No `.pre-commit-config.yaml`. Adding hooks for `ruff`, `mypy`, and `pytest --fast` would catch issues before they are committed.

### 10.4 No CI pipeline
No GitHub Actions (or equivalent) workflow exists. A minimal pipeline running `uv run pytest tests/unit tests/integration -v` on every PR would prevent regressions.

### 10.5 `pyproject.toml` missing dev tool deps
`pytest-cov`, `ruff`, and `mypy` are not in `[dependency-groups.dev]`. Adding them ensures consistent tooling across environments.
