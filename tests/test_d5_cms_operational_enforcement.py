import os
os.environ["ENVIRONMENT"] = "test"
os.environ["DEBUG"] = "true"
from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
import app.db.session as db_session
from app.core.config import settings
settings.ENVIRONMENT = "test"

from app.core.security import get_password_hash
from app.models.auth import User, RecruitmentAdmin
from app.api.deps import (
    get_current_cms_user,
    get_cms_user_base,
    require_account_identity,
)
from app.api.v1.endpoints.cms import (
    get_dashboard_stats,
    get_cms_profile,
    update_cms_profile,
    create_cms_item,
    update_cms_item,
    delete_cms_item,
    check_cms_write_access,
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
def setup_cms_users():
    """Setup CMS test users: verified admin, first-login admin, marketing staff."""
    db = TestingSessionLocal()
    db.query(User).delete()

    admin_ready = User(
        id=101,
        username="cms_admin_ready",
        email="ready@itsp.co.id",
        name="CMS Admin Ready",
        password=get_password_hash("ValidPass1234!"),
        role="admin",
        is_active=True,
        is_first_login=False,
        mfa_enabled=True,
        mfa_secret="JBSWY3DPEHPK3PXP",
        mfa_verified_at=datetime.now(timezone.utc),
        session_version=1,
    )
    admin_first_login = User(
        id=102,
        username="cms_admin_first",
        email="first@itsp.co.id",
        name="CMS Admin First Login",
        password=get_password_hash("ValidPass1234!"),
        role="admin",
        is_active=True,
        is_first_login=True,
        mfa_enabled=False,
        mfa_secret=None,
        session_version=1,
    )
    marketing_user = User(
        id=103,
        username="cms_marketing",
        email="marketing@itsp.co.id",
        name="CMS Marketing Staff",
        password=get_password_hash("ValidPass1234!"),
        role="marketing",
        is_active=True,
        is_first_login=False,
        mfa_enabled=True,
        mfa_secret="JBSWY3DPEHPK3PXP",
        mfa_verified_at=datetime.now(timezone.utc),
        session_version=1,
    )
    db.add_all([admin_ready, admin_first_login, marketing_user])
    db.commit()
    db.close()


def test_d5_operational_dependency_blocks_first_login_cms_user():
    """get_current_cms_user must reject users with is_first_login=True when FIRST_LOGIN_ENFORCE=True."""
    orig_enforce = settings.FIRST_LOGIN_ENFORCE
    settings.FIRST_LOGIN_ENFORCE = True
    try:
        db = TestingSessionLocal()
        req = make_request({"X-Internal-Secret": settings.INTERNAL_API_SECRET, "X-CMS-User-Id": "102"})

        with pytest.raises(HTTPException) as exc:
            get_current_cms_user(request=req, credentials=None, db_company=db)
        assert exc.value.status_code == 403
        assert "FIRST_LOGIN_REQUIRED" in exc.value.detail
    finally:
        settings.FIRST_LOGIN_ENFORCE = orig_enforce


def test_d5_dashboard_stats_enforces_auth_and_restricts_recent_contacts():
    """Dashboard stats requires get_current_cms_user and hides recent_contacts from marketing."""
    db = TestingSessionLocal()
    admin_ready = db.query(User).filter(User.id == 101).first()
    mkt_user = db.query(User).filter(User.id == 103).first()
    req = make_request()

    # 1. Admin receives dashboard stats with recent_contacts list
    res_admin = get_dashboard_stats(request=req, db=db, current_user=admin_ready)
    assert res_admin.data["user_count"] >= 3
    assert "recent_contacts" in res_admin.data

    # 2. Marketing receives dashboard stats but recent_contacts is empty
    res_mkt = get_dashboard_stats(request=req, db=db, current_user=mkt_user)
    assert res_mkt.data["user_count"] >= 3
    assert res_mkt.data["recent_contacts"] == []


def test_d5_profile_idor_protection_and_password_change_flow():
    """Profile endpoint enforces anti-IDOR, allows password change for first-login, and resets MFA verification."""
    db = TestingSessionLocal()
    user_first = db.query(User).filter(User.id == 102).first()
    user_ready = db.query(User).filter(User.id == 101).first()
    req = make_request({"X-Internal-Secret": settings.INTERNAL_API_SECRET, "X-CMS-User-Id": "101"})

    # 1. Accessing other user's profile triggers 403 IDOR_DETECTED
    with pytest.raises(HTTPException) as exc_idor:
        get_cms_profile(user_id=102, request=req, db=db, current_user=user_ready)
    assert exc_idor.value.status_code == 403
    assert "IDOR_DETECTED" in exc_idor.value.detail

    # 2. First login user can change password via get_cms_user_base
    change_payload = {
        "user_id": 102,
        "action": "change_password",
        "current_password": "ValidPass1234!",
        "new_password": "NewSecretPassword123!",
    }
    res_pw = update_cms_profile(
        payload=change_payload,
        request=req,
        db=db,
        karir_db=db,
        current_user=user_first,
    )
    assert res_pw.message == "Kata sandi berhasil diubah."

    # Verify user state after password change: is_first_login is cleared, session_version incremented, mfa_verified_at None
    db.refresh(user_first)
    assert user_first.is_first_login is False
    assert user_first.session_version == 2
    assert user_first.mfa_verified_at is None
    assert user_first.password_changed_at is not None


def test_d5_cms_write_access_roles():
    """Verify write permission partitioning between admin and marketing roles."""
    db = TestingSessionLocal()
    admin_ready = db.query(User).filter(User.id == 101).first()
    mkt_user = db.query(User).filter(User.id == 103).first()

    # Marketing cannot write to sensitive models (e.g. users) -> 403
    with pytest.raises(HTTPException) as exc_mkt:
        check_cms_write_access("users", mkt_user)
    assert exc_mkt.value.status_code == 403
    assert "Administrator" in exc_mkt.value.detail

    # Marketing can write to content models (e.g. blog-posts) -> Allowed
    check_cms_write_access("blog-posts", mkt_user)

    # Admin can write to all models
    check_cms_write_access("users", admin_ready)
    check_cms_write_access("products", admin_ready)


def test_cms_role_from_db_and_mismatched_header_rejected_403():
    """
    A.4: get_current_cms_user / get_cms_user_base menggunakan peran dari baris DB User.
    Jika header X-Admin-Role dikirim dan berbeda dengan database, tolak 403.
    """
    db = TestingSessionLocal()
    mkt_user = db.query(User).filter(User.id == 103).first()
    assert mkt_user.role == "marketing"

    # 1. Header X-Admin-Role = 'admin' tapi di DB adalah 'marketing' -> TOLAK 403
    req_mismatch = make_request({
        "X-Internal-Secret": settings.INTERNAL_API_SECRET,
        "X-CMS-User-Id": "103",
        "X-Admin-Role": "admin",
    })
    with pytest.raises(HTTPException) as exc:
        get_cms_user_base(request=req_mismatch, credentials=None, db_company=db)
    assert exc.value.status_code == 403
    assert "Header role tidak sesuai dengan data akun" in exc.value.detail

    # 2. Header X-Admin-Role cocok ('marketing') -> SUKSES, peran dari DB
    req_match = make_request({
        "X-Internal-Secret": settings.INTERNAL_API_SECRET,
        "X-CMS-User-Id": "103",
        "X-Admin-Role": "marketing",
    })
    user_resolved = get_cms_user_base(request=req_match, credentials=None, db_company=db)
    assert user_resolved.id == 103
    assert user_resolved.role == "marketing"

    # 3. Tanpa header X-Admin-Role -> SUKSES, peran mutlak dari DB
    req_no_role = make_request({
        "X-Internal-Secret": settings.INTERNAL_API_SECRET,
        "X-CMS-User-Id": "103",
    })
    user_no_role = get_cms_user_base(request=req_no_role, credentials=None, db_company=db)
    assert user_no_role.id == 103
    assert user_no_role.role == "marketing"


def test_stale_session_rejected_after_password_change_and_reset_both_enforce_modes():
    """
    A.1: Cookie/versi sesi usang ditolak setelah ganti password dan setelah reset-password,
    baik FIRST_LOGIN_ENFORCE=true maupun false.
    """
    from fastapi.security import HTTPAuthorizationCredentials
    from app.core.security import create_access_token

    for enforce_mode in [True, False]:
        orig_enforce = settings.FIRST_LOGIN_ENFORCE
        settings.FIRST_LOGIN_ENFORCE = enforce_mode
        try:
            db = TestingSessionLocal()
            user = db.query(User).filter(User.id == 101).first()
            user.session_version = 1
            user.password_changed_at = datetime.now(timezone.utc)
            db.commit()

            # --- Skenario 1: Setelah reset-password / ganti password, session_version naik ke 2 ---
            user.session_version = 2
            db.commit()

            # Panggilan via internal helper dengan header X-Session-Version: 1 (usang) -> 401
            req_stale_header = make_request({
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-CMS-User-Id": "101",
                "X-Session-Version": "1",
            })
            with pytest.raises(HTTPException) as exc1:
                get_cms_user_base(request=req_stale_header, credentials=None, db_company=db)
            assert exc1.value.status_code == 401
            assert "dibatalkan" in exc1.value.detail.lower()

            # Panggilan via JWT dengan session_version: 1 (usang) -> 401
            token_stale = create_access_token(
                subject=101,
                role="admin",
                extra_claims={"type": "cms", "session_version": 1}
            )
            creds_stale = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token_stale)
            req_jwt = make_request({})
            with pytest.raises(HTTPException) as exc2:
                get_cms_user_base(request=req_jwt, credentials=creds_stale, db_company=db)
            assert exc2.value.status_code == 401
            assert "dibatalkan" in exc2.value.detail.lower()

            # Panggilan dengan X-Session-Version: 2 (terkini) -> SUKSES
            req_valid = make_request({
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-CMS-User-Id": "101",
                "X-Session-Version": "2",
            })
            user_ok = get_cms_user_base(request=req_valid, credentials=None, db_company=db)
            assert user_ok.id == 101
        finally:
            settings.FIRST_LOGIN_ENFORCE = orig_enforce


