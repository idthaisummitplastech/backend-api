from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.crud.crud_recruitment import crud_applicant, crud_job
from app.models.auth import RecruitmentAdmin
from app.models.recruitment import Applicant
from app.schemas.recruitment import ApplicantCreate, ApplicantResponse
from app.schemas.common import ApiResponse
from app.api.deps import get_current_admin, get_current_applicant, RoleChecker
from app.core.middleware import limiter

router = APIRouter()


@router.post("/apply", response_model=ApiResponse[ApplicantResponse], status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def apply_job(
    request: Request,
    payload: ApplicantCreate,
    db: Session = Depends(get_db),
):
    """Candidate job application submission."""
    # Check if job exists and is open
    job = crud_job.get(db, payload.job_posting_id)
    if not job or not job.is_open:
        raise HTTPException(status_code=400, detail="Lowongan pekerjaan ini telah ditutup atau tidak aktif.")

    # Check duplicate email
    existing = crud_applicant.get_by_email(db, payload.email)
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Alamat email ini sudah terdaftar dalam sistem. Silakan login ke Portal Karir.",
        )

    # Create applicant
    applicant = crud_applicant.create(db, obj_in=payload)
    return ApiResponse(
        data=ApplicantResponse.model_validate(applicant),
        message="Pendaftaran berhasil! Silakan login untuk memantau status seleksi Anda.",
    )


@router.get("", response_model=ApiResponse[List[ApplicantResponse]])
def get_applicants_list(
    stage: Optional[int] = Query(None, ge=1, le=7),
    job_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "user_dept", "admin"])),
):
    """Retrieve applicant lists with automatic departmental scoping for User Dept."""
    filters = {}
    if stage:
        filters["current_stage"] = stage
    if job_id:
        filters["job_posting_id"] = job_id
    if status_filter:
        filters["stage_status"] = status_filter

    applicants = crud_applicant.get_multi(db, limit=300, filters=filters)

    # Departmental scoping for User Dept
    if admin.role == "user_dept" and admin.department:
        user_dept = admin.department.strip().lower()
        applicants = [
            a for a in applicants
            if a.job_posting and user_dept in (a.job_posting.department or "").lower()
        ]

    return ApiResponse(data=[ApplicantResponse.model_validate(a) for a in applicants])


@router.get("/{id}", response_model=ApiResponse[ApplicantResponse])
def get_applicant_detail(
    id: int,
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "user_dept", "admin"])),
):
    """Retrieve complete candidate dossier by ID."""
    applicant = crud_applicant.get_with_details(db, id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Data pelamar tidak ditemukan.")
    return ApiResponse(data=ApplicantResponse.model_validate(applicant))


@router.get("/me/tracking", response_model=ApiResponse[ApplicantResponse])
def get_applicant_self_tracking(
    current_applicant: Applicant = Depends(get_current_applicant),
    db: Session = Depends(get_db),
):
    """Candidate live recruitment status tracker."""
    applicant = crud_applicant.get_with_details(db, current_applicant.id)
    return ApiResponse(data=ApplicantResponse.model_validate(applicant))
