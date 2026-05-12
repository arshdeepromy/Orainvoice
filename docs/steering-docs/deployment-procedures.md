# Deployment Procedures — Multi-Environment Rules

This document defines deployment rules and procedures for a multi-environment SaaS application. It covers the principles that prevent downtime, data loss, and deployment failures regardless of your specific infrastructure.

## Why This Matters

Deployment is the highest-risk activity in a production system. Common failures include:
- Deploying without backing up the database (migration fails → data loss)
- Stopping the running service before the new build is ready (unnecessary downtime)
- Deploying untested code directly to production
- Overwriting environment-specific config files during deployment
- Line-ending or encoding issues when transferring between OS types
- Forgetting to run database migrations after deploying new code

---

## Critical Deployment Rules

### 1. Always Back Up Before Deploying

**Especially when migrations are involved.** A failed migration can leave the database in an inconsistent state.

```bash
# Example: PostgreSQL backup before deployment
pg_dump -U postgres myapp_db | gzip > backups/myapp_$(date +%Y%m%d_%H%M%S).sql.gz
```

Verify the backup exists and has a reasonable size before proceeding.

### 2. Build Before Stopping

**Never stop running containers until the new images are ready.** This minimizes downtime.

```bash
# CORRECT — builds new image first, then swaps containers
docker compose up -d --build --force-recreate app

# WRONG — causes unnecessary downtime
docker compose stop app        # ← downtime starts here
docker compose build app       # ← building while site is down
docker compose up -d app       # ← downtime ends here
```

### 3. Code Must Be in Version Control First

Before any deployment, all code must be committed and pushed:

```bash
git add <files>
git commit -m "description of changes"
git push
```

Never deploy uncommitted local changes. If the deployment fails, you need a known-good state to roll back to.

### 4. Never Overwrite Environment-Specific Files

Each environment has its own configuration. Deployment scripts must exclude:
- `.env` / `.env.production` files
- Environment-specific Docker Compose overrides
- SSL certificates
- Locally-built artifacts that differ per architecture

```bash
# Example: rsync with exclusions
rsync -av \
  --exclude='.env' \
  --exclude='docker-compose.prod.yml' \
  --exclude='certs/' \
  source/ destination/
```

### 5. Handle Cross-Platform Transfers Carefully

When deploying from one OS to another (e.g., Windows → Linux):
- Use archive downloads from your git host rather than local tar files
- Line-ending differences (CRLF vs LF) can cause subtle script failures
- File permissions are not preserved across OS boundaries

```bash
# Prefer: download from git host
curl -L -o code.tar.gz https://github.com/org/repo/archive/refs/heads/main.tar.gz

# Avoid: local tar from a different OS
tar -cf code.tar ./app  # Windows line endings will transfer
```

### 6. Run Migrations Automatically

Configure your deployment to run database migrations on startup:

```dockerfile
# In your Docker entrypoint
#!/bin/bash
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
```

This ensures the database schema is always in sync with the deployed code.

---

## Environment Separation

### Typical Environment Layout

| Environment | Purpose | Deployment Trigger |
|---|---|---|
| Development | Local development and testing | Automatic (code changes) |
| Staging | Pre-production validation | Manual or CI/CD |
| Production | Live customer traffic | Manual approval required |
| DR/Standby | Disaster recovery replica | Replication (automatic) |

### Environment-Specific Configuration

Each environment needs its own:
- Database connection string
- Redis URL
- API keys (use test keys in non-production)
- CORS origins
- Rate limiting thresholds
- Log levels
- Feature flags

Store these in environment-specific `.env` files that are never committed to git.

---

## Deployment Procedures

### Backend-Only Deployment

When only backend code changed (no frontend, no migrations):

1. Commit and push to version control
2. Back up the production database
3. Transfer code to production server
4. Rebuild the app container (builds first, then swaps)
5. Verify the app starts without errors

### Frontend + Backend Deployment

When frontend files also changed:

1. Commit and push to version control
2. Back up the production database
3. Build frontend locally (if production server can't build it)
4. Transfer backend code to production
5. Transfer built frontend assets to production
6. Rebuild all affected containers
7. Verify both frontend and backend respond correctly

### Migration-Only Deployment

When only database schema changes are needed:

1. **Always back up first** — migrations are the highest-risk deployment
2. Test the migration on a staging environment with production-like data
3. Deploy the code (migration runs on startup)
4. Verify the migration completed: check `alembic current` or equivalent
5. Verify the application works with the new schema

---

## Post-Deployment Verification

After every deployment:

```bash
# 1. Check the service is running
docker ps --filter name=myapp --format '{{.Names}} {{.Status}}'

# 2. Check for startup errors
docker logs myapp-1 --tail 30

# 3. Verify the health endpoint
curl -s -o /dev/null -w "%{http_code}" http://localhost/api/health

# 4. Check database migration status
docker exec myapp-1 alembic current

# 5. Smoke test critical paths
curl -s http://localhost/api/v1/auth/health
```

---

## Rollback Procedures

### Code Rollback

```bash
# Revert to previous commit
git revert HEAD
git push

# Redeploy
docker compose up -d --build --force-recreate app
```

### Database Rollback

```bash
# Downgrade one migration
docker exec myapp-1 alembic downgrade -1

# Or restore from backup
gunzip < backups/myapp_20260315_120000.sql.gz | psql -U postgres myapp_db
```

### When to Rollback vs Fix Forward

- **Rollback** if: the bug affects all users, data integrity is at risk, or the fix is complex
- **Fix forward** if: the bug is minor, affects few users, and the fix is simple and quick

---

## Rate Limiting Across Environments

| Environment | Rate Limits | Rationale |
|---|---|---|
| Development | Disabled (0) | React Strict Mode doubles requests; no limits needed |
| Staging | 2x production | Allows load testing without hitting limits |
| Production | Standard (100-200/min per user) | Protects against abuse |

---

## Checklist

Before deploying to production:

- [ ] All code is committed and pushed to version control
- [ ] Database is backed up (verify backup file exists and has reasonable size)
- [ ] Migrations tested on staging with production-like data
- [ ] Environment-specific files are excluded from transfer
- [ ] Frontend is built for the target architecture
- [ ] No hardcoded development URLs or credentials in the code
- [ ] Health check endpoint responds after deployment
- [ ] Application logs show no startup errors
- [ ] Critical user flows work (login, core feature, payment if applicable)
- [ ] Rollback plan is documented and tested
