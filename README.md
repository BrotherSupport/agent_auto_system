# Agent Auto System

A CrewAI-powered automation platform. Define jobs, trigger them via API or UI, and let AI agents execute them in the background.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Browser UI  (HTML + Vanilla JS)                        │
│  • Landing page  • Live progress feed  • Run history    │
│  • SSE real-time status + log streaming                 │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼────────────────────────────────────┐
│  FastAPI  (src/main.py)                                 │
│  • /api/jobs  CRUD                                      │
│  • /api/jobs/{id}/run  → 202, spawns background task    │
│  • /api/runs/{id}/stream  → SSE (status + log stream)   │
└───────────────┬─────────────────────────┬───────────────┘
                │                         │
     ┌──────────▼──────────┐   ┌──────────▼──────────────┐
     │  SQLite (SQLModel)  │   │  CrewAI Executor         │
     │  jobs / runs tables │   │  • dispatches job_type   │
     │  + progress log col │   │  • writes progress log   │
     └─────────────────────┘   │  • detects app failures  │
                                │                          │
                                │  Flows → Crews → Tools   │
                                │  ├ FormFillFlow           │
                                │  ├ WebScraperFlow         │
                                │  ├ HNDigestFlow           │
                                │  └ XScraperFlow           │
                                └─────────────────────────┘
```

**Key design choices:**
- FastAPI returns `202` immediately; the flow runs in `asyncio.create_task`
- SSE (`/api/runs/{id}/stream`) pushes live status **and** granular progress log entries — no polling needed
- CrewAI Flow manages state; each Crew handles one automation domain
- SQLite is sufficient for a single-node automation runner
- The executor detects application-level failures (e.g. `submitted: false`) and marks runs as `failed`, not just Python exceptions

---

## Automation Jobs

| Job Type | Description | Payload Fields | Needs API Key |
|---|---|---|---|
| `google_form_fill` | AI agent fills a Google Form via HTTP | `company_name`, `company_size`, `ai_problem` | OpenAI |
| `web_scraper` | AI agent fetches any URL and answers a question about it | `url`, `question` | OpenAI |
| `hacker_news_digest` | AI agent reads HN top stories and writes a digest | `limit` (1–10) | OpenAI |
| `x_scraper` | AI agent scrapes recent posts from a public X profile (via nitter) | `username`, `limit` (1–10) | OpenAI |

### google_form_fill

Fills the AI Consultant Survey at `docs.google.com/forms/…` with company info.
Uses `GoogleFormInspectorTool` (discovers entry IDs) + `GoogleFormSubmitTool` (HTTP POST with session cookies).

### web_scraper

Fetches any public URL, strips HTML, and asks the AI to answer a custom question based on the page content.
Returns: `title`, `answer`, `key_points`.

### hacker_news_digest

Calls the HN Firebase public API, fetches top N stories, and has the AI write a digest with story-of-the-day, per-story summaries, and recurring themes.
Returns: `story_of_the_day`, `stories`, `themes`.

### x_scraper

Scrapes a public X (Twitter) user's recent posts via nitter (plain HTTP, no auth required). Tries multiple nitter instances for resilience. AI agent summarizes the activity.
Returns: `username`, `post_count`, `top_post`, `themes`, `summary`, `posts`.

---

## Key Features

| Feature | Detail |
|---|---|
| **Live progress log** | SSE streams granular step-by-step log entries to the UI in real time |
| **Correct failure detection** | Executor checks application-level results (e.g. `submitted: false`) — not just Python exceptions |
| **Job templates** | Reusable job definitions stored in DB with typed JSON payloads |
| **Async execution** | Runs never block the API; background tasks update status and log in real time |
| **Tabbed detail view** | Expandable run rows show **Result** and **Log** tabs |
| **4 automation types** | Form fill, web scraper, HN digest, X post scraper |

---

## Run Commands

```bash
# Install dependencies (requires uv)
uv sync

# Install Playwright browser
uv run playwright install chromium

# Set up environment
cp .env.example .env
# → add OPENAI_API_KEY to .env

# Run unit + integration tests
uv run pytest tests/unit tests/integration -v

# Start dev server
uv run uvicorn src.main:app --reload --port 8000

# Open the UI
open http://localhost:8000
```

---

## Flow: How a Run Works

```
1. User picks automation type + fills fields in modal
        ↓
2. POST /api/jobs  → creates job row → 201
        ↓
3. POST /api/jobs/{id}/run  → creates run row (status=pending) → 202
        ↓
4. UI opens EventSource on /api/runs/{run_id}/stream
   + shows live progress panel
        ↓
5. Background: executor dispatches to correct Flow
   ├─ appends progress log entries throughout
   ├─ Flow validates payload → executes Crew
   └─ Crew uses tool(s) → returns structured JSON
        ↓
6. Executor checks result for app-level failures
   ├─ submitted: false  → status = "failed"
   ├─ error key present → status = "failed"
   └─ otherwise         → status = "success"
        ↓
7. SSE streams each new log entry + terminal status
   → UI updates badge, progress panel, result cell
   → Progress panel hides; detail row shows Result + Log tabs
```

---

## Project Structure

```
agent_auto_system/
├── .env
├── pyproject.toml
├── README.md
├── doc/design.md
├── src/
│   ├── main.py
│   ├── database.py        # init_db handles migrations (ALTER TABLE ADD COLUMN)
│   ├── models.py          # Job, Run (+ log column for progress)
│   ├── routers/
│   │   ├── jobs.py
│   │   └── runs.py        # SSE streams status + new_logs
│   └── automation/
│       ├── executor.py    # dispatches job_type, progress logging, failure detection
│       ├── progress.py    # append_log() helper
│       ├── flows/
│       │   ├── form_fill_flow.py
│       │   ├── web_scraper_flow.py
│       │   ├── hn_digest_flow.py
│       │   └── x_scraper_flow.py
│       ├── crews/
│       │   ├── form_crew/
│       │   ├── web_scraper_crew/
│       │   ├── hn_digest_crew/
│       │   └── x_scraper_crew/
│       └── tools/
│           ├── google_form_tools.py
│           ├── web_scraper_tool.py
│           ├── hn_tool.py
│           └── x_scraper_tool.py
├── tests/
└── ui/
    ├── index.html          # live progress panel, tabbed detail rows
    └── app.js
```
