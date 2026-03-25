#!/bin/bash
set -e
cd ~/invoicing

# Pull latest
git fetch origin main
git reset --hard origin/main

# Rebuild app and frontend images, then restart
docker compose -f docker-compose.yml -f docker-compose.pi.yml up --build -d

# Clear and rebuild frontend dist inside container
docker compose -f docker-compose.yml -f docker-compose.pi.yml exec -T frontend sh -c "rm -rf /app/dist/* && npx vite build"

# Restart nginx to pick up new dist
docker compose -f docker-compose.yml -f docker-compose.pi.yml restart nginx

echo "Deploy complete"
