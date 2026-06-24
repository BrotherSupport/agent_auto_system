import asyncio
import json
import logging
import re
import time
from datetime import UTC, datetime

from sqlmodel import Session

from src.automation.harness.costs import estimate_cost
from src.automation.harness.provider import normalize as normalize_llm
from src.automation.harness.validator import validate
from src.automation.pipeline import execute_pipeline
from src.automation.progress import append_log
from src.database import get_engine
from src.models import Run
from src.telemetry import record_run as _record_run

logger = logging.getLogger(__name__)


def _update_run(run_id: int, status: str, result: dict | None = None, **metrics):
    with Session(get_engine()) as s:
        run = s.get(Run, run_id)
        run.status = status
        if result is not None:
            run.result = json.dumps(result)
        if status in ("success", "failed"):
            run.finished_at = datetime.now(UTC)
        for k, v in metrics.items():
            setattr(run, k, v)
        s.add(run)
        s.commit()


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL | re.IGNORECASE)


def _parse_result(result_str: str) -> dict:
    """Parse a flow's raw string output into a dict.

    LLMs (notably Gemini) often wrap JSON in markdown code fences (```json ... ```),
    which makes a naive json.loads fail. Strip the fence and retry before falling
    back to wrapping the raw text in a {"message": ...} envelope.
    """
    try:
        return json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        pass

    if isinstance(result_str, str):
        m = _FENCE_RE.match(result_str)
        if m:
            try:
                return json.loads(m.group(1))
            except (json.JSONDecodeError, TypeError):
                pass

    return {"message": result_str}


_FLOW_MAP = {
    "google_form_fill":    ("src.automation.flows.form_fill_flow",      "FormFillFlow",      "Launching form fill agent..."),
    "web_scraper":         ("src.automation.flows.web_scraper_flow",     "WebScraperFlow",    "Launching web scraper agent..."),
    "email_sender":        ("src.automation.flows.email_sender_flow",    "EmailSenderFlow",   "Preparing email delivery..."),
    "hacker_news_digest":  ("src.automation.flows.hn_digest_flow",       "HNDigestFlow",      "Contacting Hacker News API..."),
    "x_scraper":           ("src.automation.flows.x_scraper_flow",       "XScraperFlow",      "Connecting to X profile scraper..."),
    "google_sheet_reader": ("src.automation.flows.google_sheet_flow",    "GoogleSheetFlow",   "Connecting to Google Sheets..."),
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
    result = _parse_result(result_str)

    usage = getattr(flow.state, "usage", {})
    return result, usage


async def execute_run(run_id: int, job_type: str, payload: dict):
    logger.info("Starting run_id=%d job_type=%s", run_id, job_type)
    _update_run(run_id, "running")
    _t0 = time.monotonic()
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
            if job_type == "pipeline":
                pipeline_steps = current_payload.get("steps", [])
                result, usage = await execute_pipeline(run_id, pipeline_steps, effective_provider, effective_model)
            else:
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
                _record_run(job_type=job_type, status="failed", duration_secs=time.monotonic() - _t0,
                            provider=effective_provider, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost)
                _update_run(run_id, "failed", result, **metrics)
            else:
                append_log(run_id, "Automation completed successfully!")
                _record_run(job_type=job_type, status="success", duration_secs=time.monotonic() - _t0,
                            provider=effective_provider, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost)
                _update_run(run_id, "success", result, **metrics)
            return

        except asyncio.CancelledError:
            raise  # DB status already updated by the cancel endpoint
        except Exception as exc:
            if attempt < max_retries:
                append_log(run_id, f"Error (will retry): {str(exc)[:200]}")
                logger.warning("run_id=%d attempt=%d raised %s, retrying", run_id, attempt, exc)
                continue
            cost    = estimate_cost(effective_model, tokens_in, tokens_out)
            metrics = dict(llm_provider=effective_provider, llm_model=effective_model,
                           tokens_in=tokens_in, tokens_out=tokens_out,
                           cost_usd=cost, retry_count=attempt)
            logger.error("run_id=%d failed after %d attempt(s): %s", run_id, attempt + 1, exc)
            append_log(run_id, f"Error: {str(exc)[:200]}")
            _record_run(job_type=job_type, status="failed", duration_secs=time.monotonic() - _t0,
                        provider=effective_provider, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost)
            _update_run(run_id, "failed", {"error": str(exc)}, **metrics)
