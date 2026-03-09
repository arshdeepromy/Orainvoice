#!/bin/bash

# Start only backend services (API, DB, Redis, Celery)
# Works on both Apple Silicon (ARM64) and Intel/AMD (x86_64)
set -e

echo "🚀 Starting WorkshopPro NZ Backend..."
echo "🔍 Detected architecture: $(uname -m)"

# Check if .env exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✅ Created .env file"
fi

# Start only backend services
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis

echo "⏳ Waiting for database..."
sleep 5

# Run migrations
docker-compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app alembic upgrade head

# Start app and celery
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up app celery-worker celery-beat

echo ""
echo "✅ Backend running at http://localhost:8080"
echo "📚 API docs at http://localhost:8080/docs"
