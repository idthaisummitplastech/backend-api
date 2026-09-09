from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.crud.crud_recruitment import crud_applicant, crud_job, crud_karyawan, crud_setting
from app.models.auth import RecruitmentAdmin
from app.models.recruitment import Applicant, KaryawanSementara
from app.schemas.recruitment import ApplicantCreate, ApplicantResponse
from app.schemas.common import ApiResponse, StatusResponse
from app.api.deps import get_current_admin, get_current_applicant, RoleChecker
from app.core.middleware import limiter
from app.core.security import get_password_hash
from app.services.recruitment_service import recruitment_service

router = APIRouter()


@router.post("/apply")
@limiter.limit("15/minute")
def apply_job(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    """
    Candidate job application submission:
    - Checks job status, opening date, and closing date
    - Handles re-apply cleanup if candidate previously failed or expired > 30 days ago
    - Calculates candidate age from birth_date
    - Auto-generates standard temp password (e.g. Itsp@2026)
    - Persists candidate and returns applicant data + temp password for email delivery
    """
    job_id = int(payload.get("job_posting_id") or payload.get("jobPostingId") or 0)
    full_name = str(payload.get("full_name") or payload.get("fullName") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    phone = str(payload.get("phone") or "").strip()
    birth_date_str = str(payload.get("birth_date") or payload.get("birthDate") or "")
    last_education = str(payload.get("last_education") or payload.get("lastEducation") or "").strip()
    school_name = str(payload.get("school_name") or payload.get("schoolName") or "").strip()
    major = str(payload.get("major") or "").strip()
    experience = str(payload.get("experience") or "Fresh Graduate").strip()
    english_skill = str(payload.get("english_skill") or payload.get("englishSkill") or "Intermediate").strip()
    other_languages = str(payload.get("other_languages") or payload.get("otherLanguages") or "-").strip()
    cv_file = str(payload.get("cv_file") or payload.get("cvBase64") or "")
    cv_file_size = int(payload.get("cv_file_size") or payload.get("cvFileSize") or 0)

    # 1. Validation
    if not (full_name and email and phone and birth_date_str and last_education and school_name and major and job_id and cv_file):
        raise HTTPException(
            status_code=400,
            detail="Mohon lengkapi seluruh formulir pendaftaran yang bertanda bintang (*).",
        )

    # 2. Check job status and date limits
    job = crud_job.get(db, job_id)
    if not job or not job.is_open:
        raise HTTPException(
            status_code=400,
            detail="Mohon maaf, lowongan pekerjaan ini telah ditutup atau tidak aktif.",
        )

    now = datetime.now(timezone.utc)
    if job.opening_date and job.opening_date > now:
        raise HTTPException(
            status_code=400,
            detail="Lowongan ini belum dibuka. Silakan kembali pada tanggal pembukaan.",
        )
    if job.closing_date and job.closing_date < now:
        raise HTTPException(
            status_code=400,
            detail="Masa pendaftaran lowongan ini telah berakhir (kedaluwarsa).",
        )

    # 3. Check existing applicant
    existing = crud_applicant.get_by_email(db, email)
    if existing:
        # Check if existing applicant is still in progress (< 30 days)
        days_since = (datetime.now(timezone.utc) - existing.created_at).total_seconds() / 86400
        is_still_active = existing.stage_status == "in_progress" and days_since < 30
        if is_still_active:
            active_title = existing.job_posting.title if existing.job_posting else "Posisi Lain"
            raise HTTPException(
                status_code=400,
                detail=f'Alamat email "{email}" saat ini masih memiliki proses seleksi aktif untuk posisi "{active_title}". Harap selesaikan tahapan tersebut terlebih dahulu.',
            )

        # Cleanup old record to allow fresh re-application
        try:
            db.query(KaryawanSementara).filter(KaryawanSementara.applicant_id == existing.id).delete()
            crud_applicant.remove(db, id=existing.id)
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[RE-APPLY CLEANUP ERROR] {e}")

    # 4. Parse birth date and calculate age
    try:
        birth_date = datetime.fromisoformat(birth_date_str.replace("Z", "+00:00"))
    except Exception:
        birth_date = datetime.strptime(birth_date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)

    today = datetime.now(timezone.utc)
    age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    if age <= 0:
        age = 20

    # 5. Generate password & hash
    year = today.year
    temp_password = f"Itsp@{year}"
    hashed_pw = get_password_hash(temp_password)

    # 6. Create applicant
    new_applicant = Applicant(
        job_posting_id=job_id,
        full_name=full_name,
        email=email,
        password=hashed_pw,
        phone=phone,
        birth_date=birth_date,
        age=age,
        last_education=last_education,
        school_name=school_name,
        major=major,
        experience=experience,
        english_skill=english_skill,
        other_languages=other_languages,
        cv_file=cv_file,
        cv_file_size=cv_file_size,
        current_stage=1,
        stage_status="in_progress",
    )
    db.add(new_applicant)
    db.commit()
    db.refresh(new_applicant)

    return {
        "success": True,
        "message": "Pendaftaran berhasil! Silakan login untuk memantau status seleksi Anda.",
        "temp_password": temp_password,
        "applicant": {
            "id": new_applicant.id,
            "full_name": new_applicant.full_name,
            "email": new_applicant.email,
            "current_stage": new_applicant.current_stage,
            "stage_status": new_applicant.stage_status,
            "job_posting": {
                "id": job.id,
                "title": job.title,
                "department": job.department,
            },
        },
    }


@router.get("/status/{applicant_id}")
def get_applicant_status_details(
    applicant_id: int,
    db: Session = Depends(get_db),
):
    """
    Candidate live recruitment status tracker with settings & sanitized submission data.
    """
    applicant = crud_applicant.get_with_details(db, applicant_id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Data pelamar tidak ditemukan.")

    # Master settings
    settings_list = crud_setting.get_multi(db, limit=100)
    settings_map = {s.key: s.value for s in settings_list}

    # Sanitize submissions (privacy: score masked unless show_score is true)
    sanitized_subs = []
    for sub in applicant.test_submissions:
        sanitized_subs.append({
            "id": sub.id,
            "testType": sub.test_type,
            "test_type": sub.test_type,
            "isPassed": sub.is_passed,
            "is_passed": sub.is_passed,
            "isLocked": sub.is_locked,
            "is_locked": sub.is_locked,
            "violationsCount": sub.violations_count,
            "violations_count": sub.violations_count,
            "score": sub.score if sub.show_score else None,
            "showScore": sub.show_score,
            "show_score": sub.show_score,
            "submittedAt": sub.submitted_at,
            "submitted_at": sub.submitted_at,
        })

    # Format interviews
    interviews = []
    for iv in applicant.interviews:
        interviews.append({
            "id": iv.id,
            "interviewType": iv.interview_type,
            "scheduledAt": iv.scheduled_at,
            "locationMode": iv.location_mode,
            "meetingPlatform": iv.meeting_platform,
            "meetingLink": iv.meeting_link,
            "meetingPasscode": iv.meeting_passcode,
            "interviewerName": iv.interviewer_name,
            "notes": iv.notes,
            "status": iv.status,
        })

    # Format karyawan data
    karyawan_data = None
    if applicant.karyawan_data:
        k = applicant.karyawan_data
        karyawan_data = {
            "id": k.id,
            "nikSementara": k.nik_sementara,
            "namaLengkap": k.nama_lengkap,
            "email": k.email,
            "noHp": k.no_hp,
            "departemen": k.departemen,
            "jabatan": k.jabatan,
            "tanggalBergabung": k.tanggal_bergabung,
            "statusIntegrasi": k.status_integrasi,
            "idCardPrinted": k.id_card_printed,
        }

    return {
        "success": True,
        "applicant": {
            "id": applicant.id,
            "fullName": applicant.full_name,
            "full_name": applicant.full_name,
            "email": applicant.email,
            "phone": applicant.phone,
            "lastEducation": applicant.last_education,
            "schoolName": applicant.school_name,
            "major": applicant.major,
            "experience": applicant.experience,
            "englishSkill": applicant.english_skill,
            "currentStage": applicant.current_stage,
            "current_stage": applicant.current_stage,
            "stageStatus": applicant.stage_status,
            "stage_status": applicant.stage_status,
            "failedAtStage": applicant.failed_at_stage,
            "failed_at_stage": applicant.failed_at_stage,
            "rejectionReason": applicant.rejection_reason,
            "rejection_reason": applicant.rejection_reason,
            "screeningNotes": applicant.screening_notes,
            "psikotesScheduledAt": applicant.psikotes_scheduled_at,
            "psikotesLocation": applicant.psikotes_location or "Portal Karir Online PT ITSP",
            "userTestScheduledAt": applicant.user_test_scheduled_at,
            "userTestLocation": applicant.user_test_location or "Portal Karir Online PT ITSP",
            "mcuNotes": applicant.mcu_notes,
            "offeringLetter": applicant.offering_letter,
            "offeringSalary": applicant.offering_salary,
            "offeringStatus": applicant.offering_status,
            "contractSignedAt": applicant.contract_signed_at,
            "jobPosting": {
                "id": applicant.job_posting.id,
                "title": applicant.job_posting.title,
                "department": applicant.job_posting.department,
                "location": applicant.job_posting.location,
            } if applicant.job_posting else None,
            "testSubmissions": sanitized_subs,
            "interviews": interviews,
            "karyawanData": karyawan_data,
        },
        "settings": settings_map,
    }


@router.post("/accept-offer")
def candidate_accept_offer(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    """
    Candidate acceptance of formal Job Offer (Stage 7).
    Generates temporary NIK and establishes KaryawanSementara record.
    """
    applicant_id = int(payload.get("applicant_id") or payload.get("applicantId") or 0)
    if not applicant_id:
        raise HTTPException(status_code=400, detail="ID Pelamar wajib disertakan.")

    applicant = crud_applicant.get_with_details(db, applicant_id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Data pelamar tidak ditemukan.")

    if applicant.current_stage != 7:
        raise HTTPException(status_code=400, detail="Anda belum berada pada Tahap 7 (Offering Letter).")

    now = datetime.now(timezone.utc)
    applicant.offering_status = "accepted"
    applicant.stage_status = "passed"
    applicant.contract_signed_at = now

    # Generate temporary NIK & Karyawan Data if not exists
    if not applicant.karyawan_data:
        dept_name = applicant.job_posting.department if applicant.job_posting else "General"
        nik = recruitment_service._generate_nik_sementara(db, dept_name)
        karyawan = crud_karyawan.create(
            db,
            obj_in={
                "applicant_id": applicant.id,
                "nik_sementara": nik,
                "nama_lengkap": applicant.full_name,
                "email": applicant.email,
                "no_hp": applicant.phone,
                "departemen": dept_name,
                "jabatan": applicant.job_posting.title if applicant.job_posting else "Karyawan",
                "tanggal_bergabung": now + timedelta(days=7),
                "status_integrasi": "ready",
                "id_card_printed": False,
            },
        )
    else:
        nik = applicant.karyawan_data.nik_sementara

    db.commit()
    return {
        "success": True,
        "message": "Selamat! Anda telah resmi menyetujui Penawaran Kerja PT Indonesia Thai Summit Plastech. Data Anda telah diproses ke bagian Human Capital untuk penerbitan ID Card & jadwal penandatanganan kontrak fisik di pabrik.",
        "nik": nik,
    }


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
