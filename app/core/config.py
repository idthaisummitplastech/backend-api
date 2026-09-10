import json
from typing import List, Self, Union
from pydantic import AnyHttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application Info
    PROJECT_NAME: str = "PT ITSP Core Backend"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    VERSION: str = "1.0.0"

    # Security & Cryptography — WAJIB via env, tanpa fallback di code.
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours for Admin/HR
    APPLICANT_TOKEN_EXPIRE_MINUTES: int = 180  # 3 hours for Applicants

    # CORS — WAJIB via env (comma-separated atau JSON array). Tanpa default hardcoded
    # agar ganti domain cukup via env. Contoh:
    # BACKEND_CORS_ORIGINS="https://itsp.co.id,https://karir.itsp.co.id"
    BACKEND_CORS_ORIGINS: List[str] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, str) and v.startswith("["):
            try:
                return json.loads(v)
            except Exception:
                return [v]
        return v

    # PostgreSQL Database — WAJIB via env, tanpa kredensial di code.
    DATABASE_URL: str = ""
    DATABASE_COMPANY_URL: str = ""
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # Sentry Telemetry
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 1.0
    SENTRY_PROFILES_SAMPLE_RATE: float = 1.0

    # Rate Limiting
    RATE_LIMIT_LOGIN: str = "10/minute"
    RATE_LIMIT_PUBLIC: str = "60/minute"

    # SMTP / Zimbra Corporate Email — WAJIB via env, tanpa kredensial di code.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "PT ITSP Recruitment Center"
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False

    # Frontend URLs — WAJIB via env, tanpa default localhost/domain di code.
    # Ganti domain cukup via .env / secret manager.
    # Contoh: FRONTEND_COMPANY_URL="https://itsp.co.id"
    #          FRONTEND_CAREER_URL="https://karir.itsp.co.id"
    FRONTEND_COMPANY_URL: str = ""
    FRONTEND_CAREER_URL: str = ""

    # Grafana OTLP Telemetry — WAJIB via env bila logging Grafana dipakai.
    # Tanpa default URL/token di code agar rotasi cukup via env.
    GRAFANA_OTLP_URL: str = ""
    GRAFANA_AUTH_HEADER: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _require_production_secrets(self) -> Self:
        # Fail-fast: tanpa kredensial via env, backend menolak start.
        # Development lokal tetap wajib isi .env (lihat .env.example) — tanpa kredensial default.
        missing: list[str] = []
        if not self.SECRET_KEY or len(self.SECRET_KEY) < 32:
            missing.append("SECRET_KEY (min 32 karakter via env)")
        if not self.DATABASE_URL:
            missing.append("DATABASE_URL (via env)")
        if not self.DATABASE_COMPANY_URL:
            missing.append("DATABASE_COMPANY_URL (via env)")
        if self.ENVIRONMENT.lower() == "production":
            if not self.SMTP_HOST:
                missing.append("SMTP_HOST (via env, production)")
            if not self.SMTP_USER or not self.SMTP_PASS:
                missing.append("SMTP_USER/SMTP_PASS (via env, production)")
        if missing:
            raise ValueError(
                "Konfigurasi backend belum lengkap — isi file .env (lihat .env.example). "
                "Kurang: " + ", ".join(missing)
            )
        return self


settings = Settings()
