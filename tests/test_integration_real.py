import os
import json
from datetime import datetime, timezone
import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.session as db_session
from app.db.base import Base
from app.core.config import settings
from app.core.security import get_password_hash, create_access_token
from app.models.auth import RecruitmentAdmin, User
from app.models.recruitment import Applicant, JobPosting
from app.models.cms import Announcement, ContactSubmission

# Setup in-memory SQLite database
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=test_engine)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Patch session module engine/sessionmaker
db_session.engine = test_engine
db_session.engine_company = test_engine
db_session.SessionLocal = TestingSessionLocal
db_session.SessionCompanyLocal = TestingSessionLocal

# Prevent lifespan init_db from attempting PostgreSQL connections
import app.db.init_db as init_db_module
init_db_module.engine = test_engine
init_db_module.engine_company = test_engine
init_db_module.init_db = lambda db: None

from main import app
from app.db.session import get_db, get_db_company

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_db_company] = override_get_db

# Real TestClient (no dependency override on auth!)
client = TestClient(app)

SECRET = settings.SECRET_KEY


@pytest.fixture(scope="module", autouse=True)
def seed_test_database():
    """Seed real entities in SQLite test database."""
    db = TestingSessionLocal()
    try:
        # 1. CMS Users
        cms_admin = User(
            id=1,
            name="CMS Admin",
            email="admin@itsp.co.id",
            password=get_password_hash("AdminPass123!"),
            role="admin",
            is_active=True,
            mfa_enabled=False,
        )
        cms_marketing = User(
            id=2,
            name="CMS Marketing",
            email="mkt@itsp.co.id",
            password=get_password_hash("MktPass123!"),
            role="marketing",
            is_active=True,
            mfa_enabled=False,
        )
        cms_mfa_user = User(
            id=3,
            name="CMS User MFA",
            email="mfa_user@itsp.co.id",
            password=get_password_hash("MfaPass123!"),
            role="admin",
            is_active=True,
            mfa_enabled=True,
            mfa_secret="JBSWY3DPEHPK3PXP",
            backup_codes=json.dumps(["BC123", "BC456"]),
        )
        db.add_all([cms_admin, cms_marketing, cms_mfa_user])

        # 2. Recruitment Admins
        ats_admin = RecruitmentAdmin(
            id=1,
            username="rec_admin",
            name="Recruitment Admin",
            email="rec_admin@itsp.co.id",
            password=get_password_hash("RecAdminPass123!"),
            role="admin",
            is_active=True,
            is_mfa_enabled=False,
        )
        ats_interviewer = RecruitmentAdmin(
            id=2,
            username="rec_interviewer",
            name="Interviewer User",
            email="interviewer@itsp.co.id",
            password=get_password_hash("IntPass123!"),
            role="interviewer",
            is_active=True,
            is_mfa_enabled=False,
        )
        ats_mfa_admin = RecruitmentAdmin(
            id=3,
            username="rec_mfa_admin",
            name="Rec MFA Admin",
            email="mfa_admin@itsp.co.id",
            password=get_password_hash("RecMfaPass123!"),
            role="admin",
            is_active=True,
            is_mfa_enabled=True,
            mfa_secret="JBSWY3DPEHPK3PXP",
        )
        db.add_all([ats_admin, ats_interviewer, ats_mfa_admin])

        # 3. Job Posting & Applicants
        job = JobPosting(
            id=1,
            title="Software Engineer",
            department="IT",
            requirements="Python",
            description="Backend dev",
            is_open=True,
        )
        db.add(job)
        db.commit()

        applicant_1 = Applicant(
            id=10,
            job_posting_id=1,
            full_name="John Doe",
            email="applicant10@test.com",
            password=get_password_hash("AppPass123!"),
            phone="08123456789",
            birth_date=datetime.now(timezone.utc),
            age=25,
            last_education="S1",
            school_name="Universitas Indonesia",
            major="Teknik Informatika",
            experience="2 Tahun",
            english_skill="Intermediate",
            other_languages="None",
            cv_file="cv.pdf",
            current_stage=7,
            stage_status="in_progress",
        )
        applicant_2 = Applicant(
            id=11,
            job_posting_id=1,
            full_name="Jane Smith",
            email="applicant11@test.com",
            password=get_password_hash("AppPass123!"),
            phone="08123456788",
            birth_date=datetime.now(timezone.utc),
            age=24,
            last_education="S1",
            school_name="ITB",
            major="Sistem Informasi",
            experience="1 Tahun",
            english_skill="Advanced",
            other_languages="Japanese",
            cv_file="cv2.pdf",
            current_stage=7,
            stage_status="in_progress",
        )
        db.add_all([applicant_1, applicant_2])

        # 4. CMS Announcement & Contact Submission
        announcement = Announcement(
            id=1,
            message="Kantor libur besok",
            is_active=True,
        )
        contact = ContactSubmission(
            id=1,
            name="Budi",
            email="budi@example.com",
            subject="Tanya Produk",
            message="Halo mau tanya produk",
        )
        db.add_all([announcement, contact])

        db.commit()
    finally:
        db.close()


# ============================================================================
# (a) MFA ENDPOINTS
# ============================================================================

def test_cms_mfa_get_secret():
    # Tanpa secret -> 403
    r1 = client.get("/api/v1/auth/cms-mfa/1")
    assert r1.status_code == 403

    # Secret salah -> 403
    r2 = client.get("/api/v1/auth/cms-mfa/1", headers={"X-Internal-Secret": "wrong_secret"})
    assert r2.status_code == 403

    # Secret benar, user mfa_enabled=False -> 200 (secret dikembalikan untuk setup)
    r3 = client.get("/api/v1/auth/cms-mfa/1", headers={"X-Internal-Secret": SECRET})
    assert r3.status_code == 200
    data3 = r3.json()
    assert data3["mfa_enabled"] is False
    assert "mfa_secret" in data3
    assert data3["backup_codes_count"] == 0
    assert "backup_codes" not in data3  # plaintext backup codes TIDAK dikembalikan

    # Secret benar, user mfa_enabled=True -> 200 (secret TIDAK dikembalikan setelah aktif)
    r4 = client.get("/api/v1/auth/cms-mfa/3", headers={"X-Internal-Secret": SECRET})
    assert r4.status_code == 200
    data4 = r4.json()
    assert data4["mfa_enabled"] is True
    assert data4.get("mfa_secret") is None
    assert data4["backup_codes_count"] == 2
    assert "backup_codes" not in data4


def test_cms_mfa_save_secret():
    # Tanpa secret -> 403
    r1 = client.put("/api/v1/auth/cms-mfa/1/save-secret", json={"mfa_secret": "TESTSECRET123"})
    assert r1.status_code == 403

    # Secret benar pada user yang belum aktif -> 200
    r2 = client.put(
        "/api/v1/auth/cms-mfa/1/save-secret",
        headers={"X-Internal-Secret": SECRET},
        json={"mfa_secret": "TESTSECRET123"},
    )
    assert r2.status_code == 200

    # Secret benar pada user yang SUDAH aktif MFA -> 400 (tampering ditolak)
    r3 = client.put(
        "/api/v1/auth/cms-mfa/3/save-secret",
        headers={"X-Internal-Secret": SECRET},
        json={"mfa_secret": "ATTACKERSECRET123"},
    )
    assert r3.status_code == 400


def test_cms_mfa_activate():
    # Tanpa secret -> 403
    r1 = client.post("/api/v1/auth/cms-mfa/activate", json={"user_id": 1, "secret": "TESTSECRET123"})
    assert r1.status_code == 403

    # Tanpa user_id -> 400
    r2 = client.post(
        "/api/v1/auth/cms-mfa/activate",
        headers={"X-Internal-Secret": SECRET},
        json={},
    )
    assert r2.status_code == 400

    # Secret benar -> 200 (mengaktifkan MFA)
    r3 = client.post(
        "/api/v1/auth/cms-mfa/activate",
        headers={"X-Internal-Secret": SECRET},
        json={"user_id": 1, "secret": "TESTSECRET123", "backup_codes": ["B1", "B2"]},
    )
    assert r3.status_code == 200
    assert r3.json()["success"] is True

    # User sudah aktif -> 400 (tidak bisa di-activate ulang)
    r4 = client.post(
        "/api/v1/auth/cms-mfa/activate",
        headers={"X-Internal-Secret": SECRET},
        json={"user_id": 1, "secret": "TESTSECRET123"},
    )
    assert r4.status_code == 400


def test_ats_mfa_endpoints():
    # Setup: Tanpa secret -> 403
    r1 = client.get("/api/v1/auth/ats-mfa/1/setup")
    assert r1.status_code == 403

    # Setup: Secret benar pada admin belum aktif -> 200
    r2 = client.get("/api/v1/auth/ats-mfa/1/setup", headers={"X-Internal-Secret": SECRET})
    assert r2.status_code == 200
    secret_key = r2.json()["secret"]

    # Setup: Secret benar pada admin yang sudah aktif -> 400
    r3 = client.get("/api/v1/auth/ats-mfa/3/setup", headers={"X-Internal-Secret": SECRET})
    assert r3.status_code == 400

    # Verify: Tanpa secret -> 403
    r4 = client.post("/api/v1/auth/ats-mfa/verify", json={"admin_id": 1, "enable": True, "code": "123456"})
    assert r4.status_code == 403

    # Verify: Secret benar + kode salah -> 400
    r5 = client.post(
        "/api/v1/auth/ats-mfa/verify",
        headers={"X-Internal-Secret": SECRET},
        json={"admin_id": 1, "enable": True, "code": "000000"},
    )
    assert r5.status_code == 400

    # Verify: Secret benar + kode valid -> 200
    totp = pyotp.TOTP(secret_key)
    r6 = client.post(
        "/api/v1/auth/ats-mfa/verify",
        headers={"X-Internal-Secret": SECRET},
        json={"admin_id": 1, "enable": True, "code": totp.now()},
    )
    assert r6.status_code == 200


# ============================================================================
# (b) APPLICANTS/STATUS & ACCEPT-OFFER
# ============================================================================

def test_applicant_status_and_accept_offer():
    # GET status: Tanpa secret -> 403
    r1 = client.get("/api/v1/applicants/status/10")
    assert r1.status_code == 403

    # GET status: Secret ada tapi X-Applicant-Id tidak cocok (tampering) -> 403
    r2 = client.get(
        "/api/v1/applicants/status/10",
        headers={"X-Internal-Secret": SECRET, "X-Applicant-Id": "11"},
    )
    assert r2.status_code == 403

    # GET status: Secret benar + X-Applicant-Id cocok -> 200
    r3 = client.get(
        "/api/v1/applicants/status/10",
        headers={"X-Internal-Secret": SECRET, "X-Applicant-Id": "10"},
    )
    assert r3.status_code == 200
    assert r3.json()["applicant"]["id"] == 10

    # POST accept-offer: Tanpa secret -> 403
    r4 = client.post("/api/v1/applicants/accept-offer", json={"applicant_id": 10})
    assert r4.status_code == 403

    # POST accept-offer: Secret ada tapi X-Applicant-Id tidak cocok -> 403
    r5 = client.post(
        "/api/v1/applicants/accept-offer",
        headers={"X-Internal-Secret": SECRET, "X-Applicant-Id": "11"},
        json={"applicant_id": 10},
    )
    assert r5.status_code == 403

    # POST accept-offer: Secret benar + X-Applicant-Id cocok -> 200
    r6 = client.post(
        "/api/v1/applicants/accept-offer",
        headers={"X-Internal-Secret": SECRET, "X-Applicant-Id": "10"},
        json={"applicant_id": 10},
    )
    assert r6.status_code == 200


# ============================================================================
# (c) /CMS/PROFILE & DASHBOARD-STATS
# ============================================================================

def test_cms_profile_and_dashboard_stats():
    # GET profile: Tanpa secret -> 403
    r1 = client.get("/api/v1/cms/profile?user_id=1")
    assert r1.status_code == 403

    # GET profile: Secret benar -> 200
    r2 = client.get("/api/v1/cms/profile?user_id=1", headers={"X-Internal-Secret": SECRET})
    assert r2.status_code == 200
    assert r2.json()["data"]["email"] == "admin@itsp.co.id"

    # POST profile: Tanpa secret -> 403
    r3 = client.post(
        "/api/v1/cms/profile",
        json={"user_id": 1, "action": "update_profile", "name": "Admin Baru"},
    )
    assert r3.status_code == 403

    # POST profile: Secret benar -> 200
    r4 = client.post(
        "/api/v1/cms/profile",
        headers={"X-Internal-Secret": SECRET},
        json={"user_id": 1, "action": "update_profile", "name": "Admin Baru"},
    )
    assert r4.status_code == 200

    # GET dashboard-stats: Tanpa secret -> 403
    r5 = client.get("/api/v1/cms/dashboard-stats")
    assert r5.status_code == 403

    # GET dashboard-stats: Secret tanpa X-Admin-Role -> 403
    r6 = client.get("/api/v1/cms/dashboard-stats", headers={"X-Internal-Secret": SECRET})
    assert r6.status_code == 403

    # GET dashboard-stats: Secret + role marketing -> 200 (recent contacts excluded)
    r7 = client.get(
        "/api/v1/cms/dashboard-stats",
        headers={"X-Internal-Secret": SECRET, "X-Admin-Role": "marketing"},
    )
    assert r7.status_code == 200
    data7 = r7.json()["data"]
    assert data7["recent_contacts"] == []

    # GET dashboard-stats: Secret + role admin -> 200 (recent contacts included)
    r8 = client.get(
        "/api/v1/cms/dashboard-stats",
        headers={"X-Internal-Secret": SECRET, "X-Admin-Role": "admin"},
    )
    assert r8.status_code == 200
    data8 = r8.json()["data"]
    assert len(data8["recent_contacts"]) > 0


# ============================================================================
# (d) ROLECHECKER ENDPOINT DIGUNAKAN WEB-KARIR (GET /recruitment/admins)
# ============================================================================

def test_recruitment_admins_rolechecker():
    # 1. Tanpa token dan tanpa internal secret -> 401
    r1 = client.get("/api/v1/recruitment/admins")
    assert r1.status_code == 401

    # 2. Secret tanpa role -> 403
    r2 = client.get("/api/v1/recruitment/admins", headers={"X-Internal-Secret": SECRET})
    assert r2.status_code == 403

    # 3. Secret + role salah (interviewer bukan admin) -> 403
    r3 = client.get(
        "/api/v1/recruitment/admins",
        headers={"X-Internal-Secret": SECRET, "X-Admin-Role": "interviewer"},
    )
    assert r3.status_code == 403

    # 4. Secret + role benar (admin) -> 200
    r4 = client.get(
        "/api/v1/recruitment/admins",
        headers={"X-Internal-Secret": SECRET, "X-Admin-Role": "admin"},
    )
    assert r4.status_code == 200
    assert isinstance(r4.json()["data"], list)

    # 5. Bearer token asli dengan role salah (interviewer) -> 403
    token_interviewer = create_access_token(
        subject="2",
        role="interviewer",
        extra_claims={"type": "ats", "email": "interviewer@itsp.co.id"},
    )
    r5 = client.get(
        "/api/v1/recruitment/admins",
        headers={"Authorization": f"Bearer {token_interviewer}"},
    )
    assert r5.status_code == 403

    # 6. Bearer token asli dengan role benar (admin) -> 200
    token_admin = create_access_token(
        subject="1",
        role="admin",
        extra_claims={"type": "ats", "email": "rec_admin@itsp.co.id"},
    )
    r6 = client.get(
        "/api/v1/recruitment/admins",
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert r6.status_code == 200


# ============================================================================
# (e) CMS WRITE /cms/{model} OLEH MARKETING DAN ADMIN
# ============================================================================

def test_cms_model_write_access():
    # POST announcement: Tanpa auth -> 401
    r1 = client.post("/api/v1/cms/announcements", json={"message": "Test 1"})
    assert r1.status_code == 401

    # POST announcement: Secret tanpa role -> 403
    r2 = client.post(
        "/api/v1/cms/announcements",
        headers={"X-Internal-Secret": SECRET},
        json={"message": "Test 2"},
    )
    assert r2.status_code == 403

    # POST announcement: Secret + role salah (hr tidak boleh tulis konten CMS) -> 403
    r3 = client.post(
        "/api/v1/cms/announcements",
        headers={"X-Internal-Secret": SECRET, "X-Admin-Role": "hr"},
        json={"message": "Test 3"},
    )
    assert r3.status_code == 403

    # POST announcement: Secret + role marketing -> 201 (diizinkan)
    r4 = client.post(
        "/api/v1/cms/announcements",
        headers={"X-Internal-Secret": SECRET, "X-Admin-Role": "marketing"},
        json={"message": "Promo Spesial", "is_active": True},
    )
    assert r4.status_code == 201
    item_id = r4.json()["data"]["id"]

    # PUT announcement: Secret + role marketing -> 200
    r5 = client.put(
        f"/api/v1/cms/announcements/{item_id}",
        headers={"X-Internal-Secret": SECRET, "X-Admin-Role": "marketing"},
        json={"message": "Promo Spesial Update"},
    )
    assert r5.status_code == 200

    # PUT announcement: Secret + role hr -> 403
    r6 = client.put(
        f"/api/v1/cms/announcements/{item_id}",
        headers={"X-Internal-Secret": SECRET, "X-Admin-Role": "hr"},
        json={"message": "Hacked by HR"},
    )
    assert r6.status_code == 403

    # POST announcement: Secret + role admin -> 201
    r7 = client.post(
        "/api/v1/cms/announcements",
        headers={"X-Internal-Secret": SECRET, "X-Admin-Role": "admin"},
        json={"message": "Pemberitahuan Direksi", "is_active": True},
    )
    assert r7.status_code == 201
    item2_id = r7.json()["data"]["id"]

    # DELETE announcement: Secret + role marketing -> 200
    r8 = client.delete(
        f"/api/v1/cms/announcements/{item_id}",
        headers={"X-Internal-Secret": SECRET, "X-Admin-Role": "marketing"},
    )
    assert r8.status_code == 200

    # Model sensitif 'users': marketing TIDAK boleh menulis -> 403
    r9 = client.post(
        "/api/v1/cms/users",
        headers={"X-Internal-Secret": SECRET, "X-Admin-Role": "marketing"},
        json={"email": "attacker@test.com", "name": "Attacker", "role": "admin"},
    )
    assert r9.status_code == 403
