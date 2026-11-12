"""
Tests for two backend hardening measures (FIRST_LOGIN_ENFORCE gate):

1. Mandatory X-Session-Version header when FIRST_LOGIN_ENFORCE=true and
   a real identity header (X-Admin-Id / X-CMS-User-Id) is present.
   When FIRST_LOGIN_ENFORCE=false, the old behaviour (optional header) is preserved.

2. Role-only fallback path (synthetic admin_internal / cms_internal, id=0)
   is blocked for operational endpoints (get_current_admin / get_current_cms_user)
   when FIRST_LOGIN_ENFORCE=true. Base dependencies still allow it.
   When FIRST_LOGIN_ENFORCE=false, role-only works as before.
"""
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
from app.models.auth import RecruitmentAdmin, User
from app.api.deps import (
    get_authenticated_admin_base,
    get_cms_user_base,
    get_current_admin,
    get_current_cms_user,
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
def setup_test_data():
    """Create ATS admin and CMS user with session_version=1, fully verified."""
    db = TestingSessionLocal()
    db.query(RecruitmentAdmin).delete()
    db.query(User).delete()

    ats_admin = RecruitmentAdmin(
        id=1,
        username="admin_test",
        name="ATS Admin Test",
        email="admin@test.local",
        password=get_password_hash("TestPass1234!"),
        role="admin",
        is_active=True,
        is_first_login=False,
        is_mfa_enabled=True,
        mfa_secret="JBSWY3DPEHPK3PXP",
        mfa_verified_at=datetime.now(timezone.utc),
        session_version=1,
    )
    cms_user = User(
        id=10,
        username="cms_test",
        email="cms@test.local",
        name="CMS User Test",
        password=get_password_hash("TestPass1234!"),
        role="admin",
        is_active=True,
        is_first_login=False,
        mfa_enabled=True,
        mfa_secret="JBSWY3DPEHPK3PXP",
        mfa_verified_at=datetime.now(timezone.utc),
        session_version=1,
    )
    db.add_all([ats_admin, cms_user])
    db.commit()
    db.close()


# ── 1. Mandatory X-Session-Version ──────────────────────────────────────────


class TestSessionVersionMandatory:
    """X-Session-Version MUST be present with identity headers when FIRST_LOGIN_ENFORCE=true."""

    def test_ats_admin_id_without_session_version_rejected_when_enforce_true(self):
        orig = settings.FIRST_LOGIN_ENFORCE
        settings.FIRST_LOGIN_ENFORCE = True
        try:
            db = TestingSessionLocal()
            req = make_request({
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-Admin-Id": "1",
            })
            with pytest.raises(HTTPException) as exc:
                get_current_admin(request=req, credentials=None, db=db)
            assert exc.value.status_code == 401
            assert "X-Session-Version" in exc.value.detail
        finally:
            settings.FIRST_LOGIN_ENFORCE = orig

    def test_ats_admin_id_without_session_version_accepted_when_enforce_false(self):
        orig = settings.FIRST_LOGIN_ENFORCE
        settings.FIRST_LOGIN_ENFORCE = False
        try:
            db = TestingSessionLocal()
            req = make_request({
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-Admin-Id": "1",
            })
            admin = get_current_admin(request=req, credentials=None, db=db)
            assert admin.id == 1
        finally:
            settings.FIRST_LOGIN_ENFORCE = orig

    def test_ats_admin_id_with_session_version_accepted_when_enforce_true(self):
        orig = settings.FIRST_LOGIN_ENFORCE
        settings.FIRST_LOGIN_ENFORCE = True
        try:
            db = TestingSessionLocal()
            req = make_request({
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-Admin-Id": "1",
                "X-Session-Version": "1",
            })
            admin = get_current_admin(request=req, credentials=None, db=db)
            assert admin.id == 1
        finally:
            settings.FIRST_LOGIN_ENFORCE = orig

    def test_cms_user_id_without_session_version_rejected_when_enforce_true(self):
        orig = settings.FIRST_LOGIN_ENFORCE
        settings.FIRST_LOGIN_ENFORCE = True
        try:
            db = TestingSessionLocal()
            req = make_request({
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-CMS-User-Id": "10",
            })
            with pytest.raises(HTTPException) as exc:
                get_current_cms_user(request=req, credentials=None, db_company=db)
            assert exc.value.status_code == 401
            assert "X-Session-Version" in exc.value.detail
        finally:
            settings.FIRST_LOGIN_ENFORCE = orig

    def test_cms_user_id_without_session_version_accepted_when_enforce_false(self):
        orig = settings.FIRST_LOGIN_ENFORCE
        settings.FIRST_LOGIN_ENFORCE = False
        try:
            db = TestingSessionLocal()
            req = make_request({
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-CMS-User-Id": "10",
            })
            user = get_current_cms_user(request=req, credentials=None, db_company=db)
            assert user.id == 10
        finally:
            settings.FIRST_LOGIN_ENFORCE = orig

    def test_cms_user_id_with_session_version_accepted_when_enforce_true(self):
        orig = settings.FIRST_LOGIN_ENFORCE
        settings.FIRST_LOGIN_ENFORCE = True
        try:
            db = TestingSessionLocal()
            req = make_request({
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-CMS-User-Id": "10",
                "X-Session-Version": "1",
            })
            user = get_current_cms_user(request=req, credentials=None, db_company=db)
            assert user.id == 10
        finally:
            settings.FIRST_LOGIN_ENFORCE = orig


# ── 2. Role-only fallback blocked for operational endpoints ──────────────────


class TestRoleOnlyFallback:
    """Synthetic id=0 accounts via role-only header are blocked by operational deps when FIRST_LOGIN_ENFORCE=true."""

    def test_ats_role_only_rejected_by_operational_dep_when_enforce_true(self):
        """get_current_admin rejects role-only (admin_internal, id=0) when FIRST_LOGIN_ENFORCE=true."""
        orig = settings.FIRST_LOGIN_ENFORCE
        settings.FIRST_LOGIN_ENFORCE = True
        try:
            db = TestingSessionLocal()
            req = make_request({
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-Admin-Role": "admin",
            })
            with pytest.raises(HTTPException) as exc:
                get_current_admin(request=req, credentials=None, db=db)
            assert exc.value.status_code == 401
            assert "X-Admin-Id" in exc.value.detail
        finally:
            settings.FIRST_LOGIN_ENFORCE = orig

    def test_ats_role_only_accepted_by_operational_dep_when_enforce_false(self):
        """get_current_admin allows role-only (admin_internal, id=0) when FIRST_LOGIN_ENFORCE=false."""
        orig = settings.FIRST_LOGIN_ENFORCE
        settings.FIRST_LOGIN_ENFORCE = False
        try:
            db = TestingSessionLocal()
            req = make_request({
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-Admin-Role": "admin",
            })
            admin = get_current_admin(request=req, credentials=None, db=db)
            assert admin.id == 0
            assert admin.username == "admin_internal"
        finally:
            settings.FIRST_LOGIN_ENFORCE = orig

    def test_ats_role_only_accepted_by_base_dep_regardless(self):
        """get_authenticated_admin_base still allows role-only even when FIRST_LOGIN_ENFORCE=true."""
        orig = settings.FIRST_LOGIN_ENFORCE
        settings.FIRST_LOGIN_ENFORCE = True
        try:
            db = TestingSessionLocal()
            req = make_request({
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-Admin-Role": "admin",
            })
            admin = get_authenticated_admin_base(request=req, credentials=None, db=db)
            assert admin.id == 0
            assert admin.username == "admin_internal"
        finally:
            settings.FIRST_LOGIN_ENFORCE = orig

    def test_cms_role_only_rejected_by_operational_dep_when_enforce_true(self):
        """get_current_cms_user rejects role-only (cms_internal, id=0) when FIRST_LOGIN_ENFORCE=true."""
        orig = settings.FIRST_LOGIN_ENFORCE
        settings.FIRST_LOGIN_ENFORCE = True
        try:
            db = TestingSessionLocal()
            req = make_request({
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-Admin-Role": "admin",
            })
            with pytest.raises(HTTPException) as exc:
                get_current_cms_user(request=req, credentials=None, db_company=db)
            assert exc.value.status_code == 401
            assert "X-CMS-User-Id" in exc.value.detail
        finally:
            settings.FIRST_LOGIN_ENFORCE = orig

    def test_cms_role_only_accepted_by_operational_dep_when_enforce_false(self):
        """get_current_cms_user allows role-only (cms_internal, id=0) when FIRST_LOGIN_ENFORCE=false."""
        orig = settings.FIRST_LOGIN_ENFORCE
        settings.FIRST_LOGIN_ENFORCE = False
        try:
            db = TestingSessionLocal()
            req = make_request({
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-Admin-Role": "admin",
            })
            user = get_current_cms_user(request=req, credentials=None, db_company=db)
            assert user.id == 0
            assert user.username == "cms_internal"
        finally:
            settings.FIRST_LOGIN_ENFORCE = orig

    def test_cms_role_only_accepted_by_base_dep_regardless(self):
        """get_cms_user_base still allows role-only even when FIRST_LOGIN_ENFORCE=true."""
        orig = settings.FIRST_LOGIN_ENFORCE
        settings.FIRST_LOGIN_ENFORCE = True
        try:
            db = TestingSessionLocal()
            req = make_request({
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-Admin-Role": "admin",
            })
            user = get_cms_user_base(request=req, credentials=None, db_company=db)
            assert user.id == 0
            assert user.username == "cms_internal"
        finally:
            settings.FIRST_LOGIN_ENFORCE = orig

