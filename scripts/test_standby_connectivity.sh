#!/bin/bash
# Run this on the PRIMARY Pi to test standby postgres container connectivity to primary
# Usage: bash scripts/test_standby_connectivity.sh

ssh nerdy@192.168.10.87 << 'EOF'
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 pg_isready -h 192.168.1.90 -p 5432 -U replicator -d workshoppro -t 10
EOF
