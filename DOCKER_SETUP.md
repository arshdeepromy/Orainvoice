# Docker Setup - Multi-Architecture (ARM64 & x86_64)

This guide helps you run WorkshopPro NZ locally using Docker on both:
- **Apple Silicon** (M1, M2, M3 - ARM64)
- **Intel/AMD** processors (x86_64)

Docker automatically detects your architecture and builds the appropriate images.

## Prerequisites

- Docker Desktop for Mac (with Apple Silicon support)
- At least 4GB RAM allocated to Docker
- 10GB free disk space

## Quick Start

### Option 1: Automated Setup (Recommended)

```bash
./start-dev.sh
```

This script will:
- Create .env file if missing
- Build ARM64-compatible images
- Start all services (PostgreSQL, Redis, API, Frontend, Celery)
- Run database migrations
- Show access URLs

### Option 2: Manual Setup

1. **Copy environment file:**
   ```bash
   cp .env.example .env
   ```

2. **Build and start services:**
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
   ```

3. **Run migrations (in another terminal):**
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head
   ```

## Access Points

- **API Documentation**: http://localhost:8080/docs
- **Frontend**: http://localhost:3000
- **PostgreSQL**: localhost:5432 (user: postgres, pass: postgres)
- **Redis**: localhost:6379

## Useful Commands

### View logs
```bash
# All services
docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f

# Specific service
docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f app
```

### Stop services
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml down
```

### Rebuild after code changes
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

### Run database migrations
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head
```

### Access database
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres psql -U postgres -d workshoppro
```

### Run tests
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec app pytest
```

### Shell into app container
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec app bash
```

## ARM64 Optimizations

The setup is architecture-agnostic and includes:
- **Auto-detection**: Docker builds for your host architecture automatically
- **Alpine images**: PostgreSQL and Redis use Alpine (supports both ARM64 and AMD64)
- **Python slim**: Base Python image works on both architectures
- **Node Alpine**: Frontend uses Node Alpine (multi-arch support)
- **Optimized volumes**: `:delegated` flag for better performance on macOS
- **No platform locks**: Switch between ARM and x86 machines without config changes

## Troubleshooting

### Port already in use
If you see "port already allocated" errors:
```bash
# Check what's using the port
lsof -i :8080  # or :5432, :6379, :3000

# Stop the conflicting service or change ports in docker-compose.yml
```

### Database connection errors
```bash
# Restart PostgreSQL
docker-compose -f docker-compose.yml -f docker-compose.dev.yml restart postgres

# Check if it's healthy
docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps
```

### Slow performance
- Increase Docker Desktop memory allocation (Settings > Resources)
- Use `:delegated` volume mounts (already configured)
- Consider using Docker volumes instead of bind mounts for node_modules

### Clean slate
```bash
# Remove all containers, volumes, and images
docker-compose -f docker-compose.yml -f docker-compose.dev.yml down -v
docker system prune -a
```

## Development Workflow

1. Code changes in `app/` are automatically reloaded (hot reload enabled)
2. Frontend changes in `frontend/src/` trigger Vite HMR
3. Database schema changes require running migrations
4. New dependencies require rebuilding the image

## Environment Variables

Edit `.env` to configure:
- Database credentials
- API keys (Stripe, Carjam, etc.)
- JWT secrets
- Email/SMS providers
- Feature flags

See `.env.example` for all available options.
