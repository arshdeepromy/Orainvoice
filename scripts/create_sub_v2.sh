#!/bin/bash
set -e
echo '=== Clean stale slot on primary ==='
cd ~/invoicing
docker compose -f docker-compose.yml -f docker-compose.pi.yml exec -T postgres psql -U postgres -d workshoppro -c "SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE slot_name = 'orainvoice_ha_sub' AND NOT active;" 2>&1 || true

echo ''
echo '=== Creating subscription on standby (NO timeout) ==='
ssh -o ConnectTimeout=15 -o ServerAliveInterval=5 -o ServerAliveCountMax=60 nerdy@192.168.10.87 << 'EOF'
sudo docker exec invoicing-postgres-1 bash -c 'cat > /tmp/csub.sql << EOSQL
SET statement_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
CREATE SUBSCRIPTION orainvoice_ha_sub
  CONNECTION '"'"'host=172.19.0.1 port=15432 dbname=workshoppro user=replicator password=${REPLICATOR_PASSWORD} sslmode=disable connect_timeout=30'"'"'
  PUBLICATION orainvoice_ha_pub
  WITH (copy_data = false);
EOSQL
psql -U postgres -d workshoppro -f /tmp/csub.sql 2>&1'
EOF

echo ''
echo '=== Verify ==='
sleep 5
ssh -o ConnectTimeout=15 nerdy@192.168.10.87 << 'EOF2'
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT subname, subenabled FROM pg_subscription;"
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT srsubstate, count(*) FROM pg_subscription_rel GROUP BY srsubstate;"
EOF2

echo ''
echo '=== Primary ==='
cd ~/invoicing
docker compose -f docker-compose.yml -f docker-compose.pi.yml exec -T postgres psql -U postgres -d workshoppro -c "SELECT slot_name, active FROM pg_replication_slots;"

echo 'DONE.'
