#!/bin/bash
# ============================================================================
# check_repl_status.sh — Check HA replication status on primary and standby
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

echo "=== PRIMARY: replication slots ==="
cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml exec -T postgres psql -U postgres -d workshoppro -c "SELECT slot_name, active, active_pid FROM pg_replication_slots;"

echo "=== PRIMARY: stat_replication ==="
cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml exec -T postgres psql -U postgres -d workshoppro -c "SELECT pid, usename, application_name, client_addr, state FROM pg_stat_replication;"

echo "=== PRIMARY: row counts ==="
cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml exec -T postgres psql -U postgres -d workshoppro -c "
SELECT 'organisations' as tbl, count(*) as cnt FROM organisations
UNION ALL SELECT 'users', count(*) FROM users
UNION ALL SELECT 'invoices', count(*) FROM invoices
UNION ALL SELECT 'customers', count(*) FROM customers
ORDER BY tbl;"

echo "=== STANDBY: subscription status ==="
ssh nerdy@192.168.10.87 << 'EOF'
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT subname, subenabled FROM pg_subscription;"
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT * FROM pg_stat_subscription;"
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT srsubid, srrelid::regclass, srsublsn, srsubstate FROM pg_subscription_rel LIMIT 20;"
EOF

echo "=== STANDBY: row counts ==="
ssh nerdy@192.168.10.87 << 'EOF2'
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "
SELECT 'organisations' as tbl, count(*) as cnt FROM organisations
UNION ALL SELECT 'users', count(*) FROM users
UNION ALL SELECT 'invoices', count(*) FROM invoices
UNION ALL SELECT 'customers', count(*) FROM customers
ORDER BY tbl;"
EOF2
