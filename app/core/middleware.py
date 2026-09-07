import logging
import time
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
import sentry_sdk

logger = logging.getLogger(__name__)

# Enterprise IP-based Rate Limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    OWASP Compliant Security Headers Middleware.
    Hardens HTTP response headers against Clickjacking, MIME sniffing, and XSS.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time

        # Security Headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        
        # HSTS (HTTP Strict Transport Security) for HTTPS
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Diagnostic header
        response.headers["X-Process-Time"] = f"{process_time:.4f}s"
        return response


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catches unhandled internal server exceptions.
    Prevents information leakage (stack traces, SQL details) to end users.
    Dispatches full stack trace to Sentry for DevOps tracking.
    """
    logger.exception(f"Unhandled Exception on {request.method} {request.url.path}: {str(exc)}")
    
    # Send to Sentry
    sentry_sdk.capture_exception(exc)

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Terjadi kesalahan internal pada server. Silakan hubungi tim administrator.",
            "error_code": "INTERNAL_SERVER_ERROR",
        },
    )
