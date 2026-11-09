import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from app.core.config import settings
from app.core.security import create_access_token
from app.models.auth import RecruitmentAdmin
from app.api.v1.endpoints.cms import (
    serialize_cms_record,
    SENSITIVE_MODEL_COLUMNS,
    check_cms_model_access,
    PUBLIC_GET_MODELS,
    SENSITIVE_GET_MODELS,
)


class ColumnStub:
    def __init__(self, name: str):
        self.name = name


class ModelStub:
    def __init__(self, **kwargs):
        self.__table__ = MagicMock()
        self.__table__.columns = [ColumnStub(k) for k in kwargs.keys()]
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_user_serializer_blacklists_sensitive_columns():
    """Verify password, mfa_secret, and backup_codes are stripped from users output."""
    stub_user = ModelStub(
        id=42,
        name="Staff Test",
        email="staff@itsp.co.id",
        role="admin",
        password="bcrypt_hash_secret_value",
        mfa_secret="JBSWY3DPEHPK3PXP",
        backup_codes='["123456", "789012"]',
        is_active=True,
        portal_access="both",
        department="IT",
    )

    result = serialize_cms_record("users", stub_user)

    # 1. Kunci rahasia TIDAK BOLEH ada di keluaran
    assert "password" not in result
    assert "mfa_secret" not in result
    assert "backup_codes" not in result

    # 2. Field non-rahasia tetap ada dan terpetakan dengan benar
    assert result["id"] == 42
    assert result["name"] == "Staff Test"
    assert result["email"] == "staff@itsp.co.id"
    assert result["role"] == "admin"
    assert result["is_active"] is True
    assert result["portal_access"] == "both"


def test_user_serializer_enrichment_from_rec_admin_map():
    """Verify username, department, and MFA status are properly enriched from recruitment admin map."""
    stub_user = ModelStub(
        id=10,
        name="HR Staff",
        email="hr@itsp.co.id",
        role="hr",
        password="another_hash",
        mfa_secret="MFASEC123",
        backup_codes="[]",
        is_active=True,
    )
    rec_admin = MagicMock()
    rec_admin.username = "hr-staff"
    rec_admin.department = "Human Capital"
    rec_admin.is_mfa_enabled = True
    rec_admin.portal_access = "karir"

    rec_admin_map = {"hr@itsp.co.id": rec_admin}

    result = serialize_cms_record("users", stub_user, rec_admin_map=rec_admin_map)

    assert "password" not in result
    assert "mfa_secret" not in result
    assert "backup_codes" not in result
    assert result["username"] == "hr-staff"
    assert result["department"] == "Human Capital"
    assert result["is_mfa_enabled"] is True
    assert result["portal_access"] == "karir"


def test_non_user_model_preserves_regular_columns():
    """Verify non-user models (e.g. blog-posts) serialize regular columns without stripping."""
    stub_post = ModelStub(
        id=1,
        title="Company Milestone 2026",
        slug="milestone-2026",
        content="Article content here",
        is_published=True,
    )

    result = serialize_cms_record("blog-posts", stub_post)

    assert result["id"] == 1
    assert result["title"] == "Company Milestone 2026"
    assert result["slug"] == "milestone-2026"
    assert result["is_published"] is True


def test_public_models_allow_anonymous_access():
    """Verify models in PUBLIC_GET_MODELS allow anonymous GET without credentials."""
    mock_request = MagicMock()
    mock_db = MagicMock()

    for model in ["hero-sections", "nav-menus", "services", "products", "settings"]:
        assert model in PUBLIC_GET_MODELS
        res = check_cms_model_access(model, request=mock_request, db=mock_db, credentials=None)
        assert res is None


def test_sensitive_contacts_requires_auth():
    """Verify 'contacts' model rejects unauthenticated request with 401."""
    mock_request = MagicMock()
    mock_request.headers.get.return_value = None
    mock_db = MagicMock()

    with pytest.raises(HTTPException) as exc:
        check_cms_model_access("contacts", request=mock_request, db=mock_db, credentials=None)
    assert exc.value.status_code == 401


def test_sensitive_contacts_allows_internal_secret():
    """Verify 'contacts' model allows request with valid X-Internal-Secret."""
    mock_request = MagicMock()
    mock_request.headers.get.side_effect = lambda h: settings.SECRET_KEY if h.lower() == "x-internal-secret" else None
    mock_db = MagicMock()
    fake_admin = RecruitmentAdmin(id=1, username="admin", role="admin", email="admin@itsp.co.id")
    mock_db.query().filter().first.return_value = fake_admin

    admin = check_cms_model_access("contacts", request=mock_request, db=mock_db, credentials=None)
    assert admin is not None
    assert admin.role == "admin"


def test_sensitive_admin_menus_allows_jwt():
    """Verify 'admin-menus' model allows request with valid JWT Bearer token."""
    token = create_access_token(subject=1, role="hr")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    mock_request = MagicMock()
    mock_request.headers.get.return_value = None

    fake_admin = RecruitmentAdmin(id=1, username="hruser", role="hr", email="hr@itsp.co.id")
    mock_db = MagicMock()
    from app.crud.crud_auth import crud_admin
    orig_get = crud_admin.get
    crud_admin.get = MagicMock(return_value=fake_admin)

    try:
        admin = check_cms_model_access("admin-menus", request=mock_request, db=mock_db, credentials=credentials)
        assert admin is not None
        assert admin.id == 1
    finally:
        crud_admin.get = orig_get


def test_sensitive_users_rejects_non_admin_role():
    """Verify 'users' model rejects non-admin JWT (e.g. hr/marketing) with 403."""
    token = create_access_token(subject=2, role="marketing")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    mock_request = MagicMock()
    mock_request.headers.get.return_value = None

    fake_marketing = RecruitmentAdmin(id=2, username="mkt", role="marketing", email="mkt@itsp.co.id")
    mock_db = MagicMock()
    from app.crud.crud_auth import crud_admin
    orig_get = crud_admin.get
    crud_admin.get = MagicMock(return_value=fake_marketing)

    try:
        with pytest.raises(HTTPException) as exc:
            check_cms_model_access("users", request=mock_request, db=mock_db, credentials=credentials)
        assert exc.value.status_code == 403
        assert "hanya dapat diakses oleh peran admin" in exc.value.detail
    finally:
        crud_admin.get = orig_get


def test_sensitive_users_allows_admin_role():
    """Verify 'users' model permits admin JWT."""
    token = create_access_token(subject=1, role="admin")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    mock_request = MagicMock()
    mock_request.headers.get.return_value = None

    fake_admin = RecruitmentAdmin(id=1, username="admin", role="admin", email="admin@itsp.co.id")
    mock_db = MagicMock()
    from app.crud.crud_auth import crud_admin
    orig_get = crud_admin.get
    crud_admin.get = MagicMock(return_value=fake_admin)

    try:
        admin = check_cms_model_access("users", request=mock_request, db=mock_db, credentials=credentials)
        assert admin is not None
        assert admin.role == "admin"
    finally:
        crud_admin.get = orig_get


def test_default_deny_for_new_or_unregistered_model():
    """Verify newly introduced models outside PUBLIC_GET_MODELS default to requiring authentication."""
    mock_request = MagicMock()
    mock_request.headers.get.return_value = None
    mock_db = MagicMock()

    # Model not in PUBLIC_GET_MODELS must require auth (default-deny)
    with pytest.raises(HTTPException) as exc:
        check_cms_model_access("internal_audit_logs", request=mock_request, db=mock_db, credentials=None)
    assert exc.value.status_code == 401


