# Requirements Document

## Introduction

This feature lets the org user split-pay an invoice via QR code. When the staff member clicks "QR Payment" on the InvoiceList or InvoiceDetail page, the system intercepts the existing flow with a small **payment-amount selection modal** that asks the user to choose between **Full payment** (existing behaviour) and **Partial payment** (new). Choosing Full continues exactly as today — the QR session is created for the invoice's full `balance_due` and the kiosk displays the QR code. Choosing Partial reveals an amount input pre-populated with `balance_due`; the staff member types the amount the customer is paying right now (e.g., a deposit, instalment, or cash-plus-card split), and the QR session is created for that smaller amount only. The customer scans the kiosk QR code, pays the partial amount via Stripe Checkout, and the existing webhook handler — which is already partial-payment aware — records the payment, increments `invoice.amount_paid`, decrements `invoice.balance_due`, and flips the invoice status to `partially_paid` (or `paid` if the partial happens to settle the remaining balance). The org user can repeat the QR flow for further partials until the invoice is fully paid.

The change is additive: no existing endpoint contract is broken, no existing UI element is removed, and the default chosen radio in the new modal is "Full payment" so a user who clicks straight through Continue gets the current behaviour byte-for-byte.

## Glossary

- **Amount_Selection_Modal**: New pre-QR modal shown on the org user's screen after clicking "QR Payment", offering Full vs Partial radio options. Replaces the immediate QR session creation step. NOT shown to the kiosk or to the customer.
- **Full_Payment_Choice**: Radio option that creates a QR session for `invoice.balance_due` — identical contract to the pre-feature behaviour.
- **Partial_Payment_Choice**: Radio option that reveals an amount input and creates a QR session for the typed amount (a value strictly less than `balance_due` and at least the platform-configured minimum).
- **Partial_Amount**: The amount in NZD the staff member types when Partial_Payment_Choice is selected. Always satisfies `Stripe_Minimum (for the invoice currency) <= Partial_Amount <= invoice.balance_due` after rounding to two decimal places.
- **Stripe_Minimum**: Stripe's minimum charge amount per currency. Sourced from a per-currency dict `STRIPE_MIN_BY_CURRENCY` defined in `app/modules/payments/service.py` (verified during implementation that no equivalent constant exists today). For NZD, AUD, USD, and EUR the minimum is `0.50`; for GBP `0.30`; for JPY `50` (no decimals); fallback `0.50` for unlisted currencies. Per-currency from day one so multi-currency invoicing (future work) is a one-entry change. Source: [Stripe — minimum and maximum charge amounts](https://stripe.com/docs/currencies#minimum-and-maximum-charge-amounts).
- **QR_Session**: The existing `pending_qr_sessions` row plus Stripe PaymentIntent created via `create_qr_session_for_existing_invoice`. The PI's amount and the kiosk-visible amount must equal the Partial_Amount when Partial_Payment_Choice is selected.
- **Payment_Token_Override**: A new optional column `amount_override` on the existing `payment_tokens` table that, when set, overrides `invoice.balance_due` as the "amount due now" surfaced by the public payment page and used by the surcharge recompute on payment-method change.
- **Public_Payment_Page**: The customer-facing payment page at `/api/v1/public/pay/{token}` and frontend route `/pay/{token}` / `/m/pay/{token}`. Already aware of `balance_due` and surcharge rates; must be taught to honour Payment_Token_Override.
- **Update_Surcharge_Endpoint**: Existing `POST /api/v1/public/pay/{token}/update-surcharge`. Currently rebuilds the PI amount from `invoice.balance_due + surcharge`; must be taught to use Payment_Token_Override when set so partial-amount QR payments don't silently rescale to the full balance when the customer picks a payment method.
- **Webhook_Handler**: Existing `handle_stripe_webhook` in `app/modules/payments/service.py`. Already records partial payments correctly via `invoice.amount_paid += pay_amount`, `invoice.balance_due -= pay_amount`, status flip to `partially_paid` or `paid`. **No changes required.**
- **Reuse_Branch_Guard**: The early-return path in `create_qr_session_for_existing_invoice` that reuses an existing `payment_page_url` + `stripe_payment_intent_id` if the invoice already has them. Must be skipped when the new request's amount differs from the existing PI's amount, to prevent partial-amount requests from silently displaying the previous (full or different-partial) PI.
- **Idempotency_Surface**: The webhook handler's existing duplicate-PI guard at `app/modules/payments/service.py` ~line 824 that rejects events whose `stripe_payment_intent_id` was already recorded as a non-refund Payment. Each partial QR payment uses a distinct PaymentIntent so this guard already covers multi-partial flows.

## Requirements

### Requirement 1: Pre-QR Amount Selection Modal on Org User Screen

**User Story:** As a staff member collecting payment for an invoice with an outstanding balance, I want to choose whether the customer is paying the full balance or only a partial amount before the QR code is generated, so that the kiosk QR matches what the customer will actually scan and pay.

#### Acceptance Criteria

1.1 WHEN the staff member clicks "QR Payment" on the InvoiceList page OR the InvoiceDetail page AND the invoice has status in {`issued`, `partially_paid`, `overdue`} AND the organisation has a non-null `stripe_connect_account_id`, THE Org_User_Screen SHALL render the Amount_Selection_Modal instead of immediately calling `POST /api/v1/payments/qr-session/existing`

1.2 THE Amount_Selection_Modal SHALL display two mutually exclusive radio options: "Full payment ($BALANCE_DUE)" and "Partial payment"

1.3 THE Amount_Selection_Modal SHALL pre-select the Full_Payment_Choice radio so that pressing Continue without interacting maps to the pre-feature behaviour

1.4 WHEN the staff member selects the Partial_Payment_Choice radio, THE Amount_Selection_Modal SHALL reveal an amount input field pre-populated with `invoice.balance_due` formatted to two decimal places

1.5 THE Amount_Selection_Modal SHALL show the invoice's `balance_due` value alongside the Full_Payment_Choice label so the staff member sees the current outstanding amount

1.6 WHEN the staff member presses Continue with Full_Payment_Choice selected, THE Org_User_Screen SHALL call `POST /api/v1/payments/qr-session/existing` with body `{invoice_id}` only — the new optional `amount` field SHALL be omitted, preserving the pre-feature request shape

1.7 WHEN the staff member presses Continue with Partial_Payment_Choice selected AND the typed amount is valid, THE Org_User_Screen SHALL call `POST /api/v1/payments/qr-session/existing` with body `{invoice_id, amount}` where `amount` is the typed value as a string with two decimal places

1.8 WHEN the staff member dismisses the Amount_Selection_Modal via X button, backdrop click, or Escape key, THE Org_User_Screen SHALL NOT make any network calls and SHALL NOT modify any invoice or session state

### Requirement 2: Partial Amount Validation (Frontend)

**User Story:** As a staff member, I want the partial amount input to refuse obviously-wrong values before sending to the backend so I see immediate feedback rather than waiting for an API round-trip.

#### Acceptance Criteria

2.1 WHILE Partial_Payment_Choice is selected AND the amount input is empty OR contains zero OR contains a value less than Stripe_Minimum (for the invoice's currency, e.g. $0.50 NZD) OR contains a value greater than `invoice.balance_due`, THE Continue button SHALL be visually disabled and SHALL NOT submit on click

2.2 WHEN the staff member types a non-numeric character in the amount input, THE input SHALL silently strip the character (allow only digits and one decimal separator)

2.3 WHEN the typed amount has more than two decimal places, THE input SHALL truncate (not round) trailing digits beyond the second decimal so the value sent to the backend always has at most two decimal places

2.4 WHEN the typed amount equals `invoice.balance_due` (within 1¢ tolerance for floating-point safety) AND Partial_Payment_Choice is selected, THE Org_User_Screen SHALL still send `{invoice_id, amount}` (NOT silently rewrite to the Full_Payment_Choice request) — the user explicitly chose Partial and the backend treats the equal-to-balance case as a full payment naturally

2.5 WHEN validation fails, THE Amount_Selection_Modal SHALL display a single concise inline message under the input describing the violation: "Amount must be at least $0.50", "Amount cannot exceed the outstanding balance of $X.XX", or "Enter an amount"

### Requirement 3: Backend Partial Amount Acceptance and Validation

**User Story:** As a system operator, I want the backend to authoritatively validate partial amounts so a malformed or malicious frontend payload cannot cause an invoice to be over-collected, under-collected below Stripe's minimum, or modified incorrectly.

#### Acceptance Criteria

3.1 THE `POST /api/v1/payments/qr-session/existing` request body schema (`QrSessionExistingInvoiceRequest`) SHALL gain an optional field `amount: Decimal | None = Field(None, gt=0, description="Optional partial amount; defaults to invoice.balance_due if omitted")`

3.2 WHEN the request body contains `amount` field, THE service `create_qr_session_for_existing_invoice` SHALL coerce the value to `Decimal` and validate `stripe_min_for_currency(invoice.currency) <= amount <= invoice.balance_due` (after both sides are rounded to two decimal places)

3.3 IF the supplied `amount` is less than `stripe_min_for_currency(invoice.currency)`, THEN THE service SHALL raise `ValueError` with message "Partial amount must be at least {min_amount} {currency}" (e.g., "$0.50 NZD") and the endpoint SHALL return HTTP 400

3.4 IF the supplied `amount` is greater than `invoice.balance_due`, THEN THE service SHALL raise `ValueError` with message "Partial amount cannot exceed the outstanding balance of $X.XX" and the endpoint SHALL return HTTP 400

3.5 WHEN the request body omits `amount` (field is `None`), THE service SHALL behave exactly as the pre-feature implementation — the resolved billing amount SHALL equal `invoice.balance_due`

3.6 WHEN the resolved billing amount equals `invoice.balance_due`, THE service SHALL behave identically whether the field was omitted or supplied with the matching value (idempotent equivalence)

3.7 THE service SHALL apply the validation and amount resolution BEFORE the Reuse_Branch_Guard check so that supplying a different partial amount on a follow-up call does not return a stale session

### Requirement 4: PaymentIntent and Pending Session Created for Partial Amount

**User Story:** As a system, I need the Stripe PaymentIntent created for a partial QR payment to bill exactly the partial amount, with the correct application fee proportionate to that smaller amount, and with metadata that reconciles back to the invoice on webhook receipt.

#### Acceptance Criteria

4.1 WHEN a partial QR session is being created, THE service SHALL set `amount_cents = int(resolved_amount * 100)` based on the partial amount, NOT on `invoice.balance_due`

4.2 WHEN computing `application_fee_amount`, THE service SHALL multiply the platform fee percentage by the partial amount in cents (NOT by the full balance) so the platform fee scales proportionately with the partial

4.3 THE PaymentIntent metadata SHALL include `original_amount` set to the partial amount as a string with two decimal places (e.g., `"100.00"`), so the existing webhook handler subtracts surcharge from this value to record `pay_amount = partial` against the invoice

4.4 THE PaymentIntent metadata SHALL also include `is_partial_payment: "true"` when the request supplied a non-null `amount`, providing an explicit marker for downstream observability and audit log filtering

4.5 THE inserted `pending_qr_sessions` row SHALL set `amount = resolved_amount` (the partial), so the kiosk display, `GET /api/v1/payments/qr-session/pending`, and `GET /api/v1/payments/qr-session/{session_id}/status` all surface the partial amount as the session's amount

4.6 THE response body of `POST /api/v1/payments/qr-session/existing` SHALL set `amount = resolved_amount` so the org user's waiting popup displays the partial amount, not the invoice balance

### Requirement 5: Reuse-Branch Guard for Mixed Full/Partial Calls

**User Story:** As a staff member, I want each click of QR Payment with a different amount to produce a fresh QR session for that amount, so that I never accidentally send a customer to a stale payment link with the wrong total.

#### Acceptance Criteria

5.1 WHEN `create_qr_session_for_existing_invoice` finds an existing `payment_page_url` + `stripe_payment_intent_id` on the invoice AND the existing PaymentIntent's amount in cents equals the requested `resolved_amount * 100`, THE service SHALL reuse the existing session as today (refresh the `pending_qr_sessions` row and `payment_tokens.amount_override`)

5.2 WHEN `create_qr_session_for_existing_invoice` finds an existing `payment_page_url` + `stripe_payment_intent_id` on the invoice AND the existing PaymentIntent's amount differs from the requested `resolved_amount * 100`, THE service SHALL skip the reuse path and create a new PaymentIntent + a new payment_token with `amount_override = resolved_amount` set

5.3 WHEN the service creates a new PaymentIntent because of an amount mismatch, THE service SHALL also expire any existing PaymentIntent on the invoice via the Stripe API call `POST /v1/payment_intents/{pi_id}/cancel` so an orphan unfunded PI does not remain on the merchant's Stripe dashboard. Stripe API errors during cancel SHALL be logged at WARNING level but SHALL NOT fail the new-session creation

5.4 WHEN the service creates a new payment token because of an amount mismatch, THE old token SHALL be marked `is_active = False` and SHALL NOT be deleted (preserves audit trail of all generated payment links)

### Requirement 6: Public Payment Page Honours Partial Amount Override

**User Story:** As a customer scanning the kiosk QR for a partial payment, I want the payment page to show the partial amount I'm being asked to pay rather than the invoice's full outstanding balance, so I'm not confused or asked to pay more than expected.

#### Acceptance Criteria

6.1 THE `payment_tokens` table SHALL gain an optional column `amount_override NUMERIC(12,2) NULL` (nullable so existing rows remain unaffected) — populated when the partial-amount flow generates a token, NULL when the full-balance flow generates one

6.2 WHEN `GET /api/v1/public/pay/{token}` resolves a token, THE endpoint SHALL include in the response `balance_due` set to `payment_token.amount_override` if non-null, otherwise `invoice.balance_due` (existing behaviour)

6.3 WHEN `GET /api/v1/public/pay/{token}` resolves a token with `amount_override` set, THE response SHALL also include a new field `is_partial_payment: true` (boolean, defaults to `false` when `amount_override` is null) so the public payment page can display a banner clarifying "You are paying a partial amount of $X. Outstanding balance after this payment will be $Y."

6.4 WHEN `POST /api/v1/public/pay/{token}/update-surcharge` recomputes the surcharge on payment-method change, THE endpoint SHALL use `payment_token.amount_override` if non-null as the surcharge base AND as the PI's pre-surcharge component, so the gross PI amount on Stripe always equals `partial + surcharge_on_partial`. The existing surcharge gross-up formula `(amount × p + fixed) / (1 − p)` SHALL be applied to the partial amount, not to the invoice balance

6.5 WHEN the public payment page renders for a partial token, THE customer-facing UI SHALL show the existing payment-summary block ("Subtotal", "Surcharge", "Total") with Subtotal labelled as "Amount Due (Partial)" rather than "Amount Due" so the customer is unambiguously aware they are not paying the whole invoice

### Requirement 7: Multi-Partial Payment Support and Cumulative Settlement

**User Story:** As a staff member splitting a $300 invoice across three $100 partial card payments at the kiosk, I want each partial to record correctly and the invoice to flip to `paid` only after the third partial settles the balance — without manual reconciliation.

#### Acceptance Criteria

7.1 WHEN the existing `handle_stripe_webhook` receives a `payment_intent.succeeded` or `checkout.session.completed` event for a partial QR PaymentIntent, THE handler SHALL behave exactly as it does today: extract `original_amount` from metadata, subtract surcharge, cap at `invoice.balance_due`, INSERT a `Payment` row, increment `invoice.amount_paid`, decrement `invoice.balance_due`, and flip status to `partially_paid` (if balance > 0) or `paid` (if balance = 0). **No code change to the webhook handler.**

7.2 WHEN the second partial QR session is created on an invoice already in `partially_paid` status, THE service SHALL accept and process the request normally — the status check `invoice.status in ("issued", "partially_paid", "overdue")` already permits this

7.3 WHEN the second partial QR PaymentIntent succeeds, THE existing webhook handler's idempotency guard (PI ID uniqueness check) SHALL allow the second partial through because each partial session has a distinct `stripe_payment_intent_id`

7.4 WHEN a partial amount is supplied that exactly equals the current `invoice.balance_due`, THE webhook handler SHALL flip the invoice status to `paid` (status transition `partially_paid → paid` or `issued → paid` already supported)

7.5 WHEN the org user views InvoiceDetail after a partial settles, THE Payments tab SHALL list each partial payment as its own row with its own `payment_method_type`, `surcharge_amount`, and `stripe_payment_intent_id` (existing UI handles this today since the Payments table already supports multiple rows per invoice)

### Requirement 8: Amount Validation Guard on Stripe Minimum and Surcharged Total

**User Story:** As a system operator, I want the partial flow to refuse amounts that would cause Stripe to reject the PaymentIntent at creation time so the staff member gets immediate, clear feedback rather than a cryptic Stripe error after the customer scans the QR.

#### Acceptance Criteria

8.1 THE service SHALL validate that `resolved_amount + max_possible_surcharge >= stripe_min_for_currency(invoice.currency)` where `max_possible_surcharge` is computed using the highest enabled surcharge rate from the org's `surcharge_rates` settings — to prevent a sub-minimum partial from becoming a sub-minimum gross when `surcharge_enabled=False`

8.2 IF the partial amount alone is less than `stripe_min_for_currency(invoice.currency)`, THEN the service SHALL reject the request with HTTP 400 (this is also enforced at Requirement 3.3; this requirement reaffirms the floor behaviour)

8.3 WHEN the org has `surcharge_enabled=False`, THE Stripe minimum floor SHALL apply to the partial amount itself (no gross-up to consider)

8.4 WHEN the org has `surcharge_enabled=True`, THE Stripe minimum floor SHALL still apply to the partial amount itself (the surcharge can only increase the gross, never decrease it, so a partial above the minimum always produces a gross above the minimum)

### Requirement 9: Audit Log Coverage for Partial QR Sessions

**User Story:** As a compliance reviewer, I want partial QR payment requests to be visible in the audit log so I can reconstruct exactly when and by whom each partial was initiated.

#### Acceptance Criteria

9.1 WHEN `create_qr_session_for_existing_invoice` successfully creates a new partial PaymentIntent, THE service SHALL emit a `payment.qr_session_created` audit log entry with `entity_type="invoice"`, `entity_id=invoice.id`, `org_id`, `user_id`, `before_value=null`, and `after_value` containing `{stripe_payment_intent_id, amount, balance_due_at_request_time, is_partial_payment}` so the partial-vs-full distinction and the amount are recorded

9.2 WHEN `create_qr_session_for_existing_invoice` reuses an existing session (Requirement 5.1), THE service SHALL NOT emit a duplicate audit log entry — the original creation already recorded the session

9.3 WHEN `create_qr_session_for_existing_invoice` cancels a stale existing PaymentIntent (Requirement 5.3), THE service SHALL emit a `payment.qr_session_superseded` audit log entry with `entity_id=invoice.id`, `before_value={stripe_payment_intent_id: <old>}`, `after_value={stripe_payment_intent_id: <new>, reason: "amount_changed"}` so the lifecycle of the orphan PI is auditable

9.4 THE existing `payment.stripe_webhook_received` audit log entry on payment receipt SHALL continue to fire unchanged — its current `payment_amount`, `surcharge_amount`, `amount_paid`, `balance_due`, `invoice_status` payload already covers the partial case

### Requirement 10: Concurrent Modal and Concurrent Session Handling

**User Story:** As an organisation with multiple staff members, I want simultaneous QR payment attempts from different users on the same invoice to behave predictably without one user's session silently overwriting another's, and I want the kiosk to display only one QR session at a time.

#### Acceptance Criteria

10.1 WHEN two staff members each click "QR Payment" on the same invoice within seconds AND each chooses different amounts in their respective modals, THE second `POST /api/v1/payments/qr-session/existing` call SHALL succeed by replacing the first user's `pending_qr_sessions` row (current behaviour: one row per org via the unique constraint on `org_id`) and SHALL cancel the first user's PaymentIntent (Requirement 5.3)

10.2 WHEN the first user's waiting popup is still open after the second user's session replaced it, THE first user's `GET /api/v1/payments/qr-session/{session_id}/status` poll SHALL return `expired` (because the Stripe PI was cancelled by the second call) and the first user's popup SHALL surface a non-blocking message "This QR session was superseded by a newer payment attempt"

10.3 WHEN a partial payment completes via webhook AND a different QR session was created for the same invoice in the meantime, THE webhook SHALL still record the completed partial against the invoice (idempotency keyed by `stripe_payment_intent_id`, not by `pending_qr_sessions.session_id`) so the partial is not lost

10.4 WHEN the existing `expire_qr_session` endpoint is called on a partial QR session, THE behaviour SHALL be identical to today — Stripe PI cancellation + delete `pending_qr_sessions` row — with no special-casing for partial vs full

### Requirement 11: Partial-Payment-Aware Email Notifications

**User Story:** As a customer who paid only part of an invoice, I want the receipt email I receive to clearly state that this was a partial payment and show the remaining balance, so I'm not confused about whether I still owe money.

#### Acceptance Criteria

11.1 WHEN the existing post-payment email (`email_invoice` invoked by `record_cash_payment_endpoint` or the Stripe webhook handler) fires after a payment is recorded, THE email subject SHALL distinguish full vs partial:
  - Full payment (invoice.status flipped to `paid`): subject remains "Invoice {number} paid — receipt from {org_name}" or whatever the active invoice template renders
  - Partial payment (invoice.status remains `partially_paid` or `overdue` after recording): subject SHALL be "Partial payment received for invoice {number} — ${partial_amount}"

11.2 WHEN the email body renders for a partial-payment receipt, THE body SHALL include a "Payment received: $X.XX" line and a "Remaining balance: $Y.YY" line above the regular invoice content, so the customer immediately sees both values without scanning the PDF

11.3 THE attached PDF SHALL be unchanged — it continues to render the invoice in its current state (with `amount_paid`, `balance_due`, payment history table). The email body is the partial-vs-full distinguisher; the PDF is the historical document

11.4 WHEN `email_invoice` is invoked and the most recent `Payment` row for the invoice has `amount < invoice.total` AND `invoice.balance_due > 0`, THE function SHALL switch to the partial-payment subject + body. Detection is based on invoice state at email time, not on a flag passed by the caller — this keeps the call sites unchanged

11.5 WHEN the org has a custom email template configured for `template_type = "invoice_send"`, THE custom template's subject and body SHALL be rendered as today (no override). Partial-payment phrasing only applies when the org is using the hardcoded default template — orgs that customise their template are assumed to have considered partial-payment wording themselves


## Quality Attribute Requirements

- **Reversibility:** A partial QR payment that completes successfully cannot be reversed by re-issuing a different partial — refunds use the existing refund flow (`process_refund`), which is unchanged by this feature.
- **Compliance:** The partial flow respects the per-currency Stripe minimum (e.g. $0.50 NZD) using the same source as Stripe's API itself; the surcharge gross-up formula introduced in 1.10.5 continues to apply, ensuring the merchant nets exactly the partial amount typed.
- **Observability:** Three new audit log entries (`payment.qr_session_created`, `payment.qr_session_superseded`, plus the existing webhook entry) provide a full lifecycle view per partial. Receipt emails clearly distinguish partial-payment from full-payment via subject and body content (Requirement 11).
- **Backwards compatibility:** Existing API contract for `POST /api/v1/payments/qr-session/existing` is preserved when `amount` is omitted; existing kiosk and waiting-popup polling endpoints are unchanged in shape; existing webhook handler is unchanged in code; existing custom email templates render as today.
- **No Stripe schema dependency:** The feature relies only on PaymentIntent's existing `amount`, `metadata`, `application_fee_amount` fields — no Stripe Beta features, no new event types, no new webhook subscriptions required.
- **Idempotency:** Webhook duplicate-event delivery (Stripe sends at-least-once) is protected by the existing `stripe_payment_intent_id` uniqueness guard. Spec includes explicit duplicate-event tests so the guard is verified to cover partial-payment flows the same way it covers full payments.
