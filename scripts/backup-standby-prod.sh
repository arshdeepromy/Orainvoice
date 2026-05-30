#!/usr/bin/env bash
#
# OraInvoice — standby-prod database backup
#
# Pulls a logical pg_dump from the local Prod-Standby Postgres container
# (which replicates from Pi PROD), gzips it, and writes it to ~/OraBck.
#
# WHY the standby-prod and not Pi PROD primary:
#   pg_dump on the primary would compete with live API queries. The
#   replica is a byte-identical copy receiving WAL streaming so dumping
#   it is free as far as production traffic is concerned.
#
# Schedule: every 15 minutes via user cron — see crontab entry installed
# alongside this script (`scripts/install-backup-cron.sh`).
#
# Retention:
#   - All backups from the last 24 hours kept (96 dumps at 15-min cadence).
#   - One backup per day kept for the last 7 days (the daily snapshot is
#     simply the most recent file from each calendar day; older intra-day
#     dumps are pruned).
#
# Future: Google Drive upload — see ORACLOUD_HOOK at the bottom of this
# file. Drop-in target for the BYO Drive backup feature in
# .kiro/specs/byo-drive-backup/.
#
# PERFORMANCE_AUDIT.md §I-M4 / §I-H5: addresses the off-host backup gap
# at the local level. Off-site comes when the BYO Drive feature ships.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BACKUP_DIR="${ORABCK_DIR:-$HOME/OraBck}"
CONTAINER="${ORABCK_CONTAINER:-invoicing-standby-prod-postgres-1}"
DB_USER="${ORABCK_DB_USER:-postgres}"
DB_NAME="${ORABCK_DB_NAME:-workshoppro}"

# Retention windows (override via env if you want different policy).
RETAIN_RECENT_HOURS="${ORABCK_RETAIN_RECENT_HOURS:-24}"
RETAIN_DAILY_DAYS="${ORABCK_RETAIN_DAILY_DAYS:-7}"

# Logging
LOG_FILE="$BACKUP_DIR/backup.log"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { printf '[%s] %s\n' "$(ts)" "$*" | tee -a "$LOG_FILE"; }
fail() { log "ERROR: $*"; exit 1; }

mkdir -p "$BACKUP_DIR"

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

if ! command -v docker >/dev/null 2>&1; then
    fail "docker not on PATH (cron's PATH is minimal — set PATH at top of crontab or use absolute paths)"
fi

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
    fail "Container '$CONTAINER' not found. Is the standby-prod stack running?"
fi

# Container must be in 'running' state, not paused / restarting.
state=$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo "unknown")
if [ "$state" != "running" ]; then
    fail "Container '$CONTAINER' is in state '$state' (expected 'running')"
fi

# Postgres must accept connections.
if ! docker exec "$CONTAINER" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
    fail "Postgres on '$CONTAINER' is not accepting connections"
fi

# ---------------------------------------------------------------------------
# Dump
# ---------------------------------------------------------------------------

stamp=$(date '+%Y-%m-%d_%H-%M-%S')
dump_file="$BACKUP_DIR/${DB_NAME}-${stamp}.sql.gz"

log "Dumping $DB_NAME from $CONTAINER -> $dump_file"

# Pipe pg_dump through gzip directly so we never write the uncompressed
# stream to disk. Use --format=plain (default) so the file is restorable
# with a simple `gunzip -c | psql`.
if docker exec "$CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" 2>>"$LOG_FILE" | gzip -6 > "$dump_file"; then
    size=$(du -h "$dump_file" | cut -f1)
    if [ ! -s "$dump_file" ]; then
        rm -f "$dump_file"
        fail "Dump produced an empty file (deleted)"
    fi
    log "Dump complete (${size})"
else
    rm -f "$dump_file"
    fail "pg_dump failed"
fi

# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

# 1. Delete any dump files older than RETAIN_DAILY_DAYS days outright.
log "Pruning dumps older than ${RETAIN_DAILY_DAYS} days"
find "$BACKUP_DIR" -maxdepth 1 -name "${DB_NAME}-*.sql.gz" -type f \
    -mtime +"${RETAIN_DAILY_DAYS}" -delete

# 2. Within the daily-keep window but outside the recent-keep window,
#    keep only one dump per calendar day (the latest of that day).
#
#    Strategy: list files older than RETAIN_RECENT_HOURS hours, group by
#    YYYY-MM-DD prefix, keep the lexicographically-latest, delete the rest.
log "Compacting older-than-${RETAIN_RECENT_HOURS}h dumps to one per day"
recent_cutoff_min=$(( RETAIN_RECENT_HOURS * 60 ))

# Files older than recent window but newer than the daily window.
mapfile -t old_files < <(find "$BACKUP_DIR" -maxdepth 1 -name "${DB_NAME}-*.sql.gz" -type f \
    -mmin +"$recent_cutoff_min" \
    -mtime -"${RETAIN_DAILY_DAYS}" \
    -printf '%f\n' | sort)

if [ ${#old_files[@]} -gt 0 ]; then
    declare -A latest_per_day=()
    # Sorted ascending, so the last entry seen for any given day is the latest.
    for f in "${old_files[@]}"; do
        # Filename pattern: workshoppro-YYYY-MM-DD_HH-MM-SS.sql.gz
        day="${f#${DB_NAME}-}"
        day="${day:0:10}"  # YYYY-MM-DD
        latest_per_day["$day"]="$f"
    done
    pruned=0
    for f in "${old_files[@]}"; do
        day="${f#${DB_NAME}-}"
        day="${day:0:10}"
        if [ "${latest_per_day[$day]}" != "$f" ]; then
            rm -f "$BACKUP_DIR/$f"
            pruned=$((pruned + 1))
        fi
    done
    if [ "$pruned" -gt 0 ]; then
        log "Pruned $pruned non-latest dump(s) from older days"
    fi
fi

# ---------------------------------------------------------------------------
# Future: ORACLOUD_HOOK — Google Drive upload integration point.
#
# When the BYO Drive backup feature ships (.kiro/specs/byo-drive-backup),
# uncomment / extend the block below to push the new dump_file to the
# configured Drive folder. Keep the local copy regardless — Drive is a
# secondary location, not a replacement for the local OraBck dir.
# ---------------------------------------------------------------------------
# if command -v rclone >/dev/null 2>&1 && [ -n "${ORABCK_RCLONE_REMOTE:-}" ]; then
#     rclone copyto "$dump_file" "${ORABCK_RCLONE_REMOTE}/$(basename "$dump_file")" \
#         2>>"$LOG_FILE" \
#         && log "Uploaded to Drive: $(basename "$dump_file")" \
#         || log "WARNING: Drive upload failed (local copy retained)"
# fi

log "Backup cycle complete"
