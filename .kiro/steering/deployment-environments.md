---
inclusion: auto
---

# Deployment Environments & Production Deployment Procedure

## Environments

### DEV — Local Windows Machine
- Containers: `invoicing-*` (app, frontend, nginx, postgres, redis)
- Compose: `docker-compose.yml` + `docker-compose.dev.yml`
- Env file: `.env`
- URL: `http://localhost` (port 80)
- All development, testing, and code changes happen here FIRST
- Never deploy untested code to prod

### PROD — Raspberry Pi
- Host: `192.168.1.90`
- User: `nerdy` (SSH key auth, no password needed for SSH; password required for sudo)
- Project path: `~/invoicing/`
- Containers: `invoicing-*` (same 5 containers, ARM64 native builds)
- Compose: `docker-compose.yml` + `docker-compose.pi.yml`
- Env file: `.env.pi` (copied as `.env` on Pi)
- URL: `http://192.168.1.90:8999`
- Port 8999 (nginx-proxy-manager occupies 80/443)
- `ENVIRONMENT=development` (SSL disabled — no certs on internal Docker network)
- DATABASE_URL includes `?ssl=disable` in docker-compose.yml on Pi
- Has active customer data — treat with care

## Workflow Rules

1. All code changes and testing happen on LOCAL (dev) containers first
2. Never modify prod directly unless it's an env/config-only change
3. When user says "deploy to prod" or "push to pi", follow the Production Deployment Procedure below
4. Always back up the prod database BEFORE deploying
5. Keep backups timestamped on the Pi at `~/invoicing-backups/`

## Production Deployment Procedure

When the user says "deploy to prod" / "push to pi" / "deploy these changes":

### Step 1: Pre-flight checks
```bash
# Verify Pi is reachable
ssh nerdy@192.168.1.90 'echo "Pi OK"'
# Verify containers are running
ssh nerdy@192.168.1.90 'cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml ps'
```

### Step 2: Backup production database
```bash
ssh nerdy@192.168.1.90 'mkdir -p ~/invoicing-backups'
ssh nerdy@192.168.1.90 'docker exec invoicing-postgres-1 pg_dump -U postgres -Fc workshoppro -f /tmp/backup.dump && docker cp invoicing-postgres-1:/tmp/backup.dump ~/invoicing-backups/workshoppro_$(date +%Y%m%d_%H%M%S).dump && docker exec invoicing-postgres-1 rm /tmp/backup.dump'
ssh nerdy@192.168.1.90 'ls -lh ~/invoicing-backups/ | tail -5'
```

### Step 3: Build frontend locally (Pi can't build Vite on ARM)

The Pi's ARM CPU can't reliably build the Vite frontend. Build it locally and transfer the pre-built dist.

```powershell
# Delete any stale local dist (prevents Docker from using cached old build)
Remove-Item -Recurse -Force frontend/dist 2>$null

# Build frontend in Docker with --no-cache to force fresh Vite build
docker compose -f docker-compose.yml -f docker-compose.dev.yml build --no-cache frontend

# Start the frontend container to populate the volume
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d frontend

# Copy the pre-built dist from the container to a clean local directory
docker cp invoicing-frontend-1:/app/dist frontend_dist_export
```

### Step 4: Sync code to Pi using git archive + SCP

**IMPORTANT:** Windows `tar` does NOT work for syncing to Pi. It has issues with:
- Exclude flags being ignored
- Permission errors on existing files
- Symlinks from Docker volumes
- `__pycache__` directories owned by root

**Use `git archive` instead** — it creates a clean tar from the git repo:

```powershell
# Ensure all changes are committed and pushed
git add -A
git commit -m "deploy: <description>"
git push origin <branch>

# Create a clean tar from the current HEAD (excludes .git, node_modules, __pycache__ automatically)
git archive --format=tar HEAD -o deploy.tar

# SCP the tar to Pi
scp deploy.tar nerdy@192.168.1.90:/tmp/deploy.tar
```

### Step 5: Extract code on Pi

```bash
# Fix directory permissions (Docker sets directories to read-only)
ssh nerdy@192.168.1.90 'cd ~/invoicing && find . -maxdepth 5 -type d -exec chmod u+w {} \; 2>/dev/null'

# Extract the git archive (overwrites existing files)
ssh nerdy@192.168.1.90 'cd ~/invoicing && tar --overwrite -xf /tmp/deploy.tar'

# Verify critical files landed
ssh nerdy@192.168.1.90 'ls ~/invoicing/app/main.py ~/invoicing/Dockerfile ~/invoicing/docker-compose.yml'
```

### Step 6: Transfer pre-built frontend dist

```powershell
# Create the dist directory on Pi if it doesn't exist
ssh nerdy@192.168.1.90 'mkdir -p ~/invoicing/frontend/dist/assets'

# SCP the pre-built dist files
scp -r frontend_dist_export/* nerdy@192.168.1.90:/home/nerdy/invoicing/frontend/dist/
```

### Step 7: Rebuild and restart containers on Pi

```bash
# Rebuild app container (backend only — uses cached pip layers, fast)
ssh nerdy@192.168.1.90 'cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate app'

# Rebuild frontend + nginx (frontend uses pre-built dist, no Vite build needed)
ssh nerdy@192.168.1.90 'cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml stop frontend nginx && docker compose -f docker-compose.yml -f docker-compose.pi.yml rm -f frontend nginx && docker volume rm invoicing_frontend_dist 2>/dev/null && docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build frontend nginx'
```

**CRITICAL:** After frontend container starts, fix the assets directory permissions:
```bash
ssh nerdy@192.168.1.90 'cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml exec frontend chmod -R 755 /app/dist/assets'
```
Without this, nginx can't read the JS/CSS files and you get a blank white page.

### Step 8: Verify deployment

```bash
# Check all containers are running
ssh nerdy@192.168.1.90 'cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml ps'

# Check migration is at head
ssh nerdy@192.168.1.90 'cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml exec app alembic current'

# Check app logs for errors
ssh nerdy@192.168.1.90 'cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml logs app --tail 20'

# Verify frontend is accessible (should return 200, not blank page)
ssh nerdy@192.168.1.90 'curl -s -o /dev/null -w "%{http_code}" http://localhost:8999/'

# Verify API responds
ssh nerdy@192.168.1.90 'curl -s -o /dev/null -w "%{http_code}" http://localhost:8999/api/v1/auth/stripe-publishable-key'
```

### Step 9: Cleanup

```powershell
# Remove local temp files
Remove-Item deploy.tar 2>$null
Remove-Item -Recurse -Force frontend_dist_export 2>$null

# Remove tar from Pi
ssh nerdy@192.168.1.90 'rm -f /tmp/deploy.tar'
```

---

## Known Deployment Issues and Fixes

### Issue: Blank white page after deployment
**Cause:** The `frontend/dist/assets/` directory gets created with `drwx------` (700) permissions inside the Docker volume. Nginx worker runs as non-root and can't read the JS/CSS files.
**Fix:** Run `chmod -R 755 /app/dist/assets` inside the frontend container after every deployment (Step 7 above).

### Issue: Windows tar fails with "Cannot open: File exists" or "Permission denied"
**Cause:** Windows tar can't overwrite files owned by root on the Pi, and has issues with Docker-created symlinks and `__pycache__` directories.
**Fix:** Use `git archive` instead of Windows tar. Git archive creates a clean tar from the repo that extracts cleanly on Linux.

### Issue: Pi can't build frontend (Vite fails on ARM)
**Cause:** Some npm packages don't have ARM64 binaries, and Vite build can be unreliable on the Pi's limited resources.
**Fix:** Always build the frontend locally on Windows, then transfer the pre-built `dist/` to Pi. The Dockerfile detects `dist/` exists and skips the Vite build ("Using pre-built dist/").

### Issue: Old frontend assets still showing after deployment
**Cause:** The Docker volume `invoicing_frontend_dist` caches old assets. New deployment adds new files but doesn't remove old ones.
**Fix:** Delete the volume before recreating the frontend container: `docker volume rm invoicing_frontend_dist`

### Issue: Directory permissions on Pi prevent file extraction
**Cause:** Docker sets directories to read-only (`dr-xr-xr-x`) when building images. The `nerdy` user can't write to them.
**Fix:** Run `find . -maxdepth 5 -type d -exec chmod u+w {} \;` before extracting the tar.

### Issue: `.env.pi` not copied
**Cause:** `git archive` excludes `.env*` files (they're in `.gitignore`).
**Fix:** `.env.pi` should already exist on the Pi from initial setup. If it needs updating, SCP it separately: `scp .env.pi nerdy@192.168.1.90:~/invoicing/.env`

---

## Database Comparison (Dev vs Prod)

After deployment, verify tables match:
```powershell
# Save dev tables
docker compose exec postgres psql -U postgres -d workshoppro -t -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;" > dev_tables.txt

# Save prod tables
ssh nerdy@192.168.1.90 'cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml exec -T postgres psql -U postgres -d workshoppro -t -c "SELECT tablename FROM pg_tables WHERE schemaname = '\''public'\'' ORDER BY tablename;"' > prod_tables.txt

# Compare
$dev = (Get-Content dev_tables.txt | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
$prod = (Get-Content prod_tables.txt | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
Compare-Object $dev $prod
# No output = tables match
```

## Rollback Procedure

If something goes wrong after deployment:

### Quick rollback (restore database from backup)
```bash
# List available backups
ssh nerdy@192.168.1.90 'ls -lh ~/invoicing-backups/'
# Stop the app container to prevent writes
ssh nerdy@192.168.1.90 'cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml stop app'
# Copy backup into the container and restore (replace FILENAME)
ssh nerdy@192.168.1.90 'docker cp ~/invoicing-backups/FILENAME.dump invoicing-postgres-1:/tmp/restore.dump && docker exec invoicing-postgres-1 pg_restore -U postgres -d workshoppro --clean --if-exists --no-owner /tmp/restore.dump && docker exec invoicing-postgres-1 rm /tmp/restore.dump'
# Restart app
ssh nerdy@192.168.1.90 'cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml start app'
```

### Full rollback (code + database)
- Keep previous code snapshots if needed (git tag before deploy)
- Restore database from backup as above
- Re-sync the previous code version

## Key Files (Pi-specific)
- `docker-compose.pi.yml` — Pi resource limits, port 8999, tuned postgres/redis
- `.env.pi` — Pi environment (CORS for 192.168.1.90:8999, WebAuthn RP_ID, etc.)
- Pi `.env` is a COPY of `.env.pi` — always update `.env.pi` locally, then scp as `.env`

## Backup Retention
- Backups stored at `~/invoicing-backups/` on the Pi
- Format: `workshoppro_YYYYMMDD_HHMMSS.dump`
- Clean up old backups periodically (keep last 5-10)
- Initial baseline backup: `workshoppro_initial_20260322.dump` (522KB)

## HA Replication (Active-Standby)

### Architecture
- Primary and standby are deployed on separate physical machines at different physical locations
- Connected via VPN — SSL certs secure the replicator DB connection between sites
- Primary node: serves all read/write traffic
- Standby node: receives real-time data via PostgreSQL logical replication
- Heartbeat service monitors both nodes' health via HTTP
- DNS/NPM routing is managed manually by the admin
- `docker-compose.ha-standby.yml` is for LOCAL DEV ONLY — never use it in production
- In production, both nodes use `docker-compose.yml` + `docker-compose.pi.yml` on their respective hosts

### Local Dev HA Setup

The dev environment runs two complete stacks on the same machine (for testing only):

| | Primary | Standby |
|---|---------|---------|
| Project | `invoicing` | `invoicing-standby` |
| Compose | `docker-compose.yml` + `docker-compose.dev.yml` | `docker-compose.ha-standby.yml` |
| Env | `.env` | `.env.ha-standby` |
| Nginx | port 80 | port 8081 |
| Postgres | port 5434 (host) | port 5433 (host) |
| Redis | port 6379 | port 6380 |

**Critical rules:**
- Primary postgres is on host port **5434** (not 5432) to avoid conflicts with local PostgreSQL
- **Never seed the standby database** — all data comes from replication
- Use `host.docker.internal` for peer endpoints (not `localhost`)
- Containers must be recreated (not just restarted) after adding new env vars
- Both postgres instances must have `wal_level=logical`

**Dev setup steps:**
1. Start primary: `docker compose -p invoicing up --build -d`
2. Migrate + seed primary
3. Start standby: `docker compose -p invoicing-standby -f docker-compose.ha-standby.yml up --build -d`
4. Migrate standby (NO seeding)
5. Configure HA via frontend on both nodes
6. Initialize replication: primary first (publication), then standby (subscription)

See `docs/HA_REPLICATION_GUIDE.md` for the full guide including production deployment, security, and troubleshooting.

### Environment Variables
Both nodes need these in their `.env`:
- `HA_HEARTBEAT_SECRET` — shared HMAC secret for heartbeat signing (must be identical on both nodes)
- `HA_PEER_DB_URL` — PostgreSQL connection string for the peer's database (used by replication)

### Initial Setup

1. **Configure Primary Node**
   - Set `HA_HEARTBEAT_SECRET` in `.env` on the primary Pi
   - Deploy and start the app
   - Call `PUT /api/v1/ha/configure` with `role: "primary"` and the standby's endpoint
   - Call `POST /api/v1/ha/replication/init` to create the publication

2. **Configure Standby Node**
   - Set `HA_HEARTBEAT_SECRET` (same value) and `HA_PEER_DB_URL` in `.env` on the standby Pi
   - Deploy using `docker-compose.yml` + `docker-compose.pi-standby.yml`
   - Run migrations only (do NOT seed)
   - Call `PUT /api/v1/ha/configure` with `role: "standby"` and the primary's endpoint
   - Call `POST /api/v1/ha/replication/init` to create the subscription

3. **Verify**
   - Check `GET /api/v1/ha/replication/status` on both nodes
   - Check the HA Status Panel on the Global Admin Dashboard
   - Verify heartbeat is healthy on both nodes

### Rolling Update Procedure

To update the app with zero downtime:

1. **Put standby in maintenance mode**: `POST /api/v1/ha/maintenance-mode` on standby
2. **Update standby**: deploy new code, run migrations, restart containers
3. **Exit maintenance on standby**: `POST /api/v1/ha/ready` on standby
4. **Verify standby is healthy**: check replication status and heartbeat
5. **Promote standby to primary**: `POST /api/v1/ha/promote` on standby (with confirmation)
6. **Update DNS/NPM**: point traffic to the new primary
7. **Demote old primary to standby**: `POST /api/v1/ha/demote` on old primary
8. **Update old primary**: deploy new code, run migrations, restart containers
9. **Exit maintenance on old primary**: `POST /api/v1/ha/ready`
10. **Verify both nodes healthy**: check HA Status Panel

### Key Files
- `docker-compose.ha-standby.yml` — local dev standby compose (NOT for production)
- `.env.ha-standby` — local dev standby environment
- `app/modules/ha/` — all HA backend code
- `frontend/src/components/ha/` — HA frontend components
- `frontend/src/pages/admin/HAReplication.tsx` — HA admin page
- `docs/HA_REPLICATION_GUIDE.md` — comprehensive HA guide (includes production deployment)
