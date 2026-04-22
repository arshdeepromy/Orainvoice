# Deployment Environments & Process

## Environments

| Environment | Location | Compose Files | Project Name | App Port | DB Port |
|---|---|---|---|---|---|
| Dev (local) | Windows desktop | `docker-compose.yml` + `docker-compose.dev.yml` | `orainvoice` | 80 | 5434 |
| HA Standby (local) | Windows desktop | `docker-compose.ha-standby.yml` | `invoicing-standby` | 8081 | 5433 |
| Standby Prod (local) | Windows desktop | `docker-compose.standby-prod.yml` | `invoicing-standby-prod` | 8082 | 5435 |
| Production | Raspberry Pi 5 (`192.168.1.90`, user: `nerdy`) | `docker-compose.yml` + `docker-compose.pi.yml` | `invoicing` | 8999 | 5432 |

### Production (Pi) Details

- Raspberry Pi 5, ARM64 architecture, 7.6 GB RAM, 4 cores
- Accessed via reverse proxy: `https://invoice.oraflows.co.nz`, `https://one.oraflows.com`, `https://one.oraflows.co.nz`
- SSH: `ssh nerdy@192.168.1.90`
- Pi has **no git installed** — code is transferred via tar archives
- Pi-specific files (`.env.pi`, `docker-compose.pi.yml`) live on the Pi and are never overwritten during deployment

### Standby Prod (Local) Details

- Runs on the same Windows desktop as dev, separate Docker Compose project
- Replicates data from the Pi primary via PostgreSQL logical replication
- Uses volume mounts for `./app` and `./alembic` — code changes take effect on container restart (no rebuild needed)
- Env file: `.env.standby-prod`

---

## Critical Deployment Rules

### 1. Git Must Be Updated First

Before any deployment, **all code must be committed and pushed to GitHub**:

```bash
git add <files>
git commit -m "description of changes"
git push
```

### 2. Download Tar from GitHub — Never Use Local Tar

**Locally packed tar files do not work on the Pi.** There are line-ending and encoding differences between Windows and the Pi's Linux environment that cause subtle issues.

Always download a fresh tar archive from GitHub after pushing:

```bash
# On the Pi — download fresh code from GitHub
ssh nerdy@192.168.1.90
cd /home/nerdy
curl -L -o code.tar.gz https://github.com/arshdeepromy/Orainvoice/archive/refs/heads/main.tar.gz
tar -xzf code.tar.gz
# Copy files into the deployment directory (preserving Pi-specific files)
rsync -av --exclude='.env.pi' --exclude='docker-compose.pi.yml' --exclude='certs/' \
  Orainvoice-main/ /home/nerdy/invoicing/
rm -rf Orainvoice-main code.tar.gz
```

Or from the Windows machine:

```powershell
# Download from GitHub and transfer to Pi
curl -L -o code.tar.gz https://github.com/arshdeepromy/Orainvoice/archive/refs/heads/main.tar.gz
scp code.tar.gz nerdy@192.168.1.90:/home/nerdy/
ssh nerdy@192.168.1.90 "cd /home/nerdy && tar -xzf code.tar.gz && rsync -av --exclude='.env.pi' --exclude='docker-compose.pi.yml' --exclude='certs/' Orainvoice-main/ /home/nerdy/invoicing/ && rm -rf Orainvoice-main code.tar.gz"
```

### 3. Frontend Must Be Built Locally

The Pi is ARM64-based and some npm packages (native modules, sharp, etc.) fail to build on ARM. The frontend **must be built on the Windows desktop** and the built dist transferred to the Pi.

```powershell
# Build frontend locally
cd frontend
npm run build

# Transfer the built dist to Pi
tar -cf - dist/ | ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing/frontend && rm -rf dist && tar -xf -"
```

### 4. Backup Data Before Deployment

**Always back up the production database before deploying**, especially when migrations are involved:

```bash
ssh nerdy@192.168.1.90 "docker exec invoicing-postgres-1 pg_dump -U postgres workshoppro | gzip > /home/nerdy/backups/workshoppro_$(date +%Y%m%d_%H%M%S).sql.gz"
```

Verify the backup exists and has a reasonable size before proceeding.

### 5. Minimize Downtime — Build Before Stopping

**Never stop running containers until the new images are ready.** Docker builds the new image while the old container is still serving traffic. Only when the build completes does Docker swap the containers.

The `--build --force-recreate` flags handle this correctly:

```bash
# This builds the new image FIRST, then stops the old container and starts the new one
docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate app
```

Do NOT do this:
```bash
# BAD — causes unnecessary downtime
docker compose stop app        # ← downtime starts here
docker compose build app       # ← building while site is down
docker compose up -d app       # ← downtime ends here
```

---

## Deployment Procedures

### Backend-Only Deployment (Pi Prod)

When only Python backend files changed (no frontend, no migrations):

```bash
# 1. Commit and push to GitHub
git add <changed files>
git commit -m "fix: description"
git push

# 2. Backup database
ssh nerdy@192.168.1.90 "docker exec invoicing-postgres-1 pg_dump -U postgres workshoppro | gzip > /home/nerdy/backups/workshoppro_$(date +%Y%m%d_%H%M%S).sql.gz"

# 3. Download fresh code from GitHub to Pi
ssh nerdy@192.168.1.90 "cd /home/nerdy && curl -sL -o code.tar.gz https://github.com/arshdeepromy/Orainvoice/archive/refs/heads/main.tar.gz && tar -xzf code.tar.gz && rsync -av --exclude='.env.pi' --exclude='docker-compose.pi.yml' --exclude='certs/' --exclude='frontend/dist' Orainvoice-main/ /home/nerdy/invoicing/ && rm -rf Orainvoice-main code.tar.gz"

# 4. Rebuild app container (builds new image first, then swaps)
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate app"
```

### Frontend + Backend Deployment (Pi Prod)

When frontend files also changed:

```bash
# 1. Commit and push to GitHub
git add <changed files>
git commit -m "feat: description"
git push

# 2. Backup database
ssh nerdy@192.168.1.90 "docker exec invoicing-postgres-1 pg_dump -U postgres workshoppro | gzip > /home/nerdy/backups/workshoppro_$(date +%Y%m%d_%H%M%S).sql.gz"

# 3. Build frontend locally (ARM64 npm issues prevent building on Pi)
cd frontend
npm run build
cd ..

# 4. Download fresh backend code from GitHub to Pi
ssh nerdy@192.168.1.90 "cd /home/nerdy && curl -sL -o code.tar.gz https://github.com/arshdeepromy/Orainvoice/archive/refs/heads/main.tar.gz && tar -xzf code.tar.gz && rsync -av --exclude='.env.pi' --exclude='docker-compose.pi.yml' --exclude='certs/' --exclude='frontend/dist' Orainvoice-main/ /home/nerdy/invoicing/ && rm -rf Orainvoice-main code.tar.gz"

# 5. Transfer locally-built frontend dist to Pi
tar -cf - frontend/dist/ | ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && tar -xf -"

# 6. Stop frontend + nginx, remove old volume, rebuild
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml stop frontend nginx && docker compose -f docker-compose.yml -f docker-compose.pi.yml rm -f frontend nginx && docker volume rm invoicing_frontend_dist 2>/dev/null; docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate app frontend nginx"
```

### Standby Prod Deployment (Local)

Standby prod uses volume mounts — just restart the app container:

```powershell
docker compose -p invoicing-standby-prod -f docker-compose.standby-prod.yml restart app
```

If frontend changed, also restart frontend + nginx:

```powershell
docker compose -p invoicing-standby-prod -f docker-compose.standby-prod.yml restart app frontend nginx
```

---

## Post-Deployment Verification

After deploying to Pi prod:

```bash
# Check container is running
ssh nerdy@192.168.1.90 "docker ps --filter name=invoicing-app --format '{{.Names}} {{.Status}}'"

# Check app logs for startup errors
ssh nerdy@192.168.1.90 "docker logs invoicing-app-1 --tail 30 2>&1"

# Verify the app responds
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.90:8999/api/v1/health
```

---

## Files That Must NOT Be Overwritten on Pi

These files are Pi-specific and must be excluded from any sync/rsync:

- `.env.pi` — Pi production environment variables
- `docker-compose.pi.yml` — Pi-specific Docker Compose overrides
- `certs/` — SSL certificates for PostgreSQL replication
- `frontend/dist/` — Must be built locally and transferred separately (not from GitHub)
