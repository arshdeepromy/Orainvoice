#!/bin/bash
# Run on PRIMARY Pi to debug standby container networking
ssh nerdy@192.168.10.87 << 'EOF'
echo "=== Container network info ==="
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 bash -c 'ip route show default 2>/dev/null || cat /proc/net/route | head -5'
echo "=== Ping primary from container ==="
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 bash -c 'timeout 3 ping -c 1 192.168.1.90 2>&1 || echo PING_FAILED'
echo "=== Try psql from container to primary ==="
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 bash -c 'timeout 10 psql "host=192.168.1.90 port=5432 dbname=workshoppro user=replicator password=NoorHarleen1 sslmode=disable connect_timeout=5" -c "SELECT 1" 2>&1 || echo PSQL_FAILED'
EOF
