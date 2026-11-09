from unittest.mock import MagicMock
from app.api.v1.endpoints.cms import serialize_cms_record, SENSITIVE_MODEL_COLUMNS


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
