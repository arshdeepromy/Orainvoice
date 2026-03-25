#!/bin/bash
# Run on PRIMARY Pi to debug SSL connection from standby container
ssh nerdy@192.168.10.87 << 'EOF'
echo "=== Try psql with sslmode=disable ==="
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 bash -c 'timeout 10 psql "host=192.168.1.90 port=5432 dbname=workshoppro user=replicator password=NoorHarleen1 sslmode=disable connect_timeout=5" -c "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()" 2>&1'
echo "=== Try psql with sslmode=prefer ==="
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 bash -c 'timeout 10 psql "host=192.168.1.90 port=5432 dbname=workshoppro user=replicator password=NoorHarleen1 sslmode=prefer connect_timeout=5" -c "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()" 2>&1'
echo "=== Try psql with sslmode=require ==="
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 bash -c 'timeout 10 psql "host=192.168.1.90 port=5432 dbname=workshoppro user=replicator password=NoorHarleen1 sslmode=require connect_timeout=5" -c "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()" 2>&1'
EOF
