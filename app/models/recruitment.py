from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class JobPosting(Base):
    __tablename__ = "job_postings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    department = Column(String(100), nullable=False)
    location = Column(String(150), default="Karawang / Cikarang", nullable=False)
    type = Column(String(50), default="Full-Time", nullable=False)
    experience = Column(String(100), default="1-3 Tahun", nullable=False)
    requirements = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    is_open = Column(Boolean, default=True, nullable=False)
    closing_date = Column(DateTime(timezone=True), nullable=True)
    opening_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    applicants = relationship("Applicant", back_populates="job_posting", cascade="all, delete-orphan")


class Applicant(Base):
    __tablename__ = "applicants"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    job_posting_id = Column(Integer, ForeignKey("job_postings.id"), nullable=False)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)  # Bcrypt hash
    phone = Column(String(50), nullable=False)
    birth_date = Column(DateTime(timezone=True), nullable=False)
    age = Column(Integer, nullable=False)
    last_education = Column(String(100), nullable=False)
    school_name = Column(String(255), nullable=False)
    major = Column(String(255), nullable=False)
    experience = Column(String(255), nullable=False)
    english_skill = Column(String(100), nullable=False)
    other_languages = Column(String(255), nullable=False)
    cv_file = Column(Text, nullable=False)  # Base64 or secure stored file path
    cv_file_size = Column(Integer, default=0, nullable=False)

    # 7-Stage Progress Tracker
    current_stage = Column(Integer, default=1, nullable=False)  # Stages 1 to 7
    stage_status = Column(String(50), default="in_progress", nullable=False)  # in_progress, passed, failed
    failed_at_stage = Column(Integer, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Stage 1: Screening Notes
    screening_notes = Column(Text, nullable=True)

    # Stage 2 & 3: Online Test Schedule, Token & Venue
    psikotes_scheduled_at = Column(DateTime(timezone=True), nullable=True)
    psikotes_token = Column(String(50), nullable=True)
    psikotes_location = Column(String(255), default="Portal Karir Online PT ITSP", nullable=False)

    user_test_scheduled_at = Column(DateTime(timezone=True), nullable=True)
    user_test_token = Column(String(50), nullable=True)
    user_test_location = Column(String(255), default="Portal Karir Online PT ITSP", nullable=False)

    # Stage 6 & 7: Medical & Offering
    mcu_notes = Column(Text, nullable=True)
    offering_letter = Column(Text, nullable=True)
    offering_salary = Column(String(100), nullable=True)
    offering_status = Column(String(50), default="pending", nullable=False)  # pending, issued, accepted, rejected
    contract_signed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    job_posting = relationship("JobPosting", back_populates="applicants")
    test_submissions = relationship("TestSubmission", back_populates="applicant", cascade="all, delete-orphan")
    interviews = relationship("InterviewSchedule", back_populates="applicant", cascade="all, delete-orphan")
    karyawan_data = relationship("KaryawanSementara", back_populates="applicant", uselist=False, cascade="all, delete-orphan")


class InterviewSchedule(Base):
    __tablename__ = "interview_schedules"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    applicant_id = Column(Integer, ForeignKey("applicants.id", ondelete="CASCADE"), nullable=False)
    interview_type = Column(String(50), nullable=False)  # 'hr' or 'user'
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    location_mode = Column(String(50), default="online", nullable=False)  # 'online' or 'onsite'
    meeting_platform = Column(String(50), default="teams", nullable=True)
    meeting_link = Column(String(500), nullable=True)
    meeting_passcode = Column(String(100), nullable=True)
    location_address = Column(String(500), nullable=True)
    room_name = Column(String(100), nullable=True)
    interviewer_name = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String(50), default="scheduled", nullable=False)  # scheduled, completed, cancelled
    feedback = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    applicant = relationship("Applicant", back_populates="interviews")


class TestQuestion(Base):
    __tablename__ = "test_questions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    category = Column(String(50), nullable=False)  # 'psikotes' or 'user_test'
    department = Column(String(100), nullable=True)  # 'General', 'IT', 'Engineering', etc.
    question = Column(Text, nullable=False)
    question_type = Column(String(50), default="single_choice", nullable=False)  # 'single_choice', 'multi_choice', 'essay'
    image_url = Column(Text, nullable=True)
    options = Column(Text, nullable=False)  # JSON string of options [A, B, C, D]
    correct_key = Column(String(10), nullable=True)  # 'A', 'B', 'C', 'D' or null
    points = Column(Integer, default=10, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class TestSubmission(Base):
    __tablename__ = "test_submissions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    applicant_id = Column(Integer, ForeignKey("applicants.id", ondelete="CASCADE"), nullable=False)
    test_type = Column(String(50), nullable=False)  # 'psikotes' or 'user_test'
    score = Column(Integer, default=0, nullable=True)
    show_score = Column(Boolean, default=False, nullable=False)
    answers = Column(Text, nullable=False)  # JSON string of responses
    question_set = Column(Text, nullable=True)  # JSON string of randomized question IDs
    option_map = Column(Text, nullable=True)  # JSON string of option mapping
    violations_count = Column(Integer, default=0, nullable=False)  # Anti-cheat tab strike count
    is_locked = Column(Boolean, default=False, nullable=False)
    is_passed = Column(Boolean, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    applicant = relationship("Applicant", back_populates="test_submissions")


class KaryawanSementara(Base):
    __tablename__ = "karyawan_sementara"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    applicant_id = Column(Integer, ForeignKey("applicants.id"), unique=True, nullable=False)
    nik_sementara = Column(String(50), unique=True, index=True, nullable=False)
    nama_lengkap = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    no_hp = Column(String(50), nullable=False)
    departemen = Column(String(100), nullable=False)
    jabatan = Column(String(150), nullable=False)
    tanggal_bergabung = Column(DateTime(timezone=True), nullable=False)
    status_integrasi = Column(String(50), default="ready", nullable=False)  # ready, synced
    id_card_printed = Column(Boolean, default=False, nullable=False)
    photo_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    applicant = relationship("Applicant", back_populates="karyawan_data")


class RecruitmentSetting(Base):
    __tablename__ = "recruitment_settings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
