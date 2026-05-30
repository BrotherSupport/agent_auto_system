import os
os.environ.setdefault("OTEL_ENABLED", "false")

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.models import Job  # ensure both tables are in metadata


@pytest.fixture(scope="function")
def test_engine():
    # StaticPool: all connections share the same in-memory SQLite database.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def db_session(test_engine):
    with Session(test_engine) as s:
        yield s


@pytest_asyncio.fixture
async def client(test_engine, mocker):
    import src.database as _db
    from src.main import app

    # Patch the module-level engine so get_session(), get_engine(), and init_db()
    # all operate on the in-memory test database.
    mocker.patch.object(_db, "engine", test_engine)
    mocker.patch("src.routers.runs.get_engine", return_value=test_engine)
    mocker.patch("src.automation.executor.get_engine", return_value=test_engine)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


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
