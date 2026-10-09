import logging
import os
import secrets
from sqlalchemy.orm import Session

from app.db.base_class import Base
from app.db.session import engine, engine_company
from app.db import base as models_base  # noqa: F401 - ensure all CMS models registered
from app.db.seed_company import seed_company_cms
from app.crud.crud_auth import crud_admin
from app.crud.crud_recruitment import crud_setting
from app.schemas.auth import AdminCreate

logger = logging.getLogger(__name__)


def init_db(db: Session) -> None:
    """Initialize tables and create default seed users and master configuration."""
    logger.info("Synchronizing database tables...")
    Base.metadata.create_all(bind=engine)
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            migration_queries = [
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS nik VARCHAR(50);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS first_name VARCHAR(150);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS last_name VARCHAR(150);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS gender VARCHAR(50);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS religion VARCHAR(50);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS ethnic VARCHAR(50);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS height_cm INTEGER;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS weight_kg INTEGER;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS marriage_status VARCHAR(50);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS birth_place VARCHAR(150);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS address_ktp TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS province_ktp VARCHAR(100);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS city_ktp VARCHAR(100);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS district_ktp VARCHAR(100);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS village_ktp VARCHAR(100);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS rt_ktp VARCHAR(20);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS rw_ktp VARCHAR(20);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS street_ktp VARCHAR(255);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS domicile_same_as_ktp BOOLEAN DEFAULT TRUE;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS address_domicile TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS province_domicile VARCHAR(100);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS city_domicile VARCHAR(100);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS district_domicile VARCHAR(100);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS village_domicile VARCHAR(100);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS rt_domicile VARCHAR(20);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS rw_domicile VARCHAR(20);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS street_domicile VARCHAR(255);",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS photo_file TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS ktp_file TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS kk_file TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS ijazah_file TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS transkrip_file TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS cert_nonformal_file TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS bpjs_kesehatan_file TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS bpjs_ketenagakerjaan_file TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS npwp_file TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS akta_file TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS skck_file TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS education_history TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS work_history TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS family_parents TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS family_siblings TEXT;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS psikotes_duration_minutes INTEGER DEFAULT 60;",
                "ALTER TABLE applicants ADD COLUMN IF NOT EXISTS user_test_duration_minutes INTEGER DEFAULT 60;",
            ]
            for q in migration_queries:
                conn.execute(text(q))
            data_karyawan_queries = [
                "ALTER TABLE data_karyawan ALTER COLUMN email DROP NOT NULL;",
                "ALTER TABLE data_karyawan ALTER COLUMN phone DROP NOT NULL;",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS years_of_service NUMERIC(5,2);",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS contract_history TEXT;",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS contract_sequence INTEGER DEFAULT 1;",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS level VARCHAR(50);",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS section VARCHAR(100);",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS employee_type VARCHAR(50);",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS factory_office VARCHAR(50);",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS payroll_id VARCHAR(50);",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS plant VARCHAR(50);",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS ptkp_status VARCHAR(20);",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS npwp VARCHAR(50);",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS bpjs_tk_no VARCHAR(50);",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS bank_account_no VARCHAR(50);",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS bank_name VARCHAR(50) DEFAULT 'BCA';",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS father_name VARCHAR(150);",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS mother_name VARCHAR(150);",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS spouse_name VARCHAR(150);",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS family_children TEXT;",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS family_members_count INTEGER DEFAULT 0;",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS family_parents TEXT;",
                "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS family_siblings TEXT;",
            ]
            for q in data_karyawan_queries:
                conn.execute(text(q))
            conn.commit()
            logger.info("Career applicants and data_karyawan tables migration verified.")
    except Exception as e:
        logger.warning(f"Career DB migration notice: {e}")

    try:
        Base.metadata.create_all(bind=engine_company)
        # Auto-migration: ensure newly added columns exist in existing production DB tables
        from sqlalchemy import text
        with engine_company.connect() as conn:
            conn.execute(text("ALTER TABLE nav_menus ADD COLUMN IF NOT EXISTS is_maintenance BOOLEAN DEFAULT FALSE;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(100);"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR(100);"))
            conn.commit()
        logger.info("Company CMS tables synchronized (web_perusahaan).")
        seed_company_cms()
    except Exception as e:
        logger.warning(f"Company DB sync skipped: {e}")

    # 1. Seed Default Admin — password WAJIB via env, tanpa hardcoded di code.
    # Contoh: SEED_ADMIN_PASSWORD="isi-password-kuat-sementara" python -m app.db.init_db
    # Jika env kosong, buat password acak aman agar tidak ada kredensial default yang lemah.
    admin = crud_admin.get_by_username(db, "admin")
    admin_email = crud_admin.get_by_email(db, "admin@itsp.co.id")
    if not admin and not admin_email:
        admin_password = os.getenv("SEED_ADMIN_PASSWORD") or secrets.token_urlsafe(24)
        crud_admin.create(
            db,
            obj_in=AdminCreate(
                username="admin",
                name="System Superadmin",
                email="admin@itsp.co.id",
                password=admin_password,
                role="admin",
                department="IT",
            ),
        )
        if os.getenv("SEED_ADMIN_PASSWORD"):
            logger.info("Default superadmin created: admin (password dari SEED_ADMIN_PASSWORD)")
        else:
            logger.warning(
                "SEED_ADMIN_PASSWORD kosong — superadmin dibuat dengan password acak. "
                "Set SEED_ADMIN_PASSWORD via env lalu reset password bila perlu."
            )

    # 2. Seed Default HR Evaluator — password WAJIB via env / acak, tanpa hardcoded.
    hr = crud_admin.get_by_username(db, "hr_recruitment")
    hr_email = crud_admin.get_by_email(db, "recruitment@itsp.co.id")
    if not hr and not hr_email:
        hr_password = os.getenv("SEED_HR_PASSWORD") or secrets.token_urlsafe(24)
        crud_admin.create(
            db,
            obj_in=AdminCreate(
                username="hr_recruitment",
                name="HR Recruitment Specialist",
                email="recruitment@itsp.co.id",
                password=hr_password,
                role="hr",
                department="HRD & GA",
            ),
        )
        logger.info("Default HR user created: hr_recruitment (password via SEED_HR_PASSWORD / acak)")

    # 3. Seed Default IT User Dept Evaluator — password WAJIB via env / acak.
    user_dept = crud_admin.get_by_username(db, "user_it")
    user_dept_email = crud_admin.get_by_email(db, "it.head@itsp.co.id")
    if not user_dept and not user_dept_email:
        it_password = os.getenv("SEED_IT_PASSWORD") or secrets.token_urlsafe(24)
        crud_admin.create(
            db,
            obj_in=AdminCreate(
                username="user_it",
                name="IT Section Head",
                email="it.head@itsp.co.id",
                password=it_password,
                role="user_dept",
                department="IT & Enterprise System",
            ),
        )
        logger.info("Default User Dept evaluator created: user_it (password via SEED_IT_PASSWORD / acak)")

    # 3b. Primary Superadmin 1526.08.26 / it-04@thaisummit.co.id — Employee ID immutable, portal both
    # Login utama pakai Employee ID; email fallback 6 bulan. Password default Itsp@YYYY (is_first_login=true).
    it04 = crud_admin.get_by_employee_id(db, "1526.08.26")
    # legacy one-time: baris lama terlanjur ITSP.1526.08.26 -> migrasi ke polos
    it04_legacy = crud_admin.get_by_employee_id(db, "ITSP.1526.08.26")
    if it04_legacy and not it04:
        it04 = it04_legacy
    it04_email = crud_admin.get_by_email(db, "it-04@thaisummit.co.id")
    if it04_legacy and it04_email and it04_legacy.id == it04_email.id:
        it04 = it04_legacy
    if not it04 and not it04_email:
        from app.schemas.auth import get_default_password as _gdp
        it04_password = os.getenv("SEED_IT04_PASSWORD") or _gdp()
        crud_admin.create(
            db,
            obj_in=AdminCreate(
                employee_id="1526.08.26",
                username="it-04",
                name="IT Admin",
                email="it-04@thaisummit.co.id",
                password=it04_password,
                role="admin",
                department="IT",
                portal_access="both",
                is_active=True,
                is_first_login=True,
            ),
        )
        logger.info("Primary superadmin ensured: 1526.08.26 / it-04@thaisummit.co.id (role=admin, portal=both)")
    else:
        target = it04 or it04_email
        needs = []
        if target.role != "admin":
            target.role = "admin"; needs.append("role->admin")
        if (getattr(target, "portal_access", None) or "") != "both":
            target.portal_access = "both"; needs.append("portal->both")
        if not getattr(target, "is_active", True):
            target.is_active = True; needs.append("is_active->true")
        if (target.employee_id or "") != "1526.08.26":
            target.employee_id = "1526.08.26"; needs.append("employee_id")
        if (getattr(target, "email", "") or "").lower() != "it-04@thaisummit.co.id":
            target.email = "it-04@thaisummit.co.id"; needs.append("email")
        if (getattr(target, "username", "") or "") != "it-04":
            target.username = "it-04"; needs.append("username")
        if needs:
            db.add(target); db.commit(); db.refresh(target)
            logger.info(f"Primary superadmin promoted: {', '.join(needs)}")
        else:
            logger.info("Primary superadmin already present: 1526.08.26")

    # 4. Master Recruitment Settings
    default_settings = {
        "mcu_clinic_name": "Klinik Pramita / Prodia Karawang",
        "mcu_clinic_address": "Jl. Galuh Mas Raya No. 12, Karawang Barat",
        "plant_address": "Kawasan Industri KIIC, Jl. Permata Raya Lot CA-1, Karawang",
        "plant_maps_url": "https://maps.google.com/?q=PT+Indonesia+Thai+Summit+Plastech",
    }
    for k, v in default_settings.items():
        if not crud_setting.get_by_attribute(db, "key", k):
            crud_setting.create(db, obj_in={"key": k, "value": v})

    logger.info("Database seeding completed successfully.")
