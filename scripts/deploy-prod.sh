#!/bin/bash
# =============================================================================
# Production Deploy Script — OraInvoice
#
# Pulls latest code from a PRIVATE GitHub repo, auto-detects architecture
# (x86_64 vs ARM64), rebuilds containers for the correct platform, runs
# migrations, and automatically rolls back if anything fails.
#
# SETUP (run once on the prod server):
#   1. Create a GitHub Personal Access Token (classic) with 'repo' scope
#   2. Save it:  echo "YOUR_TOKEN" > ~/.ora_deploy_token && chmod 600 ~/.ora_deploy_token
#   3. Or export it:  export GITHUB_TOKEN="YOUR_TOKEN"
#
# Usage:
#   ./scripts/deploy-prod.sh              # deploy from current branch
#   ./scripts/deploy-prod.sh main         # deploy specific branch
#
# Data safety:
#   - pgdata and redisdata volumes are NEVER touched
#   - Only app + frontend images are rebuilt
#   - Postgres and Redis containers are restarted (not rebuilt)
# =============================================================================
set -euo pipefail

BRANCH="${1:-}"
DEPLOY_LOG="deploy-$(date +%Y%m%d-%H%M%S).log"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[DEPLOY]${NC} $*" | tee -a "$DEPLOY_LOG"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"  | tee -a "$DEPLOY_LOG"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"    | tee -a "$DEPLOY_LOG"; }
info() { echo -e "${CYAN}[INFO]${NC} $*"    | tee -a "$DEPLOY_LOG"; }

# ---------------------------------------------------------------------------
# 0. Pre-flight checks
# ---------------------------------------------------------------------------
if ! command -v docker &>/dev/null || ! docker compose version &>/dev/null; then
    err "docker compose is required but not found."
    exit 1
fi

if [ ! -f "docker-compose.yml" ]; then
    err "Run this script from the project root (where docker-compose.yml lives)."
    exit 1
fi

# ---------------------------------------------------------------------------
# 1. Detect architecture and set platform + compose files
# ---------------------------------------------------------------------------
ARCH=$(uname -m)
case "$ARCH" in
    x86_64|amd64)
        PLATFORM="linux/amd64"
        COMPOSE_CMD="docker compose -f docker-compose.yml"
        info "Detected architecture: x86_64 (amd64)"
        ;;
    aarch64|arm64)
        PLATFORM="linux/arm64"
        # Use Pi overrides if the file exists
        if [ -f "docker-compose.pi.yml" ]; then
            COMPOSE_CMD="docker compose -f docker-compose.yml -f docker-compose.pi.yml"
            info "Detected architecture: ARM64 — using Pi overrides"
        else
            COMPOSE_CMD="docker compose -f docker-compose.yml"
            info "Detected architecture: ARM64 (no Pi override file found)"
        fi
        ;;
    armv7l|armhf)
        PLATFORM="linux/arm/v7"
        if [ -f "docker-compose.pi.yml" ]; then
            COMPOSE_CMD="docker compose -f docker-compose.yml -f docker-compose.pi.yml"
            info "Detected architecture: ARMv7 — using Pi overrides"
        else
            COMPOSE_CMD="docker compose -f docker-compose.yml"
            info "Detected architecture: ARMv7"
        fi
        ;;
    *)
        err "Unknown architecture: $ARCH"
        exit 1
        ;;
esac

log "Build platform: $PLATFORM"
log "Compose command: $COMPOSE_CMD"

# ---------------------------------------------------------------------------
# 2. Resolve GitHub token for private repo auth
# ---------------------------------------------------------------------------
GITHUB_TOKEN="${GITHUB_TOKEN:-}"

# Try loading from file if env var not set
if [ -z "$GITHUB_TOKEN" ] && [ -f "$HOME/.ora_deploy_token" ]; then
    GITHUB_TOKEN=$(cat "$HOME/.ora_deploy_token" | tr -d '[:space:]')
    info "Loaded GitHub token from ~/.ora_deploy_token"
fi

if [ -z "$GITHUB_TOKEN" ]; then
    err "No GitHub token found. Set up auth for your private repo:"
    err "  Option A: echo 'ghp_YourToken' > ~/.ora_deploy_token && chmod 600 ~/.ora_deploy_token"
    err "  Option B: export GITHUB_TOKEN='ghp_YourToken'"
    exit 1
fi

# Inject token into the remote URL for this pull
CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
if [ -z "$CURRENT_REMOTE" ]; then
    err "No git remote 'origin' configured."
    exit 1
fi

# Build authenticated URL (works for both HTTPS and SSH-style remotes)
# Converts git@github.com:user/repo.git → https://TOKEN@github.com/user/repo.git
if echo "$CURRENT_REMOTE" | grep -q "^git@"; then
    # SSH format → convert to HTTPS with token
    REPO_PATH=$(echo "$CURRENT_REMOTE" | sed 's/git@github.com://' | sed 's/\.git$//')
    AUTH_URL="https://${GITHUB_TOKEN}@github.com/${REPO_PATH}.git"
elif echo "$CURRENT_REMOTE" | grep -q "^https://"; then
    # HTTPS format → inject token
    AUTH_URL=$(echo "$CURRENT_REMOTE" | sed "s|https://|https://${GITHUB_TOKEN}@|")
else
    err "Unrecognized remote URL format: $CURRENT_REMOTE"
    exit 1
fi

info "Remote: $CURRENT_REMOTE (token injected for pull)"

# ---------------------------------------------------------------------------
# 3. Tag current working images so we can roll back
# ---------------------------------------------------------------------------
log "Tagging current images as :rollback..."

PROJECT_DIR=$(basename "$(pwd)")
APP_IMAGE="${PROJECT_DIR}-app"
FRONTEND_IMAGE="${PROJECT_DIR}-frontend"

docker tag "$APP_IMAGE:latest" "$APP_IMAGE:rollback" 2>/dev/null || warn "No existing app image to tag (first deploy?)"
docker tag "$FRONTEND_IMAGE:latest" "$FRONTEND_IMAGE:rollback" 2>/dev/null || warn "No existing frontend image to tag (first deploy?)"

OLD_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
log "Current commit: $OLD_COMMIT"

# ---------------------------------------------------------------------------
# 4. Record current Alembic revision (for migration rollback)
# ---------------------------------------------------------------------------
log "Recording current migration revision..."
OLD_ALEMBIC_REV=$($COMPOSE_CMD exec -T app alembic current 2>/dev/null | grep -oP '[a-f0-9]+(?= \(head\))' || echo "")
if [ -n "$OLD_ALEMBIC_REV" ]; then
    log "Current Alembic revision: $OLD_ALEMBIC_REV"
else
    warn "Could not determine current Alembic revision (app not running?)"
fi

# ---------------------------------------------------------------------------
# 5. Pull latest code using token auth
# ---------------------------------------------------------------------------
log "Pulling latest code..."
git fetch "$AUTH_URL" 2>&1 | tee -a "$DEPLOY_LOG"

if [ -n "$BRANCH" ]; then
    log "Checking out branch: $BRANCH"
    git checkout "$BRANCH" 2>&1 | tee -a "$DEPLOY_LOG"
fi

# Pull using the authenticated URL (token never stored in git config)
git pull "$AUTH_URL" "$(git rev-parse --abbrev-ref HEAD)" 2>&1 | tee -a "$DEPLOY_LOG"

NEW_COMMIT=$(git rev-parse --short HEAD)
log "New commit: $NEW_COMMIT"

if [ "$OLD_COMMIT" = "$NEW_COMMIT" ] && [ -z "$BRANCH" ]; then
    warn "Already up to date ($NEW_COMMIT). Rebuilding anyway..."
fi

# ---------------------------------------------------------------------------
# Rollback function
# ---------------------------------------------------------------------------
rollback() {
    err "============================================"
    err "  DEPLOY FAILED — ROLLING BACK"
    err "============================================"

    log "Restoring previous images..."
    docker tag "$APP_IMAGE:rollback" "$APP_IMAGE:latest" 2>/dev/null || true
    docker tag "$FRONTEND_IMAGE:rollback" "$FRONTEND_IMAGE:latest" 2>/dev/null || true

    log "Reverting git to $OLD_COMMIT..."
    git checkout "$OLD_COMMIT" 2>/dev/null || true

    if [ -n "$OLD_ALEMBIC_REV" ]; then
        log "Rolling back migrations to $OLD_ALEMBIC_REV..."
        $COMPOSE_CMD up -d postgres redis 2>/dev/null || true
        sleep 5
        $COMPOSE_CMD run --rm app alembic downgrade "$OLD_ALEMBIC_REV" 2>/dev/null || warn "Migration rollback failed — may need manual intervention"
    fi

    log "Restarting services with previous images..."
    $COMPOSE_CMD up -d --no-build 2>&1 | tee -a "$DEPLOY_LOG" || true

    sleep 10
    if $COMPOSE_CMD exec -T app python -c "print('ok')" &>/dev/null; then
        warn "Rollback successful — running on previous version ($OLD_COMMIT)"
    else
        err "Rollback may have issues — check manually: $COMPOSE_CMD ps"
    fi

    err "Deploy log: $DEPLOY_LOG"
    exit 1
}

# ---------------------------------------------------------------------------
# 6. Build new images for the detected platform
# ---------------------------------------------------------------------------
log "Building new images for $PLATFORM..."
export DOCKER_DEFAULT_PLATFORM="$PLATFORM"

if ! $COMPOSE_CMD build --no-cache app frontend 2>&1 | tee -a "$DEPLOY_LOG"; then
    err "Build failed."
    rollback
fi

# ---------------------------------------------------------------------------
# 7. Stop app + frontend (keep postgres + redis running)
# ---------------------------------------------------------------------------
log "Stopping app and frontend containers..."
$COMPOSE_CMD stop app frontend nginx 2>&1 | tee -a "$DEPLOY_LOG"

# ---------------------------------------------------------------------------
# 8. Database backup before migrations
# ---------------------------------------------------------------------------
log "Creating pre-migration database snapshot..."
BACKUP_FILE="backups/pre-deploy-${NEW_COMMIT}-$(date +%Y%m%d-%H%M%S).sql.gz"
mkdir -p backups

# Source .env for DB credentials
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-workshoppro}"
if [ -f ".env" ]; then
    # Only grab the vars we need, don't pollute the environment
    POSTGRES_USER=$(grep -oP '^POSTGRES_USER=\K.*' .env 2>/dev/null || echo "postgres")
    POSTGRES_DB=$(grep -oP '^POSTGRES_DB=\K.*' .env 2>/dev/null || echo "workshoppro")
fi

if $COMPOSE_CMD exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$BACKUP_FILE" 2>/dev/null; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    log "Database backup: $BACKUP_FILE ($BACKUP_SIZE)"
else
    warn "Database backup failed — continuing (rollback images still available)"
fi

# ---------------------------------------------------------------------------
# 9. Start services with new images (entrypoint runs migrations)
# ---------------------------------------------------------------------------
log "Starting services with new images..."
if ! $COMPOSE_CMD up -d 2>&1 | tee -a "$DEPLOY_LOG"; then
    err "Failed to start services."
    rollback
fi

# ---------------------------------------------------------------------------
# 10. Wait for app to become healthy
# ---------------------------------------------------------------------------
log "Waiting for app to become healthy..."
MAX_WAIT=180  # ARM builds can be slower to start
WAITED=0
APP_HEALTHY=false

while [ $WAITED -lt $MAX_WAIT ]; do
    # Check if the app responds on the /health endpoint (public, no auth required)
    if $COMPOSE_CMD exec -T app python -c "
import httpx
r = httpx.get('http://localhost:8000/health', timeout=5)
assert r.status_code == 200 and r.json().get('status') == 'ok'
" &>/dev/null; then
        APP_HEALTHY=true
        break
    fi

    # Check if container crashed
    if $COMPOSE_CMD ps app 2>/dev/null | grep -qE "exited|dead"; then
        err "App container crashed during startup."
        $COMPOSE_CMD logs --tail=50 app 2>&1 | tee -a "$DEPLOY_LOG"
        rollback
    fi

    sleep 5
    WAITED=$((WAITED + 5))
    log "  ...waiting ($WAITED/${MAX_WAIT}s)"
done

if [ "$APP_HEALTHY" != "true" ]; then
    err "App did not become healthy within ${MAX_WAIT}s."
    $COMPOSE_CMD logs --tail=80 app 2>&1 | tee -a "$DEPLOY_LOG"
    rollback
fi

# ---------------------------------------------------------------------------
# 11. Verify frontend/nginx
# ---------------------------------------------------------------------------
log "Verifying frontend..."
sleep 5
if ! $COMPOSE_CMD ps nginx 2>/dev/null | grep -q "running"; then
    warn "Nginx might not be running — check: $COMPOSE_CMD ps"
fi

# ---------------------------------------------------------------------------
# 12. Cleanup
# ---------------------------------------------------------------------------
log "Cleaning up dangling images..."
docker image prune -f &>/dev/null || true

# Keep rollback images for manual recovery
log "Rollback images kept: ${APP_IMAGE}:rollback, ${FRONTEND_IMAGE}:rollback"

# Rotate old backups (keep last 5)
BACKUP_COUNT=$(ls -1 backups/pre-deploy-*.sql.gz 2>/dev/null | wc -l)
if [ "$BACKUP_COUNT" -gt 5 ]; then
    ls -1t backups/pre-deploy-*.sql.gz | tail -n +6 | xargs rm -f
    log "Rotated old backups (kept last 5)"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
log "============================================"
log "  DEPLOY SUCCESSFUL"
log "  Commit:   $OLD_COMMIT → $NEW_COMMIT"
log "  Platform: $PLATFORM ($ARCH)"
log "  Log:      $DEPLOY_LOG"
log "============================================"
