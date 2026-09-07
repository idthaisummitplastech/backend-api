import pytest
from fastapi.testclient import TestClient
from main import app
from app.core.security import get_password_hash, verify_password, create_access_token, decode_access_token

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
