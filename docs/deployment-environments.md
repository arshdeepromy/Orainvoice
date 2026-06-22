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

The Pi is ARM64-based and some npm packages (native modules, sharp, etc.) fail to build on ARM. The frontend **must be built on the Windows desktop** (inside the Docker dev container since Node.js is not installed globally) and the built dist transferred to the Pi.

```powershell
# Build frontend inside the dev container
docker compose -p orainvoice exec frontend sh -c "cd /app && npm run build"

# Extract the dist from the container to a tar.gz file (avoids PowerShell binary pipe corruption)
docker compose -p orainvoice exec frontend sh -c "cd /app && tar -czf /tmp/dist.tar.gz dist/"
docker cp orainvoice-frontend-1:/tmp/dist.tar.gz C:\Users\Romy\OneDrive\Desktop\dist.tar.gz

# Transfer to Pi via SCP
scp C:\Users\Romy\OneDrive\Desktop\dist.tar.gz nerdy@192.168.1.90:/tmp/dist.tar.gz

# Extract on Pi
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing/frontend && rm -rf dist && tar -xzf /tmp/dist.tar.gz && rm /tmp/dist.tar.gz"
```

### 4. Backup Data Before Deployment

**Always back up the production database before deploying**, especially when migrations are involved:

```bash
# Write to /tmp to avoid permission issues with ~/backups
ssh nerdy@192.168.1.90 "docker exec invoicing-postgres-1 pg_dump -U postgres workshoppro > /tmp/pre_deploy.sql && gzip -f /tmp/pre_deploy.sql && ls -lh /tmp/pre_deploy.sql.gz"
```

Verify the backup exists and has a reasonable size (should be ~1MB+ for a production database) before proceeding.

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

# 2. Backup database (write to /tmp to avoid permission issues)
ssh nerdy@192.168.1.90 "docker exec invoicing-postgres-1 pg_dump -U postgres workshoppro > /tmp/pre_deploy.sql && gzip -f /tmp/pre_deploy.sql"

# 3. Download fresh code from GitHub to Pi (adjust branch name as needed)
#    NOTE: The extracted folder name matches the branch — e.g. Orainvoice-main/ or Orainvoice-feat-org-detail-dashboard/
BRANCH="main"
ssh nerdy@192.168.1.90 "cd /tmp && curl -sL -o code.tar.gz https://github.com/arshdeepromy/Orainvoice/archive/refs/heads/${BRANCH}.tar.gz && tar -xzf code.tar.gz && rsync -av --exclude='.env.pi' --exclude='docker-compose.pi.yml' --exclude='certs/' --exclude='frontend/dist' Orainvoice-*/  /home/nerdy/invoicing/ && rm -rf Orainvoice-* code.tar.gz"

# 4. Rebuild app container (builds new image first, then swaps — expect 5-8 min on Pi)
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate app"
# Pi may be unresponsive during build — wait and check later if SSH hangs
```

### Frontend + Backend Deployment (Pi Prod)

When frontend files also changed:

```bash
# 1. Commit and push to GitHub
git add <changed files>
git commit -m "feat: description"
git push

# 2. Backup database
ssh nerdy@192.168.1.90 "docker exec invoicing-postgres-1 pg_dump -U postgres workshoppro > /tmp/pre_deploy.sql && gzip -f /tmp/pre_deploy.sql"

# 3. Build frontend inside the dev container (Node.js not installed on host)
docker compose -p orainvoice exec frontend sh -c "cd /app && npm run build"
#    Fix any TypeScript errors before proceeding — tsc -b runs first and blocks on errors

# 4. Extract frontend dist via file (NOT pipe — PowerShell corrupts binary pipes)
docker compose -p orainvoice exec frontend sh -c "cd /app && tar -czf /tmp/dist.tar.gz dist/"
docker cp orainvoice-frontend-1:/tmp/dist.tar.gz C:\Users\Romy\OneDrive\Desktop\dist.tar.gz
scp C:\Users\Romy\OneDrive\Desktop\dist.tar.gz nerdy@192.168.1.90:/tmp/dist.tar.gz
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing/frontend && rm -rf dist && tar -xzf /tmp/dist.tar.gz && rm /tmp/dist.tar.gz"

# 5. Download fresh backend code from GitHub to Pi (adjust branch name)
BRANCH="main"
ssh nerdy@192.168.1.90 "cd /tmp && curl -sL -o code.tar.gz https://github.com/arshdeepromy/Orainvoice/archive/refs/heads/${BRANCH}.tar.gz && tar -xzf code.tar.gz && rsync -av --exclude='.env.pi' --exclude='docker-compose.pi.yml' --exclude='certs/' --exclude='frontend/dist' Orainvoice-*/ /home/nerdy/invoicing/ && rm -rf Orainvoice-* code.tar.gz"

# 6. Stop frontend + nginx, delete old volume, rebuild everything (expect 10-15 min total on Pi)
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml stop frontend nginx && docker compose -f docker-compose.yml -f docker-compose.pi.yml rm -f frontend nginx && docker volume rm invoicing_frontend_dist 2>/dev/null; docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate app frontend nginx"
# Pi will be unresponsive during build — this is normal. Wait 10-15 minutes.
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

---

## Known Issues & Gotchas (Lessons Learned)

### Branch Name in GitHub Download URL

When deploying from a feature branch (not `main`), the GitHub tar URL and extracted folder name change:

```bash
# main branch
curl -sL -o code.tar.gz https://github.com/arshdeepromy/Orainvoice/archive/refs/heads/main.tar.gz
# Extracts to: Orainvoice-main/

# Feature branch (e.g. feat/org-detail-dashboard)
curl -sL -o code.tar.gz https://github.com/arshdeepromy/Orainvoice/archive/refs/heads/feat/org-detail-dashboard.tar.gz
# Extracts to: Orainvoice-feat-org-detail-dashboard/
```

Always match the rsync source folder name to the branch. Get it wrong and rsync copies nothing.

### PowerShell Binary Pipe Corruption

**Never pipe binary data (tar streams) through PowerShell.** PowerShell mangles binary streams when piping between processes. This causes `tar: Skipping to next header` errors on the Pi.

```powershell
# BAD — PowerShell corrupts the binary tar stream
docker compose exec frontend sh -c "tar -cf - dist/" | ssh nerdy@192.168.1.90 "tar -xf -"

# GOOD — Use file-based transfer instead
docker compose exec frontend sh -c "tar -czf /tmp/dist.tar.gz -C /app dist/"
docker cp orainvoice-frontend-1:/tmp/dist.tar.gz C:\Users\Romy\OneDrive\Desktop\dist.tar.gz
scp C:\Users\Romy\OneDrive\Desktop\dist.tar.gz nerdy@192.168.1.90:/tmp/dist.tar.gz
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing/frontend && rm -rf dist && tar -xzf /tmp/dist.tar.gz && rm /tmp/dist.tar.gz"
```

### Pi Backup Directory Permissions

The `/home/nerdy/backups/` directory may be owned by root (created by a Docker volume or previous sudo operation). Writing directly to it fails with `Permission denied`.

```bash
# BAD — permission denied
docker exec invoicing-postgres-1 pg_dump -U postgres workshoppro | gzip > ~/backups/backup.sql.gz

# GOOD — write to /tmp first, then move if needed
ssh nerdy@192.168.1.90 "docker exec invoicing-postgres-1 pg_dump -U postgres workshoppro > /tmp/pre_deploy.sql && gzip -f /tmp/pre_deploy.sql"
```

### Pi Becomes Unresponsive During Builds

ARM64 Docker builds are CPU-intensive. During the `COPY . .` and `pip install` steps, the Pi may become unresponsive to SSH for 2-5 minutes. This is normal.

- **Do not panic** — the build is still running
- **Do not start a second build** — it will queue behind the first and make things worse
- **SSH commands will hang** — they'll complete once the build finishes and CPU load drops
- **Expect 5-8 minutes** for a full app image rebuild on the Pi
- **Frontend image builds add another 3-5 minutes** on top

If you need to check progress, use a long timeout:

```powershell
# Start the build as a background process and check later
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && nohup docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate app > /tmp/deploy.log 2>&1 &"

# Check progress later
ssh nerdy@192.168.1.90 "tail -20 /tmp/deploy.log"
```

### Local Dev Has Multiple Docker Compose Projects

The Windows desktop runs multiple Docker Compose projects that share ports:

| Project | Redis Port | Postgres Port | App Port |
|---|---|---|---|
| `orainvoice` (dev) | 6379 | 5434 | 80 |
| `invoicing-standby-prod` | 6381 | 5435 | 8082 |
| `invoicing` (from `.env` COMPOSE_FILE) | conflicts with `orainvoice` | conflicts | conflicts |

The `invoicing` project name (derived from the directory name in some contexts) conflicts with `orainvoice`. If you see port binding errors like `Bind for 0.0.0.0:6379 failed: port is already allocated`, it means two projects are trying to use the same port.

**Fix:** Always specify the project name explicitly:

```powershell
# Dev
docker compose -p orainvoice up -d app

# Standby prod
docker compose -p invoicing-standby-prod -f docker-compose.standby-prod.yml up -d app

# NEVER run bare "docker compose up" — it may pick up the wrong project name
```

### Node/npm Not in PATH on Windows

The Windows desktop does not have Node.js installed globally. The frontend is built inside the Docker container:

```powershell
# Build frontend inside the running dev container
docker compose -p orainvoice exec frontend sh -c "cd /app && npm run build"

# The built dist is at /app/dist inside the container
```

### TypeScript Errors Block Frontend Build

The `npm run build` command runs `tsc -b` (TypeScript check) before `vite build`. Any TS error will fail the entire build. Fix all TS errors before attempting deployment.

Common TS errors encountered:
- **Unused variables**: `TS6133: 'x' is declared but its value is never read` — prefix with `_` (e.g. `_clientSecret`)
- **Type mismatches in tests**: Test helper functions missing required fields — add the missing field with a default value

### Frontend Volume Must Be Deleted for Updates

The Pi's frontend uses a Docker named volume (`invoicing_frontend_dist`). The `watch-build.sh` script inside the container copies the dist into this volume. When deploying a new frontend, the old volume must be deleted so the new dist is used:

```bash
# Must stop frontend+nginx, remove containers, delete volume, then rebuild
docker compose stop frontend nginx
docker compose rm -f frontend nginx
docker volume rm invoicing_frontend_dist
docker compose up -d --build frontend nginx
```

Simply restarting the containers will NOT pick up the new frontend dist — the old volume persists.
