import pytest
from unittest.mock import MagicMock
from fastapi import Response
from app.models.auth import RecruitmentAdmin, User
from app.core.security import verify_password
from app.api.v1.endpoints.cms import create_cms_item
from app.api.v1.endpoints.recruitment import reset_applicant_password


def test_create_cms_user_generates_temp_password():
    """POST /cms/users tanpa password wajib generate temporary password acak aman min 16 chars dan is_first_login=True."""
    db = MagicMock()
    karir_db = MagicMock()
    # Mock duplicate check: None (belum terdaftar)
    db.query(User).filter().first.return_value = None
    karir_db.query(RecruitmentAdmin).filter().first.return_value = None

    created_user = User(
        id=15,
        name="Pengguna Baru",
        email="baru@itsp.co.id",
        role="marketing",
        is_active=True,
    )
    from app.crud.base import CRUDBase
    orig_create = CRUDBase.create
    captured_obj = {}

    def mock_create(self, db_session, *, obj_in):
        captured_obj.update(obj_in)
        return created_user

    CRUDBase.create = mock_create

    admin_caller = RecruitmentAdmin(id=1, username="admin", role="admin")
    resp_obj = Response()

    try:
        res = create_cms_item(
            model="users",
            payload={
                "name": "Pengguna Baru",
                "email": "baru@itsp.co.id",
                "role": "marketing",
                # password dikosongkan sengaja
            },
            response=resp_obj,
            db=db,
            karir_db=karir_db,
            current_admin=admin_caller,
        )

        assert res.temp_password is not None
        assert len(res.temp_password) >= 16
        # Pastikan disimpan sebagai bcrypt hash (bukan plaintext)
        assert captured_obj["password"].startswith("$2b$") or captured_obj["password"].startswith("$2a$")
        assert verify_password(res.temp_password, captured_obj["password"]) is True
        assert captured_obj["is_first_login"] is True
        # Pastikan header anti-cache no-store terpasang
        assert "no-store" in resp_obj.headers.get("Cache-Control", "")
    finally:
        CRUDBase.create = orig_create


def test_recruitment_reset_password_generates_temp_password():
    """POST /recruitment/reset-password tanpa new_password wajib generate temporary password acak aman."""
    db = MagicMock()
    db_company = MagicMock()

    target_admin = RecruitmentAdmin(
        id=20,
        username="staff_it",
        name="Staff IT",
        email="it@itsp.co.id",
        role="hr",
    )
    db.query(RecruitmentAdmin).filter().first.return_value = target_admin
    db_company.query(User).filter().first.return_value = None

    admin_caller = RecruitmentAdmin(id=1, username="admin", role="admin")
    resp_obj = Response()

    res = reset_applicant_password(
        payload={
            "targetType": "admin",
            "targetId": 20,
            # new_password dikosongkan sengaja
        },
        response=resp_obj,
        db=db,
        db_company=db_company,
        _admin=admin_caller,
    )

    assert "temp_password" in res
    temp_pw = res["temp_password"]
    assert len(temp_pw) >= 16
    assert verify_password(temp_pw, target_admin.password) is True
    assert target_admin.is_first_login is True
    assert "no-store" in resp_obj.headers.get("Cache-Control", "")


def test_admin_create_rejects_password_less_than_12_chars():
    """B.3: AdminCreate mewajibkan password minimal 12 karakter bila diisi."""
    from pydantic import ValidationError
    from app.schemas.auth import AdminCreate

    # Password 11 karakter -> HARUS GAGAL
    with pytest.raises(ValidationError) as exc:
        AdminCreate(
            username="admin_test",
            name="Admin Test",
            email="test@itsp.co.id",
            password="shortpass11",  # 11 chars
        )
    assert any("at least 12 characters" in str(err) or "min_length" in str(err) for err in exc.value.errors())

    # Password 12 karakter -> HARUS LOLOS
    admin_valid = AdminCreate(
        username="admin_test",
        name="Admin Test",
        email="test@itsp.co.id",
        password="validpass123",  # 12 chars
    )
    assert admin_valid.password == "validpass123"

    # Password None/kosong -> HARUS LOLOS (karena CRUD akan generate random 16-char)
    admin_none = AdminCreate(
        username="admin_test",
        name="Admin Test",
        email="test@itsp.co.id",
        password=None,
    )
    assert admin_none.password is None

