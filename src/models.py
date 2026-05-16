from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    job_type: str = "google_form_fill"
    payload: str  # JSON string
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id")
    status: str = "pending"  # pending | running | success | failed
    result: Optional[str] = None  # JSON string
    log: Optional[str] = None  # JSON array of {ts, msg} progress entries
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
