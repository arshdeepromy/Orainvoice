#!/usr/bin/env bash
#
# Install (or remove) the OraBck cron entry for the current user.
#
# Usage:
#   scripts/install-orabck-cron.sh          # install / re-install
#   scripts/install-orabck-cron.sh --uninstall
#
# The entry runs every 4 hours and dumps the standby-prod Postgres
# replica to ~/OraBck. See scripts/backup-standby-prod.sh for the
# backup logic, retention policy, and the future Drive-upload hook.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/backup-standby-prod.sh"
MARKER="# OraInvoice — standby-prod database backup every 4 hours"
# Older markers we should also strip when re-installing (cleans up any
# previous-cadence entries left behind after a schedule change).
LEGACY_MARKERS=(
    "# OraInvoice — standby-prod database backup every 15 minutes"
)

if [ ! -x "$SCRIPT" ]; then
    echo "ERROR: $SCRIPT is not executable. Run: chmod +x $SCRIPT" >&2
    exit 1
fi

action="${1:-install}"

# Read existing crontab, stripping any prior OraBck block (between any
# of our markers and the next blank line / EOF). Both the current
# marker and any legacy markers are removed so re-running upgrades
# the schedule cleanly.
existing=$(crontab -l 2>/dev/null || true)

# Build a single regex of all markers for awk.
all_markers=("$MARKER" "${LEGACY_MARKERS[@]}")
markers_joined=$(printf '%s|' "${all_markers[@]}")
markers_joined="${markers_joined%|}"

filtered=$(awk -v markers="$markers_joined" '
    BEGIN {
        n = split(markers, arr, "|")
        for (i = 1; i <= n; i++) marker_set[arr[i]] = 1
        skipping = 0
    }
    {
        if (($0) in marker_set) { skipping = 1; next }
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
0 */4 * * * $SCRIPT >/dev/null 2>&1
EOF
} | crontab -

echo "OraBck cron entry installed:"
crontab -l | grep -A1 "$MARKER" || true
