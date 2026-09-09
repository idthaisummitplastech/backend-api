from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.crud.crud_recruitment import crud_karyawan, crud_setting, crud_applicant, crud_submission
from app.crud.crud_auth import crud_admin
from app.models.auth import RecruitmentAdmin
from app.models.recruitment import Applicant, KaryawanSementara, InterviewSchedule, TestSubmission
from app.schemas.recruitment import (
    AdvanceStageRequest,
    KaryawanSementaraResponse,
)
from app.schemas.auth import (
    AdminCreate,
    AdminUpdate,
    AdminResponse,
)
from app.schemas.common import ApiResponse, StatusResponse
from app.services.recruitment_service import recruitment_service
from app.services.email_service import email_service
from app.core.config import settings
from app.api.deps import get_current_admin, RoleChecker
from app.core.security import get_password_hash

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


@router.post("/cleanup-applicants")
def cleanup_applicants(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "admin"])),
):
    """
    Database cleanup & optimization for applicants:
    - mode: 'soft_cleanup' (expire abandoned applicants >30 days and empty heavy CV files)
    - mode: 'hard_delete' (permanently delete failed applicants >30 days old)
    """
    mode = str(payload.get("mode") or "soft_cleanup")
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    # 1. Find abandoned applicants (in_progress > 30 days)
    abandoned = db.query(Applicant).filter(
        Applicant.stage_status == "in_progress",
        Applicant.created_at < thirty_days_ago,
    ).all()

    auto_expired_count = 0
    for a in abandoned:
        a.stage_status = "failed"
        a.failed_at_stage = a.current_stage
        a.rejection_reason = "Gugur Otomatis: Masa aktif seleksi berakhir (tidak ada aktivitas lebih dari 30 hari)."
        auto_expired_count += 1
    db.commit()

    if mode == "hard_delete":
        failed_old = db.query(Applicant).filter(
            Applicant.stage_status == "failed",
            Applicant.created_at < thirty_days_ago,
        ).all()

        hard_deleted_count = 0
        for f in failed_old:
            db.query(KaryawanSementara).filter(KaryawanSementara.applicant_id == f.id).delete()
            db.query(TestSubmission).filter(TestSubmission.applicant_id == f.id).delete()
            db.query(InterviewSchedule).filter(InterviewSchedule.applicant_id == f.id).delete()
            db.delete(f)
            hard_deleted_count += 1
        db.commit()

        return {
            "success": True,
            "message": f"Pembersihan Tuntas Selesai! {auto_expired_count} pelamar mangkir diubah statusnya menjadi Gugur, dan {hard_deleted_count} data pelamar kedaluwarsa dihapus permanen dari database.",
            "auto_expired_count": auto_expired_count,
            "autoExpiredCount": auto_expired_count,
            "hard_deleted_count": hard_deleted_count,
            "hardDeletedCount": hard_deleted_count,
        }

    # Default: Soft Cleanup (empty CV base64 files to save DB storage)
    failed_with_cv = db.query(Applicant).filter(
        Applicant.stage_status == "failed",
        Applicant.created_at < thirty_days_ago,
        Applicant.cv_file != "",
    ).all()

    purged_cv_count = 0
    for a in failed_with_cv:
        a.cv_file = ""
        a.cv_file_size = 0
        purged_cv_count += 1
    db.commit()

    return {
        "success": True,
        "message": f"Optimalisasi Database Selesai! {auto_expired_count} pelamar mangkir diubah statusnya menjadi Gugur, dan {purged_cv_count} berkas CV lama berhasil dikosongkan. Beban database berkurang drastis.",
        "auto_expired_count": auto_expired_count,
        "autoExpiredCount": auto_expired_count,
        "purged_cv_count": purged_cv_count,
        "purgedCvCount": purged_cv_count,
    }


@router.post("/schedule-interview")
def schedule_interview(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "user_dept", "admin"])),
):
    """Schedule or update interview date, platform, and meeting link."""
    applicant_id = int(payload.get("applicant_id") or payload.get("applicantId") or 0)
    interview_type = str(payload.get("interview_type") or payload.get("interviewType") or "hr")
    scheduled_at_str = str(payload.get("scheduled_at") or payload.get("scheduledAt") or "")
    location_mode = str(payload.get("location_mode") or payload.get("locationMode") or "online")
    meeting_platform = str(payload.get("meeting_platform") or payload.get("meetingPlatform") or "teams")
    meeting_link = payload.get("meeting_link") or payload.get("meetingLink")
    meeting_passcode = payload.get("meeting_passcode") or payload.get("meetingPasscode")
    interviewer_name = payload.get("interviewer_name") or payload.get("interviewerName") or current_admin.name
    notes = payload.get("notes")

    applicant = crud_applicant.get(db, applicant_id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Pelamar tidak ditemukan.")

    scheduled_at = None
    if scheduled_at_str:
        try:
            scheduled_at = datetime.fromisoformat(scheduled_at_str.replace("Z", "+00:00"))
        except Exception:
            scheduled_at = datetime.strptime(scheduled_at_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)

    schedule = InterviewSchedule(
        applicant_id=applicant.id,
        interview_type=interview_type,
        scheduled_at=scheduled_at or datetime.now(timezone.utc),
        location_mode=location_mode,
        meeting_platform=meeting_platform,
        meeting_link=meeting_link,
        meeting_passcode=meeting_passcode,
        interviewer_name=interviewer_name,
        notes=notes,
        status="scheduled",
    )
    db.add(schedule)
    db.commit()

    return {
        "success": True,
        "message": f"Jadwal wawancara ({interview_type.upper()}) berhasil ditetapkan.",
        "interview": {
            "id": schedule.id,
            "interview_type": schedule.interview_type,
            "scheduled_at": schedule.scheduled_at,
            "meeting_link": schedule.meeting_link,
        }
    }


@router.post("/reset-password")
def reset_applicant_password(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "admin"])),
):
    """Reset candidate password by HR/Admin."""
    applicant_id = int(payload.get("applicant_id") or payload.get("applicantId") or 0)
    new_password = str(payload.get("new_password") or payload.get("newPassword") or "").strip()

    if not applicant_id:
        raise HTTPException(status_code=400, detail="ID Pelamar wajib diisi.")
    if not new_password or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password baru minimal 6 karakter.")

    applicant = crud_applicant.get(db, applicant_id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Data pelamar tidak ditemukan.")

    applicant.password = get_password_hash(new_password)
    db.commit()

    return {"success": True, "message": f"Password pelamar {applicant.full_name} berhasil direset."}


@router.post("/reset-test")
def reset_applicant_test(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "admin"])),
):
    """Reset candidate exam session (clear lock & violations)."""
    applicant_id = int(payload.get("applicant_id") or payload.get("applicantId") or 0)
    test_type = str(payload.get("test_type") or payload.get("testType") or "").strip()

    if not applicant_id:
        raise HTTPException(status_code=400, detail="ID Pelamar wajib diisi.")

    query = db.query(TestSubmission).filter(TestSubmission.applicant_id == applicant_id)
    if test_type:
        query = query.filter(TestSubmission.test_type == test_type)

    submissions = query.all()
    for sub in submissions:
        sub.is_locked = False
        sub.violations_count = 0
        sub.submitted_at = None
        sub.score = 0
    db.commit()

    return {"success": True, "message": f"Sesi ujian berhasil direset. Pelamar dapat mengakses kembali ujian."}


@router.post("/resend-email")
def resend_stage_email(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "user_dept", "admin"])),
):
    """Kirim ulang email notifikasi sesuai tahap aktif pelamar (recovery bila email kelolosan tidak diterima)."""
    raw_id = payload.get("applicant_id") or payload.get("applicantId") or payload.get("id") or 0
    raw_email = str(payload.get("email") or "").strip().lower()
    try:
        applicant_id = int(raw_id) if raw_id else 0
    except (ValueError, TypeError):
        applicant_id = 0

    applicant = None
    if applicant_id:
        applicant = crud_applicant.get_with_details(db, applicant_id)
    elif raw_email:
        found = crud_applicant.get_by_email(db, raw_email)
        if found:
            applicant = crud_applicant.get_with_details(db, found.id)

    if not applicant:
        raise HTTPException(status_code=404, detail="Data pelamar tidak ditemukan.")

    job_title = applicant.job_posting.title if applicant.job_posting else "Posisi Terkait"
    stage = applicant.current_stage or 1
    status_value = (applicant.stage_status or "in_progress").lower()

    # 1. Pelamar gugur -> kirim ulang rejection notice
    if status_value == "failed":
        result = email_service.send_rejection_notice(
            to_email=applicant.email,
            name=applicant.full_name,
            position=job_title,
            reason=applicant.rejection_reason,
        )
        label = f"Tahap {stage} (Gugur)"
    # 2. Tahap 2 -> undangan psikotes
    elif stage == 2 and applicant.psikotes_token:
        test_url = f"{settings.FRONTEND_CAREER_URL}/portal/test/psikotes"
        result = email_service.send_screening_passed(
            to_email=applicant.email,
            name=applicant.full_name,
            position=job_title,
            token=applicant.psikotes_token,
            test_url=test_url,
        )
        label = "Tahap 2 (Psikotes)"
    # 3. Tahap 3 -> undangan ujian teknis user dept
    elif stage == 3 and applicant.user_test_token:
        test_url = f"{settings.FRONTEND_CAREER_URL}/portal/test/user-test"
        result = email_service.send_user_test_invitation(
            to_email=applicant.email,
            name=applicant.full_name,
            position=job_title,
            token=applicant.user_test_token,
            test_url=test_url,
        )
        label = "Tahap 3 (Ujian Teknis)"
    # 4. Tahap lain / token belum ada -> pengingat status generik
    else:
        result = email_service.send_stage_reminder(
            to_email=applicant.email,
            name=applicant.full_name,
            position=job_title,
            stage=stage,
            stage_status=applicant.stage_status,
        )
        label = f"Tahap {stage}"

    if not result.get("success"):
        raise HTTPException(
            status_code=502,
            detail=f"Gagal mengirim ulang email {label} ke {applicant.email}: {result.get('error') or 'kesalahan SMTP'}.",
        )

    return {"success": True, "message": f"Email notifikasi {label} berhasil dikirim ulang ke {applicant.email}."}


@router.post("/update-score")
def update_test_score(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "user_dept", "admin"])),
):
    """Update exam score, pass/fail status, and score visibility."""
    submission_id = payload.get("submission_id") or payload.get("submissionId")
    applicant_id = payload.get("applicant_id") or payload.get("applicantId")
    test_type = payload.get("test_type") or payload.get("testType")

    submission = None
    if submission_id:
        submission = db.query(TestSubmission).filter(TestSubmission.id == int(submission_id)).first()
    elif applicant_id and test_type:
        submission = db.query(TestSubmission).filter(
            TestSubmission.applicant_id == int(applicant_id),
            TestSubmission.test_type == str(test_type),
        ).first()

    if not submission:
        raise HTTPException(status_code=404, detail="Data submission ujian tidak ditemukan.")

    if "score" in payload:
        submission.score = int(payload["score"])
    if "is_passed" in payload or "isPassed" in payload:
        val = payload.get("is_passed") if "is_passed" in payload else payload.get("isPassed")
        submission.is_passed = bool(val)
    if "show_score" in payload or "showScore" in payload:
        val = payload.get("show_score") if "show_score" in payload else payload.get("showScore")
        submission.show_score = bool(val)

    db.commit()
    return {"success": True, "message": "Nilai ujian dan status kelulusan berhasil diperbarui."}


# --- RECRUITMENT ADMIN USERS CRUD ---
@router.get("/admins", response_model=ApiResponse[List[AdminResponse]])
def get_recruitment_admins(
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["admin"])),
):
    """List all recruitment ATS admin accounts."""
    admins = crud_admin.get_multi(db, limit=100)
    return ApiResponse(data=[AdminResponse.model_validate(a) for a in admins])


@router.post("/admins", response_model=ApiResponse[AdminResponse])
def create_recruitment_admin(
    payload: AdminCreate,
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["admin"])),
):
    """Create recruitment ATS admin user."""
    existing = crud_admin.get_by_username(db, payload.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username sudah digunakan.")
    new_admin = crud_admin.create(db, obj_in=payload)
    return ApiResponse(data=AdminResponse.model_validate(new_admin), message="Akun admin rekrutmen berhasil dibuat.")


@router.put("/admins/{id}", response_model=ApiResponse[AdminResponse])
def update_recruitment_admin(
    id: int,
    payload: AdminUpdate,
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["admin"])),
):
    """Update recruitment admin."""
    admin = crud_admin.get(db, id)
    if not admin:
        raise HTTPException(status_code=404, detail="Admin tidak ditemukan.")
    updated = crud_admin.update(db, db_obj=admin, obj_in=payload)
    return ApiResponse(data=AdminResponse.model_validate(updated), message="Data admin berhasil diperbarui.")


@router.delete("/admins/{id}", response_model=StatusResponse)
def delete_recruitment_admin(
    id: int,
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["admin"])),
):
    """Delete recruitment admin."""
    admin = crud_admin.get(db, id)
    if not admin:
        raise HTTPException(status_code=404, detail="Admin tidak ditemukan.")
    crud_admin.remove(db, id=id)
    return StatusResponse(message="Akun admin berhasil dihapus.")


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

