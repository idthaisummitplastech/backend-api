import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from app.core.config import settings
from app.models.auth import User
from app.models.cms import ContactSubmission
from app.api.v1.endpoints.cms import get_cms_profile, update_cms_profile, get_dashboard_stats


def make_request(headers=None):
    req = MagicMock()
    hdrs = headers or {}
    req.headers.get.side_effect = lambda k, default=None: hdrs.get(k) or hdrs.get(k.lower()) or default
    return req


def test_cms_profile_rejects_missing_internal_secret():
    """GET dan POST /cms/profile wajib menolak request tanpa X-Internal-Secret (403)."""
    db = MagicMock()
    karir_db = MagicMock()
    req_no_auth = make_request({})

    with pytest.raises(HTTPException) as exc1:
        get_cms_profile(req_no_auth, user_id=1, db=db)
    assert exc1.value.status_code == 403

    with pytest.raises(HTTPException) as exc2:
        update_cms_profile({"user_id": 1}, req_no_auth, db=db, karir_db=karir_db)
    assert exc2.value.status_code == 403


def test_cms_profile_allows_internal_secret():
    """GET /cms/profile dengan X-Internal-Secret valid berhasil membaca profil."""
    db = MagicMock()
    fake_user = User(
        id=1,
        name="Admin Test",
        email="adm@itsp.co.id",
        role="admin",
        mfa_enabled=True,
        backup_codes='["123456", "654321"]',
    )
    db.query(User).filter().first.return_value = fake_user

    req = make_request({"X-Internal-Secret": settings.SECRET_KEY})
    resp = get_cms_profile(req, user_id=1, db=db)
    data = resp.data
    assert data["id"] == 1
    assert data["name"] == "Admin Test"
    assert data["backup_codes_count"] == 2
    assert "password" not in data
    assert "mfa_secret" not in data


def test_dashboard_stats_requires_secret_and_role():
    """GET /cms/dashboard-stats wajib require_internal_secret dan role admin/marketing."""
    db = MagicMock()

    # 1. Tanpa secret -> 403
    with pytest.raises(HTTPException) as exc1:
        get_dashboard_stats(make_request({}), db=db)
    assert exc1.value.status_code == 403

    # 2. Dengan secret tapi role tidak sah (misal guest) -> 403
    req_invalid_role = make_request({
        "X-Internal-Secret": settings.SECRET_KEY,
        "X-Admin-Role": "guest",
    })
    with pytest.raises(HTTPException) as exc2:
        get_dashboard_stats(req_invalid_role, db=db)
    assert exc2.value.status_code == 403


def test_dashboard_stats_role_based_recent_contacts():
    """Role admin mendapatkan rincian kontak terbaru; role marketing hanya mendapatkan jumlah (recent_contacts kosong)."""
    db = MagicMock()
    db.query().count.return_value = 10
    db.query().filter().count.return_value = 2

    c1 = ContactSubmission(id=1, name="Budi", email="b@test.com", subject="Tanya Produk", is_read=False)
    db.query(ContactSubmission).order_by().limit().all.return_value = [c1]

    # 1. Admin role -> recent_contacts terisi
    req_admin = make_request({
        "X-Internal-Secret": settings.SECRET_KEY,
        "X-Admin-Role": "admin",
    })
    resp_admin = get_dashboard_stats(req_admin, db=db)
    assert len(resp_admin.data["recent_contacts"]) == 1
    assert resp_admin.data["recent_contacts"][0]["name"] == "Budi"

    # 2. Marketing role -> recent_contacts kosong
    req_marketing = make_request({
        "X-Internal-Secret": settings.SECRET_KEY,
        "X-Admin-Role": "marketing",
    })
    resp_mkt = get_dashboard_stats(req_marketing, db=db)
    assert resp_mkt.data["contact_count"] == 10
    assert resp_mkt.data["unread_contacts"] == 2
    assert resp_mkt.data["recent_contacts"] == []
