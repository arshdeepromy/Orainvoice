#!/bin/bash
# Run on PRIMARY Pi - creates subscription on standby
# Uses a SQL file to avoid psql -c wrapping in a transaction

ssh nerdy@192.168.10.87 << 'ENDREMOTE'
# Write SQL to a temp file inside the container
echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 bash -c 'cat > /tmp/create_sub.sql << EOSQL
SET statement_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
DROP SUBSCRIPTION IF EXISTS orainvoice_ha_sub;
CREATE SUBSCRIPTION orainvoice_ha_sub
  CONNECTION '"'"'host=192.168.1.90 port=5432 dbname=workshoppro user=replicator password=NoorHarleen1 sslmode=disable connect_timeout=30'"'"'
  PUBLICATION orainvoice_ha_pub;
EOSQL
psql -U postgres -d workshoppro -f /tmp/create_sub.sql'

echo "EXIT_CODE=$?"

echo W4h3guru1# | sudo -S docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "SELECT subname, subenabled FROM pg_subscription;"
ENDREMOTE
