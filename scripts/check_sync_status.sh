#!/bin/bash
# ============================================================================
# check_sync_status.sh — Check table sync status on the standby
# ============================================================================
# Prerequisites:
# - SSH key auth configured to the standby (nerdy@192.168.10.87)
# - Sudoers configured with NOPASSWD for docker commands on the standby
# - Run from the PRIMARY Pi
#
# IMPORTANT: Leaked credentials were removed from this script (BUG-HA-03).
# Ensure the sudo password and replicator DB password have been rotated
# on production if they were previously committed to version control.
# ============================================================================

ssh nerdy@192.168.10.87 << 'EOF'
echo "=== Subscription rel states ==="
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT srsubstate, count(*) FROM pg_subscription_rel GROUP BY srsubstate;"

echo "=== Recent postgres logs (last 30 lines) ==="
sudo docker logs invoicing-postgres-1 --tail=30 2>&1

echo "=== Subscription worker processes ==="
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT pid, backend_type, state, wait_event_type, wait_event FROM pg_stat_activity WHERE backend_type LIKE '%logical%' OR backend_type LIKE '%tablesync%';"

echo "=== max_sync_workers_per_subscription ==="
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SHOW max_sync_workers_per_subscription;"
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SHOW max_logical_replication_workers;"
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SHOW max_worker_processes;"
EOF
