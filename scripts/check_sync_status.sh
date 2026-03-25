#!/bin/bash
# Run on PRIMARY Pi - check table sync status on standby
ssh nerdy@192.168.10.87 << 'EOF'
echo "=== Subscription rel states ==="
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT srsubstate, count(*) FROM pg_subscription_rel GROUP BY srsubstate;"

echo "=== Recent postgres logs (last 30 lines) ==="
echo W4h3guru1# | sudo -S docker logs invoicing-postgres-1 --tail=30 2>&1

echo "=== Subscription worker processes ==="
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT pid, backend_type, state, wait_event_type, wait_event FROM pg_stat_activity WHERE backend_type LIKE '%logical%' OR backend_type LIKE '%tablesync%';"

echo "=== max_sync_workers_per_subscription ==="
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SHOW max_sync_workers_per_subscription;"
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SHOW max_logical_replication_workers;"
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SHOW max_worker_processes;"
EOF
