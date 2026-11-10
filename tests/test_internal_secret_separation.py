import hmac
import pytest
from unittest.mock import patch
from app.core.config import Settings, settings
from app.core.security import verify_internal_api_secret


def test_verify_internal_api_secret_timing_safe():
    """Verify constant-time digest comparison behaves correctly with valid and invalid secrets."""
    valid_secret = "a_very_secure_internal_api_secret_key_32_chars_min"
    with patch.object(settings, "INTERNAL_API_SECRET", valid_secret):
        # 1. Exact match returns True
        assert verify_internal_api_secret(valid_secret) is True

        # 2. Wrong secret returns False
        assert verify_internal_api_secret("wrong_secret_value_123456789012345678") is False

        # 3. None or empty header returns False
        assert verify_internal_api_secret("") is False
        assert verify_internal_api_secret(None) is False


def test_empty_or_short_configured_secret_never_matches():
    """Empty or short configured secret in settings must NEVER match any incoming header."""
    # 1. Configured secret is empty string
    with patch.object(settings, "INTERNAL_API_SECRET", ""):
        assert verify_internal_api_secret("") is False
        assert verify_internal_api_secret("any_value") is False
        assert verify_internal_api_secret(None) is False

    # 2. Configured secret is shorter than 32 characters
    with patch.object(settings, "INTERNAL_API_SECRET", "short_secret_only_24_chars!"):
        assert verify_internal_api_secret("short_secret_only_24_chars!") is False

    # 3. Configured secret is None
    with patch.object(settings, "INTERNAL_API_SECRET", None):
        assert verify_internal_api_secret("any_value") is False


def test_internal_secret_decoupled_from_jwt_secret_key():
    """JWT SECRET_KEY must NOT be accepted as X-Internal-Secret when they are distinct."""
    jwt_key = "jwt_signing_secret_key_minimum_32_chars_long_1234"
    internal_key = "internal_microservice_api_secret_key_32_chars_5678"

    with patch.object(settings, "SECRET_KEY", jwt_key), \
         patch.object(settings, "INTERNAL_API_SECRET", internal_key):
        # Sending JWT key as internal secret is REJECTED
        assert verify_internal_api_secret(jwt_key) is False
        # Sending proper internal key is ACCEPTED
        assert verify_internal_api_secret(internal_key) is True


def test_backend_settings_validation_rejects_missing_or_short_internal_secret():
    """Backend startup fails fast if INTERNAL_API_SECRET is missing or less than 32 chars."""
    base_env = {
        "SECRET_KEY": "a" * 32,
        "DATABASE_URL": "postgresql+psycopg://u:p@localhost:5432/db",
        "DATABASE_COMPANY_URL": "postgresql+psycopg://u:p@localhost:5432/dbc",
    }

    # 1. Missing INTERNAL_API_SECRET
    with pytest.raises(ValueError) as exc1:
        Settings(**base_env, INTERNAL_API_SECRET="")
    assert "INTERNAL_API_SECRET (min 32 karakter via env)" in str(exc1.value)

    # 2. Short INTERNAL_API_SECRET (< 32 chars)
    with pytest.raises(ValueError) as exc2:
        Settings(**base_env, INTERNAL_API_SECRET="too_short_secret_key_123")
    assert "INTERNAL_API_SECRET (min 32 karakter via env)" in str(exc2.value)

    # 3. Valid INTERNAL_API_SECRET (>= 32 chars) succeeds
    valid_settings = Settings(**base_env, INTERNAL_API_SECRET="b" * 32)
    assert valid_settings.INTERNAL_API_SECRET == "b" * 32
