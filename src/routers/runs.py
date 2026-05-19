import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
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
    runs = session.exec(
        select(Run).order_by(Run.started_at.desc()).offset(offset).limit(limit)
    ).all()
    if not runs:
        return []
    job_ids = list({r.job_id for r in runs})
    jobs = {j.id: j for j in session.exec(select(Job).where(Job.id.in_(job_ids))).all()}
    result = []
    for run in runs:
        job = jobs.get(run.job_id)
        result.append({
            "id": run.id,
            "job_id": run.job_id,
            "job_name": job.name if job else f"job {run.job_id}",
            "job_type": job.job_type if job else "unknown",
            "status": run.status,
            "result": run.result,
            "log": run.log,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        })
    return result


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status in ("pending", "running"):
        raise HTTPException(status_code=409, detail="Cannot delete a run that is in progress")
    session.delete(run)
    session.commit()


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


@router.delete("/runs", status_code=200)
def bulk_delete_runs(
    ids: Optional[str] = Query(None, description="Comma-separated run IDs"),
    delete_all: bool = Query(False),
    session: Session = Depends(get_session),
):
    if delete_all:
        runs = session.exec(
            select(Run).where(Run.status.not_in(["pending", "running"]))
        ).all()
    elif ids:
        id_list = [int(i) for i in ids.split(",") if i.strip().isdigit()]
        if not id_list:
            return {"deleted": 0}
        runs = session.exec(
            select(Run).where(Run.id.in_(id_list)).where(Run.status.not_in(["pending", "running"]))
        ).all()
    else:
        return {"deleted": 0}

    for run in runs:
        session.delete(run)
    session.commit()
    return {"deleted": len(runs)}


@router.get("/stats")
def get_stats(session: Session = Depends(get_session)):
    runs = session.exec(select(Run)).all()
    if not runs:
        return _empty_stats()

    job_ids = list({r.job_id for r in runs})
    jobs = {j.id: j for j in session.exec(select(Job).where(Job.id.in_(job_ids))).all()}

    completed = [r for r in runs if r.finished_at and r.status in ("success", "failed")]
    successes = [r for r in runs if r.status == "success"]
    failures = [r for r in runs if r.status == "failed"]

    durations = []
    for r in completed:
        try:
            s = r.started_at if r.started_at.tzinfo else r.started_at.replace(tzinfo=timezone.utc)
            f = r.finished_at if r.finished_at.tzinfo else r.finished_at.replace(tzinfo=timezone.utc)
            durations.append((f - s).total_seconds())
        except Exception:
            pass

    avg_dur = round(sum(durations) / len(durations), 1) if durations else 0
    success_rate = round(len(successes) / len(completed) * 100, 1) if completed else 0

    # Breakdown by job type
    by_type: dict = {}
    for run in runs:
        job = jobs.get(run.job_id)
        jtype = job.job_type if job else "unknown"
        if jtype not in by_type:
            by_type[jtype] = {"total": 0, "success": 0, "failed": 0, "pending": 0, "running": 0, "_durs": []}
        by_type[jtype]["total"] += 1
        by_type[jtype][run.status] = by_type[jtype].get(run.status, 0) + 1
        if run.finished_at and run.started_at and run.status in ("success", "failed"):
            try:
                s = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=timezone.utc)
                f = run.finished_at if run.finished_at.tzinfo else run.finished_at.replace(tzinfo=timezone.utc)
                by_type[jtype]["_durs"].append((f - s).total_seconds())
            except Exception:
                pass

    for jtype, data in by_type.items():
        durs = data.pop("_durs")
        data["avg_duration"] = round(sum(durs) / len(durs), 1) if durs else 0

    # Last 7 days trend
    today = datetime.now(timezone.utc).date()
    trend = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_runs = []
        for r in runs:
            try:
                rd = r.started_at.date() if hasattr(r.started_at, "date") else r.started_at
                if rd == day:
                    day_runs.append(r)
            except Exception:
                pass
        trend.append({
            "date": day.isoformat(),
            "label": day.strftime("%a"),
            "total": len(day_runs),
            "success": len([r for r in day_runs if r.status == "success"]),
            "failed": len([r for r in day_runs if r.status == "failed"]),
        })

    return {
        "total_runs": len(runs),
        "success": len(successes),
        "failed": len(failures),
        "active": len([r for r in runs if r.status in ("pending", "running")]),
        "success_rate": success_rate,
        "avg_duration_secs": avg_dur,
        "by_type": by_type,
        "trend": trend,
    }


def _empty_stats():
    today = datetime.now(timezone.utc).date()
    trend = [
        {"date": (today - timedelta(days=i)).isoformat(), "label": (today - timedelta(days=i)).strftime("%a"),
         "total": 0, "success": 0, "failed": 0}
        for i in range(6, -1, -1)
    ]
    return {
        "total_runs": 0, "success": 0, "failed": 0, "active": 0,
        "success_rate": 0, "avg_duration_secs": 0, "by_type": {}, "trend": trend,
    }


async def _run_in_background(run_id: int, job_type: str, payload: dict):
    from src.automation.executor import execute_run
    await execute_run(run_id, job_type, payload)
