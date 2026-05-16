import json
from datetime import datetime, timezone

from sqlmodel import Session

from src.database import get_engine


def append_log(run_id: int, message: str):
    if not run_id:
        return
    with Session(get_engine()) as s:
        from src.models import Run
        run = s.get(Run, run_id)
        if run is None:
            return
        entries = json.loads(run.log) if run.log else []
        entries.append({"ts": datetime.now(timezone.utc).strftime("%H:%M:%S"), "msg": message})
        run.log = json.dumps(entries)
        s.add(run)
        s.commit()
