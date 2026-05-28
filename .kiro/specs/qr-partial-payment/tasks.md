# Implementation Plan: QR Partial Payment

## Overview

Implements partial-amount QR payments by adding an optional `amount` field to the existing `POST /api/v1/payments/qr-session/existing` endpoint and an optional `amount_override` column on `payment_tokens`. The org user gets a small modal between the QR Payment button and the existing waiting popup that lets them pick Full (default) or Partial. The webhook handler is unchanged — it already records partial payments correctly via `metadata.original_amount`.

The implementation is split into:

- Database migration (1 task)
- Backend Python (4 tasks: schema, service, public router, audit log)
- Frontend React (4 tasks: modal component, InvoiceList wiring, InvoiceDetail wiring, public payment page banner)
- Tests (2 tasks: backend integration + property, frontend unit)
- Release artefacts (3 tasks: changelog, version bump, manual smoke test)

Existing behaviour is preserved when `amount` is omitted — every backend path remains backwards compatible.

## Scope and execution rules

- **Tests:** Only run the new tests added by this spec plus the existing payment-flow files they touch. Do **not** run the full repository test suite. Specific commands listed inline at each test task and consolidated under task 14.3.
- **Deployment target:** Dev environment only (`docker-compose.yml` + `docker-compose.dev.yml`, project `invoicing`, port 80, DB port 5434). **No Pi/PROD deployment, no standby deployment, no SSH/tar sync.**
- **Version bump:** Required (per project versioning discipline). Bump `pyproject.toml`, `app/__init__.py`, `frontend/package.json`, `mobile/package.json`, and add CHANGELOG entry.
- **Git:** Commit changes and `git push` to GitHub (`arshdeepromy/Orainvoice`, `main`) once tests pass and dev rebuild is verified. Do NOT trigger Pi PROD deploy or sync code to the Pi via tar+SSH.
- **Migration:** Apply to dev DB only (task 1.2). Pi PROD migration is out of scope for this spec.

## Tasks

- [ ] 1. Database migration for payment_tokens.amount_override
  - [x] 1.1 Create Alembic migration for the new column
    - First, verify the current head: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic heads` and `ls alembic/versions/ | sort | tail -1`. As of spec authoring (2026-05-26) the latest is `0192_b2b_fleet_portal_rls.py`, so the next revision is `0193`. If a newer migration has landed since, increment accordingly and update `down_revision` to match the actual head
    - Filename pattern: `YYYY_MM_DD_HHMM-XXXX_payment_tokens_amount_override.py` (matches existing project convention)
    - Add columns to `payment_tokens`:
      - `amount_override NUMERIC(12,2) NULL` with column comment "Partial-payment amount for the QR partial-payment flow. NULL means use invoice.balance_due (default behaviour)."
      - `last_pi_amount_cents BIGINT NULL` with column comment "Cached cents value of the PaymentIntent's last-known amount, used by create_qr_session_for_existing_invoice to make a same-amount-reuse decision without a synchronous Stripe API call. Refreshed on every successful PI create or update-surcharge call."
    - Use `op.add_column` (no batch needed — Postgres supports adding nullable columns without table rewrite)
    - Provide a clean `downgrade()` that drops both columns in reverse order
    - Idempotent style: existing rows automatically get NULL on upgrade, no data backfill required
    - _Requirements: 5.1, 6.1_
  - [x] 1.2 Apply the migration to the dev database immediately
    - Run: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head`
    - Verify the upgrade succeeded by reading the output ("Running upgrade 0192 -> 0193" or current head). No errors should appear
    - Verify the column exists: `docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "\\d payment_tokens"` and confirm both new columns are present and NULL
    - This step is **mandatory** per `database-migration-checklist.md`. Do not proceed past this task without applying and verifying the migration
    - _Requirements: 5.1, 6.1_

- [ ] 2. Add Stripe minimum charge constants and amount validation
  - [x] 2.1 Verify whether a minimum constant already exists, then add per-currency constants
    - Grep for existing constants: `grep -rn "STRIPE_MIN\\|MIN_AMOUNT\\|amount_too_small" app/` — confirmed at spec authoring (2026-05-26) that no such constant exists in the codebase
    - Add to `app/modules/payments/service.py` (or a new `app/modules/payments/constants.py` module if preferred):
      ```python
      # Stripe minimum charge amounts per currency.
      # Source: https://stripe.com/docs/currencies#minimum-and-maximum-charge-amounts
      # Per-currency dict so multi-currency invoicing (when introduced) does not
      # require a code change here — only an entry in this dict.
      STRIPE_MIN_BY_CURRENCY: dict[str, Decimal] = {
          "NZD": Decimal("0.50"),
          "AUD": Decimal("0.50"),
          "USD": Decimal("0.50"),
          "GBP": Decimal("0.30"),
          "EUR": Decimal("0.50"),
          "JPY": Decimal("50"),
      }
      DEFAULT_STRIPE_MIN = Decimal("0.50")  # fallback for unlisted currencies

      def stripe_min_for_currency(currency: str | None) -> Decimal:
          """Return the documented Stripe minimum charge for the given currency.

          Falls back to DEFAULT_STRIPE_MIN if the currency is not in the dict
          (defensive: better to refuse a sub-minimum charge than to assume).
          """
          if not currency:
              return DEFAULT_STRIPE_MIN
          return STRIPE_MIN_BY_CURRENCY.get(currency.upper(), DEFAULT_STRIPE_MIN)
      ```
    - Use `stripe_min_for_currency(invoice.currency)` in `create_qr_session_for_existing_invoice` rather than a hard-coded NZD value, so multi-currency support (future work) requires zero changes here
    - _Requirements: 3.3, 8.1, 8.2_

- [ ] 3. Extend the request schema
  - [x] 3.1 Add optional `amount` field to `QrSessionExistingInvoiceRequest` in `app/modules/payments/schemas.py`
    - Type `Decimal | None`, default `None`, `gt=Decimal("0")`
    - Field validator `_quantize_to_cents` that rejects values with more than 2 decimal places (raise `ValueError("Amount must have at most 2 decimal places")`) and quantizes valid values to `Decimal("0.01")` exponent
    - Docstring explaining backwards-compat semantics: omit → full balance; provide → partial
    - _Requirements: 3.1, 3.5, 3.6_

- [ ] 4. Update PaymentToken ORM model
  - [x] 4.1 Add `amount_override` Mapped column to `PaymentToken` in `app/modules/payments/models.py`
    - Type `Mapped[Decimal | None]`, `Numeric(12, 2)`, `nullable=True`
    - Column comment string matching the migration
    - No relationship changes
    - _Requirements: 6.1_

- [ ] 5. Extend generate_payment_token to accept amount_override
  - [x] 5.1 Add `amount_override: Decimal | None = None` parameter to `generate_payment_token` in `app/modules/payments/token_service.py`
    - Pass through to the `PaymentToken(...)` constructor
    - When None, the column is NULL on insert (default behaviour)
    - When provided, the column carries the partial amount
    - _Requirements: 6.1, 5.4_

- [ ] 5.5 Extend `create_payment_intent` to accept extra metadata (CRITICAL — the function does NOT currently accept this)
  - [x] 5.5.1 Add `extra_metadata: dict[str, str] | None = None` parameter to `create_payment_intent` in `app/integrations/stripe_connect.py:301`
    - When provided AND non-empty, append `metadata[KEY] = VALUE` form fields to the Stripe payload BEFORE the POST
    - Existing callers continue to work — the parameter is optional and defaults to None
    - This is the foundational change that lets us set `original_amount`, `is_partial_payment`, and `source: "kiosk_qr"` at PI creation time, instead of relying on the customer reaching `update-surcharge` for those fields to be populated
    - _Requirements: 4.3, 4.4_
  - [x] 5.5.2 Update the existing `create_qr_payment_session` (the create-new-invoice path at `app/modules/payments/service.py:1199`) to pass these baseline keys via `extra_metadata`:
    ```python
    extra_metadata={
        "source": "kiosk_qr",
        "original_amount": str(total),
        "is_partial_payment": "false",  # full payment for the new-invoice path
    }
    ```
    This closes the pre-existing detection-bug gap where `is_qr_payment` in the webhook was always False if the customer skipped `update-surcharge`. Forward-fix as part of this spec
    - _Requirements: 4.3, 4.4 (and webhook detection regression-fix)_

- [ ] 6. Refactor create_qr_session_for_existing_invoice for partial amounts
  - [x] 6.1 Add `partial_amount: Decimal | None = None` keyword argument
    - _Requirements: 3.1, 3.5_
  - [x] 6.2 Resolve `resolved_amount` and `is_partial` flag
    - When `partial_amount is None`: `resolved_amount = invoice.balance_due.quantize(Decimal("0.01"))`, `is_partial = False`
    - When `partial_amount is not None`: validate `stripe_min_for_currency(invoice.currency) <= partial_amount <= invoice.balance_due` (after quantize), raise `ValueError` with currency-aware friendly messages on violation; `resolved_amount = partial_amount.quantize(Decimal("0.01"))`, `is_partial = True`
    - _Requirements: 3.2, 3.3, 3.4, 3.6_
  - [x] 6.3 Narrow the reuse-branch guard
    - Move the resolution + validation block ABOVE the existing reuse-branch check so partial-amount requests pass through the validation gate first (Req 3.7)
    - Source the existing PI's amount from the **DB-cached** `payment_tokens.last_pi_amount_cents` column (added in task 1.1) — NOT from a synchronous Stripe API call. Rationale: a live Stripe call adds 200-400ms to every QR Payment click and can fail under network blips; the cached value is updated on every PI create or update-surcharge so it stays accurate. Cache miss (NULL value) treated as "no existing amount known" — fall through to create-new path
    - Compare cached cents to `int(resolved_amount * 100)`. Reuse only when amounts match
    - When the cached value is stale (mismatches Stripe — e.g., a manual amount change via Stripe Dashboard that didn't go through our code), the reuse path returns a session pointing at the wrong amount. This edge case is acceptable: Stripe Dashboard manual edits are an out-of-band workflow that the merchant uses at their own risk. Document this trade-off in a code comment near the reuse check
    - _Requirements: 5.1, 5.2_
  - [x] 6.3.1 Refresh the cached PI amount on every PI create
    - When the new PaymentIntent is created (task 6.7), set `payment_token.last_pi_amount_cents = target_cents` on the freshly-inserted token row
    - Same applies to the public-router `update_surcharge` endpoint (task 9.3) — when it updates the PI on Stripe to a new gross amount, also UPDATE `payment_tokens.last_pi_amount_cents` to the new total cents
    - This keeps the cached value within one round-trip of truth and avoids the synchronous Stripe call
    - _Requirements: 5.1, 5.2_
  - [x] 6.4 Cancel orphan PaymentIntent before creating a new one (when amount mismatch path)
    - Before calling `create_payment_intent` for the new PI, if `invoice.stripe_payment_intent_id` exists, call a new helper `_cancel_payment_intent` (see task 7) wrapped in try/except
    - Log Stripe failures at WARNING level, swallow the exception so the new-session creation does not depend on cancellation success
    - _Requirements: 5.3_
  - [x] 6.5 Mark old payment_token inactive (when amount mismatch path)
    - Find the active payment_token for this invoice, set `is_active = False`, do NOT delete
    - Use `update(...).where(...).values(is_active=False)` for atomicity
    - _Requirements: 5.4_
  - [x] 6.6 Pass `amount_override` to the new payment_token
    - Call `generate_payment_token(..., amount_override=resolved_amount if is_partial else None)`
    - _Requirements: 6.1_
  - [x] 6.7 Set PaymentIntent metadata correctly via the `extra_metadata` parameter (added in task 5.5.1)
    - Pass to `create_payment_intent`:
      ```python
      extra_metadata={
          "source": "kiosk_qr",
          "original_amount": str(resolved_amount),
          "is_partial_payment": "true" if is_partial else "false",
      }
      ```
    - Setting `original_amount` and `source` AT CREATION (not just in `update-surcharge`) closes the existing webhook-detection bug — the webhook reads `metadata.original_amount` and falls back to `(amount_received - surcharge)` if missing; for partial flows we cannot tolerate that fallback because the amount_received already includes surcharge
    - Setting `is_partial_payment` AT CREATION gives audit-log filtering and downstream observers an explicit marker that doesn't require querying the `payment_tokens.amount_override` to determine partial-vs-full
    - The `update-surcharge` endpoint will OVERWRITE `original_amount` with `payment_token.amount_override or invoice.balance_due` when the customer picks a payment method — that's correct (post-method-pick the gross is `original + surcharge`, so the webhook subtracts surcharge to get back to original)
    - Application fee calculation: `int(amount_cents * fee_percent / 100)` where `amount_cents = int(resolved_amount * 100)` — proportional to partial, not balance
    - _Requirements: 4.1, 4.2, 4.3, 4.4_
  - [x] 6.8 Set pending_qr_sessions row amount to resolved_amount
    - The existing INSERT statement already uses a variable for amount; ensure it's `resolved_amount`, not `invoice.balance_due`
    - _Requirements: 4.5_
  - [x] 6.9 Return resolved_amount in response
    - Existing return dict includes `"amount": ...` — make sure it's `resolved_amount`, not `invoice.balance_due`
    - _Requirements: 4.6_

- [ ] 7. Add _cancel_payment_intent helper
  - [x] 7.1 Implement `_cancel_payment_intent` in `app/modules/payments/service.py`
    - Direct httpx POST to `https://api.stripe.com/v1/payment_intents/{id}/cancel`
    - Use `Stripe-Account` header with the org's `stripe_connect_account_id`
    - Body: `cancellation_reason=abandoned`
    - Use the existing pattern from `expire_qr_session` and `update_surcharge` for header/auth construction
    - Raise on 5xx, log + raise-suppressed on 4xx (PI already in terminal state etc)
    - _Requirements: 5.3_

- [ ] 8. Update the create-qr-session-existing-invoice endpoint
  - [x] 8.1 Thread `partial_amount` from request body to service call in `app/modules/payments/router.py`
    - `payload.amount` → `partial_amount` keyword argument on the service call
    - No other endpoint changes
    - _Requirements: 3.1_

- [ ] 9. Surface amount_override on the public payment page
  - [x] 9.1 Add `is_partial_payment: bool = False` field to **`PaymentPageResponse`** in `app/modules/payments/schemas.py:364` (NOT `PublicPaymentPageResponse` — that name was a draft error; the actual class is `PaymentPageResponse`)
    - _Requirements: 6.3_
  - [x] 9.2 In `get_payment_page_data` (`app/modules/payments/public_router.py`), resolve display amount
    - Read `payment_token.amount_override` after the token is loaded
    - Set the response's `balance_due = payment_token.amount_override or invoice.balance_due`
    - Set `is_partial_payment = payment_token.amount_override is not None`
    - The `base_data` dict already includes `balance_due=invoice.balance_due` — replace that with `balance_due=resolved_balance` and add `is_partial_payment=is_partial` so it propagates through every `PaymentPageResponse(**base_data, ...)` call site (paid path, voided path, payable path, fallback)
    - _Requirements: 6.2, 6.3_
  - [x] 9.3 In `update_surcharge` (`app/modules/payments/public_router.py`), use override as surcharge base
    - Read `payment_token.amount_override`
    - Replace `balance_due = invoice.balance_due` with `resolved_balance = payment_token.amount_override or invoice.balance_due`
    - Use `resolved_balance` as the surcharge base
    - Use `resolved_balance` in `metadata[original_amount]` (NOT `invoice.balance_due`)
    - PI total = `int((resolved_balance + surcharge) * 100)`
    - **Also update the cached `payment_tokens.last_pi_amount_cents`** to the new total cents (per task 6.3.1) so the reuse-branch decision stays accurate after a surcharge rewrite
    - _Requirements: 6.4, 5.1_

- [ ] 10. Audit log for QR session lifecycle
  - [x] 10.1 Emit `payment.qr_session_created` audit log entry on every new-PI path
    - `entity_type="invoice"`, `entity_id=invoice.id`, `org_id`, `user_id`
    - `before_value=null`, `after_value={stripe_payment_intent_id, amount: str(resolved_amount), balance_due_at_request_time: str(invoice.balance_due_before_modification), is_partial_payment: bool}`
    - Skipped on the reuse-branch path (Req 9.2)
    - _Requirements: 9.1, 9.2_
  - [x] 10.2 Emit `payment.qr_session_superseded` audit log entry when an old PI is cancelled
    - `entity_id=invoice.id`, `before_value={stripe_payment_intent_id: <old>}`, `after_value={stripe_payment_intent_id: <new>, reason: "amount_changed"}`
    - Fires only when the cancel-old-PI branch executes
    - _Requirements: 9.3_

- [ ] 11. Frontend QrPaymentAmountModal component
  - [x] 11.1 Create `frontend/src/pages/invoices/QrPaymentAmountModal.tsx`
    - Props: `open`, `onClose`, `invoice` (id, balance_due, invoice_number), `onContinue`, `loading`
    - Layout: header, body (radio group + conditional amount input + inline error), footer (Cancel + Continue)
    - State: `mode: 'full' | 'partial'`, `amount: string`, `error: string | null`
    - Pre-populate amount input with formatted balance_due when Partial is selected
    - Validation: empty/zero/NaN, < 0.50, > balance_due, > 2dp (silently truncate)
    - Continue dispatches `onContinue(null)` for full, `onContinue(parseFloat(amount))` for partial
    - Closes on Escape, backdrop click, X button, Cancel — all call `onClose`
    - Uses Tailwind classes consistent with existing modals (e.g. `QrPaymentWaitingPopup`)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.1, 2.2, 2.3, 2.4, 2.5_
  - [x] 11.2 Write `QrPaymentAmountModal.test.tsx` covering the happy paths and validation states
    - Pre-selected Full radio
    - Toggling to Partial reveals the amount input pre-populated with balance_due
    - Continue with Full calls `onContinue(null)`
    - Continue with Partial calls `onContinue(typed amount)`
    - Continue disabled at boundary conditions (empty, < 0.50, > balance, NaN)
    - Backdrop click calls onClose
    - Escape calls onClose
    - X button calls onClose
    - Cancel button calls onClose
    - 3+ decimal places silently truncated
    - Loading state disables the modal close + Continue button
    - _Requirements: 2.5_

- [ ] 11.5 Extend `QrPaymentWaitingPopup` to handle `expired` status (regression-fix found during code audit)
  - [x] 11.5.1 Add `expired` state handling in the polling loop in `frontend/src/pages/invoices/QrPaymentWaitingPopup.tsx`
    - Today the popup only handles `complete` — when status is `expired` (PI cancelled by another tab's superseding session, or Stripe session expired, or `expire_qr_session` called), the popup keeps polling forever. Spec Requirement 10.2 promises a "superseded" message but the existing popup has no code path for that
    - Add a third popup state alongside `waiting` and `success`: `superseded` (or generalised `expired`)
    - When `pollStatus` receives `status === 'expired'`, transition to the new state, stop polling, show a message: "This QR session was superseded by a newer payment attempt." with a Close button
    - Acceptable to use the same UI shell as the success state (different icon + text)
    - _Requirements: 10.2_
  - [x] 11.5.2 Test coverage in `QrPaymentWaitingPopup.test.tsx`
    - `test_popup_shows_superseded_message_on_expired_status` — mock `apiClient.get` returning `{status: 'expired'}`, render popup, assert "superseded" text appears, assert polling stops
    - _Requirements: 10.2_

- [ ] 12. Wire the modal into InvoiceList and InvoiceDetail
  - [x] 12.1 Modify `handleQrPayment` in `frontend/src/pages/invoices/InvoiceList.tsx:841`
    - The existing handler takes no arguments and reads `invoice` from outer scope (split-panel selected invoice). Preserve that pattern
    - Change `handleQrPayment` to: `if (!invoice) return; setQrAmountModalOpen(true)` — it opens the modal instead of immediately POSTing
    - Add a new function `handleAmountModalContinue(amount: number | null)` that does the existing POST with conditional body (`{invoice_id}` or `{invoice_id, amount: amount.toFixed(2)}`)
    - On error use the file's existing pattern: `showMsg(detail || 'Failed to create QR payment session.', 'error')` (NOT `setActionMessage`)
    - Mount `<QrPaymentAmountModal>` in the JSX, gated on `qrAmountModalOpen && invoice`
    - Reuse existing state (`qrPaymentLoading`, `qrSessionData`, `qrWaitingPopupOpen`); add only `qrAmountModalOpen`
    - _Requirements: 1.1, 1.6, 1.7_
  - [x] 12.2 Mirror the same change in `frontend/src/pages/invoices/InvoiceDetail.tsx:577`
    - Same wiring pattern as 12.1
    - InvoiceDetail uses `setActionMessage(detail || 'Failed to create QR payment session.')` (NOT `showMsg`) — match the file's existing error-display pattern
    - _Requirements: 1.1_

- [ ] 13. Public payment page banner for partial-amount tokens
  - [x] 13.1 Modify `frontend/src/pages/public/InvoicePaymentPage.tsx` to consume `is_partial_payment`
    - Add `isPartial = data?.is_partial_payment ?? false` near the existing data-shape destructuring
    - When `isPartial` is true, render an informational banner above the payment method picker:
      - Text: "You are paying a partial amount of {formatNZD(balanceDue)}. Please contact the business if you intended to pay the full balance."
      - Style: `bg-blue-50 border-blue-200 text-blue-900` (matches existing info banners)
    - When `isPartial`, change the payment-summary subtotal label from "Amount Due" to "Amount Due (Partial)"
    - _Requirements: 6.3, 6.5_
  - [x] 13.2 Mirror the change in `mobile/src/screens/auth/PublicPaymentScreen.tsx`
    - Same banner, same label change, same `is_partial_payment` field consumption
    - Use mobile-app touch-target guidelines (`min-h-[44px]`)
    - _Requirements: 6.3, 6.5_

- [ ] 13.5 Partial-payment-aware email subject and body in `email_invoice`
  - [x] 13.5.1 Detect partial vs full at the time `email_invoice` is invoked
    - Read the most recent `Payment` row for the invoice (ordered by `created_at DESC LIMIT 1`) — note: the column is `created_at`, NOT `recorded_at` (verified against `app/modules/payments/models.py:60`)
    - If the row exists AND `invoice.balance_due > 0` AND the invoice status is in {`partially_paid`, `overdue`}, mark this email as a partial-payment receipt
    - Otherwise the email is a regular invoice send / full-paid receipt — existing behaviour
    - Note: this detection runs every time `email_invoice` is called. For the FIRST send (just-issued invoice with zero payments), `balance_due > 0` but no Payment row exists — treated as regular send (correct). For payment-receipt sends, the most recent Payment row will exist and the partial-vs-full state is determined by post-payment invoice state
    - _Requirements: 11.1, 11.4_
  - [x] 13.5.2 Update the hardcoded fallback subject and body for partial receipts
    - In the existing `email_invoice` function (`app/modules/invoices/service.py:4294`), find the block that sets `_email_subject` and `_email_body` when no rendered template applies
    - When partial-receipt detection is true, set:
      - `_email_subject = f"Partial payment received for invoice {inv_number} — {format_money(latest_payment.amount, currency)}"`
      - Body: Insert a two-line summary ABOVE the existing body content:
        ```
        Payment received: {format_money(latest_payment.amount)}
        Remaining balance: {format_money(invoice.balance_due)}

        {existing body...}
        ```
    - When partial-receipt detection is false, the subject and body remain unchanged (full payment / regular invoice)
    - _Requirements: 11.1, 11.2, 11.5_
  - [x] 13.5.3 Custom templates pass through unchanged
    - When `_rendered_template` is non-null (org has configured an `invoice_send` template), the partial-vs-full logic does NOT override the rendered subject/body. The org has opted into custom phrasing
    - This preserves existing template-customisation semantics and avoids surprising orgs that have crafted their own wording
    - _Requirements: 11.5_
  - [x] 13.5.4 Test coverage in `tests/test_email_invoice_partial.py`
    - `test_partial_receipt_subject_distinguishes_partial` — record partial payment, call `email_invoice`, capture sent message, assert subject matches "Partial payment received for invoice ..."
    - `test_partial_receipt_body_includes_received_and_remaining` — assert body contains both "Payment received: $X.XX" and "Remaining balance: $Y.YY" lines
    - `test_full_payment_uses_existing_subject` — record final payment that settles the invoice, assert subject is the regular "Invoice X from Y" form (no regression)
    - `test_custom_template_overrides_partial_logic` — configure a custom `invoice_send` template, record partial, assert custom template subject/body is used (not the partial form)
    - _Requirements: 11.x_

- [ ] 14. Backend tests for partial QR flow
  - [x] 14.1 Integration tests in `tests/test_qr_partial_payment_integration.py`
    - `test_partial_amount_omitted_uses_balance` — service with `amount=None` → PI cents = balance × 100, token.amount_override = NULL
    - `test_partial_amount_below_stripe_min` — `amount=0.49` → HTTP 400 with friendly detail
    - `test_partial_amount_above_balance` — `amount=balance+0.01` → HTTP 400 with friendly detail
    - `test_partial_amount_equal_balance_still_partial` — `amount=balance` → token.amount_override=balance, metadata.is_partial_payment="true"
    - `test_reuse_branch_same_amount` — second call with same amount, no new PI, no audit log entry
    - `test_reuse_branch_different_amount_cancels_old_pi` — second call with different amount, mock Stripe cancel, verify new PI created, old token marked inactive, both audit log entries emitted
    - `test_reuse_branch_stripe_cancel_failure_continues` — Stripe cancel returns 400 → service still creates new PI, audit superseded entry still emitted, error logged at WARNING
    - `test_application_fee_proportional_to_partial` — fee = int(partial × 100 × fee_pct / 100), not int(balance × ...)
    - `test_metadata_is_partial_payment_flag` — full → "false", partial → "true"
    - `test_pending_qr_session_amount_matches_partial` — pending_qr_sessions.amount == resolved_amount
    - `test_response_amount_matches_partial` — endpoint response `amount` field matches resolved_amount
    - `test_public_pay_get_uses_amount_override` — GET /public/pay/{token} returns balance_due == amount_override and is_partial_payment=true
    - `test_update_surcharge_uses_amount_override` — POST /update-surcharge with override-set token → surcharge computed against override, PI updated to override × (1 + p/(1-p))
    - `test_webhook_records_partial_correctly` — partial PI confirmation → Payment row with amount=partial, surcharge=correct, invoice.balance_due decremented by partial, status partially_paid
    - `test_webhook_third_partial_settles_to_paid` — three sequential 100s on a 300 invoice → status paid, three Payment rows, three audit log entries
    - `test_webhook_duplicate_event_for_partial_pi_idempotent` — fire the SAME `payment_intent.succeeded` webhook event twice for the same partial PI; assert exactly one Payment row, exactly one decrement of `invoice.balance_due`, and no double-spend. Stripe sends webhook events at-least-once so duplicate delivery is an expected production scenario. The existing webhook handler's idempotency guard (`SELECT WHERE stripe_payment_intent_id = X AND is_refund = False`) must protect partial flows the same way it protects full payments — this test verifies that protection. **This is the highest-value test in this list — getting this wrong silently double-debits the customer**
    - `test_webhook_partial_then_duplicate_then_second_partial` — sequence: fire partial PI #1 succeeded, then fire DUPLICATE of PI #1 succeeded (must be ignored), then fire partial PI #2 succeeded (must record). Confirms idempotency keys per-PI not per-invoice
    - _Requirements: 3.x, 4.x, 5.x, 6.x, 7.x, 7.3_
  - [x] 14.2 Property tests in `tests/properties/test_qr_partial_properties.py`
    - **Property 1: Cents round-trip.** For Decimal d in [0.50, 99999.99] with ≤ 2dp, `int(d * 100) / 100 == d`
    - **Property 2: Validation envelope.** For (amount, balance) with 0 < amount ≤ balance and amount ≥ 0.50, service accepts; outside this envelope, service rejects with HTTP 400
    - **Property 3: Webhook records exactly partial.** For partial $a$ and surcharge $(p, f)$, after successful payment, `invoice.balance_due_after = invoice.balance_due_before - a` (within 1¢)
    - _Requirements: 3.x, 7.x_
  - [x] 14.3 Run only the relevant backend tests — not the full suite
    - Execute exactly these test files in the dev container:
      ```bash
      docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app \
        pytest -x \
          tests/test_qr_partial_payment_integration.py \
          tests/properties/test_qr_partial_properties.py \
          tests/test_email_invoice_partial.py \
          tests/test_payments_qr_session.py \
          tests/test_payments_webhook.py
      ```
    - Rationale: this spec only touches QR session creation, the public payment endpoints, the Stripe webhook handler, and the partial-receipt email path. Running the full repository suite (3000+ tests) is out of scope and adds noise without value
    - If any of those existing files have been renamed or split since spec authoring, substitute the actual filenames covering the same modules. Skip files that don't exist
    - All listed tests must pass. No `--no-cov` shortcut, no skipped failures
    - _Requirements: All test requirements_

- [ ] 15. Frontend unit tests
  - [x] 15.1 Update `InvoiceList.test.tsx` to assert the new modal-mediated flow
    - Click QR Payment → assert modal opens
    - Modal Continue with Full → assert `apiClient.post` called with `{invoice_id}` only
    - Modal Continue with Partial typed value → assert `apiClient.post` called with `{invoice_id, amount: '100.00'}`
    - Modal close → assert no API call made
    - _Requirements: 1.6, 1.7, 1.8_
  - [x] 15.2 Mirror in `InvoiceDetail.test.tsx`
    - _Requirements: 1.6, 1.7, 1.8_
  - [x] 15.3 Update `InvoicePaymentPage.test.tsx` and `PublicPaymentScreen.test.tsx` (mobile)
    - When `is_partial_payment` is true, banner text appears and label is "Amount Due (Partial)"
    - When false (default), banner is absent and label is "Amount Due"
    - _Requirements: 6.3, 6.5_
  - [x] 15.4 Run only the relevant frontend tests — not the full suite
    - Frontend (web):
      ```bash
      cd frontend
      npx vitest run \
        src/pages/invoices/__tests__/InvoiceList.test.tsx \
        src/pages/invoices/__tests__/InvoiceDetail.test.tsx \
        src/pages/public/__tests__/InvoicePaymentPage.test.tsx \
        src/components/payments/__tests__/QrPartialPaymentModal.test.tsx
      ```
    - Mobile (only if mobile public payment page test was touched):
      ```bash
      cd mobile
      npx vitest run \
        src/screens/auth/__tests__/PublicPaymentScreen.test.tsx
      ```
    - If any test paths differ from the actual filenames in the repo, substitute accordingly. Don't run `npx vitest run` with no args — that triggers the full suite
    - _Requirements: All frontend test requirements_

- [ ] 16. Manual QA smoke test on dev environment
  - [ ] 16.1 Smoke test partial flow end-to-end on local Ubuntu dev (`devin.oraflows.co.nz`)
    - Create test invoice for $300
    - Click QR Payment → modal opens with Full pre-selected
    - Switch to Partial, type "100.00", Continue
    - Verify waiting popup shows $100.00
    - Verify kiosk picks up $100.00 in QR display
    - Scan QR with phone
    - Verify public payment page shows "Amount Due (Partial) $100.00" + banner
    - Pay with test card → invoice goes to partially_paid, balance becomes $200
    - Repeat with another $100 partial → balance becomes $100, status partially_paid
    - Repeat with $100 final → balance becomes $0, status paid
    - Verify Payments tab on InvoiceDetail shows three rows with three different stripe_payment_intent_ids and three correct surcharge amounts
    - Verify audit log shows three `payment.qr_session_created` entries and three `payment.stripe_webhook_received` entries
    - _Requirements: All — end-to-end verification_
  - [ ] 16.2 Smoke test reuse-branch behaviour
    - Click QR Payment, choose Full, Continue (creates PI for full balance)
    - Cancel modal-popup before customer pays
    - Click QR Payment again, choose Full, Continue
    - Verify same `session_id` returned (reuse branch, no new PI on Stripe Dashboard)
    - Click QR Payment again, choose Partial $50, Continue
    - Verify new `session_id` returned, old PI cancelled in Stripe Dashboard, audit log shows `payment.qr_session_superseded`
    - _Requirements: 5.1, 5.2, 5.3_
  - [ ] 16.3 Smoke test concurrent-modal behaviour
    - Two browser tabs open on the same invoice, both as org_admin
    - Tab A: click QR Payment, choose Partial $100, Continue
    - Tab B: click QR Payment, choose Partial $200, Continue
    - Verify Tab A's waiting popup shows the superseded message after a poll cycle
    - Verify Tab B's waiting popup shows $200 successfully
    - Verify only one pending_qr_sessions row exists for the org
    - Verify Tab A's PI is `canceled` on Stripe Dashboard
    - _Requirements: 10.1, 10.2_

- [ ] 17. Release artefacts (dev-only — no Pi/PROD deployment)
  - [x] 17.1 Bump version
    - `pyproject.toml`: `1.10.5` → `1.11.0` (minor bump — adds new optional API field)
    - `app/__init__.py`: matching string
    - `frontend/package.json`: matching string
    - `mobile/package.json`: matching string (mobile public payment page got the partial banner)
    - _Requirements: Release discipline_
  - [x] 17.2 Add CHANGELOG.md entry under `[1.11.0]` heading
    - Section: `### Added`
    - Bullet describing the new partial-amount QR flow at a glance
    - Bullet noting the new `payment_tokens.amount_override` and `payment_tokens.last_pi_amount_cents` columns and `is_partial_payment` response field
    - Bullet noting the regression-fix that PI metadata (`source`, `original_amount`, `is_partial_payment`) is now set at PI creation rather than only via `update-surcharge`
    - Bullet noting that the existing webhook handler is unchanged — partial payments record correctly via existing `metadata.original_amount` plumbing, plus the new "clear stale invoice PI fields after payment" behaviour
    - Bullet noting compliance: gross-up surcharge (1.10.5) continues to apply to the partial amount; merchant nets exactly the typed amount
    - _Requirements: Release discipline_
  - [x] 17.3 Update ISSUE_TRACKER.md with a closing entry referencing this spec
    - Spec link, brief description, completed-on date
    - Note the regression-fixes for the existing pre-existing bugs (PI metadata not set at creation; stale PI fields after webhook) so future agents know they were addressed here
    - _Requirements: Documentation_
  - [x] 17.4 Rebuild dev containers with the new code
    - Backend: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build app` (entrypoint runs `alembic upgrade head` automatically, but the migration was already applied in task 1.2)
    - Frontend: stop frontend + nginx, remove containers, delete `invoicing_frontend_dist` volume, rebuild with `--build` (per project deployment notes for frontend changes)
    - **Do NOT** sync to Pi (192.168.1.90), **do NOT** deploy to PROD or any standby. This spec ships to dev only
    - _Requirements: Release discipline_
  - [x] 17.5 Commit and push to GitHub
    - Stage the spec changes (`.kiro/specs/qr-partial-payment/`), all source changes (`app/`, `frontend/`, `mobile/`, `alembic/versions/`), version bumps, and `CHANGELOG.md` / `docs/ISSUE_TRACKER.md` updates
    - Commit message format: `feat(payments): partial-amount QR payments` followed by a short body listing the new endpoint capability, migration revision, and version bump
    - Push to `main` on `arshdeepromy/Orainvoice`. Pi has no auto-pull — pushing is for source-of-truth/history only and does NOT trigger a Pi deploy
    - _Requirements: Release discipline_

- [ ] 18. Clear stale invoice PI fields after webhook records a payment (regression-fix found during code audit)
  - [x] 18.1 In `handle_stripe_webhook` (`app/modules/payments/service.py` ~line 920, after `clear_pending_qr_session`), also clear the invoice's PI fields when the payment was successfully recorded:
    ```python
    invoice.stripe_payment_intent_id = None
    invoice.payment_page_url = None
    inv_json = dict(invoice.invoice_data_json or {})
    inv_json.pop("stripe_client_secret", None)
    invoice.invoice_data_json = inv_json
    flag_modified(invoice, "invoice_data_json")
    await db.flush()
    ```
    - This is safe because after a successful payment the PI is in a terminal state (`succeeded` or `canceled`) and cannot be reused. Stripe rejects further updates with `payment_intent_unexpected_state`
    - Without this, the second-partial-payment QR flow enters the existing reuse-branch (line 1448 of service.py), finds an active `payment_token` and a non-null `invoice.stripe_payment_intent_id`, tries to reuse — and any subsequent `update-surcharge` call from the customer fails on Stripe
    - _Requirements: 7.1, 7.2 (multi-partial settlement), regression-fix for pre-existing reuse-branch bug_
  - [x] 18.2 Deactivate active payment_tokens for the invoice in the webhook (closes a re-scan gap on the just-paid URL)
    - In `handle_stripe_webhook` after the Payment row is inserted and the invoice has been updated, deactivate ALL `is_active=True` payment_tokens for this invoice:
      ```python
      from app.modules.payments.models import PaymentToken
      await db.execute(
          update(PaymentToken)
          .where(
              PaymentToken.invoice_id == invoice.id,
              PaymentToken.is_active == True,  # noqa: E712
          )
          .values(is_active=False)
      )
      await db.flush()
      ```
    - Why: Without this, the just-paid URL stays active in the database for its 72-hour TTL. If a customer or anyone with the URL re-scans/re-visits T1 in the window between payment-completion and the next partial being initiated, the public payment page returns `is_payable=true` with `client_secret=None` (because task 18.1 cleared the PI fields on the invoice), causing the Stripe Elements form to fail to render. Token deactivation in the webhook means subsequent scans return clean HTTP 404 "Invalid payment link" — the customer gets a definitive answer instead of a broken form
    - The existing `generate_payment_token` function (`app/modules/payments/token_service.py:54-62`) already deactivates active tokens for the invoice when a NEW token is generated. This task ensures deactivation happens at payment-completion time too, closing the in-between gap
    - For the multi-partial flow, deactivating after each partial is the correct behaviour: the next partial generates a new active token; the just-paid one is safely retired
    - _Requirements: 7.1, 7.2, gap-closure for the "$200 invoice with three partials, customer re-scans first URL" edge case_
  - [x] 18.3 Test `test_webhook_clears_stale_pi_fields` in the integration test file
    - After webhook records a successful payment, assert `invoice.stripe_payment_intent_id is None` and `invoice.payment_page_url is None`
    - Assert `invoice.invoice_data_json.get("stripe_client_secret") is None`
    - _Requirements: 7.1, 7.2_
  - [x] 18.4 Test `test_webhook_deactivates_payment_tokens` in the integration test file
    - Generate a token T1 for invoice I (active=True)
    - Fire webhook for payment that records against I
    - Assert T1.is_active is False after the webhook completes
    - Assert that `GET /public/pay/{T1}` returns HTTP 404 "Invalid payment link"
    - _Requirements: 7.1, 7.2, 18.2 gap-closure_
  - [x] 18.5 Test `test_second_partial_creates_new_pi_after_first_settled` in the integration test file
    - Sequence: invoice $300 → first partial QR for $100 → webhook records payment → assert PI fields cleared, T1 deactivated → second partial QR for $100 → assert NEW PI created (not reuse), NEW token T2 generated and active, T1 still in DB but is_active=False
    - _Requirements: 7.2, regression-fix verification_
  - [x] 18.6 Test `test_three_partials_settle_correctly_with_token_lifecycle` in the integration test file
    - The exact scenario: invoice $200, three partials $50 + $50 + $100
    - After partial #1 ($50) settles: assert balance_due=$150, status=partially_paid, T1 deactivated, invoice PI fields cleared
    - After partial #2 ($50) settles: assert balance_due=$100, status=partially_paid, T2 deactivated, invoice PI fields cleared
    - After partial #3 ($100) settles: assert balance_due=$0, status=paid, T3 deactivated
    - Three Payment rows total, three distinct stripe_payment_intent_ids
    - Assert `GET /public/pay/{T1}` returns 404 immediately after partial #1 webhook completes
    - Assert `GET /public/pay/{T2}` returns is_payable=true with valid client_secret WHILE partial #2 is in flight
    - Cumulative `amount_paid` = $200 = `invoice.total`
    - _Requirements: 7.1, 7.2, 7.4, 7.5, end-to-end multi-partial verification_

## Implementation order recommendation

Suggested order minimises risk and lets each step be verified before moving on:

1. Migration first (1) — fast to deploy, zero risk on its own. **Apply to dev DB immediately (task 1.2)**.
2. Per-currency Stripe minimum constants + schema validation (2, 3) — small, isolated; backend tests can be added immediately.
3. ORM column + token service (4, 5) — wire the new field through; not yet exercised.
4. Extend `create_payment_intent` with `extra_metadata` parameter (5.5) — foundational change required before service refactor can set metadata at creation. Tiny, backwards-compatible.
5. Service refactor + cancel helper + endpoint (6, 7, 8) — the main behavioural change. Pay attention to the DB-cached PI amount strategy in 6.3.1 and the metadata-via-extra_metadata flow in 6.7.
6. Public router consumption (9) — public page now honours the override. Update the cached PI amount in update_surcharge.
7. Audit logs (10) — observability layer.
8. Frontend modal + wiring (11, 11.5, 12) — UI exposure. Match each file's existing handler signature pattern (no new arguments). Include the QrPaymentWaitingPopup `expired` state handling.
9. Public payment page banner (13) — final UX polish.
10. Partial-payment-aware emails (13.5) — receipt subject + body distinguish partial vs full.
11. Tests (14, 15) — codify behaviour, including the critical webhook duplicate-event idempotency tests.
12. Manual QA (16) — verify end-to-end on dev.
13. Release (17) — version + changelog + tracker.
14. Webhook stale-PI-fields cleanup (18) — regression-fix discovered during code audit. Can land alongside the rest of the spec but is logically a separate fix; sequenced last so test coverage exists for it.

## Risk register

| Risk | Mitigation |
|---|---|
| Stripe cancel API rate limit during high-volume amount changes | Cancel is best-effort; failure logged + ignored. Daily orphan-PI reconciliation job (separate spec) catches strays. |
| Webhook arrives for cancelled PI (race) | Existing webhook handler ignores already-finalised invoices via status check; idempotency by PI ID prevents double-record. |
| Frontend sends amount without 2dp due to floating-point | `toFixed(2)` on send + Pydantic validator rejects > 2dp at the schema layer. |
| Multiple concurrent partial requests on same invoice | DB row-level lock via `SELECT FOR UPDATE` (existing pattern); pending_qr_sessions unique on org_id ensures kiosk display is deterministic. |
| Partial amount that, with surcharge, drops below Stripe minimum | Validation runs against `partial_amount` itself, which must be ≥ $0.50; surcharge can only increase the gross. |
| Frontend cached without is_partial_payment field knowledge | Field defaults to `false` on response; older frontend cleanly ignores it (backwards compatible). |
| Migration deployed but service code not yet at 1.11.0 | Column is nullable with default NULL — pre-feature service code does not read it, so no runtime error. |
