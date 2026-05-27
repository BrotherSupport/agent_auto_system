"""Integration tests for bulk-delete and stats endpoints."""
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from src.models import Job, Run

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_job(session, job_type: str = "web_scraper") -> Job:
    job = Job(
        name=f"Test {job_type}",
        job_type=job_type,
        payload=json.dumps({"url": "https://example.com"}),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _make_run(session, job_id: int, status: str = "success",
              duration_secs: int = 10) -> Run:
    started = datetime.now(UTC)
    finished = started + timedelta(seconds=duration_secs) if status in ("success", "failed") else None
    run = Run(
        job_id=job_id,
        status=status,
        result=json.dumps({"ok": True}) if status == "success" else None,
        started_at=started,
        finished_at=finished,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


# ── DELETE /api/runs?delete_all=true ─────────────────────────────────────────

async def test_delete_all_removes_completed_runs(client, db_session):
    job = _make_job(db_session)
    _make_run(db_session, job.id, "success")
    _make_run(db_session, job.id, "failed")

    resp = await client.delete("/api/runs?delete_all=true")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2

    list_resp = await client.get("/api/runs")
    assert list_resp.json() == []


async def test_delete_all_skips_active_runs(client, db_session):
    job = _make_job(db_session)
    _make_run(db_session, job.id, "success")
    active = _make_run(db_session, job.id, "running")

    resp = await client.delete("/api/runs?delete_all=true")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1

    list_resp = await client.get("/api/runs")
    remaining = list_resp.json()
    assert len(remaining) == 1
    assert remaining[0]["id"] == active.id


async def test_delete_all_when_no_runs_returns_zero(client):
    resp = await client.delete("/api/runs?delete_all=true")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0


async def test_delete_all_skips_pending_runs(client, db_session):
    job = _make_job(db_session)
    _make_run(db_session, job.id, "pending")

    resp = await client.delete("/api/runs?delete_all=true")
    assert resp.json()["deleted"] == 0


# ── DELETE /api/runs?ids=… ────────────────────────────────────────────────────

async def test_bulk_delete_by_ids(client, db_session):
    job = _make_job(db_session)
    r1 = _make_run(db_session, job.id, "success")
    r2 = _make_run(db_session, job.id, "success")
    r3 = _make_run(db_session, job.id, "success")

    resp = await client.delete(f"/api/runs?ids={r1.id},{r2.id}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2

    list_resp = await client.get("/api/runs")
    remaining_ids = {r["id"] for r in list_resp.json()}
    assert r3.id in remaining_ids
    assert r1.id not in remaining_ids
    assert r2.id not in remaining_ids


async def test_bulk_delete_by_ids_skips_active(client, db_session):
    job = _make_job(db_session)
    r_done = _make_run(db_session, job.id, "success")
    r_active = _make_run(db_session, job.id, "running")

    resp = await client.delete(f"/api/runs?ids={r_done.id},{r_active.id}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1

    # Active run must still be there
    get_resp = await client.get(f"/api/runs/{r_active.id}")
    assert get_resp.status_code == 200


async def test_bulk_delete_empty_ids_returns_zero(client):
    resp = await client.delete("/api/runs")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0


async def test_bulk_delete_nonexistent_ids_returns_zero(client):
    resp = await client.delete("/api/runs?ids=9999,8888")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0


# ── GET /api/stats — empty ────────────────────────────────────────────────────

async def test_stats_empty_db_returns_zeros(client):
    resp = await client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_runs"] == 0
    assert data["success"] == 0
    assert data["failed"] == 0
    assert data["success_rate"] == 0
    assert data["avg_duration_secs"] == 0
    assert data["by_type"] == {}


async def test_stats_trend_has_7_days(client):
    resp = await client.get("/api/stats")
    data = resp.json()
    assert len(data["trend"]) == 7


# ── GET /api/stats — with data ────────────────────────────────────────────────

async def test_stats_total_runs_correct(client, db_session):
    job = _make_job(db_session)
    _make_run(db_session, job.id, "success")
    _make_run(db_session, job.id, "success")
    _make_run(db_session, job.id, "failed")

    data = (await client.get("/api/stats")).json()
    assert data["total_runs"] == 3
    assert data["success"] == 2
    assert data["failed"] == 1


async def test_stats_success_rate_calculation(client, db_session):
    job = _make_job(db_session)
    _make_run(db_session, job.id, "success")
    _make_run(db_session, job.id, "success")
    _make_run(db_session, job.id, "success")
    _make_run(db_session, job.id, "failed")

    data = (await client.get("/api/stats")).json()
    assert data["success_rate"] == 75.0


async def test_stats_by_type_populated(client, db_session):
    web_job = _make_job(db_session, "web_scraper")
    hn_job = _make_job(db_session, "hacker_news_digest")
    _make_run(db_session, web_job.id, "success")
    _make_run(db_session, web_job.id, "success")
    _make_run(db_session, hn_job.id, "failed")

    data = (await client.get("/api/stats")).json()
    bt = data["by_type"]
    assert bt["web_scraper"]["total"] == 2
    assert bt["web_scraper"]["success"] == 2
    assert bt["hacker_news_digest"]["failed"] == 1


async def test_stats_avg_duration_computed(client, db_session):
    job = _make_job(db_session)
    _make_run(db_session, job.id, "success", duration_secs=10)
    _make_run(db_session, job.id, "success", duration_secs=20)

    data = (await client.get("/api/stats")).json()
    assert data["avg_duration_secs"] == 15.0


async def test_stats_active_count(client, db_session, mocker):
    mocker.patch("src.routers.runs._run_in_background", new=AsyncMock())
    job = _make_job(db_session)
    _make_run(db_session, job.id, "running")
    _make_run(db_session, job.id, "pending")
    _make_run(db_session, job.id, "success")

    data = (await client.get("/api/stats")).json()
    assert data["active"] == 2
