# Email Provider Unification — Multi-Provider Failover for All Email Paths

**Status:** Plan only — no code changes.
**Author:** investigation 2026-05-13
**Goal:** Every outbound email in the app goes through one shared sender that reads the `email_providers` table, attempts providers in priority order, and fails over on any error. Multi-active + priority-based fallback works for every email type.

---

## 1. Scope & Goals

### In scope
- Replace every direct `smtplib`/`send_org_email`/`get_email_client` call with a single unified sender.
- Make the existing `email_providers` table the **only** source of truth for outbound email configuration.
- Support multi-active providers with priority-ordered failover for **every** email type (not just invoices/quotes/payments/vehicle reports).
- Fix the `activate` endpoint so it no longer deactivates other providers.
- Migrate the legacy `integration_configs[name='smtp']` row into an `email_providers` row at upgrade time.
- Remove dead legacy code paths once migration is verified.

### Out of scope
- Anything SMS-related (separate `sms_verification_providers` machinery, untouched).
- Brevo bounce-webhook signature verification (`brevo_webhook_secret` in env settings — unchanged).
- Org-level (per-tenant) email providers — the `email_providers` table is platform-wide; we keep that property.
- Email template content/rendering changes — bodies stay as-is.

### Non-goal: backwards-compatible dual-write
We will **not** keep both `integration_configs[smtp]` and `email_providers` in lockstep. The plan converges on `email_providers` and removes the legacy path entirely (after a one-time data migration).

---

## 2. Current-State Audit — Every Email Send Site

Each site below has been read end-to-end. The "config source" column tells you whether the site reads from `email_providers` (good but duplicated) or the legacy `integration_configs.smtp` (no failover at all).

### Group A — already reads `email_providers` but uses **raw `smtplib`** with a hand-rolled failover loop (14 sites, ~1500 LOC of near-duplicate code)

> **Line numbers re-baselined 2026-05-25.** Function names are the source of truth; line numbers track HEAD at re-baseline time and may drift again.

| # | Location | Function | Notes |
|---|---|---|---|
| A1 | `app/modules/invoices/service.py:4046` | `email_invoice` | Loop + attachments + MIME building; ~250 LOC. |
| A2 | `app/modules/invoices/service.py:4441` | `send_payment_reminder` | Reuses the same provider loop pattern. |
| A3 | `app/modules/quotes/service.py:989` | quote email send | Loop + attachments. |
| A4 | `app/modules/payments/service.py:497` | `_send_receipt_email` | Post-payment receipt with PDF attachment. `smtplib` import at L526, provider loop ~L687. |
| A5 | `app/modules/vehicles/report_service.py:293` | `email_service_history_report` | Loop + PDF + HTML template. |
| A6 | `app/modules/bookings/service.py:1099` | `_send_booking_confirmation_email` | Plain-text body, loop. |
| A7 | `app/modules/auth/service.py:360` | `_send_permanent_lockout_email` | HTML + text, loop. Uses `async_session_factory`. |
| A8 | `app/modules/auth/service.py:2523` | `_send_invitation_email` | HTML + text, loop, dev fallback logs URL. |
| A9 | `app/modules/auth/service.py:2825` | `send_verification_email` | HTML + text, loop, dev fallback. |
| A10 | `app/modules/auth/service.py:3027` | `send_receipt_email` | Paid-plan signup receipt, loop. |
| A11 | `app/modules/auth/mfa_service.py:370` | `_send_email_otp` | **`.limit(1)` at L397 — no failover.** Raises `RuntimeError` if provider 1 fails. Bug. |
| A12 | `app/modules/customers/service.py:652` | `notify_customer()` (email channel) | `smtplib` import at L698; ad-hoc customer messages, loop. Uses `org_name` as `from_name` override. |
| A13 | `app/modules/landing/router.py:57` | `submit_demo_request()` | Public landing page demo request notification, loop. **No org context** (`org_id=None`). |
| A14 | `app/modules/payments/service.py:349` | `send_invoice_payment_link_email` | **Added in v1.10.2 "Send Payment Link"** — same hand-rolled `smtplib` loop pattern as A1. `smtplib` import at L526, provider query at L599, SMTP at L687. |

### Group B — uses unified `send_email_task` → `send_org_email` → `IntegrationConfig[smtp]` (17 sites, **no failover at all**)

All of these end up at `app/integrations/brevo.py:341` → `get_email_client` → `load_smtp_config_from_db` (reads one row from `integration_configs` where `name='smtp'`). If that single config fails, the email fails.

| # | Location | Template type |
|---|---|---|
| B1 | `app/modules/customers/service.py:2087` | `portal_link` (customer portal invite) |
| B2 | `app/modules/franchise/service.py:247` | franchise admin notifications |
| B3 | `app/modules/portal/service.py:1364` | `quote_accepted` portal notif |
| B4 | `app/modules/portal/service.py:1463` | portal booking notif |
| B5 | `app/modules/portal/service.py:2127` | portal DSAR |
| B6 | `app/modules/portal/service.py:2240` | portal recover (link recovery) |
| B7 | `app/modules/notifications/service.py:1214` | customer notification dispatch (overdue) — inside `process_wof_rego_reminders` body |
| B8 | `app/modules/notifications/service.py:1328` | wof/rego reminders |
| B9 | `app/modules/notifications/service.py:1510` | general notification rules send loop (scheduled rules dispatcher). **Note**: L2014-2025 is a separate `select(EmailProvider).where(is_active=True)` gating check (Group E, read-only) — do NOT migrate that one. |
| B10 | `app/modules/notifications/reminder_queue_service.py:610` | scheduled reminder queue — inside `_send_email_reminder` at L590 |
| B11 | `app/modules/compliance_docs/notification_service.py:270` | compliance doc notifications |
| B12 | `app/tasks/subscriptions.py:489` | dunning email |
| B13 | `app/tasks/subscriptions.py:567` | trial expiry reminder |
| B14 | `app/tasks/subscriptions.py:760` | subscription invoice |
| B15 | `app/tasks/subscriptions.py:793` | dunning payment failed |
| B16 | `app/tasks/subscriptions.py:929` | suspension warning/notice |
| B17 | `app/tasks/scheduled.py:97`, `:219`, `:682` | scheduled notifications (3 inner sites) |

### Group C — TODO stubs (no email actually sent)

| # | Location | What it should do |
|---|---|---|
| C1 | `app/modules/auth/service.py:861` `_send_token_reuse_alert` | currently just logs |
| C2 | `app/modules/auth/service.py:635` `_send_anomalous_login_alert` | currently just logs |
| C3 | `app/modules/auth/service.py:1892` `_send_password_reset_email` | currently just logs — **SECURITY HOTFIX, scheduled ahead of Phase 3 (see Phase 0.5)**. Today, every "Forgot password?" click silently fails to email; users cannot recover their account. |

### Group D — admin endpoints

| # | Location | Purpose |
|---|---|---|
| D1 | `app/modules/admin/router.py:701` `test_smtp_email` | Legacy admin test endpoint; reads `IntegrationConfig.smtp`. |
| D2 | `app/modules/admin/router.py:650` `configure_smtp` → `save_smtp_config` | Legacy write endpoint for `IntegrationConfig.smtp`. |
| D3 | `app/modules/email_providers/router.py:136` `post_test` | New per-provider test endpoint. **Just fixed for Brevo REST API + SMTP-with-login (2026-05-13).** |
| D4 | `app/modules/email_providers/router.py:52` `post_activate` | Currently deactivates all others — bug to fix here. |
| D5 | `app/modules/admin/router.py:1340` `list_integrations` + `:1206` `integration_cost_dashboard` + `app/modules/admin/service.py:4724` | Read-only callers that check "any active email provider"; already compatible with multi-active. |

### Group E — supporting modules (read-only or non-send)

| # | Location | Notes |
|---|---|---|
| E1 | `app/modules/notifications/reminder_queue_service.py:118` | Gating check `is_active=True ORDER BY priority` — compatible with multi-active. |
| E2 | `app/modules/notifications/service.py:2022` | Same gating pattern. (Previously documented as L1835; drift +187.) |
| E3 | `app/modules/admin/service.py:5796` `export_integration_settings` / `app/modules/admin/router.py:1485` `restore_integration_settings` route → service-layer function is named **`import_integration_settings`** in `admin/service.py` (NOT `restore_integration_settings` — that's the route handler). Backup/restore covers BOTH `integration_configs` and `email_providers`. Restore must remain backward-compatible during transition. |
| E4 | `app/cli/rotate_keys.py:23` | Key rotation iterates `EmailProvider.credentials_encrypted` and `IntegrationConfig.config_encrypted` separately; needs no changes if we keep both columns. |
| E5 | `app/modules/notifications/router.py:863` `brevo_bounce_webhook` & `:946` `sendgrid_bounce_webhook` | Inbound webhooks — independent, unchanged. |

---

## 3. Data Model: The Two Parallel Stores

### `integration_configs[name='smtp']` (legacy)
- Single row, blob JSON encrypted with envelope crypto.
- Fields stored: `provider` (brevo/sendgrid/smtp), `api_key`, `host`, `port`, `username`, `password`, `domain`, `from_email`, `from_name`, `reply_to`.
- Created by `save_smtp_config()`, decrypted by `load_smtp_config_from_db()`.
- Verified flag (`is_verified` column on `integration_configs`) flipped by the legacy admin test endpoint.

### `email_providers` (current, target)
- Multiple rows. Columns from [app/modules/admin/models.py:435-463](app/modules/admin/models.py#L435-L463):
  - `provider_key` (unique): `brevo` | `sendgrid` | `mailgun` | `ses` | `gmail` | `outlook` | `custom_smtp`
  - `display_name`, `description`, `setup_guide`
  - `smtp_host`, `smtp_port`, `smtp_encryption` (none/tls/ssl)
  - `priority` (int, lower = first try), `is_active` (bool — schema allows multiple `true`)
  - `credentials_set` (bool), `credentials_encrypted` (LargeBinary — JSON blob)
  - `config` (JSONB) — holds `from_email`, `from_name`, `reply_to`
- Credentials JSON shape (varies by provider — see `EmailProviders.tsx:27-69`):
  - `brevo`: `{api_key, smtp_login?}` (after the 2026-05-13 fix)
  - `sendgrid`: `{api_key}`
  - `mailgun`, `ses`, `gmail`, `outlook`, `custom_smtp`: `{username, password}` (custom_smtp also has `smtp_host`)
- Seeded by migration `0065_create_email_providers.py` with all 7 providers pre-populated; `0074_add_email_provider_encryption_priority.py` added the two newer columns.

### Org-level overrides
- Today: `send_email_task` accepts `org_sender_name` and `org_reply_to`. These flow into `EmailMessage.from_name` / `EmailMessage.reply_to` and override the platform-wide defaults from `config.from_email` / `config.from_name`.
- The unified sender **must preserve this override capability** — at least 4 portal sites and 1 customer site (B1, B3–B6) rely on it.

---

## 4. Target Architecture

### 4.1 New module: `app/integrations/email_sender.py`

Provides one public function and supporting types. Replaces (over time) `app/integrations/brevo.py`'s `send_org_email`, `EmailClient`, `load_smtp_config_from_db`, `get_email_client`, and `SmtpConfig`.

```python
# Public API (final shape — implementation deferred to execution phase)

@dataclass
class EmailAttachment: ...      # (copy from brevo.py — filename, content, mime_type)

@dataclass
class EmailMessage: ...         # (copy from brevo.py — to_email, to_name, subject, html_body, text_body, attachments)

@dataclass
class EmailAttempt:
    provider_key: str           # which provider tried
    transport: str              # 'rest_api' | 'smtp'
    success: bool
    error: str | None
    duration_ms: int

@dataclass
class SendResult:
    success: bool
    provider_key: str | None    # which provider actually delivered
    transport: str | None
    message_id: str | None
    error: str | None           # only set when success=False, summarizes last error
    attempts: list[EmailAttempt]

    # --- Backwards-compat alias for one release ---
    # The existing brevo.py SendResult exposed a single `provider: str` field.
    # Tests assert on `result.provider` (e.g. test_security_focused.py:359,
    # test_email_infrastructure.py). Expose a read-only alias so those tests
    # keep working until Phase 9 retires the shim.
    @property
    def provider(self) -> str:
        return self.provider_key or ""

async def send_email(
    db: AsyncSession,
    message: EmailMessage,
    *,
    org_sender_name: str | None = None,   # overrides config.from_name
    org_reply_to: str | None = None,      # overrides config.reply_to
    on_total_failure: TotalFailureAction = TotalFailureAction.LOG_ONLY,
) -> SendResult:
    """Send via every active email_providers row in priority order until one succeeds.

    The sender does NOT call ``create_in_app_notification`` or log to
    ``notification_log`` itself — callers own those side-effects, using
    ``result.success`` / ``result.attempts`` to decide what to do.
    No ``org_id`` parameter: the caller already has the org context and
    is the one that decides whether to surface a failure.
    """
```

### 4.2 Dispatch matrix inside `send_email`

For each provider (ordered by `priority ASC`, `is_active=True`, `credentials_set=True`):

| Provider | Transport chosen | Reason |
|---|---|---|
| `brevo` + `api_key` only | Brevo REST API v3 (`api.brevo.com/v3/smtp/email`) | Form's `xkeysib-...` key works on REST. |
| `brevo` + `api_key` + `smtp_login` | SMTP (`smtp-relay.brevo.com:587` STARTTLS) | User supplied SMTP login → SMTP key path. |
| `sendgrid` + `api_key` only | SendGrid v3 REST (`api.sendgrid.com/v3/mail/send`) | Same pattern as Brevo. |
| `mailgun`, `ses`, `gmail`, `outlook`, `custom_smtp` | SMTP (with `smtp_encryption` ∈ none/tls/ssl) | Standard SMTP auth. |

Failure within a single provider attempt is caught, recorded in `attempts`, and the loop continues. Total exhaustion returns `success=False` with the last error.

### 4.3 Where this lives

Place the new module at `app/integrations/email_sender.py`. Keep `app/integrations/brevo.py` for one release as a thin shim that re-exports `EmailMessage`, `EmailAttachment`, `SendResult` for backwards-compat with tests that import them. Removal in cleanup phase.

### 4.4 `send_email_task` rewrite

[app/tasks/notifications.py:32-71](app/tasks/notifications.py#L32-L71)'s `_send_email_async` currently calls `send_org_email` (which reads `IntegrationConfig.smtp`). Rewrite to:

```python
async def _send_email_async(...):
    async with async_session_factory() as session:
        async with session.begin():
            message = EmailMessage(
                to_email=to_email, to_name=to_name, subject=subject,
                html_body=html_body, text_body=text_body, attachments=[],
            )
            result = await send_email(
                session, message,
                org_sender_name=org_sender_name,
                org_reply_to=org_reply_to,
            )
            if result.success:
                # provider_key column added in Phase 8 sub-step 8a (see below)
                await update_log_status(session, log_id=uuid.UUID(log_id),
                                        status="sent",
                                        sent_at=datetime.now(timezone.utc),
                                        provider_key=result.provider_key)
                return {"success": True, "message_id": result.message_id,
                        "provider": result.provider_key}
            return {"success": False, "error": result.error or "Unknown email send error"}
```

This single change fixes **all 17 Group B sites at once** without touching any of them.

**Important note:** `send_email_task` is a **plain async function** (not a Celery task). It was previously a Celery task but the decorator was removed. The `RETRY_DELAYS` and `MAX_RETRIES` constants exist in the module but the retry logic is dead code — on failure, the function immediately calls `_mark_permanently_failed()`. The provider failover in the unified sender replaces the need for application-level retries.

### 4.5 Failure surfacing

Today, Groups A1–A6 call `create_in_app_notification(category="email_failure", ...)` after total failure. Groups A7–A13 (auth + landing page) deliberately do not (no org context — documented as a v1 limitation).

> **Import-path note:** `create_in_app_notification` lives in `app.modules.in_app_notifications.service` (a separate module from `app.modules.notifications`). Grepping the `notifications/` module will not find it — see [in_app_notifications/service.py:90](app/modules/in_app_notifications/service.py#L90).

The unified sender will:
- Not call `create_in_app_notification` itself (avoids tight coupling).
- Return `SendResult` with `attempts` populated so callers decide whether to raise an in-app notification.
- Callers that previously called `create_in_app_notification` keep doing so based on `result.success == False`.

This preserves the existing UX for invoice/quote/payments/booking/vehicle-report failure notifications.

---

## 5. Execution Phases

Each phase is independently shippable. The order minimises risk: build the new helper first, prove it on isolated sites, then sweep.

### Phase 0 — Preparation (no behavior changes)

- [ ] Add a sender_strategy enum / docstring example to `app/integrations/email_sender.py` (empty module + types only).
- [ ] Move `EmailMessage`, `EmailAttachment`, `SendResult` to `email_sender.py`. In `brevo.py`, re-export them.
- [ ] Add `app/integrations/email_sender.py::send_email` skeleton that delegates to a private `_dispatch_for_provider(provider, message, ...)`.
- [ ] **Tests:** unit tests for credential dispatch matrix (mock provider rows, assert which transport gets picked).

**Gate:** all existing tests still pass.

### Phase 0.5 — SECURITY HOTFIX: password-reset email (cherry-pick ahead of Phase 1)

Today, [`_send_password_reset_email`](app/modules/auth/service.py#L1892) only logs; the "Forgot password?" flow silently fails to send. This is a standalone account-recovery bug and should ship **before** the rest of the unification work.

- [ ] Implement `_send_password_reset_email` using the **existing** raw-`smtplib` + EmailProvider loop pattern (copy from `_send_invitation_email`) so it ships independently of Phase 1's unified sender. It will be rewritten to call `send_email()` in Phase 4, but until then the user-facing flow works.
- [ ] Add `tests/test_password_reset_email.py` asserting the email is at least attempted.
- [ ] Bump PATCH version and ship as a standalone hotfix release.

**Gate:** forgot-password flow delivers an email in a manual test.

### Phase 1 — Implement send_email with full feature parity

- [ ] Implement `_dispatch_brevo_rest` (copy from `email_providers/service.py::_send_test_via_rest_api`, extend for attachments — Brevo REST supports `attachment` array, see `brevo.py:163-171`).
  - **Note:** Brevo REST API supports multiple attachments (base64-encoded, up to 10 MB each). Verify non-PDF MIME types (images, CSVs) are handled correctly. The invoice email flow attaches arbitrary uploaded files.
- [ ] Implement `_dispatch_sendgrid_rest` (copy and extend for attachments — see `brevo.py:219-229`).
- [ ] Implement `_dispatch_smtp` (covers Brevo-with-smtp_login, Mailgun, SES, Gmail, Outlook, custom_smtp). Honour `smtp_encryption` ∈ {none, tls, ssl}. Honour `smtp_login`-then-`api_key` override.
  - **Note:** All current Group A sites use synchronous `smtplib` inside async functions, blocking the event loop. The unified sender should wrap SMTP calls in `asyncio.to_thread()` to avoid blocking. This is a performance improvement over the current state.
- [ ] Build MIME message helper (multipart/mixed for attachments, multipart/alternative for HTML+text only).
- [ ] Implement provider loop with `EmailAttempt` accumulation.
- [ ] Implement `org_sender_name` / `org_reply_to` overrides.
- [ ] Honour the **default-host fallback table** currently in `email_providers/service.py:246-260` (`default_hosts = {...}`) for rows that have no `smtp_host` set.
- [ ] Add `EMAIL_SIZE_LIMIT = 25 * 1024 * 1024` as a module-level constant (currently local to `email_invoice`). The unified sender should expose this for callers that need to pre-check attachment sizes.
- [ ] **Tests:**
  - Mock httpx for REST API success/auth-fail/network-error.
  - Mock smtplib for SMTP success/auth-fail/connect-fail.
  - 3-provider chain: 1st fails connection → 2nd fails auth → 3rd succeeds. Assert `result.attempts` has 3 entries and `provider_key == third.provider_key`.
  - No active providers → returns success=False, attempts=[], error="No active email providers configured".
  - org overrides take precedence over `config.from_name`/`config.reply_to`.
  - Attachment test: multiple attachments with mixed MIME types (PDF + image) via both REST and SMTP paths.

**Gate:** new unit tests pass; old `test_email_infrastructure.py` still passes (still hitting `send_org_email` shim).

### Phase 2 — Rewire `send_email_task`

- [ ] Rewrite `app/tasks/notifications.py::_send_email_async` to call `send_email` (Section 4.4 code).
- [ ] Keep `send_org_email` and `get_email_client` in `brevo.py` as **deprecated** shims that internally call `send_email` (so test_email_infrastructure.py still works).
- [ ] **The `send_org_email` shim must translate the new `SendResult` shape** (which has `provider_key`, `transport`, `attempts`) back to the old shape (which has `provider: str`). Map `result.provider_key → result.provider` for backwards compatibility. Tests that assert on `result.provider` must keep passing.
- [ ] **Note on retry logic:** `send_email_task` currently defines `RETRY_DELAYS = (60, 300, 900)` and `MAX_RETRIES = 3` but the retry logic is **dead code** — on failure, it immediately calls `_mark_permanently_failed()`. The unified sender's provider failover replaces the need for retries (transient failures are handled by trying the next provider). Leave the retry constants in place for now; remove in Phase 9 cleanup.
- [ ] **Tests:** rerun `test_transfer_notifications.py`, `test_send_portal_link.py`, `test_portal_dsar.py`, `test_portal_quote_acceptance_notification.py`, `test_portal_recover.py`, `test_notification_retry_property.py` — all patch `app.tasks.notifications.send_email_task` so they keep working unchanged.

**Gate:** all 17 Group B sites now go through `email_providers` failover. Manual smoke test: send portal link with 2 providers active.

### Phase 3 — Migrate Group A sites (raw smtplib → send_email)

For each of A1–A14, **one PR per site** so a regression is easy to bisect. Line numbers below are HEAD as of 2026-05-25; prefer grepping the function name when reviewing.

#### A1 — `email_invoice` ([invoices/service.py:4046](app/modules/invoices/service.py#L4046))
- Replace the provider query (~L4146), MIME builder, and provider loop (~L4322 SMTP fallback) with one `send_email` call. Build `EmailAttachment` list from the existing `attachment_data` tuples. Preserve `attachments_skipped_size` body suffix.
- Keep the existing `log_email_sent` + `create_in_app_notification` failure path.

#### A2 — `send_payment_reminder` ([invoices/service.py:4441](app/modules/invoices/service.py#L4441))
- Same as A1, smaller. Reuses parts of `email_invoice`. `import smtplib` at ~L4481, provider query at ~L4489.

#### A3 — Quote send ([quotes/service.py:989](app/modules/quotes/service.py#L989))
- Same pattern as A1. `import smtplib` at L991, provider query at L1083.

#### A4 — `_send_receipt_email` ([payments/service.py:497](app/modules/payments/service.py#L497))
- Post-payment receipt with PDF attachment generated by `generate_invoice_pdf`. Convert to `EmailAttachment`. `import smtplib` at L526, provider query at L599, SMTP at L687.

#### A5 — Vehicle report ([vehicles/report_service.py:293](app/modules/vehicles/report_service.py#L293))
- Function `email_service_history_report`. HTML body from jinja template, PDF attachment. Provider query at ~L435.

#### A6 — Booking confirmation ([bookings/service.py:1099](app/modules/bookings/service.py#L1099))
- Plain text only, no attachment. `import smtplib` at L1118, provider query at L1135.

#### A7 — Lockout email ([auth/service.py:360](app/modules/auth/service.py#L360))
- Uses its own `async_session_factory()` because called outside the request context. The unified sender should also accept an explicit `db` session, so caller opens one. No-org-context: pass `org_id=None`. Provider query at ~L429.

#### A8 — Invite ([auth/service.py:2523](app/modules/auth/service.py#L2523))
- Has `db` may-be-None path (function can be called either from a request or from a background task). Keep that conditional session-open logic in the caller. Provider query at ~L2516.
- Dev-fallback (`logger.warning("DEV INVITE URL: %s", invite_url)`) when no provider configured → check `result.attempts == []` (i.e., no providers tried).

#### A9 — Verification ([auth/service.py:2825](app/modules/auth/service.py#L2825))
- Same as A8. Provider query at ~L2905.

#### A10 — Receipt ([auth/service.py:3027](app/modules/auth/service.py#L3027))
- Same as A8. Provider query at ~L3177.

#### A11 — **MFA OTP** ([auth/mfa_service.py:370](app/modules/auth/mfa_service.py#L370))
- **Currently uses `.limit(1)` at L397 — no failover.** This is a real bug. Migration also fixes it.
- Must keep raising `RuntimeError` (the MFA challenge API contract expects an exception on send-failure). Wrap `send_email` result: if `not result.success`, raise.

#### A12 — **Customer notify** ([customers/service.py:652](app/modules/customers/service.py#L652))
- Function `notify_customer()`. `import smtplib` at L698, provider query at L708.
- Ad-hoc customer messages sent via the email channel.
- Uses `org_name` as `from_name` override — must pass `org_sender_name=org_name` to `send_email`.
- Calls `log_email_sent` after success — preserve this call.

#### A13 — **Landing page demo request** ([landing/router.py:57](app/modules/landing/router.py#L57))
- Function is `submit_demo_request` (NOT `post_demo_request`). `import smtplib` at L15 (module-level), provider query at L97, SMTP at L161.
- Public form — **no org context** (`org_id=None`). Sends to a hardcoded `DEMO_REQUEST_RECIPIENT`.
- No `log_email_sent` call (no notification_log entry for public form submissions).
- On total failure, returns HTTP 500 to the user (no in-app notification — no org context).

#### A14 — **Invoice payment-link email** ([payments/service.py:349](app/modules/payments/service.py#L349))
- Function `send_invoice_payment_link_email`. Added in v1.10.2 "Send Payment Link" feature, after the original plan was drafted.
- Pattern is a near-duplicate of A1's `email_invoice`: `import smtplib` at L526, `select(EmailProvider).where(is_active && credentials_set).order_by(priority)` at L599, MIME build with optional PDF, SMTP loop at L687-689.
- Migrate to `send_email` with `EmailAttachment` for the PDF (when generated). Preserve any `log_email_sent` + audit-log calls.

**IMPORTANT — Phase 3 migration notes for all Group A sites:**
- Each site that calls `log_email_sent` after a successful send **must preserve that call** after checking `result.success`. Forgetting this will create gaps in the `notification_log` table.
- Each site that calls `create_in_app_notification` on failure **must preserve that call** after checking `not result.success`.
- Sites that use `org_name` or other org-specific values as `from_name` must pass them via `org_sender_name` parameter.

**Tests for each:** the per-module email tests enumerated below **do not exist today** and must be CREATED in each site's PR — they are NOT "existing tests to re-run".

| New test file | Covers |
|---|---|
| `tests/test_invoice_email_failover.py` | A1 + A2 (`email_invoice`, `send_payment_reminder`) + A14 (`send_invoice_payment_link_email`) |
| `tests/test_quote_email_failover.py` | A3 |
| `tests/test_payment_receipt_email.py` | A4 (`_send_receipt_email`) |
| `tests/test_vehicle_report_email.py` | A5 |
| `tests/test_booking_confirmation_email.py` | A6 |
| `tests/test_auth_email_failover.py` | A7–A10 (lockout, invite, verification, paid-plan receipt) |
| `tests/test_mfa_email_otp.py` | A11 (also exercises BUG-2 fix) |
| `tests/test_customer_notify_email.py` | A12 |
| `tests/test_landing_demo_request_email.py` | A13 (no org context) |

Each must include a 2-provider failover test: first provider returns auth-fail, second succeeds, assert `result.success` and `result.attempts == 2`.

**Gate:** zero remaining `import smtplib` lines outside `app/integrations/email_sender.py` and `app/modules/email_providers/service.py` (test endpoint — see note below).

**Note on `email_providers/service.py:test_email_provider`:** This function also uses raw `smtplib` for the per-provider test endpoint. It should be refactored to use the shared `_dispatch_smtp` / `_dispatch_brevo_rest` helpers from `email_sender.py` rather than duplicating the logic. This can be done as part of Phase 3 or deferred to Phase 9 cleanup.

> **SMTP-test path is currently inline, not a helper.** Only `_send_test_via_rest_api` exists as a top-level helper (at [email_providers/service.py:314](app/modules/email_providers/service.py#L314)). The SMTP test path is **inline within `test_email_provider`** (between L177-314, after the `default_hosts = {...}` block at L246-260). Phase 1's `_dispatch_smtp` implementation therefore extracts BOTH the inline SMTP logic from `test_email_provider` AND copies the REST helper into the new `email_sender.py` module; Phase 3 then swaps the inline `test_email_provider` block for calls to the shared helpers.

### Phase 4 — Implement Group C TODO stubs

- [ ] **C3 (`_send_password_reset_email`)** — already implemented in **Phase 0.5 hotfix** with raw `smtplib`. In this phase, rewrite to call `send_email()` instead, matching the rest of the unified codebase. No new functionality, just plumbing parity.
- [ ] **C1 / C2** — security alerts ([auth/service.py:861](app/modules/auth/service.py#L861) and [auth/service.py:635](app/modules/auth/service.py#L635)). Similar pattern. Body should include IP/device for anomalous-login alert and have a "Sessions invalidated automatically" notice for token-reuse.

**Gate:** password reset emails route through `send_email` like every other path; security alerts are actually delivered (manual test).

### Phase 5 — Fix the activate endpoint (and safety-net the deactivate endpoint)

- [ ] Edit `app/modules/email_providers/service.py:34-65::activate_email_provider`:
  ```python
  # REMOVE these 2 lines:
  # await db.execute(update(EmailProvider).values(is_active=False))
  # provider.is_active = True (replace with conditional)
  
  if provider.is_active:
      return _provider_to_dict(provider)   # idempotent
  provider.is_active = True
  ```
- [ ] Update the audit log action name + after_value to be clear: `email_provider_activated` (not `set_as_only_active`).
- [ ] **Safety net for deactivate** ([email_providers/service.py:68 `deactivate_email_provider`](app/modules/email_providers/service.py#L68)): with multi-active enabled, an admin could deactivate every provider, leaving zero active. Add a guard: count rows where `is_active=True AND credentials_set=True`. If deactivating this provider would drop the count to zero, raise `HTTPException(409, "Activate another provider before deactivating this one — at least one active email provider is required for outbound mail.")`. Frontend can additionally pre-check and disable the button for the last active provider.
- [ ] **Tests:**
  - `tests/test_email_provider_activate_multi.py` — activate provider A → activate provider B → both active. List endpoint shows both.
  - `tests/test_email_provider_deactivate_last_blocked.py` — single active provider, attempt deactivate, assert HTTP 409 and provider still active.

**Gate:** activating one provider no longer deactivates others. Deactivating the last active provider is rejected with 409.

### Phase 6 — Frontend (UI) updates

#### 6a — Multi-active banner ([EmailProviders.tsx:442](frontend/src/pages/admin/EmailProviders.tsx#L442))
- The banner `<span className="font-semibold">Active Provider:</span>` is at L442 (not L163 as originally drafted — the file was refactored).
- Change `Active Provider: <name>` → `Active Providers: <comma-separated list>` when more than one.
- The API already returns `active_provider` (singular) at `email_providers/service.py:25-31`. **Extend** the response to include `active_providers: list[str]` while keeping `active_provider` (set to the highest-priority active one) for backwards compatibility for one release.

#### 6b — Priority slider visibility ([EmailProviders.tsx:239](frontend/src/pages/admin/EmailProviders.tsx#L239))
- Currently `{provider.is_active && (<priority input>)}` at L239. Show whenever `credentials_set` so users can pre-rank a configured-but-inactive provider.

#### 6c — Failover preview
- Add a small "Send order: 1. Brevo → 2. Gmail → 3. Custom SMTP" preview line above the provider list, derived from the list response.

#### 6d — Setup guides updated
- Update Brevo setup guide in migration 0065 — or better, in a new migration that does `UPDATE email_providers SET setup_guide = '...' WHERE provider_key = 'brevo'` — to document the **two key types** (REST API key vs SMTP key+login). The current text only mentions SMTP key.

#### 6e — Verify integration_cost_dashboard renders correctly with N active providers
- [admin/router.py:1206 `integration_cost_dashboard`](app/modules/admin/router.py#L1206) reads "any active email provider" to surface an "Email: Healthy/Unhealthy" tile. With multi-active enabled (Phase 5), confirm the tile either: (a) shows "Email: Healthy ✓ (N active providers)" or (b) lists the active provider names. If the dashboard hard-codes a singular provider field, update the response shape and the admin frontend tile.
- _No backend change expected_; the existing query already iterates with `is_active=True ORDER BY priority`. A 5-minute visual check is sufficient — fix only if the tile is misleading.

### Phase 7 — Deprecate the legacy admin SMTP page

- [ ] **Pre-step — frontend audit.** Verified 2026-05-25: `Integrations.tsx` currently has 4 tabs (Carjam, Stripe, SMS Providers, Email Providers); there is **no visible "SMTP" card** in the tab list ([Integrations.tsx:754-772](frontend/src/pages/admin/Integrations.tsx#L754)). Before scoping the frontend removal, grep the entire `frontend/src/` tree for any code path that calls `PUT /admin/integrations/smtp` or `POST /admin/integrations/smtp/test`. If zero call sites exist, the frontend step is a no-op — skip it and proceed directly to the backend deprecation below.
- [ ] **Backend deprecation (always required regardless of frontend state).** Replace the bodies of `/api/v1/admin/integrations/smtp` (PUT) and `/api/v1/admin/integrations/smtp/test` (POST) endpoints in `admin/router.py:640, 692` with HTTP 410 Gone responses carrying a `Location` header pointing to `/api/v2/admin/email-providers`.
- [ ] **Telemetry during 410 window.** Add a structured log line (`logger.warning("legacy_smtp_endpoint_hit path=%s remote=%s", path, ip)`) at each 410 response. Tag with a known string so a single `grep legacy_smtp_endpoint_hit` over one release of access logs gives an exact count of remaining callers.
- [ ] Remove `save_smtp_config` and old `send_test_email` from `admin/service.py` — both are unreferenced after the endpoint bodies are replaced. (Confirm via grep before deletion.)

**Risk:** This is destructive. Any user/script still PUTting to the old URL will get 410. Mitigate by keeping the endpoints in place for one release returning HTTP 410 Gone with a `Location` header pointing to `/api/v2/admin/email-providers`. **Phase 9 removal of the 410 endpoints is gated on zero `legacy_smtp_endpoint_hit` log lines across one full release window** — see Phase 9.

### Phase 8 — Migrations

This phase contains two independent migrations. **8a is a schema-only migration that should be applied with Phase 2** so the `update_log_status(..., provider_key=...)` call lands on a real column; 8b is the one-time data migration originally scoped here.

#### 8a — Add `notification_log.provider_key` column

Acceptance Criterion #4 (Section 13) asserts `notification_log.provider_key='<provider 2>'` after a failover. The column does not exist today ([notifications/models.py:79-120](app/modules/notifications/models.py#L79)). Without it, the AC is unverifiable and Phase 2's `update_log_status(..., provider_key=...)` call would TypeError at runtime.

Migration `XXXX_add_notification_log_provider_key.py`:
```python
def upgrade():
    op.add_column(
        "notification_log",
        sa.Column("provider_key", sa.String(50), nullable=True),
    )
    # Optional but useful for forensic queries:
    op.create_index(
        "ix_notification_log_provider_key",
        "notification_log",
        ["provider_key"],
    )

def downgrade():
    op.drop_index("ix_notification_log_provider_key", table_name="notification_log")
    op.drop_column("notification_log", "provider_key")
```

Service-layer signature changes (in the same patch):
- `log_email_sent(db, *, org_id, recipient, template_type, subject, status="queued", channel="email", error_message=None, sent_at=None, **provider_key=None**)` — accept and persist.
- `update_log_status(db, *, log_id, status, error_message=None, sent_at=None, **provider_key=None**)` — accept and persist.

Backwards compat: column is NULL-able and has no default, so existing rows and existing call sites (which won't pass the kwarg) are unaffected.

**Admin-UI surfacing (otherwise the column is invisible to operators):**
- [ ] Update `_log_entry_to_dict` in `app/modules/notifications/service.py` to include `provider_key` in the serialised log entry.
- [ ] Update `list_notification_log` response so the admin UI can read the new field. Add `provider_key: str | None` to the corresponding Pydantic schema.
- [ ] In the admin notification-log frontend table (search for the consumer of `list_notification_log` — likely under `frontend/src/pages/admin/` notification log / activity viewer), add a "Provider" column. When `provider_key is null` (legacy rows before Phase 8a deploy), render `—`.
- [ ] No frontend change required for non-admin users; this column is only visible inside the admin notifications viewer.

#### 8b — Legacy SMTP → email_providers data migration

If a user has only configured the legacy `integration_configs[smtp]` and not yet touched the new `email_providers` rows, we must not lose their config.

Migration `XXXX_migrate_legacy_smtp_to_email_provider.py`:

```python
# Pseudo-code — final form in migration phase
def upgrade():
    # Read integration_configs[smtp] (encrypted blob)
    # Decrypt with envelope_decrypt_str
    # Map provider field → email_providers.provider_key:
    #   'brevo'    → email_providers.provider_key='brevo'   (REST API key path)
    #   'sendgrid' → email_providers.provider_key='sendgrid'
    #   'smtp'     → email_providers.provider_key='custom_smtp'
    # Build credentials dict per provider_key (api_key OR username+password)
    # Re-encrypt into email_providers.credentials_encrypted
    # Set is_active=True, priority=1, credentials_set=True
    # Set smtp_host/port/encryption from the legacy row
    # Set config={from_email, from_name, reply_to}
    # Only run if the email_providers row for that provider_key has credentials_set=False
    #   (don't clobber a fresh setup the admin has already done in the new UI)
```

**Cannot be a pure SQL migration** because it needs to decrypt → re-encrypt with the same KMS DEK. Must be a Python migration script that imports `app.core.encryption`. Test in a copy of prod data before running.

**Operational requirements before running this migration:**

1. **Maintenance window required.** If an admin is mid-flight writing through the legacy `IntegrationConfig.smtp` form at the moment the migration reads the encrypted blob, the migration will silently overwrite the new value from the GUI race. Schedule a 15-min window with the GUI disabled (frontend Phase 7's removal of the SMTP card helps, but the API endpoint is still alive until Phase 7's 410 Gone step).
2. **Verify no recent writes.** Pre-migration check: `SELECT updated_at FROM integration_configs WHERE name='smtp'` — if the row was updated within the last N minutes, abort and reschedule.
3. **`is_verified` carry-over.** The legacy `integration_configs.is_verified` flag indicates the admin successfully tested the SMTP config. The new schema does not have a direct equivalent (see BUG-7 follow-up). Document in the post-migration runbook: "admins should re-run the per-provider test on the new EmailProviders page to confirm credentials carried over correctly."
4. **Acquire `rotate_keys` advisory lock.** `app/cli/rotate_keys.py` re-encrypts both tables sequentially. If it runs mid-migration the state is half-encrypted. Acquire a PG advisory lock on both tables (or document operational constraint: "do not run rotate_keys during the maintenance window").

### Phase 9 — Cleanup (after one release in production)

- [ ] Remove the `send_org_email`/`get_email_client`/`load_smtp_config_from_db`/`SmtpConfig`/`EmailClient` shims from `app/integrations/brevo.py`. File becomes empty stub or merges into `email_sender.py`.
- [ ] **Gate: 410-endpoint removal.** Confirm zero `legacy_smtp_endpoint_hit` log lines over one full release window (telemetry added in Phase 7). Only then remove the 410 Gone endpoints from `admin/router.py`. If callers remain, defer one more release and notify them.
- [ ] Remove the `integration_configs[name='smtp']` row in a follow-up migration (or leave for forensic value — there's no harm in keeping it; storage is negligible).
- [ ] **No change required to `app/cli/rotate_keys.py`.** It iterates all `IntegrationConfig` rows generically; deleting the smtp row simply makes the iteration find one less item. The plan previously called for an update here — verified unnecessary against [rotate_keys.py:36-50](app/cli/rotate_keys.py#L36).

---

## 6. Known Bugs This Migration Fixes (alongside the multi-provider work)

| ID | Bug | Resolved in phase |
|---|---|---|
| BUG-1 | `activate_email_provider` deactivates all others — prevents multi-active. | Phase 5 |
| BUG-2 | MFA email OTP uses `.limit(1)` — silently single-provider. | Phase 3 (A11) |
| BUG-3 | 17 Group B sites have **zero failover**. | Phase 2 |
| BUG-4 | Password reset, anomalous-login, token-reuse alerts never actually email. | Phase 4 |
| BUG-5 | Brevo SMTP key + login + REST API key are confused; setup guide is incomplete. | 2026-05-13 fix (already shipped) + Phase 6d |
| BUG-6 | Hand-rolled SMTP code in 13 sites — every bug fix has to be applied 13× (e.g., the "Brevo `api_key` used as both username and password" bug fixed earlier is **still present** in every Group A site). | Phase 3 (rip out all 13). |
| BUG-7 | `_send_test_email` (legacy) verifies `IntegrationConfig.is_verified` but no email-providers-table equivalent — admin can't tell which providers passed their last test. | Optional follow-up: add `last_test_at`, `last_test_success` columns to `email_providers`. |

---

## 7. Test Plan

### 7.1 Existing tests to keep green

These already exist and exercise the email pipeline. Each phase **must** keep all of these green:

| File | Coverage |
|---|---|
| `tests/test_email_infrastructure.py` | `SmtpConfig`, `EmailClient`, `send_org_email`. Will need updates in Phase 2 to mock the new pipeline. |
| `tests/test_email_delivery_tracking.py` | notification_log statuses. |
| `tests/test_email_templates.py` | template rendering. |
| `tests/test_transfer_notifications.py` | patches `send_email_task` at module path. |
| `tests/test_send_portal_link.py` | patches `send_email_task`. |
| `tests/test_portal_dsar.py` | patches `send_email_task`. |
| `tests/test_portal_quote_acceptance_notification.py` | patches `send_email_task`. |
| `tests/test_portal_recover.py` | patches `send_email_task`. |
| `tests/test_notification_retry_property.py` | imports `send_email_task` directly. |
| `tests/test_landing_page.py:71` | mock EmailProvider. |
| `tests/test_rotate_keys.py` | rotation across both tables. |
| `tests/test_integration_config.py` | masks SMTP fields. |
| `tests/test_security_focused.py:359` | SMTP api_key never returned raw. |

### 7.2 New tests required

| Phase | New test |
|---|---|
| 1 | `tests/test_email_sender_dispatch.py` — matrix of (provider_key, credentials shape) → expected transport. |
| 1 | `tests/test_email_sender_failover.py` — chain of 3 providers, assert per-attempt accounting. |
| 1 | `tests/test_email_sender_attachments.py` — REST and SMTP both attach PDFs correctly. |
| 1 | `tests/test_email_sender_overrides.py` — `org_sender_name` / `org_reply_to` precedence. |
| 2 | `tests/test_send_email_task_integration.py` — end-to-end through `send_email_task` with mock httpx. |
| 3 | Per Group-A site: add a failover-success test (2 providers, first fails, second succeeds). |
| 4 | `tests/test_password_reset_email.py`, `tests/test_anomalous_login_email.py` — that the email is actually attempted (mock send). |
| 5 | `tests/test_email_provider_activate_multi.py` — activate two providers; assert both active. |
| 8 | `tests/test_migration_legacy_smtp_to_email_provider.py` — seed legacy row, run migration, assert email_providers row populated, encrypted, and decryptable. |

### 7.3 Manual / smoke tests before release

1. Configure 3 providers (Brevo REST API, Brevo SMTP, custom SMTP). Activate all 3 at priorities 1, 2, 3.
2. Send invoice email → verify Brevo REST used (check API call in logs).
3. Revoke Brevo REST key → send another → verify failover to Brevo SMTP.
4. Stop Brevo SMTP host (firewall rule) → send another → verify failover to custom SMTP.
5. Trigger each email type: invite, verification, paid-plan receipt, MFA OTP, portal link, quote accepted, invoice send, payment receipt, vehicle report, booking confirmation, password reset, subscription invoice, dunning, suspension warning, lockout alert. All deliver.
6. Deactivate all providers → trigger an email → confirm UI shows "Failed to email" in-app notification (for Group A sites) or in notification_log status=failed (for Group B sites).
7. UI smoke: priority numbers persist; multi-active banner displays correctly; setup guide for Brevo mentions both key types.

---

## 8. Rollback Strategy

Each phase has a clean rollback because we kept the legacy path operational until Phase 7:

| Phase | If we need to roll back |
|---|---|
| 0–1 | Just don't merge — no production code changes. |
| 2 | Revert `send_email_task` rewrite. `send_org_email` shim still works. Group A sites unchanged. |
| 3 | Revert site-by-site PR. |
| 4 | Revert. Stubs are reinstated as TODOs. |
| 5 | Re-add the deactivate-all SQL. Single-active behaviour returns. |
| 6 | Revert frontend changes. Banner reverts to singular. |
| 7 | **Hard:** restore the legacy admin endpoints. Possible but ugly. Recommend keeping them as 410 Gone until confidence is high. |
| 8 | Migration has a `downgrade()` that does the inverse (re-encrypts `email_providers` row back into `integration_configs[smtp]`). Test it. |
| 9 | Final cleanup — irreversible without restoring code from git history. |

---

## 9. Risk Register

| Risk | Severity | Mitigation |
|---|---|---|
| Brevo REST API gives different rate limits than SMTP. | Med | The REST API rate limit (300 tx/min for paid plans) is higher than SMTP. Not a downgrade. Document for ops. |
| Migration script decrypt fails on a corrupted row. | Low | Wrap in try/except, log loudly, skip that row, alert the operator. Don't fail the migration. |
| Org admins still using legacy `IntegrationConfig.smtp` form after Phase 6 rolls out but before Phase 7. | Low | The form is being removed. Keep the API endpoints alive (returning 200) and write through into BOTH tables for one release if we're paranoid. Default: drop UI in 6, drop API in 7. |
| Attachment size limits differ between REST and SMTP. | Low | Brevo REST: 10 MB per attachment, total payload ~50 MB. SMTP: depends on server (typically 25 MB). Existing `EMAIL_SIZE_LIMIT` in `invoices/service.py` already caps total. Reuse that constant in the unified sender. |
| `app/cli/rotate_keys.py` runs mid-migration and reads from a half-migrated state. | Med | Acquire a row-level lock or run rotate-keys offline. Document operational constraint. |
| Tests that mock `send_org_email` directly break after Phase 9 removes it. | Low | Phase 9 is gated on test-suite update. |
| `_send_email_async` is called inside `async_session_factory().begin()` — the unified sender must accept either an existing session or open its own. | Med | Standardise on caller-provided session (matches Phase 3 callers). For Phase 2, the task opens the session and passes it in — no behaviour change. |
| Synchronous `smtplib` blocks the async event loop during SMTP send (2–15s per email). | Med | Wrap all `smtplib` calls in `asyncio.to_thread()` in the unified sender. This is a performance improvement over the current state. Not a correctness issue at current traffic levels but will cause request timeouts under load. |
| Phase 3 PRs forget to preserve `log_email_sent` calls after migrating to `send_email`. | Med | Add to PR review checklist: every Group A site that previously called `log_email_sent` must still call it after checking `result.success`. Automated check: grep for `log_email_sent` in the diff to ensure it's not removed. |
| `SendResult` shape change breaks tests that assert on `result.provider`. | Low | The new dataclass exposes a `provider` read-only `@property` that returns `provider_key` (see Section 4.1). Existing tests (`test_security_focused.py:359`, `test_email_infrastructure.py`) keep passing without changes until Phase 9 removes the shim. |
| Phase 8 migration overwrites a recent admin-GUI write to `IntegrationConfig.smtp`. | Med | Run during a scheduled maintenance window with the legacy GUI disabled. Pre-migration check `updated_at` on the legacy row and abort if recent. See Phase 8 operational requirements. |
| Phase 4 rewrite of `_send_password_reset_email` from raw smtplib (Phase 0.5) to `send_email` introduces a regression on the only active-account-recovery path. | Med | The Phase 0.5 hotfix already ships a working raw-smtplib version. Phase 4's rewrite must include `test_password_reset_email.py::test_failover_chain` asserting it still delivers with 2-of-3 providers failing. |

---

## 10. Open Questions (must resolve before execution)

1. **Per-org email providers?** Currently `email_providers` is platform-wide (no `org_id` column). If we ever need per-tenant SMTP, schema change is required. Out of scope here, but confirm we don't want it before locking the design.
2. **Bounce processing.** Brevo bounce webhook hits `webhooks/brevo-bounce` and flags `Customer.email_bounced=True`. After this migration, do we wire the webhook secret discovery from `email_providers.config['brevo_webhook_secret']` instead of `app_settings.brevo_webhook_secret` (env)? Default: leave env-based for now; revisit if we add per-org Brevo accounts.
3. **`is_verified` parity.** The legacy `integration_configs.is_verified` flag is flipped to true by the test endpoint. Should `email_providers` get the same? Recommended: add `last_test_at` + `last_test_success` columns (small migration). Counts as BUG-7 fix.
4. **Provider-specific custom logic.** Mailgun has a `domain` concept that the SMTP form ignores. Today it's stored in `integration_configs[smtp].domain` but not in `email_providers`. Confirm Mailgun via SMTP only needs `username+password+host` (it does, the domain is encoded in the username).
5. ~~**What `provider_key` does the migration assign for a legacy "provider=smtp" row?**~~ **RESOLVED:** `custom_smtp`. The `email_providers` table has `provider_key='custom_smtp'` as one of the 7 seeded rows (from migration 0065). Confirmed.

---

## 11. Execution Checklist (printable)

For each phase, tick off:

```
PHASE 0 — Preparation
[ ] email_sender.py module created (empty stub + types)
[ ] EmailMessage, EmailAttachment, SendResult moved out of brevo.py with re-exports
[ ] New SendResult has `provider` @property alias for backwards-compat
[ ] Dispatch matrix docstring written
[ ] Existing test suite green

PHASE 0.5 — SECURITY HOTFIX: password reset email
[ ] _send_password_reset_email implemented with raw smtplib (mirrors _send_invitation_email pattern)
[ ] test_password_reset_email.py asserts the email is attempted
[ ] PATCH version bumped; standalone hotfix release shipped

PHASE 1 — send_email implementation
[ ] _dispatch_brevo_rest with attachment support (multi-attachment, mixed MIME types)
[ ] _dispatch_sendgrid_rest with attachment support
[ ] _dispatch_smtp covering all 6 SMTP providers + encryption modes (wrapped in asyncio.to_thread)
[ ] MIME helper
[ ] Provider loop with EmailAttempt accumulation
[ ] org_sender_name / org_reply_to override
[ ] Default-host fallback table
[ ] EMAIL_SIZE_LIMIT constant exposed at module level
[ ] 6 new unit tests pass (including attachment + mixed MIME type test)
[ ] Existing test suite green

PHASE 2 — send_email_task rewired
[ ] _send_email_async rewritten to call send_email
[ ] send_org_email shim in brevo.py (translates new SendResult shape → old shape)
[ ] All 9 Group-B-mocking tests green
[ ] Manual smoke: portal link sends via failover chain

PHASE 3 — Group A migrations (one PR per site)
[ ] A1 invoice_email
[ ] A2 payment_reminder
[ ] A3 quote_email
[ ] A4 payment_receipt
[ ] A5 vehicle_report
[ ] A6 booking_confirmation
[ ] A7 lockout_email
[ ] A8 invitation_email
[ ] A9 verification_email
[ ] A10 receipt_email
[ ] A11 mfa_email_otp (also fixes BUG-2)
[ ] A12 customer_notify (org_sender_name=org_name override)
[ ] A13 landing_demo_request — function name `submit_demo_request` (NOT `post_demo_request`); org_id=None, no log_email_sent
[ ] A14 send_invoice_payment_link_email (v1.10.2 Send Payment Link feature)
[ ] email_providers/service.py test_email_provider → use shared _dispatch_smtp/_dispatch_brevo_rest
[ ] grep -r "import smtplib" app/ returns only email_sender.py

PHASE 4 — Group C stubs
[ ] C3 password_reset_email — rewrite Phase 0.5 raw-smtplib impl to call send_email()
[ ] C2 anomalous_login_alert
[ ] C1 token_reuse_alert

PHASE 5 — activate endpoint fix + deactivate safety net
[ ] activate_email_provider no longer deactivates others
[ ] deactivate_email_provider returns 409 if it would leave zero active providers
[ ] Multi-active test passes
[ ] Deactivate-last test passes (409 returned, provider still active)

PHASE 6 — Frontend + dashboard
[ ] Banner: multi-active list
[ ] Priority slider always visible when credentials_set
[ ] Failover preview text
[ ] Brevo setup guide updated (two key types)
[ ] integration_cost_dashboard verified to render correctly with N active providers (5-min visual check)

PHASE 7 — Legacy SMTP page deprecation
[ ] Frontend audit complete — confirmed whether Integrations.tsx has an SMTP card to remove (likely no-op)
[ ] /admin/integrations/smtp endpoints return 410 Gone with Location header
[ ] Telemetry log line `legacy_smtp_endpoint_hit` added at each 410 response
[ ] save_smtp_config + old send_test_email removed from admin/service.py (after grep-confirmed unreferenced)

PHASE 8a — Schema migration: notification_log.provider_key
[ ] Migration XXXX_add_notification_log_provider_key.py written + downgrade
[ ] log_email_sent + update_log_status signatures extended to accept provider_key
[ ] _log_entry_to_dict includes provider_key
[ ] list_notification_log response schema includes provider_key
[ ] Admin notification-log viewer (frontend) shows new "Provider" column
[ ] Applied alongside Phase 2 deploy (so update_log_status(provider_key=…) lands on a real column)

PHASE 8b — Legacy SMTP → email_providers data migration
[ ] Migration script written + downgrade
[ ] Tested in copy-of-prod
[ ] Maintenance window scheduled; legacy GUI disabled
[ ] Pre-migration updated_at check passes (no recent writes to integration_configs[smtp])
[ ] No rotate_keys job running during the window
[ ] Run in staging
[ ] Run in production
[ ] Post-migration: admins notified to re-test each provider (is_verified carry-over runbook step)

PHASE 9 — Cleanup (next release)
[ ] Remove brevo.py shims
[ ] Confirm zero `legacy_smtp_endpoint_hit` log lines over one release window
[ ] Remove 410 Gone endpoints from admin/router.py
[ ] Optionally: drop integration_configs[smtp] row
[ ] rotate_keys.py needs NO change (verified — iterates generically)
[ ] Remove dead retry code (RETRY_DELAYS, MAX_RETRIES, _get_retry_delay) from notifications.py
```

---

## 12. Files That Will Change (precise inventory)

### New files
- `app/integrations/email_sender.py` (Phase 0/1)
- `tests/test_email_sender_dispatch.py`, `test_email_sender_failover.py`, `test_email_sender_attachments.py`, `test_email_sender_overrides.py`, `test_send_email_task_integration.py`, `test_email_provider_activate_multi.py`, `test_password_reset_email.py`, `test_anomalous_login_email.py`, `test_migration_legacy_smtp_to_email_provider.py` (Phases 1–5, 8)
- **Phase 3 per-site test files (none of these exist today)**: `test_invoice_email_failover.py`, `test_quote_email_failover.py`, `test_payment_receipt_email.py`, `test_vehicle_report_email.py`, `test_booking_confirmation_email.py`, `test_auth_email_failover.py`, `test_mfa_email_otp.py`, `test_customer_notify_email.py`, `test_landing_demo_request_email.py`
- `alembic/versions/XXXX_add_notification_log_provider_key.py` (Phase 8a — schema)
- `alembic/versions/XXXX_migrate_legacy_smtp_to_email_provider.py` (Phase 8b — data)
- `alembic/versions/XXXX_update_brevo_setup_guide.py` (Phase 6d, optional — could be done in-app)
- `alembic/versions/XXXX_add_email_provider_test_columns.py` (BUG-7, optional)

### Modified — backend
| File | Phase | What |
|---|---|---|
| `app/integrations/brevo.py` | 0, 2, 9 | Move types out; turn into shim; eventually delete |
| `app/tasks/notifications.py` | 2 | `_send_email_async` rewrite |
| `app/modules/notifications/models.py` | 8a | Add `provider_key: Mapped[str \| None]` column to `NotificationLog` |
| `app/modules/invoices/service.py` | 3 (A1, A2) | Remove smtplib loops, call send_email |
| `app/modules/quotes/service.py` | 3 (A3) | Same |
| `app/modules/payments/service.py` | 3 (A4) | Same |
| `app/modules/vehicles/report_service.py` | 3 (A5) | Same |
| `app/modules/bookings/service.py` | 3 (A6) | Same |
| `app/modules/auth/service.py` | 3 (A7–A10), 4 (C1–C3) | Same + implement stubs |
| `app/modules/auth/mfa_service.py` | 3 (A11) | Same, also removes `.limit(1)` |
| `app/modules/customers/service.py` | 3 (A12) | Remove smtplib loop in `notify_customer()`, call send_email with `org_sender_name=org_name` |
| `app/modules/landing/router.py` | 3 (A13) | Remove smtplib loop in `post_demo_request()`, call send_email with `org_id=None` |
| `app/modules/email_providers/service.py` | 3, 5 | Refactor `test_email_provider` to use shared dispatch helpers; activate fix |
| `app/modules/admin/router.py` | 7 | 410 Gone old endpoints |
| `app/modules/admin/service.py` | 7 | Delete `save_smtp_config`, old `send_test_email` |
| `app/modules/email_providers/service.py` | 5, 6a | `activate_email_provider` no-deactivate-others fix; `deactivate_email_provider` last-active 409 guard; `list_email_providers` returns `active_providers: list[str]` in addition to existing `active_provider` |
| `app/modules/email_providers/router.py` | 6a | Surface `active_providers` in API response |
| `app/modules/email_providers/schemas.py` | 6a | Add `active_providers: list[str]` field to list response schema |
| `app/modules/notifications/service.py` | 8a | Extend `log_email_sent` + `update_log_status` signatures with `provider_key`; include in `_log_entry_to_dict`; extend `list_notification_log` response |
| `app/modules/notifications/schemas.py` | 8a | Add `provider_key: str \| None` to the log-entry schema |

### Modified — frontend
| File | Phase | What |
|---|---|---|
| `frontend/src/pages/admin/EmailProviders.tsx` | 6a, 6b, 6c | Banner, priority slider, failover preview |
| `frontend/src/pages/admin/Integrations.tsx` | 7 | Remove SMTP card |

### Migrations (read-only inventory of existing)
- `alembic/versions/2025_01_15_0065-0065_create_email_providers.py` — seed table, unchanged.
- `alembic/versions/2026_03_09_1100-0074_add_email_provider_encryption_priority.py` — adds priority + smtp_encryption, unchanged.

---

## 13. Acceptance Criteria (definition of done for the whole project)

1. Every outbound email in the codebase routes through `app/integrations/email_sender.py::send_email`.
2. `grep -rn "import smtplib" app/` returns only the unified sender module.
3. `email_providers` table is the only configuration source. `integration_configs[smtp]` is no longer read at runtime.
4. With 3 active providers configured (priorities 1, 2, 3), if provider 1 returns auth failure, the email is delivered via provider 2 and `notification_log.status='sent'`, `notification_log.provider_key='<provider 2>'`.
5. Activating a 4th provider in the UI does not deactivate the existing 3.
6. Setup guide for Brevo explicitly documents REST-API-key vs SMTP-key+login.
7. Password reset, anomalous-login, and token-reuse alert emails are actually sent (not just logged).
8. MFA OTP supports failover to a 2nd provider.
9. The legacy admin `/admin/integrations/smtp` page is gone from the frontend.
10. All existing tests pass; new failover/dispatch tests pass; manual smoke tests in Section 7.3 all green.
