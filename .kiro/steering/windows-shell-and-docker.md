---
inclusion: auto
---

# Development Environment — Shell & Docker Reference

This workspace runs on **Ubuntu Linux** (x86_64) with **bash** as the default shell.

## Shell Rules

- Standard bash syntax: `&&`, `||`, pipes, redirects all work normally
- Environment variables: `$VAR_NAME` or `export VAR=value`
- Docker commands work without `sudo` (user is in the `docker` group)

## Docker Compose

### Project Name
The local dev containers use project name **`invoicing`** (derived from the workspace folder). Container names follow the pattern `invoicing-<service>-1`.

### Compose File Selection
The `.env` file sets `COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml` (colon separator on Linux). This auto-loads the dev override for hot-reload.

### Common Docker Commands
```bash
# Check running containers
docker compose ps

# Stop and remove containers (preserves data volumes)
docker compose down

# Rebuild and restart everything
docker compose up -d --build --force-recreate

# Rebuild a single service
docker compose up -d --build --force-recreate app

# Delete frontend_dist volume for fresh frontend rebuild
docker volume rm invoicing_frontend_dist

# View container logs
docker compose logs app --tail 50
docker compose logs postgres --tail 50

# Run migrations manually
docker compose exec app alembic upgrade head

# Open a shell in the app container
docker compose exec app bash

# Open a psql shell
docker compose exec postgres psql -U postgres -d workshoppro
```

### Fresh Database Setup Note
On a completely fresh database, the docker entrypoint automatically creates the `alembic_version` table with a wide `version_num` column (VARCHAR(128)) before running migrations. No manual intervention needed — just start the containers and migrations will run.

### Data Volumes — Never Delete These
- `invoicing_pgdata` — PostgreSQL database (all org/customer/invoice data)
- `invoicing_redisdata` — Redis cache

### Safe to Delete & Rebuild
- `invoicing_frontend_dist` — rebuilt automatically on `up --build`
- `invoicing_mobile_dist` — rebuilt automatically on `up --build`

## Port Mappings (Local Dev)
| Service  | Host Port | Container Port |
|----------|-----------|----------------|
| nginx    | 80        | 80             |
| postgres | 5434      | 5432           |
| redis    | 6379      | 6379           |
| app      | (internal)| 8000           |

## Production Deployment to Pi (CRITICAL — Read Before Every Deploy)

**Pi details**: `192.168.1.90`, user `nerdy`, project dir `/home/nerdy/invoicing`, compose files `docker-compose.yml + docker-compose.pi.yml`, port 8999.

Pi has **no git** — code is synced via `tar -cf - <files> | ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && tar -xf -"`.

### Pre-Deploy Checklist (MANDATORY)

Before deploying to Pi, **always** check these:

1. **Alembic migrations**: Compare local head vs Pi head. If they differ, you MUST sync `alembic/versions/` to Pi.
   ```bash
   # Check local head
   ls -t alembic/versions/ | head -3
   # Check Pi head
   ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml exec app python -c \"from alembic.config import Config; from alembic import command; c = Config('alembic.ini'); command.current(c)\""
   ```
   If Pi is behind, sync ALL migrations:
   ```bash
   tar -cf - alembic/versions/ | ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && tar -xf -"
   ```
   The docker entrypoint runs `alembic upgrade head` automatically on app start.

2. **Model changes**: If any `models.py` file was modified, it MUST be synced. A model referencing a column that doesn't exist in the DB will crash at runtime with `AttributeError`.

3. **All dependent files**: When syncing a fix, think about the full dependency chain:
   - Code change → does it reference new DB columns? → sync migrations + models
   - Frontend change → does it call new/changed API endpoints? → sync backend too
   - Schema change → does the router/service use new fields? → sync all three

### Deploy Steps

```bash
# 1. Sync ALL changed files (always include alembic/versions/ if any migrations exist)
tar -cf - \
  app/ \
  alembic/versions/ \
  frontend/src/ \
  frontend/package.json \
  VERSION \
  pyproject.toml \
  CHANGELOG.md \
  | ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && tar -xf -"

# 2. Rebuild backend (runs migrations automatically via entrypoint)
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate app"

# 3. Rebuild frontend (stop → rm → delete volume → rebuild)
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml stop frontend nginx"
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml rm -f frontend nginx"
ssh nerdy@192.168.1.90 "docker volume rm invoicing_frontend_dist"
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate frontend nginx"

# 4. Flush Redis cache
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml exec redis redis-cli FLUSHALL"

# 5. Verify
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml ps"
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml logs app --tail 20"
```

### Post-Deploy Verification

- Check app logs for migration output: `Running upgrade 0160 -> 0161` etc.
- Check app logs for `Application startup complete.`
- Check for no `AttributeError`, `UndefinedColumnError`, or `ProgrammingError` in logs
- Load the app in browser and test the changed features

### Common Deployment Mistakes (Lessons Learned)

| Mistake | Consequence | Prevention |
|---------|-------------|------------|
| Synced code but not `alembic/versions/` | `AttributeError: 'Model' has no attribute 'new_column'` — model references column that doesn't exist in DB | Always sync `alembic/versions/` when deploying |
| Synced only the changed files, missed a dependency | Runtime crash on import or attribute access | Sync entire `app/` directory, not individual files |
| Forgot to flush Redis after deploy | Stale cached data served to users | Always `FLUSHALL` after deploy |
| Didn't delete `frontend_dist` volume before rebuild | Old cached JS bundles served by nginx | Always `docker volume rm invoicing_frontend_dist` |
| Didn't check Pi's current alembic revision | Assumed migrations were up to date | Always check `alembic current` on Pi before deploying |

### Files to NEVER Sync to Pi (Pi-specific)

- `.env` — Pi uses `.env.pi` (different DB host, ports, CORS origins)
- `docker-compose.dev.yml` — dev-only overrides
- `.env.pi` — already on Pi, don't overwrite
- `docker-compose.pi.yml` — already on Pi, don't overwrite

## Git & GitHub
- Remote: `https://github.com/arshdeepromy/Orainvoice.git`
- Auth: GitHub CLI (`gh auth login`) — credentials stored in keyring
- Push/pull works without password prompts
- SSH to Pi: `ssh nerdy@192.168.1.90` (key auth, no password)
