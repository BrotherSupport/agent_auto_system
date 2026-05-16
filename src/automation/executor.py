import asyncio
import json
from datetime import datetime, timezone

from sqlmodel import Session

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


async def execute_run(run_id: int, job_type: str, payload: dict):
    _update_run(run_id, "running")
    try:
        if job_type == "google_form_fill":
            from src.automation.flows.form_fill_flow import FormFillFlow

            flow = FormFillFlow()
            raw = await asyncio.to_thread(flow.kickoff, inputs=payload)
        elif job_type == "web_scraper":
            from src.automation.flows.web_scraper_flow import WebScraperFlow

            flow = WebScraperFlow()
            raw = await asyncio.to_thread(flow.kickoff, inputs=payload)
        elif job_type == "hacker_news_digest":
            from src.automation.flows.hn_digest_flow import HNDigestFlow

            flow = HNDigestFlow()
            raw = await asyncio.to_thread(flow.kickoff, inputs=payload)
        else:
            raise ValueError(f"Unknown job_type: {job_type}")

        result_str = raw.raw if hasattr(raw, "raw") else str(raw)
        try:
            result = json.loads(result_str)
        except (json.JSONDecodeError, TypeError):
            result = {"message": result_str}

        _update_run(run_id, "success", result)
    except Exception as exc:
        _update_run(run_id, "failed", {"error": str(exc)})
