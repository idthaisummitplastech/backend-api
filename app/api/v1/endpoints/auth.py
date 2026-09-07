from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    ApplicantLoginRequest,
    Token,
    MFASetupResponse,
    MFAVerifyRequest,
    AdminResponse,
)
from app.schemas.common import ApiResponse
from app.services.auth_service import auth_service
from app.api.deps import get_current_admin, get_current_applicant
from app.models.auth import RecruitmentAdmin
from app.models.recruitment import Applicant
from app.core.middleware import limiter

router = APIRouter()


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
def login_admin(
    request: Request,
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    """Admin & Evaluator authentication with rate-limiting and 2FA support."""
    return auth_service.authenticate_admin(
        db,
        username_or_email=payload.username_or_email,
        password=payload.password,
        totp_code=payload.totp_code,
    )


@router.post("/applicant-login", response_model=Token)
@limiter.limit("15/minute")
def login_applicant(
    request: Request,
    payload: ApplicantLoginRequest,
    db: Session = Depends(get_db),
):
    """Career portal candidate login."""
    return auth_service.authenticate_applicant(
        db, email=payload.email, password=payload.password
    )


@router.get("/me/admin", response_model=ApiResponse[AdminResponse])
def get_current_admin_profile(
    current_admin: RecruitmentAdmin = Depends(get_current_admin),
):
    """Retrieve authenticated admin details."""
    return ApiResponse(data=AdminResponse.model_validate(current_admin))


@router.get("/me/applicant")
def get_current_applicant_profile(
    current_applicant: Applicant = Depends(get_current_applicant),
):
    """Retrieve authenticated applicant overview."""
    return {
        "id": current_applicant.id,
        "full_name": current_applicant.full_name,
        "email": current_applicant.email,
        "current_stage": current_applicant.current_stage,
        "stage_status": current_applicant.stage_status,
        "created_at": current_applicant.created_at,
    }


@router.post("/mfa/setup", response_model=ApiResponse[MFASetupResponse])
def setup_mfa(
    current_admin: RecruitmentAdmin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Generate 2FA TOTP secret and QR URI."""
    result = auth_service.setup_admin_mfa(db, current_admin.id)
    return ApiResponse(data=MFASetupResponse(**result))


@router.post("/mfa/verify", response_model=ApiResponse[bool])
def verify_mfa(
    payload: MFAVerifyRequest,
    current_admin: RecruitmentAdmin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Verify code and formally activate MFA on admin account."""
    success = auth_service.verify_and_enable_mfa(db, current_admin.id, payload.code)
    return ApiResponse(data=success, message="MFA 2-Faktor berhasil diaktifkan.")
