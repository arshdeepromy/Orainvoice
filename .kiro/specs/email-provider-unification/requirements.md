# Requirements Document

## Introduction

OraInvoice currently routes outbound email through three parallel paths: a hand-rolled `smtplib` loop duplicated across 14 sites, a single legacy `IntegrationConfig[smtp]` row read by 18 sites with no failover, and three TODO stubs that only write to the log. The result is fragile delivery (one provider failure can blackhole 18 email types at once), 1500+ lines of near-duplicate code, and several email flows that have never actually delivered (password reset, anomalous-login alert, token-reuse alert, org-admin invitation, fleet portal invite is partial).

This feature unifies every outbound email behind a single sender (`app/integrations/email_sender.py::send_email`) that reads the existing `email_providers` table, attempts each active provider in priority order, classifies failures as hard or soft, and falls over to the next provider on retryable errors. It fixes the activate/deactivate endpoints to support multi-active providers, adds bounce correlation so a webhook from Brevo or SendGrid can flip the originating `notification_log` row to `bounced`, and introduces a recipient blocklist so the next email to a known-bad address is short-circuited before any provider is tried.

The work is grounded in the gap-audited plan at [`plan.md`](plan.md) (Sections 1–14). This requirements document captures the user-facing acceptance criteria; design and tasks documents follow.

## Glossary

- **Unified_Sender** — the new module `app/integrations/email_sender.py` and its public `send_email(...)` function. Single source of truth for outbound email.
- **Email_Provider** — a row in the `email_providers` table (`brevo`, `sendgrid`, `mailgun`, `ses`, `gmail`, `outlook`, `custom_smtp`) with credentials, priority, and active flag.
- **Multi_Active_Failover** — the property that more than one Email_Provider can have `is_active=true`, and the Unified_Sender attempts each in `priority ASC` order until one succeeds or the chain is exhausted.
- **Group_A_Site** — one of the 14 sending functions that today uses raw `smtplib` with a hand-rolled provider loop (`email_invoice`, `send_payment_reminder`, quote send, `_send_receipt_email`, `email_service_history_report`, `_send_booking_confirmation_email`, `_send_permanent_lockout_email`, `_send_invitation_email`, `send_verification_email`, `send_receipt_email`, `_send_email_otp`, `notify_customer`, `submit_demo_request`, `send_invoice_payment_link_email`).
- **Group_B_Site** — one of the 18 sending callers that today goes through `send_email_task` → `send_org_email` → `IntegrationConfig[smtp]` (zero failover). Includes the fleet portal invite, all subscription tasks, all portal email types, all scheduled notifications, all reminder queue email sends, and the compliance-doc notification dispatcher.
- **Group_C_Stub** — a function that today only logs and never actually sends an email: `_send_password_reset_email`, `_send_anomalous_login_alert`, `_send_token_reuse_alert`, `_send_org_admin_invitation_email`.
- **Failure_Kind** — a classification on each send attempt: `HARD_RECIPIENT` (recipient address is bad), `HARD_PAYLOAD` (message body or attachment will fail at every provider), `SOFT_AUTH` (one provider's credentials are bad), `SOFT_PROVIDER` (network, timeout, 5xx), `BUDGET_EXCEEDED` (per-call total time budget exhausted). Hard kinds short-circuit the failover loop; soft kinds continue to the next provider; `BUDGET_EXCEEDED` aborts the remaining providers.
- **Send_Result** — the dataclass returned by `send_email`: `success: bool`, `provider_key: str | None`, `transport: str | None`, `message_id: str | None`, `error: str | None`, `attempts: list[EmailAttempt]`. Each `EmailAttempt` carries `provider_key`, `transport`, `success`, `error`, `failure_kind`, and `duration_ms`.
- **Bounce_Correlation** — the process by which a Brevo or SendGrid webhook event for a `provider_message_id` is matched back to the originating `notification_log` row, flipping its `status` from `sent` to `bounced` and recording the reason.
- **Bounced_Address** — a row in the `bounced_addresses` table representing a recipient that has hard-bounced (no expiry) or soft-bounced (expires in 7 days). Pre-checked by the Unified_Sender to short-circuit further sends.
- **Provider_Message_Id** — the unique identifier the provider issues for a successful send (Brevo `messageId` in REST response, SendGrid `X-Message-Id` header, RFC 5322 `Message-ID` for SMTP). Persisted on `notification_log` for correlation.
- **Recipient_Class** — `customer`, `user`, `fleet_account`, or `external` (landing page demo, public form, etc.). Determines what UI surface, if any, learns about a bounce.
- **Active_Provider_Set** — the rows in `email_providers` where `is_active=true AND credentials_set=true`, ordered by `priority ASC`.

## Scope

### In scope

- Build the Unified_Sender with REST and SMTP transports, attachment support, error classification, per-attempt and total time budgets, and `org_sender_name` / `org_reply_to` overrides.
- Migrate every Group_A_Site, Group_B_Site, and Group_C_Stub to the Unified_Sender.
- Fix the activate endpoint to support Multi_Active_Failover and add a 409 guard against deactivating the last active provider, with a row-level lock for race safety.
- Implement bounce correlation, the Bounced_Address blocklist, and per-provider webhook secrets.
- Update the admin frontend to show multiple active providers, expose the failover order, and add a Delivery Health view.
- One-time data migration from the legacy `integration_configs[smtp]` row into `email_providers`.
- Deprecate (HTTP 410 Gone) and eventually remove the legacy admin SMTP page.

### Out of scope

- Per-tenant email providers (the `email_providers` table remains platform-wide).
- Inbound email parsing, IMAP, or reply-to threading.
- Email template content or rendering changes (covered separately by the notification-template-integration spec).
- SMS provider unification (separate work; SMS uses `sms_verification_providers`).
- Branding the bounce-event email itself (we react to bounces; we don't try to recover the original recipient).
- Any change to Xero, Stripe, or Connexus integrations.

### Explicit non-goals

- **No dual-write between the two stores.** The legacy `integration_configs[smtp]` row and the new `email_providers` rows SHALL NOT be kept in lockstep. The implementation converges on `email_providers` and the legacy row is migrated once and then read no more.
- **No `is_verified` parity in v1 (BUG-7 deferred).** Adding `last_test_at` and `last_test_success` columns to `email_providers` so admins can see which providers passed their last test is recognised as useful but is deferred to a follow-up spec.
- **Mailgun `domain` field is not surfaced in the new schema.** Mailgun via SMTP only requires `username + password + smtp_host`; the legacy `domain` field stored in `integration_configs[smtp].domain` is not needed and is intentionally dropped during migration.

## Requirements

### Requirement 1: Unified Sender Public API

**User Story:** As a developer maintaining a Group_A_Site or Group_B_Site, I want one async function I can call with a recipient and a message, so that all outbound email goes through the same dispatch and failover logic.

#### Acceptance Criteria

1. THE Unified_Sender SHALL expose `async def send_email(db: AsyncSession, message: EmailMessage, *, org_sender_name: str | None = None, org_reply_to: str | None = None) -> SendResult` as its single public send entry point.
2. THE Unified_Sender SHALL expose `EmailMessage`, `EmailAttachment`, `EmailAttempt`, `SendResult`, and `FailureKind` as importable dataclasses.
3. THE Unified_Sender SHALL expose `EMAIL_SIZE_LIMIT`, `EMAIL_PER_ATTEMPT_TIMEOUT_SECONDS`, and `EMAIL_TOTAL_BUDGET_SECONDS` as module-level constants.
4. THE Unified_Sender SHALL NOT call `create_in_app_notification` itself; callers decide whether to surface failures based on `result.success` and `result.attempts`.
5. THE Send_Result SHALL include a read-only `provider` property that returns `provider_key` or empty string, for backwards compatibility with existing tests that assert on `result.provider`.
6. THE Unified_Sender SHALL accept the caller's existing `AsyncSession` and SHALL NOT open its own session.
7. THE Unified_Sender SHALL expose a public helper `dispatch_one_provider(db, provider, message, *, org_sender_name=None, org_reply_to=None) -> EmailAttempt` that the per-provider admin test endpoint (`email_providers/service.py::test_email_provider`) can reuse, so dispatch logic exists in exactly one module.

### Requirement 2: Multi Active Failover

**User Story:** As an org admin, I want to configure multiple email providers and have the system try them in priority order, so that a single provider outage does not stop my customers receiving invoices, receipts, or reminders.

#### Acceptance Criteria

1. THE Unified_Sender SHALL load the Active_Provider_Set ordered by `priority ASC` and attempt each provider in turn.
2. WHEN a provider attempt fails with Failure_Kind `SOFT_AUTH` OR `SOFT_PROVIDER`, THE Unified_Sender SHALL continue to the next provider in the chain.
3. WHEN a provider attempt fails with Failure_Kind `HARD_RECIPIENT` OR `HARD_PAYLOAD`, THE Unified_Sender SHALL stop the chain and return failure without trying additional providers.
4. WHEN any provider attempt succeeds, THE Unified_Sender SHALL stop the chain and return success with that provider's key, transport, and message id.
5. WHEN every provider in the chain fails, THE Unified_Sender SHALL return `success=False` with the last attempt's error message and the full `attempts` list populated.
6. WHEN the Active_Provider_Set is empty, THE Unified_Sender SHALL return `success=False` with `attempts=[]` and `error="No active email providers configured"`.
7. THE Send_Result SHALL record one EmailAttempt per provider attempted, with provider_key, transport, success flag, error string (when failed), failure_kind, and duration in milliseconds.

### Requirement 3: Provider Dispatch and Transport Selection

**User Story:** As an org admin, I want to configure each provider with the credentials it actually requires (REST API key for Brevo and SendGrid, SMTP user/pass for the others), so that I can use my preferred mail relay without forcing a particular transport.

#### Acceptance Criteria

1. WHEN the provider is `brevo` AND only `api_key` is set, THE Unified_Sender SHALL dispatch via the Brevo REST API at `https://api.brevo.com/v3/smtp/email`.
2. WHEN the provider is `brevo` AND both `api_key` and `smtp_login` are set, THE Unified_Sender SHALL dispatch via SMTP at `smtp-relay.brevo.com:587` with STARTTLS, using `smtp_login` as the username.
3. WHEN the provider is `sendgrid`, THE Unified_Sender SHALL dispatch via the SendGrid REST API at `https://api.sendgrid.com/v3/mail/send`.
4. WHEN the provider is `mailgun`, `ses`, `gmail`, `outlook`, OR `custom_smtp`, THE Unified_Sender SHALL dispatch via SMTP using the provider's `smtp_host`, `smtp_port`, and `smtp_encryption` settings.
5. WHEN the provider has no `smtp_host` configured, THE Unified_Sender SHALL fall back to the default-host table currently in `email_providers/service.py:default_hosts`.
6. THE Unified_Sender SHALL wrap every synchronous SMTP call in `asyncio.to_thread(...)` so the FastAPI event loop is never blocked.
7. THE Unified_Sender SHALL include attachments via the Brevo REST `attachment` array, the SendGrid REST `attachments` array, or as `MIMEApplication` parts inside `multipart/mixed` for SMTP.
8. THE Unified_Sender SHALL refuse to attempt any provider for which `credentials_set=false`.

### Requirement 4: Sender Identity Precedence

**User Story:** As an org admin, I want my organisation name and reply-to address to appear on outgoing email when the calling code chooses to override them, so that customer-facing email looks branded even though the SMTP relay is platform-wide.

#### Acceptance Criteria

1. THE Unified_Sender SHALL compute the effective `from_name` as `org_sender_name` if provided, otherwise `provider.config['from_name']`, otherwise an empty string.
2. THE Unified_Sender SHALL compute the effective `from_email` as `provider.config['from_email']` and SHALL skip a provider with Failure_Kind `SOFT_PROVIDER` and `error="missing from_email"` when that field is unset.
3. THE Unified_Sender SHALL compute the effective `reply_to` as `org_reply_to` if provided, otherwise `provider.config['reply_to']`, otherwise omit the header.
4. THE Unified_Sender SHALL apply the precedence chain consistently across REST and SMTP transports.

### Requirement 5: Error Classification and Time Budget

**User Story:** As an org admin, I do not want a single bad recipient address or a frozen provider to chew through every active provider attempt, because that wastes time and burns through any rate limit headroom.

#### Acceptance Criteria

1. WHEN a Brevo REST response is HTTP 400 with code `invalid_parameter` and a message referencing `email`, THE Unified_Sender SHALL classify the failure as `HARD_RECIPIENT`.
2. WHEN a SendGrid REST response is HTTP 400 with errors mentioning the recipient field, THE Unified_Sender SHALL classify the failure as `HARD_RECIPIENT`.
3. WHEN smtplib raises `SMTPRecipientsRefused` OR a 5xx code referencing the recipient, THE Unified_Sender SHALL classify the failure as `HARD_RECIPIENT`.
4. WHEN smtplib raises `SMTPDataError` with code 552 (message size), THE Unified_Sender SHALL classify the failure as `HARD_PAYLOAD`.
5. WHEN any REST call returns HTTP 401 OR 403, OR smtplib raises `SMTPAuthenticationError`, THE Unified_Sender SHALL classify the failure as `SOFT_AUTH`.
6. WHEN a network timeout, connect error, or 5xx response occurs, THE Unified_Sender SHALL classify the failure as `SOFT_PROVIDER`.
7. THE Unified_Sender SHALL bound each provider attempt to `EMAIL_PER_ATTEMPT_TIMEOUT_SECONDS` (default 15 seconds) for both REST and SMTP transports.
8. THE Unified_Sender SHALL bound the entire `send_email` call to `EMAIL_TOTAL_BUDGET_SECONDS` (default 45 seconds), short-circuiting remaining providers if the budget is exceeded and reporting `error="time budget exceeded"` in the Send_Result.
9. THE Unified_Sender SHALL pre-check the total attachment payload against `EMAIL_SIZE_LIMIT` (25 MB) and SHALL refuse the send with `failure_kind=HARD_PAYLOAD` and `error="attachment size exceeds limit"` before any provider is attempted.
10. WHERE a provider's transport documents a smaller per-attachment limit (Brevo REST 10 MB per file), THE Unified_Sender SHALL classify a `413 Payload Too Large` or equivalent SMTP `552` error from that provider as Failure_Kind `HARD_PAYLOAD` so the loop short-circuits rather than wasting attempts on other providers.

### Requirement 6: Group A Migration — Raw smtplib Sites

**User Story:** As a developer who needs to fix an email bug, I want every email-sending site to share one implementation, so that one fix in one file fixes the bug everywhere.

#### Acceptance Criteria

1. EACH Group_A_Site SHALL be migrated to call `send_email(...)` instead of importing smtplib and looping over Email_Providers manually.
2. AFTER migration, `grep -rn "import smtplib" app/` SHALL return only `app/integrations/email_sender.py`.
3. EACH migrated site that previously called `log_email_sent` SHALL still call `log_email_sent` after checking `result.success`.
4. EACH migrated site that previously called `create_in_app_notification` on failure SHALL still call it after checking `not result.success`.
5. EACH migrated site that previously used a per-org sender name (e.g. `notify_customer` using `org_name`) SHALL pass that value via `org_sender_name=...`.
6. THE site `_send_email_otp` (A11) SHALL no longer use `.limit(1)` and SHALL gain failover via the Unified_Sender, while continuing to raise `RuntimeError` on total failure to preserve the MFA challenge contract.
7. THE site `submit_demo_request` (A13) SHALL pass no org context to the Unified_Sender (the form is public) and SHALL return HTTP 500 to the caller on total failure.
8. THE site `send_invoice_payment_link_email` (A14) SHALL preserve any existing audit-log and notification-log calls.

### Requirement 7: Group B Migration — Failover-Free Sites

**User Story:** As an org admin, I want portal links, scheduled reminders, dunning emails, and compliance-doc notifications to use the same provider failover as everything else, so that a single provider outage doesn't silently break a dozen flows.

#### Acceptance Criteria

1. THE function `_send_email_async` in `app/tasks/notifications.py` SHALL be rewritten to call the Unified_Sender directly, replacing the call to `send_org_email`.
2. AFTER the rewrite, every Group_B_Site that calls `send_email_task` SHALL automatically gain failover, with no per-site code changes required.
3. THE legacy `send_org_email`, `get_email_client`, `load_smtp_config_from_db`, `SmtpConfig`, and `EmailClient` exports in `app/integrations/brevo.py` SHALL be retained as deprecated shims for one release, translating the new Send_Result shape to the old shape so existing tests continue to pass.
4. THE rewrite SHALL keep the existing `update_log_status` call and SHALL include `provider_key=result.provider_key` in that update.
5. THE 18 Group_B_Sites SHALL be enumerated in the spec inventory: 5 in `subscriptions.py`, 1 in `franchise/service.py`, 1 in `fleet_portal/admin_router.py`, 4 in `portal/service.py`, 3 in `notifications/service.py`, 1 in `notifications/reminder_queue_service.py`, 1 in `compliance_docs/notification_service.py`, 1 in `customers/service.py`, and 3 in `tasks/scheduled.py`.

### Requirement 8: Group C Stubs Implementation

**User Story:** As a user who clicks "Forgot password?" or accepts an invitation, I want to actually receive the email, because today the system silently fails to send several account-recovery and onboarding emails.

#### Acceptance Criteria

1. THE function `_send_password_reset_email` SHALL be implemented to send a real password reset email via the Unified_Sender, including the user's name, the reset link, and a clearly stated link expiry.
2. THE function `_send_anomalous_login_alert` SHALL send a real email including the IP address, device fingerprint where available, and the timestamp of the login attempt.
3. THE function `_send_token_reuse_alert` SHALL send a real email including a "sessions invalidated automatically" notice and a link to review active sessions.
4. THE function `_send_org_admin_invitation_email` SHALL send a real email via `send_email_task`, including the secure signup link and the org name.
5. EACH implemented stub SHALL use the existing notification logging (`log_email_sent`) so the admin notification log shows the attempt.

### Requirement 9: Activate and Deactivate Endpoints

**User Story:** As an org admin, I want to activate any number of email providers without deactivating the others, so that I can configure failover. I also want to be prevented from accidentally deactivating my last active provider.

#### Acceptance Criteria

1. THE endpoint `POST /api/v2/admin/email-providers/{id}/activate` SHALL set `is_active=true` on the named row only and SHALL NOT modify any other row's `is_active` field.
2. WHEN a provider is already active, THE activate endpoint SHALL return success idempotently without writing to the audit log.
3. THE endpoint `POST /api/v2/admin/email-providers/{id}/deactivate` SHALL acquire a row-level lock (`SELECT ... FOR UPDATE`) on every row in the Active_Provider_Set before evaluating whether deactivation would leave zero active providers.
4. WHEN deactivating the named provider would result in an empty Active_Provider_Set, THE deactivate endpoint SHALL return HTTP 409 with the message `"Activate another provider before deactivating this one — at least one active email provider is required for outbound mail."` and SHALL NOT modify the row.
5. WHEN two concurrent deactivate calls target the last two active providers, exactly one SHALL succeed and the other SHALL return HTTP 409.
6. THE list endpoint response SHALL include `active_providers: list[str]` (the keys of all active providers in priority order) AND retain `active_provider: str | None` (the highest-priority active key) for backwards compatibility for one release.
7. THE audit log entry written by activate SHALL use action name `email_provider_activated` (not `set_as_only_active`).

### Requirement 10: No-Active-Provider Alerting

**User Story:** As a global admin, I want to be alerted in-app when outbound email is fully broken, so that I do not first hear about it from a frustrated customer or org admin.

#### Acceptance Criteria

1. WHEN the Unified_Sender returns `success=False` AND `attempts == []` (no providers configured), THE system SHALL fire `create_in_app_notification(category='email_failure', severity='critical', recipient_role='global_admin', ...)` with a body explaining that outbound email is currently disabled.
2. WHEN the Unified_Sender returns `success=False` AND every attempt's `failure_kind` is `SOFT_AUTH`, THE system SHALL fire the same in-app notification with a body explaining that all providers' credentials appear invalid.
3. THE no-active-provider notification SHALL be deduped to once per hour using a coalescing key in Redis (or the in-app notifications service if it already supports deduplication).
4. THE all-auth-fail notification SHALL be deduped to once per day.
5. THE notifications SHALL include a deep link to the admin Email Providers page.

### Requirement 11: Bounce Correlation and Delivery Tracking

**User Story:** As an org admin, I want a bounced invoice email to show as "bounced" in the notification log instead of staying as "sent", so that I can find addresses that need updating.

#### Acceptance Criteria

1. THE Unified_Sender SHALL capture the provider's message id from each successful send (Brevo `messageId` from the JSON response, SendGrid from the `X-Message-Id` header, RFC 5322 `Message-ID` for SMTP) and persist it on `notification_log.provider_message_id`.
2. THE `brevo_bounce_webhook` and `sendgrid_bounce_webhook` handlers SHALL look up the originating `notification_log` row by `provider_message_id` and SHALL set `status='bounced'`, `bounced_at=now()`, and `bounce_reason=<event reason>`.
3. THE Brevo `delivered` event SHALL update `notification_log.delivered_at = now()` when the row is found.
4. WHEN a bounce or delivered event arrives for a `provider_message_id` that does not match any `notification_log` row, THE webhook handler SHALL still upsert the recipient into `bounced_addresses` (for bounces) and SHALL log a warning at info level.
5. THE notification log status transitions SHALL only follow legal paths: `queued → sent`, `sent → delivered`, `sent → bounced`, `queued → failed`. A property test SHALL exercise random orderings of webhook events and assert no illegal transitions occur.

### Requirement 12: Bounced Address Blocklist

**User Story:** As an org admin, I do not want the system to keep retrying email to a known-bad address, because that wastes provider quota and risks getting our domain rate-limited.

#### Acceptance Criteria

1. THE system SHALL maintain a `bounced_addresses` table with columns: `id`, `org_id` (nullable), `email_address`, `bounce_kind` (`hard` | `soft` | `blocked`), `reason`, `first_seen_at`, `last_seen_at`, `hit_count`, `expires_at` (nullable).
2. WHEN a bounce webhook event is processed, THE system SHALL upsert into `bounced_addresses` keyed on `(org_id, email_address)`. Hard bounces SHALL have `expires_at=NULL`; soft bounces SHALL have `expires_at = now() + 7 days`.
3. THE Unified_Sender SHALL pre-check the recipient against `bounced_addresses` for the relevant `(org_id, email_address)` before attempting any provider.
4. WHEN the recipient has an unexpired hard-bounce row, THE Unified_Sender SHALL return `success=False` with `attempts=[]`, `failure_kind=HARD_RECIPIENT`, and `error="recipient is on the bounce list"`.
5. WHEN the recipient has only a soft-bounce row that has not expired, THE Unified_Sender SHALL log a warning AND proceed to attempt the send.
6. A daily background task SHALL delete `bounced_addresses` rows where `expires_at < now()`.
7. AN admin SHALL be able to clear a bounce row from the Delivery Health UI, after which the next send to that address SHALL be attempted normally.
8. WHEN a hard bounce is recorded and the address matches an active customer or user, THE system SHALL fire `create_in_app_notification(category='email_bounced', recipient_role='org_admin', ...)` with the recipient and reason.

### Requirement 13: Per-Provider Webhook Secrets

**User Story:** As an org admin, I want bounce webhook signature verification to use the secret stored alongside each provider, so that rotating a key doesn't require an environment variable change and a redeploy.

#### Acceptance Criteria

1. THE Brevo bounce webhook handler SHALL read the signing secret from `email_providers.config['brevo_webhook_secret']` first, falling back to `app_settings.brevo_webhook_secret` (env) for one release.
2. THE SendGrid bounce webhook handler SHALL read the signing secret from `email_providers.config['sendgrid_webhook_secret']` first, falling back to env for one release.
3. WHEN multiple providers of the same kind are configured, THE webhook handler SHALL try each provider's secret in priority order and accept the first successful signature match.
4. WHEN no configured secret matches, THE webhook handler SHALL return HTTP 403 and SHALL NOT process the payload.

### Requirement 14: Legacy Endpoint Deprecation

**User Story:** As a global admin, I want the old SMTP integration page replaced by the existing Email Providers page, so that there is one place to configure outbound email.

#### Acceptance Criteria

1. THE endpoints `PUT /api/v1/admin/integrations/smtp` and `POST /api/v1/admin/integrations/smtp/test` SHALL return HTTP 410 Gone with a `Location` header pointing to `/api/v2/admin/email-providers`.
2. EACH 410 response SHALL emit a structured log line `legacy_smtp_endpoint_hit path=<path> remote=<ip>` so deprecation telemetry can be grepped from access logs.
3. THE service-layer functions `save_smtp_config` and the legacy `send_test_email` (in `admin/service.py`) SHALL be removed once a workspace-wide grep confirms zero remaining call sites.
4. THE legacy endpoints SHALL only be removed entirely once one full release window passes with zero `legacy_smtp_endpoint_hit` log lines.
5. THE frontend SHALL no longer offer a route to a separate SMTP configuration page; configuration is exclusively through the Email Providers admin page.
6. THE read-only admin endpoints `list_integrations` and `integration_cost_dashboard` SHALL continue to function correctly with multiple active providers, surfacing either an aggregate "Email: Healthy ✓ (N active providers)" tile or a comma-separated list of active provider names. A frontend visual check SHALL confirm the dashboard tile is not misleading after Phase 5 ships.
7. THE backup/restore admin functionality (`export_integration_settings` and `import_integration_settings`) SHALL include rows from BOTH `integration_configs` and `email_providers` tables, and SHALL remain backward-compatible with backup files generated before the Phase 8b data migration.

### Requirement 15: Legacy Configuration Migration

**User Story:** As an org operator who configured SMTP via the old admin page, I want my settings carried across to the new Email Providers page automatically, so that I don't have to re-enter API keys to keep email working after the upgrade.

#### Acceptance Criteria

1. A one-time Alembic migration SHALL read the legacy `integration_configs` row where `name='smtp'`, decrypt the blob via `envelope_decrypt_str`, and re-encrypt it into the matching `email_providers` row.
2. THE migration SHALL map the legacy `provider` field to the new `provider_key`: `'brevo' → 'brevo'`, `'sendgrid' → 'sendgrid'`, `'smtp' → 'custom_smtp'`.
3. THE migration SHALL set `is_active=true`, `priority=1`, and `credentials_set=true` on the target `email_providers` row.
4. THE migration SHALL skip the upgrade for any target row that already has `credentials_set=true` so an admin's already-configured provider is not clobbered.
5. THE migration SHALL acquire `pg_advisory_lock(hashtext('email_provider_rotate'))` as its first step and SHALL release it on completion.
6. THE `app/cli/rotate_keys.py` script SHALL acquire the same advisory lock around its EmailProvider re-encrypt loop, so a key rotation cannot run concurrently with the migration.
7. WHEN the legacy row was updated less than 5 minutes before the migration runs, THE migration SHALL abort with a clear error and SHALL NOT touch any rows.
8. THE migration SHALL include a downgrade path that re-encrypts the `email_providers` credentials back into the legacy row.
9. WHEN decryption of the legacy `integration_configs[smtp]` row fails (corrupted blob, mismatched DEK), THE migration SHALL log the failure at error level, leave both rows unchanged, and emit an operator-actionable error message; the migration SHALL NOT abort the broader Alembic upgrade because of a single corrupted row, and SHALL produce a follow-up advisory that an admin must reconfigure the provider manually through the new Email Providers page.

### Requirement 16: Notification Log Schema Extensions

**User Story:** As an org admin, I want the admin notification log to show which provider delivered each email and whether it later bounced, so that I can debug delivery problems and find addresses that need cleaning up.

#### Acceptance Criteria

1. THE `notification_log` table SHALL gain nullable columns: `provider_key VARCHAR(50)`, `provider_message_id TEXT`, `bounced_at TIMESTAMPTZ`, `bounce_reason TEXT`, `delivered_at TIMESTAMPTZ`.
2. THE column `provider_message_id` SHALL have an index that excludes NULL rows.
3. THE service helpers `log_email_sent` and `update_log_status` SHALL accept and persist `provider_key`, `provider_message_id`, `bounced_at`, `bounce_reason`, and `delivered_at` keyword arguments.
4. THE helper `_log_entry_to_dict` SHALL include all five new fields in its output.
5. THE Pydantic schema for the notification log endpoint SHALL include all five new fields, with `None` allowed.
6. THE admin notification-log frontend table SHALL display a "Provider" column (rendering `—` when null) and a status badge that shows `bounced` or `delivered` distinctly from `sent`.

### Requirement 17: Frontend — Email Providers Admin Page

**User Story:** As a global admin, I want the Email Providers page to make it obvious which providers will be tried first, so that I can understand the failover behaviour at a glance.

#### Acceptance Criteria

1. THE Email Providers page SHALL show an "Active Providers" banner listing every active provider in priority order, comma-separated. When only one is active, the banner displays a singular label.
2. THE Email Providers page SHALL show a failover preview line above the provider list, e.g. `Send order: 1. Brevo → 2. Gmail → 3. Custom SMTP`, derived from the list response.
3. THE priority slider on each provider row SHALL be visible whenever `credentials_set=true`, regardless of `is_active`, so an admin can rank a configured-but-inactive provider before activating it.
4. THE Brevo setup guide content SHALL document both authentication options: REST API key (no SMTP login required) and SMTP key with SMTP login.
5. THE deactivate button SHALL be disabled in the UI when the provider is the last active one, with a tooltip explaining why.

### Requirement 18: Frontend — Delivery Health View

**User Story:** As an org admin, I want a single screen that shows recent bounces and lets me clear them, so that I can react to delivery problems without trawling the notification log.

#### Acceptance Criteria

1. THE admin frontend SHALL include a Delivery Health view (either a tab on the Email Providers page or a new page).
2. THE view SHALL list the most recent 100 bounce events with timestamp, recipient address, provider key, bounce kind, and reason.
3. THE view SHALL provide a "Clear bounce" action per row that removes the address from `bounced_addresses` so subsequent sends are attempted normally.
4. THE view SHALL show aggregate bounce counts for the last 24 hours, 7 days, and 30 days, broken down by provider.
5. THE view SHALL be accessible only to roles `org_admin` and `global_admin`.

### Requirement 19: Backwards Compatibility During Transition

**User Story:** As a developer reading the existing test suite, I want the cutover to not break tests that mock `send_org_email`, `send_email_task`, or assert on `result.provider`, so that the migration can ship in small PRs without a flag day.

#### Acceptance Criteria

1. THE legacy `send_org_email` SHALL remain importable from `app/integrations/brevo.py` for one release as a shim that calls the Unified_Sender and translates the result.
2. THE legacy `EmailMessage`, `EmailAttachment`, and `SendResult` types SHALL be re-exported from `app/integrations/brevo.py` for one release.
3. THE Send_Result `provider` read-only property SHALL return the `provider_key` value so tests asserting on `result.provider` continue to pass.
4. THE existing tests `test_email_infrastructure.py`, `test_email_delivery_tracking.py`, `test_email_templates.py`, `test_transfer_notifications.py`, `test_send_portal_link.py`, `test_portal_dsar.py`, `test_portal_quote_acceptance_notification.py`, `test_portal_recover.py`, `test_notification_retry_property.py`, `test_landing_page.py`, `test_rotate_keys.py`, `test_integration_config.py`, AND `test_security_focused.py` SHALL all continue to pass through every phase of the rollout.

### Requirement 20: Operational Safety and Rollback

**User Story:** As the engineer running the production deployment, I want each phase to be independently rollback-able, so that a regression in one phase does not force me to revert the whole project.

#### Acceptance Criteria

1. EACH phase from 0 through 9 (per [`plan.md`](plan.md) Section 5) SHALL be deployable independently and rollback-able by reverting that phase's commits.
2. THE legacy admin endpoints SHALL NOT be removed (only 410-Gone'd) until one full release window passes with zero `legacy_smtp_endpoint_hit` log lines.
3. THE legacy data migration (Phase 8b) SHALL include a `downgrade()` function that has been tested end-to-end in staging.
4. THE shim retention requirement (one release of `send_org_email` shim, two releases of legacy 410 endpoints) SHALL be documented in the release notes.

### Requirement 21: Test Coverage

**User Story:** As a reviewer, I want every new code path to have automated tests so that the failover, error classification, blocklist, and bounce correlation logic cannot silently regress.

#### Acceptance Criteria

1. NEW unit tests SHALL cover the dispatch matrix (one test per `(provider_key, credentials shape)` combination).
2. NEW unit tests SHALL cover error classification for each Failure_Kind across both REST and SMTP transports.
3. NEW unit tests SHALL cover the per-attempt and total time budgets, asserting that a slow provider does not stall the whole chain past the budget.
4. NEW unit tests SHALL cover sender identity precedence (caller args > provider config > defaults > skip-when-missing).
5. NEW integration tests SHALL cover the `send_email_task` rewrite end-to-end with mock httpx and smtplib.
6. NEW per-Group_A_Site failover tests SHALL exercise a 2-provider chain where the first provider returns auth-fail and the second succeeds.
7. NEW tests SHALL cover the activate/deactivate concurrent-call race and assert exactly-one success on the last-two-providers case.
8. NEW tests SHALL cover bounce correlation, the blocklist short-circuit, per-provider webhook secret iteration, and the legal `notification_log.status` transitions (property-based).
9. NEW tests SHALL cover the no-active-provider and all-auth-fail in-app notification triggers and dedup behaviour.
10. NEW tests SHALL cover the legacy SMTP migration including the no-clobber rule, the recent-write abort, and the advisory-lock acquisition.

### Requirement 22: Phase Ordering and Hotfix Cherry-Pick

**User Story:** As a release manager, I want the security-critical password-reset hotfix to ship ahead of the main unification work, and Phase 8c (bounce correlation) to ship after the schema work in Phase 8a, so that each phase lands on a stable foundation.

#### Acceptance Criteria

1. THE Phase 0.5 password-reset hotfix SHALL be implemented and shipped using the existing raw `smtplib` + Email_Provider loop pattern (mirroring `_send_invitation_email`) and SHALL NOT depend on the Unified_Sender.
2. WHEN Phase 4 lands, THE function `_send_password_reset_email` SHALL be rewritten to call the Unified_Sender, replacing the Phase 0.5 raw `smtplib` implementation.
3. THE Phase 4 rewrite of `_send_password_reset_email` SHALL include a regression test (`tests/test_password_reset_email.py::test_failover_chain`) asserting delivery succeeds when 2 of 3 active providers fail.
4. THE Phase 8a schema migration SHALL be applied alongside the Phase 2 deploy so the `update_log_status(provider_key=...)` call introduced in Phase 2 lands on a real column.
5. THE Phase 8c work (bounce correlation, blocklist, per-provider webhook secrets) SHALL be sequenced AFTER Phase 8a (which adds `provider_key` to `notification_log`) and SHALL be either alongside or before Phase 9 cleanup; it SHALL NOT depend on Phase 8b's data migration having completed.

### Requirement 23: Phase 9 Cleanup — Dead Code Removal

**User Story:** As a developer maintaining the notifications task module, I want the dead retry constants and unused helpers removed once the Unified_Sender has proven stable, so that future readers don't try to use them.

#### Acceptance Criteria

1. AFTER one full release window of Phase 2 in production, THE constants `RETRY_DELAYS`, `MAX_RETRIES`, and the helper `_get_retry_delay` SHALL be removed from `app/tasks/notifications.py`.
2. AFTER one full release window of Phase 7 in production, THE legacy `send_org_email`, `get_email_client`, `load_smtp_config_from_db`, `SmtpConfig`, and `EmailClient` shims SHALL be removed from `app/integrations/brevo.py`.
3. THE 410-Gone endpoint stubs at `/api/v1/admin/integrations/smtp` and `/api/v1/admin/integrations/smtp/test` SHALL only be removed once a workspace-wide search of one full release window of access logs returns zero `legacy_smtp_endpoint_hit` entries.
4. THE legacy `integration_configs[name='smtp']` row MAY be deleted in a follow-up migration OR retained for forensic value; the choice is operator discretion and SHALL NOT block Phase 9 sign-off.
5. THE `app/cli/rotate_keys.py` script SHALL require no change at Phase 9 cleanup; its existing generic iteration over `IntegrationConfig` rows works whether or not the smtp row exists.

### Requirement 24: Documentation and Runbook Deliverables

**User Story:** As an on-call operator, I want a runbook entry for the post-Phase-8b state so that I know what to tell admins after the cutover, particularly about re-testing each provider.

#### Acceptance Criteria

1. THE release notes for the Phase 8b deploy SHALL include: a list of active providers carried across, a recommendation that each org admin re-runs the per-provider Test button on the new Email Providers page to confirm credentials, and a note that the legacy `is_verified` flag is not carried across.
2. THE release notes SHALL document the shim retention period: `send_org_email` shim retained for one release post-Phase-2; the 410-Gone endpoints retained for at least one release post-Phase-7.
3. THE operational runbook SHALL include the maintenance-window prerequisites for Phase 8b: legacy GUI disabled, no recent writes to `integration_configs[smtp]`, no `rotate_keys` job running, advisory lock acquired.

### Requirement 25: Bounce Correlation Sequencing and Independence

**User Story:** As a developer planning the bounce-correlation rollout, I want Phase 8c to be deployable independently of the legacy data migration in Phase 8b, so that delivery health visibility doesn't have to wait on a maintenance window.

#### Acceptance Criteria

1. THE Phase 8c bounce-correlation work SHALL be deployable independently of Phase 8b.
2. EVEN BEFORE the Phase 8b legacy data migration runs, THE bounce-correlation flow SHALL function for any email sent through the Unified_Sender (which is Phase 1+2 onward).
3. THE migration in Phase 8c that adds `provider_message_id`, `bounced_at`, `bounce_reason`, and `delivered_at` columns to `notification_log` SHALL be additive and reversible (NULL-able columns, no backfill required).
4. THE migration in Phase 8c that creates the `bounced_addresses` table SHALL include a downgrade that drops the table cleanly.
5. THE per-provider webhook secret read path SHALL fall back to the env var `app_settings.brevo_webhook_secret` for one release after Phase 8c ships, so a deployment that has not yet stored the secret in `email_providers.config` continues to verify webhooks.

## Acceptance Criteria — Project Done When

These mirror the plan's Section 13 acceptance criteria as updated in Section 14.8.

1. Every outbound email in the codebase routes through `send_email`.
2. `grep -rn "import smtplib" app/` returns only `app/integrations/email_sender.py`.
3. The `email_providers` table is the only configuration source read at runtime; `integration_configs[smtp]` is no longer read.
4. With three active providers configured (priorities 1/2/3), if provider 1 returns auth failure, the email is delivered via provider 2 and `notification_log.status='sent'`, `notification_log.provider_key='<provider 2>'`.
5. Activating a fourth provider in the UI does not deactivate the existing three.
6. The Brevo setup guide explicitly documents REST-API-key vs SMTP-key+login.
7. Password reset, anomalous-login, token-reuse alert, and org-admin invitation emails are actually sent.
8. MFA OTP supports failover to a second provider.
9. The legacy admin SMTP page is gone from the frontend; the legacy API endpoints return HTTP 410 Gone.
10. All existing tests pass; new failover, classification, race, blocklist, bounce-correlation, and migration tests pass.
11. Every email-sending function in the codebase (Group A14, Group B18, and the C1–C4 stubs) routes through the Unified_Sender. `_send_org_admin_invitation_email` and `_send_fleet_portal_invite_email` are explicitly verified.
12. Hard-bounce errors short-circuit the failover chain instead of consuming every provider attempt.
13. The Unified_Sender honours per-attempt and total time budgets. A frozen provider does not stall the request beyond `EMAIL_PER_ATTEMPT_TIMEOUT_SECONDS`.
14. Concurrent deactivate calls on the last two active providers serialise: exactly one succeeds, the other returns 409.
15. If every provider becomes unconfigured at once, an in-app notification fires to global_admin within one send attempt (deduped per hour).
16. Bounces correlate to the originating `notification_log` row via `provider_message_id`; a known-hard-bounced address is refused before any provider is tried.
