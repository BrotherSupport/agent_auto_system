import json
import pytest
from unittest.mock import AsyncMock

from src.models import Run


async def test_trigger_run_returns_202(client, seed_job, mocker):
    mocker.patch("src.routers.runs._run_in_background", new=AsyncMock())
    resp = await client.post(f"/api/jobs/{seed_job.id}/run")
    assert resp.status_code == 202
    data = resp.json()
    assert "run_id" in data
    assert data["status"] == "pending"


async def test_trigger_run_job_not_found(client):
    resp = await client.post("/api/jobs/9999/run")
    assert resp.status_code == 404


async def test_list_runs_empty(client):
    resp = await client.get("/api/runs")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_run_not_found(client):
    resp = await client.get("/api/runs/9999")
    assert resp.status_code == 404


async def test_get_run_after_trigger(client, seed_job, mocker):
    mocker.patch("src.routers.runs._run_in_background", new=AsyncMock())
    trig = await client.post(f"/api/jobs/{seed_job.id}/run")
    run_id = trig.json()["run_id"]

    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


async def test_list_runs_after_trigger(client, seed_job, mocker):
    mocker.patch("src.routers.runs._run_in_background", new=AsyncMock())
    await client.post(f"/api/jobs/{seed_job.id}/run")
    await client.post(f"/api/jobs/{seed_job.id}/run")

    resp = await client.get("/api/runs")
    assert len(resp.json()) == 2


async def test_sse_stream_returns_event_stream(client, db_session, seed_job):
    # Seed a completed run so the generator exits immediately
    run = Run(job_id=seed_job.id, status="success", result=json.dumps({"submitted": True}))
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    resp = await client.get(f"/api/runs/{run.id}/stream")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert b'"status": "success"' in resp.content
