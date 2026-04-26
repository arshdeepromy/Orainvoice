#!/bin/bash
set -e

echo '=== Step 1: Drop old subscription on standby ==='
ssh -o ConnectTimeout=15 -o ServerAliveInterval=5 nerdy@192.168.10.87 << 'EOF'
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "ALTER SUBSCRIPTION orainvoice_ha_sub DISABLE;" 2>&1 || true
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "ALTER SUBSCRIPTION orainvoice_ha_sub SET (slot_name = NONE);" 2>&1 || true
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "DROP SUBSCRIPTION IF EXISTS orainvoice_ha_sub;" 2>&1
EOF
echo 'Done.'

echo ''
echo '=== Step 2: Drop stale replication slot on primary ==='
cd ~/invoicing
docker compose -f docker-compose.yml -f docker-compose.pi.yml exec -T postgres psql -U postgres -d workshoppro -c "SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE slot_name = 'orainvoice_ha_sub' AND NOT active;" 2>&1 || true
echo 'Done.'

echo ''
echo '=== Step 3: Create subscription with direct IP (192.168.1.90:5432) ==='
ssh -o ConnectTimeout=15 -o ServerAliveInterval=5 -o ServerAliveCountMax=60 nerdy@192.168.10.87 << 'EOFCREATE'
sudo docker exec invoicing-postgres-1 bash -c 'cat > /tmp/csub_direct.sql << EOSQL
SET statement_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
CREATE SUBSCRIPTION orainvoice_ha_sub
  CONNECTION '"'"'host=192.168.1.90 port=5432 dbname=workshoppro user=replicator password=${REPLICATOR_PASSWORD} sslmode=disable connect_timeout=30'"'"'
  PUBLICATION orainvoice_ha_pub
  WITH (copy_data = false);
EOSQL
psql -U postgres -d workshoppro -f /tmp/csub_direct.sql 2>&1'
EOFCREATE
echo 'Done.'

echo ''
echo '=== Step 4: Wait and verify ==='
sleep 10
ssh -o ConnectTimeout=15 nerdy@192.168.10.87 << 'EOFV'
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT subname, subenabled FROM pg_subscription;"
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT srsubstate, count(*) FROM pg_subscription_rel GROUP BY srsubstate;"
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT subname, pid, received_lsn, latest_end_lsn, last_msg_send_time FROM pg_stat_subscription;"
EOFV

echo ''
echo '=== Step 5: Check primary ==='
cd ~/invoicing
docker compose -f docker-compose.yml -f docker-compose.pi.yml exec -T postgres psql -U postgres -d workshoppro -c "SELECT slot_name, active FROM pg_replication_slots;"
docker compose -f docker-compose.yml -f docker-compose.pi.yml exec -T postgres psql -U postgres -d workshoppro -c "SELECT pid, usename, application_name, client_addr, state FROM pg_stat_replication;"

echo 'ALL DONE.'
