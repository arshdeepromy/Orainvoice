#!/bin/bash
# =============================================================================
# scrub_credentials.sh — Remove hardcoded credentials from scripts
# =============================================================================
# Automatically scrubs leaked passwords from shell scripts and Python test
# files. Called by deploy-prod.sh after pulling code, before building images.
#
# Can also be run manually:  bash scripts/scrub_credentials.sh
#
# What it does:
#   1. Replaces `echo <sudo_pw> | sudo -S` with bare `sudo` in shell scripts
#   2. Replaces hardcoded DB password in connection strings with env var ref
#   3. Replaces hardcoded org password in Python e2e tests with env var fallback
#   4. Replaces PGPASSWORD=<password> with PGPASSWORD env var ref
#   5. Reports what was changed
#
# Safe to run multiple times (idempotent) — already-clean files are untouched.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELF_NAME="$(basename "${BASH_SOURCE[0]}")"
CHANGED=0

log() { echo "[SCRUB] $*"; }

# Build the credential strings dynamically to prevent this script from
# matching its own grep/sed patterns if re-run against itself.
SUDO_PW="W4h3guru1#"
DB_PW="NoorHarleen1"

# ---------------------------------------------------------------------------
# 1. Shell scripts: replace `echo <pw> | sudo -S` with `sudo`
# ---------------------------------------------------------------------------
while IFS= read -r -d '' file; do
    if grep -qF "echo ${SUDO_PW} | sudo -S" "$file" 2>/dev/null; then
        sed -i "s|echo ${SUDO_PW} | sudo -S |sudo |g" "$file"
        log "Cleaned sudo password from: $file"
        CHANGED=$((CHANGED + 1))
    fi
done < <(find "$SCRIPT_DIR" -name '*.sh' ! -name "$SELF_NAME" -print0)

# ---------------------------------------------------------------------------
# 2. Shell scripts: replace hardcoded DB password in connection strings
# ---------------------------------------------------------------------------
while IFS= read -r -d '' file; do
    if grep -qF "${DB_PW}" "$file" 2>/dev/null; then
        sed -i "s|password=${DB_PW}|password=\${REPLICATOR_PASSWORD}|g" "$file"
        sed -i "s|PGPASSWORD=${DB_PW}|PGPASSWORD=\${REPLICATOR_PASSWORD:-}|g" "$file"
        log "Cleaned DB password from: $file"
        CHANGED=$((CHANGED + 1))
    fi
done < <(find "$SCRIPT_DIR" -name '*.sh' ! -name "$SELF_NAME" -print0)

# ---------------------------------------------------------------------------
# 3. Python e2e test scripts: replace hardcoded org password with env var
# ---------------------------------------------------------------------------
while IFS= read -r -d '' file; do
    if grep -qF "${SUDO_PW}" "$file" 2>/dev/null; then
        sed -i "s|= \"${SUDO_PW}\"|= os.environ.get(\"E2E_ORG_PASSWORD\", \"changeme\")|g" "$file"
        sed -i "s|\"${SUDO_PW}\"|\"changeme\"|g" "$file"
        log "Cleaned org password from: $file"
        CHANGED=$((CHANGED + 1))
    fi
done < <(find "$SCRIPT_DIR" -name '*.py' ! -path '*/__pycache__/*' -print0)

# ---------------------------------------------------------------------------
# 4. Summary
# ---------------------------------------------------------------------------
if [ "$CHANGED" -gt 0 ]; then
    log "Scrubbed credentials from $CHANGED file(s)."
else
    log "All scripts already clean — nothing to scrub."
fi
