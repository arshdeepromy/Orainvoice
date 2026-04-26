#!/bin/sh
set -e

# ---------------------------------------------------------------------------
# Check if this is a standby node (skip migrations — data comes from replication).
# If ha_config doesn't exist yet (first deployment), treat as standalone and
# run migrations normally.  The 2>/dev/null || echo "standalone" handles the
# missing-table case.
# ---------------------------------------------------------------------------
ROLE=$(psql -U "$POSTGRES_USER" -h postgres -d "$POSTGRES_DB" -tAc \
  "SELECT role FROM ha_config LIMIT 1" 2>/dev/null || echo "standalone")
ROLE=$(echo "$ROLE" | tr -d '[:space:]')

# Treat empty result (table exists but no rows) as standalone
if [ -z "$ROLE" ]; then
    ROLE="standalone"
fi

if [ "$ROLE" = "standby" ]; then
    echo "==> Standby node detected — skipping migrations (data comes from replication)"
else
    echo "==> Running database migrations..."

    # Ensure alembic_version table has a wide enough version_num column.
    # Alembic defaults to VARCHAR(32) but some revision IDs exceed that.
    # Uses Python+asyncpg (already installed) since psql is not in the image.
    python -c "
import asyncio, os
async def fix():
    import asyncpg
    url = os.environ.get('DATABASE_URL', '').replace('+asyncpg', '').replace('postgresql+asyncpg', 'postgresql')
    if not url:
        url = 'postgresql://postgres:postgres@postgres:5432/workshoppro'
    try:
        conn = await asyncpg.connect(url.replace('postgresql+asyncpg://', 'postgresql://'))
        await conn.execute('CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(128) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))')
        # Widen column if table already exists with narrow column
        await conn.execute('ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)')
        await conn.close()
        print('  alembic_version table ready (VARCHAR(128))')
    except Exception as e:
        print(f'  Warning: could not pre-create alembic_version: {e}')
asyncio.run(fix())
" 2>&1 || true

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
fi

# In development, seed demo data only on first run
# The seed is idempotent but we skip it on restarts for speed.
# Use the "Reset Demo Account" button in Global Admin to reset manually.
# Skip seeding on standby nodes — data comes from replication.
if [ "$ROLE" != "standby" ] && [ "$ENVIRONMENT" = "development" ] && [ "${SKIP_DEV_SEED:-}" != "true" ]; then
    echo "==> Seeding development data (idempotent)..."
    python scripts/seed_all_dev.py || echo "  (seed skipped or already exists)"
fi

echo "==> Starting application..."
exec "$@"
