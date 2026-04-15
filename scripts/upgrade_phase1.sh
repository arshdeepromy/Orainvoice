#!/bin/bash
set -euo pipefail

PHASE="phase1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Dependency Upgrade: ${PHASE} ==="
echo "Phase 1: Security Patches"
echo "  cryptography, certifi, pydantic, pydantic-settings, SQLAlchemy, hypothesis, webauthn"
echo "  @headlessui/react, @types/node, axios, fast-check, postcss"
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
  cryptography==46.0.7 \
  certifi==2026.2.25 \
  pydantic==2.12.5 \
  pydantic-settings==2.13.1 \
  SQLAlchemy==2.0.49 \
  hypothesis==6.151.12 \
  webauthn==2.7.1

# 3b. Upgrade frontend dependencies
echo "--- Step 3b: Upgrading frontend dependencies ---"
cd frontend && npm install \
  @headlessui/react@2.2.10 \
  @types/node@25.6.0 \
  axios@1.15.0 \
  fast-check@4.6.0 \
  postcss@8.5.9
cd ..

# 4. Unit + Property tests
echo "--- Step 4: Running unit and property tests ---"
pytest tests/ -x --tb=short

# 5. E2E tests
echo "--- Step 5: Running E2E validation tests (Phase 1) ---"
npx playwright test tests/e2e/frontend/upgrade-validation.spec.ts --grep "Phase 1"

# 6. Post-verify encrypted settings
echo "--- Step 6: Post-upgrade encrypted settings verification ---"
python "$SCRIPT_DIR/verify_encrypted_settings.py" --phase "$PHASE" --stage post

echo ""
echo "=== ${PHASE} COMPLETE ==="
