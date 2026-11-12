import os
os.environ["ENVIRONMENT"] = "test"
os.environ["DEBUG"] = "true"
import io
import logging
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
import app.db.session as db_session
from app.core.config import settings
settings.ENVIRONMENT = "test"

from app.core.security import get_password_hash, verify_password
from app.models.auth import RecruitmentAdmin, User
from scripts.reset_admin_mfa import execute_recovery, logger as audit_logger

# Setup in-memory SQLite engine
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=test_engine)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

db_session.engine = test_engine
db_session.engine_company = test_engine
db_session.SessionLocal = TestingSessionLocal
db_session.SessionCompanyLocal = TestingSessionLocal


@pytest.fixture(autouse=True)
def setup_recovery_fixtures():
    """Setup test users for disaster recovery tests."""
    db = TestingSessionLocal()
    db.query(RecruitmentAdmin).delete()
    db.query(User).delete()

    admin = RecruitmentAdmin(
        id=1,
        username="ats_super",
        name="Super ATS Admin",
        email="super@itsp.co.id",
        password=get_password_hash("OldPassword1234!"),
        role="admin",
        is_active=True,
        is_first_login=False,
        is_mfa_enabled=True,
        mfa_secret="JBSWY3DPEHPK3PXP",
        mfa_verified_at=datetime.now(timezone.utc),
        session_version=1,
        totp_failed_attempts=3,
        totp_locked_until=datetime.now(timezone.utc),
    )
    cms_user = User(
        id=10,
        username="cms_market",
        name="CMS Marketing Staff",
        email="super@itsp.co.id",  # Matching email for sync test
        password=get_password_hash("OldPassword1234!"),
        role="marketing",
        is_active=True,
        is_first_login=False,
        mfa_enabled=True,
        mfa_secret="JBSWY3DPEHPK3PXP",
        mfa_verified_at=datetime.now(timezone.utc),
        session_version=1,
    )
    db.add_all([admin, cms_user])
    db.commit()
    db.close()


def test_d2_rejects_invalid_realm_or_action():
    """Script fails fast if realm or action is invalid."""
    db = TestingSessionLocal()
    ok1, msg1, _ = execute_recovery("invalid_realm", "super@itsp.co.id", "reset-mfa", db_ats=db, db_cms=db)
    assert ok1 is False
    assert "realm wajib bernilai 'ats' atau 'cms'" in msg1

    ok2, msg2, _ = execute_recovery("ats", "super@itsp.co.id", "invalid_action", db_ats=db, db_cms=db)
    assert ok2 is False
    assert "action wajib bernilai" in msg2


def test_d2_action_reset_mfa_ats():
    """Action reset-mfa disables MFA, clears secret, clears lockout, bumps session_version."""
    db = TestingSessionLocal()
    ok, msg, _ = execute_recovery("ats", "super@itsp.co.id", "reset-mfa", db_ats=db, db_cms=db)
    assert ok is True

    admin = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.id == 1).first()
    assert admin.is_mfa_enabled is False
    assert admin.mfa_secret is None
    assert admin.mfa_verified_at is None
    assert admin.totp_failed_attempts == 0
    assert admin.totp_locked_until is None
    assert admin.session_version == 2


def test_d2_action_reset_password_and_first_login():
    """Action reset-password updates password, sets is_first_login=True, bumps session_version."""
    db = TestingSessionLocal()
    ok, msg, temp_pwd = execute_recovery(
        "ats",
        "super@itsp.co.id",
        "reset-password",
        custom_password="EmergencySecretPassword999!",
        db_ats=db,
        db_cms=db,
    )
    assert ok is True
    assert temp_pwd == "EmergencySecretPassword999!"

    admin = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.id == 1).first()
    assert verify_password("EmergencySecretPassword999!", admin.password) is True
    assert admin.is_first_login is True
    assert admin.password_changed_at is not None
    assert admin.session_version == 2


def test_d2_action_break_glass_with_sync():
    """Break-glass performs both password reset and MFA reset, and syncs to CMS peer account."""
    db = TestingSessionLocal()
    ok, msg, temp_pwd = execute_recovery(
        realm="ats",
        identifier="super@itsp.co.id",
        action="break-glass",
        sync=True,
        db_ats=db,
        db_cms=db,
    )
    assert ok is True
    assert temp_pwd is not None
    assert len(temp_pwd) >= 16

    # Verify ATS account
    admin = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.id == 1).first()
    assert admin.is_mfa_enabled is False
    assert admin.is_first_login is True
    assert verify_password(temp_pwd, admin.password) is True
    assert admin.session_version == 2

    # Verify synced CMS account
    cms_user = db.query(User).filter(User.id == 10).first()
    assert cms_user.mfa_enabled is False
    assert cms_user.is_first_login is True
    assert verify_password(temp_pwd, cms_user.password) is True
    assert cms_user.session_version == 2


def test_d2_audit_log_never_contains_password(caplog):
    """Audit log must record recovery execution details but NEVER log plaintext passwords or hashes."""
    db = TestingSessionLocal()
    secret_test_pwd = "SuperSecretPlainTextPasswordXYZ999!"

    with caplog.at_level(logging.INFO, logger="audit_recovery"):
        ok, msg, _ = execute_recovery(
            realm="cms",
            identifier="super@itsp.co.id",
            action="reset-password",
            custom_password=secret_test_pwd,
            db_ats=db,
            db_cms=db,
        )
        assert ok is True

    log_output = caplog.text
    # 1. Verification of audit record
    assert "RECOVERY_SUCCESS" in log_output
    assert "realm=cms" in log_output
    assert "action=reset-password" in log_output

    # 2. Strict Zero-Password Guarantee in logs
    assert secret_test_pwd not in log_output
    assert "password=" not in log_output.lower()
    assert "$2b$" not in log_output
