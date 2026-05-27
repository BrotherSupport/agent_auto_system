import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.database import init_db, reconcile_stale_runs
from src.routers import jobs, runs, system

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    return {"status": "ok"}
