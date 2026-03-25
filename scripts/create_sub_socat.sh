#!/bin/bash
set -e
echo '=== Clean stale slot on primary ==='
cd ~/invoicing
docker compose -f docker-compose.yml -f docker-compose.pi.yml exec -T postgres psql -U postgres -d workshoppro -c "SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE slot_name = 'orainvoice_ha_sub' AND NOT active;" 2>&1 || true

echo ''
echo '=== Creating subscription on standby via socat (172.19.0.1:15432) ==='
ssh -o ConnectTimeout=15 -o ServerAliveInterval=5 -o ServerAliveCountMax=30 nerdy@192.168.10.87 << 'EOF'
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 bash -c 'cat > /tmp/csub.sql << EOSQL
SET statement_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
CREATE SUBSCRIPTION orainvoice_ha_sub
  CONNECTION '"'"'host=172.19.0.1 port=15432 dbname=workshoppro user=replicator password=NoorHarleen1 sslmode=disable connect_timeout=30'"'"'
  PUBLICATION orainvoice_ha_pub
  WITH (copy_data = false);
EOSQL
timeout 120 psql -U postgres -d workshoppro -f /tmp/csub.sql 2>&1'
EOF

echo ''
echo '=== Verify subscription ==='
ssh -o ConnectTimeout=15 nerdy@192.168.10.87 << 'EOF2'
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT subname, subenabled FROM pg_subscription;"
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT srsubstate, count(*) FROM pg_subscription_rel GROUP BY srsubstate;"
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT subname, pid, received_lsn, latest_end_lsn, last_msg_send_time FROM pg_stat_subscription;"
EOF2

echo ''
echo '=== Primary status ==='
cd ~/invoicing
docker compose -f docker-compose.yml -f docker-compose.pi.yml exec -T postgres psql -U postgres -d workshoppro -c "SELECT slot_name, active FROM pg_replication_slots;"
docker compose -f docker-compose.yml -f docker-compose.pi.yml exec -T postgres psql -U postgres -d workshoppro -c "SELECT pid, usename, client_addr, state FROM pg_stat_replication;"

echo 'DONE.'
