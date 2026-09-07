from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.crud.crud_recruitment import crud_job
from app.schemas.recruitment import JobPostingCreate, JobPostingUpdate, JobPostingResponse
from app.schemas.common import ApiResponse, StatusResponse
from app.api.deps import RoleChecker

router = APIRouter()


@router.get("", response_model=ApiResponse[List[JobPostingResponse]])
def get_public_open_jobs(db: Session = Depends(get_db)):
    """Fetch list of all active recruitment job postings (Public)."""
    jobs = crud_job.get_open_jobs(db)
    return ApiResponse(data=[JobPostingResponse.model_validate(j) for j in jobs])


@router.get("/all", response_model=ApiResponse[List[JobPostingResponse]])
def get_all_jobs_admin(
    db: Session = Depends(get_db),
    _admin=Depends(RoleChecker(["hr", "user_dept", "admin"])),
):
    """Fetch all job postings including draft & closed positions (Admin)."""
    jobs = crud_job.get_multi(db, limit=200)
    return ApiResponse(data=[JobPostingResponse.model_validate(j) for j in jobs])


@router.get("/{id}", response_model=ApiResponse[JobPostingResponse])
def get_job_detail(id: int, db: Session = Depends(get_db)):
    """Fetch single job detail by ID."""
    job = crud_job.get(db, id)
    if not job:
        raise HTTPException(status_code=404, detail="Lowongan pekerjaan tidak ditemukan.")
    return ApiResponse(data=JobPostingResponse.model_validate(job))


@router.post("", response_model=ApiResponse[JobPostingResponse], status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobPostingCreate,
    db: Session = Depends(get_db),
    _admin=Depends(RoleChecker(["hr", "admin"])),
):
    """Create a new job vacancy (HR & Admin only)."""
    job = crud_job.create(db, obj_in=payload)
    return ApiResponse(data=JobPostingResponse.model_validate(job), message="Lowongan kerja berhasil diterbitkan.")


@router.put("/{id}", response_model=ApiResponse[JobPostingResponse])
def update_job(
    id: int,
    payload: JobPostingUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(RoleChecker(["hr", "admin"])),
):
    """Update job vacancy information (HR & Admin only)."""
    job = crud_job.get(db, id)
    if not job:
        raise HTTPException(status_code=404, detail="Lowongan tidak ditemukan.")
    updated = crud_job.update(db, db_obj=job, obj_in=payload)
    return ApiResponse(data=JobPostingResponse.model_validate(updated), message="Data lowongan berhasil diperbarui.")


@router.delete("/{id}", response_model=StatusResponse)
def delete_job(
    id: int,
    db: Session = Depends(get_db),
    _admin=Depends(RoleChecker(["hr", "admin"])),
):
    """Delete a job posting (HR & Admin only)."""
    job = crud_job.get(db, id)
    if not job:
        raise HTTPException(status_code=404, detail="Lowongan tidak ditemukan.")
    crud_job.remove(db, id=id)
    return StatusResponse(message="Lowongan pekerjaan berhasil dihapus.")
