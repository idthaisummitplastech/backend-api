from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


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
    user_test_scheduled_at: Optional[datetime] = None
    user_test_token: Optional[str] = None
    user_test_location: Optional[str] = None
    mcu_notes: Optional[str] = None
    offering_letter: Optional[str] = None
    offering_salary: Optional[str] = None
    offering_status: str
    contract_signed_at: Optional[datetime] = None
    created_at: datetime
    job_posting: Optional[JobPostingResponse] = None

    model_config = ConfigDict(from_attributes=True)


# --- RECRUITMENT PIPELINE ACTIONS ---
class AdvanceStageRequest(BaseModel):
    applicant_id: int
    action: str = Field(..., description="'advance', 'reject', 'update_test_session', 'issue_offering', 'sign_contract'")
    notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    token: Optional[str] = None
    location: Optional[str] = None
    maps_url: Optional[str] = None
    salary_offer: Optional[str] = None
    meeting_platform: Optional[str] = "teams"
    meeting_link: Optional[str] = None
    meeting_passcode: Optional[str] = None
    interviewer_name: Optional[str] = None


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
