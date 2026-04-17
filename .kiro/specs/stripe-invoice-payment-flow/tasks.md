# Implementation Plan: Stripe Invoice Payment Flow

## Overview

This plan replaces the existing Stripe hosted Checkout flow for invoice payments with a custom payment page using Stripe Elements. The implementation covers: a new `payment_tokens` table and two new columns on `invoices` (Alembic migration), a `create_payment_intent()` Stripe integration function, a payment token service, a public payment page API, enhancements to the invoice issue and email flows, webhook handler extension for `payment_intent.succeeded`, a payment link regeneration endpoint, a React payment page with Stripe Elements, and frontend wiring for route registration and invoice detail actions.

The backend is Python/FastAPI; the frontend is TypeScript/React. Property tests use Hypothesis. E2E tests follow the `scripts/test_*_e2e.py` pattern.

## Tasks

- [x] 1. Database migration — payment_tokens table and invoice columns
  - [x] 1.1 Create Alembic migration adding `payment_tokens` table and new `invoices` columns
    - Create a single migration file in `alembic/versions/` (revision 0140)
    - Add `payment_tokens` table: `id` (UUID PK), `token` (VARCHAR(64) UNIQUE INDEX), `invoice_id` (UUID FK → invoices.id ON DELETE CASCADE), `org_id` (UUID FK → organisations.id), `expires_at` (TIMESTAMPTZ NOT NULL), `is_active` (BOOLEAN NOT NULL DEFAULT TRUE), `created_at` (TIMESTAMPTZ NOT NULL DEFAULT now())
    - Add `stripe_payment_intent_id` (VARCHAR(255) NULLABLE) column on `invoices`
    - Add `payment_page_url` (VARCHAR(500) NULLABLE) column on `invoices`
    - Use `IF NOT EXISTS` for the table creation where possible
    - _Requirements: 1.2, 3.1_

  - [x] 1.2 Run migration in the container
    - Execute: `docker compose exec app alembic upgrade head`
    - Verify output shows "Running upgrade 0139 -> 0140"
    - _Requirements: 1.2, 3.1_

  - [x] 1.3 Add `PaymentToken` SQLAlchemy model in `app/modules/payments/models.py`
    - Define `PaymentToken(Base)` with `__tablename__ = "payment_tokens"` and all columns matching the migration
    - Add relationships: `invoice = relationship("Invoice", backref="payment_tokens")`, `organisation = relationship("Organisation", backref="payment_tokens")`
    - Token format: `secrets.token_urlsafe(48)` (~64 chars)
    - _Requirements: 3.1, 3.6_

  - [x] 1.4 Add `stripe_payment_intent_id` and `payment_page_url` mapped columns to the `Invoice` model in `app/modules/invoices/models.py`
    - `stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)`
    - `payment_page_url: Mapped[str | None] = mapped_column(String(500), nullable=True)`
    - _Requirements: 1.2_

- [x] 2. Backend — Stripe PaymentIntent creation and payment token service
  - [x] 2.1 Implement `create_payment_intent()` in `app/integrations/stripe_connect.py`
    - New async function separate from existing `create_payment_link()` (which creates Checkout Sessions)
    - Parameters: `amount: int`, `currency: str`, `invoice_id: str`, `stripe_account_id: str`, `application_fee_amount: int | None = None`
    - POST to `https://api.stripe.com/v1/payment_intents` with `Stripe-Account` header
    - Include `metadata[invoice_id]` and `metadata[platform]=workshoppro_nz`
    - Include `application_fee_amount` when provided and > 0
    - Return `{"payment_intent_id": "pi_...", "client_secret": "pi_..._secret_..."}`
    - _Requirements: 1.1, 1.3, 1.4, 1.6_

  - [x] 2.2 Create `app/modules/payments/token_service.py` with `generate_payment_token()` and `validate_payment_token()`
    - `generate_payment_token(db, *, org_id, invoice_id) -> tuple[str, str]`: deactivate existing active tokens for the invoice, generate token via `secrets.token_urlsafe(48)`, set expiry to 72h, insert `PaymentToken`, build URL `{frontend_base_url}/pay/{token}`, return `(token, url)`
    - `validate_payment_token(db, *, token) -> PaymentToken | None`: query by token + `is_active=True`, return None if not found, raise `ValueError("expired")` if `expires_at < now()`, return token record if valid
    - Use `db.flush()` + `await db.refresh()` after insert
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 2.3 Write property test for PaymentIntent creation correctness (Property 1)
    - **Property 1: PaymentIntent creation correctness**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
    - Test file: `tests/properties/test_stripe_invoice_payment_properties.py`
    - Use Hypothesis: `st.decimals` for balance_due, `st.sampled_from(["nzd", "aud", "usd"])` for currency, `st.uuids()` for invoice IDs
    - Assert: `amount == int(balance_due * 100)`, `currency` matches lowercased, `metadata[invoice_id]` matches
    - Minimum 100 iterations (`@settings(max_examples=100)`)

  - [x] 2.4 Write property test for payment token generation (Property 2)
    - **Property 2: Payment token generation produces unique, secure tokens with correct expiry**
    - **Validates: Requirements 3.1, 3.2, 3.6**
    - Test file: `tests/properties/test_stripe_invoice_payment_properties.py`
    - Use Hypothesis: `st.uuids()` for invoice/org IDs, `st.integers(min_value=2, max_value=20)` for batch sizes
    - Assert: token length ≥ 32, `expires_at` is exactly 72h after `created_at`, N tokens for different invoices are all distinct
    - Minimum 100 iterations

- [x] 3. Backend — Public payment page API and Pydantic schemas
  - [x] 3.1 Add `PaymentPageResponse` and `PaymentPageLineItem` Pydantic schemas in `app/modules/payments/schemas.py`
    - `PaymentPageResponse`: `org_name`, `org_logo_url`, `org_primary_colour`, `invoice_number`, `issue_date`, `due_date`, `currency`, `line_items`, `subtotal`, `gst_amount`, `total`, `amount_paid`, `balance_due`, `status`, `client_secret`, `connected_account_id`, `publishable_key`, `is_paid`, `is_payable`, `error_message`
    - `PaymentPageLineItem`: `description`, `quantity`, `unit_price`, `line_total`
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 3.2 Create `app/modules/payments/public_router.py` with `GET /api/v1/public/pay/{token}` endpoint
    - Public endpoint (no auth required — `/api/v1/public/` is already in `PUBLIC_PREFIXES`)
    - Validate token via `validate_payment_token()`; return 404 for invalid, 410 for expired
    - Fetch invoice with line items, fetch org for branding (name, logo, primary colour)
    - If invoice is "paid" → return with `is_paid=True`, no `client_secret`
    - If invoice is "voided" or "draft" → return with `is_payable=False`, `error_message`
    - If payable → return full data with `client_secret`, `connected_account_id`, `publishable_key`
    - Do NOT return `sk_live_*`, `sk_test_*`, `whsec_*`, or internal user IDs
    - Rate limit: 20 requests/minute per IP (add to rate limiter config)
    - _Requirements: 3.3, 3.4, 3.5, 6.1, 6.2, 6.3, 6.4, 6.5, 9.3, 9.4_

  - [x] 3.3 Register the public router in the FastAPI app
    - Import `public_router` and include it with prefix `/api/v1/public` in the app setup
    - _Requirements: 6.1_

  - [x] 3.4 Write property test for valid token returning correct invoice data (Property 4)
    - **Property 4: Valid payment token returns correct invoice data and client secret**
    - **Validates: Requirements 3.3, 6.1**
    - Test file: `tests/properties/test_stripe_invoice_payment_properties.py`
    - Assert: `invoice_number` matches, `balance_due` matches, `client_secret` non-null, `connected_account_id` non-null, `is_payable` is true
    - Minimum 100 iterations

  - [x] 3.5 Write property test for no sensitive data leakage (Property 5)
    - **Property 5: Payment page response never leaks sensitive data**
    - **Validates: Requirements 6.2, 9.4**
    - Test file: `tests/properties/test_stripe_invoice_payment_properties.py`
    - Assert: serialized JSON never contains `sk_live_`, `sk_test_`, `whsec_`, or full `acct_` IDs > 30 chars
    - Minimum 100 iterations

- [x] 4. Backend — Enhance invoice issue flow and email
  - [x] 4.1 Auto-generate PaymentIntent on invoice issue with Stripe gateway
    - In `app/modules/invoices/service.py`, after an invoice is issued with `payment_gateway == "stripe"` in `invoice_data_json`:
    - Check org has `stripe_connect_account_id` — skip if not (log warning)
    - Calculate amount in cents: `int(invoice.balance_due * 100)`
    - Calculate application fee via `get_application_fee_percent()` if configured
    - Call `create_payment_intent()` with Connected Account
    - Call `generate_payment_token()` to get token + URL
    - Store `stripe_payment_intent_id` and `payment_page_url` on the invoice record
    - `db.flush()` + `await db.refresh(invoice)`
    - If PaymentIntent creation fails, still issue the invoice and send email without payment link (log error)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [x] 4.2 Inject payment link into invoice email
    - In `app/modules/invoices/service.py` → `email_invoice()`:
    - After invoice is issued and has a non-null `payment_page_url`, add a line to the plain-text email body: `Pay online: {payment_page_url}`
    - When `payment_page_url` is None, send email in current format unchanged
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 4.3 Write property test for email payment link inclusion (Property 3)
    - **Property 3: Invoice email includes payment link when present**
    - **Validates: Requirements 2.1, 2.3**
    - Test file: `tests/properties/test_stripe_invoice_payment_properties.py`
    - Assert: when `payment_page_url` is non-null, email body contains the URL; when null, email body does not contain "/pay/"
    - Minimum 100 iterations

- [x] 5. Checkpoint — Core backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Backend — Webhook handler extension and payment link regeneration
  - [x] 6.1 Extend webhook handler for `payment_intent.succeeded`
    - In `app/modules/payments/service.py` → `handle_stripe_webhook()`:
    - Change the event type check to accept both `checkout.session.completed` and `payment_intent.succeeded`
    - For `payment_intent.succeeded`: extract `invoice_id` from `metadata.invoice_id`, `amount` from `amount_received` (already in cents), `stripe_payment_intent` from `id`
    - The rest of the flow (idempotency check, payment creation, balance update, receipt email) is identical to the existing handler
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [x] 6.2 Implement `POST /api/v1/payments/invoice/{invoice_id}/regenerate-payment-link` endpoint
    - File: `app/modules/payments/router.py`
    - Auth: `require_role("org_admin", "salesperson")`
    - Validate invoice exists, belongs to org, is payable (issued/partially_paid/overdue)
    - Validate org has Connected Account
    - Create new PaymentIntent via `create_payment_intent()`
    - Generate new payment token via `generate_payment_token()` (invalidates old tokens)
    - Update invoice's `stripe_payment_intent_id` and `payment_page_url`
    - `db.flush()` + `await db.refresh(invoice)`
    - Return `{ payment_page_url, invoice_id }`
    - Add `RegeneratePaymentLinkResponse` schema in `app/modules/payments/schemas.py`
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 6.3 Write property test for token regeneration (Property 6)
    - **Property 6: Token regeneration invalidates all previous tokens**
    - **Validates: Requirements 8.2, 8.4**
    - Test file: `tests/properties/test_stripe_invoice_payment_properties.py`
    - Assert: after regeneration, all previous tokens have `is_active=False`, exactly one new active token exists, invoice's `stripe_payment_intent_id` and `payment_page_url` are updated to new values
    - Minimum 100 iterations

- [x] 7. Checkpoint — Full backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Frontend — Custom payment page with Stripe Elements
  - [x] 8.1 Create `frontend/src/pages/public/InvoicePaymentPage.tsx`
    - Public page component at route `/pay/:token`
    - On mount: `GET /api/v1/public/pay/{token}` with AbortController cleanup
    - Handle error states: 404 → "Invalid payment link", 410 → "This payment link has expired…", network error → generic error
    - Handle invoice states: `is_paid` → "This invoice has been paid" message, `!is_payable` → appropriate message with `error_message`
    - When payable: initialise `loadStripe(publishableKey, { stripeAccount: connectedAccountId })`, render `<Elements>` with `clientSecret`
    - Desktop layout: two-column (invoice preview left, Stripe form right)
    - Mobile layout (< 768px): stacked (invoice preview top, payment form below)
    - Follow `PaymentStep.tsx` pattern for Stripe Elements integration
    - Use `?.` and `?? []` / `?? 0` on all API response property access (safe-api-consumption patterns)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 9.1, 9.2_

  - [x] 8.2 Implement the payment form sub-component within `InvoicePaymentPage.tsx`
    - Show amount to be charged and "Pay Now" button
    - On submit: `stripe.confirmPayment({ elements, confirmParams: { return_url } })` or `stripe.confirmCardPayment()`
    - On success: show confirmation with amount paid and invoice number
    - On failure: show Stripe error message, allow retry
    - Disable button while processing (prevent double submission)
    - _Requirements: 5.3, 5.4, 5.5, 5.6, 5.7_

  - [x] 8.3 Implement the invoice preview section within `InvoicePaymentPage.tsx`
    - Display: org name + logo (if configured) + primary colour accent
    - Invoice number, issue date, due date
    - Line items table: description, quantity, unit price, amount
    - Subtotal, GST, total, amount paid, balance due
    - Use `?.` and `?? 0` for all numeric formatting
    - _Requirements: 4.1, 4.2_

- [x] 9. Frontend — Route registration and invoice detail enhancement
  - [x] 9.1 Register `/pay/:token` public route in `frontend/src/App.tsx`
    - Add outside the auth wrapper, alongside the existing `/portal/:token` route
    - Lazy-load `InvoicePaymentPage` to keep Stripe bundles out of the main chunk
    - Wrap with `SafePage` component following existing pattern
    - _Requirements: 5.1_

  - [x] 9.2 Add "Regenerate Payment Link" action to `frontend/src/pages/invoices/InvoiceDetail.tsx`
    - Show button when: invoice status is `issued`, `partially_paid`, or `overdue` AND org has Connected Account (from existing `stripeStatus`)
    - On click: `POST /api/v1/payments/invoice/{id}/regenerate-payment-link`
    - On success: show the new URL with copy-to-clipboard option
    - Use `?.` and `?? ''` on response property access
    - _Requirements: 8.1, 8.2, 8.3_

- [x] 10. Checkpoint — Frontend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. End-to-end test script
  - [x] 11.1 Create `scripts/test_stripe_invoice_payment_e2e.py`
    - Follow feature-testing-workflow steering pattern (httpx, asyncio, ok/fail helpers)
    - Login as org_admin
    - Create invoice with `payment_gateway: "stripe"`, issue via "Save and Send"
    - Verify invoice has `stripe_payment_intent_id` and `payment_page_url` set
    - GET public payment page API with token from URL → verify response shape
    - Verify response contains invoice preview data, `client_secret`, `connected_account_id`
    - Verify response does NOT contain `sk_live_`, `sk_test_`, `whsec_`
    - Simulate `payment_intent.succeeded` webhook → verify payment recorded, invoice status updated
    - Simulate duplicate webhook → verify idempotent (no duplicate payment)
    - GET payment page again → verify `is_paid=True`, no `client_secret`
    - Create another invoice, issue with stripe gateway
    - Regenerate payment link → verify new URL, old token invalid
    - GET old token → verify 404
    - GET new token → verify valid response
    - **Security checks:**
      - OWASP A1: GET payment page with no token → 404
      - OWASP A1: POST regenerate with salesperson token for another org → 403
      - OWASP A2: Verify response never contains `sk_live_`, `sk_test_`, `whsec_`
      - OWASP A3: Send SQL injection payload as token → no error, 404
      - OWASP A4: Verify rate limiting on payment page endpoint (21st request → 429)
      - OWASP A8: Verify audit log created for payment link generation
    - Clean up test data
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 3.1, 3.2, 3.3, 3.4, 3.5, 6.1, 6.2, 7.1, 7.4, 8.2, 8.4, 9.3, 9.4_

- [x] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at core backend, full backend, frontend, and integration milestones
- Property tests validate the 6 correctness properties defined in the design document; properties already covered by the `stripe-connect-online-payments` spec (P4 webhook balance, P6 idempotency, P7 application fee) are NOT duplicated
- The `get_db_session` dependency uses `session.begin()` which auto-commits — use `flush()` not `commit()` in services; after `db.flush()`, always `await db.refresh(obj)` before returning ORM objects for Pydantic serialization
- The auth middleware already has `/api/v1/public/` in `PUBLIC_PREFIXES` — the payment page API goes there
- Stripe Elements packages (`@stripe/react-stripe-js`, `@stripe/stripe-js`) are already in the frontend dependencies from the signup flow
- All frontend API calls must follow safe-api-consumption patterns (`?.`, `?? []`, `?? 0`, AbortController cleanup, typed generics)
- E2E test script goes in `scripts/` following the feature-testing-workflow steering pattern
