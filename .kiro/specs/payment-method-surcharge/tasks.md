# Implementation Plan: Payment Method Surcharge

## Overview

This plan adds the ability for organisation admins to pass Stripe processing fees to customers at payment time. The implementation covers: a pure-function surcharge calculation engine, surcharge settings API endpoints, a PaymentIntent surcharge update endpoint, enhanced payment page response with surcharge config, an Alembic migration for surcharge columns on `payments`, enhanced webhook/confirm handlers to extract surcharge metadata, receipt email surcharge breakdown, a surcharge settings UI section in Online Payments settings, and dynamic surcharge display on the public payment page with PaymentElement `onChange` detection.

The backend is Python 3.11 / FastAPI / SQLAlchemy async. The frontend is TypeScript / React 18 / Tailwind CSS. Property tests use Hypothesis with `@settings(max_examples=100)`. E2E tests follow the `scripts/test_*_e2e.py` pattern.

## Tasks

- [x] 1. Surcharge calculation engine — pure functions
  - [x] 1.1 Create `app/modules/payments/surcharge.py` with all pure calculation functions
    - Implement `calculate_surcharge(balance_due, percentage, fixed)` using `Decimal` and `ROUND_HALF_EVEN`
    - Implement `get_surcharge_for_method(balance_due, payment_method_type, surcharge_rates)` returning `Decimal("0.00")` for disabled/unknown methods
    - Implement `validate_surcharge_rates(rates)` returning list of error messages for out-of-bounds values (percentage > 10% or < 0, fixed > $5 or < 0)
    - Implement `serialise_rates(rates)` converting to JSON-safe format with string decimals (2dp)
    - Implement `deserialise_rates(raw, defaults)` with fallback to defaults on malformed entries + warning log
    - Define `DEFAULT_SURCHARGE_RATES` constant with NZ Stripe Connect defaults: card 2.9%+$0.30, Afterpay 6%+$0.30, Klarna 5.99%+$0, bank transfer 1%+$0
    - Define `MAX_PERCENTAGE = Decimal("10.00")` and `MAX_FIXED = Decimal("5.00")` validation limits
    - _Requirements: 3.2, 3.4, 3.5, 9.1, 9.2, 9.3, 9.4_

  - [x] 1.2 Write property test: Surcharge calculation correctness (Property 1)
    - **Property 1: Surcharge calculation correctness**
    - **Validates: Requirements 3.2, 3.4, 3.5, 5.3**
    - Test file: `tests/properties/test_surcharge_properties.py`
    - Use Hypothesis: `st.decimals(min_value=Decimal("0.01"), max_value=Decimal("999999.99"), places=2)` for balance_due, `st.decimals(min_value=Decimal("0"), max_value=Decimal("10"), places=2)` for percentage, `st.decimals(min_value=Decimal("0"), max_value=Decimal("5"), places=2)` for fixed
    - Assert: result equals `(balance_due * percentage / 100) + fixed` rounded to 2dp with ROUND_HALF_EVEN, result ≥ 0, no compounding (applying surcharge to `balance_due + surcharge` produces a larger result)
    - `@settings(max_examples=100, deadline=None)`

  - [x] 1.3 Write property test: Surcharge rate serialisation round-trip (Property 2)
    - **Property 2: Round-trip consistency**
    - **Validates: Requirements 9.1, 9.2, 9.3**
    - Test file: `tests/properties/test_surcharge_properties.py`
    - Use Hypothesis: `st.dictionaries` with `st.sampled_from(["card","afterpay_clearpay","klarna","bank_transfer"])` keys, `st.fixed_dictionaries({"percentage": st.decimals(...), "fixed": st.decimals(...), "enabled": st.booleans()})` values
    - Assert: `serialise_rates(deserialise_rates(serialise_rates(rates)))` equals `serialise_rates(rates)` — no drift
    - `@settings(max_examples=100, deadline=None)`

  - [x] 1.4 Write property test: Surcharge rate validation rejects out-of-bounds (Property 3)
    - **Property 3: Validation rejects out-of-bounds values**
    - **Validates: Requirements 2.2, 2.6, 2.7**
    - Test file: `tests/properties/test_surcharge_properties.py`
    - Use Hypothesis: `st.decimals(min_value=Decimal("-5"), max_value=Decimal("20"), places=2)` for percentage and fixed
    - Assert: out-of-bounds values produce non-empty error list; in-bounds values produce empty list
    - `@settings(max_examples=100, deadline=None)`

  - [x] 1.5 Write property test: Disabled method produces zero surcharge (Property 5)
    - **Property 5: Disabled method zero surcharge**
    - **Validates: Requirements 1.4, 3.3**
    - Test file: `tests/properties/test_surcharge_properties.py`
    - Use Hypothesis: `st.sampled_from(["card","afterpay_clearpay","klarna","bank_transfer"])` for method, `st.decimals(...)` for balance_due
    - Assert: when `enabled=False` or method not in rates, `get_surcharge_for_method()` returns `Decimal("0.00")`
    - `@settings(max_examples=100, deadline=None)`

  - [x] 1.6 Write property test: Malformed rate deserialisation falls back to defaults (Property 6)
    - **Property 6: Malformed rate fallback**
    - **Validates: Requirements 9.4**
    - Test file: `tests/properties/test_surcharge_properties.py`
    - Use Hypothesis: `st.one_of(st.none(), st.integers(), st.text(), st.dictionaries(...))` for malformed rate values
    - Assert: `deserialise_rates()` never raises, returns valid Decimal percentage and fixed values matching defaults
    - `@settings(max_examples=100, deadline=None)`

  - [x] 1.7 Write property test: Surcharge addition produces exact total (Property 7)
    - **Property 7: Surcharge addition exactness**
    - **Validates: Requirements 3.5, 4.2**
    - Test file: `tests/properties/test_surcharge_properties.py`
    - Use Hypothesis: `st.decimals(min_value=Decimal("0.01"), max_value=Decimal("999999.99"), places=2)` for balance_due, valid rates
    - Assert: `int((balance_due + surcharge) * 100) == int(balance_due * 100) + int(surcharge * 100)` — no rounding drift
    - `@settings(max_examples=100, deadline=None)`

  - [x] 1.8 Write property test: Rate-exceeds-cost warning threshold (Property 8)
    - **Property 8: Rate warning threshold**
    - **Validates: Requirements 8.2**
    - Test file: `tests/properties/test_surcharge_properties.py`
    - Use Hypothesis: `st.decimals(min_value=Decimal("0"), max_value=Decimal("10"), places=2)` for configured and default rates
    - Assert: warning triggered iff `configured_rate - default_rate > 0.50`
    - `@settings(max_examples=100, deadline=None)`

- [x] 2. Database migration — surcharge columns on payments table
  - [x] 2.1 Create Alembic migration adding surcharge columns to `payments`
    - Create migration file in `alembic/versions/` (revision 0150, depends on 0149)
    - Add `surcharge_amount` column: `Numeric(12, 2)`, NOT NULL, `server_default='0.00'`
    - Add `payment_method_type` column: `String(50)`, NULLABLE
    - No new tables needed — surcharge config lives in existing `org.settings` JSONB
    - _Requirements: 6.1, 6.2_

  - [x] 2.2 Run migration in the container
    - Execute: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head`
    - Verify output shows "Running upgrade 0149 -> 0150"
    - _Requirements: 6.1, 6.2_

  - [x] 2.3 Add `surcharge_amount` and `payment_method_type` mapped columns to the `Payment` model in `app/modules/payments/models.py`
    - `surcharge_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0.00")`
    - `payment_method_type: Mapped[str | None] = mapped_column(String(50), nullable=True)`
    - _Requirements: 6.1, 6.2, 6.3_

- [x] 3. Backend — Surcharge settings API endpoints
  - [x] 3.1 Add Pydantic schemas for surcharge settings in `app/modules/payments/schemas.py`
    - `SurchargeRateConfig`: `percentage: str`, `fixed: str`, `enabled: bool`
    - `SurchargeSettingsResponse`: `surcharge_enabled: bool`, `surcharge_acknowledged: bool`, `surcharge_rates: dict[str, SurchargeRateConfig]`
    - `UpdateSurchargeSettingsRequest`: `surcharge_enabled: bool`, `surcharge_acknowledged: bool`, `surcharge_rates: dict[str, SurchargeRateConfig]`
    - `SurchargeRateInfo`: `percentage: str`, `fixed: str`, `enabled: bool` (for payment page response)
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.4_

  - [x] 3.2 Implement `GET /api/v1/payments/online-payments/surcharge-settings` in `app/modules/payments/router.py`
    - Auth: `require_role("org_admin")`
    - Read `surcharge_enabled`, `surcharge_acknowledged`, and `surcharge_rates` from `org.settings` JSONB
    - If no config exists, return defaults with `surcharge_enabled: false` and `DEFAULT_SURCHARGE_RATES`
    - Return `SurchargeSettingsResponse`
    - _Requirements: 1.5, 2.3_

  - [x] 3.3 Implement `PUT /api/v1/payments/online-payments/surcharge-settings` in `app/modules/payments/router.py`
    - Auth: `require_role("org_admin")`
    - Validate rates via `validate_surcharge_rates()` — return 422 on invalid
    - If enabling for first time and `surcharge_acknowledged` is false, return 400 with "Please acknowledge the NZ compliance notice"
    - Serialise rates via `serialise_rates()` and save to `org.settings` JSONB
    - Write audit log: `org.surcharge_settings_updated`
    - Use `db.flush()` + `await db.refresh(org)` before returning
    - Return `SurchargeSettingsResponse`
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.4, 2.5, 2.6, 2.7, 8.4_

- [x] 4. Checkpoint — Surcharge engine, migration, and settings API complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Backend — PaymentIntent surcharge update endpoint and enhanced payment page
  - [x] 5.1 Add `UpdateSurchargeRequest` and `UpdateSurchargeResponse` schemas in `app/modules/payments/schemas.py`
    - `UpdateSurchargeRequest`: `payment_method_type: str`
    - `UpdateSurchargeResponse`: `surcharge_amount: str`, `total_amount: str`, `payment_intent_updated: bool`
    - _Requirements: 5.1, 5.2_

  - [x] 5.2 Implement `POST /api/v1/public/pay/{token}/update-surcharge` in `app/modules/payments/public_router.py`
    - Public endpoint (no auth — secured by payment token)
    - Validate payment token (same as `get_payment_page`); return 404 for invalid, 410 for expired
    - Fetch invoice and org; read surcharge config from `org.settings`
    - Compute surcharge server-side via `get_surcharge_for_method()` — frontend sends only `payment_method_type`, NOT the surcharge amount
    - If surcharging disabled or method not surcharged → surcharge = 0
    - Calculate new PI amount in cents: `int((balance_due + surcharge) * 100)`
    - Update PaymentIntent via Stripe API with `amount`, `metadata[surcharge_amount]`, `metadata[surcharge_method]`, `metadata[original_amount]`
    - Use `get_stripe_secret_key()` for Stripe API auth (DB-backed, cached)
    - Rate limited (shares payment page rate limit: 20 req/min per IP)
    - Return `UpdateSurchargeResponse`
    - _Requirements: 5.1, 5.2, 5.3, 5.5_

  - [x] 5.3 Enhance `get_payment_page()` in `app/modules/payments/public_router.py` to include surcharge config
    - Add `surcharge_enabled` and `surcharge_rates` fields to `PaymentPageResponse`
    - Read `org.settings["surcharge_enabled"]` and `org.settings["surcharge_rates"]`
    - When surcharging enabled, include rates in response; when disabled, return `surcharge_enabled: false` with empty rates
    - Handle malformed rates gracefully — fall back to defaults via `deserialise_rates()`, log warning
    - _Requirements: 3.1, 1.4, 1.5_

- [x] 6. Backend — Enhanced payment recording and receipt email
  - [x] 6.1 Enhance `handle_stripe_webhook()` in `app/modules/payments/service.py` to extract surcharge
    - Extract `surcharge_amount`, `surcharge_method`, and `original_amount` from PaymentIntent metadata
    - Use `original_amount` from metadata for the invoice payment amount; fall back to `(amount_cents / 100) - surcharge` if missing
    - Create `Payment` record with `surcharge_amount` and `payment_method_type` populated
    - Invoice `amount_paid` increases by invoice amount only (excluding surcharge)
    - Handle missing surcharge metadata gracefully — default to `Decimal("0")`
    - _Requirements: 6.1, 6.3, 6.4_

  - [x] 6.2 Enhance `confirm_payment()` in `app/modules/payments/public_router.py` to pass surcharge data
    - Same surcharge extraction logic as webhook — PI metadata contains `surcharge_amount` and `surcharge_method`
    - Pass surcharge info through to `handle_stripe_webhook()` or the shared payment recording logic
    - _Requirements: 6.1, 6.4_

  - [x] 6.3 Enhance `_send_receipt_email()` in `app/modules/payments/service.py` for surcharge breakdown
    - Update function signature to accept `surcharge_amount: Decimal` and `payment_method_type: str | None`
    - When `surcharge_amount > 0`: show invoice amount, surcharge line with method name, and total paid as separate items
    - When `surcharge_amount == 0`: use existing email format unchanged
    - Add `_payment_method_display_name()` helper: card → "Credit/Debit Card", afterpay_clearpay → "Afterpay", klarna → "Klarna", bank_transfer → "Bank Transfer"
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 6.4 Write property test: Payment amount invariant (Property 4)
    - **Property 4: Surcharge never contaminates invoice balance**
    - **Validates: Requirements 6.1, 6.3**
    - Test file: `tests/properties/test_surcharge_properties.py`
    - Use Hypothesis: `st.decimals(...)` for balance_due and surcharge, `st.uuids()` for IDs
    - Assert: `Payment.amount` equals invoice portion only, `Payment.amount + Payment.surcharge_amount` equals total charged, invoice `amount_paid` increases by `Payment.amount` only
    - `@settings(max_examples=100, deadline=None)`

- [x] 7. Checkpoint — Full backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Frontend — Surcharge settings section in Online Payments
  - [x] 8.1 Create `SurchargeSettingsSection` component in `frontend/src/pages/settings/OnlinePaymentsSettings.tsx`
    - Render inside the "Connected" state block, after `PaymentMethodsSection` and before `PayoutSettingsSection`
    - On mount: `GET /api/v1/payments/online-payments/surcharge-settings` with AbortController cleanup
    - Display NZ compliance notice: "NZ law requires surcharges to not exceed actual merchant processing costs and to be disclosed before payment"
    - Master toggle: "Pass processing fees to customers" — maps to `surcharge_enabled`
    - When enabled: show editable rate table with columns: Payment Method, Percentage (%), Fixed ($), Enabled toggle
    - Pre-populate with defaults from API response (card 2.9%+$0.30, Afterpay 6%+$0.30, Klarna 5.99%+$0, bank transfer 1%+$0)
    - Input validation: percentage 0–10%, fixed $0–$5; show inline validation errors
    - Rate-exceeds-cost warning: if configured percentage exceeds default Stripe rate by > 0.5pp, show amber warning
    - Acknowledgement checkbox: "I acknowledge that surcharges must comply with NZ consumer law" — required on first enable
    - Save button: `PUT /api/v1/payments/online-payments/surcharge-settings`; Cancel button resets to last saved state
    - Use `?.` and `?? []` / `?? 0` on all API response access; typed generics on API calls
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 8.1, 8.2, 8.4_

- [x] 9. Frontend — Dynamic surcharge display on payment page
  - [x] 9.1 Enhance `PaymentForm` in `frontend/src/pages/public/InvoicePaymentPage.tsx` for surcharge
    - Add state: `selectedMethod`, `surchargeAmount`, `updatingPI`
    - Add `onChange` handler to `<PaymentElement>`: extract `event.value?.type` (e.g. "card", "afterpay_clearpay", "klarna")
    - On method change: compute surcharge locally for instant display using `Math.round((balanceDue * pct / 100 + fixed) * 100) / 100`
    - Call `POST /api/v1/public/pay/{token}/update-surcharge` with `{ payment_method_type }` to update PaymentIntent
    - Use AbortController to cancel in-flight requests when method changes again
    - Handle update failure: show error message, prevent payment confirmation
    - Use `?.` and `?? 0` on surcharge rate access from `PaymentPageData`
    - _Requirements: 3.1, 3.2, 3.3, 4.5, 5.1, 5.2, 5.4_

  - [x] 9.2 Add surcharge display to payment summary in `InvoicePaymentPage.tsx`
    - When surcharge > 0: show "Invoice balance", "Payment method surcharge ({method})", and "Total to pay" as separate line items
    - When surcharge == 0: show "Amount to pay" only
    - Show disclosure text: "A surcharge is applied to cover payment processing fees" when surcharge active
    - Disable Pay button while PI is updating (`updatingPI` state)
    - Update Pay button label to show total including surcharge: `Pay {formatCurrency(balanceDue + surchargeAmount, currency)}`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 8.3_

- [x] 10. Checkpoint — Frontend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. End-to-end test script
  - [x] 11.1 Create `scripts/test_surcharge_e2e.py`
    - Follow feature-testing-workflow pattern (httpx, asyncio, ok/fail helpers)
    - Login as org_admin
    - GET surcharge settings → verify defaults returned with `surcharge_enabled: false`
    - PUT surcharge settings (enable, set rates, acknowledge) → verify saved correctly
    - Create and issue invoice with Stripe gateway
    - GET payment page → verify `surcharge_enabled: true` and `surcharge_rates` in response
    - POST update-surcharge with `payment_method_type: "card"` → verify surcharge amount and PI updated
    - POST update-surcharge with `payment_method_type: "klarna"` → verify different surcharge
    - POST update-surcharge with disabled method → verify surcharge = 0
    - Simulate webhook with surcharge metadata → verify Payment record has `surcharge_amount` and `payment_method_type`
    - Verify invoice `amount_paid` increased by invoice amount only (not surcharge)
    - Verify receipt email contains surcharge breakdown
    - PUT surcharge settings with `surcharge_enabled: false` → verify disabled
    - GET payment page → verify `surcharge_enabled: false`
    - **Security checks:**
      - OWASP A1: GET surcharge settings without auth → 401
      - OWASP A1: POST update-surcharge with invalid token → 404
      - OWASP A2: Verify surcharge update response never contains `sk_live_`, `sk_test_`, `whsec_`
      - OWASP A3: Send SQL injection payload as payment_method_type → no error, handled gracefully
      - OWASP A4: Verify rate limiting on surcharge update endpoint (21st request → 429)
      - OWASP A5: PUT surcharge settings with percentage > 10% → 422 rejected
    - Clean up test data
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.6, 3.1, 3.2, 3.3, 4.1, 5.1, 5.2, 5.3, 5.5, 6.1, 6.3, 6.4, 7.1, 7.2, 8.1, 8.4_

- [x] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at engine+migration, full backend, frontend, and integration milestones
- Property tests validate the 8 correctness properties defined in the design document
- The `get_db_session` dependency uses `session.begin()` which auto-commits — use `flush()` not `commit()` in services; after `db.flush()`, always `await db.refresh(obj)` before returning ORM objects
- Surcharge config lives in the existing `org.settings` JSONB column — no new tables needed for configuration
- The surcharge update endpoint is public (secured by payment token) — frontend sends only `payment_method_type`, backend computes surcharge server-side to prevent tampering
- Stripe API calls use `get_stripe_secret_key()` from DB (not env vars) per integration-credentials-architecture steering
- All frontend API calls must follow safe-api-consumption patterns (`?.`, `?? []`, `?? 0`, AbortController cleanup, typed generics)
- E2E test script goes in `scripts/` following the feature-testing-workflow pattern
- Alembic migration is revision 0150 (depends on 0149)
