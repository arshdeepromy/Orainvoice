#!/usr/bin/env bash
#
# Install (or remove) the OraBck cron entry for the current user.
#
# Usage:
#   scripts/install-orabck-cron.sh          # install / re-install
#   scripts/install-orabck-cron.sh --uninstall
#
# The entry runs every 15 minutes and dumps the standby-prod Postgres
# replica to ~/OraBck. See scripts/backup-standby-prod.sh for the
# backup logic, retention policy, and the future Drive-upload hook.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/backup-standby-prod.sh"
MARKER="# OraInvoice — standby-prod database backup every 15 minutes"

if [ ! -x "$SCRIPT" ]; then
    echo "ERROR: $SCRIPT is not executable. Run: chmod +x $SCRIPT" >&2
    exit 1
fi

action="${1:-install}"

# Read existing crontab, stripping any prior OraBck block (between our marker
# and the next blank line / EOF).
existing=$(crontab -l 2>/dev/null || true)
filtered=$(awk -v marker="$MARKER" '
    BEGIN { skipping = 0 }
    {
        if ($0 == marker) { skipping = 1; next }
        if (skipping && /^$/) { skipping = 0; next }
        if (skipping && /^[*0-9]/) { skipping = 1 }  # cron schedule line
        else if (skipping && /^PATH=/) { skipping = 1 }
        else if (skipping && /^#/) { skipping = 1 }
        else if (skipping) { skipping = 0; print; next }
        if (!skipping) print
    }
' <<< "$existing")

if [ "$action" = "--uninstall" ] || [ "$action" = "uninstall" ]; then
    if [ -z "$filtered" ]; then
        crontab -r 2>/dev/null || true
    else
        printf '%s\n' "$filtered" | crontab -
    fi
    echo "OraBck cron entry removed."
    exit 0
fi

# Install: append the block.
{
    if [ -n "$filtered" ]; then
        printf '%s\n\n' "$filtered"
    fi
    cat <<EOF
$MARKER
# Pulls pg_dump from local Prod-Standby Postgres container -> ~/OraBck.
# Script: $SCRIPT
# Logs:   ~/OraBck/backup.log
# Manage: edit via 'crontab -e' or rerun this installer.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
*/15 * * * * $SCRIPT >/dev/null 2>&1
EOF
} | crontab -

echo "OraBck cron entry installed:"
crontab -l | grep -A1 "$MARKER" || true
