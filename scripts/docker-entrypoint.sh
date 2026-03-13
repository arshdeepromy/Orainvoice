#!/bin/sh
set -e

echo "==> Running database migrations..."
# Retry up to 5 times with 3s delay — handles slow DB startup in orchestrated environments
MAX_RETRIES=5
RETRY_COUNT=0
until alembic upgrade head; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ "$RETRY_COUNT" -ge "$MAX_RETRIES" ]; then
        echo "  ERROR: migrations failed after $MAX_RETRIES attempts"
        exit 1
    fi
    echo "  Migration attempt $RETRY_COUNT/$MAX_RETRIES failed — retrying in 3s..."
    sleep 3
done

# In development, seed demo data only on first run
# The seed is idempotent but we skip it on restarts for speed.
# Use the "Reset Demo Account" button in Global Admin to reset manually.
if [ "$ENVIRONMENT" = "development" ] && [ "${SKIP_DEV_SEED:-}" != "true" ]; then
    echo "==> Seeding development data (idempotent)..."
    python scripts/seed_all_dev.py || echo "  (seed skipped or already exists)"
fi

echo "==> Starting application..."
exec "$@"
