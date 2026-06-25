# AI 健檢 Copilot — System Design Options

5 architectural approaches for the Shopee profit & ops health check tool.
Target: Shopee sellers with monthly revenue 30萬–300萬 NTD.

---

## Approach 1: Streamlit Monolith

**Architecture:** Single Python process. Streamlit handles UI, Pandas handles data parsing and calculations, Claude API generates the final report. Everything lives in one codebase.

```
[Browser] ←→ [Streamlit app (Python)]
                 ├── Pandas (parse + calculate)
                 └── Claude API (generate report)
```

**Pros**
- Fastest path to working MVP — file upload, DataFrame preview, progress bar all built in
- One language, one repo, one deploy command
- Streamlit Cloud / Railway deploy in under an hour
- Easiest for a solo dev to maintain

**Cons**
- Streamlit's layout model limits UI customization — you'll hit ceilings fast
- Hard to package as a desktop app later (Streamlit doesn't play well with PyInstaller)
- No clean API separation — adding billing, multi-user auth, or mobile later is painful
- Long-running analysis blocks the UI thread

**Effort:** ~1–2 weeks to working MVP
**Best for:** Validating the idea before writing "real" code. Ship to 5 beta sellers this week.

---

## Approach 2: FastAPI Backend + Lightweight Frontend

**Architecture:** Python FastAPI handles file upload, parsing, analysis. Simple HTML/JS or minimal React frontend calls the API. Clean separation from day one.

```
[Browser (HTML/JS)]
     ↕ REST / multipart upload
[FastAPI backend]
     ├── Schema Adapter (Pandas)
     ├── Analysis Engine (Pandas)
     └── Claude API
```

**Pros**
- Proper API from the start — easy to add auth, billing, webhook, mobile client later
- Backend is independently testable
- Frontend can evolve without touching backend
- Easy to Dockerize both services separately

**Cons**
- 2–3x more initial setup than Streamlit (CORS, file handling, session state)
- Need to build or choose a frontend — adds decision overhead
- Overkill if the product isn't validated yet

**Effort:** ~3–4 weeks to MVP
**Best for:** You're confident the product has legs and want to build something you won't throw away.

---

## Approach 3: Serverless / Event-Driven (AWS Lambda or Vercel Functions)

**Architecture:** File upload to S3/blob storage triggers a processing function. Analysis runs async. Result stored and polled or pushed via webhook.

```
[Browser] → upload → [S3 / Blob]
                          ↓ trigger
                     [Lambda / Edge Function]
                          ├── Pandas analysis
                          └── Claude API
                          ↓ write result
                     [S3 / DB]
                          ↑ poll / webhook
                     [Browser gets report]
```

**Pros**
- Scales to zero — near-zero cost when no one is using it
- No server to manage or keep running
- Naturally handles traffic spikes

**Cons**
- Pandas + large Excel files in a Lambda is tricky — memory limits (1.5–3GB), cold starts add 1–3s latency
- Async UX is harder to build ("your report is processing…") — more moving parts
- Local dev experience is worse (mocking S3, Lambda locally)
- Debugging is harder: logs are fragmented across functions

**Effort:** ~5–7 weeks to MVP (infra complexity is high)
**Best for:** If you already have AWS/Vercel infra and expect very uneven traffic. Bad choice for MVP.

---

## Approach 4: Local Desktop App (PyInstaller + Embedded Server)

**Architecture:** Python app bundled with all dependencies into a single executable. Spins up a local Flask/FastAPI server on startup. User opens `localhost:8501` in their browser. Data never leaves the machine.

```
[.exe / .app on client machine]
     ├── Embedded Python runtime
     ├── Flask/FastAPI (localhost)
     ├── Pandas
     └── Claude API (still needs internet for this)
[Browser → localhost:8501]
```

**Pros**
- Data stays on client machine (strongest answer to privacy concern)
- No hosting cost, no server to manage
- Can sell as a one-time license instead of subscription
- Works on any machine without Python installed

**Cons**
- Need separate builds for Mac and Windows — doubles maintenance burden
- Installer is ~300–500MB (Python runtime + deps)
- Updates require users to download and reinstall
- Apple Gatekeeper / Windows Defender code signing adds ~$100–400/yr and CI complexity
- Slowest iteration cycle — can't push a hotfix without a new build

**Effort:** ~6–8 weeks for first working builds, ongoing CI/CD burden
**Best for:** Enterprise or high-ticket clients who contractually cannot upload data externally. Bad for MVP.

---

## Approach 5: Agentic Pipeline (Claude as Orchestrator with Tools)

**Architecture:** Claude is the core engine. Python code defines tools (`read_csv`, `calculate_profit`, `detect_columns`). Claude decides which tools to call, in what order, and synthesizes the final report. The schema detection problem largely disappears — Claude reads raw column headers and understands them semantically.

```
[Uploaded files]
     ↓
[Python tool host]
     ├── tool: read_file(path) → raw rows
     ├── tool: detect_schema(headers, sample) → mapping
     ├── tool: calculate_sku_metrics(data) → profit table
     └── tool: flag_anomalies(metrics) → signals
     ↑↓ tool calls
[Claude (orchestrator)]
     └── final report generation
```

**Pros**
- Schema flexibility is built in — Claude maps column names semantically, no regex rules needed
- Analysis logic lives in the prompt, not code — easy to update or extend without a new deploy
- Handles edge cases and unusual formats gracefully
- Can ask clarifying questions if data is ambiguous

**Cons**
- Higher token cost per run — Claude sees more raw data instead of a compact JSON summary
- Non-deterministic — calculations done via LLM can hallucinate numbers (mitigated by doing math in tools, not prompts)
- Harder to debug — why did it flag that SKU?
- Slower per run (multiple round trips)
- Overkill if your data format is actually stable

**Effort:** ~2–3 weeks for MVP, but significant ongoing prompt engineering
**Best for:** When format variability is the primary pain, or when the analysis rules need to evolve fast without code deploys.

---

## Summary

|                       | Effort    | Deploy flexibility  | Data format handling   | Long-term ceiling |
|-----------------------|-----------|---------------------|------------------------|-------------------|
| Streamlit Monolith    | Low       | Cloud only (easily) | Manual / template      | Hits wall fast    |
| FastAPI + Frontend    | Medium    | Cloud + Docker      | Schema adapter layer   | High              |
| Serverless            | High      | Cloud only          | Schema adapter         | High but complex  |
| Desktop (PyInstaller) | Very high | Local only          | Schema adapter         | Medium            |
| Agentic (Claude tools)| Medium    | Cloud + Docker      | Best (semantic)        | Medium            |

## Recommendation

Start with **Approach 1** (Streamlit) to ship and validate. Design the Schema Adapter as a
standalone module from day one so it ports cleanly when you migrate to **Approach 2** (FastAPI)
after the first 10 paying customers. Add Docker local mode as an optional deploy target once a
client asks for it — no need to build it speculatively.
