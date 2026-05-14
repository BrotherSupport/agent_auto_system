import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session, SQLModel, create_engine

from src.models import Job


@pytest.fixture(scope="function")
def test_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def db_session(test_engine):
    with Session(test_engine) as s:
        yield s


@pytest_asyncio.fixture
async def client(test_engine, mocker):
    from src.main import app
    from src.database import get_session

    mocker.patch("src.database.get_engine", return_value=test_engine)
    mocker.patch("src.routers.runs.get_engine", return_value=test_engine)
    mocker.patch("src.automation.executor.get_engine", return_value=test_engine)

    def _override():
        with Session(test_engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def seed_job(db_session):
    job = Job(
        name="Test Form Job",
        job_type="google_form_fill",
        payload=json.dumps({
            "company_name": "Acme Corp",
            "company_size": "0-10",
            "ai_problem": "Automate test triage",
        }),
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job
