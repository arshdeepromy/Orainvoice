#!/bin/bash
# Run on PRIMARY Pi - tests TCP from standby HOST (not container) to primary
ssh nerdy@192.168.10.87 << 'EOF'
echo "=== Host TCP test to 192.168.1.90:5432 ==="
timeout 5 bash -c 'echo > /dev/tcp/192.168.1.90/5432' 2>&1 && echo HOST_TCP_OK || echo HOST_TCP_FAIL
echo "=== Host psql test ==="
PGPASSWORD=NoorHarleen1 timeout 10 psql -h 192.168.1.90 -p 5432 -U replicator -d workshoppro -c "SELECT 1 as test" 2>&1 || echo PSQL_FAILED
EOF
