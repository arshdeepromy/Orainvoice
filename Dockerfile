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
    openssh-server \
    rsync \
    iproute2 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd

# PostgreSQL 16 client tools (pg_dump / pg_restore) for the Cloud Backup &
# Restore pipeline, which shells out to `pg_dump -Fc` / `pg_restore`. The client
# major version MUST be >= the server (PostgreSQL 16) — pg_dump refuses to dump a
# server newer than itself — so install postgresql-client-16 from the official
# PGDG apt repository (Debian's default repo ships an older client).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-16 \
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

# Default web-process concurrency. Override per environment via the
# WEB_CONCURRENCY env var (compose files set this for Pi/standby).
# PERFORMANCE_AUDIT.md §1 quick win #9 / §B-M7 / §B-L4.
ENV WEB_CONCURRENCY=2

ENTRYPOINT ["/docker-entrypoint.sh"]
# --preload: import the app once in the master process, then fork workers.
#   3x faster startup and shared in-memory state across forks. Safe because
#   redis_pool, the SQLAlchemy engine, and config are fork-safe.
# --workers $(WEB_CONCURRENCY): controlled per environment, no longer pinned at 4.
CMD ["sh", "-c", "exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker --preload --workers ${WEB_CONCURRENCY:-2} --bind 0.0.0.0:8000 --timeout 120 --graceful-timeout 30 --keep-alive 5 --max-requests 10000 --max-requests-jitter 1000 --access-logfile - --error-logfile -"]
