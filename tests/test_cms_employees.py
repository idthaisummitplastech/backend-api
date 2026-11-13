"""
Unit and integration tests for GET /api/v1/cms/employees:
- Authorization via get_current_cms_user, restricted to role 'admin' in User DB.
- Non-admin roles (editor, marketing, etc.) return 403 Forbidden.
- Sensitive fields (nik, phone, address, birth_date, salary, etc.) MUST NOT be present in response.
- Only employee_id, full_name, email, department, job_title are returned.
- Search query (?search=) tokenized per-word matching.
- FIRST_LOGIN_ENFORCE behavior (true/false).
"""
import os
os.environ["ENVIRONMENT"] = "test"
os.environ["DEBUG"] = "true"

from datetime import datetime, timezone, date
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
import app.db.session as db_session
from app.core.config import settings
settings.ENVIRONMENT = "test"

from app.core.security import get_password_hash
from app.models.auth import User
from app.models.recruitment import DataKaryawan

# Setup in-memory SQLite engine
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=test_engine)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

db_session.engine = test_engine
db_session.engine_company = test_engine
db_session.SessionLocal = TestingSessionLocal
db_session.SessionCompanyLocal = TestingSessionLocal

import app.db.init_db as init_db_module
init_db_module.engine = test_engine
init_db_module.engine_company = test_engine
init_db_module.init_db = lambda db: None

from main import app
from app.db.session import get_db, get_db_company
from app.db.session import get_db as get_karir_db
from fastapi.testclient import TestClient


class TestCmsEmployeesEndpoint:

    @pytest.fixture(autouse=True)
    def setup_fixtures(self):
        def override_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_db_company] = override_db
        app.dependency_overrides[get_karir_db] = override_db

        db = TestingSessionLocal()
        # Seed CMS users
        admin_user = db.query(User).filter(User.email == "cmsadmin@example.com").first()
        if not admin_user:
            admin_user = User(
                email="cmsadmin@example.com",
                name="CMS Admin",
                password=get_password_hash("password123"),
                role="admin",
                is_active=True,
                is_first_login=False,
                session_version=1,
                mfa_enabled=True,
                mfa_verified_at=datetime.now(timezone.utc),
            )
            db.add(admin_user)

        editor_user = db.query(User).filter(User.email == "cmseditor@example.com").first()
        if not editor_user:
            editor_user = User(
                email="cmseditor@example.com",
                name="CMS Editor",
                password=get_password_hash("password123"),
                role="editor",
                is_active=True,
                is_first_login=False,
                session_version=1,
                mfa_enabled=True,
                mfa_verified_at=datetime.now(timezone.utc),
            )
            db.add(editor_user)

        # Seed Career Employees in DataKaryawan
        emp1 = db.query(DataKaryawan).filter(DataKaryawan.employee_id == "EMP-001").first()
        if not emp1:
            emp1 = DataKaryawan(
                employee_id="EMP-001",
                sequence_number=1,
                first_name="Rifqi",
                last_name="Ahmad",
                full_name="Rifqi Ahmad",
                email="rifqi.ahmad@example.com",
                phone="081234567890",
                nik="3201012345670001",
                department="Technology",
                job_title="Software Engineer",
                employee_status="active",
                address_ktp="Jl. Merdeka No. 1",
                contract_start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            )
            db.add(emp1)

        emp2 = db.query(DataKaryawan).filter(DataKaryawan.employee_id == "EMP-002").first()
        if not emp2:
            emp2 = DataKaryawan(
                employee_id="EMP-002",
                sequence_number=2,
                first_name="Siti",
                last_name="Nurhaliza",
                full_name="Siti Nurhaliza",
                email="siti.nurhaliza@example.com",
                phone="089876543210",
                nik="3201012345670002",
                department="Human Resources",
                job_title="HR Specialist",
                employee_status="active",
                address_ktp="Jl. Sudirman No. 10",
                contract_start_date=datetime(2025, 3, 1, tzinfo=timezone.utc),
            )
            db.add(emp2)

        db.commit()
        self.admin_id = admin_user.id
        self.editor_id = editor_user.id
        db.close()

        self.client = TestClient(app)
        yield
        app.dependency_overrides.clear()

    def test_cms_employees_forbidden_for_non_admin_role(self):
        """Non-admin CMS user (role='editor') must receive 403 Forbidden."""
        res = self.client.get(
            "/api/v1/cms/employees",
            headers={
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-CMS-User-Id": str(self.editor_id),
                "X-Admin-Role": "editor",
                "X-Session-Version": "1",
            },
        )
        assert res.status_code == 403
        assert "hanya untuk Administrator" in res.json()["detail"]

    def test_cms_employees_allowed_for_admin_role_and_strips_sensitive_fields(self):
        """Admin CMS user receives 200 and strict whitelist: NO NIK, phone, address, etc."""
        res = self.client.get(
            "/api/v1/cms/employees",
            headers={
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-CMS-User-Id": str(self.admin_id),
                "X-Admin-Role": "admin",
                "X-Session-Version": "1",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert len(data["employees"]) >= 2

        for emp in data["employees"]:
            # Allowed whitelist keys only
            assert set(emp.keys()) == {"employee_id", "full_name", "email", "department", "job_title"}
            # Explicit assertions that sensitive fields are completely absent
            assert "nik" not in emp
            assert "phone" not in emp
            assert "address_ktp" not in emp
            assert "birth_date" not in emp
            assert "salary" not in emp

    def test_cms_employees_search_tokenized(self):
        """Search query supports multi-token per-word search."""
        # 1. Search 'Rifqi'
        res1 = self.client.get(
            "/api/v1/cms/employees?search=Rifqi",
            headers={
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-CMS-User-Id": str(self.admin_id),
                "X-Admin-Role": "admin",
                "X-Session-Version": "1",
            },
        )
        assert res1.status_code == 200
        assert res1.json()["total"] == 1
        assert res1.json()["employees"][0]["employee_id"] == "EMP-001"

        # 2. Search multi-token 'Ahmad Rifqi' (both tokens match emp1)
        res2 = self.client.get(
            "/api/v1/cms/employees?search=Ahmad%20Rifqi",
            headers={
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-CMS-User-Id": str(self.admin_id),
                "X-Admin-Role": "admin",
                "X-Session-Version": "1",
            },
        )
        assert res2.status_code == 200
        assert res2.json()["total"] == 1
        assert res2.json()["employees"][0]["employee_id"] == "EMP-001"

        # 3. Search non-matching tokens
        res3 = self.client.get(
            "/api/v1/cms/employees?search=UnknownPersonNotExisting",
            headers={
                "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                "X-CMS-User-Id": str(self.admin_id),
                "X-Admin-Role": "admin",
                "X-Session-Version": "1",
            },
        )
        assert res3.status_code == 200
        assert res3.json()["total"] == 0
        assert len(res3.json()["employees"]) == 0

    def test_cms_employees_first_login_enforce_flag(self):
        """FIRST_LOGIN_ENFORCE=false allows valid CMS admin even if session version header is missing;
        FIRST_LOGIN_ENFORCE=true strictly enforces session validation."""
        orig = settings.FIRST_LOGIN_ENFORCE
        try:
            # 1. FIRST_LOGIN_ENFORCE = False: works without X-Session-Version
            settings.FIRST_LOGIN_ENFORCE = False
            res_false = self.client.get(
                "/api/v1/cms/employees",
                headers={
                    "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                    "X-CMS-User-Id": str(self.admin_id),
                    "X-Admin-Role": "admin",
                },
            )
            assert res_false.status_code == 200
            assert res_false.json()["success"] is True

            # 2. FIRST_LOGIN_ENFORCE = True: fails if X-Session-Version missing
            settings.FIRST_LOGIN_ENFORCE = True
            res_true_no_ver = self.client.get(
                "/api/v1/cms/employees",
                headers={
                    "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                    "X-CMS-User-Id": str(self.admin_id),
                    "X-Admin-Role": "admin",
                },
            )
            assert res_true_no_ver.status_code == 401
            assert "X-Session-Version" in res_true_no_ver.json()["detail"]

            # 3. FIRST_LOGIN_ENFORCE = True: succeeds when X-Session-Version present
            res_true_with_ver = self.client.get(
                "/api/v1/cms/employees",
                headers={
                    "X-Internal-Secret": settings.INTERNAL_API_SECRET,
                    "X-CMS-User-Id": str(self.admin_id),
                    "X-Admin-Role": "admin",
                    "X-Session-Version": "1",
                },
            )
            assert res_true_with_ver.status_code == 200
            assert res_true_with_ver.json()["success"] is True
        finally:
            settings.FIRST_LOGIN_ENFORCE = orig
