# ==============================================================================
# PT INDONESIA THAI SUMMIT PLASTECH - PRODUCTION FASTAPI CONTAINER
# Security Hardened: Non-root User, Slim Base, Explicit Dependency Layers
# ==============================================================================

FROM python:3.13-slim AS base

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install OS dependencies needed for cryptography & networking
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Security Hardening: Create non-privileged user and switch
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup --no-create-home appuser && \
    mkdir -p uploads/cv && \
    chown -R appuser:appgroup /app

USER appuser

EXPOSE 8004

# Health check probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8004/health || exit 1

# Run with high performance Uvicorn workers
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004", "--workers", "4"]
