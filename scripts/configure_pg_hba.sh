#!/bin/bash
# Adds IP-restricted replication rule to pg_hba.conf inside the Docker container.
# This restricts the replicator user to only connect from the specified peer IP,
# enforcing SSL (hostssl) and scram-sha-256 authentication.
#
# Usage: bash scripts/configure_pg_hba.sh <container_name> <peer_ip>
#
# Examples:
#   bash scripts/configure_pg_hba.sh invoicing-postgres-1 192.168.1.91
#   bash scripts/configure_pg_hba.sh invoicing-standby-postgres-1 192.168.1.90
#
# Prerequisites:
#   - Docker is installed and the target postgres container is running
#   - SSL certificates are configured (see docs/HA_REPLICATION_GUIDE.md)
#   - The replicator user has been created (see Replication User Management)
set -e

CONTAINER="${1:?Usage: $0 <container_name> <peer_ip>}"
PEER_IP="${2:?Usage: $0 <container_name> <peer_ip>}"

docker exec "$CONTAINER" bash -c "
  echo 'hostssl replication replicator ${PEER_IP}/32 scram-sha-256' >> /var/lib/postgresql/data/pg_hba.conf
  echo 'hostssl all replicator ${PEER_IP}/32 scram-sha-256' >> /var/lib/postgresql/data/pg_hba.conf
"
docker exec "$CONTAINER" psql -U postgres -c "SELECT pg_reload_conf()"
echo "pg_hba.conf updated and reloaded for peer IP: ${PEER_IP}"
