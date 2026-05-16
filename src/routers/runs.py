import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from src.database import get_engine, get_session
from src.models import Job, Run

router = APIRouter()


@router.post("/jobs/{job_id}/run", status_code=202)
async def trigger_run(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    run = Run(job_id=job_id, status="pending")
    session.add(run)
    session.commit()
    session.refresh(run)
    run_id = run.id

    payload = json.loads(job.payload)
    asyncio.create_task(_run_in_background(run_id, job.job_type, payload))

    return {"run_id": run_id, "status": "pending"}


@router.get("/runs")
def list_runs(
    offset: int = 0,
    limit: int = 50,
    session: Session = Depends(get_session),
):
    return session.exec(
        select(Run).order_by(Run.started_at.desc()).offset(offset).limit(limit)
    ).all()


@router.get("/runs/{run_id}")
def get_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: int):
    _engine = get_engine()

    async def event_generator():
        last_status = None
        last_log_count = 0
        try:
            while True:
                with Session(_engine) as s:
                    run = s.get(Run, run_id)

                if run is None:
                    yield f"data: {json.dumps({'error': 'run not found'})}\n\n"
                    break

                current_log: list = []
                if run.log:
                    try:
                        current_log = json.loads(run.log)
                    except json.JSONDecodeError:
                        pass

                status_changed = run.status != last_status
                new_entries = current_log[last_log_count:]

                if status_changed or new_entries:
                    last_status = run.status
                    last_log_count = len(current_log)

                    event: dict = {"status": run.status}
                    if new_entries:
                        event["new_logs"] = new_entries
                    if run.result:
                        try:
                            event["result"] = json.loads(run.result)
                        except json.JSONDecodeError:
                            event["result"] = run.result
                    yield f"data: {json.dumps(event)}\n\n"

                if run.status in ("success", "failed"):
                    break

                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _run_in_background(run_id: int, job_type: str, payload: dict):
    from src.automation.executor import execute_run
    await execute_run(run_id, job_type, payload)
