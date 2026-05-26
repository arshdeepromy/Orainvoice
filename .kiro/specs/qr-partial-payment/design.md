# Design Document: QR Partial Payment

## Overview

The existing kiosk QR payment flow (`kiosk-qr-payment` spec, shipped in 1.10.x) collects the **full** outstanding balance of an invoice in one PaymentIntent. This feature adds the ability for an org user to choose, at the moment of clicking "QR Payment", whether the upcoming kiosk QR will collect the full balance or only a partial amount typed in by the user. Choosing Full preserves the pre-feature behaviour exactly. Choosing Partial routes a smaller amount through the same Stripe → kiosk → webhook pipeline.

The feature exploits two pre-existing properties of the system:

1. **The webhook handler is already partial-aware.** `handle_stripe_webhook` in `app/modules/payments/service.py` reads `metadata.original_amount`, increments `invoice.amount_paid` by that value, decrements `invoice.balance_due`, and flips status to `partially_paid` (or `paid` if the partial settles). No code change is required there.
2. **PaymentIntent supports any amount in cents.** Stripe's API has no notion of "invoice total" — it only knows the `amount` parameter we hand it. The hard-coding of `int(invoice.balance_due * 100)` is purely a server-side decision.

The design therefore concentrates on three surfaces:

- **The org user UI**, which intercepts the existing QR Payment click with a small modal and conditionally adds an `amount` field to the existing `POST /api/v1/payments/qr-session/existing` payload.
- **The backend service** `create_qr_session_for_existing_invoice`, which gains an optional `amount` parameter, validates it, scales the PaymentIntent and application fee proportionally, and skips its own reuse branch when the new amount differs from the existing PI's amount.
- **The public payment page contract**, where a new `payment_tokens.amount_override` column lets the customer-facing page surface the partial amount as authoritative — including for the surcharge recompute that fires when the customer picks a payment method.

The webhook handler, the kiosk pending-session display, the kiosk session-status poll, and all customer-facing PI cancellation/expiration paths remain byte-for-byte identical.

**Key design decisions:**

- **Default to Full payment.** The Amount_Selection_Modal pre-selects Full so a user who absent-mindedly clicks Continue gets pre-feature behaviour without a network change.
- **Use a per-token override column instead of a per-invoice override.** An invoice can have multiple partial payment tokens generated over its life; storing the partial amount on the invoice would require constant overwrites and risks race conditions. Per-token is naturally append-only and matches the PaymentIntent's lifecycle.
- **Use `metadata.original_amount` as the bridge between PI amount and invoice payment record.** This metadata field is already populated by both the create-session and the update-surcharge endpoints; the webhook already reads it. Setting it to the partial amount is a one-line change with the right ripple.
- **Cancel orphan PaymentIntents proactively.** When a second QR Payment click on the same invoice creates a new PI, Stripe's books otherwise carry an unfunded "requires_payment_method" PI forever. Cancelling explicitly via `POST /v1/payment_intents/{id}/cancel` keeps the Stripe dashboard clean.
- **Keep the Reuse_Branch_Guard.** The current code reuses the existing `payment_page_url` + `stripe_payment_intent_id` when present. We narrow this to "reuse only when the existing PI's amount equals the requested amount" — the common case (clicking QR Payment twice without changing amount) still benefits from reuse.
- **No new database table.** All persistence uses existing tables: a new column on `payment_tokens`, no row in `pending_qr_sessions` shape change, no change to `invoices`, no change to `payments`.

## Architecture

```mermaid
sequenceDiagram
    participant Staff as Staff (Org User)
    participant Modal as Amount Selection Modal
    participant Backend as Backend (FastAPI)
    participant DB as Database
    participant Stripe as Stripe API
    participant Kiosk as Kiosk Screen
    participant Customer as Customer (Phone)

    Staff->>Modal: Click "QR Payment" on InvoiceList/InvoiceDetail
    Modal->>Modal: Render with Full pre-selected
    alt Full Payment chosen
        Staff->>Modal: Click Continue
        Modal->>Backend: POST /payments/qr-session/existing {invoice_id}
        Note over Backend: amount field absent → resolved_amount = invoice.balance_due
    else Partial Payment chosen
        Staff->>Modal: Type amount, click Continue
        Modal->>Modal: Frontend validate (>= $0.50, <= balance_due, 2dp)
        Modal->>Backend: POST /payments/qr-session/existing {invoice_id, amount}
        Note over Backend: amount field present → validate + use as resolved_amount
    end

    Backend->>DB: SELECT invoice FOR UPDATE (existing pattern)
    Backend->>Backend: Validate resolved_amount <= invoice.balance_due
    Backend->>Backend: Validate resolved_amount >= stripe_min_for_currency(invoice.currency)
    Backend->>DB: SELECT existing payment_token + invoice.stripe_payment_intent_id
    alt Same amount as existing PI → reuse
        Backend->>DB: Refresh pending_qr_sessions row only
        Backend-->>Modal: {session_id, amount: resolved_amount, ...}
    else Different amount or no existing PI → create new
        Backend->>Stripe: Cancel old PI if exists (fire-and-forget on error)
        Backend->>Stripe: POST /v1/payment_intents (amount=resolved_amount*100, application_fee_amount=fee*resolved_amount, metadata.original_amount=resolved_amount, metadata.is_partial_payment="true" if partial)
        Stripe-->>Backend: {id, client_secret}
        Backend->>DB: UPDATE invoice SET stripe_payment_intent_id, payment_page_url
        Backend->>DB: INSERT payment_tokens (token, amount_override=resolved_amount if partial else NULL)
        Backend->>DB: UPDATE old payment_token SET is_active=False
        Backend->>DB: DELETE existing pending_qr_sessions WHERE org_id; INSERT new
        Backend->>DB: INSERT audit_log (payment.qr_session_created [+ payment.qr_session_superseded if old PI cancelled])
        Backend-->>Modal: {session_id, amount: resolved_amount, invoice_number, expires_at}
    end

    Modal->>Modal: Show waiting popup with resolved_amount
    Note over Modal: Existing waiting-popup polling continues unchanged

    loop Kiosk polls every 2-3s (existing flow)
        Kiosk->>Backend: GET /payments/qr-session/pending
        Backend->>DB: SELECT pending_qr_sessions WHERE org_id
        Backend-->>Kiosk: {amount: resolved_amount, ...} (smaller for partial)
    end

    Customer->>Customer: Scan kiosk QR, opens public payment page
    Customer->>Backend: GET /public/pay/{token}
    Backend->>DB: SELECT payment_token, invoice
    Note over Backend: Resolve display amount = payment_token.amount_override ?? invoice.balance_due
    Backend-->>Customer: {balance_due: resolved_amount, is_partial_payment: bool, ...}

    Customer->>Backend: Selects payment method → POST /public/pay/{token}/update-surcharge
    Backend->>Backend: Compute surcharge against payment_token.amount_override ?? balance_due
    Backend->>Stripe: Update PI amount = resolved + surcharge_on_resolved
    Backend-->>Customer: {surcharge_amount, total_amount}

    Customer->>Stripe: Confirm payment
    Stripe->>Backend: webhook payment_intent.succeeded
    Note over Backend: Existing handle_stripe_webhook<br/>amount = metadata.original_amount = resolved_amount<br/>invoice.amount_paid += resolved<br/>invoice.balance_due -= resolved<br/>status → partially_paid OR paid
    Backend->>DB: INSERT payment row (existing flow)
    Backend->>DB: DELETE pending_qr_sessions

    alt Customer paid full balance via partial coincidence
        Note over Backend: invoice.balance_due == 0 → status = "paid"
    else Customer paid only some
        Note over Backend: invoice.balance_due > 0 → status = "partially_paid"<br/>Org user can repeat QR flow for next partial
    end
```

## Components and Interfaces

### Backend Components

#### Modified — `app/modules/payments/schemas.py`

`QrSessionExistingInvoiceRequest` gains an optional `amount` field:

```python
class QrSessionExistingInvoiceRequest(BaseModel):
    invoice_id: uuid.UUID = Field(..., description="ID of the existing invoice")
    amount: Decimal | None = Field(
        None,
        gt=Decimal("0"),
        description=(
            "Optional partial amount. When omitted, the QR session bills "
            "the invoice's full balance_due (existing behaviour). When "
            "provided, must be >= $0.50 and <= invoice.balance_due."
        ),
    )

    @field_validator("amount")
    @classmethod
    def _quantize_to_cents(cls, v: Decimal | None) -> Decimal | None:
        if v is None:
            return None
        # Reject more than 2dp at schema level so we never silently
        # round customer-typed cents.
        if v.as_tuple().exponent < -2:
            raise ValueError("Amount must have at most 2 decimal places")
        return v.quantize(Decimal("0.01"))
```

The optional default keeps the contract backwards-compatible.

A new typed response field is **not** added — `QrPaymentSessionResponse.amount` already carries the billing amount and the frontend already consumes it.

#### Modified — `app/modules/payments/service.py::create_qr_session_for_existing_invoice`

The function gains a `partial_amount: Decimal | None = None` keyword arg. Internal flow:

```python
async def create_qr_session_for_existing_invoice(
    db, *, org_id, user_id, invoice_id,
    partial_amount: Decimal | None = None,
    base_url: str | None = None,
) -> dict:
    # 1. Existing: fetch invoice, status check, balance_due > 0 check.
    # 2. NEW: resolve billing amount.
    if partial_amount is not None:
        min_amount = stripe_min_for_currency(invoice.currency)
        if partial_amount < min_amount:
            raise ValueError(
                f"Partial amount must be at least {min_amount} {invoice.currency or 'NZD'}"
            )
        if partial_amount > invoice.balance_due:
            raise ValueError(
                f"Partial amount cannot exceed the outstanding balance "
                f"of ${invoice.balance_due}"
            )
        resolved_amount = partial_amount.quantize(Decimal("0.01"))
        is_partial = True
    else:
        resolved_amount = invoice.balance_due.quantize(Decimal("0.01"))
        is_partial = False

    # 3. NEW: narrowed reuse guard — only reuse if existing PI's
    #    amount matches resolved_amount.
    existing_token, existing_pi_amount_cents = await _existing_token_and_pi_amount(
        db, invoice_id
    )
    target_cents = int(resolved_amount * 100)
    if existing_token and existing_pi_amount_cents == target_cents:
        # Existing reuse path: just refresh pending_qr_sessions
        return await _refresh_pending_session(db, org_id, invoice, existing_token)

    # 4. NEW: cancel orphan PI before creating a new one.
    if invoice.stripe_payment_intent_id:
        try:
            await _cancel_payment_intent(
                pi_id=invoice.stripe_payment_intent_id,
                stripe_account_id=org.stripe_connect_account_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to cancel orphan PaymentIntent %s: %s; continuing",
                invoice.stripe_payment_intent_id, exc,
            )
        await _emit_audit_log(
            db, org_id, user_id, "payment.qr_session_superseded",
            entity_id=invoice.id,
            before={"stripe_payment_intent_id": invoice.stripe_payment_intent_id},
            after={"reason": "amount_changed"},
        )

    # 5. Existing: compute application_fee_amount, but on resolved_amount.
    fee_percent = await get_application_fee_percent()
    amount_cents = target_cents
    application_fee_amount = (
        int(amount_cents * fee_percent / 100) if fee_percent else None
    )

    # 6. Existing: create PI on Stripe.
    # NOTE: create_payment_intent must first be extended to accept
    # `extra_metadata` (see task 5.5) — the current signature only
    # writes `invoice_id` and `platform` to metadata. Setting
    # `original_amount`, `is_partial_payment`, and `source: "kiosk_qr"`
    # AT CREATION (rather than waiting for update-surcharge) closes a
    # pre-existing webhook-detection bug and gives the partial flow
    # an authoritative metadata fallback.
    pi_result = await create_payment_intent(
        amount=amount_cents,
        currency=invoice.currency or "NZD",
        invoice_id=str(invoice_id),
        stripe_account_id=org.stripe_connect_account_id,
        application_fee_amount=application_fee_amount,
        extra_metadata={
            "source": "kiosk_qr",
            "original_amount": str(resolved_amount),
            "is_partial_payment": "true" if is_partial else "false",
        },
    )

    # 7. Existing: generate payment token. NEW: if partial, set amount_override.
    token, payment_url = await generate_payment_token(
        db, org_id=org_id, invoice_id=invoice_id, base_url=base_url,
        amount_override=resolved_amount if is_partial else None,
    )

    # 8. Mark old token inactive (do NOT delete — preserve audit trail).
    if existing_token:
        existing_token.is_active = False
        await db.flush()

    # 9. Existing: update invoice fields, upsert pending_qr_sessions, audit log.
    invoice.stripe_payment_intent_id = pi_result["payment_intent_id"]
    invoice.payment_page_url = payment_url
    # ... (existing logic for invoice_data_json, pending_qr_sessions row)

    await _emit_audit_log(
        db, org_id, user_id, "payment.qr_session_created",
        entity_id=invoice.id,
        before=None,
        after={
            "stripe_payment_intent_id": pi_result["payment_intent_id"],
            "amount": str(resolved_amount),
            "balance_due_at_request_time": str(invoice.balance_due),
            "is_partial_payment": is_partial,
        },
    )

    return {
        "session_id": pi_result["payment_intent_id"],
        "invoice_id": invoice_id,
        "invoice_number": invoice.invoice_number or str(invoice.id),
        "amount": resolved_amount,
        "amount_cents": target_cents,
        "expires_at": ...,
        "currency": invoice.currency or "NZD",
    }
```

`STRIPE_MIN_BY_CURRENCY` (a `dict[str, Decimal]` keyed by ISO currency code) and the `stripe_min_for_currency(currency)` helper are added as module-level definitions in `app/modules/payments/service.py`. The codebase has no equivalent constant today (verified via `grep -rn "STRIPE_MIN" app/`), so this is fresh. Per-currency from day one means multi-currency invoicing (a separate future spec) only needs to add an entry to the dict — no code change here. Source: [Stripe — minimum and maximum charge amounts](https://stripe.com/docs/currencies#minimum-and-maximum-charge-amounts).

#### Modified — `app/modules/payments/router.py::create_qr_session_existing_invoice_endpoint`

Threads the new field through:

```python
result = await create_qr_session_for_existing_invoice(
    db,
    org_id=org_uuid,
    user_id=user_uuid,
    invoice_id=payload.invoice_id,
    partial_amount=payload.amount,        # NEW
    base_url=request.headers.get("origin") or None,
)
```

#### Modified — `app/modules/payments/token_service.py::generate_payment_token`

Gains `amount_override: Decimal | None = None` parameter. When non-null, sets the new column on the inserted row. When null, the column is NULL.

#### Modified — `app/modules/payments/models.py::PaymentToken`

Adds:

```python
amount_override: Mapped[Decimal | None] = mapped_column(
    Numeric(12, 2), nullable=True,
    comment="Partial amount for QR partial-payment flow; "
            "NULL means use invoice.balance_due",
)
last_pi_amount_cents: Mapped[int | None] = mapped_column(
    BigInteger, nullable=True,
    comment="Cached cents value of the PaymentIntent's last-known amount, "
            "used by create_qr_session_for_existing_invoice for the "
            "same-amount-reuse decision without a Stripe API call. "
            "Updated on every PI create or update-surcharge.",
)
```

The `last_pi_amount_cents` cache eliminates the need for a synchronous Stripe `GET /v1/payment_intents/{id}` call on every QR Payment click. The cache is refreshed on every code path that changes the PI amount (initial create + surcharge update), so it stays accurate. Trade-off: a manual Stripe Dashboard edit by the merchant goes out-of-band and is not detected — accepted as a documented edge case.

#### Modified — `app/modules/payments/public_router.py::get_payment_page_data`

Resolves the display amount:

```python
resolved_balance = (
    payment_token.amount_override
    if payment_token.amount_override is not None
    else invoice.balance_due
)
is_partial = payment_token.amount_override is not None
```

The `PaymentPageResponse` schema (located at `app/modules/payments/schemas.py:364` — note: not `PublicPaymentPageResponse` as originally drafted) gains `is_partial_payment: bool = False`. The `balance_due` field remains the same key but holds `resolved_balance`.

#### Modified — `app/modules/payments/public_router.py::update_surcharge`

Uses the resolved amount instead of `invoice.balance_due`:

```python
resolved_balance = (
    payment_token.amount_override
    if payment_token.amount_override is not None
    else invoice.balance_due
)
surcharge = get_surcharge_for_method(
    resolved_balance, surcharge_method, rates,
)
total_amount = resolved_balance + surcharge
# Stripe PI update payload — original_amount stays as resolved_balance
payload = {
    "amount": str(int(total_amount * 100)),
    "metadata[surcharge_amount]": str(surcharge),
    "metadata[surcharge_method]": body.payment_method_type,
    "metadata[original_amount]": str(resolved_balance),
}
```

#### New Helper — `_cancel_payment_intent`

Direct Stripe API call to `POST /v1/payment_intents/{id}/cancel`, scoped to the org's connected account. Mirrors the pattern of the existing `expire_qr_session` and `update_surcharge` direct API calls. Errors are logged and swallowed (cancellation is best-effort).

### Database Migration

New Alembic migration. The implementer must verify the current head before naming the file. As of spec authoring (2026-05-26), the latest revision is `0192_b2b_fleet_portal_rls.py`, so the next is `0193`. If the head has moved before implementation begins, increment accordingly:

```python
def upgrade():
    op.add_column(
        "payment_tokens",
        sa.Column(
            "amount_override",
            sa.Numeric(12, 2),
            nullable=True,
            comment=(
                "Partial-payment amount for the QR partial-payment flow. "
                "NULL means use invoice.balance_due (default behaviour)."
            ),
        ),
    )
    op.add_column(
        "payment_tokens",
        sa.Column(
            "last_pi_amount_cents",
            sa.BigInteger(),
            nullable=True,
            comment=(
                "Cached cents value of the PaymentIntent's last-known "
                "amount, used by create_qr_session_for_existing_invoice "
                "to make a same-amount-reuse decision without a "
                "synchronous Stripe API call. Refreshed on every "
                "successful PI create or update-surcharge call."
            ),
        ),
    )

def downgrade():
    op.drop_column("payment_tokens", "last_pi_amount_cents")
    op.drop_column("payment_tokens", "amount_override")
```

Both columns are nullable with no server default, so existing rows automatically get NULL — backwards compatible. No RLS changes needed (RLS policy is on `org_id`, unaffected by the new columns).

**Mandatory post-create step (per `database-migration-checklist.md`):**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head
docker exec invoicing-postgres-1 psql -U postgres -d workshoppro -c "\d payment_tokens"
```

The migration must be applied to dev DB immediately and verified before any code that references the new columns is merged.

### Frontend Components

#### New — `frontend/src/pages/invoices/QrPaymentAmountModal.tsx`

A controlled modal accepting:

```typescript
interface QrPaymentAmountModalProps {
  open: boolean
  onClose: () => void
  invoice: { id: string; balance_due: number | string; invoice_number: string | null }
  onContinue: (amount: number | null) => Promise<void>
  loading?: boolean
}
```

Renders:

- Modal header: "QR Payment for {invoice_number}"
- Body:
  - Two radio rows (`role="radiogroup"`): "Full payment ($X.XX)" pre-selected; "Partial payment".
  - When Partial selected, an `<input type="text" inputMode="decimal">` pre-filled with the formatted balance, with an inline error message below it.
- Footer: Cancel (left) + Continue (right, `disabled` when validation fails).
- Closes on backdrop click, Escape, or Cancel — all call `onClose` with no API call.
- Continue calls `onContinue(amount)` where `amount` is `null` for full or a positive `number` for partial. The parent owns the API call so the modal stays presentation-only.

Validation is inline:

- Empty / zero / NaN → error "Enter an amount", Continue disabled.
- < 0.50 → error "Amount must be at least $0.50", Continue disabled.
- > balance_due → error "Amount cannot exceed the outstanding balance of $X.XX", Continue disabled.
- Decimal places > 2 → silently truncated on input change (cursor preserved).

Touch targets: minimum 44×44 px (matches mobile-app steering on minimum tap targets).

Tests (Vitest + RTL):

- Pre-selected Full radio.
- Partial reveals input pre-populated with balance_due.
- Continue with Full calls `onContinue(null)`.
- Continue with Partial calls `onContinue(123.45)`.
- Continue disabled at boundary conditions.
- Backdrop and Escape both call onClose.

#### Modified — `frontend/src/pages/invoices/InvoiceList.tsx::handleQrPayment`

Replaces the direct API call with a modal-mediated flow:

```tsx
const [qrAmountModalOpen, setQrAmountModalOpen] = useState(false)

// Existing handleQrPayment is parameterless and reads `invoice` from outer scope
// (split-panel selected invoice). Preserve that pattern — change the body to
// open the modal instead of calling the API directly.
const handleQrPayment = () => {
  if (!invoice) return
  setQrAmountModalOpen(true)
}

const handleAmountModalContinue = async (amount: number | null) => {
  setQrPaymentLoading(true)
  setActionMessage('')
  try {
    const body = amount === null
      ? { invoice_id: selectedInvoiceForQr.id }
      : { invoice_id: selectedInvoiceForQr.id, amount: amount.toFixed(2) }
    const res = await apiClient.post<{ session_id: string; ... }>(
      '/payments/qr-session/existing',
      body,
    )
    setQrAmountModalOpen(false)
    setQrSessionData({
      session_id: res.data?.session_id ?? '',
      amount: Number(res.data?.amount ?? 0),
      invoice_number: res.data?.invoice_number ?? '',
    })
    setQrWaitingPopupOpen(true)
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setActionMessage(detail || 'Failed to create QR payment session.')
  } finally {
    setQrPaymentLoading(false)
  }
}
```

Mounted modal:

```tsx
{selectedInvoiceForQr && (
  <QrPaymentAmountModal
    open={qrAmountModalOpen}
    onClose={() => setQrAmountModalOpen(false)}
    invoice={{
      id: selectedInvoiceForQr.id,
      balance_due: selectedInvoiceForQr.balance_due,
      invoice_number: selectedInvoiceForQr.invoice_number,
    }}
    onContinue={handleAmountModalContinue}
    loading={qrPaymentLoading}
  />
)}
```

#### Modified — `frontend/src/pages/invoices/InvoiceDetail.tsx::handleQrPayment`

Same pattern as InvoiceList — replace the immediate POST with the modal-mediated flow. The existing `handleQrPayment` becomes the modal's `onContinue` callback.

#### Modified — `frontend/src/pages/public/InvoicePaymentPage.tsx`

Reads two new fields from the page-data response:

```tsx
const isPartial = data?.is_partial_payment ?? false
```

When `isPartial` is true:

- Subtotal label changes from "Amount Due" to "Amount Due (Partial)".
- A blue informational banner appears above the payment method picker: "You are paying a partial amount of ${balanceDue}. Please contact the business if you intended to pay the full balance."

#### Modified — `mobile/src/screens/auth/PublicPaymentScreen.tsx`

Mirror the desktop public payment page changes — same banner, same label tweak, same `is_partial_payment` field consumption.

### Pydantic Schema Changes Summary

```python
# QrSessionExistingInvoiceRequest — adds optional amount
class QrSessionExistingInvoiceRequest(BaseModel):
    invoice_id: uuid.UUID
    amount: Decimal | None = Field(None, gt=Decimal("0"))

# PaymentPageResponse — adds is_partial_payment (NOT a new class — extending the existing class at schemas.py:364)
class PaymentPageResponse(BaseModel):
    # ... existing fields
    is_partial_payment: bool = Field(False, description="True when token has an amount_override")
```

The Frontend `LinkedVehicleResponse`-style optional-field pattern keeps backwards compatibility with cached/older frontends.

## User Workflow Trace

### Full payment flow (default — preserves existing behaviour)

```
User on InvoiceDetail clicks "QR Payment"
  → QrPaymentAmountModal renders, Full pre-selected
  → User clicks Continue
  → POST /payments/qr-session/existing {invoice_id}
  → Backend: amount field absent → resolved = invoice.balance_due
  → New PI created (or existing PI reused if amounts match)
  → Pending session row inserted
  → Response: {session_id, amount: balance_due, invoice_number, expires_at}
  → Modal closes, QrPaymentWaitingPopup opens, kiosk picks up new session
  → Customer scans, pays, webhook flips invoice to paid
  → Org user's status poll detects paid, popup closes with green tick
```

### Partial payment flow

```
User on InvoiceDetail (invoice $300 balance) clicks "QR Payment"
  → Modal renders, Full pre-selected
  → User clicks Partial radio → amount input revealed, pre-filled "300.00"
  → User types "100.00", presses Continue
  → POST /payments/qr-session/existing {invoice_id, amount: "100.00"}
  → Backend: validates 0.50 <= 100.00 <= 300.00 → resolved = 100.00
  → Skips reuse branch if existing PI was for 300.00
  → Cancels old PI on Stripe (best-effort)
  → New PI created for 10000 cents, application_fee=fee_pct * 10000 / 100
  → metadata.original_amount = "100.00", metadata.is_partial_payment = "true"
  → New payment_token row with amount_override = 100.00, old token marked inactive
  → Audit log: payment.qr_session_superseded + payment.qr_session_created
  → Response: {session_id, amount: 100.00, invoice_number, expires_at}
  → Modal closes, popup opens showing "Waiting for $100.00 payment..."
  → Kiosk poll picks up amount=100.00, displays QR
  → Customer scans, picks Card on public payment page
  → POST /public/pay/{token}/update-surcharge → uses amount_override=100
  → Surcharge gross-up = (100 × 0.029 + 0.30) / 0.971 ≈ 3.30
  → PI updated to 10330 cents
  → Customer confirms; Stripe webhook fires
  → Webhook: amount = 103.30, surcharge = 3.30, pay_amount = 100.00
  → invoice.amount_paid: 0 → 100.00
  → invoice.balance_due: 300.00 → 200.00
  → invoice.status: issued → partially_paid
  → org user's popup detects success, closes
  → Invoice status now partially_paid; Org user can repeat for next $100
```

### Multi-partial cumulative settlement

After three $100 partials on a $300 invoice:

| Step | balance_due before | Partial | balance_due after | Status after |
|---|---|---|---|---|
| 1 | 300.00 | 100.00 | 200.00 | partially_paid |
| 2 | 200.00 | 100.00 | 100.00 | partially_paid |
| 3 | 100.00 | 100.00 | 0.00 | paid |

Each partial creates its own `Payment` row with its own `stripe_payment_intent_id`, `surcharge_amount`, and `payment_method_type`. The Payments tab on InvoiceDetail naturally displays three rows.

### Concurrent QR clicks on same invoice

```
Staff A clicks QR on invoice $300 → modal → Partial $100 → PI #1 ($100) created
Staff B (10s later) clicks QR on same invoice → modal → Partial $200 → 
  Backend: existing PI #1 amount differs from request → cancel PI #1 + audit log
  Backend: create PI #2 ($200) → audit log payment.qr_session_created
  Backend: replace pending_qr_sessions row (unique on org_id)
  
Staff A's waiting popup polls /payments/qr-session/{PI#1}/status
  → Stripe returns "canceled" → frontend shows non-blocking message:
    "This QR session was superseded by a newer payment attempt"
Staff B's waiting popup polls PI #2 → still active → kiosk shows $200 QR
Customer scans, pays $200 → webhook on PI #2 → invoice.balance_due 300 → 100
```

## Frontend Component Breakdown

### Navigation & Access

- No new routes (modal opens inline on existing InvoiceList and InvoiceDetail pages).
- No new lazy imports.
- Modal is unconditionally available wherever the existing QR Payment button is — same role gating as today (`org_admin`, `salesperson`).
- Mobile companion app **does NOT** include this feature in scope (mobile app spec excludes payment-collection workflows; staff use the desktop app).

### Pages and Modals Inventory

- **`QrPaymentAmountModal`** (NEW) — `frontend/src/pages/invoices/QrPaymentAmountModal.tsx`
  - Triggers: "QR Payment" button on InvoiceList row actions or InvoiceDetail toolbar.
  - Contains: radio group (Full | Partial), amount input (when Partial), validation message, Cancel + Continue buttons.
  - Closes via: X (top-right), backdrop click, Escape, Cancel button, Continue resolution.
  - Unsaved-changes guard: not applicable — there's nothing to lose; closing simply abandons the choice.
- **`InvoiceList`** (MODIFIED) — wires the modal between the QR button and the existing waiting popup.
- **`InvoiceDetail`** (MODIFIED) — same wiring as InvoiceList.
- **`InvoicePaymentPage` (public, web)** (MODIFIED) — adds banner and label change when `is_partial_payment=true`.
- **`PublicPaymentScreen` (mobile)** (MODIFIED) — same change as web for kiosk-scan parity.

### Error & Edge Case UI

- **400 from backend on amount validation failure** — frontend already validates client-side, so this should never happen in normal flow. If it does, the action message bar shows the backend's `detail` field verbatim.
- **502 from Stripe** — existing handling unchanged: error message displayed in action message bar.
- **Network failure during modal Continue** — modal stays open with error inline (does not close); user can retry.
- **Loading state** — Continue button shows spinner while the API call is in flight; modal cannot be closed during this state to prevent double-submit.

### Integration Points

- Adds modal between existing button click and existing popup, all on existing pages.
- No new sidebar items, no new top-nav items, no new settings tabs.
- No changes to kiosk UI components (the kiosk just reads the smaller `amount` from the existing pending-session response).

## Concurrency and Idempotency Strategy

### Same-amount idempotency (reuse path)

When the org user clicks QR Payment twice on the same invoice with the same amount, the second call:

1. Finds the existing `payment_page_url` and `stripe_payment_intent_id` on the invoice, plus the active `payment_tokens` row with its cached `last_pi_amount_cents`.
2. Compares the cached `last_pi_amount_cents` to the requested `int(resolved_amount * 100)` — **single DB read, no Stripe API call**.
3. On match: refreshes the `pending_qr_sessions` row (DELETE-INSERT in the same transaction to preserve the unique-on-org_id constraint) — no new PI, no new token.
4. Returns the same session_id and amount.

This makes the click idempotent and mirrors the pre-feature behaviour. The cached value is updated on every PI create (task 6.7) and every `update_surcharge` call (task 9.3), so it stays within one round-trip of truth without ever needing a synchronous Stripe lookup. Stripe Dashboard manual edits are an out-of-band workflow and accepted as a documented edge case (the cached value goes stale; the reuse decision could be wrong on the very next click).

### Different-amount cancellation flow

When the second click requests a different amount, the orphan PI is cancelled. Cancellation is via `POST /v1/payment_intents/{id}/cancel` with `cancellation_reason=abandoned`. If Stripe rejects (PI already in terminal state), we swallow the error after logging — the new PI is still created and the old row's audit trail remains intact via the audit log entry.

### Webhook race against in-flight cancellation

Stripe's PI cancellation is synchronous from Stripe's perspective, but a race is possible: PI just got `confirmed` by the customer the millisecond before our cancel arrives. Stripe handles this correctly — `cancel` on an already-confirmed PI returns 400 without affecting the payment, and the webhook for the successful payment fires normally. Our webhook handler's idempotency guard records the payment even though the PI is "no longer current" from our application's perspective. This is the right outcome — we never want to lose a real customer payment.

### Multi-partial idempotency

Each successful partial creates a distinct `Payment` row keyed by `stripe_payment_intent_id`. The webhook handler's existing `SELECT WHERE stripe_payment_intent_id = X AND is_refund = False` check rejects duplicates per-PI. Different partials have different PI IDs so they correctly do not collide.

### Database transaction shape

`create_qr_session_for_existing_invoice` runs within a single `get_db_session` transaction. Order of operations:

1. SELECT invoice FOR UPDATE (existing pattern, prevents concurrent partial requests on the same invoice from both creating PIs).
2. Validate amount.
3. (Optional) Cancel old PI on Stripe — outside DB transaction (Stripe API call, synchronous).
4. Create new PI on Stripe — outside DB transaction.
5. UPDATE invoice fields, INSERT payment_tokens, UPDATE old payment_token, DELETE/INSERT pending_qr_sessions, INSERT audit_log — all inside DB transaction.
6. Implicit commit on session.begin() exit.

If steps 3 or 4 fail mid-flight, the DB transaction rolls back — no orphan rows. If step 5 fails after a successful step 4, we have a Stripe PI with no DB rows pointing at it; a daily Stripe-reconciliation job is recommended (out of scope for this feature, separately tracked as ISSUE-XXX).

## Validation and Edge Cases

### Stripe minimum

Stripe's minimum varies by currency: $0.50 NZD/AUD/USD/EUR, £0.30 GBP, ¥50 JPY. The codebase has no equivalent constant today, so this spec adds a per-currency dict `STRIPE_MIN_BY_CURRENCY` and helper `stripe_min_for_currency(currency)` in `app/modules/payments/service.py`. Validation runs both at the schema level (`gt=0` enforced by Pydantic) and at the service level (`>= stripe_min_for_currency(invoice.currency)`). Going below the per-currency floor would cause Stripe to reject the PaymentIntent at creation with `amount_too_small` error code; the service-level check catches this earlier with a friendlier, currency-aware error message.

### Decimal rounding parity

Banker's rounding is used everywhere (matches the surcharge module). `quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)` is applied to the partial amount before comparison and before sending to Stripe. The frontend uses `toFixed(2)` for display only; the source of truth for cents is the backend's quantized Decimal.

### Currency

The current implementation only supports NZD because the org's connected Stripe account is configured for NZD. The new `amount` field is treated as NZD. Multi-currency support is out of scope for this feature — when added, the validation would check against a per-currency minimum.

### Surcharge gross-up interaction

Surcharge (introduced in 1.10.5) uses the gross-up formula `(amount × p + fixed) / (1 − p)`. When the user picks a payment method on the public page, the update-surcharge endpoint will apply this formula to `payment_token.amount_override` (the partial), not to `invoice.balance_due`. The merchant nets exactly the partial amount after Stripe's fee, just as for full payments.

Worked example (from the partial flow trace):

| Step | Amount |
|---|---|
| Partial typed | $100.00 |
| Surcharge (card 2.9% + $0.30) gross-up | $3.30 |
| PI gross | $103.30 |
| Stripe fee at 2.9% + $0.30 of gross | $3.30 |
| Merchant nets | $100.00 |
| Invoice payment recorded | $100.00 |
| invoice.amount_paid increments by | $100.00 |

### Surcharge disabled

When the org has `surcharge_enabled=False`, the public page renders a single "Total $X.XX" row equal to the partial amount. The PI is created for that amount only. The webhook still uses `metadata.original_amount` (the partial) and records exactly that against the invoice.

### Voided invoice between QR session creation and customer payment

If an org admin voids the invoice while the customer is mid-scan, the public page resolves the token, finds `invoice.status == "voided"`, and renders the existing "This invoice has been voided and is no longer payable" error. The PI remains in `requires_payment_method` state until 24h later when Stripe auto-cancels it (or our cleanup job cancels it). No payment is recorded.

### Customer pays after invoice fully paid via another channel

If invoice was already paid via cash/EFTPOS while the customer was scanning, the webhook handler's existing check `if invoice.status not in ("issued", "partially_paid", "overdue"): return ignored` correctly refuses to apply the partial. The customer's card is still charged — but at the existing `update-surcharge` step the public page would have rejected the payment as the invoice status changed. This race is theoretical (customer would need to pay both ways within seconds) and the existing behaviour matches what we want.

## Module Gating

This feature does not introduce module gating. The `payments` module gate already governs the QR Payment button visibility (today). Partial payment is a refinement of the existing payment flow, not a separate paid feature. If finer gating is desired later, it can be added via a feature flag (`partial_payments_enabled` on org settings) without architectural change — but is not part of this spec.

## Performance and Latency

- **Modal render** is purely client-side; no API calls until Continue.
- **Backend partial-amount validation** is two Decimal comparisons; trivial.
- **Stripe API calls per partial click**: one PI cancel (if old PI exists) + one PI create. ~300-600ms total in observed conditions, identical to the current full-payment flow's create call.
- **Reuse path** (same amount as existing PI): zero Stripe calls; pure DB. ~50ms.
- **Public payment page** gains one column read on `payment_tokens.amount_override`; negligible.

## Security

- **Server-side authoritative validation.** Frontend validates for UX but the backend independently enforces `0.50 <= amount <= invoice.balance_due`. A tampered request with `amount = -10` or `amount = invoice.balance_due * 100` is rejected at the schema or service layer.
- **No PII in audit log.** The new audit log entries record only IDs and amounts — no customer card data, no email, no phone.
- **Token reuse prevention.** Old payment_tokens are marked `is_active=False` on amount change so a customer who started with the old (full) link can no longer use it after the org user issues a partial-amount link.
- **Idempotency vs replay.** A malicious actor cannot replay an old QR by re-scanning — Stripe's PI confirmation is one-time, and the webhook handler's PI-uniqueness guard prevents double-recording.

## Test Coverage

### Backend (pytest + pytest-asyncio + Hypothesis)

- `test_qr_partial_amount_validation` — schema rejects `amount=0`, `amount=-5`, `amount` with 3+ decimal places.
- `test_qr_partial_amount_below_stripe_min` — service rejects `amount=0.49` with HTTP 400.
- `test_qr_partial_amount_above_balance` — service rejects `amount=balance + 0.01` with HTTP 400.
- `test_qr_partial_amount_omitted_uses_balance` — service with `amount=None` produces PI with `int(balance × 100)` cents and `amount_override=NULL` on the token.
- `test_qr_partial_amount_equals_balance_creates_partial_token` — service with explicit `amount=balance` still sets `is_partial_payment=true` metadata and `amount_override=balance` on the token (Req 2.4).
- `test_qr_partial_reuse_branch_same_amount` — second call with same amount reuses PI, no new token, no audit log.
- `test_qr_partial_reuse_branch_different_amount_cancels_old_pi` — second call with different amount cancels old PI, creates new token, marks old token inactive, emits both audit log entries.
- `test_qr_partial_reuse_branch_stripe_cancel_failure_continues` — Stripe cancel returns 400 → service still creates new PI and emits superseded audit entry.
- `test_qr_partial_application_fee_proportional` — fee = `int(partial × 100 × fee_pct / 100)`, not `int(balance × 100 × fee_pct / 100)`.
- `test_qr_partial_metadata_is_partial_payment_set` — metadata contains `is_partial_payment="true"` for partial, `"false"` for full.
- `test_public_pay_get_uses_amount_override` — `GET /public/pay/{token}` returns `balance_due == amount_override` and `is_partial_payment=true` when override set.
- `test_update_surcharge_uses_amount_override` — `POST /public/pay/{token}/update-surcharge` computes surcharge against `amount_override`, updates PI to `override + surcharge_on_override`.
- `test_webhook_records_partial_correctly` — partial PI confirmation produces a Payment row with `amount=partial`, `surcharge=correct`, invoice transitions to `partially_paid` and `balance_due` is decremented by exactly partial.
- `test_webhook_third_partial_settles_to_paid` — three sequential partials of (100, 100, 100) on a 300 invoice settle the balance to 0 and flip status to `paid`.

Property tests:

- **Property 1: Partial amount round-trip preserves cents.** For any `Decimal d` with at most 2dp where `0.50 ≤ d ≤ 99999.99`, `int(d * 100)` round-trips losslessly.
- **Property 2: Partial amount validation envelope.** For any `(amount, balance)` where `0 < amount ≤ balance` and `amount ≥ 0.50`, the service accepts the request. For any `(amount, balance)` outside this envelope, the service rejects with HTTP 400.
- **Property 3: Webhook records exactly partial.** For any partial amount $a$ and surcharge configuration $(p, f)$, after a successful payment, `invoice.balance_due_after = invoice.balance_due_before − a` (within 1¢ for rounding crumbs).

### Frontend (Vitest + React Testing Library)

- `QrPaymentAmountModal.test.tsx` — pre-selected Full radio, Partial reveals input, validation states, Continue enable/disable.
- `InvoiceList.test.tsx` — modified `handleQrPayment` flow asserts modal opens before API call, full passes `null`, partial passes typed value.
- `InvoiceDetail.test.tsx` — same as InvoiceList.
- `InvoicePaymentPage.test.tsx` — `is_partial_payment=true` shows banner and "Amount Due (Partial)" label.
- `PublicPaymentScreen.test.tsx` (mobile) — same as web.

## Code-Verified Assumptions and Corrections

The following section captures findings from a direct code audit (2026-05-26) of the actual implementation. The original spec made a few assumptions that don't match how the code is currently structured. Implementers must follow these corrected expectations.

### Pydantic schema names (verified)

- The public payment page response model is **`PaymentPageResponse`** (not `PublicPaymentPageResponse` as initially drafted). Located at `app/modules/payments/schemas.py:364`. Add `is_partial_payment: bool = False` to this class.
- The QR existing-invoice request model is **`QrSessionExistingInvoiceRequest`** at `app/modules/payments/schemas.py:481`. Confirmed match.
- The QR session create response is **`QrPaymentSessionResponse`** at `app/modules/payments/schemas.py:491`. Confirmed match.
- Frontend interface for the public page response is **`PaymentPageData`** in `frontend/src/pages/public/InvoicePaymentPage.tsx`. Add `is_partial_payment?: boolean` to that interface.

### `create_payment_intent` does not accept extra metadata (CRITICAL)

The function signature at `app/integrations/stripe_connect.py:301` is:

```python
async def create_payment_intent(
    *,
    amount: int,
    currency: str,
    invoice_id: str,
    stripe_account_id: str,
    application_fee_amount: int | None = None,
    shipping: dict | None = None,
) -> dict:
```

It writes only `metadata[invoice_id]` and `metadata[platform]` to the PI at creation time. The original spec assumed an `extra_metadata` parameter — that does NOT exist. Two options for the implementer:

- **Option A (recommended):** Add an `extra_metadata: dict[str, str] | None = None` parameter to `create_payment_intent`. When provided, append `metadata[KEY] = VALUE` form fields to the Stripe payload before the POST. This is a small, backwards-compatible signature extension — existing callers continue to work.
- **Option B:** After the PI is created, make a second Stripe call (`POST /v1/payment_intents/{id}` to update) that adds the metadata. Two API round-trips, slower, but no signature change.

The spec recommends Option A. Add this as a sub-task to task 6 (or as a new task 6.0 before the others).

### `metadata.original_amount` and `metadata.is_partial_payment` are NOT set at PI creation today

In the current code, `metadata.original_amount`, `metadata.surcharge_amount`, `metadata.surcharge_method`, and `metadata.source = "kiosk_qr"` are set ONLY by the `update-surcharge` endpoint when the customer picks a payment method on the public page (`app/modules/payments/public_router.py` ~line 565). The webhook reads those keys; if the customer never triggers `update-surcharge` (rare edge case but possible), the webhook's `is_qr_payment` detection falls back to the empty string and `original_amount_str` is None. That branch is currently broken-but-unobserved in production.

The partial-payment spec must:

- Set `metadata.original_amount = str(resolved_amount)` AT PI CREATION (via `extra_metadata` per Option A above), so the webhook can record the partial correctly even if `update-surcharge` is never called by the customer.
- Set `metadata.is_partial_payment = "true"` AT PI CREATION for the same reason. This is the explicit marker that future audit-log queries and webhook observers can filter on.
- Set `metadata.source = "kiosk_qr"` AT PI CREATION as a forward-fix for the existing `is_qr_payment` detection bug. Today this metadata is missing on PIs that bypass the surcharge update; setting it at creation closes the gap.

The `update-surcharge` endpoint will overwrite `original_amount` with `payment_token.amount_override or invoice.balance_due` — that's correct behaviour (post-method-pick, the gross is `original + surcharge`, so the webhook subtracts surcharge to get back to original). The CREATE-time metadata is the authoritative fallback for the no-surcharge-update path.

### The reuse-branch's PI-amount source is currently `int(invoice.balance_due * 100)`

Re-reading `create_qr_session_for_existing_invoice` at line 1466: the existing reuse path computes `amount_cents = int(invoice.balance_due * 100)` from `invoice.balance_due`, NOT from any cached or live PI value. The PI's actual amount on Stripe could differ if `update-surcharge` was called by a customer (PI now reflects gross including surcharge) — in that case the existing code already returns a stale `amount_cents` to the kiosk. This is a pre-existing minor bug.

For the partial flow, the spec's `last_pi_amount_cents` cache solves this cleanly: on PI create or on `update-surcharge` rewrite, write the cents value back to `payment_tokens.last_pi_amount_cents`. The reuse decision compares `last_pi_amount_cents` (cached truth) vs `target_cents` (request). Backwards-compatible: when the column is NULL (existing rows pre-migration), treat as cache miss and fall through to create-new path.

### Stale `invoice.stripe_payment_intent_id` after a completed payment (CRITICAL)

The webhook handler at `app/modules/payments/service.py:920-933` clears the `pending_qr_sessions` row after a successful payment but does NOT clear `invoice.stripe_payment_intent_id` or `invoice.payment_page_url`. After the first partial settles, the invoice still carries a PI ID that Stripe considers `succeeded` and refuses to update.

**Implication for the partial flow:** When the org user clicks "QR Payment" for the second partial, the existing reuse-branch code (line 1448) sees `invoice.payment_page_url` and `invoice.stripe_payment_intent_id` are both set, finds an active payment_token (because new tokens weren't generated), and tries to reuse — but the underlying PI is `succeeded`. Stripe will reject any subsequent `update_surcharge` call on it with a `payment_intent_unexpected_state` error.

The spec's existing fix (compare cached cents to target cents) needs an additional check: **if the cached PI is for a completed/canceled state, also fall through to create-new**. Easiest implementation: store the PI's last-known status alongside the cached cents, OR skip the reuse path when the invoice's cached `last_pi_amount_cents` differs from the requested target (which it WILL, because `partial #2` requests a different amount than `partial #1` settled).

**Decision for the spec:** the existing `last_pi_amount_cents != target_cents` check IS sufficient for the multi-partial case, because the second partial necessarily has a different amount than the first. We don't need a separate status field. But we MUST also clear `invoice.stripe_payment_intent_id` and `invoice.payment_page_url` in the webhook AFTER the partial is recorded, so the next call doesn't enter the reuse path at all. Add this as task 18.

Add a new task:

- [ ] 18. Clear stale invoice.stripe_payment_intent_id and payment_page_url after webhook records a payment
  - [ ] 18.1 In `handle_stripe_webhook` (after `clear_pending_qr_session`), also clear the invoice's PI fields:
    - `invoice.stripe_payment_intent_id = None`
    - `invoice.payment_page_url = None`
    - Clear `invoice.invoice_data_json["stripe_client_secret"]` if set
    - This is safe because after a successful payment the PI is in a terminal state and cannot be reused for further payments. Clearing makes the next `create_qr_session_for_existing_invoice` call always take the create-new path
    - Without this, second-partial creation goes into the reuse branch and tries to update a completed PI on Stripe, returning a `payment_intent_unexpected_state` error
    - _Requirements: 7.1, 7.2 (multi-partial settlement), regression-prevention for existing reuse-branch bug_
  - [ ] 18.2 Add unit test `test_webhook_clears_stale_pi_fields` — after webhook records a payment, assert `invoice.stripe_payment_intent_id is None` and `invoice.payment_page_url is None`

### `clear_pending_qr_session` already exists

The function at `app/modules/payments/service.py:1896` is unchanged. The webhook calls it correctly. No spec changes needed for that pathway.

### Frontend handler signature: existing pattern uses outer-scope `invoice`

The current `handleQrPayment` in both `InvoiceList.tsx:841` and `InvoiceDetail.tsx:577` is parameter-less and reads `invoice` from outer state (the currently selected invoice in split-panel, or the route-driven `invoice` in InvoiceDetail). The spec's `handleQrPaymentClick(invoice: Invoice)` invented a new pattern that doesn't match.

**Corrected wiring:**

```typescript
// existing handleQrPayment becomes the click → modal-open trigger:
const handleQrPayment = () => {
  if (!invoice) return
  setQrAmountModalOpen(true)
}

// new function for the modal's onContinue callback:
const handleAmountModalContinue = async (amount: number | null) => {
  if (!invoice) return
  setQrPaymentLoading(true)
  setActionMessage('')
  try {
    const body: { invoice_id: string; amount?: string } = { invoice_id: invoice.id }
    if (amount !== null) {
      body.amount = amount.toFixed(2)
    }
    const res = await apiClient.post<{ session_id: string; amount: number; invoice_number: string; amount_cents: number; expires_at: string }>(
      '/payments/qr-session/existing',
      body,
    )
    setQrAmountModalOpen(false)
    setQrSessionData({
      session_id: res.data?.session_id ?? '',
      amount: Number(res.data?.amount ?? 0),
      invoice_number: res.data?.invoice_number ?? '',
    })
    setQrWaitingPopupOpen(true)
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setActionMessage(detail || 'Failed to create QR payment session.')  // InvoiceDetail uses showMsg
  } finally {
    setQrPaymentLoading(false)
  }
}
```

The modal renders inside the existing JSX, gated on `qrAmountModalOpen && invoice`. No new state is needed beyond `qrAmountModalOpen`. Existing state (`qrPaymentLoading`, `qrSessionData`, `qrWaitingPopupOpen`) is reused as today.

InvoiceList uses `showMsg(detail, 'error')` and InvoiceDetail uses `setActionMessage(detail)` — the implementer should match each file's existing error-display pattern instead of standardising on one.

### `last_pi_amount_cents` migration column is needed

This is already in the spec (task 1.1), but worth restating: the column is on `payment_tokens` (not on `invoices`), refreshed on every PI create AND every `update-surcharge` PI rewrite. The migration is straightforward — both columns are nullable, no backfill required. Existing rows will have `last_pi_amount_cents = NULL` and the reuse logic must treat NULL as cache miss → fall through to create-new path.



The following are explicitly **NOT** part of this feature; they may be considered for follow-up specs:

- **Cash-plus-card splits in one transaction.** Requires UI to offer "X via cash, Y via card" in one flow. Today the staff would record cash via the existing manual payment flow, then click QR for the partial card amount.
- **Partial payment via the customer-facing email link.** The "Send payment link" email currently links to the full balance only. The partial flow is initiated by org user via the kiosk button. Email-link partials are conceptually possible but not part of this spec.
- **Per-invoice consolidated receipt.** Each successful partial fires its own receipt email (now distinguished as "Partial payment received" — see Requirement 11). A future enhancement could aggregate all payments on an invoice into a single end-of-day or paid-in-full summary email; tracked separately.
- **Multi-currency partial.** Per-currency Stripe minimums are already wired via `STRIPE_MIN_BY_CURRENCY` (task 2.1) so adding a new currency is a one-entry change. The actual multi-currency invoicing flow (currency conversion, FX rates, customer currency preference) is the larger blocker and remains out of scope.
- **Refund flow for partial payments.** Existing `process_refund` already supports partial refunds of any Payment row by ID; no change needed.
- **Mobile companion app QR partial.** Mobile app is companion-only and excludes payment-collection flows; this stays consistent.
- **Audit log filter UI for "show only partials".** Audit log query API already supports filtering by `action`; UI surface is a separate enhancement.
- **Manual Stripe Dashboard amount edits.** If a merchant manually edits a PaymentIntent's amount via the Stripe Dashboard, our cached `payment_tokens.last_pi_amount_cents` becomes stale and the next reuse-branch decision could pick the wrong path. This is an out-of-band workflow that the merchant uses at their own risk; documented in a code comment near the reuse check.
