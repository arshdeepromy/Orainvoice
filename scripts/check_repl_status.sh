#!/bin/bash
# Run on PRIMARY Pi - check replication status on both sides

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
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT subname, subenabled FROM pg_subscription;"
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT * FROM pg_stat_subscription;"
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT srsubid, srrelid::regclass, srsublsn, srsubstate FROM pg_subscription_rel LIMIT 20;"
EOF

echo "=== STANDBY: row counts ==="
ssh nerdy@192.168.10.87 << 'EOF2'
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "
SELECT 'organisations' as tbl, count(*) as cnt FROM organisations
UNION ALL SELECT 'users', count(*) FROM users
UNION ALL SELECT 'invoices', count(*) FROM invoices
UNION ALL SELECT 'customers', count(*) FROM customers
ORDER BY tbl;"
EOF2
