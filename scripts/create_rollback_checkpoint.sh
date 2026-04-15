#!/bin/bash
set -euo pipefail

# ---------------------------------------------------------------------------
# create_rollback_checkpoint.sh
#
# Creates a three-part rollback checkpoint before a dependency upgrade phase:
#   1. PostgreSQL database dump  (pg_dump -Fc)
#   2. Git tag                   (pre-dependency-upgrade-<phase>-<date>)
#   3. Docker image tag          (invoicing-app:pre-upgrade-<phase>)
#
# Usage:
#   ./scripts/create_rollback_checkpoint.sh <phase_name>
#   Example: ./scripts/create_rollback_checkpoint.sh phase1
# ---------------------------------------------------------------------------

if [ $# -lt 1 ]; then
  echo "Usage: $0 <phase_name>"
  echo "Example: $0 phase1"
  exit 1
fi

PHASE="$1"
DATE=$(date +%Y-%m-%d)

# Database connection defaults match docker-compose.dev.yml
PGUSER="${POSTGRES_USER:-postgres}"
PGPASSWORD="${POSTGRES_PASSWORD:-postgres}"
PGDATABASE="${POSTGRES_DB:-workshoppro}"
PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5434}"

DUMP_DIR="backups"
DUMP_FILE="${DUMP_DIR}/pre_upgrade_${PHASE}_${DATE}.dump"
GIT_TAG="pre-dependency-upgrade-${PHASE}-${DATE}"
DOCKER_TAG="invoicing-app:pre-upgrade-${PHASE}"

# --- 1. Database dump ---
echo "==> Creating backups directory..."
mkdir -p "$DUMP_DIR"

echo "==> Dumping database to ${DUMP_FILE}..."
PGPASSWORD="$PGPASSWORD" pg_dump -Fc \
  -h "$PGHOST" \
  -p "$PGPORT" \
  -U "$PGUSER" \
  -d "$PGDATABASE" \
  -f "$DUMP_FILE"
echo "    Database dump complete: ${DUMP_FILE}"

# --- 2. Git tag ---
echo "==> Creating Git tag: ${GIT_TAG}..."
git tag -a "$GIT_TAG" -m "Pre-upgrade checkpoint for ${PHASE} on ${DATE}"
echo "    Git tag created: ${GIT_TAG}"

# --- 3. Docker image tag ---
echo "==> Tagging Docker image as ${DOCKER_TAG}..."
# Identify the current app service image from docker compose
APP_IMAGE=$(docker compose images app --format json | python -c "import sys,json; imgs=json.loads(sys.stdin.read()); print(imgs[0]['Repository']+':'+imgs[0]['Tag'])" 2>/dev/null || true)

if [ -z "$APP_IMAGE" ] || [ "$APP_IMAGE" = ":" ]; then
  # Fallback: find the image by compose project label
  APP_IMAGE=$(docker compose images app -q 2>/dev/null | head -1 || true)
  if [ -n "$APP_IMAGE" ]; then
    docker tag "$APP_IMAGE" "$DOCKER_TAG"
  else
    echo "    WARNING: Could not find app service image. Skipping Docker tag."
    echo "    Run 'docker compose build app' first if the image hasn't been built."
  fi
else
  docker tag "$APP_IMAGE" "$DOCKER_TAG"
fi
echo "    Docker image tagged: ${DOCKER_TAG}"

# --- Summary ---
echo ""
echo "=== Rollback checkpoint created for ${PHASE} ==="
echo "  DB dump : ${DUMP_FILE}"
echo "  Git tag : ${GIT_TAG}"
echo "  Docker  : ${DOCKER_TAG}"
echo ""
