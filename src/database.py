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
    # Migrate: add columns introduced after the initial schema
    from sqlalchemy import text
    with engine.connect() as conn:
        for ddl in [
            "ALTER TABLE run ADD COLUMN log VARCHAR",
        ]:
            try:
                conn.execute(text(ddl))
                conn.commit()
            except Exception:
                pass  # column already exists


def get_session():
    with Session(engine) as session:
        yield session
