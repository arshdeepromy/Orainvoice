#!/bin/bash
set -euo pipefail

PHASE="phase5"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Dependency Upgrade: ${PHASE} ==="
echo "Phase 5: Dependency Elimination"
echo "  Remove passlib; keep gunicorn, python-dateutil, email-validator"
echo ""

# 1. Checkpoint
echo "--- Step 1: Creating rollback checkpoint ---"
"$SCRIPT_DIR/create_rollback_checkpoint.sh" "$PHASE"

# 2. Pre-verify encrypted settings
echo "--- Step 2: Pre-upgrade encrypted settings verification ---"
python "$SCRIPT_DIR/verify_encrypted_settings.py" --phase "$PHASE" --stage pre

# 3a. Remove passlib from pyproject.toml (already removed from pyproject.toml)
echo "--- Step 3a: Verifying passlib removal ---"
if grep -q "passlib" pyproject.toml 2>/dev/null; then
  echo "    Removing passlib from pyproject.toml..."
  sed -i 's/.*passlib.*//' pyproject.toml
  sed -i '/^$/N;/^\n$/d' pyproject.toml
else
  echo "    OK: passlib already removed from pyproject.toml"
fi
echo "    Verifying no application code imports passlib..."
if grep -r "from passlib\|import passlib" app/ 2>/dev/null; then
  echo "ERROR: passlib imports found in app/ — cannot remove dependency"
  exit 1
else
  echo "    OK: No passlib imports in app/"
fi

# 3b. gunicorn — KEPT (actively used in Dockerfile CMD and docker-compose files)
echo "--- Step 3b: gunicorn evaluation ---"
echo "    KEPT: gunicorn is the production process manager"
echo "    Used in: Dockerfile CMD, docker-compose.pi.yml, docker-compose.pi-standby.yml, docker-compose.standby-prod.yml"

# 3c. python-dateutil — KEPT (relativedelta used for month/year arithmetic)
echo "--- Step 3c: python-dateutil evaluation ---"
echo "    KEPT: dateutil.relativedelta used for month/year date arithmetic in 6+ files"
echo "    datetime.timedelta cannot handle month/year offsets — no stdlib replacement"

# 3d. email-validator — KEPT (required by Pydantic EmailStr)
echo "--- Step 3d: email-validator evaluation ---"
echo "    KEPT: Pydantic EmailStr is used in auth, admin, organisations, and bookings schemas"
echo "    email-validator is a required dependency for Pydantic's EmailStr type"

# 4. Verify clean install
echo "--- Step 4: Verifying clean pip install ---"
pip install .

# 5. Unit + Property tests
echo "--- Step 5: Running unit and property tests ---"
pytest tests/ -x --tb=short

# 6. E2E regression tests (Phase 1 only)
echo "--- Step 6: Running E2E regression tests (Phase 1) ---"
npx playwright test tests/e2e/frontend/upgrade-validation.spec.ts --grep "Phase 1"

# 7. Post-verify encrypted settings
echo "--- Step 7: Post-upgrade encrypted settings verification ---"
python "$SCRIPT_DIR/verify_encrypted_settings.py" --phase "$PHASE" --stage post

echo ""
echo "=== ${PHASE} COMPLETE ==="
