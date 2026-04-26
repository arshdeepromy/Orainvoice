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

## Git & GitHub
- Remote: `https://github.com/arshdeepromy/Orainvoice.git`
- Auth: GitHub CLI (`gh auth login`) — credentials stored in keyring
- Push/pull works without password prompts
- SSH to Pi: `ssh nerdy@192.168.1.90` (key auth, no password)
