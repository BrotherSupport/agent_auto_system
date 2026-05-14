# Agent Auto System — Design Document

> **Status**: Draft · **Date**: 2026-05-14  
> **Stack**: Python · uv · CrewAI · OpenAI · FastAPI · SQLite · Playwright

---

## 1. Overview

A CrewAI-powered automation platform that runs background jobs driven by AI agents. The first job is auto-filling a Google Form on behalf of a user. A minimal HTML/JS frontend shows the landing page and automation run history.

---

## 2. Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Agent framework | CrewAI (Flows + Crews) | Structured orchestration with autonomous agents |
| LLM | OpenAI GPT-4o-mini | Cost-efficient, tool-calling support |
| Package manager | uv | Fast, lockfile-based, replaces pip/venv |
| Backend | FastAPI | Async, auto-docs, minimal boilerplate |
| Database | SQLite (via SQLModel) | Zero-ops, good for single-node automation |
| Browser automation | Playwright (Python) | Reliable form interaction, headless support |
| Frontend | HTML + Vanilla JS | Simple, no build step |

---

## 3. Project Structure

```
agent_auto_system/
├── .env                          # API keys (never committed)
├── pyproject.toml                # uv project + dependencies
├── doc/
│   └── design.md                 # this file
├── src/
│   ├── main.py                   # FastAPI app entry point
│   ├── database.py               # SQLite connection + init
│   ├── models.py                 # SQLModel table definitions
│   ├── routers/
│   │   ├── jobs.py               # Job CRUD endpoints
│   │   └── runs.py               # Run history endpoints
│   └── automation/
│       ├── flows/
│       │   └── form_fill_flow.py # CrewAI Flow orchestration
│       ├── crews/
│       │   └── form_crew/
│       │       ├── crew.py       # @CrewBase class
│       │       └── config/
│       │           ├── agents.yaml
│       │           └── tasks.yaml
│       └── tools/
│           └── playwright_form_tool.py  # Playwright tool for CrewAI
└── ui/
    ├── index.html                # Landing page + history UI
    └── app.js                    # API calls + DOM rendering
```

---

## 4. Database Schema

### `jobs`
Defines a reusable automation job template.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | auto-increment |
| `name` | TEXT | human label, e.g. "AI Consultant Form" |
| `job_type` | TEXT | e.g. `"google_form_fill"` |
| `payload` | TEXT | JSON config (form URL, field values) |
| `created_at` | DATETIME | UTC |

### `runs`
Records every execution of a job.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | auto-increment |
| `job_id` | INTEGER FK → jobs.id | |
| `status` | TEXT | `pending` · `running` · `success` · `failed` |
| `result` | TEXT | JSON output or error message |
| `started_at` | DATETIME | UTC |
| `finished_at` | DATETIME | UTC, nullable |

---

## 5. API Design

Base URL: `http://localhost:8000`

### Jobs

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/jobs` | List all jobs |
| `POST` | `/api/jobs` | Create a new job |
| `GET` | `/api/jobs/{id}` | Get job detail |
| `DELETE` | `/api/jobs/{id}` | Delete job |

### Runs

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/jobs/{id}/run` | Trigger a job run (async) |
| `GET` | `/api/runs` | List all runs (with pagination) |
| `GET` | `/api/runs/{id}` | Get run detail + result |

### System

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Serve `ui/index.html` |
| `GET` | `/health` | Health check |

---

## 6. CrewAI Architecture

### Flow: `FormFillFlow`

```
FormFillFlow (Pydantic state: job_id, payload, run_id)
    │
    ├─ @start()  validate_payload()
    │       └─ parse and validate form field values
    │
    └─ @listen(validate_payload)  execute_crew()
            └─ delegates to FormFillerCrew
                    └─ returns: { success: bool, screenshot_path, message }
```

### Crew: `FormFillerCrew`

**Agent — `form_agent`**
- Role: Web Form Automation Specialist
- Goal: Fill and submit the target Google Form accurately
- Tools: `PlaywrightFormTool`
- LLM: `gpt-4o-mini`

**Task — `fill_form_task`**
- Description: Navigate to the form URL, fill each field with the provided values, submit, and confirm success
- Expected output: JSON `{ "submitted": true, "confirmation_text": "..." }`

### Tool: `PlaywrightFormTool`

A CrewAI `BaseTool` wrapping Playwright. Input schema:

```python
class FormInput(BaseModel):
    url: str
    company_name: str
    company_size: Literal["0-10", "11-100", "200 up", "其他"]
    ai_problem: str
```

Internally launches a headless Chromium browser, fills each field by label/selector, submits, and returns the confirmation message text.

---

## 7. Target Form: AI Consultant Survey

URL: `https://docs.google.com/forms/d/e/1FAIpQLSc0E2-jTMy8WNFLlHc5rG4zw3U1QaCykBra3mdqFv0DNb8i9Q/viewform`

| Field | Label (zh) | Type | Options |
|---|---|---|---|
| 1 | 公司名稱 (Company Name) | Text input | — |
| 2 | 公司規模 (Company Size) | Radio | `0-10` / `11-100` / `200 up` / `其他` |
| 3 | 想用AI解決的問題 (AI Problem) | Text input | — |

Job payload example:
```json
{
  "url": "https://docs.google.com/forms/d/e/1FAIpQLSc0E2-jTMy8WNFLlHc5rG4zw3U1QaCykBra3mdqFv0DNb8i9Q/viewform",
  "company_name": "Acme Corp",
  "company_size": "11-100",
  "ai_problem": "Automate customer support ticket triage"
}
```

---

## 8. Frontend UI

Single-page `index.html` with two sections:

### Landing Section
- System name + tagline
- "New Run" button that opens a modal form with three fields (company name, size, AI problem)
- On submit → `POST /api/jobs` then `POST /api/jobs/{id}/run`

### History Section
- Table of recent runs: ID · Job Name · Status badge · Started At · Duration · Result link
- Auto-refreshes every 5 seconds via `setInterval` polling `GET /api/runs`
- Click a row to expand the JSON result inline

No framework — plain `fetch()` API and DOM manipulation. Styled with a minimal CSS design (dark sidebar, clean cards).

---

## 9. Configuration

### `.env`
```
OPENAI_API_KEY=sk-...
DATABASE_URL=sqlite:///./data/auto.db
```

### `pyproject.toml` (key dependencies)
```toml
[project]
name = "agent-auto-system"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
  "crewai[tools]>=0.80.0",
  "fastapi>=0.115.0",
  "uvicorn[standard]>=0.30.0",
  "sqlmodel>=0.0.21",
  "playwright>=1.44.0",
  "python-dotenv>=1.0.0",
  "openai>=1.30.0",
]
```

---

## 10. Run Instructions (local dev)

```bash
# 1. Install dependencies
uv sync

# 2. Install Playwright browsers
uv run playwright install chromium

# 3. Copy and fill env
cp .env.example .env

# 4. Start the server
uv run uvicorn src.main:app --reload --port 8000

# 5. Open UI
open http://localhost:8000
```

---

## 11. Sequence Diagram

```
User (Browser)          FastAPI              CrewAI Flow           Playwright
     │                     │                      │                     │
     │── POST /api/jobs ──►│                      │                     │
     │◄─ 201 {job_id} ─────│                      │                     │
     │                     │                      │                     │
     │── POST /jobs/1/run ►│                      │                     │
     │◄─ 202 {run_id} ─────│                      │                     │
     │                     │── FormFillFlow() ───►│                     │
     │                     │                      │── validate ────────►│
     │                     │                      │── launch browser ──►│
     │                     │                      │                     │── fill fields
     │                     │                      │                     │── submit
     │                     │                      │◄── confirmation ────│
     │                     │◄─ run result ────────│                     │
     │                     │── UPDATE runs ───────│                     │
     │                     │                      │                     │
     │── GET /api/runs ───►│                      │                     │
     │◄─ [{run: success}] ─│                      │                     │
```

---

## 12. Future Jobs (Roadmap)

| Job Type | Description |
|---|---|
| `email_outreach` | Draft and send templated emails via Gmail API |
| `linkedin_connect` | Auto-connect with filtered LinkedIn profiles |
| `sheet_updater` | Write structured data into Google Sheets |
| `web_scraper` | Extract data from a target URL and save to DB |

Each new job type: add a row to `job_type` enum, a new Crew under `automation/crews/`, and a matching payload schema.
