# 🐳 Docker Setup - Multi-Architecture Support

## TL;DR

```bash
./start-dev.sh
```

Visit: http://localhost:8080/docs

---

## ✨ Key Features

✅ **Works on both ARM64 (Apple Silicon) and x86_64 (Intel/AMD)**
✅ **No configuration changes when switching architectures**
✅ **Auto-detects your system and builds accordingly**
✅ **Hot reload for development**
✅ **Complete stack: API + DB + Redis + Celery + Frontend**

---

## 🚀 Quick Start Options

### Option 1: Full Stack (Recommended)
```bash
./start-dev.sh
```
Starts: API, Frontend, PostgreSQL, Redis, Celery workers

### Option 2: Backend Only
```bash
./start-backend-only.sh
```
Starts: API, PostgreSQL, Redis, Celery (no frontend)

### Option 3: Using Make
```bash
make up      # Start all services
make down    # Stop all services
make logs    # View logs
make help    # See all commands
```

---

## 📍 Access Points

| Service | URL | Credentials |
|---------|-----|-------------|
| API Documentation | http://localhost:8080/docs | - |
| API Base | http://localhost:8080 | - |
| Frontend | http://localhost:3000 | - |
| PostgreSQL | localhost:5432 | postgres/postgres |
| Redis | localhost:6379 | - |

---

## 🔍 Verify Setup

```bash
# Check your architecture and Docker status
./check-architecture.sh

# Validate configuration
docker-compose -f docker-compose.yml -f docker-compose.dev.yml config
```

---

## 📚 Documentation

| File | Description |
|------|-------------|
| `SETUP_SUMMARY.md` | Complete setup overview |
| `QUICKSTART.md` | Quick reference commands |
| `DOCKER_SETUP.md` | Detailed setup guide |
| `ARCHITECTURE.md` | Multi-arch technical details |
| `README_DOCKER.md` | What was changed |

---

## 🔧 Common Commands

```bash
# Start/Stop
make up                    # Start all services
make down                  # Stop all services
make restart               # Restart services

# Logs
make logs                  # All services
make logs-app              # Just API

# Database
make migrate               # Run migrations
make db-shell              # PostgreSQL shell

# Development
make shell                 # Access app container
make test                  # Run tests
make clean                 # Remove everything

# Architecture
./check-architecture.sh    # Check current architecture
```

---

## 🔄 Multi-Architecture Support

### Your Current System
```bash
./check-architecture.sh
# Shows: arm64 (Apple Silicon) or x86_64 (Intel/AMD)
```

### Switching Machines
No configuration changes needed! The same Docker setup works on:
- ✅ Apple Silicon Macs (M1, M2, M3, M4)
- ✅ Intel Macs
- ✅ Linux (ARM64 or x86_64)
- ✅ Windows with WSL2

### How It Works
Docker automatically:
1. Detects your host architecture
2. Pulls appropriate base images
3. Builds native containers
4. No emulation, no performance penalty

---

## ⚙️ Configuration

### Environment Variables
Edit `.env` file to configure:
- Database credentials
- API keys (Stripe, Carjam, Twilio, Xero, MYOB)
- JWT secrets
- Email/SMS providers
- CORS origins
- Rate limiting

### First Time Setup
```bash
# .env is already created from .env.example
# Review and update as needed
nano .env
```

---

## 🐛 Troubleshooting

### Port Already in Use
```bash
# Check what's using the port
lsof -i :8080    # API
lsof -i :5432    # PostgreSQL
lsof -i :6379    # Redis
lsof -i :3000    # Frontend

# Kill the process or change ports in docker-compose.yml
```

### Database Connection Issues
```bash
make down
make up          # Fresh start
```

### Architecture Mismatch Error
```bash
# If you see "exec format error"
make clean       # Remove old images
make build       # Rebuild for current architecture
```

### Slow Performance
- Increase Docker Desktop memory (Settings > Resources > Memory: 4GB+)
- Already using `:delegated` volumes for better macOS performance

### Clean Slate
```bash
make clean       # Remove containers and volumes
docker system prune -a    # Remove all Docker data
make build       # Rebuild everything
```

---

## 🎯 Development Workflow

1. **Start services**: `./start-dev.sh`
2. **Make code changes**: Auto-reload enabled
3. **View logs**: `make logs`
4. **Run migrations**: `make migrate` (when schema changes)
5. **Run tests**: `make test`
6. **Stop services**: `make down`

### Hot Reload
- **Backend**: Changes in `app/` auto-reload
- **Frontend**: Vite HMR for instant updates
- **Database**: Run migrations for schema changes

---

## 📦 Services Included

| Service | Version | Purpose |
|---------|---------|---------|
| PostgreSQL | 16-alpine | Database |
| Redis | 7-alpine | Cache & message broker |
| FastAPI | Latest | Python backend API |
| Celery | Latest | Background tasks |
| Celery Beat | Latest | Task scheduler |
| Vite/React | Latest | Frontend dev server |

All images support both ARM64 and x86_64 natively.

---

## 🎓 Next Steps

1. ✅ Start the application: `./start-dev.sh`
2. ✅ Verify it's running: `./check-architecture.sh`
3. ✅ Visit API docs: http://localhost:8080/docs
4. ✅ Review `.env`: Update API keys
5. ✅ Run migrations: `make migrate`
6. ✅ Start coding!

---

## 💡 Pro Tips

- Use `make help` to see all available commands
- Run `./check-architecture.sh` to verify your setup
- Keep `.env` secure (already in `.gitignore`)
- Use `make logs-app` to focus on API logs
- Database data persists in Docker volumes
- Frontend `node_modules` in Docker volume for speed

---

## 🌟 Why This Setup Rocks

- **Portable**: Same config on any machine
- **Fast**: Native builds, no emulation
- **Simple**: One command to start everything
- **Flexible**: Run full stack or backend only
- **Team-friendly**: No "works on my machine" issues
- **Future-proof**: Ready for new architectures

---

**Ready to go!** 🚀

```bash
./start-dev.sh
```

Then visit http://localhost:8080/docs and start building!
