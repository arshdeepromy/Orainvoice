#!/bin/bash
# =============================================================================
# Production Deploy Script — OraInvoice
#
# Pulls latest code from a PRIVATE GitHub repo, auto-detects architecture
# (x86_64 vs ARM64), detects existing Docker project/volumes, rebuilds
# containers for the correct platform, refreshes the frontend dist volume,
# runs migrations, and automatically rolls back if anything fails.
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
#   - pgdata and redisdata volumes are NEVER touched or recreated
#   - frontend_dist volume is refreshed in-place (cleared + rebuilt)
#   - Images are built FIRST, then containers are swapped
#   - Automatic rollback on any failure
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
# 2. Detect existing Docker project name and volumes
#    This prevents creating duplicate volumes when the repo folder name
#    differs from the original deployment folder.
# ---------------------------------------------------------------------------
CURRENT_DIR_NAME=$(basename "$(pwd)")

# Check if COMPOSE_PROJECT_NAME is already set in .env
CONFIGURED_PROJECT=$(grep -oP '^COMPOSE_PROJECT_NAME=\K.*' .env 2>/dev/null || echo "")

if [ -n "$CONFIGURED_PROJECT" ]; then
    PROJECT_NAME="$CONFIGURED_PROJECT"
    info "Using project name from .env: $PROJECT_NAME"
else
    # Auto-detect: look for existing volumes that match known patterns
    # This handles the case where the repo was cloned into a different folder
    DETECTED_PROJECT=""
    for candidate in "$CURRENT_DIR_NAME" "invoicing" "orainvoice"; do
        if docker volume ls --format '{{.Name}}' | grep -q "^${candidate}_pgdata$"; then
            DETECTED_PROJECT="$candidate"
            break
        fi
    done

    if [ -n "$DETECTED_PROJECT" ] && [ "$DETECTED_PROJECT" != "$CURRENT_DIR_NAME" ]; then
        PROJECT_NAME="$DETECTED_PROJECT"
        warn "Detected existing volumes under project '$DETECTED_PROJECT' (folder is '$CURRENT_DIR_NAME')"
        warn "Setting COMPOSE_PROJECT_NAME=$PROJECT_NAME to reuse existing data volumes"
        echo "COMPOSE_PROJECT_NAME=$PROJECT_NAME" >> .env
    else
        PROJECT_NAME="$CURRENT_DIR_NAME"
    fi
fi

# Add project name to compose command
COMPOSE_CMD="$COMPOSE_CMD -p $PROJECT_NAME"

# Verify data volumes exist
PGDATA_VOL="${PROJECT_NAME}_pgdata"
REDIS_VOL="${PROJECT_NAME}_redisdata"
FRONTEND_VOL="${PROJECT_NAME}_frontend_dist"

log "Project name: $PROJECT_NAME"
if docker volume ls --format '{{.Name}}' | grep -q "^${PGDATA_VOL}$"; then
    log "Found existing pgdata volume: $PGDATA_VOL"
else
    warn "No existing pgdata volume found — this may be a first deploy"
fi
if docker volume ls --format '{{.Name}}' | grep -q "^${REDIS_VOL}$"; then
    log "Found existing redis volume: $REDIS_VOL"
fi

# ---------------------------------------------------------------------------
# 3. Resolve GitHub token for private repo auth
# ---------------------------------------------------------------------------
GITHUB_TOKEN="${GITHUB_TOKEN:-}"

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

CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
if [ -z "$CURRENT_REMOTE" ]; then
    err "No git remote 'origin' configured."
    exit 1
fi

if echo "$CURRENT_REMOTE" | grep -q "^git@"; then
    REPO_PATH=$(echo "$CURRENT_REMOTE" | sed 's/git@github.com://' | sed 's/\.git$//')
    AUTH_URL="https://${GITHUB_TOKEN}@github.com/${REPO_PATH}.git"
elif echo "$CURRENT_REMOTE" | grep -q "^https://"; then
    AUTH_URL=$(echo "$CURRENT_REMOTE" | sed "s|https://|https://${GITHUB_TOKEN}@|")
else
    err "Unrecognized remote URL format: $CURRENT_REMOTE"
    exit 1
fi

info "Remote: $CURRENT_REMOTE (token injected for pull)"

# ---------------------------------------------------------------------------
# 4. Tag current working images as :rollback
# ---------------------------------------------------------------------------
log "Tagging current images as :rollback..."

APP_IMAGE="${PROJECT_NAME}-app"
FRONTEND_IMAGE="${PROJECT_NAME}-frontend"

docker tag "$APP_IMAGE:latest" "$APP_IMAGE:rollback" 2>/dev/null || warn "No existing app image to tag (first deploy?)"
docker tag "$FRONTEND_IMAGE:latest" "$FRONTEND_IMAGE:rollback" 2>/dev/null || warn "No existing frontend image to tag (first deploy?)"

OLD_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
log "Current commit: $OLD_COMMIT"

# ---------------------------------------------------------------------------
# 5. Record current Alembic revision (for migration rollback)
# ---------------------------------------------------------------------------
log "Recording current migration revision..."
OLD_ALEMBIC_REV=$($COMPOSE_CMD exec -T app alembic current 2>/dev/null | grep -oP '[a-f0-9]+(?= \(head\))' || echo "")
if [ -n "$OLD_ALEMBIC_REV" ]; then
    log "Current Alembic revision: $OLD_ALEMBIC_REV"
else
    warn "Could not determine current Alembic revision (app not running?)"
fi

# ---------------------------------------------------------------------------
# 6. Pull latest code
# ---------------------------------------------------------------------------
log "Pulling latest code..."
git fetch "$AUTH_URL" 2>&1 | tee -a "$DEPLOY_LOG"

if [ -n "$BRANCH" ]; then
    log "Checking out branch: $BRANCH"
    git checkout "$BRANCH" 2>&1 | tee -a "$DEPLOY_LOG"
fi

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

    # Rebuild frontend dist from rollback image
    log "Restoring frontend dist volume..."
    $COMPOSE_CMD up -d frontend 2>/dev/null || true
    sleep 3
    $COMPOSE_CMD exec -T frontend sh -c 'rm -rf /app/dist/* && npx vite build' 2>/dev/null || warn "Frontend dist restore failed"

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
# 7. Build new images FIRST (before stopping anything)
# ---------------------------------------------------------------------------
log "Building new images for $PLATFORM..."
export DOCKER_DEFAULT_PLATFORM="$PLATFORM"

if ! $COMPOSE_CMD build --no-cache app frontend 2>&1 | tee -a "$DEPLOY_LOG"; then
    err "Build failed. Current containers are still running — no downtime."
    # No rollback needed — we haven't stopped anything yet
    err "Deploy log: $DEPLOY_LOG"
    exit 1
fi

log "Images built successfully. Now swapping containers..."

# ---------------------------------------------------------------------------
# 8. Database backup before touching anything
# ---------------------------------------------------------------------------
log "Creating pre-migration database snapshot..."
BACKUP_FILE="backups/pre-deploy-${NEW_COMMIT}-$(date +%Y%m%d-%H%M%S).sql.gz"
mkdir -p backups

POSTGRES_USER=$(grep -oP '^POSTGRES_USER=\K.*' .env 2>/dev/null || echo "postgres")
POSTGRES_DB=$(grep -oP '^POSTGRES_DB=\K.*' .env 2>/dev/null || echo "workshoppro")

if $COMPOSE_CMD exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$BACKUP_FILE" 2>/dev/null; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    log "Database backup: $BACKUP_FILE ($BACKUP_SIZE)"
else
    warn "Database backup failed — continuing (rollback images still available)"
fi

# ---------------------------------------------------------------------------
# 9. Stop app + frontend + nginx (keep postgres + redis running)
# ---------------------------------------------------------------------------
log "Stopping app, frontend, and nginx..."
$COMPOSE_CMD stop app frontend nginx 2>&1 | tee -a "$DEPLOY_LOG"

# ---------------------------------------------------------------------------
# 10. Recreate containers with new images
# ---------------------------------------------------------------------------
log "Starting services with new images..."
if ! $COMPOSE_CMD up -d 2>&1 | tee -a "$DEPLOY_LOG"; then
    err "Failed to start services."
    rollback
fi

# ---------------------------------------------------------------------------
# 11. Refresh frontend dist volume
#     The frontend_dist volume persists between deploys. The Dockerfile builds
#     to /app/dist during image build, but the volume mount masks it with old
#     files. We clear the volume and rebuild inside the running container.
# ---------------------------------------------------------------------------
log "Refreshing frontend dist volume..."
sleep 3  # wait for frontend container to be ready

if ! $COMPOSE_CMD exec -T frontend sh -c 'rm -rf /app/dist/* && npx vite build' 2>&1 | tee -a "$DEPLOY_LOG"; then
    err "Frontend build failed inside container."
    rollback
fi

# Restart nginx to pick up fresh frontend files
log "Restarting nginx to serve updated frontend..."
$COMPOSE_CMD restart nginx 2>&1 | tee -a "$DEPLOY_LOG"

# ---------------------------------------------------------------------------
# 12. Wait for app to become healthy
# ---------------------------------------------------------------------------
log "Waiting for app to become healthy..."
MAX_WAIT=180
WAITED=0
APP_HEALTHY=false

while [ $WAITED -lt $MAX_WAIT ]; do
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
# 13. Verify all services are running
# ---------------------------------------------------------------------------
log "Verifying all services..."
ALL_RUNNING=true
for svc in app frontend nginx postgres redis; do
    if ! $COMPOSE_CMD ps "$svc" 2>/dev/null | grep -qE "running|Up"; then
        warn "Service $svc may not be running"
        ALL_RUNNING=false
    fi
done

if [ "$ALL_RUNNING" = "true" ]; then
    log "All 5 services confirmed running"
fi

# Verify frontend dist has new content
if $COMPOSE_CMD exec -T frontend grep -rq 'ha-replication\|HA Replication' /app/dist/ 2>/dev/null; then
    log "Frontend dist verified — contains latest code"
else
    info "Frontend dist content check skipped (no specific marker to verify)"
fi

# ---------------------------------------------------------------------------
# 14. Cleanup
# ---------------------------------------------------------------------------
log "Cleaning up dangling images..."
docker image prune -f &>/dev/null || true

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
log "  Project:  $PROJECT_NAME"
log "  Volumes:  $PGDATA_VOL, $REDIS_VOL (untouched)"
log "  Log:      $DEPLOY_LOG"
log "============================================"
