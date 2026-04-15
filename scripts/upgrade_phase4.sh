#!/bin/bash
set -euo pipefail

PHASE="phase4"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Dependency Upgrade: ${PHASE} ==="
echo "Phase 4: Major Frontend Overhaul"
echo "  react, react-dom, react-router-dom, tailwindcss, vite, vitest, typescript, jsdom"
echo "  @types/react, @types/react-dom"
echo ""

# 1. Checkpoint
echo "--- Step 1: Creating rollback checkpoint ---"
"$SCRIPT_DIR/create_rollback_checkpoint.sh" "$PHASE"

# 2. Pre-verify encrypted settings
echo "--- Step 2: Pre-upgrade encrypted settings verification ---"
python "$SCRIPT_DIR/verify_encrypted_settings.py" --phase "$PHASE" --stage pre

# 3. Upgrade frontend dependencies
echo "--- Step 3: Upgrading frontend dependencies ---"
cd frontend && npm install \
  react@19 \
  react-dom@19 \
  react-router-dom@7 \
  tailwindcss@4 \
  @tailwindcss/postcss@4 \
  vite@8 \
  vitest@4 \
  typescript@6 \
  jsdom@29 \
  @types/react@19 \
  @types/react-dom@19
cd ..

# 4. Unit + Property tests
echo "--- Step 4: Running unit and property tests ---"
pytest tests/ -x --tb=short

# 5. TypeScript + Vite build gate
echo "--- Step 5: TypeScript compilation and Vite build gate ---"
cd frontend && npx tsc -b && npx vite build
cd ..

# 6. E2E tests (full suite — no grep filter)
echo "--- Step 6: Running full E2E validation suite ---"
npx playwright test tests/e2e/frontend/upgrade-validation.spec.ts

# 7. Post-verify encrypted settings
echo "--- Step 7: Post-upgrade encrypted settings verification ---"
python "$SCRIPT_DIR/verify_encrypted_settings.py" --phase "$PHASE" --stage post

echo ""
echo "=== ${PHASE} COMPLETE ==="
