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
    # Hand off to the standard postgres entrypoint with all args
    exec docker-entrypoint.sh "$@"
else
    echo "WARNING: No SSL certificates found at /pg-certs/ — SSL will be disabled"
    # Filter out ssl-related -c flags from args
    # Args come as: postgres -c shared_buffers=256MB -c ssl=on -c ssl_cert_file=... etc.
    set -- $(
        skip_next=0
        prev=""
        for arg in "$@"; do
            if [ "$skip_next" = "1" ]; then
                skip_next=0
                continue
            fi
            case "$arg" in
                -c)
                    prev="$arg"
                    ;;
                *)
                    if [ "$prev" = "-c" ]; then
                        case "$arg" in
                            ssl=*|ssl_cert_file=*|ssl_key_file=*|ssl_ca_file=*)
                                # Skip this -c and its ssl value
                                prev=""
                                continue
                                ;;
                            *)
                                printf '%s\n' "$prev"
                                printf '%s\n' "$arg"
                                prev=""
                                ;;
                        esac
                    else
                        printf '%s\n' "$arg"
                        prev=""
                    fi
                    ;;
            esac
        done
    )
    exec docker-entrypoint.sh "$@"
fi
