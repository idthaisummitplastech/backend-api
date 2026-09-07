import logging
from sqlalchemy.orm import Session

from app.db.base_class import Base
from app.db.session import engine
from app.crud.crud_auth import crud_admin
from app.crud.crud_recruitment import crud_setting
from app.schemas.auth import AdminCreate

logger = logging.getLogger(__name__)


def init_db(db: Session) -> None:
    """Initialize tables and create default seed users and master configuration."""
    logger.info("Synchronizing database tables...")
    Base.metadata.create_all(bind=engine)

    # 1. Seed Default Admin
    admin = crud_admin.get_by_username(db, "admin")
    if not admin:
        crud_admin.create(
            db,
            obj_in=AdminCreate(
                username="admin",
                name="System Superadmin",
                email="admin@itsp.co.id",
                password="admin123!Password",
                role="admin",
                department="IT",
            ),
        )
        logger.info("Default superadmin created: admin / admin123!Password")

    # 2. Seed Default HR Evaluator
    hr = crud_admin.get_by_username(db, "hr_recruitment")
    if not hr:
        crud_admin.create(
            db,
            obj_in=AdminCreate(
                username="hr_recruitment",
                name="HR Recruitment Specialist",
                email="recruitment@itsp.co.id",
                password="hr123!Password",
                role="hr",
                department="HRD & GA",
            ),
        )
        logger.info("Default HR user created: hr_recruitment / hr123!Password")

    # 3. Seed Default IT User Dept Evaluator
    user_dept = crud_admin.get_by_username(db, "user_it")
    if not user_dept:
        crud_admin.create(
            db,
            obj_in=AdminCreate(
                username="user_it",
                name="IT Section Head",
                email="it.head@itsp.co.id",
                password="it123!Password",
                role="user_dept",
                department="IT",
            ),
        )
        logger.info("Default User Dept created: user_it / it123!Password")

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
