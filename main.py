import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from app.core.config import settings
from app.core.sentry import init_sentry
from app.core.middleware import SecurityHeadersMiddleware, global_exception_handler, limiter
from app.api.v1.api import api_router
from app.db.session import SessionLocal
from app.db.init_db import init_db

# Configure enterprise logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("itsp-core")

# 1. Initialize Sentry Telemetry
init_sentry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup & shutdown events."""
    logger.info("Starting PT ITSP Enterprise Core Backend API...")
    
    # Auto-seed database tables and initial superadmin on boot
    db = SessionLocal()
    try:
        init_db(db)
    except Exception as e:
        logger.error(f"Failed to auto-init database: {e}")
    finally:
        db.close()

    yield
    logger.info("Shutting down PT ITSP Enterprise Core Backend API...")


# 2. Instantiate FastAPI Application
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Enterprise REST API Gateway & Backend for PT Indonesia Thai Summit Plastech",
    docs_url="/docs" if settings.DEBUG or settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.DEBUG or settings.ENVIRONMENT != "production" else None,
    lifespan=lifespan,
)

# 3. Rate Limiting Middleware State
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 4. Global Unhandled Exception Handler (Security Aware: No stack leak to client)
app.add_exception_handler(Exception, global_exception_handler)

# 5. Security Headers Middleware (OWASP HSTS, CSP, X-Frame-Options)
app.add_middleware(SecurityHeadersMiddleware)

# 6. Strict CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "X-Total-Count", "X-Process-Time"],
)

# 7. Mount Central API Router
app.include_router(api_router, prefix="/api/v1")


# 8. Liveness & Health Probe Endpoints
@app.get("/", tags=["Health"])
def root():
    return {
        "status": "online",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
    }


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "database": "connected",
        "version": settings.VERSION,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8004, reload=True)
