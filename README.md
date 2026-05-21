# Agent Auto System

A CrewAI-powered automation platform with **harness engineering** built in. Define jobs, trigger them via API or UI, and let AI agents execute them with multi-LLM support, automatic result validation, and full resource tracking.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Browser UI  (HTML + Vanilla JS)                            │
│  • LLM selector  • Live progress feed  • Run history        │
│  • SSE real-time status + log streaming                     │
│  • Usage tab (tokens / cost)  • Resource stats page         │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼────────────────────────────────────────┐
│  FastAPI  (src/main.py)                                     │
│  • /api/jobs  CRUD                                          │
│  • /api/jobs/{id}/run  → 202, spawns background task        │
│  • /api/runs/{id}/stream  → SSE (status + log stream)       │
│  • /api/stats  → run metrics + token/cost aggregates        │
└───────────────┬─────────────────────────┬───────────────────┘
                │                         │
     ┌──────────▼──────────┐   ┌──────────▼──────────────────┐
     │  SQLite (SQLModel)  │   │  Harness Executor            │
     │  jobs / runs tables │   │  • resolves LLM provider     │
     │  + harness columns  │   │  • dispatches job_type       │
     │    llm_provider     │   │  • validates result quality  │
     │    llm_model        │   │  • auto-retries on failure   │
     │    tokens_in/out    │   │  • tracks tokens + cost      │
     │    cost_usd         │   │                              │
     │    retry_count      │   │  Flows → Crews → Tools       │
     └─────────────────────┘   │  ├ FormFillFlow              │
                                │  ├ WebScraperFlow            │
                                │  ├ HNDigestFlow              │
                                │  ├ XScraperFlow              │
                                │  └ EmailSenderFlow           │
                                └─────────────────────────────┘
                                           │
                          ┌────────────────▼────────────────┐
                          │  src/automation/harness/        │
                          │  ├ provider.py  LLM factory     │
                          │  ├ validator.py result checks   │
                          │  ├ costs.py     pricing table   │
                          │  └ tracker.py  DB persistence   │
                          └─────────────────────────────────┘
```

**Key design choices:**
- FastAPI returns `202` immediately; flows run in `asyncio.create_task`
- SSE (`/api/runs/{id}/stream`) pushes live status **and** granular log entries — no polling
- CrewAI Flow manages state; each Crew handles one automation domain
- SQLite is sufficient for a single-node automation runner
- The harness layer sits between the executor and CrewAI — it owns LLM selection, validation, retries, and cost tracking without touching business logic

---

## Harness Engineering

Harness engineering treats the LLM execution layer as infrastructure: standardized, observable, and resilient. Four concerns are addressed:

### 1 — Multi-LLM Support

`src/automation/harness/provider.py` is a factory that resolves any provider to a `crewai.LLM` instance. The job payload carries `llm_provider` and `llm_model`; the executor strips them before passing inputs to the flow.

| Provider | Fast model | Smart model | Env var |
|---|---|---|---|
| `openai` | `gpt-4o-mini` | `gpt-4o` | `OPENAI_API_KEY` |
| `anthropic` | `claude-haiku-4-5-20251001` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `gemini` | `gemini/gemini-1.5-flash` | `gemini/gemini-1.5-pro` | `GEMINI_API_KEY` |

Crews receive an injected `llm=` argument; `None` preserves the existing CrewAI default (OpenAI). Switching provider is a UI dropdown — no code change required.

### 2 — Automatic Result Validation + Retry

`src/automation/harness/validator.py` runs after every crew execution. It checks job-type-specific invariants:

| Job type | Validation rule |
|---|---|
| `google_form_fill` | `result.submitted is True` |
| `email_sender` | `result.sent is True` |
| `web_scraper` | `content` or `title` field present and non-empty |
| `hacker_news_digest` | `stories` or `digest` field present |
| `x_scraper` | `posts` or `summary` field present |

If validation fails and `retry_count < max_retries` (default 1), the executor re-runs the flow automatically and logs the retry. This catches soft failures — cases where the LLM responded but produced unusable output — without any application code changes.

### 3 — Resource Usage Tracking

Every completed run records:

| Column | Meaning |
|---|---|
| `llm_provider` | Which provider was used (`openai`, `anthropic`, `gemini`) |
| `llm_model` | Exact model string |
| `tokens_in` | Prompt tokens consumed (from `CrewOutput.usage_metrics`) |
| `tokens_out` | Completion tokens generated |
| `cost_usd` | Estimated cost in USD (from `src/automation/harness/costs.py` pricing table) |
| `retry_count` | How many retries were needed |

`/api/stats` aggregates these across all runs and returns `total_tokens`, `total_cost_usd`, and a `by_provider` breakdown. Columns are added to the existing DB via `ALTER TABLE` migrations on startup — no manual intervention needed.

### 4 — UI Integration

- **New Run modal**: Provider + Model dropdowns (model list updates on provider change)
- **Run table rows**: Provider badge (color-coded), cost, total tokens, retry indicator
- **Usage detail tab**: Per-run breakdown of provider, model, tokens in/out, cost, retries
- **Performance page**: Two new stat cards (Total Tokens, Total Cost) + LLM Resource Usage table by provider

---

## Automation Jobs

| Job Type | Description | Payload Fields | LLM Required |
|---|---|---|---|
| `google_form_fill` | AI fills a Google Form via HTTP | `company_name`, `company_size`, `ai_problem` | Yes |
| `web_scraper` | Fetches any URL and returns structured summary | `url` | Yes |
| `hacker_news_digest` | Reads HN top stories and writes a digest | `limit` (1–10) | Yes |
| `x_scraper` | Scrapes recent posts from a public X profile | `username`, `limit` (1–10) | Yes |
| `email_sender` | Sends email via Gmail SMTP | `to`, `subject`, `body`, `cc` (opt) | No |

All LLM-backed jobs accept optional `llm_provider` and `llm_model` fields in their payload to override the default provider.

---

## Key Features

| Feature | Detail |
|---|---|
| **Multi-LLM** | Switch between OpenAI, Anthropic Claude, and Google Gemini per run from the UI |
| **Auto-validation + retry** | Harness validates every result against job-type rules; retries on soft failure |
| **Token + cost tracking** | Every run records prompt/completion tokens and estimated USD cost |
| **Resource stats** | Performance page shows total tokens, total cost, and per-provider breakdown |
| **Live progress log** | SSE streams granular step-by-step log entries to the UI in real time |
| **Failure detection** | Checks application-level results (`submitted: false`) — not just exceptions |
| **Job templates** | Reusable job definitions stored in DB with typed JSON payloads |
| **Async execution** | Runs never block the API; background tasks update status in real time |
| **Tabbed detail view** | Expandable run rows show **Result**, **Log**, and **Usage** tabs |

---

## Docker Quick Start

```bash
# Build
docker build --target runtime --tag agent-auto-system:local .

# Run (choose one or more LLM providers)
docker run -d \
  --name agent-auto \
  -p 8000:8000 \
  -e OPENAI_API_KEY=sk-... \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e GEMINI_API_KEY=AIza... \
  -v agent_data:/app/data \
  agent-auto-system:local

open http://localhost:8000
```

Or with **docker compose** (recommended):

```bash
cp .env.example .env   # fill in at least one LLM API key
docker compose up --build -d
```

See **[doc/docker.md](doc/docker.md)** for full details.

---

## Run Commands (local / dev)

```bash
# Install dependencies (requires uv)
uv sync

# Install Playwright browser
uv run playwright install chromium

# Set up environment
cp .env.example .env
# → add at least OPENAI_API_KEY (or ANTHROPIC_API_KEY / GEMINI_API_KEY)

# Run tests
uv run pytest tests/unit tests/integration -v

# Start dev server
uv run uvicorn src.main:app --reload --port 8000

# Open the UI
open http://localhost:8000
```

---

## Flow: How a Run Works

```
1. User picks automation type, fills fields, selects LLM provider + model
        ↓
2. POST /api/jobs  → creates job row (payload includes llm_provider/model) → 201
        ↓
3. POST /api/jobs/{id}/run  → creates run row (status=pending) → 202
        ↓
4. UI opens EventSource on /api/runs/{run_id}/stream
   + shows live progress panel
        ↓
5. Harness executor:
   ├─ strips llm_provider / llm_model from payload
   ├─ resolves LLM instance via provider.py
   ├─ logs "Using anthropic / claude-haiku-4-5-20251001" if non-default
   └─ dispatches to correct Flow with injected LLM
        ↓
6. Flow → Crew → Tool(s) → structured JSON result
   (usage_metrics captured from CrewOutput)
        ↓
7. Harness validator checks result quality
   ├─ passes → continue
   └─ fails + retries remaining → re-run flow (logged)
        ↓
8. Executor checks app-level failures
   ├─ submitted: false  → status = "failed"
   ├─ error key present → status = "failed"
   └─ otherwise         → status = "success"
        ↓
9. tracker.py writes llm_provider, llm_model, tokens_in, tokens_out,
   cost_usd, retry_count to the run row
        ↓
10. SSE streams terminal status → UI updates badge, result cell,
    Usage tab; Performance page reflects new token/cost totals
```

---

## Project Structure

```
agent_auto_system/
├── .env
├── pyproject.toml
├── src/
│   ├── main.py
│   ├── database.py          # init_db handles migrations (ALTER TABLE ADD COLUMN)
│   ├── models.py            # Job, Run (+ harness columns)
│   ├── routers/
│   │   ├── jobs.py
│   │   └── runs.py          # SSE, stats (token/cost aggregates)
│   └── automation/
│       ├── executor.py      # harness-aware dispatcher
│       ├── progress.py      # append_log() helper
│       ├── harness/         # ← harness engineering module
│       │   ├── provider.py  #   LLM factory (OpenAI / Anthropic / Gemini)
│       │   ├── validator.py #   per-job result validation + retry logic
│       │   ├── costs.py     #   token pricing table → USD estimate
│       │   └── tracker.py   #   persists metrics to Run row
│       ├── flows/
│       │   ├── form_fill_flow.py
│       │   ├── web_scraper_flow.py
│       │   ├── hn_digest_flow.py
│       │   ├── x_scraper_flow.py
│       │   └── email_sender_flow.py
│       ├── crews/
│       │   ├── form_crew/
│       │   ├── web_scraper_crew/
│       │   ├── hn_digest_crew/
│       │   ├── x_scraper_crew/
│       │   └── email_sender_crew/
│       └── tools/
│           ├── google_form_tools.py
│           ├── web_scraper_tool.py
│           ├── hn_tool.py
│           ├── x_scraper_tool.py
│           └── gmail_send_tool.py
├── tests/
└── ui/
    ├── index.html           # LLM selector, Usage tab, resource stat cards
    └── app.js               # provider/model dropdowns, cost/token display
```
