#!/bin/bash
# ==========================================================================
# OraInvoice — Production Update Script
# ==========================================================================
# Run directly on the production server (Pi or any Linux host).
# Downloads latest code from GitHub, backs up data, builds fresh images,
# and deploys with automatic rollback on failure.
#
# Usage:
#   ./scripts/update.sh                  # Full update (backend + frontend)
#   ./scripts/update.sh --backend-only   # Backend only (skip frontend rebuild)
#   ./scripts/update.sh --rollback       # Rollback to previous images
#
# Requirements:
#   - docker and docker compose installed
#   - curl installed
#   - Internet access to GitHub
#   - Must be run from the project root (/home/nerdy/invoicing)
# ==========================================================================

set -e

# --------------------------------------------------------------------------
# Configuration — auto-detected, override with env vars if needed
# --------------------------------------------------------------------------
REPO_URL="${REPO_URL:-https://github.com/arshdeepromy/Orainvoice/archive/refs/heads/main.tar.gz}"
PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
BACKUP_DIR="${BACKUP_DIR:-$HOME}"
DB_CONTAINER="${DB_CONTAINER:-$(docker ps --format '{{.Names}}' | grep postgres | head -1)}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-workshoppro}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
MAX_BACKUPS=10  # Keep last N backups, delete older ones

# Auto-detect compose files
if [ -f "$PROJECT_DIR/docker-compose.pi.yml" ]; then
    COMPOSE_CMD="docker compose -f docker-compose.yml -f docker-compose.pi.yml"
elif [ -f "$PROJECT_DIR/docker-compose.dev.yml" ]; then
    COMPOSE_CMD="docker compose -f docker-compose.yml -f docker-compose.dev.yml"
else
    COMPOSE_CMD="docker compose"
fi

# Files that must NEVER be overwritten by code sync
PROTECTED_FILES=(
    ".env"
    ".env.pi"
    "docker-compose.pi.yml"
    "certs/"
)

# --------------------------------------------------------------------------
# Colours and logging
# --------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No colour

log()   { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $*"; }
ok()    { echo -e "${GREEN}[$(date +%H:%M:%S)] ✓${NC} $*"; }
warn()  { echo -e "${YELLOW}[$(date +%H:%M:%S)] ⚠${NC} $*"; }
fail()  { echo -e "${RED}[$(date +%H:%M:%S)] ✗${NC} $*"; }

# --------------------------------------------------------------------------
# Pre-flight checks
# --------------------------------------------------------------------------
preflight() {
    log "Running pre-flight checks..."

    # Must be in project directory
    if [ ! -f "$PROJECT_DIR/docker-compose.yml" ]; then
        fail "docker-compose.yml not found. Run this script from the project root."
        exit 1
    fi

    # Docker must be running
    if ! docker info >/dev/null 2>&1; then
        fail "Docker is not running."
        exit 1
    fi

    # curl must be available
    if ! command -v curl >/dev/null 2>&1; then
        fail "curl is not installed."
        exit 1
    fi

    # Database container must be running
    if [ -z "$DB_CONTAINER" ]; then
        warn "No PostgreSQL container found — skipping database backup."
    fi

    ok "Pre-flight checks passed"
}

# --------------------------------------------------------------------------
# Step 1: Backup database
# --------------------------------------------------------------------------
backup_database() {
    if [ -z "$DB_CONTAINER" ]; then
        warn "Skipping database backup (no postgres container)"
        return 0
    fi

    log "Backing up database..."
    mkdir -p "$BACKUP_DIR" 2>/dev/null || true

    # If backup dir isn't writable, fall back to /tmp
    if [ ! -w "$BACKUP_DIR" ]; then
        BACKUP_DIR="/tmp"
        warn "Cannot write to $BACKUP_DIR — using /tmp"
    fi

    BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sql.gz"
    log "  Target: $BACKUP_FILE"

    if docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"; then
        local size
        size=$(du -h "$BACKUP_FILE" | cut -f1)
        ok "Database backup complete ($size)"
    else
        fail "Database backup FAILED"
        exit 1
    fi

    # Verify backup is not empty
    if [ ! -s "$BACKUP_FILE" ]; then
        fail "Backup file is empty — aborting"
        rm -f "$BACKUP_FILE"
        exit 1
    fi

    # Rotate old backups — keep only the last N
    local count
    count=$(ls -1 "$BACKUP_DIR"/${DB_NAME}_*.sql.gz 2>/dev/null | wc -l)
    if [ "$count" -gt "$MAX_BACKUPS" ]; then
        local to_delete=$((count - MAX_BACKUPS))
        ls -1t "$BACKUP_DIR"/${DB_NAME}_*.sql.gz | tail -n "$to_delete" | xargs rm -f
        log "Rotated $to_delete old backup(s)"
    fi
}

# --------------------------------------------------------------------------
# Step 2: Tag current images for rollback
# --------------------------------------------------------------------------
tag_rollback_images() {
    log "Tagging current images for rollback..."

    # Tag current app image (ignore errors if no image exists)
    local app_image
    app_image=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^(invoicing|orainvoice)-app:latest' | head -1) || true
    if [ -n "$app_image" ]; then
        docker tag "$app_image" "${app_image%%:*}:rollback" 2>/dev/null && ok "Tagged app image for rollback" || true
    fi

    # Tag current frontend image (ignore errors if no image exists)
    local fe_image
    fe_image=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^(invoicing|orainvoice)-frontend:latest' | head -1) || true
    if [ -n "$fe_image" ]; then
        docker tag "$fe_image" "${fe_image%%:*}:rollback" 2>/dev/null && ok "Tagged frontend image for rollback" || true
    fi

    ok "Rollback images tagged"
}

# --------------------------------------------------------------------------
# Step 3: Download latest code from GitHub
# --------------------------------------------------------------------------
download_code() {
    log "Downloading latest code from GitHub..."

    local tmp_dir="$HOME/_update_tmp_$$"
    local tar_file="$tmp_dir/code.tar.gz"

    mkdir -p "$tmp_dir"
    trap "rm -rf $tmp_dir" EXIT

    # Download
    if ! curl -sL -o "$tar_file" "$REPO_URL"; then
        fail "Failed to download code from GitHub"
        exit 1
    fi

    # Verify it's a valid gzip
    if ! gzip -t "$tar_file" 2>/dev/null; then
        fail "Downloaded file is not a valid archive"
        exit 1
    fi

    ok "Downloaded code archive"

    # Extract
    cd "$tmp_dir"
    tar -xzf code.tar.gz
    local extracted_dir
    extracted_dir=$(ls -d */ | head -1)

    if [ -z "$extracted_dir" ]; then
        fail "No directory found after extraction"
        exit 1
    fi

    # Build rsync exclude list from protected files
    local exclude_args=""
    for f in "${PROTECTED_FILES[@]}"; do
        exclude_args="$exclude_args --exclude=$f"
    done

    # Sync code — protect env files, certs, and Pi-specific compose
    # shellcheck disable=SC2086
    rsync -a --delete \
        $exclude_args \
        --exclude='frontend/dist' \
        --exclude='__pycache__' \
        --exclude='.hypothesis' \
        --exclude='.git' \
        "$extracted_dir/" "$PROJECT_DIR/"

    ok "Code synced to $PROJECT_DIR"

    # Clean up
    cd "$PROJECT_DIR"
    rm -rf "$tmp_dir"
    trap - EXIT
}

# --------------------------------------------------------------------------
# Step 4: Build fresh images (no cache)
# --------------------------------------------------------------------------
build_images() {
    local backend_only="${1:-false}"

    log "Building fresh Docker images (no cache)..."

    # Get git SHA from the downloaded code (VERSION file or git log from GitHub API)
    local git_sha="unknown"
    local build_date
    build_date="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    # Try to get the latest commit SHA from GitHub API
    git_sha=$(curl -sf "https://api.github.com/repos/arshdeepromy/Orainvoice/commits/main" 2>/dev/null | grep -m1 '"sha"' | cut -d'"' -f4 | head -c 8) || true
    if [ -z "$git_sha" ]; then
        git_sha="unknown"
    fi

    local version="unknown"
    if [ -f "$PROJECT_DIR/VERSION" ]; then
        version=$(cat "$PROJECT_DIR/VERSION" | tr -d '[:space:]')
    fi

    log "  Version: $version | SHA: $git_sha | Date: $build_date"

    # Build app image
    log "  Building app image..."
    if $COMPOSE_CMD build --no-cache --build-arg GIT_SHA="$git_sha" --build-arg BUILD_DATE="$build_date" app 2>&1 | tail -5; then
        ok "App image built"
    else
        fail "App image build FAILED"
        return 1
    fi

    if [ "$backend_only" = "false" ]; then
        # Build frontend image — includes npm install + vite build
        log "  Building frontend image..."
        if $COMPOSE_CMD build --no-cache frontend 2>&1 | tail -5; then
            ok "Frontend image built"
        else
            fail "Frontend image build FAILED"
            return 1
        fi
    fi

    ok "All images built successfully"
}

# --------------------------------------------------------------------------
# Step 5: Deploy — swap containers with minimal downtime
# --------------------------------------------------------------------------
deploy() {
    local backend_only="${1:-false}"

    log "Deploying new containers..."

    if [ "$backend_only" = "true" ]; then
        # Backend only — just recreate the app container
        # Docker builds first, then swaps (minimal downtime)
        if $COMPOSE_CMD up -d --force-recreate app 2>&1; then
            ok "App container deployed"
        else
            fail "App deployment FAILED"
            return 1
        fi
    else
        # Full deploy — stop frontend+nginx, remove old volume, start fresh
        log "  Stopping frontend + nginx..."
        $COMPOSE_CMD stop frontend nginx 2>/dev/null || true
        $COMPOSE_CMD rm -f frontend nginx 2>/dev/null || true

        # Remove old frontend dist volume to force fresh copy from new image
        local project_name
        project_name=$($COMPOSE_CMD config --format json 2>/dev/null | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4)
        if [ -n "$project_name" ]; then
            docker volume rm "${project_name}_frontend_dist" 2>/dev/null || true
        fi

        # Recreate all service containers
        if $COMPOSE_CMD up -d --force-recreate app frontend nginx 2>&1; then
            ok "All containers deployed"
        else
            fail "Deployment FAILED"
            return 1
        fi
    fi
}

# --------------------------------------------------------------------------
# Step 6: Health check — verify the app is responding
# --------------------------------------------------------------------------
health_check() {
    log "Running health checks..."

    local max_wait=60
    local waited=0

    # Wait for app container to be running
    while [ $waited -lt $max_wait ]; do
        local status
        status=$(docker inspect --format='{{.State.Status}}' "$($COMPOSE_CMD ps -q app 2>/dev/null)" 2>/dev/null || echo "unknown")
        if [ "$status" = "running" ]; then
            break
        fi
        sleep 2
        waited=$((waited + 2))
    done

    if [ $waited -ge $max_wait ]; then
        fail "App container did not start within ${max_wait}s"
        return 1
    fi

    # Wait for the app to respond to health check
    waited=0
    while [ $waited -lt $max_wait ]; do
        # Check from the host via the nginx port (the way real users access it)
        local app_port
        app_port=$(docker port "$($COMPOSE_CMD ps -q nginx 2>/dev/null)" 80 2>/dev/null | head -1 | cut -d: -f2) || true

        if [ -n "$app_port" ]; then
            if curl -sf "http://localhost:${app_port}/api/v1/health" >/dev/null 2>&1; then
                ok "App is healthy and responding"
                return 0
            fi
        fi

        # Fallback: check if the app container is running and not restarting
        local app_status
        app_status=$(docker inspect --format='{{.State.Status}}' "$($COMPOSE_CMD ps -q app 2>/dev/null)" 2>/dev/null || echo "unknown")
        local restart_count
        restart_count=$(docker inspect --format='{{.RestartCount}}' "$($COMPOSE_CMD ps -q app 2>/dev/null)" 2>/dev/null || echo "0")

        if [ "$app_status" = "running" ] && [ "$restart_count" = "0" ] && [ $waited -ge 15 ]; then
            ok "App container is running (no restarts)"
            return 0
        fi

        sleep 3
        waited=$((waited + 3))
    done

    # If health check fails, check logs for errors
    fail "App health check failed after ${max_wait}s"
    log "Last 20 lines of app logs:"
    $COMPOSE_CMD logs app --tail 20 2>&1
    return 1
}

# --------------------------------------------------------------------------
# Step 7: Clean up old Docker resources
# --------------------------------------------------------------------------
cleanup() {
    log "Cleaning up old Docker resources..."

    # Remove dangling images (old builds)
    docker image prune -f >/dev/null 2>&1 || true

    # Remove unused build cache
    docker builder prune -f >/dev/null 2>&1 || true

    ok "Cleanup complete"
}

# --------------------------------------------------------------------------
# Rollback — restore previous images
# --------------------------------------------------------------------------
rollback() {
    log "Rolling back to previous images..."

    # Find rollback-tagged images
    local app_rollback
    app_rollback=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep 'app:rollback' | head -1)
    local fe_rollback
    fe_rollback=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep 'frontend:rollback' | head -1)

    if [ -z "$app_rollback" ]; then
        fail "No rollback image found for app. Cannot rollback."
        exit 1
    fi

    # Re-tag rollback images as latest
    docker tag "$app_rollback" "${app_rollback%%:*}:latest"
    ok "Restored app image"

    if [ -n "$fe_rollback" ]; then
        docker tag "$fe_rollback" "${fe_rollback%%:*}:latest"
        ok "Restored frontend image"
    fi

    # Restart containers with the restored images
    $COMPOSE_CMD stop frontend nginx 2>/dev/null || true
    $COMPOSE_CMD rm -f frontend nginx 2>/dev/null || true

    local project_name
    project_name=$($COMPOSE_CMD config --format json 2>/dev/null | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4)
    if [ -n "$project_name" ]; then
        docker volume rm "${project_name}_frontend_dist" 2>/dev/null || true
    fi

    $COMPOSE_CMD up -d --force-recreate app frontend nginx 2>&1

    ok "Rollback complete"

    # Restore database if needed
    local latest_backup
    latest_backup=$(ls -1t "$BACKUP_DIR"/${DB_NAME}_*.sql.gz 2>/dev/null | head -1)
    if [ -n "$latest_backup" ]; then
        warn "Database backup available at: $latest_backup"
        warn "To restore: gunzip -c $latest_backup | docker exec -i $DB_CONTAINER psql -U $DB_USER $DB_NAME"
    fi
}

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
main() {
    local backend_only=false
    local do_rollback=false

    # Parse arguments
    for arg in "$@"; do
        case "$arg" in
            --backend-only) backend_only=true ;;
            --rollback)     do_rollback=true ;;
            --help|-h)
                echo "Usage: $0 [--backend-only] [--rollback]"
                echo ""
                echo "Options:"
                echo "  --backend-only   Only update the backend (skip frontend rebuild)"
                echo "  --rollback       Rollback to previous images"
                echo ""
                echo "Environment variables:"
                echo "  REPO_URL         GitHub archive URL (default: OraInvoice main branch)"
                echo "  PROJECT_DIR      Project root directory (default: current directory)"
                echo "  BACKUP_DIR       Backup directory (default: ~/backups)"
                exit 0
                ;;
            *)
                fail "Unknown argument: $arg"
                exit 1
                ;;
        esac
    done

    echo ""
    echo "=========================================="
    echo "  OraInvoice Update — $(date '+%Y-%m-%d %H:%M')"
    echo "=========================================="
    echo ""

    # Handle rollback
    if [ "$do_rollback" = "true" ]; then
        preflight
        rollback
        health_check || warn "Health check failed after rollback — check logs"
        exit 0
    fi

    # Normal update flow
    local start_time
    start_time=$(date +%s)

    preflight
    backup_database
    tag_rollback_images
    download_code

    if build_images "$backend_only"; then
        if deploy "$backend_only"; then
            if health_check; then
                cleanup

                local end_time
                end_time=$(date +%s)
                local duration=$((end_time - start_time))

                echo ""
                echo "=========================================="
                ok "Update complete in ${duration}s"
                echo "=========================================="
                echo ""
            else
                fail "Health check failed — rolling back..."
                rollback
                health_check || fail "Rollback also failed — manual intervention needed"
                exit 1
            fi
        else
            fail "Deployment failed — rolling back..."
            rollback
            health_check || fail "Rollback also failed — manual intervention needed"
            exit 1
        fi
    else
        fail "Build failed — no changes deployed (old containers still running)"
        exit 1
    fi
}

main "$@"
