import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from src.database import get_session
from src.models import Job

router = APIRouter()


class JobCreate(BaseModel):
    name: str
    job_type: str = "google_form_fill"
    payload: dict
    schedule: str | None = None  # cron expression, e.g. "0 8 * * *"


@router.get("/jobs")
def list_jobs(session: Session = Depends(get_session)):
    return session.exec(select(Job).order_by(Job.created_at.desc())).all()


@router.post("/jobs", status_code=201)
def create_job(data: JobCreate, session: Session = Depends(get_session)):
    job = Job(name=data.name, job_type=data.job_type, payload=json.dumps(data.payload), schedule=data.schedule)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.get("/jobs/{job_id}")
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    session.delete(job)
    session.commit()
