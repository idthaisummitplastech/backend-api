from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from app.services.employee_import_service import parse_employee_sheet

from app.db.session import get_db, get_db_company
from app.crud.crud_recruitment import (
    crud_karyawan,
    crud_setting,
    crud_applicant,
    crud_submission,
    crud_data_karyawan,
)
from app.crud.crud_auth import crud_admin
from app.models.auth import RecruitmentAdmin, User
from app.models.recruitment import (
    Applicant,
    KaryawanSementara,
    InterviewSchedule,
    TestSubmission,
    DataKaryawan,
)
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
    return {
        "success": True,
        "message": result["message"],
        "email_sent": result.get("email_sent", True),
        "email_error": result.get("email_error", None),
    }


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

    resolved_loc = payload.get("location_address") or payload.get("locationAddress") or payload.get("location")
    resolved_maps = payload.get("maps_url") or payload.get("mapsUrl") or payload.get("maps")
    resolved_room = payload.get("room_name") or payload.get("roomName") or payload.get("room")

    schedule = InterviewSchedule(
        applicant_id=applicant.id,
        interview_type=interview_type,
        scheduled_at=scheduled_at or datetime.now(timezone.utc),
        location_mode=location_mode,
        meeting_platform=meeting_platform,
        meeting_link=meeting_link,
        meeting_passcode=meeting_passcode,
        location_address=resolved_loc,
        maps_url=resolved_maps,
        room_name=resolved_room,
        interviewer_name=interviewer_name,
        notes=notes,
        status="scheduled",
    )
    db.add(schedule)
    db.commit()

    # Send official invitation email with maps URL
    job_title = applicant.job_posting.title if applicant.job_posting else "Posisi Terkait"
    email_service.send_interview_invitation(
        to_email=applicant.email,
        name=applicant.full_name,
        position=job_title,
        interview_type=interview_type,
        scheduled_at=schedule.scheduled_at,
        location_mode=location_mode,
        meeting_platform=meeting_platform,
        meeting_link=meeting_link,
        meeting_passcode=meeting_passcode,
        location_address=schedule.location_address,
        maps_url=schedule.maps_url,
        room_name=schedule.room_name,
        interviewer_name=interviewer_name,
        notes=notes,
    )

    return {
        "success": True,
        "message": f"Jadwal wawancara ({interview_type.upper()}) berhasil ditetapkan dan undangan telah dikirimkan ke email kandidat.",
        "interview": {
            "id": schedule.id,
            "interview_type": schedule.interview_type,
            "scheduled_at": schedule.scheduled_at,
            "meeting_link": schedule.meeting_link,
            "maps_url": schedule.maps_url,
        }
    }


@router.post("/reset-password")
def reset_applicant_password(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    db_company: Session = Depends(get_db_company),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "admin"])),
):
    """Reset candidate or staff/admin password by HR/Admin."""
    target_type = str(payload.get("targetType") or payload.get("target_type") or "").strip().lower()
    target_id = int(payload.get("targetId") or payload.get("target_id") or payload.get("applicant_id") or payload.get("applicantId") or 0)
    new_password = str(payload.get("new_password") or payload.get("newPassword") or "").strip()

    if not new_password or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password baru minimal 6 karakter.")

    if target_type == "admin":
        if not target_id:
            raise HTTPException(status_code=400, detail="ID Pengguna Staf/Admin wajib diisi.")

        hashed = get_password_hash(new_password)
        target_email = None
        user_name = "Pengguna"

        # 1. Update in company User (web_perusahaan)
        comp_user = db_company.query(User).filter(User.id == target_id).first()
        if comp_user:
            comp_user.password = hashed
            db_company.commit()
            target_email = comp_user.email
            user_name = comp_user.name
        else:
            rec_user = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.id == target_id).first()
            if not rec_user:
                raise HTTPException(status_code=404, detail="Akun staf/admin tidak ditemukan.")
            rec_user.password = hashed
            db.commit()
            target_email = rec_user.email
            user_name = rec_user.name

        # 2. Sync to other database
        if target_email:
            ra = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email.ilike(target_email)).first()
            if ra:
                ra.password = hashed
                db.commit()
            cu = db_company.query(User).filter(User.email.ilike(target_email)).first()
            if cu:
                cu.password = hashed
                db_company.commit()

        return {"success": True, "message": f"Password akun staf/admin {user_name} berhasil direset."}

    # Default: Reset Applicant Password
    if not target_id:
        raise HTTPException(status_code=400, detail="ID Pelamar wajib diisi.")

    applicant = crud_applicant.get(db, target_id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Data pelamar tidak ditemukan.")

    applicant.password = get_password_hash(new_password)
    db.commit()

    return {"success": True, "message": f"Password pelamar {applicant.full_name} berhasil direset."}


@router.post("/reset-test")
def reset_applicant_test(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "user_dept", "admin"])),
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
    if not submissions:
        raise HTTPException(status_code=404, detail="Tidak ada data sesi ujian yang ditemukan untuk pelamar ini.")

    for sub in submissions:
        db.delete(sub)
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
    result = []
    for k in items:
        resp = KaryawanSementaraResponse.model_validate(k)
        if not resp.photo_url and k.applicant and k.applicant.photo_file:
            resp.photo_url = k.applicant.photo_file
        result.append(resp)
    return ApiResponse(data=result)


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


# --- OFFICIAL COMPANY EMPLOYEES & CONTRACT SIGNING ---

@router.get("/employee-sequence")
def get_employee_sequence(
    join_date: Optional[str] = Query(None),
    custom_seq: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "admin"])),
):
    """Preview next sequential employee ID in format {id}.{MM}.{YY}."""
    info = crud_data_karyawan.preview_next_employee_id(db, join_date_val=join_date, custom_sequence=custom_seq)
    return {"success": True, **info}


@router.post("/employee-sequence")
def set_employee_sequence(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "admin"])),
):
    """Set/adjust the last employee sequence number."""
    seq = int(payload.get("sequence") or payload.get("last_sequence") or 0)
    if seq <= 0:
        raise HTTPException(status_code=400, detail="Nomor sequence harus lebih besar dari 0.")
    crud_data_karyawan.set_last_sequence(db, seq)
    return {"success": True, "message": f"Nomor urut ID terakhir berhasil disesuaikan menjadi: {seq}."}


@router.post("/hire-contract")
def hire_and_sign_contract(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "admin"])),
):
    """
    Official contract signing & employee onboarding by HR:
    - Transfers all applicant personal data & files to data_karyawan
    - Automatically assigns sequential employee ID {id}.{MM}.{YY} (e.g. 1530.09.26)
    - Saves contract start date (Join Date) and contract end date
    - Updates applicant status to hired and removes all action buttons in ATS
    """
    applicant_id = int(payload.get("applicant_id") or payload.get("applicantId") or 0)
    if not applicant_id:
        raise HTTPException(status_code=400, detail="ID Pelamar wajib disertakan.")

    applicant = crud_applicant.get_with_details(db, applicant_id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Data pelamar tidak ditemukan.")

    # Check if already hired
    existing_emp = crud_data_karyawan.get_by_applicant_id(db, applicant.id)
    if existing_emp:
        raise HTTPException(
            status_code=400,
            detail=f"Kandidat ini sudah terdaftar sebagai karyawan resmi dengan ID: {existing_emp.employee_id}."
        )

    # Parse contract dates
    start_date_raw = payload.get("contract_start_date") or payload.get("contractStartDate") or applicant.offering_join_date
    end_date_raw = payload.get("contract_end_date") or payload.get("contractEndDate")

    start_dt = None
    if start_date_raw:
        try:
            start_dt = datetime.fromisoformat(str(start_date_raw)[:10]).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    if not start_dt:
        start_dt = datetime.now(timezone.utc)

    end_dt = None
    if end_date_raw:
        try:
            end_dt = datetime.fromisoformat(str(end_date_raw)[:10]).replace(tzinfo=timezone.utc)
        except Exception:
            pass

    custom_seq = payload.get("sequence_number") or payload.get("sequenceNumber")
    if custom_seq:
        custom_seq = int(custom_seq)

    preview = crud_data_karyawan.preview_next_employee_id(db, join_date_val=start_dt, custom_sequence=custom_seq)
    employee_id = preview["employee_id"]
    seq_number = preview["next_sequence"]

    # Calculate duration in months
    duration_months = 12
    if end_dt and start_dt:
        diff_days = (end_dt - start_dt).days
        duration_months = max(1, round(diff_days / 30.4))

    dept = payload.get("department") or (applicant.job_posting.department if applicant.job_posting else "General")
    title = payload.get("job_title") or (applicant.job_posting.title if applicant.job_posting else "Karyawan")
    loc = payload.get("work_location") or "Plant PT ITSP Karawang"
    sal = payload.get("salary") or applicant.offering_salary or "Sesuai Standar Perusahaan"
    c_status = payload.get("contract_status") or "PKWT 1"

    emp = DataKaryawan(
        employee_id=employee_id,
        sequence_number=seq_number,
        applicant_id=applicant.id,
        full_name=applicant.full_name,
        first_name=applicant.first_name,
        last_name=applicant.last_name,
        nik=applicant.nik,
        email=applicant.email,
        phone=applicant.phone,
        birth_place=applicant.birth_place,
        birth_date=applicant.birth_date,
        age=applicant.age,
        gender=applicant.gender,
        religion=applicant.religion,
        ethnic=applicant.ethnic,
        height_cm=applicant.height_cm,
        weight_kg=applicant.weight_kg,
        marriage_status=applicant.marriage_status,
        blood_type=payload.get("blood_type"),
        address_ktp=applicant.address_ktp,
        province_ktp=applicant.province_ktp,
        city_ktp=applicant.city_ktp,
        district_ktp=applicant.district_ktp,
        village_ktp=applicant.village_ktp,
        rt_ktp=applicant.rt_ktp,
        rw_ktp=applicant.rw_ktp,
        street_ktp=applicant.street_ktp,
        domicile_same_as_ktp=applicant.domicile_same_as_ktp,
        address_domicile=applicant.address_domicile,
        province_domicile=applicant.province_domicile,
        city_domicile=applicant.city_domicile,
        district_domicile=applicant.district_domicile,
        village_domicile=applicant.village_domicile,
        rt_domicile=applicant.rt_domicile,
        rw_domicile=applicant.rw_domicile,
        street_domicile=applicant.street_domicile,
        last_education=applicant.last_education,
        school_name=applicant.school_name,
        major=applicant.major,
        education_history=applicant.education_history,
        work_history=applicant.work_history,
        family_parents=applicant.family_parents,
        family_siblings=applicant.family_siblings,
        job_title=title,
        department=dept,
        work_location=loc,
        salary=sal,
        contract_start_date=start_dt,
        contract_end_date=end_dt,
        contract_duration_months=duration_months,
        contract_status=c_status,
        employee_status="active",
        photo_file=applicant.photo_file,
        ktp_file=applicant.ktp_file,
        kk_file=applicant.kk_file,
        ijazah_file=applicant.ijazah_file,
        transkrip_file=applicant.transkrip_file,
        npwp_file=applicant.npwp_file,
        bpjs_kesehatan_file=applicant.bpjs_kesehatan_file,
        bpjs_ketenagakerjaan_file=applicant.bpjs_ketenagakerjaan_file,
        skck_file=applicant.skck_file,
        cv_file=applicant.cv_file,
        signed_contract_file=applicant.signed_contract_file,
        hired_at=datetime.now(timezone.utc),
        notes=payload.get("notes"),
    )

    db.add(emp)

    # Mark applicant as hired & employee
    applicant.is_employee = True
    applicant.employee_id = employee_id
    applicant.stage_status = "hired"

    # Update sequence tracker
    crud_data_karyawan.set_last_sequence(db, seq_number)

    db.commit()
    db.refresh(emp)

    return {
        "success": True,
        "message": f"Penandatanganan kontrak selesai! {applicant.full_name} resmi diangkat sebagai karyawan PT ITSP dengan Nomor ID: {employee_id}.",
        "employee_id": employee_id,
        "employee": {
            "id": emp.id,
            "employee_id": emp.employee_id,
            "full_name": emp.full_name,
            "department": emp.department,
            "job_title": emp.job_title,
            "contract_start_date": emp.contract_start_date.isoformat() if emp.contract_start_date else None,
            "contract_end_date": emp.contract_end_date.isoformat() if emp.contract_end_date else None,
            "contract_status": emp.contract_status,
        },
    }


@router.get("/employees")
def get_employees_list(
    department: Optional[str] = Query(None),
    contract_status: Optional[str] = Query(None),
    employee_status: Optional[str] = Query(None),
    contract_eval: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort: Optional[str] = Query("desc"),
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "admin"])),
):
    """Retrieve full employee lists with filter and search."""
    query = db.query(DataKaryawan)
    if department:
        d = department.strip()
        d_lower = d.lower()
        # Use exact case-insensitive match first, then fallback to grouped aliases
        if d_lower in ("information technology", "it", "syd & it", "syd & it", "syd"):
            # Match exactly "SYD & IT" or anything containing "SYD" — NOT broad "%it%"
            query = query.filter(
                (DataKaryawan.department.ilike("SYD & IT")) |
                (DataKaryawan.department.ilike("SYD%IT%")) |
                (DataKaryawan.department.ilike("%SYD%"))
            )
        elif d_lower in ("human resources & ga", "hr & ga", "hr", "hrga", "human resources"):
            query = query.filter(
                (DataKaryawan.department.ilike("HR & GA")) |
                (DataKaryawan.department.ilike("%HR%GA%")) |
                (DataKaryawan.department.ilike("Human Resources%"))
            )
        elif d_lower in ("quality control", "quality assurance", "qc", "qa"):
            query = query.filter(
                (DataKaryawan.department.ilike("Quality Assurance")) |
                (DataKaryawan.department.ilike("Quality Control")) |
                (DataKaryawan.department.ilike("%Quality%")) |
                (DataKaryawan.department.ilike("%QA%")) |
                (DataKaryawan.department.ilike("%QC%"))
            )
        elif d_lower in ("supply chain / warehouse", "warehouse & delivery", "warehouse", "delivery"):
            query = query.filter(
                (DataKaryawan.department.ilike("Warehouse & Delivery")) |
                (DataKaryawan.department.ilike("%Warehouse%")) |
                (DataKaryawan.department.ilike("%Delivery%"))
            )
        elif d_lower in ("accounting & finance", "accounting", "finance"):
            query = query.filter(
                (DataKaryawan.department.ilike("Accounting & Finance")) |
                (DataKaryawan.department.ilike("%Accounting%")) |
                (DataKaryawan.department.ilike("%Finance%"))
            )
        else:
            # Exact match first, then partial
            query = query.filter(DataKaryawan.department.ilike(d))
    if contract_status:
        cs = contract_status.strip().upper()
        if cs == "PKWT":
            # Exclude PKWTT — only match PKWT 1, PKWT 2, etc.
            query = query.filter(
                DataKaryawan.contract_status.ilike("PKWT%"),
                ~DataKaryawan.contract_status.ilike("PKWTT%")
            )
        elif cs == "TRAINEE":
            query = query.filter(DataKaryawan.contract_status.ilike("Trainee%"))
        elif cs == "PKWTT":
            query = query.filter((DataKaryawan.contract_status.ilike("%PKWTT%")) | (DataKaryawan.contract_status.ilike("%Tetap%")))
        elif cs == "EXPATRIATE":
            query = query.filter((DataKaryawan.contract_status.ilike("%Expat%")) | (DataKaryawan.contract_status.ilike("%TSP%")))
        else:
            query = query.filter(DataKaryawan.contract_status.ilike(f"%{cs}%"))
    if contract_eval == "expiring_soon":
        # Perlu evaluasi perpanjangan: kontrak habis dalam <= 30 hari ke depan, exclude PKWTT
        now = datetime.now(timezone.utc)
        thirty_days = now + timedelta(days=30)
        lower_bound = now - timedelta(days=1)
        query = query.filter(
            DataKaryawan.contract_end_date.isnot(None),
            DataKaryawan.contract_end_date >= lower_bound,
            DataKaryawan.contract_end_date <= thirty_days,
            ~DataKaryawan.contract_status.ilike("%PKWTT%"),
            ~DataKaryawan.contract_status.ilike("%Tetap%"),
        )
        if not contract_status or contract_status.strip().upper() != "TRAINEE":
            query = query.filter(~DataKaryawan.contract_status.ilike("Trainee%"))
    elif contract_eval == "expired":
        now = datetime.now(timezone.utc)
        query = query.filter(
            DataKaryawan.contract_end_date.isnot(None),
            DataKaryawan.contract_end_date < now - timedelta(days=1),
            ~DataKaryawan.contract_status.ilike("%PKWTT%"),
            ~DataKaryawan.contract_status.ilike("%Tetap%"),
        )
    elif contract_eval == "safe":
        now = datetime.now(timezone.utc)
        thirty_days = now + timedelta(days=30)
        query = query.filter(
            DataKaryawan.contract_end_date.isnot(None),
            DataKaryawan.contract_end_date > thirty_days,
        )
    if employee_status and employee_status != "all":
        query = query.filter(DataKaryawan.employee_status == employee_status)
    elif not employee_status:
        # By default, only show active employees (exclude resigned/terminated)
        query = query.filter(DataKaryawan.employee_status != "resign")
    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            (DataKaryawan.full_name.ilike(s)) |
            (DataKaryawan.employee_id.ilike(s)) |
            (DataKaryawan.nik.ilike(s)) |
            (DataKaryawan.email.ilike(s)) |
            (DataKaryawan.job_title.ilike(s)) |
            (DataKaryawan.department.ilike(s))
        )

    if sort and str(sort).lower() == "asc":
        employees = query.order_by(DataKaryawan.sequence_number.asc(), DataKaryawan.id.asc()).all()
    else:
        employees = query.order_by(DataKaryawan.sequence_number.desc(), DataKaryawan.id.desc()).all()
    return {
        "success": True,
        "total": len(employees),
        "employees": [
            {
                "id": e.id,
                "employee_id": e.employee_id,
                "sequence_number": e.sequence_number,
                "applicant_id": e.applicant_id,
                "full_name": e.full_name,
                "first_name": e.first_name,
                "last_name": e.last_name,
                "nik": e.nik,
                "email": e.email,
                "phone": e.phone,
                "birth_place": e.birth_place,
                "birth_date": e.birth_date.isoformat() if e.birth_date else None,
                "age": e.age,
                "gender": e.gender,
                "religion": e.religion,
                "ethnic": e.ethnic,
                "height_cm": e.height_cm,
                "weight_kg": e.weight_kg,
                "marriage_status": e.marriage_status,
                "blood_type": e.blood_type,
                "address_ktp": e.address_ktp,
                "city_ktp": e.city_ktp,
                "province_ktp": e.province_ktp,
                "address_domicile": e.address_domicile,
                "last_education": e.last_education,
                "school_name": e.school_name,
                "major": e.major,
                "education_history": e.education_history,
                "work_history": e.work_history,
                "family_parents": e.family_parents,
                "family_siblings": e.family_siblings,
                "job_title": e.job_title,
                "department": e.department,
                "work_location": e.work_location,
                "salary": e.salary,
                "contract_start_date": e.contract_start_date.isoformat() if e.contract_start_date else None,
                "contract_end_date": e.contract_end_date.isoformat() if e.contract_end_date else None,
                "contract_duration_months": e.contract_duration_months,
                "contract_status": e.contract_status,
                "contract_sequence": e.contract_sequence,
                "contract_history": e.contract_history,
                "years_of_service": e.years_of_service,
                "level": e.level,
                "section": e.section,
                "employee_type": e.employee_type,
                "factory_office": e.factory_office,
                "employee_status": e.employee_status,
                "photo_file": e.photo_file,
                "ktp_file": e.ktp_file,
                "kk_file": e.kk_file,
                "ijazah_file": e.ijazah_file,
                "npwp_file": e.npwp_file,
                "bpjs_kesehatan_file": e.bpjs_kesehatan_file,
                "bpjs_ketenagakerjaan_file": e.bpjs_ketenagakerjaan_file,
                "skck_file": e.skck_file,
                "signed_contract_file": e.signed_contract_file,
                "hired_at": e.hired_at.isoformat() if e.hired_at else None,
                "notes": e.notes,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "national_id": e.nik,
                "join_date": e.contract_start_date.isoformat() if e.contract_start_date else None,
                "photo_profile": e.photo_file,
                "agreed_salary": e.salary,
                "marital_status": e.marriage_status,
                "ptkp_status": e.ptkp_status,
                "education_level": e.last_education,
                "institution_name": e.school_name,
                "ktp_street_address": e.address_ktp or e.street_ktp,
                "domicile_street_address": e.address_domicile or e.street_domicile,
                "work_experiences": e.work_history,
                "payroll_id": e.payroll_id,
                "plant": e.plant,
                "npwp": e.npwp,
                "bpjs_tk_no": e.bpjs_tk_no,
                "account_no": e.account_no,
                "bank_account_no": e.bank_account_no,
                "bank_name": e.bank_name,
                "father_name": e.father_name,
                "mother_name": e.mother_name,
                "spouse_name": e.spouse_name,
                "family_children": e.family_children,
                "family_members_count": e.family_members_count,
                "exit_date": e.exit_date.isoformat() if e.exit_date else None,
                "exit_reason": e.exit_reason,
            }
            for e in employees
        ]
    }


@router.get("/departments")
def get_recruitment_departments(
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["admin", "hr", "user_dept"])),
):
    """Get list of distinct departments from data_karyawan for dropdown/autocomplete selection."""
    depts = db.query(DataKaryawan.department).distinct().all()
    clean_depts = sorted(list(set(d[0].strip() for d in depts if d[0] and d[0].strip())))
    return {"success": True, "departments": clean_depts}



@router.get("/employees/{id}")
def get_employee_detail(
    id: int,
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "admin"])),
):
    """Retrieve complete profile of a single employee."""
    emp = crud_data_karyawan.get(db, id)
    if not emp:
        raise HTTPException(status_code=404, detail="Data karyawan tidak ditemukan.")

    return {
        "success": True,
        "employee": {
            "id": emp.id,
            "employee_id": emp.employee_id,
            "sequence_number": emp.sequence_number,
            "applicant_id": emp.applicant_id,
            "full_name": emp.full_name,
            "first_name": emp.first_name,
            "last_name": emp.last_name,
            "nik": emp.nik,
            "email": emp.email,
            "phone": emp.phone,
            "birth_place": emp.birth_place,
            "birth_date": emp.birth_date.isoformat() if emp.birth_date else None,
            "age": emp.age,
            "gender": emp.gender,
            "religion": emp.religion,
            "ethnic": emp.ethnic,
            "height_cm": emp.height_cm,
            "weight_kg": emp.weight_kg,
            "marriage_status": emp.marriage_status,
            "blood_type": emp.blood_type,
            "address_ktp": emp.address_ktp,
            "province_ktp": emp.province_ktp,
            "city_ktp": emp.city_ktp,
            "district_ktp": emp.district_ktp,
            "village_ktp": emp.village_ktp,
            "rt_ktp": emp.rt_ktp,
            "rw_ktp": emp.rw_ktp,
            "street_ktp": emp.street_ktp,
            "domicile_same_as_ktp": emp.domicile_same_as_ktp,
            "address_domicile": emp.address_domicile,
            "province_domicile": emp.province_domicile,
            "city_domicile": emp.city_domicile,
            "district_domicile": emp.district_domicile,
            "village_domicile": emp.village_domicile,
            "rt_domicile": emp.rt_domicile,
            "rw_domicile": emp.rw_domicile,
            "street_domicile": emp.street_domicile,
            "last_education": emp.last_education,
            "school_name": emp.school_name,
            "major": emp.major,
            "education_history": emp.education_history,
            "work_history": emp.work_history,
            "family_parents": emp.family_parents,
            "family_siblings": emp.family_siblings,
            "job_title": emp.job_title,
            "department": emp.department,
            "work_location": emp.work_location,
            "salary": emp.salary,
            "contract_start_date": emp.contract_start_date.isoformat() if emp.contract_start_date else None,
            "contract_end_date": emp.contract_end_date.isoformat() if emp.contract_end_date else None,
            "contract_duration_months": emp.contract_duration_months,
            "contract_status": emp.contract_status,
            "contract_sequence": emp.contract_sequence,
            "contract_history": emp.contract_history,
            "years_of_service": emp.years_of_service,
            "level": emp.level,
            "section": emp.section,
            "employee_type": emp.employee_type,
            "factory_office": emp.factory_office,
            "employee_status": emp.employee_status,
            "photo_file": emp.photo_file,
            "ktp_file": emp.ktp_file,
            "kk_file": emp.kk_file,
            "ijazah_file": emp.ijazah_file,
            "transkrip_file": emp.transkrip_file,
            "npwp_file": emp.npwp_file,
            "bpjs_kesehatan_file": emp.bpjs_kesehatan_file,
            "bpjs_ketenagakerjaan_file": emp.bpjs_ketenagakerjaan_file,
            "skck_file": emp.skck_file,
            "cv_file": emp.cv_file,
            "signed_contract_file": emp.signed_contract_file,
            "hired_at": emp.hired_at.isoformat() if emp.hired_at else None,
            "notes": emp.notes,
            "created_at": emp.created_at.isoformat() if emp.created_at else None,
            "national_id": emp.nik,
            "join_date": emp.contract_start_date.isoformat() if emp.contract_start_date else None,
            "photo_profile": emp.photo_file,
            "agreed_salary": emp.salary,
            "marital_status": emp.marriage_status,
            "ptkp_status": emp.ptkp_status,
            "education_level": emp.last_education,
            "institution_name": emp.school_name,
            "ktp_street_address": emp.address_ktp or emp.street_ktp,
            "domicile_street_address": emp.address_domicile or emp.street_domicile,
            "work_experiences": emp.work_history,
            "payroll_id": emp.payroll_id,
            "plant": emp.plant,
            "npwp": emp.npwp,
            "bpjs_tk_no": emp.bpjs_tk_no,
            "account_no": emp.account_no,
            "bank_account_no": emp.bank_account_no,
            "bank_name": emp.bank_name,
            "father_name": emp.father_name,
            "mother_name": emp.mother_name,
            "spouse_name": emp.spouse_name,
            "family_children": emp.family_children,
            "family_members_count": emp.family_members_count,
            "exit_date": emp.exit_date.isoformat() if emp.exit_date else None,
            "exit_reason": emp.exit_reason,
        }
    }


@router.put("/employees/{id}")
def update_employee(
    id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "admin"])),
):
    """Update employee details or contract renewal."""
    emp = crud_data_karyawan.get(db, id)
    if not emp:
        raise HTTPException(status_code=404, detail="Data karyawan tidak ditemukan.")

    # Map common aliases from frontend
    alias_map = {
        "join_date": "contract_start_date",
        "agreed_salary": "salary",
        "national_id": "nik",
        "education_level": "last_education",
        "institution_name": "school_name",
        "ktp_street_address": "address_ktp",
        "domicile_street_address": "address_domicile",
        "marital_status": "marriage_status",
    }
    for alias, target in alias_map.items():
        if alias in payload and target not in payload:
            payload[target] = payload[alias]

    for field in [
        "full_name", "phone", "email", "job_title", "department", "work_location",
        "salary", "contract_status", "contract_sequence", "contract_history", "years_of_service",
        "level", "section", "employee_type", "factory_office",
        "payroll_id", "plant", "ptkp_status", "npwp", "bpjs_tk_no", "account_no", "bank_account_no", "bank_name",
        "father_name", "mother_name", "spouse_name", "family_children", "family_members_count",
        "employee_status", "exit_date", "exit_reason", "notes", "blood_type",
        "marriage_status", "address_ktp", "address_domicile",
        "nik", "birth_place", "age", "gender", "religion",
        "last_education", "major", "school_name", "photo_file",
    ]:
        if field in payload:
            setattr(emp, field, payload[field])

    if "photo_profile" in payload and payload["photo_profile"]:
        emp.photo_file = payload["photo_profile"]

    if "birth_date" in payload:
        if payload["birth_date"]:
            try:
                emp.birth_date = datetime.fromisoformat(str(payload["birth_date"])[:10]).replace(tzinfo=timezone.utc)
            except Exception:
                pass
        else:
            emp.birth_date = None

    if "contract_start_date" in payload and payload["contract_start_date"]:
        try:
            emp.contract_start_date = datetime.fromisoformat(str(payload["contract_start_date"])[:10]).replace(tzinfo=timezone.utc)
        except Exception:
            pass

    if "contract_end_date" in payload:
        if payload["contract_end_date"]:
            try:
                emp.contract_end_date = datetime.fromisoformat(str(payload["contract_end_date"])[:10]).replace(tzinfo=timezone.utc)
            except Exception:
                pass
        else:
            emp.contract_end_date = None

    db.commit()
    return {"success": True, "message": "Data karyawan berhasil diperbarui."}


@router.get("/employees/template")
def download_employee_template():
    """Download standard Excel template for master employee import."""
    import os
    from fastapi.responses import FileResponse

    file_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "static", "Template_Master_Karyawan_ITSP.xlsx")
    )
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File template tidak ditemukan.")
    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="Template_Master_Karyawan_ITSP.xlsx",
    )


@router.post("/employees/import-excel")
async def import_employees_excel(
    file: UploadFile = File(...),
    include_out: bool = Form(False),
    replace_all: bool = Form(False),
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["admin", "hr"])),
):
    """Import Master Employee Excel file into data_karyawan."""
    import openpyxl
    import io

    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Format file harus berupa Excel (.xlsx atau .xls).")

    contents = await file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(contents), data_only=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Gagal membaca file Excel: {str(exc)}")

    all_employees = []

    # Dynamically match employee sheet (ITSP, Employee, Karyawan, Staff, Pegawai)
    emp_sheet = None
    for s in wb.sheetnames:
        if s.lower() in ("itsp", "employee", "karyawan", "staff", "pegawai", "tetap"):
            emp_sheet = s
            break

    # Dynamically match trainee sheet (Trainee, Traine, Magang, Pemagangan, Training)
    trainee_sheet = None
    for s in wb.sheetnames:
        if any(kw in s.lower() for kw in ("trainee", "traine", "magang", "pemagangan", "training")):
            trainee_sheet = s
            break

    # Dynamically match out/resign sheet (Out, Resign, Keluar, Nonaktif)
    out_sheet = None
    for s in wb.sheetnames:
        if any(kw in s.lower() for kw in ("out", "resign", "keluar", "nonaktif")):
            out_sheet = s
            break

    if emp_sheet:
        all_employees.extend(parse_employee_sheet(wb[emp_sheet], emp_sheet, default_emp_status="active"))
    if trainee_sheet:
        all_employees.extend(parse_employee_sheet(wb[trainee_sheet], trainee_sheet, default_emp_status="active"))
    if include_out and out_sheet:
        all_employees.extend(parse_employee_sheet(wb[out_sheet], out_sheet, default_emp_status="resign"))

    # Fallback if specific sheets not matched: scan all sheets
    if not all_employees and wb.sheetnames:
        for s in wb.sheetnames:
            all_employees.extend(parse_employee_sheet(wb[s], s, default_emp_status="active"))

    if not all_employees:
        raise HTTPException(status_code=400, detail="Tidak ada data karyawan yang valid ditemukan di dalam file Excel.")

    if replace_all:
        db.query(Applicant).filter(Applicant.is_employee == True).update({"is_employee": False, "employee_id": None})
        db.query(DataKaryawan).delete()
        db.commit()

    existing_map = {e.employee_id: e for e in db.query(DataKaryawan).all()}
    inserted_count = 0
    updated_count = 0
    seq_counter = len(existing_map) + 1

    for emp in all_employees:
        emp_id = emp["employee_id"]
        if emp_id in existing_map:
            existing_obj = existing_map[emp_id]
            for k, v in emp.items():
                if k not in ("id", "employee_id", "applicant_id") and v is not None:
                    setattr(existing_obj, k, v)
            updated_count += 1
        else:
            if not emp.get("sequence_number"):
                emp["sequence_number"] = seq_counter
                seq_counter += 1
            new_obj = DataKaryawan(**emp)
            db.add(new_obj)
            existing_map[emp_id] = new_obj
            inserted_count += 1

    db.commit()
    return {
        "success": True,
        "message": f"Berhasil mengimpor {inserted_count} data karyawan baru dan memperbarui {updated_count} data karyawan (Total: {len(all_employees)} data).",
        "inserted": inserted_count,
        "updated": updated_count,
        "total": len(all_employees),
    }


@router.delete("/employees/all")
def delete_all_employees(
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["admin", "hr"])),
):
    """Delete all employee records from data_karyawan (Reset master data)."""
    db.query(Applicant).filter(Applicant.is_employee == True).update({"is_employee": False, "employee_id": None})
    deleted_count = db.query(DataKaryawan).delete()
    db.commit()
    return {
        "success": True,
        "message": f"Seluruh data karyawan ({deleted_count} data) berhasil dihapus dari sistem.",
        "deleted_count": deleted_count,
    }


@router.delete("/employees/{id}")
def delete_employee(
    id: int,
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["admin", "hr"])),
):
    """Delete single employee record (Admin or HR)."""
    emp = crud_data_karyawan.get(db, id)
    if not emp:
        raise HTTPException(status_code=404, detail="Data karyawan tidak ditemukan.")

    # Revert applicant employee flag if linked
    if emp.applicant_id:
        app = crud_applicant.get(db, emp.applicant_id)
        if app:
            app.is_employee = False
            app.employee_id = None

    crud_data_karyawan.remove(db, id=id)
    return {"success": True, "message": f"Data karyawan {emp.full_name} ({emp.employee_id}) berhasil dihapus."}


@router.post("/employees")
def create_employee_manual(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["admin", "hr"])),
):
    """Create a new employee manually (PKWT, PKWTT, Trainee, Expatriate)."""
    full_name = str(payload.get("full_name") or "").strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="Nama lengkap wajib diisi.")

    contract_status = str(payload.get("contract_status") or "PKWT").strip()
    job_title = str(payload.get("job_title") or "Staff").strip()
    department = str(payload.get("department") or "General").strip()

    # Determine or generate employee ID
    custom_emp_id = str(payload.get("employee_id") or "").strip()
    start_date_raw = payload.get("contract_start_date") or payload.get("join_date")
    start_date = None
    if start_date_raw:
        try:
            start_date = datetime.fromisoformat(str(start_date_raw)[:10]).replace(tzinfo=timezone.utc)
        except Exception:
            start_date = datetime.now(timezone.utc)
    else:
        start_date = datetime.now(timezone.utc)

    if custom_emp_id:
        exist = db.query(DataKaryawan).filter(DataKaryawan.employee_id == custom_emp_id).first()
        if exist:
            raise HTTPException(status_code=400, detail=f"ID Karyawan {custom_emp_id} sudah digunakan.")
        emp_id = custom_emp_id
        seq_num = None
    else:
        preview = crud_data_karyawan.preview_next_employee_id(db, join_date_val=start_date)
        emp_id = preview["preview_employee_id"]
        seq_num = preview["next_sequence"]
        crud_data_karyawan.set_last_sequence(db, seq_num)

    end_date_raw = payload.get("contract_end_date")
    end_date = None
    if end_date_raw and "PKWTT" not in contract_status.upper():
        try:
            end_date = datetime.fromisoformat(str(end_date_raw)[:10]).replace(tzinfo=timezone.utc)
        except Exception:
            end_date = None

    birth_date_raw = payload.get("birth_date")
    birth_date = None
    if birth_date_raw:
        try:
            birth_date = datetime.fromisoformat(str(birth_date_raw)[:10]).replace(tzinfo=timezone.utc)
        except Exception:
            birth_date = None

    emp = DataKaryawan(
        employee_id=emp_id,
        sequence_number=seq_num,
        full_name=full_name,
        nik=str(payload.get("nik") or "").strip() or None,
        phone=str(payload.get("phone") or "").strip() or None,
        email=str(payload.get("email") or f"{emp_id.replace('.', '').lower()}@itsp.co.id").strip(),
        gender=payload.get("gender") or "Laki-laki",
        birth_place=payload.get("birth_place"),
        birth_date=birth_date,
        age=int(payload.get("age")) if payload.get("age") else None,
        religion=payload.get("religion"),
        marriage_status=payload.get("marriage_status"),
        address_ktp=payload.get("address_ktp"),
        address_domicile=payload.get("address_domicile"),
        job_title=job_title,
        department=department,
        section=payload.get("section"),
        level=payload.get("level"),
        plant=payload.get("plant") or "KIIC",
        work_location=payload.get("work_location") or "Plant PT ITSP Karawang",
        employee_type=payload.get("employee_type") or "Direct",
        contract_status=contract_status,
        contract_start_date=start_date,
        contract_end_date=end_date,
        salary=str(payload.get("salary") or "").strip() or None,
        ptkp_status=payload.get("ptkp_status") or "TK",
        npwp=payload.get("npwp"),
        bpjs_tk_no=payload.get("bpjs_tk_no"),
        account_no=payload.get("account_no"),
        bank_name=payload.get("bank_name"),
        bank_account_no=payload.get("bank_account_no"),
        father_name=payload.get("father_name"),
        mother_name=payload.get("mother_name"),
        spouse_name=payload.get("spouse_name"),
        last_education=payload.get("last_education"),
        school_name=payload.get("school_name"),
        major=payload.get("major"),
        notes=payload.get("notes"),
        employee_status="active",
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return {
        "success": True,
        "message": f"Karyawan baru {emp.full_name} ({emp.employee_id}) berhasil ditambahkan ke database.",
        "employee_id": emp.employee_id,
        "id": emp.id,
    }


@router.post("/employees/{id}/terminate")
def terminate_employee(
    id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["admin", "hr"])),
):
    """Mark an employee as exited / not renewed (Karyawan Keluar / Habis Kontrak)."""
    emp = crud_data_karyawan.get(db, id)
    if not emp:
        raise HTTPException(status_code=404, detail="Data karyawan tidak ditemukan.")

    exit_reason = str(payload.get("exit_reason") or "Habis Kontrak (Tidak Diperpanjang)").strip()
    exit_date_raw = payload.get("exit_date")
    if exit_date_raw:
        try:
            exit_date = datetime.fromisoformat(str(exit_date_raw)[:10]).replace(tzinfo=timezone.utc)
        except Exception:
            exit_date = datetime.now(timezone.utc)
    else:
        exit_date = datetime.now(timezone.utc)

    notes = str(payload.get("notes") or "").strip()
    emp.employee_status = "resign"
    emp.exit_date = exit_date
    emp.exit_reason = exit_reason
    if notes:
        existing_notes = emp.notes or ""
        emp.notes = f"{existing_notes}\n[Catatan Keluar {exit_date.strftime('%Y-%m-%d')}]: {notes}".strip()

    db.commit()
    return {
        "success": True,
        "message": f"Status karyawan {emp.full_name} ({emp.employee_id}) berhasil diubah menjadi Karyawan Keluar ({exit_reason}).",
    }


@router.get("/employees-retention")
def get_employee_retention(
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["admin", "hr"])),
):
    """Get retention setting and counts of exited employees and expired retention."""
    retention_val = crud_setting.get_value(db, "employee_exit_retention_months", "12")
    try:
        retention_months = int(retention_val)
    except (ValueError, TypeError):
        retention_months = 12

    exited_query = db.query(DataKaryawan).filter(DataKaryawan.employee_status == "resign")
    total_exited = exited_query.count()

    expired_count = 0
    if retention_months > 0:
        threshold = datetime.now(timezone.utc) - timedelta(days=retention_months * 30)
        expired_count = exited_query.filter(
            (DataKaryawan.exit_date.isnot(None) & (DataKaryawan.exit_date < threshold)) |
            (DataKaryawan.exit_date.is_(None) & (DataKaryawan.contract_end_date < threshold))
        ).count()

    return {
        "success": True,
        "retention_months": retention_months,
        "total_exited": total_exited,
        "expired_count": expired_count,
    }


@router.post("/employees-retention")
def set_employee_retention(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["admin", "hr"])),
):
    """Save retention setting for exited employees."""
    months = int(payload.get("retention_months", 12))
    crud_setting.set_value(db, "employee_exit_retention_months", str(months))
    return {
        "success": True,
        "retention_months": months,
        "message": f"Masa retensi riwayat karyawan keluar berhasil diatur menjadi {months} bulan ({'1 tahun' if months==12 else str(months) + ' bulan'}).",
    }


@router.post("/employees-retention/cleanup")
def cleanup_expired_exited_employees(
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["admin", "hr"])),
):
    """Permanently delete exited employee records older than retention period."""
    retention_val = crud_setting.get_value(db, "employee_exit_retention_months", "12")
    try:
        retention_months = int(retention_val)
    except (ValueError, TypeError):
        retention_months = 12

    if retention_months <= 0:
        return {"success": True, "deleted_count": 0, "message": "Retensi diatur selamanya. Tidak ada data yang dihapus."}

    threshold = datetime.now(timezone.utc) - timedelta(days=retention_months * 30)
    to_delete = db.query(DataKaryawan).filter(
        DataKaryawan.employee_status == "resign",
        (
            (DataKaryawan.exit_date.isnot(None) & (DataKaryawan.exit_date < threshold)) |
            (DataKaryawan.exit_date.is_(None) & (DataKaryawan.contract_end_date < threshold))
        )
    ).all()

    deleted_count = 0
    for e in to_delete:
        db.delete(e)
        deleted_count += 1
    db.commit()

    return {
        "success": True,
        "deleted_count": deleted_count,
        "message": f"Berhasil membersihkan {deleted_count} data riwayat karyawan keluar yang telah melewati batas retensi ({retention_months} bulan).",
    }


