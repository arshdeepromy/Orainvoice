# Implementation Plan

This bugfix spec addresses three defects from `bugfix.md`:

- **Bug 1** — Group A migrated email sites never write `notification_log` on success (req 1.1, 1.3, 1.4, 1.5).
- **Bug 2** — Brevo / SendGrid webhook signing secrets cannot be stored from the admin GUI, so all webhook events are rejected with 403 (req 2.1, 2.2, 2.3, 2.4).
- **Bug 3** — Email-link sites build URLs from `settings.frontend_base_url = http://localhost:5173` instead of the request `Origin` (req 2.5, 2.6, 2.7, 2.8, 2.9, 2.11).

The implementation order is: write failing exploration tests + passing preservation tests for each bug, then fix the bug, then re-run the same tests to verify the fix and the absence of regressions. Each call-site fix is its own commit so the history stays bisectable.

---

## Phase 0 — Property tests (write BEFORE any fix)

- [x] 1. Write Bug 1 condition exploration test — `notification_log` empty on successful email
  - **Property 1: Bug Condition** — Group A success path does not write `notification_log`
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **GOAL**: Surface counterexamples that demonstrate `notification_log` has zero rows for `invoice_send`, `quote_send`, `vehicle_report_send`, `payment_receipt`, `booking_confirmation`, and `customer_notify` after a successful `send_email` call
  - **Scoped PBT Approach**: Use Hypothesis with a small set of seeded `org_id` + `recipient_email` pairs; mock `send_email` to return `SendResult(success=True, provider_key="brevo", provider_message_id="<msg-id>")`; for each Group A site, drive the function and assert ≥1 row exists in `notification_log` with the matching `template_type`, `status="sent"`, and `provider_key="brevo"`
  - Test file: `tests/test_notification_log_success_path.py`
  - Strategy: parametrise over (function, expected_template_type) tuples for the six Group A sites; share a fixture that builds a minimal org + customer + invoice/quote/etc and patches `app.integrations.email_sender.send_email` to return success
  - For each site: assert `SELECT COUNT(*) FROM notification_log WHERE template_type=?` is ≥ 1 after the call
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS for all six sites (confirms bug)
  - Document counterexample (e.g., `email_invoice produced audit_log row but no notification_log row`)
  - _Requirements: 1.1, 1.3, 1.4, 1.5_

- [x] 2. Write Bug 1 preservation property test — failure path unchanged
  - **Property 2: Preservation** — Group A failure path still calls `log_email_sent(status="failed")` and `create_in_app_notification`
  - **IMPORTANT**: Follow observation-first methodology
  - Test file: `tests/test_notification_log_failure_preservation.py`
  - Observe: drive `email_invoice` with `send_email` mocked to return `SendResult(success=False, error="boom")` on UNFIXED code → confirm `notification_log` row with `status="failed"` exists AND in_app_notification with `category="email_failure"` exists
  - Repeat observation for each of the six Group A sites
  - Write property-based test: for all six sites, when `result.success=False`, the failed-row + in-app-notification pattern fires unchanged
  - Verify tests PASS on UNFIXED code (these capture existing correct behaviour to preserve)
  - **EXPECTED OUTCOME**: Tests PASS
  - _Requirements: 4.1, 4.2_

- [x] 3. Write Bug 2 condition exploration test — webhook secret cannot be stored
  - **Property 1: Bug Condition** — `EmailProviderCredentialsRequest` drops `webhook_secret`; `_candidate_provider_secrets` returns empty
  - **CRITICAL**: This test MUST FAIL on unfixed code
  - Test file: `tests/test_email_providers_webhook_secret.py` (new file)
  - Sub-tests:
    - PUT `/api/v2/admin/email-providers/brevo/credentials` with body `{"credentials": {"api_key": "x"}, "webhook_secret": "S"}` and assert `email_providers.config['brevo_webhook_secret']` equals `"S"` afterwards (UNFIXED: schema drops the field, value is not persisted)
    - GET `/api/v2/admin/email-providers` returns `config` for brevo NOT containing the raw webhook secret (UNFIXED: even if it were stored, it'd be returned in plaintext — assert redacted to `"***"` post-fix)
    - With `email_providers.config['brevo_webhook_secret']` pre-seeded to `"S"`, POST a signed webhook to `/api/v1/notifications/webhooks/brevo-bounce` and assert 200 (UNFIXED: handler reads from this exact key, so this would actually pass IF the seed write happened directly via SQL — keep this case because it locks in the contract)
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: First two sub-tests FAIL, third sub-test PASSES (lock-in)
  - _Requirements: 2.1, 2.2, 2.3_

- [x] 4. Write Bug 2 preservation property test — env-var fallback + non-webhook provider unaffected
  - **Property 2: Preservation** — `app_settings.brevo_webhook_secret` env-var fallback still works; `custom_smtp` provider unchanged
  - Test file: `tests/test_email_providers_webhook_secret.py` (same file as task 3, new test class `TestPreservation`)
  - Observe: with `email_providers.config` empty AND `app_settings.brevo_webhook_secret = "envS"`, signed webhook POSTs are accepted (UNFIXED: passes — the legacy fallback path)
  - Observe: PUT credentials for `custom_smtp` with `webhook_secret` set; verify the field is silently ignored (custom SMTP has no webhook concept) — neither stored under any config key nor surfaced in response
  - Verify tests PASS on UNFIXED code
  - _Requirements: 4.7, 4.10_

- [x] 5. Write Bug 3 condition exploration test — invitation URL uses `localhost:5173`
  - **Property 1: Bug Condition** — Email-link sites build URLs from `settings.frontend_base_url` regardless of `Origin` header
  - **CRITICAL**: This test MUST FAIL on unfixed code
  - Test file: `tests/test_email_link_origin.py` (new file)
  - Sub-tests, parametrised over (endpoint, payload, expected_link_template_type):
    - `POST /api/v1/org/users/invite` with body `{"email": "u@example.com", "role": "salesperson"}` and `Origin: https://devin.oraflows.co.nz` — capture the `_send_invitation_email` argument and assert `invite_url.startswith("https://devin.oraflows.co.nz/verify-email?token=")`
    - `POST /api/v1/admin/organisations` with `Origin: https://example.com` — capture `_send_org_admin_invitation_email` and assert URL host = `example.com`
    - `POST /api/v1/auth/forgot-password` with valid email and `Origin: https://example.com` — capture `_send_password_reset_email` and assert reset_url host = `example.com`
    - `POST /api/v1/customers/{customer_id}/send-portal-link` with `Origin: https://example.com` — capture `send_portal_link` body and assert portal URL host = `example.com`
  - Use FastAPI `TestClient` with the test app and `monkeypatch` to capture the `_send_*_email` calls (don't actually send)
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: All four sub-tests FAIL (URL host = `localhost:5173`)
  - _Requirements: 2.5, 2.6, 2.7, 2.9_

- [x] 6. Write Bug 3 preservation property test — already-correct sites unchanged + Origin-missing fallback works
  - **Property 2: Preservation** — Sites already reading the request origin keep working; `frontend_base_url` fallback used when Origin absent
  - Test file: `tests/test_email_link_origin.py` (same file, new test class `TestPreservation`)
  - Observe on UNFIXED code:
    - `POST /api/v1/quotes/{id}/email` with `Origin: https://example.com` already produces a quote acceptance link with host `example.com` — passes today
    - `POST /api/v1/invoices` with `Origin: https://example.com` and a customer with email already produces an invoice email payment link with host `example.com` — passes today
    - `POST /api/v1/fleet-portal/admin/accounts` (invite) with `Origin: https://example.com` already produces a fleet invite URL with host `example.com` — passes today
    - For an affected endpoint (e.g. user invite), with NO `Origin` header AND NO `Host` header, the URL falls back to `settings.frontend_base_url`
  - Write property-based tests covering each preservation case
  - Verify tests PASS on UNFIXED code (lock-in for the correct sites; the fourth case will keep passing post-fix because it tests the fallback branch)
  - _Requirements: 4.11, 4.12, 4.13, 4.14, 3.16_

---

## Phase 1 — Bug 1 fixes (one commit per Group A site for bisectability)

- [x] 7. Fix `email_invoice` success path — write `notification_log` row before audit log
  - **Site**: `app/modules/invoices/service.py::email_invoice` (~L4636, just after the failure-path raise)
  - Insert the success branch immediately after `raise ValueError(error_msg)` block but BEFORE the audit log write:
    ```python
    from app.modules.notifications.service import log_email_sent as _log_email_sent
    try:
        await _log_email_sent(
            db, org_id=org_id, recipient=recipient_email,
            template_type="invoice_send", subject=_email_subject,
            status="sent", channel="email",
            provider_key=result.provider_key,
            provider_message_id=result.provider_message_id,
        )
    except Exception:
        logger.warning("Failed to log success for invoice %s", invoice_id)
    ```
  - **Bug_Condition**: isBugCondition(X) where X.module = "invoices/service.email_invoice" AND X.result.success = true
  - **Expected_Behavior**: row exists in `notification_log` with `template_type="invoice_send"`, `status="sent"`, `provider_key=result.provider_key`
  - **Preservation**: failure-path `_log_email_sent(status="failed")` + `create_in_app_notification` calls remain untouched; audit log write remains unchanged
  - Verify Property 1 sub-test for `email_invoice` now PASSES; verify Property 2 unchanged
  - Commit message: `email-delivery-visibility-fixes: bug 1 — email_invoice success-path notification_log`
  - _Requirements: 1.1, 1.3, 1.4, 1.5, 3.1, 3.3, 3.4, 4.1_

- [x] 8. Fix `send_quote_email` success path
  - **Site**: `app/modules/quotes/service.py::send_quote_email` (~L1112)
  - Same pattern as task 7: add `_log_email_sent(status="sent", template_type="quote_send", provider_key=..., provider_message_id=...)` immediately after the failure block
  - Verify Property 1 sub-test for quote site PASSES
  - Commit: `email-delivery-visibility-fixes: bug 1 — send_quote_email success-path notification_log`
  - _Requirements: 1.3, 3.2, 3.4, 4.1_

- [x] 9. Fix `email_vehicle_report` success path
  - **Site**: `app/modules/vehicles/report_service.py::email_vehicle_report` (~L457)
  - Same pattern: `template_type="vehicle_report_send"`
  - Commit: `email-delivery-visibility-fixes: bug 1 — email_vehicle_report success-path notification_log`
  - _Requirements: 1.3, 3.2, 4.1_

- [x] 10. Fix `send_payment_receipt_email` success path
  - **Site**: `app/modules/payments/service.py::send_payment_receipt_email` (~L713)
  - Note: this site has `if result.success` (not `if not`) so the success branch already exists at L713-716 (logger.info only) — add `_log_email_sent(status="sent", template_type="payment_receipt", ...)` BEFORE the `return` inside that branch
  - Commit: `email-delivery-visibility-fixes: bug 1 — send_payment_receipt_email success-path notification_log`
  - _Requirements: 1.3, 3.2, 4.1_

- [x] 11. Fix `send_booking_confirmation_email` success path
  - **Site**: `app/modules/bookings/service.py::send_booking_confirmation_email` (~L1274)
  - Same as task 10: success branch already exists with logger.info; add `_log_email_sent(status="sent", template_type="booking_confirmation", ...)` before `return True`
  - Commit: `email-delivery-visibility-fixes: bug 1 — send_booking_confirmation_email success-path notification_log`
  - _Requirements: 1.3, 3.2, 4.1_

- [x] 12. Fix `notify_customer` success path
  - **Site**: `app/modules/customers/service.py::notify_customer` (~L770, just after `if result.success:` logger line)
  - Add `_log_email_sent(status="sent", template_type="customer_notify", ...)` before the function returns success
  - Note: `notify_customer` passes `org_sender_name=org_name` to `send_email` — preserve unchanged
  - Commit: `email-delivery-visibility-fixes: bug 1 — notify_customer success-path notification_log`
  - _Requirements: 1.3, 3.2, 4.1_

- [x] 13. Verify Bug 1 condition + preservation tests all pass
  - Re-run `tests/test_notification_log_success_path.py` and `tests/test_notification_log_failure_preservation.py`
  - **EXPECTED OUTCOME**: both files green, all six Group A sites covered
  - Run a focused integration smoke: create a fresh invoice via `POST /api/v1/invoices` against the local dev stack, then `SELECT recipient, template_type, status, provider_key, provider_message_id FROM notification_log ORDER BY created_at DESC LIMIT 1` and verify a row exists for `invoice_send / sent / brevo / <msg-id>`
  - _Requirements: 1.1, 1.3, 1.4, 3.4, 4.1_

---

## Phase 2 — Bug 2 fixes (admin can store webhook signing secret)

- [x] 14. Extend `EmailProviderCredentialsRequest` schema with `webhook_secret`
  - **File**: `app/modules/email_providers/schemas.py`
  - Add field to `EmailProviderCredentialsRequest`:
    ```python
    webhook_secret: str | None = Field(
        None,
        description="Webhook signing secret (provider-specific). Persisted under config['<provider_key>_webhook_secret']. Empty string is treated as 'no change'.",
    )
    ```
  - Add a custom serialiser / `field_serializer` to `EmailProviderResponse` (or do redaction in the dict-builder in `_provider_to_dict`) so `config['brevo_webhook_secret']` and `config['sendgrid_webhook_secret']` are replaced with the literal string `"***"` when present, omitted when absent. Other config keys (`from_email`, `from_name`, `reply_to`) pass through unchanged
  - _Requirements: 3.7, 3.9, 4.9_

- [x] 15. Extend `save_email_credentials` to persist the webhook secret
  - **File**: `app/modules/email_providers/service.py::save_email_credentials` (~L196)
  - Add `webhook_secret: str | None = None` keyword-only parameter
  - When `provider_key in {"brevo", "sendgrid"}` AND `webhook_secret` is not None AND `webhook_secret.strip() != ""`, write `config[f"{provider_key}_webhook_secret"] = webhook_secret.strip()`
  - When `webhook_secret` is None or empty, leave any existing `config[<key>_webhook_secret]` untouched (no clobber on partial save — matches the empty-fields semantics in `frontend/src/pages/admin/EmailProviders.tsx::handleSaveCredentials` L388)
  - When `provider_key NOT IN {"brevo", "sendgrid"}` AND `webhook_secret` is set, silently ignore it (log at DEBUG) — custom SMTP has no webhook concept
  - _Requirements: 3.7, 4.6, 4.10_

- [x] 16. Pipe `webhook_secret` through `put_credentials` router
  - **File**: `app/modules/email_providers/router.py::put_credentials` (~L100)
  - Pass `webhook_secret=payload.webhook_secret` to `save_email_credentials`
  - _Requirements: 3.7_

- [x] 17. Add `webhook_secret` field to admin GUI for Brevo + SendGrid
  - **File**: `frontend/src/pages/admin/EmailProviders.tsx`
  - In `CREDENTIAL_FIELDS.brevo` and `CREDENTIAL_FIELDS.sendgrid`, append:
    ```ts
    { key: 'webhook_secret', label: 'Webhook signing secret', placeholder: 'Leave blank to keep existing', type: 'password' }
    ```
  - In `handleSaveCredentials` (~L388), lift `webhook_secret` out of the `credentials` sub-dict (same pattern as `smtp_host`, `from_email` are lifted today) so the request body becomes:
    ```ts
    await apiClient.put(`/api/v2/admin/email-providers/${key}/credentials`, {
      credentials, // api_key, smtp_login only
      smtp_host, smtp_port, smtp_encryption,
      from_email, from_name, reply_to,
      webhook_secret: webhook_secret || undefined,
    })
    ```
  - Render the public webhook URL near the field (e.g. `Webhook URL: ${window.location.origin}/api/v1/notifications/webhooks/${providerKey}-bounce` for the matching provider) so the admin can copy-paste into Brevo/SendGrid
  - When `provider.config.brevo_webhook_secret === "***"` (or `sendgrid_webhook_secret === "***"`), display "Already set — leave blank to keep" as the input placeholder
  - All API consumption in this file MUST follow the safe-api-consumption pattern: `?? ''`, `?? []`, no `as any`, typed generics on `apiClient` calls
  - _Requirements: 3.6, 3.10, 3.11, safe-api-consumption.md_

- [x] 18. Verify Bug 2 condition + preservation tests all pass
  - Re-run `tests/test_email_providers_webhook_secret.py`
  - **EXPECTED OUTCOME**: Property 1 sub-tests PASS (webhook secret stored, redacted on read)
  - **EXPECTED OUTCOME**: Property 2 PASSES (env-var fallback intact, custom_smtp ignores field)
  - Smoke against local dev:
    1. `PUT /api/v2/admin/email-providers/brevo/credentials` with `{"credentials": {"api_key": "..."}, "webhook_secret": "<from Brevo dashboard>"}` via the GUI
    2. `SELECT config FROM email_providers WHERE provider_key='brevo'` and confirm `brevo_webhook_secret` is set
    3. `GET /api/v2/admin/email-providers` and confirm response masks the secret with `"***"`
    4. Trigger Brevo to fire a test webhook (or use `curl` with a known signature) and confirm `docker logs invoicing-app-1` no longer shows the "no signing secret configured" warning, instead returns 200
  - Commit: `email-delivery-visibility-fixes: bug 2 — admin GUI for brevo/sendgrid webhook signing secret`
  - _Requirements: 2.1, 2.2, 2.3, 3.6, 3.7, 3.8, 3.9, 4.7, 4.10_

---

## Phase 3 — Bug 3 fixes (URLs from request Origin)

For each defective site, the pattern is:

1. **Router**: extract `_origin = request.headers.get("origin") or None` (or scheme://host fallback when Origin missing), pass `base_url=_origin` to the service.
2. **Service**: accept new keyword arg `base_url: str | None = None`, use it preferentially with the existing `getattr(settings, "frontend_base_url", "")` fallback.

A shared helper avoids copy-paste drift.

- [x] 19. Add `extract_request_base_url(request)` helper
  - **File**: `app/core/request_utils.py` (new file — or append to existing `app/core/utils.py` if a util module already exists; check first)
  - Implementation:
    ```python
    def extract_request_base_url(request: Request) -> str | None:
        """Return the absolute base URL (scheme://host) the client used.

        Prefers the ``Origin`` header (set by browsers on cross-origin requests).
        Falls back to ``request.url.scheme`` + ``Host`` header when ``Origin`` is
        absent (server-to-server callers, redirected forms). Returns ``None``
        when neither is present so callers can fall back to
        ``settings.frontend_base_url``.
        """
        origin = (request.headers.get("origin") or "").strip()
        if origin:
            return origin.rstrip("/")
        host = (request.headers.get("host") or "").strip()
        if host:
            scheme = request.url.scheme or "https"
            return f"{scheme}://{host}".rstrip("/")
        return None
    ```
  - Add module unit tests in `tests/test_request_utils.py`: covers Origin set, Host-only fallback, both empty
  - _Requirements: 3.12, 3.16_

- [x] 20. Fix `POST /api/v1/org/users/invite` (org user invitation)
  - **Router**: `app/modules/organisations/router.py::invite_user` (~L921)
    - Add `_origin = extract_request_base_url(request)` at the top of the handler
    - Pass `base_url=_origin` to `invite_org_user`
  - **Service**: `app/modules/organisations/service.py::invite_org_user` (~L1066)
    - Add `base_url: str | None = None` kwarg
    - Pass to `create_invitation(..., base_url=base_url)` (which already accepts it)
  - **Bug_Condition**: invitation email URL host = `localhost:5173` even when `Origin` header is set
  - **Expected_Behavior**: URL host = `Origin` header value
  - **Preservation**: when `Origin` absent and `Host` absent, fall back to `settings.frontend_base_url` (handled by `create_invitation`'s existing fallback)
  - Commit: `email-delivery-visibility-fixes: bug 3 — invite_user reads request origin`
  - _Requirements: 2.5, 3.12, 3.13, 3.14, 3.15_

- [x] 21. Fix `POST /api/v1/admin/organisations` (Global Admin provisions org)
  - **Router**: `app/modules/admin/router.py::provision_organisation_endpoint` (~L144 area; verify exact line)
    - Add `_origin = extract_request_base_url(request)`
    - Pass `base_url=_origin` to `provision_organisation`
  - **Service**: `app/modules/admin/service.py::provision_organisation` (~L108)
    - Add `base_url: str | None = None` kwarg
    - Pass to `_send_org_admin_invitation_email(..., base_url=base_url)` (signature already accepts it per L361)
  - Commit: `email-delivery-visibility-fixes: bug 3 — provision_organisation reads request origin`
  - _Requirements: 2.6, 3.12, 3.13_

- [x] 22. Fix password reset email link
  - **Router**: locate the `/auth/forgot-password` (or equivalent) endpoint in `app/modules/auth/router.py`. Add `_origin = extract_request_base_url(request)` and pass `base_url=_origin` through the call chain
  - **Service**: extend `_send_password_reset_email` (`app/modules/auth/service.py` ~L2197) signature with `base_url: str | None = None`; replace the inline `getattr(settings, 'frontend_base_url', '') or 'http://localhost'` with `(base_url or getattr(settings, 'frontend_base_url', '') or 'http://localhost').rstrip("/")`
  - Update intermediate caller(s) in the auth service that wrap `_send_password_reset_email` to thread `base_url` through
  - Commit: `email-delivery-visibility-fixes: bug 3 — password reset email reads request origin`
  - _Requirements: 2.7, 3.12, 3.13_

- [x] 23. Fix auth alert helpers (lockout, token-reuse, sessions-alert)
  - **Service**: `app/modules/auth/service.py`
    - `_send_lockout_email` (~L399 — uses `support_url`)
    - `_send_token_reuse_alert` (~L668-676 — uses `security_url` and `reset_url`)
    - The L1046 `sessions_url` helper (find the enclosing function name and update similarly)
  - For each: add `base_url: str | None = None` kwarg; replace the inline `getattr(settings, 'frontend_base_url', '')` reads with `(base_url or getattr(settings, 'frontend_base_url', '') or 'http://localhost').rstrip("/")`
  - Update direct callers of these helpers that run inside request scope (look for callers in `app/modules/auth/router.py` and `app/middleware/auth.py`) — pass `base_url=extract_request_base_url(request)` from those sites
  - Callers in background-task / non-request contexts (e.g. account suspension sweeps) keep passing `None` — the fallback covers them
  - Commit: `email-delivery-visibility-fixes: bug 3 — auth alert helpers accept base_url`
  - _Requirements: 2.8, 3.12, 3.14, 4.12_

- [x] 24. Fix `POST /api/v1/customers/{id}/send-portal-link`
  - **Router**: `app/modules/customers/router.py::send_portal_link_endpoint` (~L963)
    - Add `_origin = extract_request_base_url(request)`
    - Pass `base_url=_origin` to `send_portal_link`
  - **Service**: `app/modules/customers/service.py::send_portal_link` (~L2284 area)
    - Add `base_url: str | None = None` kwarg
    - Replace `portal_url = f"{settings.frontend_base_url}/portal/{customer.portal_token}"` with `_base = (base_url or settings.frontend_base_url or "http://localhost").rstrip("/")` then `portal_url = f"{_base}/portal/{customer.portal_token}"`
  - Commit: `email-delivery-visibility-fixes: bug 3 — send_portal_link reads request origin`
  - _Requirements: 2.9, 3.12, 3.13_

- [x] 25. Fix portal service URL builders that run inside request scope
  - **Service**: `app/modules/portal/service.py`
    - **Site A** at ~L1108 — `pay_invoice_via_portal` builds `portal_base` for Stripe Checkout `success_url` + `cancel_url`. The customer is on the public portal page (e.g. `https://devin.oraflows.co.nz/portal/<token>`) when they click Pay; Stripe needs absolute URLs to redirect back to AFTER checkout, and those URLs must match the host the customer is actually on, otherwise the redirect lands on the wrong domain (or `localhost:3000`)
    - **Site B** at ~L2206 — second `portal_url` builder for the "request portal link" / portal recovery email flow
  - **Plan**:
    1. Locate the routers for both sites (likely `portal/router.py::pay_invoice_via_portal_endpoint` and `request_portal_link_endpoint`)
    2. In each router handler, add `_origin = extract_request_base_url(request)` (helper from Task 19)
    3. Pass `base_url=_origin` to the service function
    4. In each service function, add `base_url: str | None = None` kwarg
    5. Build the URL with `_base = (base_url or app_settings.frontend_base_url or "http://localhost:3000").rstrip("/")`
  - **Stripe-specific safety net** (Site A only): Stripe Checkout `success_url` / `cancel_url` MUST be publicly reachable. If `base_url` parses as a non-http(s) scheme (e.g. `capacitor://`, `file://`) OR is bare `localhost` / `127.0.0.1` while `app_settings.frontend_base_url` is a real public host, fall back to `app_settings.frontend_base_url`. Implementation:
    ```python
    from urllib.parse import urlparse

    def _resolve_stripe_redirect_base(request_base: str | None, fallback: str | None) -> str:
        candidate = (request_base or "").strip().rstrip("/")
        if candidate:
            parsed = urlparse(candidate)
            if parsed.scheme in {"http", "https"}:
                host = (parsed.hostname or "").lower()
                # Allow real public hosts always; allow localhost only if no public fallback exists
                if host and host not in {"localhost", "127.0.0.1"} or not (fallback and "localhost" not in fallback):
                    return candidate
        return (fallback or "http://localhost:3000").rstrip("/")
    ```
    Use this helper at Site A only. Site B (recovery email link) does not need the safety net because it's just an email body URL, not a Stripe redirect target — the standard `(base_url or frontend_base_url or fallback)` chain is fine
  - **Preservation**: existing background-task callers (Stripe webhook handlers, scheduled jobs) that don't have a request scope continue to call the service without `base_url` and fall through to `app_settings.frontend_base_url` exactly as today — no caller is forced to migrate
  - **Test additions** (extend `tests/test_email_link_origin.py`):
    - `POST /api/v1/portal/pay/<token>` with `Origin: https://example.com` → assert Stripe `success_url` host = `example.com`
    - `POST /api/v1/portal/pay/<token>` with `Origin: capacitor://localhost` → assert Stripe `success_url` falls back to `app_settings.frontend_base_url`
    - `POST /api/v1/portal/request-link` with `Origin: https://example.com` → assert recovery email body URL host = `example.com`
  - Commit: `email-delivery-visibility-fixes: bug 3 — portal service URLs read request origin (with Stripe-redirect safety net)`
  - _Requirements: 2.11, 3.12, 3.13, 4.12_

- [x] 26. Verify Bug 3 condition + preservation tests all pass
  - Re-run `tests/test_email_link_origin.py`
  - **EXPECTED OUTCOME**: all four Property 1 sub-tests PASS (URL host matches `Origin`)
  - **EXPECTED OUTCOME**: Property 2 still PASSES (correct sites unchanged, fallback works)
  - Smoke against local dev:
    1. From the GUI accessed at the dev origin, `POST /api/v1/org/users/invite` with a test recipient
    2. Inspect the Brevo dashboard email body and confirm the `Accept Invitation` link begins with the dev origin, NOT `http://localhost:5173`
    3. Repeat for password reset and customer portal link
  - _Requirements: 2.5, 2.6, 2.7, 2.8, 2.9, 3.12, 3.15, 4.11, 4.12, 4.13, 4.14_

---

## Phase 4 — Final verification

- [x] 27. End-to-end smoke against local dev (post all fixes)
  - Issue an invoice via the Create Invoice button → confirm:
    - `audit_log` row written (already worked)
    - `notification_log` row written with `template_type='invoice_send'`, `status='sent'`, `provider_key='brevo'`, `provider_message_id` set
    - The org admin sees the row on `Notifications → Delivery Log` page
  - Trigger a Brevo webhook (Brevo dashboard → "Test webhook" or send a real email to a deliberately-unknown address):
    - `docker logs invoicing-app-1` shows the webhook arrived with HTTP 200 (not 403)
    - `notification_log.delivered_at` (or `bounced_at` + `bounce_reason`) updated for the `provider_message_id` that matches
    - For bounce: a row appears in `bounced_addresses`
  - Invite a new org user from the dev origin:
    - The recipient email contains a link to the dev origin (not localhost)
  - _Requirements: 1.4, 1.5, 2.1, 3.4, 3.5, 3.8, 3.15_

- [x] 28. Update `docs/ISSUE_TRACKER.md`
  - Add three issue entries:
    - `ISSUE-XXX` — Bug 1: Group A success-path notification_log gap (resolved by this spec)
    - `ISSUE-XXX+1` — Bug 2: Brevo/SendGrid webhook signing secret cannot be stored from GUI (resolved)
    - `ISSUE-XXX+2` — Bug 3: Email-link sites build URLs from `frontend_base_url` instead of request `Origin` (resolved)
  - Reference the bugfix spec by path in each entry
  - _Requirements: project-overview.md issue-tracking convention_

- [x] 29. Push to `origin/main` (manual — user gates the push)
  - DO NOT push automatically. List the new commits, summarise, ask the user to push when ready
  - User pushes manually per the no-auto-push rule
  - _Requirements: project-overview.md git workflow_

---

## Test scope discipline

Per the workspace rules, only run tests scoped to the current task. Do NOT run the full suite during this spec. If unrelated test failures surface (e.g. a flaky test in another module), log as a separate issue per `issue-tracking-workflow.md` and do NOT broaden scope.

The Property 1 / Property 2 tests written in tasks 1-6 are scoped. Each fix task (7-12, 14-17, 19-25) re-runs only the Property tests covering its bug condition. Phase 4 task 27 is a manual smoke, not a test-suite run.
