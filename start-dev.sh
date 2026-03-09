#!/bin/bash

# WorkshopPro NZ - Development Startup Script
# Works on both Apple Silicon (ARM64) and Intel/AMD (x86_64)
set -e

echo "🚀 Starting WorkshopPro NZ in Docker..."
echo "🔍 Detected architecture: $(uname -m)"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Copying from .env.example..."
    cp .env.example .env
    echo "✅ Created .env file. Please update it with your configuration."
    echo ""
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop and try again."
    exit 1
fi

echo "🧹 Cleaning up old containers..."
docker-compose -f docker-compose.yml -f docker-compose.dev.yml down

echo ""
echo "🏗️  Building images for your architecture ($(uname -m))..."
docker-compose -f docker-compose.yml -f docker-compose.dev.yml build --no-cache

echo ""
echo "🐳 Starting services..."
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis

echo ""
echo "⏳ Waiting for database to be ready..."
sleep 5

echo ""
echo "🔄 Running database migrations..."
docker-compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app alembic upgrade head

echo ""
echo "🚀 Starting all services..."
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

echo ""
echo "✅ All services started!"
echo ""
echo "📍 Access points:"
echo "   - API: http://localhost:8080"
echo "   - Frontend: http://localhost:3000"
echo "   - PostgreSQL: localhost:5432"
echo "   - Redis: localhost:6379"
echo ""
echo "🛑 To stop: docker-compose -f docker-compose.yml -f docker-compose.dev.yml down"
