import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.security import create_access_token
from app.models.auth import RecruitmentAdmin, User
from app.models.recruitment import Applicant
from app.api.deps import get_current_admin, get_current_applicant


def make_creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def make_request():
    req = MagicMock()
    req.url.path = "/api/v1/recruitment/admins"
    req.headers.get.return_value = None
    return req


def test_token_without_type_rejected():
    """Token tanpa klaim type wajib ditolak HTTP 401 (disengaja agar login ulang)."""
    db = MagicMock()
    token = create_access_token(subject=1, role="admin")  # tanpa extra_claims type
    creds = make_creds(token)
    req = make_request()

    with pytest.raises(HTTPException) as exc:
        get_current_admin(req, creds, db)
    assert exc.value.status_code == 401
    assert "klaim tipe" in exc.value.detail.lower() or "format lama" in exc.value.detail.lower()


def test_applicant_token_rejected_on_admin():
    """Token pelamar (sub=1) TIDAK BOLEH bisa mengakses get_current_admin meski RecruitmentAdmin ID=1 ada."""
    db = MagicMock()
    # Stub RecruitmentAdmin ID=1 (Superadmin)
    superadmin = RecruitmentAdmin(id=1, username="admin", email="admin@itsp.co.id", role="admin")
    db.query().filter().first.return_value = superadmin
    from app.crud.crud_auth import crud_admin
    crud_admin.get = MagicMock(return_value=superadmin)

    # Token pelamar dengan ID 1
    token_pelamar = create_access_token(
        subject=1,
        role="applicant",
        extra_claims={"type": "applicant", "name": "Pelamar Satu"},
    )
    creds = make_creds(token_pelamar)
    req = make_request()

    with pytest.raises(HTTPException) as exc:
        get_current_admin(req, creds, db)
    assert exc.value.status_code == 403
    assert "pelamar" in exc.value.detail.lower()


def test_cms_token_not_mapped_to_recruitment_admin():
    """Token CMS (type=cms, sub=2, role=marketing) TIDAK BOLEH dipetakan ke RecruitmentAdmin ID=2 (role=admin)."""
    db = MagicMock()
    from app.crud.crud_auth import crud_admin
    # Di RecruitmentAdmin ada ID 2 role admin
    rec_admin = RecruitmentAdmin(id=2, username="hr_boss", email="boss@itsp.co.id", role="admin")
    crud_admin.get = MagicMock(return_value=rec_admin)

    # Di User CMS ada ID 2 role marketing
    cms_user = User(id=2, username="market2", email="mkt@itsp.co.id", name="Staff Marketing", role="marketing", is_active=True)
    db.query(User).filter().first.return_value = cms_user

    # Token dari CMS user
    token_cms = create_access_token(
        subject=2,
        role="marketing",
        extra_claims={"type": "cms", "email": "mkt@itsp.co.id"},
    )
    creds = make_creds(token_cms)
    req = make_request()

    admin_entity = get_current_admin(req, creds, db)
    # Wajib membaca dari User CMS, bukan RecruitmentAdmin
    assert admin_entity.role == "marketing"
    assert admin_entity.id == 2
    assert admin_entity.email == "mkt@itsp.co.id"


def test_valid_ats_token_accepted():
    """Token ATS yang sah dan role-nya cocok wajib lolos."""
    db = MagicMock()
    from app.crud.crud_auth import crud_admin
    ats_admin = RecruitmentAdmin(id=5, username="hr_staff", email="hr5@itsp.co.id", role="hr", is_active=True)
    crud_admin.get = MagicMock(return_value=ats_admin)

    token_ats = create_access_token(
        subject=5,
        role="hr",
        extra_claims={"type": "ats", "email": "hr5@itsp.co.id"},
    )
    creds = make_creds(token_ats)
    req = make_request()

    result = get_current_admin(req, creds, db)
    assert result.id == 5
    assert result.role == "hr"


def test_token_role_mismatch_rejected():
    """Bila klaim role pada JWT sengaja dipalsukan (tampered), tolak HTTP 403."""
    db = MagicMock()
    from app.crud.crud_auth import crud_admin
    # Akun asli di DB adalah hr
    ats_admin = RecruitmentAdmin(id=5, username="hr_staff", email="hr5@itsp.co.id", role="hr", is_active=True)
    crud_admin.get = MagicMock(return_value=ats_admin)

    # Penyerang memalsukan klaim role=admin
    token_tampered = create_access_token(
        subject=5,
        role="admin",
        extra_claims={"type": "ats", "email": "hr5@itsp.co.id"},
    )
    creds = make_creds(token_tampered)
    req = make_request()

    with pytest.raises(HTTPException) as exc:
        get_current_admin(req, creds, db)
    assert exc.value.status_code == 403
    assert "tidak cocok" in exc.value.detail.lower()


def test_applicant_endpoint_rejects_non_applicant_token():
    """get_current_applicant wajib menolak token admin atau token tanpa klaim applicant."""
    db = MagicMock()
    token_admin = create_access_token(
        subject=1,
        role="admin",
        extra_claims={"type": "ats"},
    )
    creds = make_creds(token_admin)
    req = make_request()

    with pytest.raises(HTTPException) as exc:
        get_current_applicant(req, creds, db)
    assert exc.value.status_code == 403


def test_valid_applicant_token_accepted():
    """Token pelamar yang sah (type=applicant, role=applicant) diterima di get_current_applicant."""
    db = MagicMock()
    from app.crud.crud_recruitment import crud_applicant
    fake_appl = Applicant(id=10, full_name="Budi Pelamar", email="budi@gmail.com")
    crud_applicant.get = MagicMock(return_value=fake_appl)

    token_pelamar = create_access_token(
        subject=10,
        role="applicant",
        extra_claims={"type": "applicant", "email": "budi@gmail.com"},
    )
    creds = make_creds(token_pelamar)
    req = make_request()

    res = get_current_applicant(req, creds, db)
    assert res.id == 10
    assert res.full_name == "Budi Pelamar"
