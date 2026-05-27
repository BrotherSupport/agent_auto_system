import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlmodel import Session, select

from src.automation.registry import cancel as cancel_task
from src.automation.registry import register, unregister
from src.database import get_engine, get_session
from src.models import Job, Run

logger = logging.getLogger(__name__)
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
    task = asyncio.create_task(_run_in_background(run_id, job.job_type, payload))
    register(run_id, task)
    logger.info("Triggered run_id=%d for job_id=%d (%s)", run_id, job_id, job.job_type)

    return {"run_id": run_id, "status": "pending"}


@router.post("/runs/{run_id}/cancel", status_code=200)
async def cancel_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=409, detail="Run is not active")

    was_cancelled = cancel_task(run_id)
    if was_cancelled:
        run.status = "failed"
        run.result = json.dumps({"error": "Cancelled by user"})
        run.finished_at = datetime.now(UTC)
        session.add(run)
        session.commit()

    return {"cancelled": was_cancelled, "run_id": run_id}


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

                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/runs", status_code=200)
def bulk_delete_runs(
    ids: str | None = Query(None, description="Comma-separated run IDs"),
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
def get_stats():
    engine = get_engine()
    today = datetime.now(UTC).date()

    with engine.connect() as conn:
        total_runs = conn.execute(text("SELECT COUNT(*) FROM run")).scalar() or 0
        if not total_runs:
            return _empty_stats()

        # Overall counts, token totals, and average duration
        row = conn.execute(text("""
            SELECT
                SUM(CASE WHEN status='success' THEN 1 ELSE 0 END),
                SUM(CASE WHEN status='failed'  THEN 1 ELSE 0 END),
                SUM(CASE WHEN status IN ('pending','running') THEN 1 ELSE 0 END),
                SUM(COALESCE(tokens_in,  0)),
                SUM(COALESCE(tokens_out, 0)),
                SUM(COALESCE(cost_usd,   0.0)),
                AVG(CASE WHEN finished_at IS NOT NULL AND status IN ('success','failed')
                    THEN (julianday(finished_at) - julianday(started_at)) * 86400 END)
            FROM run
        """)).fetchone()

        n_success, n_failed, n_active = row[0] or 0, row[1] or 0, row[2] or 0
        total_tokens_in  = row[3] or 0
        total_tokens_out = row[4] or 0
        total_cost       = row[5] or 0.0
        avg_dur          = round(row[6], 1) if row[6] is not None else 0

        # By type: counts + weighted average duration per job_type
        type_rows = conn.execute(text("""
            SELECT
                COALESCE(j.job_type, 'unknown') AS jtype,
                r.status,
                COUNT(*) AS cnt,
                SUM(CASE WHEN r.finished_at IS NOT NULL AND r.status IN ('success','failed')
                    THEN (julianday(r.finished_at) - julianday(r.started_at)) * 86400 ELSE 0 END) AS sum_dur,
                SUM(CASE WHEN r.finished_at IS NOT NULL AND r.status IN ('success','failed')
                    THEN 1 ELSE 0 END) AS cnt_dur
            FROM run r
            LEFT JOIN job j ON r.job_id = j.id
            GROUP BY jtype, r.status
        """)).fetchall()

        by_type: dict = {}
        for jtype, status, cnt, sum_dur, cnt_dur in type_rows:
            bt = by_type.setdefault(jtype, {
                "total": 0, "success": 0, "failed": 0, "pending": 0, "running": 0,
                "_sum_dur": 0.0, "_cnt_dur": 0,
            })
            bt["total"] += cnt
            bt[status] = bt.get(status, 0) + cnt
            bt["_sum_dur"] += sum_dur or 0.0
            bt["_cnt_dur"] += cnt_dur or 0

        for bt in by_type.values():
            sd, cd = bt.pop("_sum_dur"), bt.pop("_cnt_dur")
            bt["avg_duration"] = round(sd / cd, 1) if cd else 0

        # By provider
        prov_rows = conn.execute(text("""
            SELECT
                COALESCE(llm_provider, 'unknown') AS provider,
                COUNT(*) AS runs,
                SUM(COALESCE(tokens_in,  0)),
                SUM(COALESCE(tokens_out, 0)),
                SUM(COALESCE(cost_usd,   0.0))
            FROM run
            GROUP BY COALESCE(llm_provider, 'unknown')
        """)).fetchall()

        by_provider: dict = {}
        for provider, runs, ti, to_, cost in prov_rows:
            by_provider[provider] = {
                "runs": runs, "tokens_in": ti or 0, "tokens_out": to_ or 0,
                "cost_usd": round(cost or 0.0, 6), "models": [],
            }

        model_rows = conn.execute(text("""
            SELECT DISTINCT COALESCE(llm_provider, 'unknown'), llm_model
            FROM run WHERE llm_model IS NOT NULL
        """)).fetchall()
        for provider, model in model_rows:
            if provider in by_provider:
                by_provider[provider]["models"].append(model)
        for bp in by_provider.values():
            bp["models"].sort()

        # 7-day trend (only days with runs; fill gaps below)
        trend_rows = conn.execute(text("""
            SELECT
                DATE(started_at) AS day,
                COUNT(*) AS total,
                SUM(CASE WHEN status='success' THEN 1 ELSE 0 END),
                SUM(CASE WHEN status='failed'  THEN 1 ELSE 0 END)
            FROM run
            WHERE DATE(started_at) >= DATE('now', '-6 days')
            GROUP BY DATE(started_at)
        """)).fetchall()

        trend_map = {
            row[0]: {"total": row[1], "success": row[2] or 0, "failed": row[3] or 0}
            for row in trend_rows
        }

    n_completed = n_success + n_failed
    trend = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        bucket = trend_map.get(ds, {"total": 0, "success": 0, "failed": 0})
        trend.append({"date": ds, "label": d.strftime("%a"), **bucket})

    return {
        "total_runs": total_runs,
        "success": n_success,
        "failed": n_failed,
        "active": n_active,
        "success_rate": round(n_success / n_completed * 100, 1) if n_completed else 0,
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
    today = datetime.now(UTC).date()
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
    try:
        await execute_run(run_id, job_type, payload)
    finally:
        unregister(run_id)
