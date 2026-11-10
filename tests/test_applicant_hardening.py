import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from app.core.config import settings
from app.models.recruitment import Applicant, RecruitmentSetting
from app.api.v1.endpoints.applicants import get_applicant_status_details, candidate_accept_offer
from app.crud.crud_recruitment import crud_applicant, crud_setting


def make_request(headers=None):
    req = MagicMock()
    hdrs = headers or {}
    req.headers.get.side_effect = lambda k, default=None: hdrs.get(k) or hdrs.get(k.lower()) or default
    return req


def test_applicant_status_and_offer_rejects_missing_secret():
    """Endpoint status dan accept-offer wajib menolak pemanggilan tanpa X-Internal-Secret dengan 403."""
    db = MagicMock()
    req_no_auth = make_request({})

    with pytest.raises(HTTPException) as exc1:
        get_applicant_status_details("1", req_no_auth, db)
    assert exc1.value.status_code == 403

    with pytest.raises(HTTPException) as exc2:
        candidate_accept_offer({"applicant_id": 1}, req_no_auth, db)
    assert exc2.value.status_code == 403


def test_applicant_cannot_access_other_applicant_status():
    """Pelamar A (ID 1) TIDAK BOLEH membaca status pelamar B (ID 2) -> 403."""
    db = MagicMock()

    # Pelamar yang dicari adalah ID 2
    applicant_b = Applicant(
        id=2,
        full_name="Pelamar B",
        email="b@itsp.co.id",
        current_stage=3,
        stage_status="in_progress",
        rejection_reason=None,
        screening_notes="CATATAN RAHASIA HR: Skor tes rendah",
    )
    applicant_b.test_submissions = []
    applicant_b.interviews = []
    applicant_b.karyawan_data = None
    applicant_b.job_posting = None

    # Request datang dengan header sesi Pelamar A (X-Applicant-Id: 1)
    req = make_request({
        "X-Internal-Secret": settings.INTERNAL_API_SECRET,
        "X-Applicant-Id": "1",
    })

    with patch.object(crud_applicant, "get_with_details_by_identifier", return_value=applicant_b):
        with pytest.raises(HTTPException) as exc:
            get_applicant_status_details("2", req, db)
        assert exc.value.status_code == 403
        assert "tidak berhak" in exc.value.detail.lower()


def test_applicant_status_sanitizes_notes_and_settings():
    """Pelamar yang sah dapat membaca datanya, tetapi screeningNotes dan master settings dibuang."""
    db = MagicMock()

    appl = Applicant(
        id=1,
        full_name="Pelamar Sah",
        email="sah@itsp.co.id",
        current_stage=2,
        stage_status="in_progress",
        rejection_reason=None,
        screening_notes="INTERNAL HR ONLY: kandidat berpotensi",
    )
    appl.test_submissions = []
    appl.interviews = []
    appl.karyawan_data = None
    appl.job_posting = None

    # Mock settings di DB: ada setting MCU dan setting sensitif internal
    setting_public = RecruitmentSetting(key="mcu_partner_name", value="RS Hermina")
    setting_secret = RecruitmentSetting(key="smtp_secret_password", value="SecretP@ss")
    setting_internal = RecruitmentSetting(key="internal_ats_token", value="XYZ123")

    req = make_request({
        "X-Internal-Secret": settings.INTERNAL_API_SECRET,
        "X-Applicant-Id": "1",
    })

    with patch.object(crud_applicant, "get_with_details_by_identifier", return_value=appl), \
         patch.object(crud_setting, "get_multi", return_value=[setting_public, setting_secret, setting_internal]):
        resp = get_applicant_status_details("1", req, db)
        assert resp["success"] is True
        data_appl = resp["applicant"]
        assert data_appl["id"] == 1
        # 1. screeningNotes wajib TIDAK ADA di respons pelamar
        assert "screeningNotes" not in data_appl
        assert "screening_notes" not in data_appl

        # 2. Settings master sensitif wajib TIDAK ADA di respons
        returned_settings = resp["settings"]
        assert "mcu_partner_name" in returned_settings
        assert "smtp_secret_password" not in returned_settings
        assert "internal_ats_token" not in returned_settings


def test_applicant_cannot_accept_offer_of_another_applicant():
    """Pelamar A (sesi ID 1) mencoba menerima penawaran pelamar B (payload ID 2) -> 403."""
    db = MagicMock()
    req = make_request({
        "X-Internal-Secret": settings.INTERNAL_API_SECRET,
        "X-Applicant-Id": "1",
    })

    with pytest.raises(HTTPException) as exc:
        candidate_accept_offer({"applicant_id": 2}, req, db)
    assert exc.value.status_code == 403
    assert "tidak sesuai dengan sesi" in exc.value.detail.lower()
