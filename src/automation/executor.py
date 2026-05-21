import asyncio
import json
from datetime import datetime, timezone

from sqlmodel import Session

from src.automation.progress import append_log
from src.database import get_engine
from src.models import Run


def _update_run(run_id: int, status: str, result: dict | None = None):
    with Session(get_engine()) as s:
        run = s.get(Run, run_id)
        run.status = status
        if result is not None:
            run.result = json.dumps(result)
        if status in ("success", "failed"):
            run.finished_at = datetime.now(timezone.utc)
        s.add(run)
        s.commit()


def _is_app_failure(job_type: str, result: dict) -> bool:
    if "error" in result:
        return True
    if job_type == "google_form_fill" and not result.get("submitted", True):
        return True
    if job_type == "email_sender" and result.get("sent") is False:
        return True
    return False


async def _run_flow(run_id: int, job_type: str, payload: dict, llm):
    """Execute the appropriate flow and return (result_dict, usage_dict)."""
    inputs = {**payload, "run_id": run_id}

    if job_type == "google_form_fill":
        from src.automation.flows.form_fill_flow import FormFillFlow
        flow = FormFillFlow()
        flow.llm = llm
        append_log(run_id, "Launching form fill agent...")
        raw = await asyncio.to_thread(flow.kickoff, inputs=inputs)

    elif job_type == "web_scraper":
        from src.automation.flows.web_scraper_flow import WebScraperFlow
        flow = WebScraperFlow()
        flow.llm = llm
        append_log(run_id, "Launching web scraper agent...")
        raw = await asyncio.to_thread(flow.kickoff, inputs=inputs)

    elif job_type == "email_sender":
        from src.automation.flows.email_sender_flow import EmailSenderFlow
        flow = EmailSenderFlow()
        append_log(run_id, "Preparing email delivery...")
        raw = await asyncio.to_thread(flow.kickoff, inputs=inputs)

    elif job_type == "hacker_news_digest":
        from src.automation.flows.hn_digest_flow import HNDigestFlow
        flow = HNDigestFlow()
        flow.llm = llm
        append_log(run_id, "Contacting Hacker News API...")
        raw = await asyncio.to_thread(flow.kickoff, inputs=inputs)

    elif job_type == "x_scraper":
        from src.automation.flows.x_scraper_flow import XScraperFlow
        flow = XScraperFlow()
        flow.llm = llm
        append_log(run_id, "Connecting to X profile scraper...")
        raw = await asyncio.to_thread(flow.kickoff, inputs=inputs)

    else:
        raise ValueError(f"Unknown job_type: {job_type}")

    result_str = raw.raw if hasattr(raw, "raw") else str(raw)
    try:
        result = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        result = {"message": result_str}

    usage = getattr(flow.state, "usage", {})
    return result, usage


async def execute_run(run_id: int, job_type: str, payload: dict):
    from src.automation.harness.provider import resolve as resolve_llm
    from src.automation.harness.validator import validate
    from src.automation.harness.tracker import update_run_metrics
    from src.automation.harness.costs import estimate_cost

    _update_run(run_id, "running")
    append_log(run_id, f"Starting {job_type}...")

    llm_provider = payload.pop("llm_provider", None)
    llm_model = payload.pop("llm_model", None)
    max_retries = int(payload.pop("max_retries", 1))

    llm, effective_provider, effective_model = resolve_llm(llm_provider, llm_model)
    if llm_provider:
        append_log(run_id, f"Using {effective_provider} / {effective_model}")

    tokens_in = tokens_out = 0
    retry_count = 0

    for attempt in range(max_retries + 1):
        if attempt > 0:
            retry_count = attempt
            append_log(run_id, f"Retrying (attempt {attempt + 1}/{max_retries + 1})...")

        try:
            append_log(run_id, "Processing results...")
            result, usage = await _run_flow(run_id, job_type, payload, llm)

            tokens_in  += usage.get("prompt_tokens", 0)
            tokens_out += usage.get("completion_tokens", 0)

            vr = validate(job_type, result)
            if not vr.valid and attempt < max_retries:
                append_log(run_id, f"Validation failed ({vr.reason}), retrying...")
                continue

            cost = estimate_cost(effective_model, tokens_in, tokens_out)
            update_run_metrics(run_id, effective_provider, effective_model,
                               tokens_in, tokens_out, cost, retry_count)

            if _is_app_failure(job_type, result) or not vr.valid:
                err = result.get("error", vr.reason)
                append_log(run_id, f"Automation reported failure: {err}")
                _update_run(run_id, "failed", result)
            else:
                append_log(run_id, "Automation completed successfully!")
                _update_run(run_id, "success", result)
            return

        except Exception as exc:
            if attempt < max_retries:
                append_log(run_id, f"Error (will retry): {str(exc)[:200]}")
                continue
            cost = estimate_cost(effective_model, tokens_in, tokens_out)
            update_run_metrics(run_id, effective_provider, effective_model,
                               tokens_in, tokens_out, cost, retry_count)
            append_log(run_id, f"Error: {str(exc)[:200]}")
            _update_run(run_id, "failed", {"error": str(exc)})
