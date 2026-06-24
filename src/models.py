from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Job(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    job_type: str = "google_form_fill"
    payload: str  # JSON string
    schedule: str | None = None  # cron expression, e.g. "0 8 * * *"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Run(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id")
    status: str = "pending"  # pending | running | success | failed
    result: str | None = None  # JSON string
    log: str | None = None  # JSON array of {ts, msg} progress entries
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    # Harness fields
    llm_provider: str | None = None
    llm_model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    retry_count: int = 0
    # Evaluation fields (LLM-as-judge quality score; informational only)
    eval_score: float | None = None        # 0-100 quality score
    eval_confidence: float | None = None    # 0-1 confidence in the score
    eval_notes: str | None = None           # short rationale
    eval_method: str | None = None          # "llm" | "heuristic"
