import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.security import create_access_token
from app.api.deps import get_current_admin, get_current_applicant
from app.models.auth import RecruitmentAdmin, User
from app.models.recruitment import Applicant
from app.crud.crud_auth import crud_admin


def make_creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def make_request():
    req = MagicMock()
    req.headers.get.return_value = None
    return req


def test_token_without_type_claim_rejected():
    """Token lama atau token tanpa klaim type wajib ditolak untuk memaksa login ulang."""
    db = MagicMock()
    token_tanpa_type = create_access_token(
        subject=1,
        role="admin",
        extra_claims={"email": "admin@itsp.co.id"},
    )
    creds = make_creds(token_tanpa_type)
    req = make_request()

    with pytest.raises(HTTPException) as exc:
        get_current_admin(req, creds, db)
    assert exc.value.status_code == 401
    assert "klaim tipe" in exc.value.detail.lower()


def test_applicant_token_rejected_on_admin():
    """Token pelamar (sub=1) TIDAK BOLEH bisa mengakses get_current_admin meski RecruitmentAdmin ID=1 ada."""
    db = MagicMock()
    superadmin = RecruitmentAdmin(id=1, username="admin", email="admin@itsp.co.id", role="admin")
    db.query().filter().first.return_value = superadmin

    token_pelamar = create_access_token(
        subject=1,
        role="applicant",
        extra_claims={"type": "applicant", "name": "Pelamar Satu"},
    )
    creds = make_creds(token_pelamar)
    req = make_request()

    with patch.object(crud_admin, "get", return_value=superadmin):
        with pytest.raises(HTTPException) as exc:
            get_current_admin(req, creds, db)
        assert exc.value.status_code == 403
        assert "pelamar" in exc.value.detail.lower()


def test_cms_token_not_mapped_to_recruitment_admin():
    """Token CMS (type=cms, sub=2, role=marketing) TIDAK BOLEH dipetakan ke RecruitmentAdmin ID=2 (role=admin)."""
    db = MagicMock()
    rec_admin = RecruitmentAdmin(id=2, username="hr_boss", email="boss@itsp.co.id", role="admin")
    cms_user = User(id=2, username="market2", email="mkt@itsp.co.id", name="Staff Marketing", role="marketing", is_active=True)
    db.query(User).filter().first.return_value = cms_user

    token_cms = create_access_token(
        subject=2,
        role="marketing",
        extra_claims={"type": "cms", "email": "mkt@itsp.co.id"},
    )
    creds = make_creds(token_cms)
    req = make_request()

    with patch.object(crud_admin, "get", return_value=rec_admin):
        admin_entity = get_current_admin(req, creds, db)
        assert admin_entity.role == "marketing"
        assert admin_entity.id == 2
        assert admin_entity.email == "mkt@itsp.co.id"


def test_valid_ats_token_accepted():
    """Token ATS yang sah dan role-nya cocok wajib lolos."""
    db = MagicMock()
    ats_admin = RecruitmentAdmin(id=5, username="hr_staff", email="hr5@itsp.co.id", role="hr", is_active=True)

    token_ats = create_access_token(
        subject=5,
        role="hr",
        extra_claims={"type": "ats", "email": "hr5@itsp.co.id"},
    )
    creds = make_creds(token_ats)
    req = make_request()

    with patch.object(crud_admin, "get", return_value=ats_admin):
        result = get_current_admin(req, creds, db)
        assert result.id == 5
        assert result.role == "hr"


def test_token_role_mismatch_rejected():
    """Bila klaim role pada JWT sengaja dipalsukan (tampered), tolak HTTP 403."""
    db = MagicMock()
    ats_admin = RecruitmentAdmin(id=5, username="hr_staff", email="hr5@itsp.co.id", role="hr", is_active=True)

    token_tampered = create_access_token(
        subject=5,
        role="admin",
        extra_claims={"type": "ats", "email": "hr5@itsp.co.id"},
    )
    creds = make_creds(token_tampered)
    req = make_request()

    with patch.object(crud_admin, "get", return_value=ats_admin):
        with pytest.raises(HTTPException) as exc:
            get_current_admin(req, creds, db)
        assert exc.value.status_code == 403
        assert "tidak cocok" in exc.value.detail.lower()


def test_get_current_applicant_validates_type_and_role():
    """get_current_applicant hanya menerima token dengan type='applicant' dan role='applicant'."""
    db = MagicMock()
    app_entity = Applicant(id=10, email="appl@itsp.co.id", full_name="Pelamar")
    db.query(Applicant).filter().first.return_value = app_entity

    token_applicant = create_access_token(
        subject=10,
        role="applicant",
        extra_claims={"type": "applicant", "email": "appl@itsp.co.id"},
    )
    creds = make_creds(token_applicant)

    req = make_request()
    result = get_current_applicant(req, creds, db)
    assert result.id == 10

    # Token dengan type='ats' tapi mencoba akses route applicant ditolak
    token_ats = create_access_token(
        subject=10,
        role="applicant",
        extra_claims={"type": "ats", "email": "appl@itsp.co.id"},
    )
    creds_ats = make_creds(token_ats)
    with pytest.raises(HTTPException) as exc:
        get_current_applicant(req, creds_ats, db)
    assert exc.value.status_code == 403
    assert "pelamar" in exc.value.detail.lower()
