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
# Create backup directory if needed
ssh nerdy@192.168.1.90 'mkdir -p ~/invoicing-backups'
# Dump the database inside the container, then copy out
ssh nerdy@192.168.1.90 'docker exec invoicing-postgres-1 pg_dump -U postgres -Fc workshoppro -f /tmp/backup.dump && docker cp invoicing-postgres-1:/tmp/backup.dump ~/invoicing-backups/workshoppro_$(date +%Y%m%d_%H%M%S).dump && docker exec invoicing-postgres-1 rm /tmp/backup.dump'
# Verify backup was created and has reasonable size
ssh nerdy@192.168.1.90 'ls -lh ~/invoicing-backups/ | tail -5'
```

### Step 3: Sync code to Pi
```bash
# From local workspace root, tar and pipe to Pi (excludes node_modules, .git, etc.)
tar --exclude='node_modules' --exclude='.git' --exclude='__pycache__' --exclude='.hypothesis' --exclude='*.pyc' --exclude='.env' -cf - . | ssh nerdy@192.168.1.90 'cd ~/invoicing && tar xf -'
# Copy the Pi-specific env file
scp .env.pi nerdy@192.168.1.90:~/invoicing/.env
```

### Step 4: Rebuild and restart containers
```bash
ssh nerdy@192.168.1.90 'cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml up --build -d'
```

### Step 5: Verify deployment
```bash
# Check containers are healthy
ssh nerdy@192.168.1.90 'cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml ps'
# Check app logs for errors
ssh nerdy@192.168.1.90 'cd ~/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml logs app --tail 20'
# Verify API responds
ssh nerdy@192.168.1.90 'curl -s -o /dev/null -w "%{http_code}" http://localhost:8999/'
```

### Step 6: Confirm with user
- Report deployment status
- If errors found, offer to rollback

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
- Two Raspberry Pi nodes at different physical locations
- Primary node: serves all read/write traffic
- Standby node: receives real-time data via PostgreSQL logical replication
- Heartbeat service monitors both nodes' health via HTTP
- DNS/NPM routing is managed manually by the admin

### Local Dev HA Setup

The dev environment runs two complete stacks on the same machine:

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
- `docker-compose.ha-standby.yml` — local dev standby compose
- `.env.ha-standby` — local dev standby environment
- `docker-compose.pi-standby.yml` — production standby compose override
- `app/modules/ha/` — all HA backend code
- `frontend/src/components/ha/` — HA frontend components
- `frontend/src/pages/admin/HAReplication.tsx` — HA admin page
- `docs/HA_REPLICATION_GUIDE.md` — comprehensive HA guide
