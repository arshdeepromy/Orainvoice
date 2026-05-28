# Implementation Plan: Email Provider Unification

## Overview

Tasks are ordered to match the phase sequencing in [`design.md`](design.md) and [`plan.md`](plan.md) (Section 5). Each top-level task corresponds to a phase. Phases ship independently; rollback is per-phase. Where the plan requires advisory locks, row-level locks, dedup keys, or per-provider helpers, those are explicit subtasks here.

Group A migrations (Phase 3) are listed as one PR per site (A1–A14) so a regression bisects to a single commit.

## Testing scope (applies to every task)

**Hard rule: only run tests relevant to the change in this task. Do NOT run the full suite, do NOT run unrelated module tests, and do NOT run e2e batteries unless the task explicitly says to.**

If a test failure surfaces in an unrelated module while running the scoped tests, log it as a separate issue per `issue-tracking-workflow.md` — do NOT broaden the test scope to chase it.

- Phase 1 sender unit tests: `pytest tests/test_email_sender_*.py`
- Phase 2 task wiring: `pytest tests/test_send_email_task_integration.py tests/test_email_infrastructure.py tests/test_send_portal_link.py tests/test_portal_dsar.py tests/test_portal_quote_acceptance_notification.py tests/test_portal_recover.py tests/test_transfer_notifications.py tests/test_notification_retry_property.py`
- Phase 3 per-site: only that site's new failover test plus the closest existing module test
- Phase 5 activate/deactivate: `pytest tests/test_email_provider_*.py`
- Phase 8a schema: `pytest tests/test_notification_log_provider_columns.py tests/test_email_delivery_tracking.py`
- Phase 8b legacy migration: `pytest tests/test_migration_legacy_smtp_to_email_provider.py tests/test_rotate_keys.py tests/test_integration_config.py`
- Phase 8c bounce correlation: `pytest tests/test_email_bounce_correlation.py tests/test_bounced_address_blocklist.py tests/test_bounce_per_provider_secret.py tests/test_email_delivery_event.py tests/test_notification_log_state_transitions_property.py`
- Frontend changes: `cd frontend && npx vitest run src/pages/admin/EmailProviders.test.tsx` (or scoped to the changed file)
- Diagnostics: run `getDiagnostics` only on files actually changed in the task

## Git workflow (applies to every phase)

Solo-dev workflow: each phase lands as a **single commit on `main`**. No phase branches, no PRs, no review queue. Bisectability is preserved by keeping each phase (and each Phase 3 A-site migration) in its own commit with a conventional message.

**Per-phase wrap-up (final subtask of every phase):**

1. Stage only the files this phase touches (no `git add .` blanket adds — list them explicitly).
2. Run the phase's scoped tests one more time; abort the wrap-up if anything fails.
3. Run `getDiagnostics` on every changed file; fix any new errors before committing.
4. Commit on `main` with a conventional message: `email-provider-unification: phase <N> — <short summary>`.
5. Do **not** push automatically. The user pushes to `origin/main` manually when they're ready.

**Safety:**
- Never `git push --force` unless explicitly asked.
- Never amend a commit that has already been pushed.
- If a phase needs rollback after the commit lands, write a follow-up commit (`git revert <sha>` or a forward-fix commit) — do not rewrite history.
- Migrations that touch production state (Phase 2 schema, Phase 8b legacy data migration, Phase 8c bounced_addresses table) still need the same care they would on a feature branch: dev-environment dry-run before commit, downgrade tested, runbook updated where the task says so.

## Tasks

- [ ] 0. Phase 0 — Preparation (no behaviour changes)

  - [x] 0.1 Create `app/integrations/email_sender.py` with empty module + dataclass stubs
    - Define `EmailMessage`, `EmailAttachment` (mirror current shapes from `app/integrations/brevo.py`)
    - Define `EmailAttempt`, `SendResult` (per design Components §1)
    - Define `FailureKind` enum with values `HARD_RECIPIENT`, `HARD_PAYLOAD`, `SOFT_AUTH`, `SOFT_PROVIDER`, `BUDGET_EXCEEDED`
    - Add `SendResult.provider` read-only `@property` returning `provider_key or ""` for backwards compatibility
    - Add module-level constants `EMAIL_SIZE_LIMIT`, `EMAIL_PER_ATTEMPT_TIMEOUT_SECONDS`, `EMAIL_TOTAL_BUDGET_SECONDS`
    - No actual `send_email` implementation yet — leave as `async def send_email(...): raise NotImplementedError`
    - _Requirements: 1.1, 1.2, 1.3, 1.5_

  - [x] 0.2 Re-export new types from `app/integrations/brevo.py`
    - Add re-exports: `from app.integrations.email_sender import EmailMessage, EmailAttachment, SendResult`
    - Keep existing `EmailMessage`/`EmailAttachment`/`SendResult` dataclasses as aliases so existing imports of either name still resolve
    - _Requirements: 19.1, 19.2_

  - [x] 0.3 Verify existing test suite still green
    - Run `pytest tests/test_email_infrastructure.py tests/test_security_focused.py`
    - Confirm no test broke from the re-export change
    - _Requirements: 19.4_

  - [x] 0.4 Phase 0 wrap-up — commit and push
    - Stage only: `app/integrations/email_sender.py`, `app/integrations/brevo.py`, plus any test mock fixes that became necessary (e.g. updates in `tests/test_email_infrastructure.py` and `tests/integration/test_notifications.py` for the new `SendResult` shape) and the ISSUE-150 entry added to `docs/ISSUE_TRACKER.md` during 0.3
    - Re-run `pytest tests/test_email_infrastructure.py tests/test_security_focused.py` — abort if anything fails
    - Run `getDiagnostics` on the changed files; fix any new errors
    - Commit on `main`: `email-provider-unification: phase 0 — sender module scaffold + types`
    - User pushes to `origin/main` manually when ready
    - _Requirements: 20.1_

- [ ] 0.5 Phase 0.5 — SECURITY HOTFIX: password reset email

  - [x] 0.5.1 Implement `_send_password_reset_email` in `app/modules/auth/service.py:1892` using existing raw `smtplib` + Email_Provider loop pattern
    - Copy the pattern from `_send_invitation_email` at the same file (~L2523)
    - Build HTML and text bodies referencing the reset URL with explicit 1-hour expiry
    - Use the same `select(EmailProvider).where(is_active && credentials_set).order_by(priority)` loop
    - Open its own `async_session_factory()` if `db` is None (mirroring `_send_permanent_lockout_email`)
    - Wrap in try/except so the API call doesn't crash on failure (user gets generic "if your email is registered..." response either way)
    - _Requirements: 8.1, 22.1_

  - [x] 0.5.2 Add `tests/test_password_reset_email.py` asserting the email is at least attempted
    - Mock `EmailProvider` rows; patch `smtplib.SMTP`; assert `sendmail` was called once
    - One success-path test, one no-providers test (asserts no crash, just a warning log)
    - _Requirements: 8.1, 22.1_

  - [x] 0.5.3 Bump PATCH version and ship as standalone hotfix
    - Update `app/__init__.py` `__version__` (whatever the next PATCH is from current 1.11.0)
    - Update `frontend/package.json` `version`
    - Note in release notes: "Forgot Password emails now actually deliver."
    - _Requirements: 22.1_

  - [x] 0.5.4 Phase 0.5 wrap-up — commit and push
    - Stage only: `app/modules/auth/service.py`, `tests/test_password_reset_email.py`, `app/__init__.py`, `frontend/package.json`
    - Re-run `pytest tests/test_password_reset_email.py` — abort if anything fails
    - Run `getDiagnostics` on changed files
    - Commit on `main`: `email-provider-unification: phase 0.5 — password reset hotfix`
    - User pushes to `origin/main` manually when ready (this is a security hotfix — push promptly)
    - _Requirements: 20.1, 22.1_

- [ ] 1. Phase 1 — Implement `send_email` with full feature parity

  - [x] 1.1 Implement `_dispatch_brevo_rest` in `app/integrations/email_sender.py`
    - Adapt `_send_test_via_rest_api` from `app/modules/email_providers/service.py:314` (REST helper already exists for the test endpoint)
    - Extend with multi-attachment support — Brevo REST `attachment` array accepts base64 content + name + content-type
    - Capture `messageId` from JSON response and write into the returned `EmailAttempt`
    - Use `httpx.AsyncClient(timeout=EMAIL_PER_ATTEMPT_TIMEOUT_SECONDS)` for the request
    - _Requirements: 3.1, 3.7_

  - [x] 1.2 Implement `_dispatch_sendgrid_rest`
    - POST to `https://api.sendgrid.com/v3/mail/send` with `Authorization: Bearer {api_key}`
    - Build SendGrid-shape payload (personalisations array, content array)
    - Capture `X-Message-Id` from response headers
    - Same `httpx` client and timeout
    - _Requirements: 3.3, 3.7_

  - [x] 1.3 Implement `_dispatch_smtp` covering Brevo-with-smtp_login, Mailgun, SES, Gmail, Outlook, custom_smtp
    - Honour `smtp_encryption` ∈ `none`, `tls`, `ssl`
    - When provider has no `smtp_host`, fall back to the default-host table from `email_providers/service.py:246-260`
    - Wrap every blocking smtplib call in `asyncio.to_thread(...)` so the event loop is not blocked
    - Generate an RFC 5322 `Message-ID` header at send time and persist it in the returned `EmailAttempt`
    - Apply per-attempt socket timeout via `socket.settimeout(EMAIL_PER_ATTEMPT_TIMEOUT_SECONDS)`
    - _Requirements: 3.2, 3.4, 3.5, 3.6, 5.7_

  - [x] 1.4 Add `_build_mime_message` helper
    - `multipart/mixed` when attachments are present, otherwise `multipart/alternative` for HTML+text only
    - Honour `from_name`, `from_email`, `reply_to` per `_resolve_sender_identity`
    - _Requirements: 3.7, 4.4_

  - [x] 1.5 Add `_resolve_sender_identity`
    - Compute `(from_name, from_email, reply_to)` per design Components §6
    - Return None when `provider.config['from_email']` is missing so the loop can skip with `failure_kind=SOFT_PROVIDER, error="missing from_email"`
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 1.6 Add error-classification helpers `_classify_brevo_rest_error`, `_classify_sendgrid_rest_error`, `_classify_smtp_error`, `_classify_network_exc`
    - Map every documented error to one of `HARD_RECIPIENT`, `HARD_PAYLOAD`, `SOFT_AUTH`, `SOFT_PROVIDER`
    - Tests must cover at least one example per (provider, FailureKind) pair
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 1.7 Implement `dispatch_one_provider` public helper
    - Public signature per design Components §3
    - Loads credentials, builds the message MIME, delegates to one of the three private dispatchers, captures `duration_ms`
    - Returns a single `EmailAttempt` (no chain, no blocklist check)
    - This is the helper that Phase 3 will use to refactor `email_providers/service.py::test_email_provider`
    - _Requirements: 1.7_

  - [x] 1.8 Implement `send_email` main loop
    - Pre-check total payload against `EMAIL_SIZE_LIMIT`; return early with HARD_PAYLOAD if exceeded
    - Pre-check `bounced_addresses` blocklist (Phase 8c will populate the table; Phase 1 implements the read path so the call site is in place)
    - Load `Active_Provider_Set` (`is_active=True AND credentials_set=True ORDER BY priority ASC`)
    - When empty, return failure with `attempts=[]` and call `_maybe_fire_no_providers_alert`
    - Loop with `time.monotonic()` budget; per-attempt + total budget enforced
    - Short-circuit on HARD_RECIPIENT or HARD_PAYLOAD; continue on SOFT_AUTH or SOFT_PROVIDER
    - When loop exhausts and every attempt is SOFT_AUTH, call `_maybe_fire_all_auth_fail_alert`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 5.7, 5.8, 5.9_

  - [x] 1.9 Stub the no-providers and all-auth-fail alerts behind feature flags
    - `_maybe_fire_no_providers_alert(db)` — Phase 4 wires the actual `create_in_app_notification` call; Phase 1 just leaves a TODO and a `logger.warning` so the loop still completes
    - Same for `_maybe_fire_all_auth_fail_alert(db)`
    - The Redis dedup key implementation lands in Phase 4
    - _Requirements: 10.1, 10.2 (deferred wiring)_

  - [x] 1.10 Add `tests/test_email_sender_dispatch.py` — credential dispatch matrix
    - For each `provider_key`, parameterised across credentials shapes, assert the chosen transport
    - `brevo` + only `api_key` → REST; `brevo` + `api_key` + `smtp_login` → SMTP; `sendgrid` + `api_key` → REST; everything else → SMTP
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 21.1_

  - [x] 1.11 Add `tests/test_email_sender_failover.py` — 3-provider chain
    - Provider 1 returns 401 → SOFT_AUTH; Provider 2 raises connection error → SOFT_PROVIDER; Provider 3 returns 202 → success
    - Assert `result.success`, `result.provider_key == third.provider_key`, `len(result.attempts) == 3`, attempt classifications correct
    - _Requirements: 2.1, 2.2, 21.1_

  - [x] 1.12 Add `tests/test_email_sender_attachments.py`
    - Multi-attachment with mixed MIME types (PDF + image) sent via REST and via SMTP path; assert both downstream payloads include the attachments
    - _Requirements: 3.7, 21.1_

  - [x] 1.13 Add `tests/test_email_sender_overrides.py`
    - Caller passes `org_sender_name="Acme Workshop"` and `org_reply_to="reply@acme.co.nz"`; provider's config has different `from_name`/`reply_to`
    - Assert the From and Reply-To headers in the dispatched payload come from the caller args, not the provider config
    - _Requirements: 4.1, 4.3, 21.4_

  - [x] 1.14 Add `tests/test_email_sender_error_classification.py`
    - Drive each FailureKind across both REST and SMTP transports
    - Cover: Brevo 400 invalid_parameter recipient → HARD_RECIPIENT; Brevo 401 → SOFT_AUTH; Brevo 413 → HARD_PAYLOAD; Brevo timeout → SOFT_PROVIDER
    - Cover: SendGrid 400 with recipient errors → HARD_RECIPIENT; SendGrid 401 → SOFT_AUTH
    - Cover: smtplib `SMTPRecipientsRefused` → HARD_RECIPIENT; `SMTPDataError(552)` → HARD_PAYLOAD; `SMTPAuthenticationError` → SOFT_AUTH; socket timeout → SOFT_PROVIDER
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 21.2_

  - [x] 1.15 Add `tests/test_email_sender_timeouts.py`
    - Mock httpx with a 30s sleep; assert per-attempt times out at ~15s, classification SOFT_PROVIDER
    - 3-provider chain where each takes 20s; assert total budget enforced and last attempt(s) marked BUDGET_EXCEEDED
    - _Requirements: 5.7, 5.8, 21.3_

  - [x] 1.16 Verify existing test suite green
    - `pytest tests/test_email_infrastructure.py tests/test_security_focused.py`
    - Phase 1 still hits the legacy `send_org_email` shim from those tests; they must keep passing
    - _Requirements: 19.4_

  - [x] 1.17 Phase 1 wrap-up — commit and push
    - Stage only: `app/integrations/email_sender.py` and the 6 new test files (`tests/test_email_sender_*.py`)
    - Re-run `pytest tests/test_email_sender_*.py tests/test_email_infrastructure.py tests/test_security_focused.py` — abort if anything fails
    - Run `getDiagnostics` on changed files
    - Commit on `main`: `email-provider-unification: phase 1 — send_email implementation`
    - User pushes to `origin/main` manually when ready
    - _Requirements: 20.1_

- [ ] 2. Phase 2 + Phase 8a — Rewire `send_email_task` and add `notification_log.provider_key`

  Phase 8a ships alongside Phase 2 so the rewritten `_send_email_async` lands `update_log_status(provider_key=...)` on a real column.

  - [x] 2.1 Create Alembic migration `XXXX_add_notification_log_provider_columns.py`
    - Determine next revision number from `alembic/versions/` (current head should be 0194 per project-overview; verify before assigning)
    - Add nullable columns to `notification_log`: `provider_key VARCHAR(50)`, `provider_message_id TEXT`, `bounced_at TIMESTAMPTZ`, `bounce_reason TEXT`, `delivered_at TIMESTAMPTZ`
    - Create partial index `ix_notification_log_provider_message_id ON notification_log(provider_message_id) WHERE provider_message_id IS NOT NULL`
    - Create non-partial index `ix_notification_log_provider_key ON notification_log(provider_key)`
    - Idempotent: use raw SQL `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for repeat-deploy safety
    - Add downgrade that drops both indexes then drops both columns in reverse order
    - **HA replication:** confirm `notification_log` is already in `ora_publication`; if so, no `_HA_ADD_TPL` snippet needed (additive column changes don't break logical replication)
    - _Requirements: 16.1, 16.2_

  - [x] 2.2 Add columns to `app/modules/notifications/models.py::NotificationLog`
    - `provider_key: Mapped[str | None] = mapped_column(String(50), nullable=True)`
    - `provider_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)`
    - `bounced_at`, `delivered_at`: `Mapped[datetime | None]` with `TIMESTAMP(timezone=True)`
    - `bounce_reason: Mapped[str | None]`
    - _Requirements: 16.1_

  - [x] 2.3 Extend `log_email_sent` and `update_log_status` in `app/modules/notifications/service.py`
    - Add keyword-only parameters: `provider_key: str | None = None`, `provider_message_id: str | None = None`, `bounced_at: datetime | None = None`, `bounce_reason: str | None = None`, `delivered_at: datetime | None = None`
    - Persist when supplied; do not overwrite when not supplied (None means "leave unchanged" on update; "leave NULL" on insert)
    - _Requirements: 16.3_

  - [x] 2.4 Update `_log_entry_to_dict` to include the new fields
    - Add all five fields to the serialised dict
    - _Requirements: 16.4_

  - [x] 2.5 Extend Pydantic schema in `app/modules/notifications/schemas.py`
    - Add to the log-entry response model: `provider_key`, `provider_message_id`, `bounced_at`, `bounce_reason`, `delivered_at` — all `Optional`/`None`-allowed
    - Update the `list_notification_log` response schema if it wraps the entries
    - _Requirements: 16.5_

  - [x] 2.6 Rewrite `_send_email_async` in `app/tasks/notifications.py`
    - Replace `send_org_email` call with `send_email` call (per design Components §9)
    - Build `EmailMessage` with `org_id` plumbed through from the existing string `org_id` argument (parse to UUID)
    - On success, call `update_log_status` with `provider_key=result.provider_key, provider_message_id=result.message_id, status="sent", sent_at=now()`
    - On failure, call `update_log_status` with `status="failed", error_message=result.error`
    - Return dict matches old shape: `{"success", "message_id", "provider"}` so existing tests asserting on `result["provider"]` continue to pass
    - _Requirements: 7.1, 7.2, 7.4, 16.3_

  - [x] 2.7 Convert `send_org_email`, `get_email_client`, `load_smtp_config_from_db`, `SmtpConfig`, `EmailClient` in `app/integrations/brevo.py` to deprecated shims
    - Each shim internally calls the new sender; do NOT re-implement the old SMTP path
    - The `send_org_email` shim must translate the new `SendResult` shape (which has `provider_key`) to the old shape (which had `provider: str`) by relying on `SendResult.provider` `@property`
    - Tag each shim with `# DEPRECATED — Phase 9 deletes this. See email-provider-unification spec.`
    - _Requirements: 19.1, 19.2, 19.3_

  - [x] 2.8 Add notification-log frontend Provider column
    - Locate the admin notification-log viewer (search for the `list_notification_log` consumer; likely `frontend/src/pages/admin/NotificationLog.tsx` or similar)
    - Add a "Provider" column rendering `provider_key` or `—` when null
    - Update the row's status badge so `bounced` and `delivered` render distinctly from `sent` (red and blue respectively, vs green for sent)
    - On `bounced` rows, show `bounce_reason` as a hover tooltip on the badge
    - _Requirements: 16.6_

  - [x] 2.9 Add `tests/test_send_email_task_integration.py`
    - End-to-end via `send_email_task` with mock httpx
    - 2-provider chain failover scenario
    - Assert `notification_log.status='sent'` and `provider_key`, `provider_message_id` populated
    - _Requirements: 21.5_

  - [x] 2.10 Add `tests/test_notification_log_provider_columns.py`
    - Persist a row via `log_email_sent` with the new kwargs; assert columns set
    - Update via `update_log_status`; assert columns updated
    - Verify `_log_entry_to_dict` returns the new fields
    - _Requirements: 16.3, 16.4, 16.5_

  - [x] 2.11 Re-run existing Group B tests to confirm zero regressions
    - `pytest tests/test_transfer_notifications.py tests/test_send_portal_link.py tests/test_portal_dsar.py tests/test_portal_quote_acceptance_notification.py tests/test_portal_recover.py tests/test_notification_retry_property.py tests/test_email_infrastructure.py tests/test_email_delivery_tracking.py`
    - All must remain green
    - _Requirements: 19.4_

  - [ ] 2.12 Manual smoke: send a portal link with two providers active
    - Configure two providers in dev environment; revoke first provider's API key; send a portal link
    - Assert second provider delivers; check notification log shows correct provider_key
    - _Requirements: 21 (smoke)_

  - [x] 2.13 Phase 2 + 8a wrap-up — commit and push
    - Stage only: `alembic/versions/XXXX_add_notification_log_provider_columns.py`, `app/modules/notifications/{models,service,schemas}.py`, `app/tasks/notifications.py`, `app/integrations/brevo.py`, the notification-log frontend file changed in 2.8, and the two new test files
    - Re-run the Phase 2 scoped test list from the Testing scope section — abort if anything fails
    - Run the migration in dev: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head`; verify `0184 → 0XXX` applies cleanly
    - Run `getDiagnostics` on changed files
    - Commit on `main`: `email-provider-unification: phase 2 + 8a — task rewire + notification_log columns`
    - Note in the commit body that this single commit covers BOTH Phase 2 and Phase 8a per Req 22.4
    - User pushes to `origin/main` manually when ready
    - _Requirements: 20.1, 22.4_

- [ ] 3. Phase 3 — Migrate Group A sites (raw smtplib → send_email)

  Each subtask is **one PR per site** so a regression is easy to bisect. After all 14 sites land, the grep gate at 3.16 must pass. Per-site migration template is in design.md > Per-Site Migration Patterns > Group A.

  - [x] 3.1 A1 — Migrate `email_invoice` in `app/modules/invoices/service.py:4294`
    - Replace provider query, MIME builder, and provider loop with one `send_email` call
    - Build `EmailAttachment` list from the existing `attachment_data` tuples
    - Preserve the `attachments_skipped_size` body suffix
    - Preserve `log_email_sent` after `result.success`
    - Preserve `create_in_app_notification(category="email_failure", ...)` after `not result.success`
    - Pass `org_id=invoice.org_id` on `EmailMessage`
    - Add `tests/test_invoice_email_failover.py` covering A1, A2, and A14 (one combined file per the plan)
    - _Requirements: 6.1, 6.3, 6.4_

  - [x] 3.2 A2 — Migrate `send_payment_reminder` in `app/modules/invoices/service.py:4747`
    - Same pattern as 3.1, smaller body, no PDF attachment in the email branch
    - Add the failover test case to `tests/test_invoice_email_failover.py`
    - _Requirements: 6.1, 6.3, 6.4_

  - [x] 3.3 A3 — Migrate quote send in `app/modules/quotes/service.py:989`
    - Same pattern as A1 with PDF attachment
    - Remove `import smtplib` and `from email.mime.* import ...` from the function
    - Add `tests/test_quote_email_failover.py`
    - _Requirements: 6.1, 6.3, 6.4_

  - [x] 3.4 A4 — Migrate `_send_receipt_email` in `app/modules/payments/service.py:525`
    - PDF attachment from `generate_invoice_pdf`; convert to `EmailAttachment`
    - Add `tests/test_payment_receipt_email.py`
    - _Requirements: 6.1, 6.3, 6.4_

  - [x] 3.5 A5 — Migrate `email_service_history_report` in `app/modules/vehicles/report_service.py:293`
    - HTML body from Jinja template, PDF attachment
    - Add `tests/test_vehicle_report_email.py`
    - _Requirements: 6.1, 6.3, 6.4_

  - [x] 3.6 A6 — Migrate `_send_booking_confirmation_email` in `app/modules/bookings/service.py:1162`
    - Plain text only, no attachment
    - Add `tests/test_booking_confirmation_email.py`
    - _Requirements: 6.1, 6.3, 6.4_

  - [x] 3.7 A7 — Migrate `_send_permanent_lockout_email` in `app/modules/auth/service.py:360`
    - Function uses its own `async_session_factory()` because called outside request context — keep that pattern, the unified sender accepts a caller-provided session
    - No org context: `EmailMessage.org_id = None`
    - Will be exercised by `tests/test_auth_email_failover.py` (covers A7–A10)
    - _Requirements: 6.1, 6.3, 6.4_

  - [x] 3.8 A8 — Migrate `_send_invitation_email` in `app/modules/auth/service.py:2523`
    - Has `db may-be-None` path; preserve conditional session-open in the caller
    - Dev-fallback: when `result.attempts == []` (no providers configured), `logger.warning("DEV INVITE URL: %s", invite_url)` to keep the existing dev UX
    - Add A8 cases to `tests/test_auth_email_failover.py`
    - _Requirements: 6.1, 6.3, 6.4_

  - [x] 3.9 A9 — Migrate `send_verification_email` in `app/modules/auth/service.py:2825`
    - Same pattern as A8 (HTML + text, dev fallback log on no-providers)
    - Add A9 cases to `tests/test_auth_email_failover.py`
    - _Requirements: 6.1, 6.3, 6.4_

  - [x] 3.10 A10 — Migrate `send_receipt_email` (paid signup) in `app/modules/auth/service.py:3027`
    - Same pattern as A8
    - Add A10 cases to `tests/test_auth_email_failover.py`
    - _Requirements: 6.1, 6.3, 6.4_

  - [x] 3.11 A11 — Migrate `_send_email_otp` in `app/modules/auth/mfa_service.py:370` (also fixes BUG-2)
    - Remove the `.limit(1)` on the EmailProvider query at L397 — failover comes from the unified sender
    - Wrap result: when `not result.success`, raise `RuntimeError(f"MFA email send failed: {result.error}")` so the MFA challenge contract is preserved
    - Add `tests/test_mfa_email_otp.py` covering 2-provider failover and the RuntimeError-on-total-failure case
    - _Requirements: 6.1, 6.6_

  - [x] 3.12 A12 — Migrate `notify_customer` in `app/modules/customers/service.py:679`
    - Pass `org_sender_name=org_name` so the From header reflects the org
    - Preserve `log_email_sent` call after success
    - Add `tests/test_customer_notify_email.py`
    - _Requirements: 6.1, 6.3, 6.5_

  - [x] 3.13 A13 — Migrate `submit_demo_request` in `app/modules/landing/router.py:57`
    - Public form: `org_id=None`, no `log_email_sent` (no notification_log entry for public submissions)
    - On `not result.success`, return HTTP 500 to the caller (no in-app notification — no org context)
    - Remove the module-level `import smtplib` at L15
    - Add `tests/test_landing_demo_request_email.py`
    - _Requirements: 6.1, 6.7_

  - [x] 3.14 A14 — Migrate `send_invoice_payment_link_email` in `app/modules/payments/service.py:378`
    - Same pattern as A1 with optional PDF attachment
    - Preserve any `log_email_sent` and audit-log calls
    - Already covered by `tests/test_invoice_email_failover.py` from 3.1
    - _Requirements: 6.1, 6.3, 6.8_

  - [x] 3.15 Refactor `email_providers/service.py::test_email_provider` to use shared dispatch
    - Extract the inline SMTP block (currently between L177 and L314) and replace with a call to `dispatch_one_provider(...)` from `email_sender.py`
    - The REST helper `_send_test_via_rest_api` at L314 can either be removed (replaced by `dispatch_one_provider`) or retained as a thin local helper that calls `dispatch_one_provider`
    - Manual smoke: trigger the per-provider Test button on the admin Email Providers page; confirm it still reports success/failure correctly for both REST and SMTP providers
    - _Requirements: 1.7, 6.2_

  - [x] 3.16 Phase 3 grep gate
    - Run `grep -rn "import smtplib" app/`
    - **Expected output:** only `app/integrations/email_sender.py`
    - If anything else shows up, that site has not been migrated yet — add a follow-up subtask for it
    - _Requirements: 6.2_

  - [x] 3.17 PR-checklist gate per Group A site
    - For every Phase 3 PR, the reviewer must verify:
      1. The diff still calls `log_email_sent` if the original did
      2. The diff still calls `create_in_app_notification` on failure if the original did
      3. Any per-org sender name is passed via `org_sender_name=...`
      4. `EmailMessage.org_id` is set to the right value (or explicitly `None` for A7, A11, A13)
    - _Requirements: 6.3, 6.4, 6.5_

  - [x] 3.18 Group E gating-check sites — do NOT migrate
    - The following sites are **read-only "is any provider active" gating checks**, not send sites. They must remain untouched by Phase 3:
      - `app/modules/notifications/reminder_queue_service.py` ~L118 (per plan §2 E1)
      - `app/modules/notifications/service.py` ~L2022 (per plan §2 E2)
      - `app/modules/admin/router.py` `list_integrations` and `integration_cost_dashboard` (per plan §2 D5; covered separately by tasks 6.6 and 7.7)
    - Reviewer guard: if a Phase 3 PR touches any of these files, reject it unless the change is explicitly out of scope (e.g. a follow-up cleanup that the reviewer can verify is harmless)
    - _Requirements: project-overview alignment_

  - [x] 3.19 Phase 3 per-site wrap-up — commit on main (one cycle per A-site)
    - Each Group A subtask (3.1–3.14) and the test-endpoint refactor (3.15) lands as **its own commit on `main`** so a regression bisects to a single commit
    - Stage only the migrated service file + that site's new test file
    - Re-run only that site's new failover test plus the closest existing module test (per Phase 3 testing scope)
    - Run `getDiagnostics` on the changed files
    - Commit on `main`: `email-provider-unification: phase 3 — A<n> migrate <function>`
    - Verify the PR-checklist gate items from 3.17 yourself before committing (this replaces the reviewer step)
    - User pushes to `origin/main` manually when ready (recommended: push after each site so a regression is reachable from origin for bisecting)
    - **Finish each site's commit before starting the next** — keeps each migration in its own bisectable commit
    - _Requirements: 20.1, 6.1_

  - [x] 3.20 Phase 3 grep-gate wrap-up — commit on main
    - Once all A1–A14 commits and 3.15 are on `main`, run the grep gate from 3.16
    - Add a small CI guard test (`tests/test_no_smtplib_outside_email_sender.py`) that runs the same grep and fails if any other file imports `smtplib`
    - Stage only the new test file
    - Run `pytest tests/test_no_smtplib_outside_email_sender.py`
    - Commit on `main`: `email-provider-unification: phase 3 — grep-gate CI guard`
    - User pushes to `origin/main` manually when ready
    - _Requirements: 6.2, 20.1_

- [ ] 4. Phase 4 — Implement Group C stubs and the no-providers / all-auth-fail alerts

  - [x] 4.1 C3 — Rewrite `_send_password_reset_email` in `app/modules/auth/service.py:1892` to call `send_email`
    - Replace the Phase 0.5 raw-smtplib implementation with a call to the unified sender
    - `org_id=None` (account recovery, no org context); no `log_email_sent` (the security-critical email path stays out of org notification logs)
    - On failure, log a warning but do not raise — the calling endpoint always returns the same generic "if the email is registered..." response either way
    - Update `tests/test_password_reset_email.py` to include `::test_failover_chain` asserting delivery succeeds when 2 of 3 providers fail
    - _Requirements: 8.1, 22.2, 22.3_

  - [x] 4.2 C2 — Implement `_send_anomalous_login_alert` in `app/modules/auth/service.py:635`
    - Build HTML + text body including IP address, device fingerprint (where available), timestamp, and a "If this wasn't you, change your password immediately" CTA
    - Use the unified sender; `org_id=user.org_id` if known, else None
    - Add `tests/test_anomalous_login_email.py` asserting the email is at least attempted
    - _Requirements: 8.2_

  - [x] 4.3 C1 — Implement `_send_token_reuse_alert` in `app/modules/auth/service.py:861`
    - Body explains "We detected a refresh token replay attempt. All your sessions have been invalidated. Please sign in again." plus a link to active-sessions page
    - `org_id=None` (sessions are org-agnostic)
    - Add a tests case in `tests/test_anomalous_login_email.py` (same file, separate test)
    - _Requirements: 8.3_

  - [x] 4.4 C4 — Implement `_send_org_admin_invitation_email` in `app/modules/admin/service.py:347`
    - Replace the `logger.info("...queued...")` stub with a real `send_email_task` call (gets failover via Phase 2 plumbing automatically)
    - Build HTML + text body with the secure signup link, the org name, and a 7-day expiry note
    - `template_type="org_admin_invitation"`, `org_id=org.id`, `org_sender_name="OraInvoice"`
    - Add `tests/test_org_admin_invitation_email.py`
    - _Requirements: 8.4_

  - [x] 4.5 Wire `_maybe_fire_no_providers_alert` in `email_sender.py`
    - Implement the Redis-dedup pattern with TTL=`NO_PROVIDERS_DEDUP_SECONDS` (1 hour)
    - Call `create_in_app_notification(category='email_failure', severity='critical', recipient_role='global_admin', title='No email providers configured', body='Outbound email is currently disabled. Configure at least one provider in Admin > Email Providers.', link_url='/admin/email-providers')`
    - Coalesce key: a single Redis key like `email_no_providers_alert`; SETNX with TTL
    - On Redis unavailable, fail open (still fire the in-app notification each time — better duplication than silence)
    - _Requirements: 10.1, 10.3, 10.5_

  - [x] 4.6 Wire `_maybe_fire_all_auth_fail_alert` in `email_sender.py`
    - Same pattern as 4.5 but with TTL=`ALL_AUTH_FAIL_DEDUP_SECONDS` (1 day) and body explaining "All providers' credentials appear to be invalid"
    - Coalesce key: `email_all_auth_fail_alert`
    - _Requirements: 10.2, 10.4, 10.5_

  - [x] 4.7 Add `tests/test_email_no_providers_alert.py`
    - First call with empty Active_Provider_Set fires the in-app notification
    - Second call within 1h does NOT fire (deduped)
    - After Redis TTL expires, third call fires again
    - Mock Redis with a fake in-process implementation
    - _Requirements: 10.1, 10.3, 21.9_

  - [x] 4.8 Add `tests/test_email_all_auth_fail_alert.py`
    - 3-provider chain all returning 401; first such send fires the in-app notification
    - Subsequent send within 24h does NOT fire
    - One provider succeeds → notification does NOT fire
    - _Requirements: 10.2, 10.4, 21.9_

  - [x] 4.9 Phase 4 wrap-up — commit and push
    - Stage only: `app/modules/auth/service.py`, `app/modules/admin/service.py`, `app/integrations/email_sender.py`, and the new test files (`test_password_reset_email.py` updated, `test_anomalous_login_email.py`, `test_email_no_providers_alert.py`, `test_email_all_auth_fail_alert.py`, `test_org_admin_invitation_email.py`)
    - Re-run only those 5 test files plus `pytest tests/test_email_sender_*.py` for the alert wiring
    - Run `getDiagnostics` on changed files
    - Commit on `main`: `email-provider-unification: phase 4 — stubs implemented + alerts wired`
    - User pushes to `origin/main` manually when ready
    - _Requirements: 20.1, 8, 10_

- [ ] 5. Phase 5 — Fix activate endpoint and add deactivate safety net

  - [x] 5.1 Edit `activate_email_provider` in `app/modules/email_providers/service.py:34`
    - Remove the `await db.execute(update(EmailProvider).values(is_active=False))` line that deactivates everything else
    - Replace the unconditional `provider.is_active = True` with an idempotent block:
      ```python
      if provider.is_active:
          return _provider_to_dict(provider)
      provider.is_active = True
      ```
    - Update the audit log action name to `email_provider_activated` (was `set_as_only_active` or similar)
    - For defence-in-depth, acquire the same row-level lock pattern as deactivate (5.2)
    - _Requirements: 9.1, 9.2, 9.7_

  - [x] 5.2 Edit `deactivate_email_provider` in `app/modules/email_providers/service.py:68`
    - Acquire `SELECT ... FOR UPDATE` on every row in the Active_Provider_Set (per design Concurrency §Activate/Deactivate)
    - If the target row is not in the active set, look it up without the lock; if not found, raise 404; otherwise return idempotently
    - Compute `remaining_after = active_set - {target}`; if empty, raise `HTTPException(409, "Activate another provider before deactivating this one — at least one active email provider is required for outbound mail.")`
    - On valid deactivation, set `is_active=False`, flush, write audit log
    - _Requirements: 9.3, 9.4, 9.5_

  - [x] 5.3 Update `list_email_providers` to return `active_providers: list[str]`
    - Compute the list of `provider_key` values where `is_active=True` ordered by `priority ASC`
    - Keep the existing `active_provider: str | None` field set to the first element of the new list (backwards compatibility)
    - Update `EmailProviderListResponse` schema in `app/modules/email_providers/schemas.py` to include the new field
    - _Requirements: 9.6_

  - [x] 5.4 Add `tests/test_email_provider_activate_multi.py`
    - Activate provider A → activate provider B → assert both `is_active=True` after the second call
    - List endpoint shows both in `active_providers`; `active_provider` (singular) is the higher-priority one
    - _Requirements: 9.1, 9.6, 21.7_

  - [x] 5.5 Add `tests/test_email_provider_deactivate_last_blocked.py`
    - Single active provider; attempt deactivate; assert HTTP 409 returned with the exact error message from 5.2
    - Provider remains active after the failed call
    - _Requirements: 9.4_

  - [x] 5.6 Add `tests/test_email_provider_concurrent_deactivate.py`
    - Two coroutines each call deactivate on the last two active providers concurrently (`asyncio.gather`)
    - Assert exactly one returns 200 (success), one returns 409 (the loser of the row-lock race)
    - Final state: exactly one active provider remaining
    - _Requirements: 9.5, 21.7_

  - [x] 5.7 Phase 5 wrap-up — commit and push
    - Stage only: `app/modules/email_providers/{service,schemas,router}.py`, the 3 new test files
    - Re-run only `pytest tests/test_email_provider_*.py`
    - Run `getDiagnostics` on changed files
    - Commit on `main`: `email-provider-unification: phase 5 — activate/deactivate fix + race safety`
    - User pushes to `origin/main` manually when ready
    - _Requirements: 20.1, 9_

- [ ] 6. Phase 6 — Frontend updates (Email Providers admin page)

  - [x] 6.1 Multi-active banner in `frontend/src/pages/admin/EmailProviders.tsx`
    - At ~L442 (verify line during implementation), replace the singular `Active Provider:` banner with the conditional rendering shown in design.md > Frontend > Phase 6a
    - Source data from the new `active_providers` field on the list response
    - _Requirements: 9.6, 17.1_

  - [x] 6.2 Priority slider visibility
    - At ~L239 (verify line), change the conditional from `{provider.is_active && (...)}` to `{provider.credentials_set && (...)}`
    - Show helper text "Will apply when activated" when `credentials_set && !is_active`
    - _Requirements: 17.3_

  - [x] 6.3 Failover preview line
    - Add the new `<div>` element above the provider list rendering "Send order: 1. X → 2. Y → 3. Z"
    - Only render when `activeProviders.length > 1`
    - _Requirements: 17.2_

  - [x] 6.4 Disable last-deactivate button
    - On each row's Deactivate button, add `disabled={provider.is_active && activeProviders.length === 1}`
    - Add a `title` tooltip with the reason
    - The 409 from the backend (Phase 5.2) remains the authoritative guard
    - _Requirements: 9.4, 17.5_

  - [x] 6.5 Brevo setup guide content
    - Create migration `XXXX_update_brevo_setup_guide.py` that runs `UPDATE email_providers SET setup_guide = '...' WHERE provider_key = 'brevo'`
    - Setup guide explains the two key types: REST API key (no SMTP login required) and SMTP key + SMTP login. Include where to find each in the Brevo admin UI.
    - _Requirements: 17.4_

  - [x] 6.6 Verify integration_cost_dashboard renders correctly with N active providers
    - Manual visual check after Phase 5 ships: open the Cost Dashboard tile labelled "Email"
    - Acceptable: shows "Email: Healthy ✓ (N active providers)" or comma-separated provider names
    - If the tile shows only one provider name when there are several, raise a small follow-up backend issue
    - _Requirements: 14.6_

  - [x] 6.7 Frontend test: `frontend/src/pages/admin/EmailProviders.test.tsx`
    - Render with one active provider → singular banner
    - Render with three active providers → "Active Providers (3): A, B, C" + failover preview line
    - Render row with `credentials_set=true, is_active=false` → priority slider visible with helper text
    - Render row that is the last active → Deactivate button disabled with tooltip
    - _Requirements: 17.1, 17.2, 17.3, 17.5_

  - [x] 6.8 Phase 6 wrap-up — commit and push
    - Stage only: `frontend/src/pages/admin/EmailProviders.tsx`, `frontend/src/pages/admin/EmailProviders.test.tsx`, `alembic/versions/XXXX_update_brevo_setup_guide.py`
    - Re-run only `cd frontend && npx vitest run src/pages/admin/EmailProviders.test.tsx`
    - Run `getDiagnostics` on the two frontend files
    - Commit on `main`: `email-provider-unification: phase 6 — frontend multi-active UI`
    - User pushes to `origin/main` manually when ready
    - _Requirements: 20.1, 17_

- [ ] 7. Phase 7 — Deprecate the legacy admin SMTP page

  - [x] 7.1 Frontend audit: confirm no SMTP card exists in `Integrations.tsx`
    - Run `grep -rn "PUT /admin/integrations/smtp\|POST /admin/integrations/smtp/test\|smtp/test" frontend/src/`
    - Verified 2026-05-25: zero call sites; tab list is Carjam, Stripe, SMS Providers, Email Providers
    - If anything turns up, remove it as part of this task
    - _Requirements: 14.5_

  - [x] 7.2 Replace `PUT /api/v1/admin/integrations/smtp` body with HTTP 410 Gone
    - Edit `app/modules/admin/router.py:640` — keep the route registered so old clients don't 404
    - Return: `JSONResponse(status_code=410, content={"detail": "This endpoint is deprecated. Configure email via /api/v2/admin/email-providers."}, headers={"Location": "/api/v2/admin/email-providers"})`
    - _Requirements: 14.1_

  - [x] 7.3 Replace `POST /api/v1/admin/integrations/smtp/test` body with HTTP 410 Gone
    - Same pattern as 7.2 at `app/modules/admin/router.py:692`
    - _Requirements: 14.1_

  - [x] 7.4 Add `legacy_smtp_endpoint_hit` telemetry log line
    - Inside both 410 handlers, before returning: `logger.warning("legacy_smtp_endpoint_hit path=%s remote=%s", request.url.path, request.client.host if request.client else "?")`
    - Tag must be exactly `legacy_smtp_endpoint_hit` so a single grep over access logs counts callers
    - _Requirements: 14.2_

  - [x] 7.5 Remove unreferenced legacy helpers from `app/modules/admin/service.py`
    - Run `grep -rn "save_smtp_config\|send_test_email" app/ tests/` — confirm zero call sites except inside `admin/service.py` itself
    - Delete `save_smtp_config` and the legacy `send_test_email` function (the one at `admin/service.py:1080` per design)
    - _Requirements: 14.3_

  - [x] 7.6 Add a test for the 410-Gone behaviour
    - `tests/test_legacy_smtp_endpoint_410.py` — PUT/POST returns 410, response includes the Location header, log line emitted
    - _Requirements: 14.1, 14.2_

  - [x] 7.7 Update integration backup/restore to remain compatible
    - Verify `export_integration_settings` and `import_integration_settings` (in `admin/service.py`) still iterate both `integration_configs` and `email_providers` rows
    - If backups predating Phase 8b only contain the legacy row, restoring them must still set `email_providers.credentials_set=true` for the corresponding `provider_key` (using the same migration logic from Phase 8b)
    - Add `tests/test_integration_backup_restore_compat.py` covering both directions
    - _Requirements: 14.7_

  - [x] 7.8 Phase 7 wrap-up — commit and push
    - Stage only: `app/modules/admin/router.py`, `app/modules/admin/service.py`, `tests/test_legacy_smtp_endpoint_410.py`, `tests/test_integration_backup_restore_compat.py`
    - Re-run only `pytest tests/test_legacy_smtp_endpoint_410.py tests/test_integration_backup_restore_compat.py`
    - Run `getDiagnostics` on changed files
    - Commit on `main`: `email-provider-unification: phase 7 — legacy /admin/integrations/smtp 410 Gone`
    - Note in the commit body that the 410 endpoints stay in place for at least one full release before Phase 9 removes them
    - User pushes to `origin/main` manually when ready
    - _Requirements: 20.1, 14_

- [ ] 8. Phase 8b — Legacy SMTP → email_providers data migration

  Phase 8a is included in Phase 2 above (schema must land before the rewritten task does). This task covers Phase 8b only.

  - [x] 8.1 Create migration `XXXX_migrate_legacy_smtp_to_email_provider.py`
    - First step: `bind.execute("SELECT pg_advisory_lock(hashtext('email_provider_rotate'))")` with `SET LOCAL lock_timeout = '60s'`; on timeout, raise a clear error per design Concurrency > Migration 8b race
    - Read `integration_configs` row where `name='smtp'`; bail out cleanly if no row
    - Decrypt blob via `envelope_decrypt_str`; on decryption failure, log error, leave both rows unchanged, emit advisory message, and CONTINUE (do not abort the broader Alembic upgrade)
    - Pre-check: if `integration_configs.updated_at > now() - interval '5 minutes'`, abort with "Recent write to integration_configs[smtp] detected. Reschedule maintenance window."
    - Map `provider` field to `provider_key`: `brevo → brevo`, `sendgrid → sendgrid`, `smtp → custom_smtp`
    - Build credentials dict per provider_key shape (`api_key` for REST providers; `username`+`password` for SMTP)
    - Re-encrypt into `email_providers.credentials_encrypted` using `envelope_encrypt_str`
    - Set `is_active=True`, `priority=1`, `credentials_set=True`, `smtp_host`/`smtp_port`/`smtp_encryption` from legacy row
    - Set `config = {"from_email": ..., "from_name": ..., "reply_to": ...}`
    - **No-clobber rule:** only run the upgrade for a `provider_key` whose row currently has `credentials_set=False`. If the admin already configured that provider via the new UI, leave it untouched.
    - Final step: `bind.execute("SELECT pg_advisory_unlock(hashtext('email_provider_rotate'))")` (also in a `finally` block so the lock is released on error)
    - Add downgrade that re-encrypts `email_providers.credentials_encrypted` back into `integration_configs[smtp].config_encrypted`
    - **HA replication:** no `_HA_ADD_TPL` snippet needed (this migration only updates existing rows; both tables are already in `ora_publication`)
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.7, 15.8, 15.9_

  - [x] 8.2 Update `app/cli/rotate_keys.py` to acquire the same advisory lock
    - Wrap the EmailProvider re-encrypt loop in `acquire → try → finally release`
    - Use the exact same key: `hashtext('email_provider_rotate')`
    - _Requirements: 15.6_

  - [x] 8.3 Add `tests/test_migration_legacy_smtp_to_email_provider.py`
    - Seed a legacy row in `integration_configs[smtp]` with encrypted credentials
    - Run the migration; assert `email_providers.brevo` (or whichever provider_key maps) has `credentials_set=True`, `is_active=True`, decryptable credentials
    - Assert `is_verified` (legacy) does NOT carry over (operator must re-test post-migration)
    - Run downgrade; assert legacy row is restored to its original state
    - _Requirements: 15.1, 15.8, 21.10_

  - [x] 8.4 Add `tests/test_migration_no_clobber.py`
    - Seed BOTH a legacy row AND an `email_providers` row already with `credentials_set=True`
    - Run the migration; assert the new row's credentials are unchanged (no clobber)
    - _Requirements: 15.4, 21.10_

  - [x] 8.5 Add `tests/test_migration_recent_write_abort.py`
    - Seed legacy row with `updated_at = now() - 1 minute` (i.e. recently written)
    - Run the migration; assert it aborts with the documented error message
    - Assert no rows changed
    - _Requirements: 15.7, 21.10_

  - [x] 8.6 Add `tests/test_migration_advisory_lock.py`
    - Acquire the advisory lock from a separate connection
    - Run the migration in another connection; assert it aborts within `lock_timeout` with the documented "Could not acquire" error
    - Release the lock from the first connection; rerun the migration; assert it now succeeds
    - _Requirements: 15.5, 15.6, 21.10_

  - [x] 8.7 Operational pre-flight runbook entry
    - Add a section to the project's deploy runbook (likely `docs/RUNBOOK.md` or a new `docs/MIGRATION_8B_RUNBOOK.md`)
    - Include: maintenance window scheduling, GUI disabled, no recent writes verified, no rotate_keys job running, advisory lock acquired, post-migration admin notification recommendation (admins re-test each provider via the new UI)
    - _Requirements: 24.1, 24.3_

  - [ ] 8.8 Staging dry-run
    - Run the migration in staging using a copy of production data (or production-like fixtures)
    - Verify `email_providers` row populated correctly; verify a real test email sends through the unified sender
    - Run the downgrade; verify legacy row restored
    - Document any deviations in the runbook before scheduling production deploy
    - _Requirements: 20.3_

  - [x] 8.9 Phase 8b wrap-up — commit and push
    - Stage only: `alembic/versions/XXXX_migrate_legacy_smtp_to_email_provider.py`, `app/cli/rotate_keys.py`, `tests/test_migration_*.py` files added in this phase, `docs/RUNBOOK.md` (or `docs/RUNBOOKS/email-provider-unification.md`)
    - Re-run only `pytest tests/test_migration_legacy_smtp_to_email_provider.py tests/test_migration_no_clobber.py tests/test_migration_recent_write_abort.py tests/test_migration_advisory_lock.py tests/test_rotate_keys.py`
    - Run `getDiagnostics` on changed files
    - Commit on `main`: `email-provider-unification: phase 8b — legacy SMTP data migration`
    - Note in the commit body the maintenance window prerequisites and link to the runbook entry from 8.7
    - **Do not push to PROD without an approved maintenance window** — even though this lands on `main` immediately, hold off pushing/deploying until the runbook prerequisites are satisfied
    - _Requirements: 20.1, 15, 20.3_

- [ ] 9. Phase 8c — Bounce correlation, blocklist, and Delivery Health

  Phase 8c is sequenced AFTER Phase 8a (uses `provider_message_id` column) but is independent of Phase 8b (data migration). It can ship at the same time as or before Phase 9.

  - [x] 9.1 Create migration `XXXX_create_bounced_addresses.py`
    - Determine next revision number from `alembic/versions/`
    - Create `bounced_addresses` table per design Data Model > Phase 8c
    - Functional unique index on `(COALESCE(org_id::text, ''), LOWER(email_address))` — requires PG 11+, all envs are PG 16
    - Indexes: `ix_bounced_addresses_email`, `ix_bounced_addresses_expires` (partial)
    - Add to `ora_publication` for HA replication using the `_HA_ADD_TPL` snippet pattern; matching `_HA_DROP_TPL` in downgrade
    - RLS: enable with org-scoped policy where `org_id IS NULL OR org_id = current_setting('app.current_org_id')::uuid` (NULL rows are platform-wide and visible to all orgs)
    - Idempotent: `CREATE TABLE IF NOT EXISTS`; `DROP POLICY IF EXISTS` in downgrade
    - _Requirements: 12.1_

  - [x] 9.2 Add `BouncedAddress` SQLAlchemy model in `app/modules/notifications/models.py`
    - Mirror migration columns and types
    - Add a `__table_args__` with the functional unique index reference
    - _Requirements: 12.1_

  - [x] 9.3 Implement `_check_bounce_blocklist` in `email_sender.py`
    - Pre-send query against `bounced_addresses` for `(org_id OR NULL, lower(email_address))`
    - Return `(is_blocked: bool, reason: str | None)` per design Components §7
    - Wire into the `send_email` main loop (already a stub in Phase 1.8)
    - _Requirements: 12.3, 12.4, 12.5_

  - [x] 9.4 Capture provider message id in `_dispatch_*` helpers
    - Brevo REST: read `messageId` from JSON response
    - SendGrid REST: read `X-Message-Id` from response headers
    - SMTP: generate the `Message-ID` header during MIME construction; persist same value as the captured id
    - Plumb through `EmailAttempt` → `SendResult.message_id`
    - _Requirements: 11.1_

  - [x] 9.5 Create `app/modules/notifications/bounce_correlation.py` helper module
    - `flag_bounce(db, *, provider_message_id, recipient, kind, reason, provider_key)` — encapsulates the notification_log lookup + bounced_addresses upsert + in-app notification
    - Idempotent on repeated webhook events: ON CONFLICT DO UPDATE bumps `hit_count` and `last_seen_at`; notification_log update is a no-op if status is already bounced
    - _Requirements: 11.2, 12.2, 12.8_

  - [x] 9.6 Update `brevo_bounce_webhook` in `app/modules/notifications/router.py:863`
    - Look up the matching active provider's `brevo_webhook_secret` from `email_providers.config`; fall back to `app_settings.brevo_webhook_secret` for one release (per Requirement 25.5)
    - Verify signature; on mismatch return 403 and log warning
    - For each event: call `flag_bounce(...)` if event is in `BREVO_BOUNCE_EVENTS`; if the event is `delivered`, update `notification_log.delivered_at`
    - Existing customer.email_bounced flagging logic stays as a side-effect inside flag_bounce
    - _Requirements: 11.2, 11.3, 13.1, 13.3, 13.4_

  - [x] 9.7 Update `sendgrid_bounce_webhook` in `app/modules/notifications/router.py:946`
    - Same pattern as 9.6 with SendGrid's webhook signature scheme
    - Read `sendgrid_webhook_secret` from `email_providers.config` first, env var fallback
    - _Requirements: 11.2, 13.2, 13.3, 13.4_

  - [x] 9.8 In-app notification for bounces affecting customers/users
    - Inside `flag_bounce`, if the recipient matches an active customer or user, fire `create_in_app_notification(category='email_bounced', recipient_role='org_admin', body='Email to {addr} bounced: {reason}', link_url='/admin/email-providers/delivery-health', metadata={'address': addr, 'reason': reason})`
    - Use the existing 24h dedup-key mechanism in `app/modules/in_app_notifications/service.py` keyed on `category + email_address`
    - _Requirements: 12.8_

  - [x] 9.9 Add Delivery Health endpoints in `app/modules/email_providers/router.py`
    - `GET /api/v2/admin/email-providers/delivery-health` returning the aggregate stats + recent bounces per design API Endpoints
    - `DELETE /api/v2/admin/email-providers/bounced-addresses/{id}` removing a row so the next send to that address is attempted
    - Both endpoints accept role `global_admin` AND `org_admin`
    - Pagination: `offset` + `limit` query params (default `limit=100`, max 500); reject `skip` per the v2 API convention
    - _Requirements: 18.1, 18.2, 18.3_

  - [x] 9.10 Schedule the daily bounce cleanup task
    - Add `cleanup_expired_bounce_rows` to `app/tasks/scheduled.py`
    - Schedule hourly via the existing scheduled-tasks framework
    - Deletes rows where `expires_at IS NOT NULL AND expires_at < now()` (hard bounces never expire)
    - _Requirements: 12.6_

  - [x] 9.11 Frontend: add Delivery Health UI
    - Decision: tab inside `EmailProviders.tsx` (default per design Risks > Decisions deferred); new file `frontend/src/pages/admin/EmailDeliveryHealth.tsx` containing `DeliveryStatsCards` + `BounceTable`
    - Cards: 24h / 7d / 30d totals with horizontal bar by provider
    - Table: columns Recipient, Provider, Kind, Reason, First seen, Last seen, Hits, Expires, Action
    - Action column: "Clear" button → confirmation modal → DELETE bounce row → refetch
    - Empty state: "No bounces in the last 30 days. ✓"
    - _Requirements: 18.1, 18.2, 18.3, 18.4_

  - [x] 9.12 Add `tests/test_email_bounce_correlation.py`
    - Send a mock email; capture `provider_message_id`; simulate Brevo bounce webhook event; assert notification_log row flips to `status='bounced'` with reason
    - _Requirements: 11.1, 11.2, 21.8_

  - [x] 9.13 Add `tests/test_bounced_address_blocklist.py`
    - Hard-bounce an address; second send to the same address short-circuits with `failure_kind=HARD_RECIPIENT`
    - Soft-bounce only: send still proceeds (logs warning)
    - Clear the bounce; next send proceeds normally
    - _Requirements: 12.3, 12.4, 12.5, 12.7_

  - [x] 9.14 Add `tests/test_bounce_per_provider_secret.py`
    - Configure two Brevo providers each with a distinct `brevo_webhook_secret` in `config`
    - Webhook signed with provider 2's secret; assert handler tries provider 1's secret first, then provider 2, accepts on match
    - Webhook with no matching secret → 403, no DB writes
    - Webhook with env-var fallback only → still verified for the one-release transition window
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 25.5_

  - [x] 9.15 Add `tests/test_email_delivery_event.py`
    - Brevo `delivered` event for a known `provider_message_id` sets `notification_log.delivered_at`
    - Same event for an unknown id logs a warning but does not error
    - _Requirements: 11.3, 11.4_

  - [x] 9.16 Add `tests/test_notification_log_state_transitions_property.py` (Hypothesis property test)
    - Generate random orderings of webhook events for a given log row
    - Assert no illegal transitions occur (legal: queued → sent → delivered, queued → sent → bounced, queued → failed)
    - Property test budget: small (`max_examples=50`) to keep CI fast
    - _Requirements: 11.5, 21.8_

  - [x] 9.17 Phase 8c wrap-up — commit and push
    - Stage only: `alembic/versions/XXXX_create_bounced_addresses.py`, `app/modules/notifications/{models,router,bounce_correlation}.py`, `app/modules/email_providers/{router,schemas}.py`, `app/integrations/email_sender.py`, `app/tasks/scheduled.py`, `frontend/src/pages/admin/EmailDeliveryHealth.tsx`, the 5 new test files
    - Re-run only the Phase 8c scoped test list from the Testing scope section
    - Run `getDiagnostics` on changed backend and frontend files
    - Commit on `main`: `email-provider-unification: phase 8c — bounce correlation + delivery health`
    - User pushes to `origin/main` manually when ready
    - _Requirements: 20.1, 11, 12, 13, 18, 25_

- [ ] 10. Phase 9 — Cleanup (gated on one full release of stable Phase 2 + Phase 7 in production)

  Phase 9 is intentionally **last** and only runs after telemetry confirms zero callers of the deprecated paths.

  - [ ] 10.1 Confirm zero `legacy_smtp_endpoint_hit` log lines across one full release window
    - Query production access logs for the tag
    - If non-zero, defer Phase 9 by one release and notify any internal callers
    - _Requirements: 14.4, 23.3_

  - [x] 10.2 Remove the `send_org_email`, `get_email_client`, `load_smtp_config_from_db`, `SmtpConfig`, `EmailClient` shims from `app/integrations/brevo.py`
    - Verify via grep that no caller imports any of these symbols (after Phase 2 they should only be used by tests, which themselves got rewritten in Phase 2 to use the new sender)
    - Either delete the file entirely or leave it as an empty module with a deprecation comment
    - _Requirements: 23.2_

  - [x] 10.3 Remove the 410-Gone endpoint stubs from `app/modules/admin/router.py`
    - Drop the route registrations for `PUT /admin/integrations/smtp` and `POST /admin/integrations/smtp/test`
    - _Requirements: 23.3, 14.4_

  - [x] 10.4 Remove dead retry constants from `app/tasks/notifications.py`
    - Delete `RETRY_DELAYS = (60, 300, 900)`
    - Delete `MAX_RETRIES = 3`
    - Delete `_get_retry_delay` if unreferenced (verify with grep first)
    - _Requirements: 23.1_

  - [x] 10.5 Verify `app/cli/rotate_keys.py` needs no changes
    - The script iterates `IntegrationConfig` rows generically; deleting the smtp row (or leaving it for forensic value) does not require code changes
    - Phase 8b's advisory-lock additions stay
    - _Requirements: 23.5_

  - [x] 10.6 Optionally drop the legacy `integration_configs[name='smtp']` row
    - Operator discretion: keep for forensic value, or drop in a follow-up migration
    - If dropping, write a small migration with downgrade that recreates the row from a backup if available
    - _Requirements: 23.4_

  - [x] 10.7 Final test sweep
    - `pytest tests/test_email_*.py tests/test_send_email_*.py tests/test_email_provider_*.py tests/test_email_sender_*.py`
    - All must remain green
    - _Requirements: 19.4_

  - [x] 10.8 Phase 9 wrap-up — commit and push
    - Stage only: `app/integrations/brevo.py` (deleted/empty), `app/tasks/notifications.py` (retry constants removed), `app/modules/admin/router.py` (410 stubs removed), and any optional follow-up migration for dropping the legacy row
    - Re-run only the final-test-sweep command from 10.7
    - Run `getDiagnostics` on changed files
    - Commit on `main`: `email-provider-unification: phase 9 — cleanup shims and 410 stubs`
    - Note in the commit body the access-log telemetry confirmation from 10.1 (zero `legacy_smtp_endpoint_hit` lines over the release window)
    - User pushes to `origin/main` manually when ready
    - _Requirements: 20.1, 23_

- [ ] 11. Documentation, release notes, and runbook updates

  These tasks accompany the relevant phases but are tracked separately so doc updates aren't forgotten.

  - [x] 11.1 Phase 2 release notes
    - Note: "All scheduled email types (subscription invoices, dunning, portal links, fleet invites, compliance reminders, etc.) now have multi-provider failover."
    - Note shim retention: `send_org_email` shim retained for one release; existing tests keep passing
    - _Requirements: 24.2_

  - [x] 11.2 Phase 7 release notes
    - Note: "The legacy /admin/integrations/smtp endpoints now return HTTP 410 Gone. Use /api/v2/admin/email-providers."
    - Note: 410 endpoints retained for at least one release post-deploy; Phase 9 removal gated on telemetry
    - _Requirements: 24.2_

  - [x] 11.3 Phase 8b release notes (post-deploy admin advisory)
    - "Your SMTP configuration has been migrated to the new Email Providers page. Please open Admin > Email Providers and click Test on each provider to confirm credentials carried across. The legacy is_verified flag is not carried across."
    - Surface this as an in-app notification to global_admin role at the moment the migration completes (one-shot, not deduped)
    - _Requirements: 24.1_

  - [x] 11.4 Operational runbook entry
    - Update `docs/RUNBOOK.md` (or create `docs/RUNBOOKS/email-provider-unification.md`) with the Phase 8b prerequisites: maintenance window, GUI disabled, no recent integration_configs writes, no rotate_keys job running, advisory lock acquired
    - Include rollback steps per phase from design > Phase Sequencing > Rollback strategy
    - _Requirements: 20.4, 24.3_

  - [x] 11.5 Update `.kiro/steering/integration-credentials-architecture.md`
    - Add a section: "Email is now configured exclusively via the Email Providers admin page. The legacy IntegrationConfig[smtp] row exists only for backwards compatibility and is read by no runtime code path."
    - Reference the unification spec
    - _Requirements: 24.2_

  - [x] 11.6 Update `docs/ISSUE_TRACKER.md`
    - Mark BUG-1 (activate deactivates others), BUG-2 (MFA `.limit(1)`), BUG-3 (Group B no failover), BUG-4 (stub-only stubs), BUG-5 (Brevo guide), BUG-6 (hand-rolled SMTP duplication) as resolved with reference to this spec
    - BUG-7 (`is_verified` parity) remains open as a deferred follow-up per Requirements > Explicit non-goals
    - _Requirements: project-overview alignment_

## Phase Gates Summary

| Phase | Gate | Verification |
|---|---|---|
| 0 | Existing test suite green; `email_sender.py` has only types/constants | `pytest tests/test_email_infrastructure.py tests/test_security_focused.py` |
| 0.5 | Forgot Password delivers an email in manual test | Manual smoke; `tests/test_password_reset_email.py` |
| 1 | New unit tests pass; existing tests still green | `pytest tests/test_email_sender_*.py tests/test_email_infrastructure.py` |
| 2 | All Group B sites use unified sender; Phase 8a schema applied | `pytest tests/test_send_email_task_integration.py` + Group B existing tests |
| 3 | `grep -rn "import smtplib" app/` returns only `email_sender.py` | Per-site failover tests + grep |
| 4 | All four C-stubs send real email; no-providers and all-auth-fail alerts fire and dedup | `pytest tests/test_email_no_providers_alert.py tests/test_email_all_auth_fail_alert.py tests/test_password_reset_email.py tests/test_anomalous_login_email.py` |
| 5 | Activate is multi-active; deactivate-last returns 409; concurrent deactivate races resolve correctly | `pytest tests/test_email_provider_*.py` |
| 6 | UI shows multiple active providers; failover preview line; Brevo guide updated | `cd frontend && npx vitest run src/pages/admin/EmailProviders.test.tsx` |
| 7 | Legacy endpoints return 410 Gone with Location header; telemetry log line emitted | `pytest tests/test_legacy_smtp_endpoint_410.py` + access-log spot check |
| 8a | `notification_log.provider_key` and friends populated by `update_log_status` | `pytest tests/test_notification_log_provider_columns.py` (delivered with Phase 2) |
| 8b | Migration carries legacy row across; no-clobber rule enforced; advisory lock held | `pytest tests/test_migration_legacy_smtp_to_email_provider.py tests/test_migration_no_clobber.py tests/test_migration_recent_write_abort.py tests/test_migration_advisory_lock.py` + staging dry-run |
| 8c | Bounce webhooks correlate to log rows; blocklist short-circuits known-bad addresses; per-provider secrets used | `pytest tests/test_email_bounce_correlation.py tests/test_bounced_address_blocklist.py tests/test_bounce_per_provider_secret.py tests/test_email_delivery_event.py tests/test_notification_log_state_transitions_property.py` |
| 9 | Zero `legacy_smtp_endpoint_hit` log lines for one full release; shims removed | Telemetry grep + final test sweep |

## Requirement → Task Trace

| Requirement | Tasks |
|---|---|
| 1 Unified Sender Public API | 0.1, 1.1–1.9 |
| 2 Multi Active Failover | 1.8, 1.10, 1.11 |
| 3 Provider Dispatch | 1.1, 1.2, 1.3, 1.10, 1.12 |
| 4 Sender Identity Precedence | 1.5, 1.13 |
| 5 Error Classification + Time Budget | 1.6, 1.8, 1.14, 1.15 |
| 6 Group A Migration | 3.1–3.17 |
| 7 Group B Migration | 2.6, 2.7, 2.9, 2.11, 2.12 |
| 8 Group C Stubs | 0.5.1, 4.1, 4.2, 4.3, 4.4 |
| 9 Activate/Deactivate Endpoints | 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.4 |
| 10 No-Active-Provider Alerting | 1.9, 4.5, 4.6, 4.7, 4.8 |
| 11 Bounce Correlation | 9.4, 9.5, 9.6, 9.7, 9.12, 9.15, 9.16 |
| 12 Bounced Address Blocklist | 1.8, 9.1, 9.2, 9.3, 9.5, 9.10, 9.13 |
| 13 Per-Provider Webhook Secrets | 9.6, 9.7, 9.14 |
| 14 Legacy Endpoint Deprecation | 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 10.3 |
| 15 Legacy Configuration Migration | 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8 |
| 16 Notification Log Schema Extensions | 2.1–2.5, 2.8, 2.10 |
| 17 Frontend Email Providers Admin | 6.1, 6.2, 6.3, 6.4, 6.5, 6.7 |
| 18 Frontend Delivery Health | 9.9, 9.11 |
| 19 Backwards Compatibility | 0.2, 0.3, 1.16, 2.7, 2.11 |
| 20 Operational Safety + Rollback | 8.7, 11.4 |
| 21 Test Coverage | All test subtasks across phases |
| 22 Phase Ordering + Hotfix | 0.5.x, 4.1, plus phase ordering of top-level tasks |
| 23 Phase 9 Cleanup | 10.1–10.7 |
| 24 Documentation Deliverables | 11.1–11.5 |
| 25 Bounce Sequencing Independence | Phase 8c (task 9.x) is independent of Phase 8b (task 8.x) |

## Definition of Done

- [ ] All Phase 0–9 tasks ticked
- [ ] All Phase Gates Summary rows pass
- [ ] Manual smoke test sequence in design.md > Test Plan executed without regressions
- [ ] BUG-1 through BUG-6 marked resolved in `docs/ISSUE_TRACKER.md`
- [ ] Release notes for each phase published
- [ ] Operational runbook entry for Phase 8b in place before that migration runs
- [ ] Existing test suite remains green throughout the rollout
