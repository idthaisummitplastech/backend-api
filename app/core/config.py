import json
from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application Info
    PROJECT_NAME: str = "PT ITSP Core Backend"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    VERSION: str = "1.0.0"

    # Security & Cryptography
    SECRET_KEY: str = "pt-itsp-recruitment-ats-enterprise-jwt-secret-key-2026"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours for Admin/HR
    APPLICANT_TOKEN_EXPIRE_MINUTES: int = 180  # 3 hours for Applicants

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "https://itsp.co.id",
        "https://karir.itsp.co.id",
    ]

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

    # PostgreSQL Database
    DATABASE_URL: str = "postgresql+psycopg://sydit:syditsp@localhost:5432/web_karir"
    DATABASE_COMPANY_URL: str = "postgresql+psycopg://sydit:syditsp@localhost:5432/web_perusahaan"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # Sentry Telemetry
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 1.0
    SENTRY_PROFILES_SAMPLE_RATE: float = 1.0

    # Rate Limiting
    RATE_LIMIT_LOGIN: str = "10/minute"
    RATE_LIMIT_PUBLIC: str = "60/minute"

    # SMTP / Zimbra Corporate Email
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "PT ITSP Recruitment Center"
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False

    # Frontend URLs
    FRONTEND_COMPANY_URL: str = "http://localhost:3000"
    FRONTEND_CAREER_URL: str = "http://localhost:3001"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
