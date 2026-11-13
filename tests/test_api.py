"""
Smoke tests for root/health endpoints, security headers, password hashing, and JWT flow.
Uses SQLite in-memory — no PostgreSQL required.
"""
import os
os.environ["ENVIRONMENT"] = "test"
os.environ["DEBUG"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["DATABASE_COMPANY_URL"] = "sqlite:///:memory:"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.session as db_session
from app.db.base import Base
from app.core.config import settings
settings.ENVIRONMENT = "test"

# In-memory SQLite engine shared across threads (StaticPool)
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

from fastapi.testclient import TestClient
from main import app
from app.core.security import get_password_hash, verify_password, create_access_token, decode_access_token
from app.db.session import get_db, get_db_company


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_db_company] = override_get_db

client = TestClient(app)


def test_root_endpoint():
    """Verify root health check endpoint returns 200."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "version" in data


def test_health_check():
    """Verify /health endpoint returns healthy status."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_security_headers_present():
    """Verify OWASP security headers are injected into HTTP responses."""
    response = client.get("/")
    headers = response.headers
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-XSS-Protection") == "1; mode=block"
    assert "Strict-Transport-Security" in headers


def test_password_hashing_and_verification():
    """Verify bcrypt hash generation and constant-time verification."""
    raw_pass = "SuperSecurePassword123!"
    hashed = get_password_hash(raw_pass)
    assert hashed != raw_pass
    assert verify_password(raw_pass, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_jwt_token_flow():
    """Verify JWT token signing and decoding."""
    token = create_access_token(subject=42, role="hr", department="HRD")
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["role"] == "hr"
    assert payload["department"] == "HRD"
