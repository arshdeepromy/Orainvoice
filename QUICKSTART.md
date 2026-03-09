# Quick Start Guide - Multi-Architecture

Works on both **Apple Silicon** (ARM64) and **Intel/AMD** (x86_64) automatically!

## 🚀 Start Everything (Recommended)

```bash
./start-dev.sh
```

Then visit:
- API: http://localhost:8080/docs
- Frontend: http://localhost:3000

## 🔧 Backend Only

```bash
./start-backend-only.sh
```

## 📦 Using Make Commands

```bash
make up          # Start all services
make down        # Stop all services
make logs        # View logs
make shell       # Access app container
make migrate     # Run DB migrations
make test        # Run tests
```

## 🛑 Stop Everything

```bash
make down
# or
docker-compose -f docker-compose.yml -f docker-compose.dev.yml down
```

## 📖 Full Documentation

See `DOCKER_SETUP.md` for detailed instructions and troubleshooting.

## ⚙️ Configuration

Edit `.env` file to configure API keys, database settings, etc.

## 🔍 Check Status

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps
```
