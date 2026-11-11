import os
import pytest

# Pastikan environment test tersetting sebelum modul app di-import
os.environ["ENVIRONMENT"] = "test"
os.environ["DEBUG"] = "true"
os.environ.setdefault("SECRET_KEY", "test_jwt_secret_key_minimum_32_characters_long_for_testing")
os.environ.setdefault("INTERNAL_API_SECRET", "test_internal_api_secret_minimum_32_characters_for_proxy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_karir.db")
os.environ.setdefault("DATABASE_COMPANY_URL", "sqlite:///./test_company.db")

from app.core.config import settings
settings.ENVIRONMENT = "test"

# Cegah lifespan auto-init Postgres riil saat menjalankan test suite
import app.db.init_db as init_db_module
init_db_module.init_db = lambda *args, **kwargs: None


@pytest.fixture(autouse=True)
def ensure_test_env(monkeypatch):
    """Pastikan settings pengujian selalu memiliki INTERNAL_API_SECRET dan SECRET_KEY yang valid."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "SECRET_KEY", os.environ.get("SECRET_KEY", "test_jwt_secret_key_minimum_32_characters_long_for_testing"))
    monkeypatch.setattr(settings, "INTERNAL_API_SECRET", os.environ.get("INTERNAL_API_SECRET", "test_internal_api_secret_minimum_32_characters_for_proxy"))
