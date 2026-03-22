#!/bin/sh
# Copy SSL certs to a location owned by postgres and fix permissions.
# PostgreSQL requires the key file to be owned by the postgres user
# and have mode 0600.  Docker volume mounts from Windows don't preserve
# Unix permissions, so we copy them at container startup.

set -e

SSL_DIR="/var/lib/postgresql/ssl"
mkdir -p "$SSL_DIR"

# Copy certs if they exist (mounted at /pg-certs/)
if [ -f /pg-certs/server.crt ]; then
    cp /pg-certs/server.crt "$SSL_DIR/server.crt"
    cp /pg-certs/server.key "$SSL_DIR/server.key"
    cp /pg-certs/ca.crt "$SSL_DIR/ca.crt"
    chmod 600 "$SSL_DIR/server.key"
    chmod 644 "$SSL_DIR/server.crt" "$SSL_DIR/ca.crt"
    chown postgres:postgres "$SSL_DIR"/*
    echo "SSL certificates installed at $SSL_DIR"
else
    echo "WARNING: No SSL certificates found at /pg-certs/ — SSL will be disabled"
    # Remove ssl flags from args if no certs
    exec docker-entrypoint.sh "$@"
    exit 0
fi

# Hand off to the standard postgres entrypoint
exec docker-entrypoint.sh "$@"
