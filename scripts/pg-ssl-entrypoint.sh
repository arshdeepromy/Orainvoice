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
    # Remove ssl-related flags from args so postgres starts without SSL
    FILTERED_ARGS=""
    SKIP_NEXT=0
    for arg in "$@"; do
        if [ "$SKIP_NEXT" = "1" ]; then
            SKIP_NEXT=0
            continue
        fi
        case "$arg" in
            ssl=on|ssl_cert_file=*|ssl_key_file=*|ssl_ca_file=*)
                continue
                ;;
            -c)
                # Peek at next arg — we need to check if it's an ssl flag
                FILTERED_ARGS="$FILTERED_ARGS $arg"
                ;;
            *)
                # Check if previous was -c and this is an ssl param
                if echo "$FILTERED_ARGS" | grep -q ' -c$'; then
                    case "$arg" in
                        ssl=on|ssl_cert_file=*|ssl_key_file=*|ssl_ca_file=*)
                            # Remove the trailing -c we just added
                            FILTERED_ARGS=$(echo "$FILTERED_ARGS" | sed 's/ -c$//')
                            continue
                            ;;
                    esac
                fi
                FILTERED_ARGS="$FILTERED_ARGS $arg"
                ;;
        esac
    done
    exec docker-entrypoint.sh $FILTERED_ARGS
    exit 0
fi

# Hand off to the standard postgres entrypoint
exec docker-entrypoint.sh "$@"
