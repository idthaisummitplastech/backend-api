import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from starlette.requests import Request
from app.core.config import settings
from app.models.auth import RecruitmentAdmin, User
from app.api.v1.endpoints.auth import (
    require_internal_secret,
    get_cms_user_mfa,
    save_cms_mfa_secret,
    activate_cms_mfa,
    verify_cms_mfa,
    get_ats_admin_mfa_setup,
    verify_ats_admin_mfa,
)


def make_request(headers=None):
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
        if isinstance(headers, dict)
        else [],
    }
    return Request(scope)


def test_require_internal_secret_rejects_missing_or_invalid():
    # Tanpa header secret -> 403
    req_empty = make_request({})
    with pytest.raises(HTTPException) as exc1:
        require_internal_secret(req_empty)
    assert exc1.value.status_code == 403

    # Secret salah -> 403
    req_wrong = make_request({"X-Internal-Secret": "wrong-secret-value"})
    with pytest.raises(HTTPException) as exc2:
        require_internal_secret(req_wrong)
    assert exc2.value.status_code == 403

    # Secret valid -> lulus tanpa exception
    req_valid = make_request({"X-Internal-Secret": settings.INTERNAL_API_SECRET})
    require_internal_secret(req_valid)


def test_get_cms_user_mfa_hardening():
    db = MagicMock()
    user_unverified = User(
        id=1,
        email="user1@itsp.co.id",
        name="User 1",
        role="marketing",
        mfa_enabled=False,
        mfa_secret="SECRETTEST123456",
        backup_codes='["CODE1", "CODE2"]',
    )
    user_active = User(
        id=2,
        email="user2@itsp.co.id",
        name="User 2",
        role="admin",
        mfa_enabled=True,
        mfa_secret="SECRETACTIVE9999",
        backup_codes='["CODE3", "CODE4", "CODE5"]',
    )

    db.query().filter().first.side_effect = [user_unverified, user_active]

    # 1. Panggilan tanpa secret ditolak 403
    req_no_auth = make_request({})
    with pytest.raises(HTTPException) as exc:
        get_cms_user_mfa(1, req_no_auth, db)
    assert exc.value.status_code == 403

    # 2. Panggilan dengan secret valid saat mfa_enabled=False: secret dikembalikan untuk setup
    req_auth = make_request({"X-Internal-Secret": settings.INTERNAL_API_SECRET})
    res_unverified = get_cms_user_mfa(1, req_auth, db)
    assert res_unverified["mfa_enabled"] is False
    assert res_unverified["mfa_secret"] == "SECRETTEST123456"
    assert "backup_codes" not in res_unverified
    assert res_unverified["backup_codes_count"] == 2

    # 3. Panggilan saat mfa_enabled=True: secret TIDAK BOLEH dibocorkan (None), backup_codes tidak ada
    res_active = get_cms_user_mfa(2, req_auth, db)
    assert res_active["mfa_enabled"] is True
    assert res_active["mfa_secret"] is None
    assert "backup_codes" not in res_active
    assert res_active["backup_codes_count"] == 3


def test_save_cms_mfa_secret_hardening():
    db = MagicMock()
    user_active = User(id=2, email="u2@itsp.co.id", mfa_enabled=True, mfa_secret="OLD_SEC")
    user_unverified = User(id=3, email="u3@itsp.co.id", mfa_enabled=False, mfa_secret=None)

    db.query().filter().first.side_effect = [user_active, user_unverified]

    req_auth = make_request({"X-Internal-Secret": settings.INTERNAL_API_SECRET})

    # Coba timpa secret akun yang sudah aktif -> ditolak 400
    with pytest.raises(HTTPException) as exc:
        save_cms_mfa_secret(2, {"secret": "MALICIOUS_SECRET"}, req_auth, db)
    assert exc.value.status_code == 400
    assert "MFA sudah aktif" in exc.value.detail

    # Akun belum aktif -> diizinkan menyimpan secret
    res = save_cms_mfa_secret(3, {"secret": "NEW_VALID_SECRET"}, req_auth, db)
    assert res["success"] is True
    assert user_unverified.mfa_secret == "NEW_VALID_SECRET"


def test_activate_cms_mfa_hardening():
    db = MagicMock()
    user_active = User(id=2, email="u2@itsp.co.id", mfa_enabled=True)
    db.query().filter().first.return_value = user_active

    # Tanpa secret -> 403
    with pytest.raises(HTTPException) as exc1:
        activate_cms_mfa({"user_id": 2}, make_request({}), db)
    assert exc1.value.status_code == 403

    # Dengan secret tapi akun sudah aktif -> 400
    req_auth = make_request({"X-Internal-Secret": settings.INTERNAL_API_SECRET})
    with pytest.raises(HTTPException) as exc2:
        activate_cms_mfa({"user_id": 2}, req_auth, db)
    assert exc2.value.status_code == 400


def test_ats_admin_mfa_hardening():
    db = MagicMock()
    db_comp = MagicMock()

    admin_active = RecruitmentAdmin(id=1, username="admin1", email="a1@itsp.co.id", role="admin", is_mfa_enabled=True, mfa_secret="SEC1")
    admin_unverified = RecruitmentAdmin(id=2, username="hr1", email="hr@itsp.co.id", role="hr", is_mfa_enabled=False, mfa_secret=None)

    db.query().filter().first.side_effect = [admin_active, admin_unverified]

    # 1. Setup tanpa secret -> 403
    with pytest.raises(HTTPException) as exc1:
        get_ats_admin_mfa_setup(1, make_request({}), db, db_comp)
    assert exc1.value.status_code == 403

    req_auth = make_request({"X-Internal-Secret": settings.INTERNAL_API_SECRET})

    # 2. Setup saat sudah aktif -> 400
    with pytest.raises(HTTPException) as exc2:
        get_ats_admin_mfa_setup(1, req_auth, db, db_comp)
    assert exc2.value.status_code == 400

    # 3. Setup saat belum aktif -> sukses
    res_setup = get_ats_admin_mfa_setup(2, req_auth, db, db_comp)
    assert res_setup["success"] is True
    assert "secret" in res_setup

    # 4. Nonaktifkan MFA untuk role admin -> 403
    db.query().filter().first.side_effect = None
    db.query().filter().first.return_value = admin_active
    with pytest.raises(HTTPException) as exc3:
        verify_ats_admin_mfa({"admin_id": 1, "enable": False}, req_auth, db, db_comp)
    assert exc3.value.status_code == 403
