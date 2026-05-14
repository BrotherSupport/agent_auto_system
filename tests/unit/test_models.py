import json
from datetime import datetime

from sqlmodel import select

from src.models import Job, Run


def test_job_creation(db_session):
    job = Job(name="Test", payload=json.dumps({"key": "val"}))
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    assert job.id is not None
    assert job.name == "Test"
    assert job.job_type == "google_form_fill"
    assert isinstance(job.created_at, datetime)


def test_run_defaults_to_pending(db_session, seed_job):
    run = Run(job_id=seed_job.id)
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    assert run.status == "pending"
    assert run.result is None
    assert run.finished_at is None


def test_run_stores_job_fk(db_session, seed_job):
    run = Run(job_id=seed_job.id, status="running")
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    assert run.job_id == seed_job.id


def test_multiple_runs_per_job(db_session, seed_job):
    for _ in range(3):
        db_session.add(Run(job_id=seed_job.id))
    db_session.commit()

    runs = db_session.exec(select(Run)).all()
    assert len(runs) == 3
