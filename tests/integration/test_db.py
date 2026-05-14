import json

from sqlmodel import select

from src.models import Job, Run


def test_job_persists_to_db(db_session):
    job = Job(name="DB Test", payload=json.dumps({}))
    db_session.add(job)
    db_session.commit()

    result = db_session.exec(select(Job)).first()
    assert result.name == "DB Test"


def test_run_persists_with_fk(db_session, seed_job):
    run = Run(job_id=seed_job.id, status="running")
    db_session.add(run)
    db_session.commit()

    result = db_session.exec(select(Run)).first()
    assert result.job_id == seed_job.id
    assert result.status == "running"


def test_run_status_can_be_updated(db_session, seed_job):
    run = Run(job_id=seed_job.id)
    db_session.add(run)
    db_session.commit()

    run.status = "success"
    run.result = json.dumps({"submitted": True})
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    assert run.status == "success"
    assert json.loads(run.result)["submitted"] is True


def test_deleting_job_removes_it(db_session, seed_job):
    db_session.delete(seed_job)
    db_session.commit()

    result = db_session.exec(select(Job)).all()
    assert result == []
