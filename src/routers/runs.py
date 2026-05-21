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
            "llm_provider": run.llm_provider,
            "llm_model": run.llm_model,
            "tokens_in": run.tokens_in or 0,
            "tokens_out": run.tokens_out or 0,
            "cost_usd": run.cost_usd or 0.0,
            "retry_count": run.retry_count or 0,
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


def _duration_secs(r: Run) -> float | None:
    try:
        s = r.started_at  if r.started_at.tzinfo  else r.started_at.replace(tzinfo=timezone.utc)
        f = r.finished_at if r.finished_at.tzinfo else r.finished_at.replace(tzinfo=timezone.utc)
        return (f - s).total_seconds()
    except (AttributeError, TypeError):
        return None


@router.get("/stats")
def get_stats(session: Session = Depends(get_session)):
    runs = session.exec(select(Run)).all()
    if not runs:
        return _empty_stats()

    job_ids = list({r.job_id for r in runs})
    jobs = {j.id: j for j in session.exec(select(Job).where(Job.id.in_(job_ids))).all()}

    today = datetime.now(timezone.utc).date()
    trend_buckets: dict = {today - timedelta(days=i): {"total": 0, "success": 0, "failed": 0}
                           for i in range(6, -1, -1)}

    n_success = n_failed = n_active = 0
    durations: list[float] = []
    by_type: dict = {}
    by_provider: dict = {}
    total_tokens_in = total_tokens_out = 0
    total_cost = 0.0

    for run in runs:
        status = run.status
        if status == "success":
            n_success += 1
        elif status == "failed":
            n_failed += 1
        elif status in ("pending", "running"):
            n_active += 1

        jtype = (jobs[run.job_id].job_type if run.job_id in jobs else "unknown")
        bt = by_type.setdefault(jtype, {"total": 0, "success": 0, "failed": 0,
                                         "pending": 0, "running": 0, "_durs": []})
        bt["total"] += 1
        bt[status] = bt.get(status, 0) + 1

        if run.finished_at and status in ("success", "failed"):
            d = _duration_secs(run)
            if d is not None:
                durations.append(d)
                bt["_durs"].append(d)

        total_tokens_in  += run.tokens_in  or 0
        total_tokens_out += run.tokens_out or 0
        total_cost       += run.cost_usd   or 0.0

        p = run.llm_provider or "unknown"
        bp = by_provider.setdefault(p, {"runs": 0, "tokens_in": 0, "tokens_out": 0,
                                         "cost_usd": 0.0, "models": set()})
        bp["runs"] += 1
        bp["tokens_in"]  += run.tokens_in  or 0
        bp["tokens_out"] += run.tokens_out or 0
        bp["cost_usd"]   += run.cost_usd   or 0.0
        if run.llm_model:
            bp["models"].add(run.llm_model)

        try:
            rd = run.started_at.date()
            if rd in trend_buckets:
                trend_buckets[rd]["total"] += 1
                if status in ("success", "failed"):
                    trend_buckets[rd][status] += 1
        except (AttributeError, TypeError):
            pass

    for data in by_type.values():
        durs = data.pop("_durs")
        data["avg_duration"] = round(sum(durs) / len(durs), 1) if durs else 0
    for bp in by_provider.values():
        bp["models"]   = sorted(bp["models"])
        bp["cost_usd"] = round(bp["cost_usd"], 6)

    n_completed = n_success + n_failed
    avg_dur      = round(sum(durations) / len(durations), 1) if durations else 0
    success_rate = round(n_success / n_completed * 100, 1) if n_completed else 0
    trend = [
        {"date": d.isoformat(), "label": d.strftime("%a"), **trend_buckets[d]}
        for d in sorted(trend_buckets)
    ]

    return {
        "total_runs": len(runs),
        "success": n_success,
        "failed": n_failed,
        "active": n_active,
        "success_rate": success_rate,
        "avg_duration_secs": avg_dur,
        "by_type": by_type,
        "trend": trend,
        "total_tokens_in": total_tokens_in,
        "total_tokens_out": total_tokens_out,
        "total_tokens": total_tokens_in + total_tokens_out,
        "total_cost_usd": round(total_cost, 6),
        "by_provider": by_provider,
    }


def _empty_stats():
    today = datetime.now(timezone.utc).date()
    trend = [
        {"date": d.isoformat(), "label": d.strftime("%a"), "total": 0, "success": 0, "failed": 0}
        for i in range(6, -1, -1)
        for d in (today - timedelta(days=i),)
    ]
    return {
        "total_runs": 0, "success": 0, "failed": 0, "active": 0,
        "success_rate": 0, "avg_duration_secs": 0, "by_type": {}, "trend": trend,
        "total_tokens_in": 0, "total_tokens_out": 0, "total_tokens": 0,
        "total_cost_usd": 0.0, "by_provider": {},
    }


async def _run_in_background(run_id: int, job_type: str, payload: dict):
    from src.automation.executor import execute_run
    await execute_run(run_id, job_type, payload)
