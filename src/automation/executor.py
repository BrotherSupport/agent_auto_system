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
    """Detect when the automation ran but reported a logical failure."""
    if "error" in result:
        return True
    if job_type == "google_form_fill" and not result.get("submitted", True):
        return True
    if job_type == "email_sender" and result.get("sent") is False:
        return True
    return False


async def execute_run(run_id: int, job_type: str, payload: dict):
    _update_run(run_id, "running")
    append_log(run_id, f"Starting {job_type}...")

    try:
        inputs = {**payload, "run_id": run_id}

        if job_type == "google_form_fill":
            from src.automation.flows.form_fill_flow import FormFillFlow
            append_log(run_id, "Launching form fill agent...")
            raw = await asyncio.to_thread(FormFillFlow().kickoff, inputs=inputs)

        elif job_type == "web_scraper":
            from src.automation.flows.web_scraper_flow import WebScraperFlow
            append_log(run_id, "Launching web scraper agent...")
            raw = await asyncio.to_thread(WebScraperFlow().kickoff, inputs=inputs)

        elif job_type == "email_sender":
            from src.automation.flows.email_sender_flow import EmailSenderFlow
            append_log(run_id, "Preparing email delivery...")
            raw = await asyncio.to_thread(EmailSenderFlow().kickoff, inputs=inputs)

        elif job_type == "hacker_news_digest":
            from src.automation.flows.hn_digest_flow import HNDigestFlow
            append_log(run_id, "Contacting Hacker News API...")
            raw = await asyncio.to_thread(HNDigestFlow().kickoff, inputs=inputs)

        elif job_type == "x_scraper":
            from src.automation.flows.x_scraper_flow import XScraperFlow
            append_log(run_id, f"Connecting to X profile scraper...")
            raw = await asyncio.to_thread(XScraperFlow().kickoff, inputs=inputs)

        else:
            raise ValueError(f"Unknown job_type: {job_type}")

        append_log(run_id, "Processing results...")
        result_str = raw.raw if hasattr(raw, "raw") else str(raw)
        try:
            result = json.loads(result_str)
        except (json.JSONDecodeError, TypeError):
            result = {"message": result_str}

        if _is_app_failure(job_type, result):
            append_log(run_id, f"Automation reported failure: {result.get('error', result.get('confirmation', ''))}")
            _update_run(run_id, "failed", result)
        else:
            append_log(run_id, "Automation completed successfully!")
            _update_run(run_id, "success", result)

    except Exception as exc:
        append_log(run_id, f"Error: {str(exc)[:200]}")
        _update_run(run_id, "failed", {"error": str(exc)})
