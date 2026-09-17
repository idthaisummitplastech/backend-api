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
        Base.metadata.create_all(bind=engine_company)
        # Auto-migration: ensure newly added columns exist in existing production DB tables
        from sqlalchemy import text
        with engine_company.connect() as conn:
            conn.execute(text("ALTER TABLE nav_menus ADD COLUMN IF NOT EXISTS is_maintenance BOOLEAN DEFAULT FALSE;"))
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
