# Multi-platform support: works on both ARM64 (Apple Silicon) and AMD64 (x86_64)
FROM python:3.11-slim

# WeasyPrint system dependencies (compatible with both architectures)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libcairo2 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip setuptools && pip install --no-cache-dir .

COPY . .

# Build metadata — injected by update script or CI
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
ENV GIT_SHA=$GIT_SHA
ENV BUILD_DATE=$BUILD_DATE

# Entrypoint runs migrations + optional dev seeding before starting the app
COPY scripts/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "4", "--bind", "0.0.0.0:8000", "--timeout", "120", "--graceful-timeout", "30", "--keep-alive", "5", "--max-requests", "10000", "--max-requests-jitter", "1000", "--access-logfile", "-", "--error-logfile", "-"]
