import os
from pathlib import Path

from dotenv import load_dotenv
from sqlmodel import Session, SQLModel, create_engine

load_dotenv()

_db_url = os.getenv("DATABASE_URL", "sqlite:///./data/auto.db")
engine = create_engine(_db_url, connect_args={"check_same_thread": False})


def get_engine():
    return engine


def init_db():
    if _db_url.startswith("sqlite:///./"):
        Path("data").mkdir(exist_ok=True)
    SQLModel.metadata.create_all(engine)
    from sqlalchemy import text
    with engine.connect() as conn:
        for ddl in [
            # Column migrations (idempotent)
            "ALTER TABLE run ADD COLUMN log VARCHAR",
            "ALTER TABLE run ADD COLUMN llm_provider VARCHAR",
            "ALTER TABLE run ADD COLUMN llm_model VARCHAR",
            "ALTER TABLE run ADD COLUMN tokens_in INTEGER DEFAULT 0",
            "ALTER TABLE run ADD COLUMN tokens_out INTEGER DEFAULT 0",
            "ALTER TABLE run ADD COLUMN cost_usd REAL DEFAULT 0.0",
            "ALTER TABLE run ADD COLUMN retry_count INTEGER DEFAULT 0",
            "ALTER TABLE job ADD COLUMN schedule VARCHAR",
            # Indexes for common query patterns
            "CREATE INDEX IF NOT EXISTS ix_run_job_id ON run(job_id)",
            "CREATE INDEX IF NOT EXISTS ix_run_status ON run(status)",
            "CREATE INDEX IF NOT EXISTS ix_run_started_at ON run(started_at)",
        ]:
            try:
                conn.execute(text(ddl))
                conn.commit()
            except Exception:
                pass  # column/index already exists


def reconcile_stale_runs() -> int:
    """Mark any runs stuck in pending/running as failed (e.g. after server restart)."""
    from sqlalchemy import text
    error = '{"error": "Server restarted while run was in progress"}'
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "UPDATE run SET status='failed', result=:result "
                "WHERE status IN ('running', 'pending')"
            ),
            {"result": error},
        )
        conn.commit()
        return result.rowcount


def get_session():
    with Session(engine) as session:
        yield session
