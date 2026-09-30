from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.schemas.tests import TestSubmissionResponse


# --- JOB POSTING SCHEMAS ---
class JobPostingBase(BaseModel):
    title: str
    department: str
    location: str = "Karawang / Cikarang"
    type: str = "Full-Time"
    experience: str = "1-3 Tahun"
    requirements: str
    description: str
    is_open: bool = True
    closing_date: Optional[datetime] = None
    opening_date: Optional[datetime] = None


class JobPostingCreate(JobPostingBase):
    pass


class JobPostingUpdate(BaseModel):
    title: Optional[str] = None
    department: Optional[str] = None
    location: Optional[str] = None
    type: Optional[str] = None
    experience: Optional[str] = None
    requirements: Optional[str] = None
    description: Optional[str] = None
    is_open: Optional[bool] = None
    closing_date: Optional[datetime] = None
    opening_date: Optional[datetime] = None


class JobPostingResponse(JobPostingBase):
    id: int
    created_at: datetime
    applicants_count: int = 0
    _count: Optional[dict] = None

    model_config = ConfigDict(from_attributes=True)


# --- APPLICANT SCHEMAS ---
class ApplicantCreate(BaseModel):
    job_posting_id: int
    full_name: str
    email: EmailStr
    password: str = Field(..., min_length=6)
    phone: str
    birth_date: datetime
    age: int
    last_education: str
    school_name: str
    major: str
    experience: str
    english_skill: str
    other_languages: str
    cv_file: str  # Base64 or uploaded URL
    cv_file_size: int = 0

    # Extended Identity Fields
    nik: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    gender: Optional[str] = None
    religion: Optional[str] = None
    ethnic: Optional[str] = None
    height_cm: Optional[int] = None
    weight_kg: Optional[int] = None
    marriage_status: Optional[str] = None
    birth_place: Optional[str] = None

    # Extended Address Fields
    address_ktp: Optional[str] = None
    province_ktp: Optional[str] = None
    city_ktp: Optional[str] = None
    district_ktp: Optional[str] = None
    village_ktp: Optional[str] = None
    rt_ktp: Optional[str] = None
    rw_ktp: Optional[str] = None
    street_ktp: Optional[str] = None

    domicile_same_as_ktp: Optional[bool] = True
    address_domicile: Optional[str] = None
    province_domicile: Optional[str] = None
    city_domicile: Optional[str] = None
    district_domicile: Optional[str] = None
    village_domicile: Optional[str] = None
    rt_domicile: Optional[str] = None
    rw_domicile: Optional[str] = None
    street_domicile: Optional[str] = None

    # Extended Document Upload Fields
    photo_file: Optional[str] = None
    ktp_file: Optional[str] = None
    kk_file: Optional[str] = None
    ijazah_file: Optional[str] = None
    transkrip_file: Optional[str] = None
    cert_nonformal_file: Optional[str] = None
    bpjs_kesehatan_file: Optional[str] = None
    bpjs_ketenagakerjaan_file: Optional[str] = None
    npwp_file: Optional[str] = None
    akta_file: Optional[str] = None
    skck_file: Optional[str] = None

    # Structured History & Family Data
    education_history: Optional[str] = None
    work_history: Optional[str] = None
    family_parents: Optional[str] = None
    family_siblings: Optional[str] = None


class ApplicantUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    last_education: Optional[str] = None
    school_name: Optional[str] = None
    major: Optional[str] = None
    experience: Optional[str] = None
    english_skill: Optional[str] = None
    other_languages: Optional[str] = None
    cv_file: Optional[str] = None
    cv_file_size: Optional[int] = None
    screening_notes: Optional[str] = None
    mcu_notes: Optional[str] = None
    offering_letter: Optional[str] = None
    offering_salary: Optional[str] = None
    offering_status: Optional[str] = None
    offering_attachment: Optional[str] = None
    offering_clauses: Optional[str] = None
    offering_signer_name: Optional[str] = None
    offering_signer_title: Optional[str] = None
    offering_signer_signature: Optional[str] = None
    offering_join_date: Optional[str] = None
    offering_ref_number: Optional[str] = None
    signed_contract_file: Optional[str] = None

    # Extended fields update
    nik: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    gender: Optional[str] = None
    religion: Optional[str] = None
    ethnic: Optional[str] = None
    height_cm: Optional[int] = None
    weight_kg: Optional[int] = None
    marriage_status: Optional[str] = None
    birth_place: Optional[str] = None
    address_ktp: Optional[str] = None
    address_domicile: Optional[str] = None


class ApplicantResponse(BaseModel):
    id: int
    job_posting_id: int
    full_name: str
    email: EmailStr
    phone: str
    birth_date: datetime
    age: int
    last_education: str
    school_name: str
    major: str
    experience: str
    english_skill: str
    other_languages: str
    cv_file: str
    cv_file_size: int
    current_stage: int
    stage_status: str
    failed_at_stage: Optional[int] = None
    rejection_reason: Optional[str] = None
    screening_notes: Optional[str] = None
    psikotes_scheduled_at: Optional[datetime] = None
    psikotes_token: Optional[str] = None
    psikotes_location: Optional[str] = None
    psikotes_maps_url: Optional[str] = None
    user_test_scheduled_at: Optional[datetime] = None
    user_test_token: Optional[str] = None
    user_test_location: Optional[str] = None
    user_test_maps_url: Optional[str] = None
    mcu_notes: Optional[str] = None
    offering_letter: Optional[str] = None
    offering_salary: Optional[str] = None
    offering_status: str
    offering_attachment: Optional[str] = None
    offering_clauses: Optional[str] = None
    offering_signer_name: Optional[str] = None
    offering_signer_title: Optional[str] = None
    offering_signer_signature: Optional[str] = None
    offering_join_date: Optional[str] = None
    offering_ref_number: Optional[str] = None
    signed_contract_file: Optional[str] = None
    contract_signed_at: Optional[datetime] = None
    is_employee: Optional[bool] = False
    employee_id: Optional[str] = None
    created_at: datetime
    job_posting: Optional[JobPostingResponse] = None
    test_submissions: Optional[List[TestSubmissionResponse]] = Field(default_factory=list, serialization_alias="testSubmissions")

    # Extended Identity Fields
    nik: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    gender: Optional[str] = None
    religion: Optional[str] = None
    ethnic: Optional[str] = None
    height_cm: Optional[int] = None
    weight_kg: Optional[int] = None
    marriage_status: Optional[str] = None
    birth_place: Optional[str] = None

    # Extended Address Fields
    address_ktp: Optional[str] = None
    province_ktp: Optional[str] = None
    city_ktp: Optional[str] = None
    district_ktp: Optional[str] = None
    village_ktp: Optional[str] = None
    rt_ktp: Optional[str] = None
    rw_ktp: Optional[str] = None
    street_ktp: Optional[str] = None

    domicile_same_as_ktp: Optional[bool] = True
    address_domicile: Optional[str] = None
    province_domicile: Optional[str] = None
    city_domicile: Optional[str] = None
    district_domicile: Optional[str] = None
    village_domicile: Optional[str] = None
    rt_domicile: Optional[str] = None
    rw_domicile: Optional[str] = None
    street_domicile: Optional[str] = None

    # Extended Document Upload Fields
    photo_file: Optional[str] = None
    ktp_file: Optional[str] = None
    kk_file: Optional[str] = None
    ijazah_file: Optional[str] = None
    transkrip_file: Optional[str] = None
    cert_nonformal_file: Optional[str] = None
    bpjs_kesehatan_file: Optional[str] = None
    bpjs_ketenagakerjaan_file: Optional[str] = None
    npwp_file: Optional[str] = None
    akta_file: Optional[str] = None
    skck_file: Optional[str] = None

    # Structured History & Family Data
    education_history: Optional[str] = None
    work_history: Optional[str] = None
    family_parents: Optional[str] = None
    family_siblings: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# --- RECRUITMENT PIPELINE ACTIONS ---
class AdvanceStageRequest(BaseModel):
    applicant_id: int
    action: str = Field(..., description="'advance'/'approve', 'reject', 'update_test_session'/'update_token', 'sign_contract'")
    notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    scheduled_until: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    token: Optional[str] = None
    location: Optional[str] = None
    maps_url: Optional[str] = None
    salary_offer: Optional[str] = None
    offering_attachment: Optional[str] = None
    offering_clauses: Optional[str] = None
    offering_signer_name: Optional[str] = None
    offering_signer_title: Optional[str] = None
    offering_signer_signature: Optional[str] = None
    offering_join_date: Optional[str] = None
    offering_ref_number: Optional[str] = None
    meeting_platform: Optional[str] = "teams"
    meeting_link: Optional[str] = None
    meeting_passcode: Optional[str] = None
    interviewer_name: Optional[str] = None
    target_stage: Optional[int] = None
    stage_status: Optional[str] = "in_progress"
    send_email: Optional[bool] = True

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases_and_casing(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        
        # 1. Normalize camelCase to snake_case aliases
        if "applicant_id" not in data and "applicantId" in data:
            data["applicant_id"] = data["applicantId"]
        if "target_stage" not in data and "targetStage" in data:
            data["target_stage"] = data["targetStage"]
        if "stage_status" not in data and "stageStatus" in data:
            data["stage_status"] = data["stageStatus"]
        if "send_email" not in data and "sendEmail" in data:
            data["send_email"] = data["sendEmail"]
        if "scheduled_at" not in data and "scheduledAt" in data:
            data["scheduled_at"] = data["scheduledAt"]
        if "scheduled_until" not in data and "scheduledUntil" in data:
            data["scheduled_until"] = data["scheduledUntil"]
        if "duration_minutes" not in data and "durationMinutes" in data:
            data["duration_minutes"] = data["durationMinutes"]
        if "maps_url" not in data and "mapsUrl" in data:
            data["maps_url"] = data["mapsUrl"]
        if "salary_offer" not in data and "salaryOffer" in data:
            data["salary_offer"] = data["salaryOffer"]
        if "offering_attachment" not in data and "offeringAttachment" in data:
            data["offering_attachment"] = data["offeringAttachment"]
        elif "offering_attachment" not in data and "offeringFile" in data:
            data["offering_attachment"] = data["offeringFile"]
        if "offering_clauses" not in data and "offeringClauses" in data:
            data["offering_clauses"] = data["offeringClauses"]
        if "offering_signer_name" not in data and "offeringSignerName" in data:
            data["offering_signer_name"] = data["offeringSignerName"]
        if "offering_signer_title" not in data and "offeringSignerTitle" in data:
            data["offering_signer_title"] = data["offeringSignerTitle"]
        if "offering_signer_signature" not in data and "offeringSignerSignature" in data:
            data["offering_signer_signature"] = data["offeringSignerSignature"]
        elif "offering_signer_signature" not in data and "offeringSignature" in data:
            data["offering_signer_signature"] = data["offeringSignature"]
        if "offering_join_date" not in data and "offeringJoinDate" in data:
            data["offering_join_date"] = data["offeringJoinDate"]
        if "offering_ref_number" not in data and "offeringRefNumber" in data:
            data["offering_ref_number"] = data["offeringRefNumber"]
        if "meeting_platform" not in data and "meetingPlatform" in data:
            data["meeting_platform"] = data["meetingPlatform"]
        if "meeting_link" not in data and "meetingLink" in data:
            data["meeting_link"] = data["meetingLink"]
        if "meeting_passcode" not in data and "meetingPasscode" in data:
            data["meeting_passcode"] = data["meetingPasscode"]
        if "interviewer_name" not in data and "interviewerName" in data:
            data["interviewer_name"] = data["interviewerName"]
        if "rejection_reason" not in data and "rejectionReason" in data:
            data["rejection_reason"] = data["rejectionReason"]

        # 2. Normalize and sanitize action
        raw_action = str(data.get("action") or "").strip().lower()
        if raw_action == "approve":
            data["action"] = "advance"
        elif raw_action == "update_token":
            data["action"] = "update_test_session"
        else:
            data["action"] = raw_action

        return data


class TestSessionUpdateRequest(BaseModel):
    applicant_id: int
    stage: int = Field(..., description="Stage 2 for Psikotes, Stage 3 for User Test")
    token: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    location: Optional[str] = None


# --- INTERVIEW SCHEMAS ---
class InterviewScheduleBase(BaseModel):
    applicant_id: int
    interview_type: str  # 'hr' or 'user'
    scheduled_at: datetime
    location_mode: str = "online"
    meeting_platform: Optional[str] = "teams"
    meeting_link: Optional[str] = None
    meeting_passcode: Optional[str] = None
    location_address: Optional[str] = None
    maps_url: Optional[str] = None
    room_name: Optional[str] = None
    interviewer_name: Optional[str] = None
    notes: Optional[str] = None


class InterviewScheduleCreate(InterviewScheduleBase):
    pass


class InterviewScheduleResponse(InterviewScheduleBase):
    id: int
    status: str
    feedback: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- KARYAWAN SEMENTARA (ONBOARDING) ---
class KaryawanSementaraResponse(BaseModel):
    id: int
    applicant_id: int
    nik_sementara: str
    nama_lengkap: str
    email: str
    no_hp: str
    departemen: str
    jabatan: str
    tanggal_bergabung: datetime
    status_integrasi: str
    id_card_printed: bool
    photo_url: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
