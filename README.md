# Agent Auto System

A CrewAI-powered automation platform. Define jobs, trigger them via API or UI, and let AI agents execute them in the background.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Browser UI  (HTML + Vanilla JS)                        │
│  • Landing page  • Run history  • SSE status updates    │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼────────────────────────────────────┐
│  FastAPI  (src/main.py)                                 │
│  • /api/jobs  CRUD                                      │
│  • /api/jobs/{id}/run  → 202, spawns background task    │
│  • /api/runs/{id}/stream  → SSE status stream           │
└───────────────┬─────────────────────────┬───────────────┘
                │                         │
     ┌──────────▼──────────┐   ┌──────────▼──────────┐
     │  SQLite (SQLModel)  │   │  CrewAI Flow         │
     │  jobs / runs tables │   │  FormFillFlow        │
     └─────────────────────┘   │    └ FormFillerCrew  │
                                │        └ form_agent  │
                                │    └ PlaywrightTool  │
                                └─────────────────────┘
                                           │
                                ┌──────────▼──────────┐
                                │  Playwright (headless│
                                │  Chromium)           │
                                │  fills Google Form   │
                                └─────────────────────┘
```

**Key design choices:**
- FastAPI returns `202` immediately; the flow runs in `asyncio.create_task`
- SSE (`/api/runs/{id}/stream`) pushes live status — no polling needed
- CrewAI Flow manages state; the Crew handles autonomous browser interaction
- SQLite is sufficient for a single-node automation runner

---

## Key Features

| Feature | Detail |
|---|---|
| **Job templates** | Reusable job definitions stored in DB with typed JSON payloads |
| **Async execution** | Runs never block the API; background tasks update status in real time |
| **Live status via SSE** | `EventSource` stream per run — no client polling required |
| **AI-driven form fill** | CrewAI agent navigates, fills, and submits Google Forms via Playwright |
| **Run history UI** | Auto-updating table with status badges and expandable JSON results |
| **TDD** | All features built test-first: unit → integration → e2e |

---

## Automation Jobs

### Task 1 — Auto Apply Form (AI Consultant Survey)

Fills [this Google Form](https://docs.google.com/forms/d/e/1FAIpQLSc0E2-jTMy8WNFLlHc5rG4zw3U1QaCykBra3mdqFv0DNb8i9Q/viewform) with:

| Field | Type |
|---|---|
| 公司名稱 (Company Name) | text |
| 公司規模 (Company Size) | radio: `0-10` / `11-100` / `200 up` / `其他` |
| 想用AI解決的問題 (AI Problem) | text |

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

# Run e2e tests (real browser + OpenAI key required)
uv run pytest tests/e2e --e2e -v

# Start dev server
uv run uvicorn src.main:app --reload --port 8000

# Open the UI
open http://localhost:8000
```

---

## Flow: How a Run Works

```
1. User fills modal in UI
        ↓
2. POST /api/jobs  → creates job row → 201
        ↓
3. POST /api/jobs/{id}/run  → creates run row (status=pending) → 202
        ↓
4. UI opens EventSource on /api/runs/{run_id}/stream
        ↓
5. Background: FormFillFlow kicks off
   ├─ validate_payload()    → status=running
   └─ execute_crew()
       └─ form_agent uses PlaywrightFormTool
           ├─ navigate to form URL
           ├─ fill Company Name
           ├─ select Company Size radio
           ├─ fill AI Problem
           └─ click Submit
        ↓
6. Flow returns result → DB updated (status=success/failed)
        ↓
7. SSE stream emits terminal event → UI updates row → stream closes
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
│   ├── database.py
│   ├── models.py
│   ├── routers/
│   │   ├── jobs.py
│   │   └── runs.py
│   └── automation/
│       ├── flows/form_fill_flow.py
│       ├── crews/form_crew/
│       │   ├── crew.py
│       │   └── config/{agents,tasks}.yaml
│       └── tools/playwright_form_tool.py
├── tests/
│   ├── conftest.py
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── ui/
    ├── index.html
    └── app.js
```
