from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    Float,
    Numeric,
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

    # Extended Identity Fields
    nik = Column(String(50), nullable=True)
    first_name = Column(String(150), nullable=True)
    last_name = Column(String(150), nullable=True)
    gender = Column(String(50), nullable=True)
    religion = Column(String(50), nullable=True)
    ethnic = Column(String(50), nullable=True)
    height_cm = Column(Integer, nullable=True)
    weight_kg = Column(Integer, nullable=True)
    marriage_status = Column(String(50), nullable=True)
    birth_place = Column(String(150), nullable=True)

    # Extended Address Fields (KTP & Domicile)
    address_ktp = Column(Text, nullable=True)
    province_ktp = Column(String(100), nullable=True)
    city_ktp = Column(String(100), nullable=True)
    district_ktp = Column(String(100), nullable=True)
    village_ktp = Column(String(100), nullable=True)
    rt_ktp = Column(String(20), nullable=True)
    rw_ktp = Column(String(20), nullable=True)
    street_ktp = Column(String(255), nullable=True)

    domicile_same_as_ktp = Column(Boolean, default=True, nullable=True)
    address_domicile = Column(Text, nullable=True)
    province_domicile = Column(String(100), nullable=True)
    city_domicile = Column(String(100), nullable=True)
    district_domicile = Column(String(100), nullable=True)
    village_domicile = Column(String(100), nullable=True)
    rt_domicile = Column(String(20), nullable=True)
    rw_domicile = Column(String(20), nullable=True)
    street_domicile = Column(String(255), nullable=True)

    # Extended Document Upload Fields
    photo_file = Column(Text, nullable=True)
    ktp_file = Column(Text, nullable=True)
    kk_file = Column(Text, nullable=True)
    ijazah_file = Column(Text, nullable=True)
    transkrip_file = Column(Text, nullable=True)
    cert_nonformal_file = Column(Text, nullable=True)
    bpjs_kesehatan_file = Column(Text, nullable=True)
    bpjs_ketenagakerjaan_file = Column(Text, nullable=True)
    npwp_file = Column(Text, nullable=True)
    akta_file = Column(Text, nullable=True)
    skck_file = Column(Text, nullable=True)

    # Structured History & Family Data (JSON strings)
    education_history = Column(Text, nullable=True)
    work_history = Column(Text, nullable=True)
    family_parents = Column(Text, nullable=True)
    family_siblings = Column(Text, nullable=True)

    # 7-Stage Progress Tracker
    current_stage = Column(Integer, default=1, nullable=False)  # Stages 1 to 7
    stage_status = Column(String(50), default="in_progress", nullable=False)  # in_progress, passed, failed
    failed_at_stage = Column(Integer, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Stage 1: Screening Notes
    screening_notes = Column(Text, nullable=True)

    # Stage 2 & 3: Online Test Schedule, Token, Duration & Venue
    psikotes_scheduled_at = Column(DateTime(timezone=True), nullable=True)
    psikotes_duration_minutes = Column(Integer, default=60, nullable=True)
    psikotes_token = Column(String(50), nullable=True)
    psikotes_location = Column(String(255), default="Portal Karir Online PT ITSP", nullable=False)
    psikotes_maps_url = Column(String(500), nullable=True)

    user_test_scheduled_at = Column(DateTime(timezone=True), nullable=True)
    user_test_duration_minutes = Column(Integer, default=60, nullable=True)
    user_test_token = Column(String(50), nullable=True)
    user_test_location = Column(String(255), default="Portal Karir Online PT ITSP", nullable=False)
    user_test_maps_url = Column(String(500), nullable=True)

    # Stage 6 & 7: Medical & Offering
    mcu_notes = Column(Text, nullable=True)
    offering_letter = Column(Text, nullable=True)
    offering_salary = Column(String(100), nullable=True)
    offering_status = Column(String(50), default="pending", nullable=False)  # pending, issued, accepted, rejected
    offering_attachment = Column(Text, nullable=True)  # PDF attachment data URI / URL from HR
    offering_clauses = Column(Text, nullable=True)  # Editable clauses / terms by HR
    offering_signer_name = Column(String(150), nullable=True)  # Name of HR signatory
    offering_signer_title = Column(String(150), nullable=True)  # Title / Department of HR signatory
    offering_signer_signature = Column(Text, nullable=True)  # Digital signature (Base64 data URL) of HR
    offering_join_date = Column(String(100), nullable=True)  # Tanggal mulai bekerja
    offering_ref_number = Column(String(100), nullable=True)  # Nomor surat resmi korporat
    signed_contract_file = Column(Text, nullable=True)  # PDF signed by applicant
    contract_signed_at = Column(DateTime(timezone=True), nullable=True)
    is_employee = Column(Boolean, default=False, nullable=False)
    employee_id = Column(String(50), nullable=True)  # NIK Karyawan resmi misal 1530.09.26

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    job_posting = relationship("JobPosting", back_populates="applicants")
    test_submissions = relationship("TestSubmission", back_populates="applicant", cascade="all, delete-orphan")
    interviews = relationship("InterviewSchedule", back_populates="applicant", cascade="all, delete-orphan")
    karyawan_data = relationship("KaryawanSementara", back_populates="applicant", uselist=False, cascade="all, delete-orphan")
    data_karyawan = relationship("DataKaryawan", back_populates="applicant", uselist=False)


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
    maps_url = Column(String(500), nullable=True)
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


class DataKaryawan(Base):
    __tablename__ = "data_karyawan"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    employee_id = Column(String(50), unique=True, index=True, nullable=False)  # Format: {id}.{MM}.{YY} e.g. 1530.09.26
    sequence_number = Column(Integer, index=True, nullable=False)  # e.g. 1530
    applicant_id = Column(Integer, ForeignKey("applicants.id", ondelete="SET NULL"), unique=True, nullable=True)

    # Identitas Pribadi (lengkap dari formulir pendaftaran)
    full_name = Column(String(255), nullable=False)
    first_name = Column(String(150), nullable=True)
    last_name = Column(String(150), nullable=True)
    nik = Column(String(50), index=True, nullable=True)  # NIK KTP
    email = Column(String(255), index=True, nullable=True)
    phone = Column(String(50), nullable=True)
    birth_place = Column(String(150), nullable=True)
    birth_date = Column(DateTime(timezone=True), nullable=True)
    age = Column(Integer, nullable=True)
    gender = Column(String(50), nullable=True)
    religion = Column(String(50), nullable=True)
    ethnic = Column(String(50), nullable=True)
    height_cm = Column(Integer, nullable=True)
    weight_kg = Column(Integer, nullable=True)
    marriage_status = Column(String(50), nullable=True)
    blood_type = Column(String(10), nullable=True)

    # Alamat KTP
    address_ktp = Column(Text, nullable=True)
    province_ktp = Column(String(100), nullable=True)
    city_ktp = Column(String(100), nullable=True)
    district_ktp = Column(String(100), nullable=True)
    village_ktp = Column(String(100), nullable=True)
    rt_ktp = Column(String(20), nullable=True)
    rw_ktp = Column(String(20), nullable=True)
    street_ktp = Column(String(255), nullable=True)

    # Alamat Domisili
    domicile_same_as_ktp = Column(Boolean, default=True, nullable=True)
    address_domicile = Column(Text, nullable=True)
    province_domicile = Column(String(100), nullable=True)
    city_domicile = Column(String(100), nullable=True)
    district_domicile = Column(String(100), nullable=True)
    village_domicile = Column(String(100), nullable=True)
    rt_domicile = Column(String(20), nullable=True)
    rw_domicile = Column(String(20), nullable=True)
    street_domicile = Column(String(255), nullable=True)

    # Pendidikan & Riwayat
    last_education = Column(String(100), nullable=True)
    school_name = Column(String(255), nullable=True)
    major = Column(String(255), nullable=True)
    education_history = Column(Text, nullable=True)  # JSON
    work_history = Column(Text, nullable=True)  # JSON
    family_parents = Column(Text, nullable=True)  # JSON
    family_siblings = Column(Text, nullable=True)  # JSON

    # Kepegawaian & Kontrak Kerja Resmi
    job_title = Column(String(150), nullable=False)
    department = Column(String(100), index=True, nullable=False)
    work_location = Column(String(150), default="Plant PT ITSP Karawang", nullable=True)
    salary = Column(String(100), nullable=True)
    contract_start_date = Column(DateTime(timezone=True), nullable=False)  # Tanggal Mulai Kontrak
    contract_end_date = Column(DateTime(timezone=True), nullable=True)  # Tanggal Selesai Kontrak
    contract_duration_months = Column(Integer, default=12, nullable=True)
    contract_status = Column(String(50), default="PKWT 1", nullable=False)  # PKWT 1, PKWT 2, PKWTT, Percobaan
    contract_sequence = Column(Integer, default=1, nullable=True)  # Kontrak ke-berapa (e.g. 1, 2, 5, 7)
    contract_history = Column(Text, nullable=True)  # JSON riwayat seluruh tahapan kontrak (K1, K2, dst)
    years_of_service = Column(Float, nullable=True)  # Masa kerja dalam tahun (e.g. 4.81)
    level = Column(String(50), nullable=True)  # e.g. M1, M2, T1, T3, T10, O, TSP
    section = Column(String(100), nullable=True)  # e.g. Injection, Painting, Assembly, Molding
    employee_type = Column(String(50), nullable=True)  # Direct, Indirect, Admin, Thai Manager
    factory_office = Column(String(50), nullable=True)  # Factory, Office
    employee_status = Column(String(50), default="active", nullable=False)  # active, resign, end_of_contract

    # Berkas & Lampiran Dokumen
    photo_file = Column(Text, nullable=True)
    ktp_file = Column(Text, nullable=True)
    kk_file = Column(Text, nullable=True)
    ijazah_file = Column(Text, nullable=True)
    transkrip_file = Column(Text, nullable=True)
    npwp_file = Column(Text, nullable=True)
    bpjs_kesehatan_file = Column(Text, nullable=True)
    bpjs_ketenagakerjaan_file = Column(Text, nullable=True)
    skck_file = Column(Text, nullable=True)
    cv_file = Column(Text, nullable=True)
    signed_contract_file = Column(Text, nullable=True)

    hired_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    applicant = relationship("Applicant", back_populates="data_karyawan")
