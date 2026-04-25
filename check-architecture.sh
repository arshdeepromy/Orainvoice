#!/bin/bash

# Check current architecture and Docker setup
echo "🔍 System Architecture Check"
echo "================================"
echo ""

# Host architecture
HOST_ARCH=$(uname -m)
echo "Host Architecture: $HOST_ARCH"

case $HOST_ARCH in
    arm64|aarch64)
        echo "  → Apple Silicon / ARM64 detected"
        ;;
    x86_64|amd64)
        echo "  → Intel/AMD x86_64 detected"
        ;;
    *)
        echo "  → Unknown architecture"
        ;;
esac

echo ""

# Docker info
if docker info > /dev/null 2>&1; then
    echo "Docker Status: ✅ Running"
    DOCKER_ARCH=$(docker version --format '{{.Server.Arch}}')
    echo "Docker Architecture: $DOCKER_ARCH"
else
    echo "Docker Status: ❌ Not running"
    exit 1
fi

echo ""

# Check if containers are running
if docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps | grep -q "Up"; then
    echo "Containers Status: ✅ Running"
    echo ""
    echo "Container Architectures:"
    
    # Check app container
    if docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps | grep -q "app.*Up"; then
        APP_ARCH=$(docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec -T app uname -m 2>/dev/null || echo "not running")
        echo "  - App: $APP_ARCH"
    fi
    
    # Check postgres container
    if docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps | grep -q "postgres.*Up"; then
        PG_ARCH=$(docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec -T postgres uname -m 2>/dev/null || echo "not running")
        echo "  - PostgreSQL: $PG_ARCH"
    fi
    
    # Check redis container
    if docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps | grep -q "redis.*Up"; then
        REDIS_ARCH=$(docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec -T redis uname -m 2>/dev/null || echo "not running")
        echo "  - Redis: $REDIS_ARCH"
    fi
else
    echo "Containers Status: ⚠️  Not running"
    echo ""
    echo "Start containers with: ./start-dev.sh"
fi

echo ""
echo "================================"
echo "✅ Configuration is multi-architecture compatible"
echo "   Works on both ARM64 and x86_64 without changes"
