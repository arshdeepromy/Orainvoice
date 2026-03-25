#!/bin/bash
# Run on PRIMARY Pi
# 1. Clean up standby: kill stuck psql, drop partial subscription
# 2. Create subscription with sslmode=disable and connect_timeout

ssh nerdy@192.168.10.87 << 'ENDREMOTE'
# Kill any stuck psql processes
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 bash -c "
# Kill stuck CREATE SUBSCRIPTION backends
psql -U postgres -d workshoppro -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE query LIKE '%CREATE SUBSCRIPTION%' AND pid != pg_backend_pid();\"
"

# Wait for cleanup
sleep 2

# Now create the subscription using a SQL file (avoids transaction wrapping)
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 bash -c "
cat > /tmp/sub.sql << 'SQLEOF'
SET statement_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
DROP SUBSCRIPTION IF EXISTS orainvoice_ha_sub;
CREATE SUBSCRIPTION orainvoice_ha_sub
  CONNECTION 'host=192.168.1.90 port=5432 dbname=workshoppro user=replicator password=NoorHarleen1 sslmode=disable connect_timeout=30'
  PUBLICATION orainvoice_ha_pub;
SQLEOF
timeout 90 psql -U postgres -d workshoppro -f /tmp/sub.sql 2>&1
echo PSQL_EXIT=\$?
"

# Check result
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT subname, subenabled FROM pg_subscription;"
ENDREMOTE
