from typing import Generator
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings

logger = logging.getLogger(__name__)

# Enterprise connection pooling configuration (Career Portal DB)
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,  # Proactively test connection liveness
    pool_recycle=1800,   # Recycle connections after 30 minutes
    echo=settings.DEBUG,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Enterprise connection pooling configuration (Company Profile CMS DB)
engine_company = create_engine(
    settings.DATABASE_COMPANY_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=settings.DEBUG,
)
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
