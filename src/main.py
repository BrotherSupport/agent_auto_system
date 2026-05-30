import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from src import telemetry as _tel
from src.database import get_engine, init_db, reconcile_stale_runs
from src.routers import jobs, runs, system

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _tel.setup(app)
    init_db()
    stale = reconcile_stale_runs()
    if stale:
        logger.warning("Marked %d stale run(s) as failed on startup", stale)
    yield


app = FastAPI(title="Agent Auto System", lifespan=lifespan)

app.include_router(jobs.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(system.router, prefix="/api")

if Path("ui").exists():
    app.mount("/ui", StaticFiles(directory="ui"), name="ui")


@app.get("/")
def root():
    return FileResponse("ui/index.html")


@app.get("/health")
def health():
    db_ok = False
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        logger.exception("Health check: DB connectivity failed")

    from src.automation.harness.provider import _CATALOG
    providers = {name: bool(os.getenv(cfg["env"])) for name, cfg in _CATALOG.items()}

    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "providers": providers,
    }
