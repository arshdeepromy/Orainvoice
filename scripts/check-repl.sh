#!/bin/bash
cd ~/invoicing
echo "=== Replication Slots ==="
docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT slot_name, active, restart_lsn, confirmed_flush_lsn FROM pg_replication_slots;"

echo ""
echo "=== Publication Tables ==="
docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT COUNT(*) as table_count FROM pg_publication_tables WHERE pubname = 'orainvoice_ha_pub';"

echo ""
echo "=== Active Replication Connections ==="
docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT pid, usename, application_name, client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn FROM pg_stat_replication;"
