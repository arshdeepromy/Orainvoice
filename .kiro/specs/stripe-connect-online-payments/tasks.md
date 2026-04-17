# Implementation Plan: Stripe Connect Online Payments

## Overview

This plan implements the org-facing Online Payments settings page and invoice payment capabilities using Stripe Connect (Standard). Most backend infrastructure already exists (OAuth flow, payment link generation, webhook handling, portal payment). The work focuses on 2 new backend endpoints (status API, disconnect API), enhancements to existing backend code (application fee, webhook idempotency, portal response), a new frontend settings page, and wiring payment actions into invoice detail, invoice list, and customer portal pages.

## Tasks

- [x] 1. Add backend schemas and new endpoints for Online Payments settings
  - [x] 1.1 Create `OnlinePaymentsStatusResponse` and `OnlinePaymentsDisconnectResponse` Pydantic schemas in `app/modules/payments/schemas.py`
    - `OnlinePaymentsStatusResponse`: `is_connected: bool`, `account_id_last4: str = ""`, `connect_client_id_configured: bool`, `application_fee_percent: Decimal | None = None`
    - `OnlinePaymentsDisconnectResponse`: `message: str`, `previous_account_last4: str`
    - _Requirements: 1.6, 1.7, 3.2_

  - [x] 1.2 Implement `GET /api/v1/payments/online-payments/status` endpoint in `app/modules/payments/router.py`
    - Gate with `require_role("org_admin", "global_admin")`
    - Fetch `Organisation` by `org_id` from request context
    - Check `org.stripe_connect_account_id` is not None → `is_connected`
    - Mask account ID: last 4 characters only, never the full ID
    - Call `get_stripe_connect_client_id()` → `connect_client_id_configured`
    - Read `application_fee_percent` from Stripe integration config
    - Return `OnlinePaymentsStatusResponse`
    - _Requirements: 1.6, 1.7, 2.6_

  - [x] 1.3 Implement `POST /api/v1/payments/online-payments/disconnect` endpoint in `app/modules/payments/router.py`
    - Gate with `require_role("org_admin")`
    - Fetch `Organisation` by `org_id`; return 400 if no `stripe_connect_account_id`
    - Capture previous account ID for audit, then set `stripe_connect_account_id = None`
    - `db.flush()` then `await db.refresh(org)`
    - Write audit log entry: `stripe_connect.disconnected` with masked previous ID and user ID
    - Return `OnlinePaymentsDisconnectResponse` with masked previous account ID
    - _Requirements: 3.2, 3.4_

  - [x] 1.4 Write property test for account ID masking (Property 1)
    - **Property 1: Account ID masking never leaks the full ID**
    - **Validates: Requirements 1.6, 1.7**
    - Test file: `tests/properties/test_stripe_connect_properties.py`
    - Use Hypothesis: `st.text(min_size=4, max_size=50, alphabet=st.characters(whitelist_categories=('L', 'N')))`
    - Assert: masked version contains exactly last 4 characters and does NOT contain the full account ID
    - Minimum 100 iterations
    - Tag: `# Feature: stripe-connect-online-payments, Property 1: Account ID masking never leaks the full ID`

  - [x] 1.5 Write unit tests for status and disconnect endpoints
    - Test file: `tests/test_online_payments_endpoints.py`
    - Test: org with connected account → `is_connected=True`, masked ID returned
    - Test: org with no connected account → `is_connected=False`, empty `account_id_last4`
    - Test: response never contains full account ID
    - Test: disconnect clears `stripe_connect_account_id` to None
    - Test: disconnect writes audit log with masked ID
    - Test: disconnect with no account → 400
    - Test: unauthenticated → 401, salesperson → 403
    - _Requirements: 1.6, 1.7, 3.2, 3.4_

- [x] 2. Add application fee support and webhook idempotency
  - [x] 2.1 Add `application_fee_percent` field to `StripeConfigRequest` in `app/modules/admin/schemas.py`
    - `application_fee_percent: Decimal | None = Field(default=None, ge=0, le=50)`
    - Store in the encrypted `integration_configs` JSON alongside existing Stripe keys
    - _Requirements: 7.3_

  - [x] 2.2 Add `get_application_fee_percent()` helper in `app/integrations/stripe_billing.py`
    - Read from Stripe integration config, return `Decimal | None`
    - _Requirements: 7.1, 7.2_

  - [x] 2.3 Add `application_fee_amount` parameter to `create_payment_link()` in `app/integrations/stripe_connect.py`
    - Add optional `application_fee_amount: int | None = None` parameter
    - When provided and > 0, add `payment_intent_data[application_fee_amount]` to the Checkout Session payload
    - _Requirements: 7.1_

  - [x] 2.4 Update callers to pass application fee
    - In `app/modules/payments/service.py` → `generate_stripe_payment_link()`: read fee percentage via `get_application_fee_percent()`, calculate `int(amount_cents * fee_percent / 100)`, pass to `create_payment_link()`
    - In `app/modules/portal/service.py` → `create_portal_payment()`: same calculation
    - When fee percentage is 0 or None, do not include application fee
    - _Requirements: 7.1, 7.2_

  - [x] 2.5 Add webhook idempotency check in `app/modules/payments/service.py` → `handle_stripe_webhook()`
    - Before creating a Payment record, query for existing payment with same `stripe_payment_intent_id` and `is_refund == False`
    - If found, return `{"status": "ignored", "reason": "Duplicate event"}` and skip payment creation
    - _Requirements: 6.6_

  - [x] 2.6 Write property test for application fee calculation (Property 7)
    - **Property 7: Application fee calculation**
    - **Validates: Requirements 7.1, 7.2**
    - Test file: `tests/properties/test_stripe_connect_properties.py`
    - Use Hypothesis: `st.integers(min_value=1, max_value=10_000_000)` for amounts, `st.decimals(min_value=Decimal("0"), max_value=Decimal("50"))` for percentages
    - Assert: `application_fee_amount == round(amount * percentage / 100)`, and when percentage is 0 or None, no fee is included
    - Minimum 100 iterations
    - Tag: `# Feature: stripe-connect-online-payments, Property 7: Application fee calculation`

  - [x] 2.7 Write property test for webhook idempotency (Property 6)
    - **Property 6: Webhook idempotency — duplicate events produce no additional records**
    - **Validates: Requirements 6.6**
    - Test file: `tests/properties/test_stripe_connect_properties.py`
    - Use Hypothesis: `st.uuids()` for invoice IDs, `st.integers(min_value=100, max_value=1_000_000)` for amounts
    - Assert: processing the same event N times (N ≥ 1) results in exactly one Payment record
    - Minimum 100 iterations
    - Tag: `# Feature: stripe-connect-online-payments, Property 6: Webhook idempotency`

- [x] 3. Add remaining backend property tests and portal enhancement
  - [x] 3.1 Add `org_has_stripe_connect: bool` to `PortalInvoicesResponse` in `app/modules/portal/service.py`
    - Set from `bool(org.stripe_connect_account_id)` in the portal invoices service
    - Portal frontend uses this to conditionally show "Pay Now" button
    - _Requirements: 5.1, 5.5_

  - [x] 3.2 Extend invoice list query to include `has_stripe_payment` computed field
    - Add a correlated subquery on the `payments` table checking for `method == "stripe"` and `is_refund == False`
    - Return as a boolean field per invoice in the list response
    - Add `has_stripe_payment: bool = False` to the invoice list response schema
    - _Requirements: 8.1_

  - [x] 3.3 Write property test for CSRF state token binding (Property 2)
    - **Property 2: CSRF state token binds to the originating org**
    - **Validates: Requirements 2.5**
    - Test file: `tests/properties/test_stripe_connect_properties.py`
    - Use Hypothesis: `st.uuids()` for org IDs
    - Assert: a state token generated for org A is rejected when the authenticated org is B
    - Minimum 100 iterations
    - Tag: `# Feature: stripe-connect-online-payments, Property 2: CSRF state token binds to the originating org`

  - [x] 3.4 Write property test for checkout session correctness (Property 3)
    - **Property 3: Checkout session amount and metadata correctness**
    - **Validates: Requirements 4.2, 4.3, 4.6**
    - Test file: `tests/properties/test_stripe_connect_properties.py`
    - Use Hypothesis: `st.integers(min_value=1, max_value=10_000_000)` for amounts, `st.uuids()` for invoice IDs, `st.sampled_from(["nzd", "aud", "usd"])` for currencies
    - Assert: `line_items[0].price_data.unit_amount == int(amount * 100)`, metadata contains invoice ID, currency matches
    - Minimum 100 iterations
    - Tag: `# Feature: stripe-connect-online-payments, Property 3: Checkout session amount and metadata correctness`

  - [x] 3.5 Write property test for webhook balance update (Property 4)
    - **Property 4: Webhook payment updates invoice balances correctly**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.8**
    - Test file: `tests/properties/test_stripe_connect_properties.py`
    - Use Hypothesis: `st.decimals(min_value=Decimal("0.01"), max_value=Decimal("999999.99"))` for amounts and balances
    - Assert: payment recorded is `min(amount, balance_due)`, new `balance_due == old - min(amount, balance_due)`, status is `"paid"` if balance is 0 else `"partially_paid"`
    - Minimum 100 iterations
    - Tag: `# Feature: stripe-connect-online-payments, Property 4: Webhook payment updates invoice balances correctly`

  - [x] 3.6 Write property test for webhook signature verification (Property 5)
    - **Property 5: Webhook signature verification accepts valid and rejects invalid signatures**
    - **Validates: Requirements 6.4**
    - Test file: `tests/properties/test_stripe_connect_properties.py`
    - Use Hypothesis: `st.binary(min_size=1, max_size=10000)` for payloads, `st.text(min_size=10, max_size=50)` for secrets
    - Assert: correctly computed HMAC-SHA256 signature is accepted, any non-matching signature raises `ValueError`
    - Minimum 100 iterations
    - Tag: `# Feature: stripe-connect-online-payments, Property 5: Webhook signature verification`

- [x] 4. Checkpoint — Backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Create Online Payments settings page (frontend)
  - [x] 5.1 Create `OnlinePaymentsSettings` page at `frontend/src/pages/settings/OnlinePaymentsSettings.tsx`
    - State: `status: OnlinePaymentsStatus | null`, `loading: boolean`, `error: string | null`, `showDisconnectDialog: boolean`
    - Fetch `GET /api/v1/payments/online-payments/status` on mount with AbortController cleanup
    - Use `?.` and `?? []` / `?? 0` on all API response property access
    - Use typed generics on `apiClient` calls — no `as any`
    - _Requirements: 1.2, 1.3, 1.4, 1.6_

  - [x] 5.2 Implement conditional rendering states in `OnlinePaymentsSettings`
    - If `!status?.connect_client_id_configured` → show "Online payments not available. Contact your platform administrator." message, hide "Set Up Now" button
    - If `!status?.is_connected` → show "Set Up Now" button + "Not Connected" badge
    - If `status?.is_connected` → show "Connected" badge + masked account ID (`account_id_last4`) + "Disconnect" button
    - Display `application_fee_percent` if configured
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 2.6_

  - [x] 5.3 Implement OAuth connect flow in `OnlinePaymentsSettings`
    - "Set Up Now" click → `POST /api/v1/billing/stripe/connect` → redirect to `authorize_url`
    - On page load, detect `?code=...&state=...` query params → call `GET /api/v1/billing/stripe/connect/callback` with params
    - On success → re-fetch status → show "Connected" without full page reload
    - On error → display error message from API response
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 5.4 Implement disconnect flow in `OnlinePaymentsSettings`
    - "Disconnect" click → show confirmation dialog warning that existing payment links will stop working
    - Confirm → `POST /api/v1/payments/online-payments/disconnect`
    - On success → re-fetch status → show "Not Connected" and "Set Up Now" button
    - _Requirements: 3.1, 3.2, 3.3_

- [x] 6. Wire settings page navigation and routing
  - [x] 6.1 Add "Online Payments" nav item to settings sidebar
    - Add to `SettingsLayout.tsx` (or equivalent settings sidebar component)
    - Visible only to `org_admin` and `global_admin` roles
    - Route path: `/settings/online-payments`
    - _Requirements: 1.1_

  - [x] 6.2 Register `/settings/online-payments` route in `frontend/src/App.tsx`
    - Import `OnlinePaymentsSettings` and add route inside the settings route group
    - Wrap with `SafePage` component following existing pattern
    - _Requirements: 1.1_

- [x] 7. Checkpoint — Settings page compiles and renders
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Add invoice payment link action and online payment indicators
  - [x] 8.1 Add "Send Payment Link" / "Pay Now" action to invoice detail page
    - File: `frontend/src/pages/invoices/InvoiceDetail.tsx` (or equivalent)
    - Show button when: invoice status is `issued`, `partially_paid`, or `overdue` AND org has connected Stripe account
    - Determine org Stripe status by fetching status API once on page load or from a shared context
    - On click: call existing `POST /api/v1/payments/stripe/create-link` with invoice ID
    - On success: display payment URL with copy-to-clipboard, email, and SMS options
    - Hide button when org has no connected account
    - Use `?.` and `?? []` / `?? 0` on all API response property access
    - _Requirements: 4.1, 4.2, 4.4, 4.5_

  - [x] 8.2 Add online payment badge to invoice list page
    - File: `frontend/src/pages/invoices/InvoiceList.tsx` (or equivalent)
    - Show a small badge/icon next to invoices where `has_stripe_payment` is true (from enhanced list response in task 3.2)
    - Use a recognisable icon (e.g., credit card or Stripe logo) with tooltip "Paid online"
    - _Requirements: 8.1_

  - [x] 8.3 Distinguish payment methods in invoice payment history
    - In the invoice detail payment history section, show "Cash" or "Stripe" label per payment entry based on `method` field
    - _Requirements: 8.2_

- [x] 9. Add conditional Pay Now button to customer portal
  - [x] 9.1 Update portal invoice page to conditionally show "Pay Now" button
    - File: `frontend/src/pages/portal/PortalInvoices.tsx` (or equivalent)
    - Only show "Pay Now" when `org_has_stripe_connect` is true (from enhanced portal response in task 3.1)
    - Only show for invoices with status `issued`, `partially_paid`, or `overdue`
    - Existing `POST /portal/{token}/pay/{invoice_id}` flow is already implemented — this wires the conditional display
    - Use `?.` and `?? false` on `org_has_stripe_connect` access
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 10. Checkpoint — Frontend integration complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. End-to-end test script
  - [x] 11.1 Create `scripts/test_online_payments_e2e.py`
    - Follow feature-testing-workflow steering pattern (httpx, asyncio, ok/fail helpers)
    - Login as org_admin
    - GET status → verify "not connected" response shape
    - POST initiate connect → verify `authorize_url` returned
    - Simulate callback with mocked Stripe response → verify org updated with `stripe_connect_account_id`
    - GET status → verify "connected" with masked ID (last 4 chars only, full ID not present)
    - POST create payment link for an issued invoice → verify URL returned
    - Simulate webhook `checkout.session.completed` → verify payment recorded, invoice status updated
    - Simulate duplicate webhook → verify idempotent (no duplicate payment created)
    - POST disconnect → verify account cleared
    - GET status → verify "not connected"
    - OWASP A1: disconnect with salesperson token → expect 403
    - OWASP A1: status with no token → expect 401
    - OWASP A2: verify response never contains full Stripe account ID or secret keys
    - OWASP A3: send SQL injection payload in disconnect body → expect no error
    - OWASP A8: verify audit log created for disconnect action
    - Clean up all test data after tests
    - _Requirements: 1.6, 1.7, 2.2, 2.5, 3.2, 3.4, 4.2, 6.1, 6.2, 6.6_

- [x] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The backend uses Python/FastAPI; the frontend uses TypeScript/React
- All frontend API calls must follow the safe-api-consumption steering patterns (optional chaining, nullish coalescing, AbortController cleanup, typed generics)
- Most backend infrastructure already exists — the OAuth flow, payment link generation, webhook handling, and portal payment are all implemented
- No database migrations are needed — `stripe_connect_account_id` already exists on `organisations`, and `payments` table already has `method` and `stripe_payment_intent_id`
- Property tests use Hypothesis (already in project dependencies) and are placed in `tests/properties/test_stripe_connect_properties.py`
- Checkpoints ensure incremental validation at backend, frontend settings, and full integration milestones
