#!/bin/bash
# Deploy pool size fix + SSL fix to Pi primary
set -e

cd ~/invoicing

echo "=== Pulling latest code ==="
git fetch origin main
git reset --hard origin/main

echo "=== Recreating postgres container (to pick up SSL args) ==="
docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --force-recreate postgres

echo "=== Waiting for postgres to be healthy ==="
sleep 10
docker exec invoicing-postgres-1 pg_isready -U postgres

echo "=== Restarting app (to pick up pool size env vars) ==="
docker compose -f docker-compose.yml -f docker-compose.pi.yml restart app

echo "=== Waiting for app to start ==="
sleep 5

echo "=== Checking SSL status ==="
docker exec invoicing-postgres-1 psql -U postgres -t -c "SHOW ssl;"

echo "=== Checking connection count ==="
docker exec invoicing-postgres-1 psql -U postgres -t -c "SELECT count(*) FROM pg_stat_activity;"

echo "=== Done ==="
