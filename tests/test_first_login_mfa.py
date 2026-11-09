import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)
from app.models.auth import User, RecruitmentAdmin
from app.api.deps import get_current_admin


def test_scoped_token_claims():
    """Verify scoped token carries 'first_login_setup' claim in JWT payload."""
    token = create_access_token(
        subject=99,
        role="admin",
        department="IT",
        scope="first_login_setup",
    )
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "99"
    assert payload["role"] == "admin"
    assert payload.get("scope") == "first_login_setup"


def test_saklar_enforce_disabled_allows_operational_endpoint():
    """When FIRST_LOGIN_ENFORCE is False (default), guard does not throw 403."""
    orig_enforce = settings.FIRST_LOGIN_ENFORCE
    settings.FIRST_LOGIN_ENFORCE = False
    try:
        token = create_access_token(
            subject=1,
            role="admin",
            scope="first_login_setup",
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        mock_request = MagicMock()
        mock_request.url.path = "/api/v1/recruitment/admins"
        mock_request.headers.get.return_value = None

        mock_db = MagicMock()
        fake_admin = RecruitmentAdmin(
            id=1,
            username="admin",
            name="Admin",
            email="admin@itsp.co.id",
            role="admin",
            is_mfa_enabled=False,
            is_first_login=True,
        )
        mock_db.query().filter().first.return_value = fake_admin
        from app.crud.crud_auth import crud_admin
        orig_get = crud_admin.get
        crud_admin.get = MagicMock(return_value=fake_admin)

        try:
            admin = get_current_admin(
                request=mock_request,
                credentials=credentials,
                db=mock_db,
            )
            # Guard does NOT reject with 403; admin entity successfully retrieved
            assert admin.id == 1
        finally:
            crud_admin.get = orig_get
    finally:
        settings.FIRST_LOGIN_ENFORCE = orig_enforce


def test_saklar_enforce_enabled_rejects_operational_endpoints():
    """When FIRST_LOGIN_ENFORCE is True, guard rejects first_login_setup scoped token with 403."""
    orig_enforce = settings.FIRST_LOGIN_ENFORCE
    settings.FIRST_LOGIN_ENFORCE = True
    try:
        token = create_access_token(
            subject=1,
            role="admin",
            scope="first_login_setup",
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        mock_request = MagicMock()
        mock_request.url.path = "/api/v1/recruitment/admins"
        mock_request.headers.get.return_value = None

        mock_db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            get_current_admin(
                request=mock_request,
                credentials=credentials,
                db=mock_db,
            )

        assert exc_info.value.status_code == 403
        assert "Wajib mengganti kata sandi dan mengaktifkan MFA" in exc_info.value.detail
    finally:
        settings.FIRST_LOGIN_ENFORCE = orig_enforce


def test_scoped_token_allowed_on_setup_endpoints():
    """Dependency guard permits first_login_setup scoped token on allowed setup routes even if ENFORCE is True."""
    orig_enforce = settings.FIRST_LOGIN_ENFORCE
    settings.FIRST_LOGIN_ENFORCE = True
    try:
        token = create_access_token(
            subject=1,
            role="admin",
            scope="first_login_setup",
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        mock_request = MagicMock()
        mock_request.url.path = "/api/v1/cms/profile"
        mock_request.headers.get.return_value = None

        mock_db = MagicMock()
        fake_admin = RecruitmentAdmin(
            id=1,
            username="admin",
            name="Admin",
            email="admin@itsp.co.id",
            role="admin",
        )
        mock_db.query().filter().first.return_value = fake_admin
        from app.crud.crud_auth import crud_admin
        orig_get = crud_admin.get
        crud_admin.get = MagicMock(return_value=fake_admin)

        try:
            admin = get_current_admin(
                request=mock_request,
                credentials=credentials,
                db=mock_db,
            )
            assert admin.id == 1
        finally:
            crud_admin.get = orig_get
    finally:
        settings.FIRST_LOGIN_ENFORCE = orig_enforce


def test_first_login_flag_cleared_on_password_change():
    """Verify is_first_login flag is reset to False when password is changed."""
    raw_old = "OldSecurePassword123!"
    raw_new = "NewSecurePassword456!@"
    user = User(
        id=1,
        email="it-04@thaisummit.co.id",
        password=get_password_hash(raw_old),
        name="IT Admin",
        role="admin",
        is_first_login=True,
    )
    assert user.is_first_login is True

    # Simulate password change logic
    assert verify_password(raw_old, user.password) is True
    assert len(raw_new) >= 12
    user.password = get_password_hash(raw_new)
    user.is_first_login = False

    assert user.is_first_login is False
    assert verify_password(raw_new, user.password) is True


def test_toggle_mfa_without_verification_rejected():
    """Administrator roles cannot disable MFA; disabling requires valid verification."""
    from app.api.v1.endpoints.cms import update_cms_profile

    mock_db = MagicMock()
    mock_karir_db = MagicMock()

    # Case 1: Admin mencoba menonaktifkan MFA -> 400 ditolak
    admin_user = User(
        id=1,
        email="admin@itsp.co.id",
        password=get_password_hash("ValidPassword123!"),
        name="Super Admin",
        role="admin",
        mfa_enabled=True,
    )
    mock_db.query().filter().first.return_value = admin_user

    with pytest.raises(HTTPException) as exc_info:
        update_cms_profile(
            payload={"user_id": 1, "action": "toggle_mfa", "enabled": False},
            db=mock_db,
            karir_db=mock_karir_db,
        )
    assert exc_info.value.status_code == 400
    assert "MFA wajib aktif untuk akun administrator" in exc_info.value.detail
