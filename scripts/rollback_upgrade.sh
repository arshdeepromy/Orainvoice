#!/bin/bash
set -euo pipefail

# ---------------------------------------------------------------------------
# rollback_upgrade.sh
#
# Reverts the application to a pre-upgrade rollback checkpoint by:
#   1. Finding the most recent Git tag for the given phase
#   2. Checking out the tagged code
#   3. Rebuilding the Docker app service from the tagged code
#   4. Running the encrypted settings verifier (rollback stage)
#   5. Printing smoke test instructions
#
# Optionally restores the database dump if --restore-db is passed.
#
# Usage:
#   ./scripts/rollback_upgrade.sh <phase_name>
#   ./scripts/rollback_upgrade.sh <phase_name> --restore-db
#
# Examples:
#   ./scripts/rollback_upgrade.sh phase1
#   ./scripts/rollback_upgrade.sh phase2 --restore-db
# ---------------------------------------------------------------------------

usage() {
  echo "Usage: $0 <phase_name> [--restore-db]"
  echo "Example: $0 phase1"
  echo "         $0 phase2 --restore-db"
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

PHASE="$1"
RESTORE_DB=false

shift
while [ $# -gt 0 ]; do
  case "$1" in
    --restore-db)
      RESTORE_DB=true
      shift
      ;;
    *)
      echo "ERROR: Unknown argument: $1"
      usage
      ;;
  esac
done

# Database connection defaults match docker-compose.dev.yml
PGUSER="${POSTGRES_USER:-postgres}"
PGPASSWORD="${POSTGRES_PASSWORD:-postgres}"
PGDATABASE="${POSTGRES_DB:-workshoppro}"
PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5434}"

# --- 1. Find the most recent Git tag for this phase ---
echo "==> Looking for rollback tag matching: pre-dependency-upgrade-${PHASE}-*"

GIT_TAG=$(git tag --list "pre-dependency-upgrade-${PHASE}-*" --sort=-version:refname | head -1)

if [ -z "$GIT_TAG" ]; then
  echo "ERROR: No Git tag found matching 'pre-dependency-upgrade-${PHASE}-*'"
  echo "Available rollback tags:"
  git tag --list "pre-dependency-upgrade-*" || echo "  (none)"
  exit 1
fi

echo "    Found tag: ${GIT_TAG}"

# --- 2. Optionally restore the database dump ---
if [ "$RESTORE_DB" = true ]; then
  echo ""
  echo "==> Restoring database from backup..."

  # Find the most recent dump file for this phase
  DUMP_FILE=$(ls -t backups/pre_upgrade_${PHASE}_*.dump 2>/dev/null | head -1)

  if [ -z "$DUMP_FILE" ]; then
    echo "ERROR: No database dump found matching 'backups/pre_upgrade_${PHASE}_*.dump'"
    echo "Available dumps:"
    ls -1 backups/pre_upgrade_*.dump 2>/dev/null || echo "  (none)"
    exit 1
  fi

  echo "    Restoring from: ${DUMP_FILE}"
  PGPASSWORD="$PGPASSWORD" pg_restore --clean --if-exists \
    -h "$PGHOST" \
    -p "$PGPORT" \
    -U "$PGUSER" \
    -d "$PGDATABASE" \
    "$DUMP_FILE"
  echo "    Database restored successfully."
fi

# --- 3. Check out the Git tag ---
echo ""
echo "==> Checking out Git tag: ${GIT_TAG}"

# Check for uncommitted changes
if ! git diff --quiet HEAD 2>/dev/null || ! git diff --cached --quiet HEAD 2>/dev/null; then
  echo "WARNING: You have uncommitted changes. Stashing them before checkout..."
  git stash push -m "rollback-upgrade-${PHASE}-autostash"
fi

git checkout "$GIT_TAG"
echo "    Checked out: ${GIT_TAG}"

# --- 4. Rebuild Docker app service ---
echo ""
echo "==> Rebuilding Docker app service from rolled-back code..."
docker compose up -d --build --force-recreate app
echo "    Docker app service rebuilt and running."

# --- 5. Run encrypted settings verifier ---
echo ""
echo "==> Running encrypted settings verifier (rollback stage)..."
python scripts/verify_encrypted_settings.py --phase "$PHASE" --stage rollback
echo "    Encrypted settings verification complete."

# --- 6. Smoke test instructions ---
echo ""
echo "==========================================="
echo "  ROLLBACK COMPLETE — ${PHASE}"
echo "==========================================="
echo ""
echo "  Git tag  : ${GIT_TAG}"
if [ "$RESTORE_DB" = true ]; then
  echo "  DB dump  : ${DUMP_FILE} (restored)"
fi
echo ""
echo "  Smoke Test Instructions:"
echo "  ────────────────────────"
echo "  1. Open the app in your browser (http://localhost or your configured URL)"
echo "  2. Log in with your admin credentials"
echo "  3. Verify the dashboard loads correctly"
echo "  4. Check that key data is visible (customers, invoices, integrations)"
echo "  5. Confirm MFA works if enabled on your account"
echo ""
echo "  If smoke tests fail, the pre-upgrade Docker image is available:"
echo "    docker run invoicing-app:pre-upgrade-${PHASE}"
echo ""
echo "==========================================="
