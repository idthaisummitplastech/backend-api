from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from app.db.base_class import Base


class RecruitmentAdmin(Base):
    """Admin and Evaluator accounts for Recruitment Portal with RBAC and MFA."""
    __tablename__ = "recruitment_admins"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    name = Column(String(200), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)  # Bcrypt hash
    role = Column(String(50), default="hr", nullable=False)  # 'hr', 'user_dept', 'admin'
    department = Column(String(100), nullable=True)
    mfa_secret = Column(String(100), nullable=True)
    is_mfa_enabled = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class User(Base):
    """Company Profile CMS Admin User."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)  # Bcrypt hash
    name = Column(String(200), nullable=False)
    role = Column(String(50), default="admin", nullable=False)
    mfa_enabled = Column(Boolean, default=False, nullable=False)
    mfa_secret = Column(String(100), nullable=True)
    backup_codes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
