#!/bin/bash
set -euo pipefail

PHASE="phase2"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Dependency Upgrade: ${PHASE} ==="
echo "Phase 2: Safe Minor Upgrades"
echo "  fastapi, uvicorn, alembic, PyJWT, pillow, reportlab, requests, httpx"
echo ""

# 1. Checkpoint
echo "--- Step 1: Creating rollback checkpoint ---"
"$SCRIPT_DIR/create_rollback_checkpoint.sh" "$PHASE"

# 2. Pre-verify encrypted settings
echo "--- Step 2: Pre-upgrade encrypted settings verification ---"
python "$SCRIPT_DIR/verify_encrypted_settings.py" --phase "$PHASE" --stage pre

# 3. Upgrade backend dependencies
echo "--- Step 3: Upgrading backend dependencies ---"
pip install \
  fastapi==0.135.3 \
  uvicorn==0.44.0 \
  alembic==1.18.4 \
  PyJWT==2.12.1 \
  pillow==12.2.0 \
  reportlab==4.4.10 \
  requests==2.33.1 \
  httpx==0.28.1

# 4. Unit + Property tests
echo "--- Step 4: Running unit and property tests ---"
pytest tests/ -x --tb=short

# 5. E2E tests (Phase 1 + Phase 2)
echo "--- Step 5: Running E2E validation tests (Phase 1 + Phase 2) ---"
npx playwright test tests/e2e/frontend/upgrade-validation.spec.ts --grep "Phase 1|Phase 2"

# 6. Post-verify encrypted settings
echo "--- Step 6: Post-upgrade encrypted settings verification ---"
python "$SCRIPT_DIR/verify_encrypted_settings.py" --phase "$PHASE" --stage post

echo ""
echo "=== ${PHASE} COMPLETE ==="
