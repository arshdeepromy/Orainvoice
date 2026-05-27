# Runbook: Email Provider Unification

Operational runbook for the [`email-provider-unification`](../../.kiro/specs/email-provider-unification/) spec — covers Phase 8b's destructive data migration, per-phase rollback, and the post-deploy advisory admins need to see.

This runbook satisfies tasks **8.7** (pre-flight for the Phase 8b legacy SMTP migration) and **11.4** (per-phase rollback steps) from [`tasks.md`](../../.kiro/specs/email-provider-unification/tasks.md). Read it end-to-end before scheduling a Phase 8b production deploy.

---

## Phase 8b — Pre-flight Checklist

Phase 8b runs alembic migration `0198_migrate_legacy_smtp_to_email_provider.py`, which decrypts the legacy `integration_configs[smtp]` row, re-encrypts its credentials into the matching `email_providers` row, and flips that row to `is_active=true, credentials_set=true, priority=1`. The migration takes a PG advisory lock (`hashtext('email_provider_rotate')`) shared with `app/cli/rotate_keys.py`. It is not idempotently safe to interrupt mid-write, so we treat it like every other production schema change: maintenance window, dry-run on staging, downgrade rehearsed.

Run through this list **in order**. Do not skip steps even if the previous deploy succeeded — the legacy row's content can change between deploys.

### 1. Schedule a maintenance window

Pick a window when:

- Outbound email traffic is light (no scheduled subscription dunning runs in the next 30 minutes).
- No `app/cli/rotate_keys.py` job is queued or running. Confirm with `pgrep -f rotate_keys` on the app host.
- No admin is mid-edit on the legacy `Admin → Integrations → SMTP` form. The migration's recent-write guard will abort on its own if someone has saved within the last 5 minutes, but a clean window avoids the noisy abort.

15 minutes of window is plenty — the migration itself runs in well under a second. The bulk of the time is the staging dry-run and the post-deploy admin advisory.

### 2. Verify Phase 7 is already in production

Phase 8b assumes the legacy `PUT /api/v1/admin/integrations/smtp` endpoint already returns HTTP 410 Gone (Phase 7). If Phase 7 is not yet deployed, an admin can still write to the legacy row through the old form between when the staging dry-run completes and when the production migration runs — that is exactly the race the recent-write guard is there to catch, but it's better not to need it.

```sh
# On the production host, confirm Phase 7 has shipped:
curl -X PUT https://prod-host/api/v1/admin/integrations/smtp \
  -H 'Authorization: Bearer <admin token>' \
  -H 'Content-Type: application/json' \
  -d '{}'
# Expected: HTTP/1.1 410 Gone
#           Location: /api/v2/admin/email-providers
```

### 3. Confirm no recent writes to the legacy row

```sh
docker compose -f docker-compose.yml -f docker-compose.pi.yml exec postgres \
  psql -U postgres -d workshoppro -c \
  "SELECT name, updated_at, now() - updated_at AS age \
   FROM integration_configs WHERE name = 'smtp';"
```

If `age` is less than 5 minutes, the migration will abort with the documented `RuntimeError("Recent write to integration_configs[smtp] detected. Reschedule maintenance window.")`. Either wait or reschedule.

### 4. Confirm `rotate_keys.py` is not running

```sh
ssh nerdy@192.168.1.90 "pgrep -af rotate_keys"
# Expected: no output (no process)
```

If a rotate is in flight, the migration will abort within 60 seconds of `pg_advisory_lock` contention with the documented `RuntimeError("Could not acquire email_provider_rotate advisory lock. Is rotate_keys.py running? Wait for it to finish, then retry.")`. Wait for the rotate to finish — do not kill it mid-way (a half-rotated `email_providers.credentials_encrypted` is much harder to clean up than a delayed migration).

### 5. Run the staging dry-run

Phase 8b task 8.8 covers this in full. The short version:

```sh
# 1. Refresh staging from a recent prod backup so the legacy row matches reality.
# 2. Apply the migration to staging.
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
  exec app alembic upgrade 0198

# 3. Verify the target email_providers row has been populated.
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
  exec postgres psql -U postgres -d workshoppro -c \
  "SELECT provider_key, credentials_set, is_active, priority \
   FROM email_providers WHERE provider_key IN ('brevo','sendgrid','custom_smtp');"

# 4. Send a real test email through the new sender, e.g. via the admin
#    "Test" button on the active provider. Confirm it delivers.

# 5. Run the downgrade and confirm the legacy row is restored.
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
  exec app alembic downgrade 0197

# 6. Re-upgrade so staging stays in sync with the planned production state.
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
  exec app alembic upgrade head
```

If anything looks off (e.g. credentials don't decrypt after upgrade, the test email fails, the downgrade leaves a different `config_encrypted` blob than the original) — abort the production deploy and triage. Document the deviation in this runbook before retrying.

### 6. Apply the migration to production

```sh
# Code is already on the Pi from the Phase 8b commit (sync via tar+SSH per project-overview).
# The docker entrypoint runs `alembic upgrade head` automatically on app start.
# To apply without an app restart:
ssh nerdy@192.168.1.90 \
  "cd /home/nerdy/invoicing && \
   docker compose -f docker-compose.yml -f docker-compose.pi.yml \
     exec app alembic upgrade head"
```

Watch the migration log lines (the migration uses logger name `alembic.runtime.migration.0198`):

```
0198: migrated integration_configs[smtp] (provider=brevo, last updated_at=...) into email_providers[brevo] (credentials_set=true, is_active=true, priority=1).
```

### 7. Post-migration verification

```sql
-- Same query as the pre-flight, run again to confirm the new state.
SELECT provider_key, credentials_set, is_active, priority,
       length(credentials_encrypted) AS blob_len
FROM email_providers
WHERE provider_key IN ('brevo','sendgrid','custom_smtp');
```

Expected: at least one of those rows has `credentials_set=true, is_active=true, priority=1, blob_len > 0`.

Trigger a test email via the admin **Email Providers → Test** button on the now-active row. Confirm it delivers and shows a green status. If a different provider was already configured through the new UI before the migration ran, the migration's no-clobber rule preserves it — the test still applies, just on whichever row is now active.

### 8. Notify admins (the post-deploy advisory)

The migration **does not** carry the legacy `is_verified` flag onto the new row, because the new sender's wire format and per-attempt timeouts are not identical to the legacy `smtplib` path — admins must re-test before trusting failover.

Per task 11.3, fire a one-shot in-app notification to all `global_admin`-role users with the body:

> Your SMTP configuration has been migrated to the new Email Providers page. Please open **Admin → Email Providers** and click **Test** on each provider to confirm credentials carried across. The legacy `is_verified` flag is not carried across.

This is a one-shot, not deduped — every global admin should see it once.

---

## Per-Phase Rollback Strategy

Each phase ships independently. Rollback is per-phase. The single-commit-per-phase convention from [`tasks.md`](../../.kiro/specs/email-provider-unification/tasks.md) means a `git revert <sha>` is the cleanest rollback for code-only phases. Migration phases need an `alembic downgrade` first.

| Phase | Code rollback | Data rollback | Time to revert |
|---|---|---|---|
| 0 | `git revert` the phase 0 commit | None — types and constants only | < 5 min |
| 0.5 (security hotfix) | `git revert` if the new password-reset flow regresses; the old code path stays intact in the same file | None | < 5 min |
| 1 | `git revert` the phase 1 commit | None | < 5 min |
| 2 + 8a | `git revert` then `alembic downgrade -1` | Migration is additive (nullable columns + indexes); downgrade drops them. | < 10 min |
| 3 (per-site) | `git revert` the specific A-site commit. Each A-site is its own commit so a regression bisects to one PR. | None | < 5 min |
| 4 | `git revert` | None — only stub bodies and Redis dedup keys change | < 5 min |
| 5 | `git revert` | None — code-only fix | < 5 min |
| 6 | `git revert` | The Brevo setup-guide migration (Phase 6.5) is text-only on `email_providers.setup_guide`; downgrade is a follow-up `UPDATE` to the previous text. Practically: do nothing, the old setup_guide text is harmless. | < 5 min |
| 7 | `git revert` | None — endpoint behaviour reverts to the pre-410 form | < 5 min |
| 8b | `git revert` then `alembic downgrade 0197` | Downgrade re-encrypts the new credentials back into `integration_configs[smtp].config_encrypted`. **Test this on staging before relying on it in prod.** Decryption failure during downgrade is logged-and-swallowed, so a stale row will not block the downgrade — but it will leave admins without their old SMTP credentials. Have the SMTP secrets ready in a password manager as a backup. | < 15 min |
| 8c | `git revert` then `alembic downgrade <bounced_addresses_revision>` | Downgrade drops `bounced_addresses` table. Webhook handlers fall back to the pre-correlation behaviour (notification_log status stays at `sent` even after a bounce — same as today). | < 10 min |
| 9 | `git revert` only — **do not** re-add the deleted shims by hand. The revert restores them. | None — Phase 9 is code-only | < 5 min |

### Rollback safety reminders

- Never `git push --force` on a phase rollback — the project policy is forward-fix commits, not history rewrites.
- A phase 8b rollback needs the same advisory-lock window as the upgrade itself: confirm `rotate_keys.py` is idle before running `alembic downgrade`.
- After any rollback, verify outbound email still flows: trigger a test email via the admin Email Providers page and confirm delivery. If the rollback leaves the system unable to send (e.g. legacy row was missing and downgrade had nothing to restore), fall back to manually re-saving SMTP credentials through the new UI.

---

## Reference

- Spec: [`.kiro/specs/email-provider-unification/`](../../.kiro/specs/email-provider-unification/) ([requirements](../../.kiro/specs/email-provider-unification/requirements.md), [design](../../.kiro/specs/email-provider-unification/design.md), [tasks](../../.kiro/specs/email-provider-unification/tasks.md), [plan](../../.kiro/specs/email-provider-unification/plan.md))
- Migration: `alembic/versions/2026_05_27_1200-0198_migrate_legacy_smtp_to_email_provider.py`
- Advisory lock: `pg_advisory_lock(hashtext('email_provider_rotate'))` — shared with `app/cli/rotate_keys.py`
- Tests: `tests/test_migration_legacy_smtp_to_email_provider.py`, `tests/test_migration_no_clobber.py`, `tests/test_migration_recent_write_abort.py`, `tests/test_migration_advisory_lock.py`
