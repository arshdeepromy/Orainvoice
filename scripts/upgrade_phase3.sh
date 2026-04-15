#!/bin/bash
set -euo pipefail

PHASE="phase3"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Dependency Upgrade: ${PHASE} ==="
echo "Phase 3: Third-Party Integration Majors"
echo "  stripe, redis, twilio (backend)"
echo "  @stripe/react-stripe-js, @stripe/stripe-js, firebase (frontend)"
echo ""

# 1. Checkpoint
echo "--- Step 1: Creating rollback checkpoint ---"
"$SCRIPT_DIR/create_rollback_checkpoint.sh" "$PHASE"

# 2. Pre-verify encrypted settings
echo "--- Step 2: Pre-upgrade encrypted settings verification ---"
python "$SCRIPT_DIR/verify_encrypted_settings.py" --phase "$PHASE" --stage pre

# 3. Upgrade backend dependencies
echo "--- Step 3a: Upgrading backend dependencies ---"
pip install \
  stripe==15.0.1 \
  redis==7.4.0 \
  twilio==9.10.4

# 3b. Upgrade frontend dependencies
echo "--- Step 3b: Upgrading frontend dependencies ---"
cd frontend && npm install \
  @stripe/react-stripe-js@6 \
  @stripe/stripe-js@9 \
  firebase@12.12.0
cd ..

# 4. Unit + Property tests
echo "--- Step 4: Running unit and property tests ---"
pytest tests/ -x --tb=short

# 5. E2E tests (Phase 1 + Phase 2 + Phase 3)
echo "--- Step 5: Running E2E validation tests (Phase 1 + Phase 2 + Phase 3) ---"
npx playwright test tests/e2e/frontend/upgrade-validation.spec.ts --grep "Phase 1|Phase 2|Phase 3"

# 6. Post-verify encrypted settings
echo "--- Step 6: Post-upgrade encrypted settings verification ---"
python "$SCRIPT_DIR/verify_encrypted_settings.py" --phase "$PHASE" --stage post

echo ""
echo "=== ${PHASE} COMPLETE ==="
