#!/bin/bash
set -e
cd ~/invoicing

echo "=== Pulling latest ==="
git fetch origin main
git reset --hard origin/main

echo "=== Verifying SSL args in compose file ==="
grep -c "ssl=on" docker-compose.pi.yml

echo "=== Recreating postgres ==="
docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --force-recreate postgres

echo "=== Waiting for healthy ==="
sleep 10
docker exec invoicing-postgres-1 pg_isready -U postgres

echo "=== Restarting app ==="
docker compose -f docker-compose.yml -f docker-compose.pi.yml restart app

sleep 5

echo "=== SSL status ==="
docker exec invoicing-postgres-1 psql -U postgres -t -c "SHOW ssl;"

echo "=== Connection count ==="
docker exec invoicing-postgres-1 psql -U postgres -t -c "SELECT count(*) FROM pg_stat_activity;"

echo "=== Process args (checking for ssl) ==="
docker exec invoicing-postgres-1 ps -o args | head -2
