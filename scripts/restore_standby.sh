#!/bin/bash
# Run on PRIMARY Pi
# 1. SCP dump to standby
# 2. Drop subscription on standby
# 3. Truncate all tables on standby (except ha_config and alembic_version)
# 4. Restore dump with triggers disabled
# 5. Create subscription with copy_data=false

set -e

echo "=== Step 1: SCP dump to standby ==="
scp -o ConnectTimeout=10 /tmp/workshoppro_data.sql nerdy@192.168.10.87:/tmp/workshoppro_data.sql
echo "SCP done"

echo "=== Step 2-5: Drop sub, truncate, restore, create sub ==="
ssh -o ConnectTimeout=10 nerdy@192.168.10.87 << 'EOF'
# Copy dump into container
sudo docker cp /tmp/workshoppro_data.sql invoicing-postgres-1:/tmp/workshoppro_data.sql

# Drop subscription
sudo docker exec invoicing-postgres-1 bash -c 'cat > /tmp/setup_repl.sql << SQLEOF
SET statement_timeout = 0;
SET idle_in_transaction_session_timeout = 0;

-- Drop existing subscription
DROP SUBSCRIPTION IF EXISTS orainvoice_ha_sub;

-- Truncate all tables except ha_config and alembic_version
DO \$\$
DECLARE
    r RECORD;
BEGIN
    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = '\''public'\'' AND tablename NOT IN ('\''ha_config'\'', '\''alembic_version'\'') LOOP
        EXECUTE '\''TRUNCATE TABLE '\'' || quote_ident(r.tablename) || '\'' CASCADE'\'';
    END LOOP;
END
\$\$;

SQLEOF
psql -U postgres -d workshoppro -f /tmp/setup_repl.sql'

echo "=== Truncate done, restoring data ==="

# Restore dump with session_replication_role=replica to disable triggers/FK checks
sudo docker exec invoicing-postgres-1 bash -c 'psql -U postgres -d workshoppro -c "SET session_replication_role = replica;" -f /tmp/workshoppro_data.sql 2>&1 | tail -5'

echo "=== Data restored, creating subscription ==="

# Create subscription with copy_data=false
sudo docker exec invoicing-postgres-1 bash -c 'cat > /tmp/create_sub_nocopy.sql << SQLEOF
SET statement_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
CREATE SUBSCRIPTION orainvoice_ha_sub
  CONNECTION '\''host=192.168.1.90 port=5432 dbname=workshoppro user=replicator password=${REPLICATOR_PASSWORD} sslmode=disable connect_timeout=30'\''
  PUBLICATION orainvoice_ha_pub
  WITH (copy_data = false);
SQLEOF
timeout 120 psql -U postgres -d workshoppro -f /tmp/create_sub_nocopy.sql 2>&1'

echo "=== Verifying ==="
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT subname, subenabled FROM pg_subscription;"
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT srsubstate, count(*) FROM pg_subscription_rel GROUP BY srsubstate;"
sudo docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "
SELECT 'organisations' as tbl, count(*) as cnt FROM organisations
UNION ALL SELECT 'users', count(*) FROM users
UNION ALL SELECT 'invoices', count(*) FROM invoices
UNION ALL SELECT 'customers', count(*) FROM customers
ORDER BY tbl;"
EOF
