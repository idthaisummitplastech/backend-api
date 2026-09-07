from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.crud.crud_recruitment import crud_karyawan, crud_setting
from app.models.auth import RecruitmentAdmin
from app.schemas.recruitment import (
    AdvanceStageRequest,
    KaryawanSementaraResponse,
)
from app.schemas.common import ApiResponse, StatusResponse
from app.services.recruitment_service import recruitment_service
from app.api.deps import get_current_admin, RoleChecker

router = APIRouter()


@router.post("/advance-stage")
def advance_stage_action(
    payload: AdvanceStageRequest,
    db: Session = Depends(get_db),
    current_admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "user_dept", "admin"])),
):
    """
    Execute stage advancement, rejection, or scheduling across the 7 recruitment stages.
    Enforces strict RBAC and departmental isolation.
    """
    result = recruitment_service.process_stage_action(db, admin=current_admin, payload=payload)
    return ApiResponse(message=result["message"])


@router.get("/karyawan-sementara", response_model=ApiResponse[List[KaryawanSementaraResponse]])
def get_karyawan_sementara_list(
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "admin"])),
):
    """Retrieve pre-onboarded candidates ready for ID card issuance and HRIS sync."""
    items = crud_karyawan.get_multi(db, limit=200)
    return ApiResponse(data=[KaryawanSementaraResponse.model_validate(k) for k in items])


@router.put("/karyawan-sementara/{id}/toggle-id-card", response_model=StatusResponse)
def toggle_id_card_printed(
    id: int,
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "admin"])),
):
    """Toggle ID card printed confirmation status."""
    karyawan = crud_karyawan.get(db, id)
    if not karyawan:
        raise HTTPException(status_code=404, detail="Data karyawan sementara tidak ditemukan.")
    karyawan.id_card_printed = not karyawan.id_card_printed
    db.commit()
    return StatusResponse(message=f"Status cetak ID Card diubah menjadi: {karyawan.id_card_printed}.")


@router.get("/settings", response_model=ApiResponse[Dict[str, str]])
def get_recruitment_settings(
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "admin"])),
):
    """Retrieve recruitment master settings (Clinic MCU, Interview Venues, Default URLs)."""
    settings = crud_setting.get_multi(db, limit=100)
    return ApiResponse(data={s.key: s.value for s in settings})


@router.post("/settings", response_model=StatusResponse)
def update_recruitment_settings(
    payload: Dict[str, str],
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "admin"])),
):
    """Update recruitment master settings."""
    for key, value in payload.items():
        crud_setting.set_value(db, key=key, value=value)
    return StatusResponse(message="Pengaturan sistem rekrutmen berhasil diperbarui.")
