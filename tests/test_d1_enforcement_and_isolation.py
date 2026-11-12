import os
os.environ["ENVIRONMENT"] = "test"
os.environ["DEBUG"] = "true"
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import pyotp
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
import app.db.session as db_session
from app.core.config import settings
settings.ENVIRONMENT = "test"

from app.core.security import create_access_token, get_password_hash
from app.models.auth import RecruitmentAdmin, User
from app.api.deps import (
    get_authenticated_admin_base,
    get_cms_user_base,
    get_current_admin,
    get_current_cms_user,
    require_account_identity,
)
from app.api.v1.endpoints.auth import (
    get_ats_admin_mfa_setup,
    verify_ats_admin_mfa,
    get_cms_user_mfa,
    activate_cms_mfa,
)

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


def make_request(headers: dict = None, path: str = "/"):
    req = MagicMock()
    headers_dict = {k.lower(): v for k, v in (headers or {}).items()}
    req.headers.get = lambda k, default=None: headers_dict.get(k.lower(), default)
    req.url.path = path
    return req


@pytest.fixture(autouse=True)
def setup_test_users():
    """Setup testing fixtures for ATS Admin and CMS User."""
    db = TestingSessionLocal()
    db.query(RecruitmentAdmin).delete()
    db.query(User).delete()

    admin1 = RecruitmentAdmin(
        id=1,
        username="admin_ats_1",
        name="ATS Admin 1",
        email="admin1@ats.local",
        password=get_password_hash("ValidPass1234!"),
        role="admin",
        is_active=True,
        is_first_login=False,
        is_mfa_enabled=True,
        mfa_secret="JBSWY3DPEHPK3PXP",
        mfa_verified_at=datetime.now(timezone.utc),
        session_version=1,
    )
    admin2 = RecruitmentAdmin(
        id=2,
        username="admin_ats_2",
        name="ATS Admin 2",
        email="admin2@ats.local",
        password=get_password_hash("ValidPass1234!"),
        role="hr",
        is_active=True,
        is_first_login=True,
        is_mfa_enabled=False,
        mfa_secret=None,
        session_version=1,
    )
    user1 = User(
        id=10,
        username="user_cms_10",
        email="user10@cms.local",
        name="CMS User 10",
        password=get_password_hash("ValidPass1234!"),
        role="marketing",
        is_active=True,
        is_first_login=False,
        mfa_enabled=True,
        mfa_secret="JBSWY3DPEHPK3PXP",
        mfa_verified_at=datetime.now(timezone.utc),
        session_version=1,
    )
    user2 = User(
        id=20,
        username="user_cms_20",
        email="user20@cms.local",
        name="CMS User 20",
        password=get_password_hash("ValidPass1234!"),
        role="admin",
        is_active=True,
        is_first_login=True,
        mfa_enabled=False,
        mfa_secret=None,
        session_version=1,
    )
    db.add_all([admin1, admin2, user1, user2])
    db.commit()
    db.close()


def test_amendment_1_header_isolation():
    """X-CMS-User-Id is strictly ignored by ATS, and X-Admin-Id is ignored by CMS."""
    valid_secret = settings.INTERNAL_API_SECRET
    db = TestingSessionLocal()

    # 1. Calling ATS base dependency with X-CMS-User-Id only -> REJECTED (403)
    req1 = make_request({"X-Internal-Secret": valid_secret, "X-CMS-User-Id": "1"})
    with pytest.raises(HTTPException) as exc1:
        get_authenticated_admin_base(request=req1, credentials=None, db=db)
    assert exc1.value.status_code == 403
    assert "X-CMS-User-Id tidak berlaku" in exc1.value.detail

    # 2. Calling CMS base dependency with X-Admin-Id only -> REJECTED (403)
    req2 = make_request({"X-Internal-Secret": valid_secret, "X-Admin-Id": "10"})
    with pytest.raises(HTTPException) as exc2:
        get_cms_user_base(request=req2, credentials=None, db_company=db)
    assert exc2.value.status_code == 403
    assert "X-Admin-Id tidak berlaku" in exc2.value.detail

    # 3. Calling ATS base dependency with proper X-Admin-Id -> SUCCESS
    req3 = make_request({"X-Internal-Secret": valid_secret, "X-Admin-Id": "1"})
    admin = get_authenticated_admin_base(request=req3, credentials=None, db=db)
    assert admin.id == 1
    assert admin.username == "admin_ats_1"


def test_amendment_2_anti_idor_protection():
    """Attempting to access another user's MFA setup or verify triggers 403 IDOR_DETECTED."""
    valid_secret = settings.INTERNAL_API_SECRET
    db = TestingSessionLocal()
    admin1 = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.id == 1).first()
    user10 = db.query(User).filter(User.id == 10).first()

    # 1. require_account_identity: ID mismatch triggers 403 IDOR_DETECTED
    with pytest.raises(HTTPException) as exc1:
        require_account_identity(admin1, 2)
    assert exc1.value.status_code == 403
    assert "IDOR_DETECTED" in exc1.value.detail

    # 2. ATS MFA Setup: Authenticated as Admin 1, trying to access Admin 2 setup -> 403 IDOR
    req = make_request({"X-Internal-Secret": valid_secret, "X-Admin-Id": "1"}, path="/api/v1/auth/ats-mfa/2/setup")
    with pytest.raises(HTTPException) as exc2:
        get_ats_admin_mfa_setup(admin_id=2, request=req, db=db, db_company=db, current_admin=admin1)
    assert exc2.value.status_code == 403
    assert "IDOR_DETECTED" in exc2.value.detail

    # 3. ATS MFA Verify: Authenticated as Admin 1, payload targets Admin 2 -> 403 IDOR
    req_verify = make_request({"X-Internal-Secret": valid_secret, "X-Admin-Id": "1"}, path="/api/v1/auth/ats-mfa/verify")
    with pytest.raises(HTTPException) as exc3:
        verify_ats_admin_mfa(
            payload={"admin_id": 2, "code": "123456", "enable": True},
            request=req_verify,
            db=db,
            db_company=db,
            current_admin=admin1,
        )
    assert exc3.value.status_code == 403
    assert "IDOR_DETECTED" in exc3.value.detail

    # 4. CMS MFA Info: Authenticated as User 10, trying to read User 20 -> 403 IDOR
    req_cms = make_request({"X-Internal-Secret": valid_secret, "X-CMS-User-Id": "10"}, path="/api/v1/auth/cms-mfa/20")
    with pytest.raises(HTTPException) as exc4:
        get_cms_user_mfa(user_id=20, request=req_cms, db=db, current_user=user10)
    assert exc4.value.status_code == 403
    assert "IDOR_DETECTED" in exc4.value.detail


def test_amendment_8_totp_rate_limiting_and_anti_replay():
    """TOTP fails lock after 5 attempts and rejects replay in same timestep window."""
    valid_secret = settings.INTERNAL_API_SECRET
    db = TestingSessionLocal()
    admin = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.id == 2).first()
    admin.mfa_secret = "JBSWY3DPEHPK3PXP"
    admin.is_mfa_enabled = False
    admin.totp_failed_attempts = 0
    admin.totp_locked_until = None
    db.commit()

    req = make_request({"X-Internal-Secret": valid_secret, "X-Admin-Id": "2"}, path="/api/v1/auth/ats-mfa/verify")

    # 1. Send 5 invalid codes
    for i in range(5):
        with pytest.raises(HTTPException) as exc:
            verify_ats_admin_mfa(
                payload={"admin_id": 2, "code": "999999", "enable": True},
                request=req,
                db=db,
                db_company=db,
                current_admin=admin,
            )
        assert exc.value.status_code == 400

    # 2. 6th attempt should be LOCKED (429)
    with pytest.raises(HTTPException) as exc_locked:
        verify_ats_admin_mfa(
            payload={"admin_id": 2, "code": "999999", "enable": True},
            request=req,
            db=db,
            db_company=db,
            current_admin=admin,
        )
    assert exc_locked.value.status_code == 429
    assert "terkunci sementara" in exc_locked.value.detail.lower()

    # Reset lockout for replay test
    admin.totp_locked_until = None
    admin.totp_failed_attempts = 0
    db.commit()

    # 3. Generate valid TOTP and verify
    totp = pyotp.TOTP("JBSWY3DPEHPK3PXP")
    valid_code = totp.now()

    res = verify_ats_admin_mfa(
        payload={"admin_id": 2, "code": valid_code, "enable": True},
        request=req,
        db=db,
        db_company=db,
        current_admin=admin,
    )
    assert res["success"] is True
    assert admin.is_mfa_enabled is True
    assert admin.mfa_verified_at is not None

    # 4. Replay same code immediately -> REJECTED (400)
    # Admin is now mfa_enabled=True, attempting re-enable with same code
    with pytest.raises(HTTPException) as exc_replay:
        verify_ats_admin_mfa(
            payload={"admin_id": 2, "code": valid_code, "enable": True},
            request=req,
            db=db,
            db_company=db,
            current_admin=admin,
        )
    assert exc_replay.value.status_code == 400


def test_amendment_3_and_7_operational_enforcement_option_a():
    """Operational dependencies reject unverified / stale sessions."""
    orig_enforce = settings.FIRST_LOGIN_ENFORCE
    settings.FIRST_LOGIN_ENFORCE = True
    try:
        db = TestingSessionLocal()
        admin2 = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.id == 2).first()
        admin2.is_first_login = True
        db.commit()

        # Admin 2 has is_first_login = True -> operational dependency MUST REJECT (403)
        req_ats = make_request({
            "X-Internal-Secret": settings.INTERNAL_API_SECRET,
            "X-Admin-Id": "2",
            "X-Session-Version": "1",
        })
        with pytest.raises(HTTPException) as exc1:
            get_current_admin(request=req_ats, credentials=None, db=db)
        assert exc1.value.status_code == 403
        assert "FIRST_LOGIN_REQUIRED" in exc1.value.detail

        # But base dependency (setup flow) MUST PERMIT
        admin_base = get_authenticated_admin_base(request=req_ats, credentials=None, db=db)
        assert admin_base.id == 2
        assert admin_base.is_first_login is True

        # Stale token test: token created with session_version=1
        token = create_access_token(subject=1, role="admin", extra_claims={"type": "ats", "session_version": 1})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        req_jwt = make_request({})

        # Bump session_version on Admin 1 to 2
        admin1 = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.id == 1).first()
        admin1.session_version = 2
        db.commit()

        # Token with session_version=1 must be REJECTED (401)
        with pytest.raises(HTTPException) as exc2:
            get_authenticated_admin_base(request=req_jwt, credentials=creds, db=db)
        assert exc2.value.status_code == 401
        assert "dibatalkan" in exc2.value.detail.lower()
    finally:
        settings.FIRST_LOGIN_ENFORCE = orig_enforce
