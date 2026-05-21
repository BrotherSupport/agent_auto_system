from sqlmodel import Session

from src.database import get_engine
from src.models import Run


def update_run_metrics(
    run_id: int,
    llm_provider: str,
    llm_model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    retry_count: int,
) -> None:
    with Session(get_engine()) as s:
        run = s.get(Run, run_id)
        if run:
            run.llm_provider = llm_provider
            run.llm_model = llm_model
            run.tokens_in = tokens_in
            run.tokens_out = tokens_out
            run.cost_usd = cost_usd
            run.retry_count = retry_count
            s.add(run)
            s.commit()
