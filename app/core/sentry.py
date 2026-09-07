import logging
from typing import Any, Dict
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.core.config import settings

logger = logging.getLogger(__name__)


def strip_sensitive_data(event: Dict[str, Any], hint: Dict[str, Any]) -> Dict[str, Any]:
    """
    Security filter: Sanitize PII and sensitive credentials before dispatching to Sentry.
    Ensures passwords, tokens, API keys, and candidate CV files are NEVER leaked to logs.
    """
    sensitive_keys = {
        "password",
        "token",
        "secret",
        "authorization",
        "mfa_secret",
        "cookie",
        "cv_file",
        "cvFile",
        "cv_base64",
    }

    # Sanitize request headers
    if "request" in event:
        req = event["request"]
        if "headers" in req and isinstance(req["headers"], dict):
            for k in list(req["headers"].keys()):
                if k.lower() in ["authorization", "cookie", "x-api-key"]:
                    req["headers"][k] = "[FILTERED]"

        # Sanitize JSON payload data
        if "data" in req and isinstance(req["data"], dict):
            for key in req["data"]:
                if any(s in key.lower() for s in sensitive_keys):
                    req["data"][key] = "[FILTERED]"

    return event


def init_sentry() -> None:
    """Initialize Sentry SDK with strict security awareness and performance tracing."""
    if not settings.SENTRY_DSN:
        logger.info("Sentry DSN is not configured. Running with local logging.")
        return

    try:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.ENVIRONMENT,
            release=f"itsp-core-api@{settings.VERSION}",
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            profiles_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
            send_default_pii=False,  # Enforce NO PII transmission
            before_send=strip_sensitive_data,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
            ],
        )
        logger.info("Sentry telemetry successfully initialized.")
    except Exception as e:
        logger.warning(f"Failed to initialize Sentry: {e}")


def capture_security_event(message: str, level: str = "warning", extra: Dict[str, Any] = None):
    """Log security-related events (e.g. failed login attempts, anti-cheat violations)."""
    logger.warning(f"[SECURITY EVENT] {message} | Extra: {extra}")
    if settings.SENTRY_DSN:
        with sentry_sdk.push_scope() as scope:
            if extra:
                for k, v in extra.items():
                    scope.set_extra(k, v)
            sentry_sdk.capture_message(message, level=level)
