import pytest
from scripts.verify_env_consistency import verify_env_secrets, verify_first_login_enforce_consistency


def test_verify_env_secrets_success():
    """Valid environment configuration where secrets match and are properly decoupled."""
    b_secret = "a" * 32
    f_secret = "a" * 32
    jwt_secret = "b" * 32

    is_valid, errors = verify_env_secrets(
        backend_internal_secret=b_secret,
        career_internal_secret=f_secret,
        company_internal_secret=f_secret,
        backend_jwt_secret=jwt_secret,
    )
    assert is_valid is True
    assert len(errors) == 0


def test_verify_env_secrets_fails_on_mismatch():
    """Fails fast with clear error message when frontend and backend secrets do not match."""
    b_secret = "backend_secret_32_chars_long_123"
    career_secret = "different_career_secret_32_chars"
    company_secret = "backend_secret_32_chars_long_123"

    is_valid, errors = verify_env_secrets(
        backend_internal_secret=b_secret,
        career_internal_secret=career_secret,
        company_internal_secret=company_secret,
    )
    assert is_valid is False
    assert any("MISMATCH SECRET! BACKEND_INTERNAL_SECRET di Web Karir" in err for err in errors)


def test_verify_env_secrets_fails_on_short_or_missing_secret():
    """Fails when any secret is missing or shorter than 32 characters."""
    # 1. Missing backend secret
    is_valid, errors = verify_env_secrets(
        backend_internal_secret="",
        career_internal_secret="c" * 32,
        company_internal_secret="c" * 32,
    )
    assert is_valid is False
    assert any("Backend: INTERNAL_API_SECRET belum diatur" in err for err in errors)

    # 2. Short frontend secret
    is_valid, errors = verify_env_secrets(
        backend_internal_secret="c" * 32,
        career_internal_secret="too_short",
        company_internal_secret="c" * 32,
    )
    assert is_valid is False
    assert any("Web Karir: BACKEND_INTERNAL_SECRET terlalu pendek" in err for err in errors)


def test_verify_env_secrets_fails_on_jwt_and_internal_secret_collision():
    """Fails when JWT signing SECRET_KEY is identical to INTERNAL_API_SECRET."""
    shared_key = "x" * 32
    is_valid, errors = verify_env_secrets(
        backend_internal_secret=shared_key,
        career_internal_secret=shared_key,
        company_internal_secret=shared_key,
        backend_jwt_secret=shared_key,
    )
    assert is_valid is False
    assert any("PELANGGARAN PEMISAHAN SECRET" in err for err in errors)


def test_verify_first_login_enforce_consistency_success():
    """All services match in FIRST_LOGIN_ENFORCE boolean value."""
    # When all true
    ok1, err1 = verify_first_login_enforce_consistency("true", "true", "true")
    assert ok1 is True
    assert len(err1) == 0

    # When all false
    ok2, err2 = verify_first_login_enforce_consistency("false", "false", "false")
    assert ok2 is True
    assert len(err2) == 0


def test_verify_first_login_enforce_consistency_fails_on_mismatch():
    """Fails when any service has mismatching switch value."""
    ok, err = verify_first_login_enforce_consistency("true", "false", "true")
    assert ok is False
    assert any("MISMATCH FIRST_LOGIN_ENFORCE! Backend (True) != Web Karir (False)" in e for e in err)


def test_verify_first_login_enforce_rejects_next_public():
    """Fails when frontend defines NEXT_PUBLIC_FIRST_LOGIN_ENFORCE."""
    ok, err = verify_first_login_enforce_consistency(
        "true", "true", "true",
        career_env={"NEXT_PUBLIC_FIRST_LOGIN_ENFORCE": "true"}
    )
    assert ok is False
    assert any("Dilarang menggunakan NEXT_PUBLIC_FIRST_LOGIN_ENFORCE" in e for e in err)

