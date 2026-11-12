from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from app.db.base_class import Base


class RecruitmentAdmin(Base):
    """Admin and Evaluator accounts for Recruitment Portal with RBAC and MFA — login via Employee ID."""
    __tablename__ = "recruitment_admins"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    employee_id = Column(String(50), unique=True, index=True, nullable=True)  # Immutable FK data_karyawan.employee_id 004.02.16
    username = Column(String(100), unique=True, index=True, nullable=False)
    name = Column(String(200), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)  # Bcrypt hash
    role = Column(String(50), default="hr", nullable=False)  # 'hr', 'user_dept', 'admin'
    department = Column(String(100), nullable=True)
    mfa_secret = Column(String(100), nullable=True)
    is_mfa_enabled = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    portal_access = Column(String(20), default="both", nullable=False)  # perusahaan | karir | both
    is_first_login = Column(Boolean, default=True, nullable=False)  # true=wajib ganti password saat login pertama
    mfa_verified_at = Column(DateTime(timezone=True), nullable=True)  # Waktu verifikasi MFA sesi terakhir
    password_changed_at = Column(DateTime(timezone=True), nullable=True)  # Waktu terakhir ganti kata sandi
    session_version = Column(Integer, default=1, nullable=False)  # Versi sesi untuk invalidasi token stale
    totp_failed_attempts = Column(Integer, default=0, nullable=False)  # Percobaan salah beruntun
    totp_locked_until = Column(DateTime(timezone=True), nullable=True)  # Waktu terkunci jika >= 5 percobaan salah
    last_used_totp_timestep = Column(Integer, nullable=True)  # Anti-replay 30s timestep window
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class User(Base):
    """Company Profile CMS Admin User — login via Employee ID."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    employee_id = Column(String(50), unique=True, index=True, nullable=True)  # Immutable FK data_karyawan.employee_id
    username = Column(String(100), unique=True, index=True, nullable=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)  # Bcrypt hash
    name = Column(String(200), nullable=False)
    role = Column(String(50), default="admin", nullable=False)
    department = Column(String(100), nullable=True)
    mfa_enabled = Column(Boolean, default=False, nullable=False)
    mfa_secret = Column(String(100), nullable=True)
    backup_codes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    portal_access = Column(String(20), default="both", nullable=False)  # perusahaan | karir | both
    is_first_login = Column(Boolean, default=True, nullable=False)
    mfa_verified_at = Column(DateTime(timezone=True), nullable=True)  # Waktu verifikasi MFA sesi terakhir
    password_changed_at = Column(DateTime(timezone=True), nullable=True)  # Waktu terakhir ganti kata sandi
    session_version = Column(Integer, default=1, nullable=False)  # Versi sesi untuk invalidasi token stale
    totp_failed_attempts = Column(Integer, default=0, nullable=False)  # Percobaan salah beruntun
    totp_locked_until = Column(DateTime(timezone=True), nullable=True)  # Waktu terkunci jika >= 5 percobaan salah
    last_used_totp_timestep = Column(Integer, nullable=True)  # Anti-replay 30s timestep window
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
