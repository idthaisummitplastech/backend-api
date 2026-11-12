from typing import Generator
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings

logger = logging.getLogger(__name__)

def _build_engine(db_url: str):
    if db_url.startswith("sqlite"):
        return create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            echo=settings.DEBUG,
        )
    return create_engine(
        db_url,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_pre_ping=True,  # Proactively test connection liveness
        pool_recycle=1800,   # Recycle connections after 30 minutes
        echo=settings.DEBUG,
    )


# Enterprise connection pooling configuration (Career Portal DB)
engine = _build_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Enterprise connection pooling configuration (Company Profile CMS DB)
engine_company = _build_engine(settings.DATABASE_COMPANY_URL)
SessionCompanyLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_company)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI Dependency that provides a transactional database session for Career Portal DB.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as exc:
        db.rollback()
        logger.error(f"Career DB session rolled back due to exception: {exc}")
        raise
    finally:
        db.close()


def get_db_company() -> Generator[Session, None, None]:
    """
    FastAPI Dependency that provides a transactional database session for Company Profile DB.
    """
    db = SessionCompanyLocal()
    try:
        yield db
    except Exception as exc:
        db.rollback()
        logger.error(f"Company DB session rolled back due to exception: {exc}")
        raise
    finally:
        db.close()
