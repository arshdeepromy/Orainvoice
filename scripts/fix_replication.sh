#!/bin/bash
# ============================================================================
# fix_replication.sh — Drop and recreate HA replication subscription
# ============================================================================
# Prerequisites:
# - SSH key auth configured to the standby (nerdy@192.168.10.87)
# - Sudoers configured with NOPASSWD for docker commands on the standby
# - HA_PEER_DB_URL environment variable set with the replication connection string
#   e.g. export HA_PEER_DB_URL='host=192.168.1.90 port=5432 dbname=workshoppro user=replicator password=<secret> sslmode=disable connect_timeout=60'
# - Run from the PRIMARY Pi
#
# IMPORTANT: Leaked credentials were removed from this script (BUG-HA-03).
# Ensure the sudo password and replicator DB password have been rotated
# on production if they were previously committed to version control.
# ============================================================================

set -e

if [ -z "${HA_PEER_DB_URL}" ]; then
  echo "ERROR: HA_PEER_DB_URL environment variable is not set."
  echo "Set it to the full replication connection string, e.g.:"
  echo "  export HA_PEER_DB_URL='host=192.168.1.90 port=5432 dbname=workshoppro user=replicator password=<secret> sslmode=disable connect_timeout=60'"
  exit 1
fi

cd ~/invoicing
DC="docker compose -f docker-compose.yml -f docker-compose.pi.yml"

echo "=== STEP 1: Drop subscription on STANDBY ==="
ssh -o ConnectTimeout=15 -o ServerAliveInterval=5 nerdy@192.168.10.87 << 'EOF'
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "ALTER SUBSCRIPTION orainvoice_ha_sub DISABLE;" 2>&1 || true
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "ALTER SUBSCRIPTION orainvoice_ha_sub SET (slot_name = NONE);" 2>&1 || true
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "DROP SUBSCRIPTION IF EXISTS orainvoice_ha_sub;" 2>&1
EOF
echo "Done step 1."

echo ""
echo "=== STEP 2: Drop replication slot on PRIMARY ==="
$DC exec -T postgres psql -U postgres -d workshoppro << 'EOSQL'
SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE slot_name = 'orainvoice_ha_sub';
EOSQL
echo "Done step 2."

echo ""
echo "=== STEP 3: Verify publication on PRIMARY ==="
$DC exec -T postgres psql -U postgres -d workshoppro -c "SELECT pubname FROM pg_publication WHERE pubname = 'orainvoice_ha_pub';"

echo ""
echo "=== STEP 4: Verify data on STANDBY ==="
ssh -o ConnectTimeout=15 nerdy@192.168.10.87 << 'EOF2'
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT 'orgs' as t, count(*) FROM organisations UNION ALL SELECT 'users', count(*) FROM users UNION ALL SELECT 'invoices', count(*) FROM invoices UNION ALL SELECT 'customers', count(*) FROM customers ORDER BY t;"
EOF2

echo ""
echo "=== STEP 5: Confirm clean state ==="
ssh -o ConnectTimeout=15 nerdy@192.168.10.87 << 'EOF3'
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT subname FROM pg_subscription;"
EOF3
$DC exec -T postgres psql -U postgres -d workshoppro -c "SELECT slot_name, active FROM pg_replication_slots;"

echo ""
echo "=== STEP 6: Create subscription with copy_data=false ==="
ssh -o ConnectTimeout=15 -o ServerAliveInterval=5 -o ServerAliveCountMax=6 nerdy@192.168.10.87 << EOFCREATE
sudo docker exec invoicing-postgres-1 bash -c 'cat > /tmp/csub.sql << EOSQL
SET statement_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
CREATE SUBSCRIPTION orainvoice_ha_sub
  CONNECTION '"'"'${HA_PEER_DB_URL}'"'"'
  PUBLICATION orainvoice_ha_pub
  WITH (copy_data = false);
EOSQL
timeout 180 psql -U postgres -d workshoppro -f /tmp/csub.sql 2>&1'
EOFCREATE
echo "Done step 6."

echo ""
echo "=== STEP 7: Wait 10s then verify ==="
sleep 10
ssh -o ConnectTimeout=15 nerdy@192.168.10.87 << 'EOFV'
echo "--- Subscription ---"
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT subname, subenabled FROM pg_subscription;"
echo "--- Table states ---"
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT srsubstate, count(*) FROM pg_subscription_rel GROUP BY srsubstate;"
echo "--- Stat subscription ---"
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT subname, pid, received_lsn, latest_end_lsn, last_msg_send_time FROM pg_stat_subscription;"
EOFV

echo ""
echo "=== STEP 8: PRIMARY replication status ==="
$DC exec -T postgres psql -U postgres -d workshoppro -c "SELECT slot_name, active, active_pid FROM pg_replication_slots;"
$DC exec -T postgres psql -U postgres -d workshoppro -c "SELECT pid, usename, application_name, client_addr, state FROM pg_stat_replication;"

echo ""
echo "ALL DONE."
