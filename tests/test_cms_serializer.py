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
    check_cms_write_access,
    PUBLIC_GET_MODELS,
    CMS_CONTENT_MODELS,
    SENSITIVE_GET_MODELS,
    SENSITIVE_MODELS,
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


def test_sensitive_contacts_allows_internal_secret_with_admin_role():
    """Verify 'contacts' model allows request with valid X-Internal-Secret and X-Admin-Role."""
    mock_request = MagicMock()
    headers_map = {
        "x-internal-secret": settings.SECRET_KEY,
        "x-admin-role": "admin",
    }
    mock_request.headers.get.side_effect = lambda h: headers_map.get(h.lower())
    mock_db = MagicMock()

    admin = check_cms_model_access("contacts", request=mock_request, db=mock_db, credentials=None)
    assert admin is not None
    assert admin.role == "admin"


def test_internal_secret_without_role_rejected_with_403():
    """Verify X-Internal-Secret without X-Admin-Role and without X-Admin-Id is rejected with 403."""
    mock_request = MagicMock()
    mock_request.headers.get.side_effect = lambda h: settings.SECRET_KEY if h.lower() == "x-internal-secret" else None
    mock_db = MagicMock()

    with pytest.raises(HTTPException) as exc:
        check_cms_model_access("contacts", request=mock_request, db=mock_db, credentials=None)
    assert exc.value.status_code == 403
    assert "memerlukan header X-Admin-Role atau X-Admin-Id" in exc.value.detail


def test_internal_secret_with_mismatched_admin_id_and_role_rejected():
    """Verify X-Internal-Secret with mismatched X-Admin-Id and X-Admin-Role is rejected with 403."""
    from app.api.deps import get_current_admin
    from app.crud.crud_auth import crud_admin

    mock_request = MagicMock()
    headers_map = {
        "x-internal-secret": settings.SECRET_KEY,
        "x-admin-id": "5",
        "x-admin-role": "admin",
    }
    mock_request.headers.get.side_effect = lambda h: headers_map.get(h.lower())
    mock_db = MagicMock()

    # Case 1: ID not found in database -> 403
    orig_get = crud_admin.get
    try:
        crud_admin.get = MagicMock(return_value=None)
        with pytest.raises(HTTPException) as exc1:
            get_current_admin(request=mock_request, credentials=None, db=mock_db)
        assert exc1.value.status_code == 403
        assert "Akun admin tidak ditemukan" in exc1.value.detail

        # Case 2: ID found as 'hr', but X-Admin-Role header claims 'admin' -> 403
        fake_hr = RecruitmentAdmin(id=5, username="hrstaff", role="hr", email="hr@itsp.co.id")
        crud_admin.get = MagicMock(return_value=fake_hr)
        with pytest.raises(HTTPException) as exc2:
            get_current_admin(request=mock_request, credentials=None, db=mock_db)
        assert exc2.value.status_code == 403
        assert "Header role tidak sesuai" in exc2.value.detail
    finally:
        crud_admin.get = orig_get


def test_marketing_role_write_permissions():
    """Verify marketing role can write content models, but is rejected for sensitive models."""
    marketing_admin = RecruitmentAdmin(id=10, username="mkt", role="marketing", email="mkt@itsp.co.id")
    super_admin = RecruitmentAdmin(id=1, username="admin", role="admin", email="admin@itsp.co.id")

    # 1. Content models: allowed for marketing and admin
    for content_model in ["hero-sections", "services", "announcements", "settings", "pages"]:
        check_cms_write_access(content_model, marketing_admin)  # should not raise
        check_cms_write_access(content_model, super_admin)       # should not raise

    # 2. Sensitive models: rejected with 403 for marketing, allowed for admin
    for sensitive_model in ["users", "contacts", "admin-menus"]:
        with pytest.raises(HTTPException) as exc:
            check_cms_write_access(sensitive_model, marketing_admin)
        assert exc.value.status_code == 403
        assert "hanya dapat dikelola oleh Administrator" in exc.value.detail

        # Admin must be allowed
        check_cms_write_access(sensitive_model, super_admin)


def test_user_password_length_and_hash_rejection():
    """Verify password < 12 characters or raw bcrypt hashes are rejected on user CRUD."""
    from app.api.v1.endpoints.cms import create_cms_item, update_cms_item

    mock_db = MagicMock()
    mock_karir_db = MagicMock()
    admin_user = RecruitmentAdmin(id=1, username="admin", role="admin", email="admin@itsp.co.id")

    # 1. Test short password (< 12 chars) on create
    with pytest.raises(HTTPException) as exc_short:
        create_cms_item(
            model="users",
            payload={"name": "Test", "email": "test@itsp.co.id", "password": "short_pw"},
            response=MagicMock(),
            db=mock_db,
            karir_db=mock_karir_db,
            current_admin=admin_user,
        )
    assert exc_short.value.status_code == 400
    assert "minimal terdiri dari 12 karakter" in exc_short.value.detail

    # 2. Test raw bcrypt hash on create
    with pytest.raises(HTTPException) as exc_hash:
        create_cms_item(
            model="users",
            payload={"name": "Test", "email": "test@itsp.co.id", "password": "$2b$12$e8r6...rawhash"},
            response=MagicMock(),
            db=mock_db,
            karir_db=mock_karir_db,
            current_admin=admin_user,
        )
    assert exc_hash.value.status_code == 400
    assert "hash password tidak diperkenankan" in exc_hash.value.detail


def test_content_models_parity_with_nextjs_whitelist():
    """Verify backend CMS_CONTENT_MODELS matches the 16 content models defined in Next.js cms-guard."""
    expected_content_models = {
        "settings",
        "nav-menus",
        "hero-sections",
        "announcements",
        "partners",
        "features",
        "services",
        "products",
        "blog-posts",
        "testimonials",
        "faqs",
        "statistics",
        "certifications",
        "facilities",
        "sustainability-reports",
        "pages",
    }
    assert CMS_CONTENT_MODELS == expected_content_models
    assert len(CMS_CONTENT_MODELS) == 16
    assert SENSITIVE_MODELS == {"users", "contacts", "admin-menus"}
    assert len(SENSITIVE_MODELS) == 3


def test_sensitive_admin_menus_allows_jwt():
    """Verify 'admin-menus' model allows request with valid JWT Bearer token."""
    token = create_access_token(subject=1, role="hr", extra_claims={"type": "ats"})
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
    token = create_access_token(subject=2, role="marketing", extra_claims={"type": "ats"})
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
    token = create_access_token(subject=1, role="admin", extra_claims={"type": "ats"})
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


