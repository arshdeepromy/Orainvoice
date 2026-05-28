# Bugfix Requirements Document

## Introduction

After the email-provider-unification spec was completed and deployed to local dev, three related defects surfaced when org admins exercised the email surface end-to-end:

1. The invoice email was actually accepted by Brevo (audit log proves `invoice.email_sent` with `provider: brevo`), but the org user never received a notification, never saw a Delivery Log row, and could not confirm whether Brevo subsequently delivered or bounced the email — because the success path of `email_invoice` writes only to `audit_log` (admin-internal), never to `notification_log`.
2. Brevo IS POSTing webhook events to `/api/v1/notifications/webhooks/brevo-bounce` (verified in app logs), but every event is rejected with **403 Forbidden** and the warning `Brevo bounce webhook: no signing secret configured (neither email_providers.config nor app_settings) — rejecting`. The reason is that `email_providers.config` for the Brevo row holds only `from_name` and `from_email`; there is no key `brevo_webhook_secret`, no admin UI input to set it, and no admin endpoint to store it. The request body of `EmailProviderCredentialsRequest` does not accept a webhook secret either.
3. When an org admin uses **Settings → Users → Invite User**, the recipient receives an invitation email whose `Accept Invitation` link points at `http://localhost:5173/verify-email?token=…` regardless of which domain the admin actually accessed the app on (e.g. `https://devin.oraflows.co.nz`). Verified by trace: `POST /api/v1/org/users/invite` → `invite_org_user` → `create_invitation` → `_send_invitation_email`, none of which read the request `Origin` header; the invitation URL is built from `settings.frontend_base_url` which defaults to `http://localhost:5173` in `app/config.py` L40 and is unset in `.env.pi`. The same defect applies to several other email-link-bearing flows (Org Admin invite from Global Admin, password reset, customer portal link, security alerts) — but the fleet portal invite, signup verification, and invoice email flows already implement the correct pattern by reading `request.headers.get("origin")` and passing it through as `base_url`. The fix copies that established pattern to the broken sites.

All three gaps point at the same observable symptom — the org user has no usable end-to-end email surface — and all three are real bugs (not feature gaps): the spec's Phase 8c work explicitly registered the bounce endpoints as public paths and built the bounce-correlation pipeline expecting webhook events to land successfully, and several call sites in the codebase (auth signup, fleet invite, invoice email) already use the request-origin pattern that this spec extends to the rest of the email-link sites.

## Bug Analysis

### Current Behavior (Defect)

**Bug 1 — Success-path notification_log gap in Group A migrated email sites.**

1.1 WHEN `email_invoice` (`app/modules/invoices/service.py::email_invoice`, ~L4294) calls `await send_email(db, _message)` AND `result.success` is true, THEN the function writes only to `audit_log` (action `invoice.email_sent`) and returns — there is no `await log_email_sent(...)` call on the success path.

1.2 WHEN `send_payment_reminder` (`app/modules/invoices/service.py::send_payment_reminder`, ~L4717) calls `await send_email(db, _message)` AND `result.success` is true, THEN the function DOES call `log_email_sent` on success at L4848 (this site is correct — used as the parity reference).

1.3 WHEN any of the following Group A sites complete a send successfully through `send_email`, THEN no `notification_log` row is written for the success: `quotes/service.py::send_quote_email` (~L1112), `vehicles/report_service.py::email_vehicle_report` (~L455), `payments/service.py::send_payment_receipt_email` (~L711), `bookings/service.py::send_booking_confirmation_email` (~L1272), `customers/service.py::notify_customer` (~L762).

1.4 WHEN the org admin opens **Notifications → Delivery Log** (`/notifications`) AND filters by `template_type='invoice_send'` or `'quote_send'` etc, THEN the list is empty — verified live: `SELECT COUNT(*) FROM notification_log WHERE template_type='invoice_email'` returns 0 across all production data, even though `audit_log` has many `invoice.email_sent` rows.

1.5 WHEN an invoice email is later marked `delivered` or `bounced` by a provider webhook (Phase 8c bounce-correlation pipeline), THEN there is no `notification_log` row whose `provider_message_id` could match the webhook payload — so even after Bug 2 is fixed, delivery/bounce events for invoice emails would have nothing to correlate against (the webhook update is `UPDATE notification_log SET status=..., bounced_at=..., bounce_reason=... WHERE provider_message_id = ?`).

**Bug 2 — Brevo webhook signing-secret cannot be stored.**

2.1 WHEN Brevo POSTs an event to `/api/v1/notifications/webhooks/brevo-bounce`, THEN the handler at `app/modules/notifications/router.py::brevo_bounce_webhook` calls `_candidate_provider_secrets(db, provider_kind="brevo", config_key="brevo_webhook_secret", env_fallback=app_settings.brevo_webhook_secret or None)`. WHEN `email_providers.config['brevo_webhook_secret']` is unset for every active Brevo row AND `app_settings.brevo_webhook_secret` is unset, THEN `candidates` is empty, the handler logs `"Brevo bounce webhook: no signing secret configured"` and returns HTTP 403 with body `{"detail": "Webhook signature verification unavailable"}` — the event payload is never parsed, no `bounced_addresses` row is upserted, and no `notification_log` row is updated.

2.2 WHEN the global admin opens **Admin → Email Providers → Brevo**, THEN the credentials form (`frontend/src/pages/admin/EmailProviders.tsx`, `CREDENTIAL_FIELDS.brevo`) shows fields for `api_key`, `smtp_login`, `from_email`, `from_name` only — there is no input for `webhook_secret`.

2.3 WHEN the global admin sends `PUT /api/v2/admin/email-providers/brevo/credentials` with a body containing a `webhook_secret` field, THEN `EmailProviderCredentialsRequest` (`app/modules/email_providers/schemas.py`) silently drops it because the schema does not declare such a field, AND `save_email_credentials` (`app/modules/email_providers/service.py`) does not accept a `webhook_secret` keyword argument and therefore would not persist it to `email_providers.config['brevo_webhook_secret']` even if the schema accepted it.

2.4 WHEN the same defect applies to SendGrid (the SendGrid webhook handler at `app/modules/notifications/router.py::sendgrid_bounce_webhook` reads `config_key="sendgrid_webhook_secret"`), THEN the SendGrid webhook is also unfixable from the GUI — both providers must be addressed by the same schema/service/UI change.

**Bug 3 — Email-link sites build URLs from `settings.frontend_base_url` instead of the request origin.**

2.5 WHEN an org admin POSTs `/api/v1/org/users/invite`, THEN `invite_user` (`app/modules/organisations/router.py` L921) does NOT read `request.headers.get("origin")` and does NOT pass any `base_url` argument through to `invite_org_user` → `create_invitation` (`app/modules/auth/service.py` L2660). `create_invitation` falls back to `settings.frontend_base_url` which is `"http://localhost:5173"` per `app/config.py` L40 (unset in every `.env.*` file). `_send_invitation_email` then builds `invite_url = f"{base_url}/verify-email?token={token}"` (L2967), so the recipient receives `http://localhost:5173/verify-email?token=…` — an unreachable URL from any host except the developer's own machine.

2.6 WHEN a Global Admin provisions a new organisation via `provision_organisation`, THEN `_send_org_admin_invitation_email` (`app/modules/admin/service.py` L353) accepts a `base_url` parameter but the calling chain from `provision_organisation` (~L198) does NOT supply one — it falls through to the same `settings.frontend_base_url` default. The Org Admin invitation email link is therefore also `http://localhost:5173/verify-email?token=…`.

2.7 WHEN a user requests a password reset, THEN `_send_password_reset_email` (`app/modules/auth/service.py` ~L2197) builds `reset_url` from `getattr(settings, 'frontend_base_url', '') or 'http://localhost'` with no request-origin override path even available — the function signature has no `base_url` parameter at all.

2.8 WHEN `_send_token_reuse_alert` and the lockout email fire (`app/modules/auth/service.py` L399, L668-676, L1046), THEN `support_url`, `security_url`, `sessions_url`, and `reset_url` are all built from `settings.frontend_base_url` directly with no request-origin path. Same defect as 2.7.

2.9 WHEN an org admin sends a customer portal link via `POST /api/v1/customers/{id}/send-portal-link`, THEN `send_portal_link_endpoint` (`app/modules/customers/router.py` L963) does NOT extract the request origin and does NOT pass `base_url` to `send_portal_link` (`app/modules/customers/service.py`); the service builds `portal_url = f"{settings.frontend_base_url}/portal/{customer.portal_token}"` (L2285). Customer receives `http://localhost:5173/portal/…`.

2.10 WHEN `notify_customer_endpoint` (`app/modules/customers/router.py` L898) is called, THEN it does NOT pass `base_url`. The service does not currently embed any URL in the body (`notify_customer` builds plain text/HTML from the admin-supplied subject + message), so this site is informational-only — flagged for completeness because the same router handler is the natural future home for any URL-bearing follow-up.

2.11 WHEN the in-app billing portal flow at `app/modules/portal/service.py` builds `portal_base` (L1108) and `portal_url` (L2206), THEN both read `app_settings.frontend_base_url` directly with no request-origin override — affects success/cancel URLs for Stripe Checkout sessions and the customer-portal access link respectively.

2.12 WHEN any of the following sites already do the right thing — `fleet_portal/admin_router.py::send_fleet_portal_invite` L120 (extracts `parsed.scheme://parsed.netloc` from origin), `auth/router.py` L2359 / L2701 / L2862 (signup, paid signup, resend verification), `invoices/router.py` L280 / L770 (invoice auto-email + manual email), `payments/router.py` L784, `banking/router.py` L115, `quotes/router.py` L386 — THEN those sites build the correct URL because they read `request.headers.get("origin")` and pass it through. The fix replicates this established pattern across the defective sites.

### Expected Behavior (Correct)

**Bug 1 — Success-path notification_log writes.**

3.1 WHEN `email_invoice` calls `await send_email(db, _message)` AND `result.success` is true, THEN the function SHALL call `await log_email_sent(db, org_id=org_id, recipient=recipient_email, template_type="invoice_send", subject=_email_subject, status="sent", channel="email", provider_key=result.provider_key, provider_message_id=result.provider_message_id)` BEFORE the audit log write, so that the bounce-correlation pipeline can match Phase 8c webhook events to this row.

3.2 WHEN any Group A site listed in 1.3 (quote_send, vehicle_report_send, payment_receipt, booking_confirmation, customer_notify) completes a send successfully, THEN that site SHALL also call `log_email_sent` with `status="sent"`, the appropriate `template_type`, and `provider_key` + `provider_message_id` from `result`.

3.3 WHEN `result.provider_message_id` is `None` (the unified sender did not set one — e.g. SMTP transports that don't return a Message-ID), THEN the success log row SHALL still be written with `provider_message_id=None`; the bounce-correlation index excludes NULL rows so this is safe.

3.4 WHEN the org admin opens **Notifications → Delivery Log** after a successful invoice email, THEN they SHALL see one row per send with: recipient email, channel `email`, template `invoice_send`, subject, **provider** (`brevo` / `sendgrid` / `custom_smtp`), status `sent`, sent_at timestamp.

3.5 WHEN the unified sender's bounce-correlation webhook later receives a delivered/bounced event for a `provider_message_id` that matches an `invoice_send` row, THEN `flag_bounce` SHALL update that row's `status`, `bounced_at`/`delivered_at`, and `bounce_reason` columns — making the Delivery Log show the post-delivery status without further code changes.

**Bug 2 — Brevo + SendGrid webhook secrets storable from the admin GUI.**

3.6 WHEN the global admin opens **Admin → Email Providers → Brevo** OR **→ SendGrid**, THEN the credentials form SHALL display an additional field `webhook_secret` (label: "Webhook signing secret", placeholder: "Leave blank to keep existing", type: `password`, masked).

3.7 WHEN the global admin submits `PUT /api/v2/admin/email-providers/{provider_key}/credentials` with `webhook_secret` set to a non-empty value, THEN `EmailProviderCredentialsRequest` SHALL accept the field as `webhook_secret: str | None = None`, AND `save_email_credentials` SHALL persist it as `email_providers.config['<provider_key>_webhook_secret']` (i.e. `brevo_webhook_secret` for Brevo, `sendgrid_webhook_secret` for SendGrid) on the same row.

3.8 WHEN `email_providers.config['brevo_webhook_secret']` is set AND Brevo POSTs a signed event to `/api/v1/notifications/webhooks/brevo-bounce`, THEN `_candidate_provider_secrets` SHALL return at least one candidate, the handler SHALL successfully verify the signature via `verify_webhook_signature`, and the event SHALL be processed (status code 200, `bounced_addresses` upserted on bounce events, `notification_log.delivered_at` set on delivered events).

3.9 WHEN `EmailProviderResponse` is returned by `GET /api/v2/admin/email-providers`, THEN `config['brevo_webhook_secret']` and `config['sendgrid_webhook_secret']` SHALL be redacted from the response payload (replaced with the sentinel string `"***"` when set, omitted when unset) — the secret SHALL NOT be returned to the frontend after it is stored.

3.10 WHEN the admin opens **Email Providers** for a Brevo provider that has the secret set, THEN the form SHALL show an indicator that the secret is configured (e.g. placeholder "Already set — leave blank to keep") and the input SHALL be optional on subsequent saves; submitting an empty `webhook_secret` SHALL leave the existing config value untouched (consistent with how empty `api_key` is currently handled in `handleSaveCredentials` at L388 — `Object.entries(data).filter(([, v]) => v.trim())`).

3.11 WHEN the admin GUI displays the public webhook URL for the configured provider, THEN it SHALL show the absolute URL the admin should paste into the Brevo / SendGrid dashboard (e.g. `https://<host>/api/v1/notifications/webhooks/brevo-bounce`) so the admin can configure the webhook on the provider side without consulting docs.

**Bug 3 — Email links built from request origin with safe fallback.**

3.12 WHEN any of the email-link-bearing endpoints listed below receive a request, THEN the route handler SHALL extract the request origin via `request.headers.get("origin")` (preferred — set by the browser on cross-origin requests) OR derive it from `request.url.scheme` + `request.headers.get("host")` when `Origin` is absent (server-to-server callers, redirected forms), and pass that string as `base_url=` to the underlying service function. Affected endpoints:
   - `POST /api/v1/org/users/invite` (`organisations/router.py::invite_user`) → `invite_org_user(..., base_url=...)` → `create_invitation(..., base_url=...)`
   - `POST /api/v1/admin/organisations` (`admin/router.py::provision_organisation_endpoint`) → `provision_organisation(..., base_url=...)` → `_send_org_admin_invitation_email(..., base_url=...)`
   - `POST /api/v1/auth/forgot-password` and any other password-reset trigger → `_send_password_reset_email(..., base_url=...)` (signature must be extended to accept `base_url`)
   - The internal callers of `_send_lockout_email`, `_send_token_reuse_alert`, and any "session activity" alert (`auth/service.py` L399, L668-676, L1046) → these helpers SHALL accept an optional `base_url` argument; their own callers (which run inside request scope) SHALL pass the request origin. When the helper is invoked from a non-request context (e.g. a background task), `base_url=None` is allowed and the helper falls back to `settings.frontend_base_url`.
   - `POST /api/v1/customers/{id}/send-portal-link` (`customers/router.py::send_portal_link_endpoint`) → `send_portal_link(..., base_url=...)`
   - Any portal email construction site in `app/modules/portal/service.py` that currently reads `app_settings.frontend_base_url` SHALL accept a `base_url` parameter from its caller and use it preferentially.

3.13 WHEN any of those service functions receive a non-empty `base_url` argument, THEN they SHALL use it (after `.rstrip("/")`) to build any absolute URL embedded in the email body or attachment.

3.14 WHEN `base_url` is empty / None / whitespace-only, THEN the service function SHALL fall back to `settings.frontend_base_url` exactly as today — preserving the developer-machine workflow when there is no real request origin (e.g. CLI scripts, background sweeps).

3.15 WHEN the recipient receives an invitation, password reset, portal link, or security alert email AND the org admin accessed the app at `https://devin.oraflows.co.nz`, THEN the link in the email body SHALL begin with `https://devin.oraflows.co.nz` (not `http://localhost:5173`).

3.16 WHEN a request arrives without an `Origin` header (curl, server-to-server, proxied redirect chain), THEN the router handler SHALL fall back to constructing the base URL from `request.url.scheme + "://" + request.headers.get("host", "")` if `host` is set, else fall back to `settings.frontend_base_url`. This matches the pattern used by `auth/router.py::resend_verification_email_endpoint` L2701 (`origin = request.headers.get("origin") or ""` followed by `base_url = origin or settings.frontend_base_url`).

### Unchanged Behavior (Regression Prevention)

4.1 WHEN any Group A site sends an email AND `result.success` is false, THEN the existing failure-path code SHALL CONTINUE TO call `log_email_sent(status="failed", error_message=...)` and `create_in_app_notification(category="email_failure", ...)` exactly as before — the success-path additions SHALL NOT alter the failure path.

4.2 WHEN `send_payment_reminder` (which already calls `log_email_sent` on success per L4848) is invoked, THEN the bugfix SHALL NOT introduce a duplicate `log_email_sent` call — only sites listed in 1.3 are modified.

4.3 WHEN the demo-request site (`landing/router.py`) sends an email, THEN it SHALL CONTINUE NOT to call `log_email_sent` because it has no `org_id` — `notification_log` is org-scoped and the legacy A13 migration explicitly preserved this behaviour.

4.4 WHEN the auth lockout-email site (`auth/service.py::_send_lockout_email`) sends an email, THEN it SHALL CONTINUE NOT to call `log_email_sent` because the auth flow has no `org_id` — same explicit gap as A13, preserved by A7.

4.5 WHEN any other auth-path send (`_send_password_reset_email`, `_send_token_reuse_alert`, `_send_org_admin_invitation_email`, `_send_email_otp`) currently writes a `log_email_sent` row, THEN that behaviour SHALL CONTINUE unchanged — the fix only adds rows where the success path was previously silent.

4.6 WHEN the global admin saves credentials via `PUT /api/v2/admin/email-providers/{provider_key}/credentials` WITHOUT including a `webhook_secret` field, THEN existing credentials AND existing `config['<provider_key>_webhook_secret']` SHALL CONTINUE TO be preserved unchanged (no clobber on partial save).

4.7 WHEN `_candidate_provider_secrets` is called for a provider whose webhook secret is unset, THEN the env-var fallback path (`app_settings.brevo_webhook_secret` / `app_settings.sendgrid_webhook_secret`) SHALL CONTINUE TO work as the legacy one-release fallback — the fix adds a GUI surface but does not break the env-var fallback.

4.8 WHEN the bounce webhook handlers are reachable without JWT (the four PUBLIC_PATHS entries added in commit `ffc8dd6`: `/api/v1/notifications/webhooks/brevo-bounce`, `/api/v1/notifications/webhooks/sendgrid-bounce`, `/api/v2/notifications/webhooks/brevo-bounce`, `/api/v2/notifications/webhooks/sendgrid-bounce`), THEN this remains unchanged — the fix is at the signing-secret-storage layer only.

4.9 WHEN `EmailProviderResponse` returns the `config` dict, THEN `from_email`, `from_name`, `reply_to` SHALL CONTINUE TO be returned in the clear (only the new `*_webhook_secret` keys are redacted).

4.10 WHEN a non-Brevo non-SendGrid provider (e.g. `custom_smtp`) is saved with a `webhook_secret` field, THEN the field SHALL be ignored (custom SMTP has no webhook concept) — the redaction logic only redacts `brevo_webhook_secret` / `sendgrid_webhook_secret` and the form only shows the field for the two providers that support webhooks.

4.11 WHEN any of the email-link sites that already use the request-origin pattern correctly fire (signup verification, fleet portal invite, invoice auto-email, manual invoice email, quote send, payment-page link, banking redirect), THEN their behaviour SHALL be unchanged — those sites already work and the fix is additive only on the sites listed in 3.12.

4.12 WHEN the underlying service function (`create_invitation`, `_send_invitation_email`, `_send_password_reset_email`, etc.) is called WITHOUT a `base_url` argument from any path, THEN the existing `getattr(settings, "frontend_base_url", "") or "http://localhost"` fallback SHALL CONTINUE TO be the safe default — no callers are forced to migrate, and the new request-origin path is opt-in per call site.

4.13 WHEN the fix is applied, the absolute URL constructed for inclusion in the email body SHALL NOT contain a trailing slash before the path component (i.e. `https://example.com/verify-email` not `https://example.com//verify-email`) — preserved by the existing `.rstrip("/")` pattern visible in every reference site.

4.14 WHEN the request `Origin` header contains a value that does not match an allow-list of expected hosts (in case of header forgery from an attacker), THEN the system SHALL CONTINUE TO trust it for URL construction in this fix — the same trust posture as today's correctly-implemented sites (`fleet_portal/admin_router.py` L120, `payments/router.py` L784) and as the QR-payment / Stripe-Connect flows that have shipped against this assumption since v1.10.x. Header-source validation (Origin ↔ Host check, allow-list enforcement) is OUT OF SCOPE for this bugfix — flagged here so reviewers don't assume the fix introduced the trust.

---

## Bug Condition Derivation

### Bug 1: Success-path notification_log gap

**Root Cause (verified by reading code):**

`email_invoice` at `app/modules/invoices/service.py` L4598-4600 calls `result = await send_email(db, _message)`. The next ~20 lines (L4602-4636) handle ONLY `if not result.success`. After `raise ValueError(error_msg)` in the failure branch, control falls through to L4637+ which writes `audit_log` and returns. Verified by `git show 7b33e9f^:app/modules/invoices/service.py` — the pre-migration code had the same gap (no `log_email_sent` on success), so this is a long-standing defect, not a Phase 3 regression. The same pattern applies to A3-A5 and A12-A14 (per the readMultipleFiles of the relevant files in this session).

`send_payment_reminder` at L4848 IS the parity reference — its success branch DOES call `await log_email_sent(db, org_id=org_id, recipient=customer.email, template_type="payment_reminder", subject=subject, status="sent", channel="email")`. The fix copies this exact pattern to the gap sites, plus adds `provider_key=result.provider_key, provider_message_id=result.provider_message_id` (kwargs already supported by `log_email_sent` per Phase 2.3 and Phase 8a, verified by the `log_email_sent` signature in `app/modules/notifications/service.py`).

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type EmailSendCallSite
  OUTPUT: boolean

  RETURN X.module IN {invoices/service.email_invoice,
                       quotes/service.send_quote_email,
                       vehicles/report_service.email_vehicle_report,
                       payments/service.send_payment_receipt_email,
                       bookings/service.send_booking_confirmation_email,
                       customers/service.notify_customer}
    AND X.calls send_email(...)
    AND X.result.success = true
    AND X.org_id IS NOT NULL
END FUNCTION
```

```pascal
// Property: Fix Checking — Success row written
FOR ALL X WHERE isBugCondition(X) DO
  result_after ← Execute X with fix applied
  ASSERT row exists in notification_log WHERE
    org_id = X.org_id
    AND recipient = X.recipient_email
    AND template_type = X.expected_template_type
    AND status = "sent"
    AND provider_key = X.result.provider_key
    AND (provider_message_id = X.result.provider_message_id OR provider_message_id IS NULL)
END FOR
```

```pascal
// Property: Preservation Checking — Failure path unchanged
FOR ALL X WHERE X.calls send_email(...) AND X.result.success = false DO
  ASSERT existing log_email_sent(status="failed", ...) call still fires
  ASSERT existing create_in_app_notification(category="email_failure", ...) call still fires
END FOR
```

```pascal
// Property: Preservation Checking — No-org sites still skip log_email_sent
FOR ALL X WHERE X.org_id IS NULL DO
  // landing demo request, auth lockout, password reset alert paths
  ASSERT no new log_email_sent call is added by the fix
END FOR
```

### Bug 2: Brevo/SendGrid webhook secret storage

**Root Cause (verified by reading code):**

`app/modules/notifications/router.py::brevo_bounce_webhook` L965-994:

```python
candidates = await _candidate_provider_secrets(
    db,
    provider_kind="brevo",
    config_key="brevo_webhook_secret",
    env_fallback=app_settings.brevo_webhook_secret or None,
)
if not candidates:
    logger.warning("Brevo bounce webhook: no signing secret configured ...")
    return JSONResponse(status_code=403, content={"detail": "Webhook signature verification unavailable"})
```

Verified live: `email_providers.config` for `provider_key='brevo'` is `{"from_name": "Orainvoice", "from_email": "no-reply@oraflows.co.nz"}` — no `brevo_webhook_secret` key. `app_settings.brevo_webhook_secret` is also unset (env var not configured). So every webhook hit returns 403 before the body is parsed.

`save_email_credentials` (`app/modules/email_providers/service.py` L196-231) accepts `from_email`, `from_name`, `reply_to` but no webhook secret. `EmailProviderCredentialsRequest` (`app/modules/email_providers/schemas.py` L51-58) has the same fields. `CREDENTIAL_FIELDS.brevo` (`frontend/src/pages/admin/EmailProviders.tsx` L28-34) has only `api_key`, `smtp_login`, `from_email`, `from_name`.

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type WebhookEvent
  OUTPUT: boolean

  RETURN X.method = "POST"
    AND X.path IN {/api/v1/notifications/webhooks/brevo-bounce,
                    /api/v1/notifications/webhooks/sendgrid-bounce,
                    /api/v2/notifications/webhooks/brevo-bounce,
                    /api/v2/notifications/webhooks/sendgrid-bounce}
    AND X.has_valid_signature_header = true
    AND email_providers.config[<provider>_webhook_secret] IS NULL
    AND app_settings.<provider>_webhook_secret IS NULL
END FUNCTION
```

```pascal
// Property: Fix Checking — Webhook accepted after secret stored via GUI
FOR ALL X WHERE
  global_admin previously did
    PUT /api/v2/admin/email-providers/<provider_key>/credentials with body containing webhook_secret = S
  AND X.signature_header = HMAC-compute(X.body, S)
DO
  result_after ← BounceWebhookHandler'(X)
  ASSERT result_after.status_code = 200
  ASSERT bounce/delivered event was applied to notification_log or bounced_addresses
END FOR
```

```pascal
// Property: Preservation Checking — Env fallback still works
FOR ALL X WHERE
  app_settings.<provider>_webhook_secret = S
  AND email_providers.config[<provider>_webhook_secret] IS NULL
  AND X.signature_header = HMAC-compute(X.body, S)
DO
  ASSERT BounceWebhookHandler(X).status_code = 200
END FOR
```

```pascal
// Property: Security — Secret never returned in admin list response
FOR ALL R WHERE R = response of GET /api/v2/admin/email-providers DO
  FOR EACH provider IN R.providers DO
    ASSERT provider.config["brevo_webhook_secret"] IS NULL OR EQUALS "***"
    ASSERT provider.config["sendgrid_webhook_secret"] IS NULL OR EQUALS "***"
  END FOR
END FOR
```

```pascal
// Property: Preservation Checking — Empty webhook_secret on save preserves existing
FOR ALL X WHERE
  email_providers.config[<provider>_webhook_secret] = OLD_VALUE (non-null)
  AND X = PUT credentials with webhook_secret missing or empty string
DO
  email_providers_after ← apply X
  ASSERT email_providers_after.config[<provider>_webhook_secret] = OLD_VALUE
END FOR
```

### Bug 3: Email-link URLs hardcoded to localhost

**Root Cause (verified by reading code):**

The user invitation flow does not propagate the request origin. Trace:

1. `app/modules/organisations/router.py::invite_user` L921 — handler reads `org_id`, `user_id`, `ip_address` from `request.state` but does NOT touch `request.headers`. Calls `invite_org_user(...)` with no `base_url` arg.
2. `app/modules/organisations/service.py::invite_org_user` L1066 — calls `create_invitation(db, ...)` with no `base_url` arg.
3. `app/modules/auth/service.py::create_invitation` L2660 — `_base_url = base_url or getattr(settings, "frontend_base_url", "") or "http://localhost"`. Since `base_url` is missing, this falls through to `settings.frontend_base_url` which is `"http://localhost:5173"` per `app/config.py` L40 (verified — no override in `.env.pi`, `.env.dev`, or any other file).
4. `app/modules/auth/service.py::_send_invitation_email` L2967 — `invite_url = f"{base_url}/verify-email?token={token}"` — final URL is `http://localhost:5173/verify-email?token=…`.

The same defect chain exists for `_send_password_reset_email`, `_send_org_admin_invitation_email` (called from `provision_organisation` without `base_url`), `send_portal_link`, and the auth alert helpers. By contrast, sites that work correctly (`fleet_portal/admin_router.py::send_fleet_portal_invite` L120, `auth/router.py::resend_verification_email_endpoint` L2701, `invoices/router.py::create_invoice_endpoint` L280, `payments/router.py` L784) all do `origin = request.headers.get("origin") or ""` then pass `base_url=origin or settings.frontend_base_url` through the call chain.

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type EmailLinkSendCallSite
  OUTPUT: boolean

  RETURN X.endpoint IN {
    POST /api/v1/org/users/invite,
    POST /api/v1/admin/organisations,
    POST /api/v1/auth/forgot-password,
    POST /api/v1/customers/{id}/send-portal-link,
    <auth alert internal call sites that fire inside request scope>
  }
  AND X.email_body contains an absolute URL whose host comes from settings.frontend_base_url
  AND X.request.headers["Origin"] != ""
  AND X.request.headers["Origin"] != "http://" + settings.frontend_base_url.host
END FUNCTION
```

```pascal
// Property: Fix Checking — Email URL host matches request origin
FOR ALL X WHERE isBugCondition(X) DO
  send_after ← Execute X with fix applied
  parsed ← URL.parse(send_after.email_body.first_absolute_url)
  ASSERT parsed.scheme + "://" + parsed.netloc = X.request.headers["Origin"]
END FOR
```

```pascal
// Property: Preservation Checking — Existing correct sites unchanged
FOR ALL X WHERE X.endpoint IN {
  POST /api/v1/quotes/{id}/email,
  POST /api/v1/invoices,
  POST /api/v1/invoices/{id}/email,
  POST /api/v1/fleet-portal/admin/accounts (invite),
  POST /api/v1/auth/signup,
  POST /api/v1/auth/resend-verification,
  POST /api/v1/payments/qr-session
} DO
  ASSERT URL host construction logic IS UNCHANGED
END FOR
```

```pascal
// Property: Preservation Checking — Fallback when Origin missing
FOR ALL X WHERE
  X.endpoint IN {affected list}
  AND X.request.headers["Origin"] IS NULL
  AND X.request.headers["Host"] IS NULL
DO
  send_after ← Execute X with fix applied
  parsed ← URL.parse(send_after.email_body.first_absolute_url)
  ASSERT parsed.scheme + "://" + parsed.netloc = settings.frontend_base_url
END FOR
```

```pascal
// Property: Preservation Checking — No new trust assumption introduced
ASSERT trust_posture(Origin header) IS IDENTICAL TO trust_posture in:
  app/modules/fleet_portal/admin_router.py::send_fleet_portal_invite L120,
  app/modules/payments/router.py L784,
  app/modules/auth/router.py L2359 / L2701 / L2862
// i.e. the fix uses the same Origin-extraction pattern these sites
// have shipped against since v1.10.x — adding allow-list validation
// is OUT OF SCOPE.
```

---

## Out of Scope

- Centralising `notification_log` writes inside the unified `send_email` itself (the alternative approach considered earlier). Each Group A site continues to call `log_email_sent` directly, matching the existing Phase 3 contract documented in `email-provider-unification/plan.md` Section 3.17.
- Migrating any of the no-org sites (landing demo, auth lockout) to write `notification_log` — those have no org_id and the table is org-scoped.
- Adding org-facing Delivery Health view (the second proposed gap from Task 6 of the previous session). That stays as a separate follow-up if the user wants it later.
- Phase 8b legacy SMTP data migration and Phase 9 cleanup — explicitly skipped per user instruction.
- Building any new bounce dashboard, alert thresholds, or auto-remediation flows. The Phase 8c Delivery Health UI already exists at `/admin/email-providers` (admin-only).
- Origin / Host header allow-list enforcement or signature-based validation. The fix uses the same trust posture as existing correctly-implemented sites (4.14). Hardening the Origin trust model is a separate security review.
- Backfilling `settings.frontend_base_url` with the production hostname in `.env.pi` / `.env`. The fix removes the *requirement* to do that for email links to work — it does not preclude doing it later as a belt-and-braces measure.

## Affected Files

**Backend — Bug 1:**
- `app/modules/invoices/service.py` — `email_invoice` success branch (~L4636)
- `app/modules/quotes/service.py` — `send_quote_email` success branch (~L1115)
- `app/modules/vehicles/report_service.py` — `email_vehicle_report` success branch (~L457)
- `app/modules/payments/service.py` — `send_payment_receipt_email` success branch (~L713)
- `app/modules/bookings/service.py` — `send_booking_confirmation_email` success branch (~L1274)
- `app/modules/customers/service.py` — `notify_customer` success branch (~L770)

**Backend — Bug 2:**
- `app/modules/email_providers/schemas.py` — add `webhook_secret` field to `EmailProviderCredentialsRequest`; add response redaction to `EmailProviderResponse` serialiser
- `app/modules/email_providers/service.py` — `save_email_credentials` to accept `webhook_secret` kwarg and persist as `config['<provider_key>_webhook_secret']`; `_provider_to_dict` (or list helper) to redact webhook secret keys from `config` on read
- `app/modules/email_providers/router.py` — pass `webhook_secret` from request body through to service

**Backend — Bug 3:**
- `app/modules/organisations/router.py::invite_user` — extract origin, pass to `invite_org_user`
- `app/modules/organisations/service.py::invite_org_user` — accept `base_url` kwarg, pass to `create_invitation`
- `app/modules/auth/service.py::create_invitation` — already accepts `base_url`; no change here, the fix is upstream
- `app/modules/admin/router.py::provision_organisation_endpoint` — extract origin, pass to `provision_organisation`
- `app/modules/admin/service.py::provision_organisation` — accept `base_url` kwarg, pass to `_send_org_admin_invitation_email`
- `app/modules/auth/router.py` — wherever password reset is triggered (forgot-password endpoint) — extract origin, pass through
- `app/modules/auth/service.py::_send_password_reset_email` — extend signature with `base_url: str | None = None`; use it preferentially with the existing fallback
- `app/modules/auth/service.py::_send_lockout_email`, `_send_token_reuse_alert` and the L1046 sessions-alert helper — extend each with `base_url: str | None = None`; callers that run inside request scope pass it through, callers in background context pass `None`
- `app/modules/customers/router.py::send_portal_link_endpoint` — extract origin, pass to `send_portal_link`
- `app/modules/customers/service.py::send_portal_link` — accept `base_url` kwarg, build `portal_url` from it preferentially
- `app/modules/portal/service.py` — sites at L1108 and L2206 — accept `base_url` from caller chain (where invoked from request handlers)

**Frontend — Bug 2:**
- `frontend/src/pages/admin/EmailProviders.tsx` — add `webhook_secret` to `CREDENTIAL_FIELDS.brevo` and `CREDENTIAL_FIELDS.sendgrid`; surface public webhook URL near the field; ensure `handleSaveCredentials` lifts `webhook_secret` out of the credentials sub-dict and into the top-level request body (alongside `from_email`, `from_name`, `reply_to`).

**Tests:**
- `tests/test_invoice_email_failover.py` — add success-path assertion that `notification_log` row is written
- `tests/test_email_providers_webhook_secret.py` — new file: PUT credentials with `webhook_secret` persists it; GET response redacts; empty webhook_secret on save preserves existing
- `tests/test_bounce_webhooks.py` — extend the existing test class to cover the GUI-stored-secret happy path (mock `email_providers.config['brevo_webhook_secret']` set, verify 200 + bounce row written)
- `tests/test_invitation_email_origin.py` — new file: parametrised test that POSTs `/api/v1/org/users/invite` with `Origin: https://devin.oraflows.co.nz` and asserts the captured `_send_invitation_email` arg contains that host; same for `/api/v1/admin/organisations`, password reset, and `/api/v1/customers/{id}/send-portal-link`. Plus a no-Origin fallback case asserting `settings.frontend_base_url` is used.
