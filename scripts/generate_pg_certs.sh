#!/bin/bash
# =============================================================================
# Generate self-signed SSL certificates for PostgreSQL HA replication
#
# Creates a private CA, then generates server certificates for primary
# and standby nodes.  All certs are placed in ./certs/pg/ which is
# mounted into the postgres containers via docker compose.
#
# Usage:
#   bash scripts/generate_pg_certs.sh
#
# Output structure:
#   certs/pg/
#     ca.crt              — CA certificate (shared between nodes)
#     ca.key              — CA private key (keep secure, not deployed)
#     primary/
#       server.crt        — Primary server certificate
#       server.key        — Primary server private key
#     standby/
#       server.crt        — Standby server certificate
#       server.key        — Standby server private key
# =============================================================================

set -euo pipefail

CERT_DIR="certs/pg"
CA_SUBJ="/CN=OraInvoice-HA-CA/O=OraInvoice/C=NZ"
DAYS_VALID=3650  # 10 years for dev; use shorter for production

echo "=== Generating PostgreSQL SSL certificates ==="

# Clean previous certs
rm -rf "$CERT_DIR"
mkdir -p "$CERT_DIR/primary" "$CERT_DIR/standby"

# --- 1. Generate CA ---
echo "[1/5] Generating CA key and certificate..."
openssl genrsa -out "$CERT_DIR/ca.key" 4096 2>/dev/null
openssl req -new -x509 -days "$DAYS_VALID" \
  -key "$CERT_DIR/ca.key" \
  -out "$CERT_DIR/ca.crt" \
  -subj "$CA_SUBJ" 2>/dev/null

# --- 2. Generate Primary server cert ---
echo "[2/5] Generating primary server key and CSR..."
openssl genrsa -out "$CERT_DIR/primary/server.key" 2048 2>/dev/null
openssl req -new \
  -key "$CERT_DIR/primary/server.key" \
  -out "$CERT_DIR/primary/server.csr" \
  -subj "/CN=primary-postgres/O=OraInvoice/C=NZ" 2>/dev/null

echo "[3/5] Signing primary server certificate with CA..."

# Create SAN extension file for primary (allows connections via multiple hostnames)
# Includes the primary Pi LAN IP for HA replication over VPN
cat > "$CERT_DIR/primary/san.cnf" <<EOF
[v3_req]
subjectAltName = DNS:postgres,DNS:localhost,DNS:primary-postgres,IP:127.0.0.1,IP:192.168.1.90
EOF

openssl x509 -req -days "$DAYS_VALID" \
  -in "$CERT_DIR/primary/server.csr" \
  -CA "$CERT_DIR/ca.crt" \
  -CAkey "$CERT_DIR/ca.key" \
  -CAcreateserial \
  -out "$CERT_DIR/primary/server.crt" \
  -extfile "$CERT_DIR/primary/san.cnf" \
  -extensions v3_req 2>/dev/null

# --- 3. Generate Standby server cert ---
echo "[4/5] Generating standby server key and CSR..."
openssl genrsa -out "$CERT_DIR/standby/server.key" 2048 2>/dev/null
openssl req -new \
  -key "$CERT_DIR/standby/server.key" \
  -out "$CERT_DIR/standby/server.csr" \
  -subj "/CN=standby-postgres/O=OraInvoice/C=NZ" 2>/dev/null

# Create SAN extension file for standby
# Includes the standby Pi LAN IP for HA replication over VPN
cat > "$CERT_DIR/standby/san.cnf" <<EOF
[v3_req]
subjectAltName = DNS:postgres,DNS:localhost,DNS:standby-postgres,IP:127.0.0.1,IP:192.168.10.87
EOF

openssl x509 -req -days "$DAYS_VALID" \
  -in "$CERT_DIR/standby/server.csr" \
  -CA "$CERT_DIR/ca.crt" \
  -CAkey "$CERT_DIR/ca.key" \
  -CAcreateserial \
  -out "$CERT_DIR/standby/server.crt" \
  -extfile "$CERT_DIR/standby/san.cnf" \
  -extensions v3_req 2>/dev/null

# --- 4. Set permissions (PostgreSQL requires key files to be 0600) ---
echo "[5/5] Setting file permissions..."
chmod 600 "$CERT_DIR/ca.key"
chmod 600 "$CERT_DIR/primary/server.key"
chmod 600 "$CERT_DIR/standby/server.key"
chmod 644 "$CERT_DIR/ca.crt"
chmod 644 "$CERT_DIR/primary/server.crt"
chmod 644 "$CERT_DIR/standby/server.crt"

# Clean up CSR and temp files
rm -f "$CERT_DIR/primary/server.csr" "$CERT_DIR/primary/san.cnf"
rm -f "$CERT_DIR/standby/server.csr" "$CERT_DIR/standby/san.cnf"
rm -f "$CERT_DIR/ca.srl"

echo ""
echo "=== SSL certificates generated successfully ==="
echo ""
echo "  CA cert:       $CERT_DIR/ca.crt"
echo "  Primary cert:  $CERT_DIR/primary/server.crt"
echo "  Primary key:   $CERT_DIR/primary/server.key"
echo "  Standby cert:  $CERT_DIR/standby/server.crt"
echo "  Standby key:   $CERT_DIR/standby/server.key"
echo ""
echo "Next steps:"
echo "  1. Rebuild containers: docker compose up --build -d"
echo "  2. Update peer DB settings in HA admin UI to use sslmode=require"
echo "  3. For production, use sslmode=verify-ca and distribute ca.crt"
