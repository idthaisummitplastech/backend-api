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

    # Extended Identity
    nik = str(payload.get("nik") or "").strip()
    first_name = str(payload.get("first_name") or payload.get("firstName") or "").strip()
    last_name = str(payload.get("last_name") or payload.get("lastName") or "").strip()
    if not full_name and (first_name or last_name):
        full_name = f"{first_name} {last_name}".strip()
    gender = str(payload.get("gender") or "").strip()
    religion = str(payload.get("religion") or "").strip()
    ethnic = str(payload.get("ethnic") or "").strip()
    height_cm = int(payload.get("height_cm") or payload.get("heightCm") or 0) or None
    weight_kg = int(payload.get("weight_kg") or payload.get("weightKg") or 0) or None
    marriage_status = str(payload.get("marriage_status") or payload.get("marriageStatus") or "").strip()
    birth_place = str(payload.get("birth_place") or payload.get("birthPlace") or "").strip()

    # Extended Address
    address_ktp = str(payload.get("address_ktp") or payload.get("addressKtp") or "").strip()
    province_ktp = str(payload.get("province_ktp") or payload.get("provinceKtp") or "").strip()
    city_ktp = str(payload.get("city_ktp") or payload.get("cityKtp") or "").strip()
    district_ktp = str(payload.get("district_ktp") or payload.get("districtKtp") or "").strip()
    village_ktp = str(payload.get("village_ktp") or payload.get("villageKtp") or "").strip()
    rt_ktp = str(payload.get("rt_ktp") or payload.get("rtKtp") or "").strip()
    rw_ktp = str(payload.get("rw_ktp") or payload.get("rwKtp") or "").strip()
    street_ktp = str(payload.get("street_ktp") or payload.get("streetKtp") or "").strip()

    domicile_same_as_ktp = bool(payload.get("domicile_same_as_ktp", payload.get("domicileSameAsKtp", True)))
    address_domicile = str(payload.get("address_domicile") or payload.get("addressDomicile") or "").strip()
    province_domicile = str(payload.get("province_domicile") or payload.get("provinceDomicile") or "").strip()
    city_domicile = str(payload.get("city_domicile") or payload.get("cityDomicile") or "").strip()
    district_domicile = str(payload.get("district_domicile") or payload.get("districtDomicile") or "").strip()
    village_domicile = str(payload.get("village_domicile") or payload.get("villageDomicile") or "").strip()
    rt_domicile = str(payload.get("rt_domicile") or payload.get("rtDomicile") or "").strip()
    rw_domicile = str(payload.get("rw_domicile") or payload.get("rwDomicile") or "").strip()
    street_domicile = str(payload.get("street_domicile") or payload.get("streetDomicile") or "").strip()

    # Extended Documents
    photo_file = str(payload.get("photo_file") or payload.get("photoFile") or "")
    ktp_file = str(payload.get("ktp_file") or payload.get("ktpFile") or "")
    kk_file = str(payload.get("kk_file") or payload.get("kkFile") or "")
    ijazah_file = str(payload.get("ijazah_file") or payload.get("ijazahFile") or "")
    transkrip_file = str(payload.get("transkrip_file") or payload.get("transkripFile") or "")
    cert_nonformal_file = str(payload.get("cert_nonformal_file") or payload.get("certNonformalFile") or "")
    bpjs_kesehatan_file = str(payload.get("bpjs_kesehatan_file") or payload.get("bpjsKesehatanFile") or "")
    bpjs_ketenagakerjaan_file = str(payload.get("bpjs_ketenagakerjaan_file") or payload.get("bpjsKetenagakerjaanFile") or "")
    npwp_file = str(payload.get("npwp_file") or payload.get("npwpFile") or "")
    akta_file = str(payload.get("akta_file") or payload.get("aktaFile") or "")
    skck_file = str(payload.get("skck_file") or payload.get("skckFile") or "")

    # Structured history & family
    import json
    edu_raw = payload.get("education_history") or payload.get("educationHistory")
    education_history = json.dumps(edu_raw) if isinstance(edu_raw, (list, dict)) else str(edu_raw or "")

    work_raw = payload.get("work_history") or payload.get("workHistory")
    work_history = json.dumps(work_raw) if isinstance(work_raw, (list, dict)) else str(work_raw or "")

    parents_raw = payload.get("family_parents") or payload.get("familyParents")
    family_parents = json.dumps(parents_raw) if isinstance(parents_raw, (list, dict)) else str(parents_raw or "")

    siblings_raw = payload.get("family_siblings") or payload.get("familySiblings")
    family_siblings = json.dumps(siblings_raw) if isinstance(siblings_raw, (list, dict)) else str(siblings_raw or "")

    # 1. Validation
    if not (full_name and email and phone and birth_date_str and job_id and cv_file):
        raise HTTPException(
            status_code=400,
            detail="Mohon lengkapi seluruh formulir pendaftaran yang bertanda bintang (*).",
        )

    if not last_education:
        last_education = "SMA/SMK"
    if not school_name:
        school_name = "-"
    if not major:
        major = "-"

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
        # Extended fields
        nik=nik,
        first_name=first_name,
        last_name=last_name,
        gender=gender,
        religion=religion,
        ethnic=ethnic,
        height_cm=height_cm,
        weight_kg=weight_kg,
        marriage_status=marriage_status,
        birth_place=birth_place,
        address_ktp=address_ktp,
        province_ktp=province_ktp,
        city_ktp=city_ktp,
        district_ktp=district_ktp,
        village_ktp=village_ktp,
        rt_ktp=rt_ktp,
        rw_ktp=rw_ktp,
        street_ktp=street_ktp,
        domicile_same_as_ktp=domicile_same_as_ktp,
        address_domicile=address_domicile,
        province_domicile=province_domicile,
        city_domicile=city_domicile,
        district_domicile=district_domicile,
        village_domicile=village_domicile,
        rt_domicile=rt_domicile,
        rw_domicile=rw_domicile,
        street_domicile=street_domicile,
        photo_file=photo_file,
        ktp_file=ktp_file,
        kk_file=kk_file,
        ijazah_file=ijazah_file,
        transkrip_file=transkrip_file,
        cert_nonformal_file=cert_nonformal_file,
        bpjs_kesehatan_file=bpjs_kesehatan_file,
        bpjs_ketenagakerjaan_file=bpjs_ketenagakerjaan_file,
        npwp_file=npwp_file,
        akta_file=akta_file,
        skck_file=skck_file,
        education_history=education_history,
        work_history=work_history,
        family_parents=family_parents,
        family_siblings=family_siblings,
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
    applicant_id: str,
    db: Session = Depends(get_db),
):
    """
    Candidate live recruitment status tracker with settings & sanitized submission data.
    Supports either integer applicant_id or applicant email string.
    """
    applicant = crud_applicant.get_with_details_by_identifier(db, applicant_id)
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
            "locationAddress": iv.location_address,
            "location_address": iv.location_address,
            "mapsUrl": iv.maps_url,
            "maps_url": iv.maps_url,
            "roomName": iv.room_name,
            "room_name": iv.room_name,
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
            "psikotesMapsUrl": applicant.psikotes_maps_url,
            "psikotes_maps_url": applicant.psikotes_maps_url,
            "userTestScheduledAt": applicant.user_test_scheduled_at,
            "userTestLocation": applicant.user_test_location or "Portal Karir Online PT ITSP",
            "userTestMapsUrl": applicant.user_test_maps_url,
            "userTest_maps_url": applicant.user_test_maps_url,
            "mcuNotes": applicant.mcu_notes,
            "offeringLetter": applicant.offering_letter,
            "offeringSalary": applicant.offering_salary,
            "offeringStatus": applicant.offering_status,
            "offeringAttachment": applicant.offering_attachment,
            "offering_attachment": applicant.offering_attachment,
            "offeringClauses": applicant.offering_clauses,
            "offering_clauses": applicant.offering_clauses,
            "offeringSignerName": applicant.offering_signer_name,
            "offering_signer_name": applicant.offering_signer_name,
            "offeringSignerTitle": applicant.offering_signer_title,
            "offering_signer_title": applicant.offering_signer_title,
            "offeringSignerSignature": applicant.offering_signer_signature,
            "offering_signer_signature": applicant.offering_signer_signature,
            "offeringJoinDate": applicant.offering_join_date,
            "offering_join_date": applicant.offering_join_date,
            "offeringRefNumber": applicant.offering_ref_number,
            "offering_ref_number": applicant.offering_ref_number,
            "signedContractFile": applicant.signed_contract_file,
            "signed_contract_file": applicant.signed_contract_file,
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

    signed_contract_file = payload.get("signed_contract_file") or payload.get("signedContractFile") or payload.get("signedFile")
    if signed_contract_file:
        applicant.signed_contract_file = signed_contract_file

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

    applicants = crud_applicant.get_multi_with_details(db, limit=300, filters=filters)

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
    """Retrieve complete candidate file/profile by ID (Berkas Lengkap Pelamar)."""
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
