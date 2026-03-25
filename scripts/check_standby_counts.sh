#!/bin/bash
# Run on PRIMARY Pi - check row counts on standby
ssh nerdy@192.168.10.87 << 'EOF'
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "
SELECT 'organisations' as tbl, count(*) as cnt FROM organisations
UNION ALL SELECT 'users', count(*) FROM users
UNION ALL SELECT 'invoices', count(*) FROM invoices
UNION ALL SELECT 'customers', count(*) FROM customers
UNION ALL SELECT 'line_items', count(*) FROM line_items
UNION ALL SELECT 'payments', count(*) FROM payments
UNION ALL SELECT 'org_vehicles', count(*) FROM org_vehicles
ORDER BY tbl;
"
EOF
