#!/bin/sh
set -e

# ---------------------------------------------------------------------------
# Check if this is a standby node (skip migrations — data comes from replication).
# If ha_config doesn't exist yet (first deployment), treat as standalone and
# run migrations normally.  Uses Python+asyncpg (already installed) since psql
# is not available in the python:3.11-slim image.
# ---------------------------------------------------------------------------
ROLE=$(python -c "
import asyncio, os
async def detect():
    import asyncpg
    url = os.environ.get('DATABASE_URL','').replace('+asyncpg','').replace('postgresql+asyncpg','postgresql')
    if not url: url = 'postgresql://postgres:postgres@postgres:5432/workshoppro'
    try:
        conn = await asyncpg.connect(url.replace('postgresql+asyncpg://','postgresql://'), timeout=5)
        role = await conn.fetchval('SELECT role FROM ha_config LIMIT 1')
        await conn.close()
        print(role or 'standalone')
    except Exception:
        print('standalone')
asyncio.run(detect())
" 2>/dev/null || echo "standalone")
ROLE=$(echo "$ROLE" | tr -d '[:space:]')

# Treat empty result (table exists but no rows) as standalone
if [ -z "$ROLE" ]; then
    ROLE="standalone"
fi

# ---------------------------------------------------------------------------
# SSH keypair auto-generation (for rsync-based volume sync between HA nodes)
# ---------------------------------------------------------------------------
if [ ! -f /ha_keys/id_ed25519 ]; then
    ssh-keygen -t ed25519 -f /ha_keys/id_ed25519 -N "" -q
    echo "  SSH keypair generated at /ha_keys/"
fi
chmod 600 /ha_keys/id_ed25519
chmod 644 /ha_keys/id_ed25519.pub
[ -f /ha_keys/authorized_keys ] || touch /ha_keys/authorized_keys
chmod 600 /ha_keys/authorized_keys

# ---------------------------------------------------------------------------
# Host LAN IP auto-detection (used by HA wizard trust handshake)
# ---------------------------------------------------------------------------
if [ -n "$HA_LOCAL_LAN_IP" ]; then
    HOST_LAN_IP="$HA_LOCAL_LAN_IP"
else
    # Inside a Docker bridge container, we can only see the Docker gateway IP
    # (172.x.x.x), not the host's actual LAN IP.  For cross-machine HA, set
    # HA_LOCAL_LAN_IP in the environment or .env file.
    HOST_LAN_IP=$(ip route 2>/dev/null | awk '/default/ {print $3}')
    if [ -z "$HOST_LAN_IP" ]; then
        HOST_LAN_IP="127.0.0.1"
        echo "  WARNING: Could not detect host LAN IP, falling back to 127.0.0.1"
    fi
    echo "  NOTE: Auto-detected Docker gateway IP ($HOST_LAN_IP). For cross-machine HA, set HA_LOCAL_LAN_IP in your environment."
fi
echo "$HOST_LAN_IP" > /tmp/host_lan_ip
echo "  Host LAN IP: $HOST_LAN_IP"

# ---------------------------------------------------------------------------
# Start sshd on port 2222 (for rsync volume sync from peer node)
# ---------------------------------------------------------------------------
cat > /etc/ssh/sshd_config.d/ha.conf <<EOF
Port 2222
AuthorizedKeysFile /ha_keys/authorized_keys
PasswordAuthentication no
PubkeyAuthentication yes
PermitRootLogin prohibit-password
EOF
/usr/sbin/sshd 2>/dev/null || echo "  WARNING: sshd failed to start (non-fatal)"

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
