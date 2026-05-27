import asyncio
import json
from datetime import datetime, timezone

from sqlmodel import Session

from src.automation.harness.costs import estimate_cost
from src.automation.harness.provider import normalize as normalize_llm
from src.automation.harness.validator import validate
from src.automation.progress import append_log
from src.database import get_engine
from src.models import Run


def _update_run(run_id: int, status: str, result: dict | None = None, **metrics):
    with Session(get_engine()) as s:
        run = s.get(Run, run_id)
        run.status = status
        if result is not None:
            run.result = json.dumps(result)
        if status in ("success", "failed"):
            run.finished_at = datetime.now(timezone.utc)
        for k, v in metrics.items():
            setattr(run, k, v)
        s.add(run)
        s.commit()


_FLOW_MAP = {
    "google_form_fill":   ("src.automation.flows.form_fill_flow",  "FormFillFlow",    "Launching form fill agent..."),
    "web_scraper":        ("src.automation.flows.web_scraper_flow", "WebScraperFlow",  "Launching web scraper agent..."),
    "email_sender":       ("src.automation.flows.email_sender_flow","EmailSenderFlow", "Preparing email delivery..."),
    "hacker_news_digest": ("src.automation.flows.hn_digest_flow",   "HNDigestFlow",    "Contacting Hacker News API..."),
    "x_scraper":          ("src.automation.flows.x_scraper_flow",   "XScraperFlow",    "Connecting to X profile scraper..."),
}


async def _run_flow(run_id: int, job_type: str, payload: dict, effective_provider: str, effective_model: str):
    if job_type not in _FLOW_MAP:
        raise ValueError(f"Unknown job_type: {job_type}")

    module_path, class_name, log_msg = _FLOW_MAP[job_type]
    append_log(run_id, log_msg)

    import importlib
    flow_cls = getattr(importlib.import_module(module_path), class_name)
    flow = flow_cls()
    inputs = {
        **payload,
        "run_id": run_id,
        "llm_provider": effective_provider,
        "llm_model": effective_model,
    }
    raw = await asyncio.to_thread(flow.kickoff, inputs=inputs)

    result_str = raw.raw if hasattr(raw, "raw") else str(raw)
    try:
        result = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        result = {"message": result_str}

    usage = getattr(flow.state, "usage", {})
    return result, usage


async def execute_run(run_id: int, job_type: str, payload: dict):
    _update_run(run_id, "running")
    append_log(run_id, f"Starting {job_type}...")

    llm_provider = payload.pop("llm_provider", None)
    llm_model    = payload.pop("llm_model", None)
    max_retries  = int(payload.pop("max_retries", 1))

    effective_provider, effective_model = normalize_llm(llm_provider, llm_model)
    if llm_provider:
        append_log(run_id, f"Using {effective_provider} / {effective_model}")

    tokens_in = tokens_out = 0
    vr = None

    for attempt in range(max_retries + 1):
        if attempt > 0:
            append_log(run_id, f"Retrying (attempt {attempt + 1}/{max_retries + 1})...")

        current_payload = dict(payload)
        if attempt > 0 and vr is not None:
            current_payload["previous_error"] = vr.reason

        try:
            result, usage = await _run_flow(run_id, job_type, current_payload, effective_provider, effective_model)

            tokens_in  += usage.get("prompt_tokens", 0)
            tokens_out += usage.get("completion_tokens", 0)

            vr = validate(job_type, result)
            if not vr.valid and attempt < max_retries:
                append_log(run_id, f"Validation failed ({vr.reason}), retrying...")
                continue

            cost    = estimate_cost(effective_model, tokens_in, tokens_out)
            metrics = dict(llm_provider=effective_provider, llm_model=effective_model,
                           tokens_in=tokens_in, tokens_out=tokens_out,
                           cost_usd=cost, retry_count=attempt)

            if not vr.valid:
                append_log(run_id, f"Automation reported failure: {result.get('error', vr.reason)}")
                _update_run(run_id, "failed", result, **metrics)
            else:
                append_log(run_id, "Automation completed successfully!")
                _update_run(run_id, "success", result, **metrics)
            return

        except Exception as exc:
            if attempt < max_retries:
                append_log(run_id, f"Error (will retry): {str(exc)[:200]}")
                continue
            cost    = estimate_cost(effective_model, tokens_in, tokens_out)
            metrics = dict(llm_provider=effective_provider, llm_model=effective_model,
                           tokens_in=tokens_in, tokens_out=tokens_out,
                           cost_usd=cost, retry_count=attempt)
            append_log(run_id, f"Error: {str(exc)[:200]}")
            _update_run(run_id, "failed", {"error": str(exc)}, **metrics)
