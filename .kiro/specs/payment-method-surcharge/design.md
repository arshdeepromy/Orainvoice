# Design Document: Payment Method Surcharge

## Overview

This feature adds the ability for organisation admins to pass Stripe processing fees to customers at payment time. When enabled, a surcharge is dynamically calculated based on the customer's selected payment method and displayed transparently on the public payment page (`/pay/{token}`) before the customer confirms payment. The invoice amount remains unchanged — the surcharge is a payment-time addition only.

### What Already Exists

| Component | Location | Status |
|---|---|---|
| Public payment page | `frontend/src/pages/public/InvoicePaymentPage.tsx` | ✅ Complete — needs surcharge display |
| Payment page backend | `app/modules/payments/public_router.py` | ✅ Complete — needs surcharge data |
| PaymentIntent creation | `app/integrations/stripe_connect.py` → `create_payment_intent()` | ✅ Complete — needs amount update endpoint |
| Stripe PaymentElement (tabs layout) | `InvoicePaymentPage.tsx` → `<PaymentElement layout="tabs">` | ✅ Complete — needs `onChange` handler |
| Online Payments settings page | `frontend/src/pages/settings/OnlinePaymentsSettings.tsx` | ✅ Complete — needs surcharge section |
| Org settings JSONB column | `organisations.settings` | ✅ Exists — surcharge config goes here |
| Payment model | `app/modules/payments/models.py` → `Payment` | ✅ Exists — needs surcharge columns |
| Payment receipt email | `app/modules/payments/service.py` → `_send_receipt_email()` | ✅ Exists — needs surcharge breakdown |
| Webhook handler | `app/modules/payments/service.py` → `handle_stripe_webhook()` | ✅ Exists — needs surcharge extraction |
| Confirm endpoint | `app/modules/payments/public_router.py` → `confirm_payment()` | ✅ Exists — needs surcharge extraction |
| Payment page response schema | `app/modules/payments/schemas.py` → `PaymentPageResponse` | ✅ Exists — needs surcharge fields |

### What Needs to Be Built

| Component | Type | Effort |
|---|---|---|
| Surcharge settings API (GET/PUT) | Backend — new endpoints | Small |
| Surcharge settings UI section | Frontend — new section in OnlinePaymentsSettings | Medium |
| Surcharge calculation engine | Backend — new pure function module | Small |
| PaymentIntent amount update endpoint | Backend — new endpoint | Small |
| Payment page surcharge data in response | Backend — enhance public_router | Small |
| Dynamic surcharge display on payment page | Frontend — enhance InvoicePaymentPage | Medium |
| PaymentElement `onChange` handler for method detection | Frontend — enhance PaymentForm | Small |
| `surcharge_amount` + `payment_method_type` columns on payments | Database migration | Small |
| Receipt email surcharge breakdown | Backend — enhance `_send_receipt_email()` | Small |
| NZ compliance notices | Frontend — UI text | Small |

## Architecture

### Surcharge Flow — End to End

```
Org Admin configures surcharge rates
    ↓
Settings saved to org.settings JSONB:
  { surcharge_enabled: true, surcharge_rates: { card: { pct: "2.90", fixed: "0.30", enabled: true }, ... } }
    ↓
Customer opens /pay/{token}
    ↓
GET /api/v1/public/pay/{token} returns surcharge_config alongside invoice data
    ↓
Customer selects payment method (card, Afterpay, Klarna, etc.)
    ↓
Frontend computes surcharge locally for instant display:
  surcharge = round(balance_due * pct/100 + fixed, 2)
    ↓
Frontend calls POST /api/v1/public/pay/{token}/update-surcharge
  { payment_method_type: "card", surcharge_amount: "2.90" }
    ↓
Backend validates surcharge matches server-side calculation
Backend updates PaymentIntent amount via Stripe API
Backend stores surcharge_amount + method in PI metadata
    ↓
Customer confirms payment (stripe.confirmPayment)
    ↓
Stripe charges balance_due + surcharge
    ↓
Webhook / confirm endpoint:
  - Extracts surcharge_amount from PI metadata
  - Records Payment with surcharge_amount and payment_method_type
  - Invoice amount_paid += balance_due (NOT surcharge)
  - Receipt email shows surcharge breakdown
```

### Security Model

1. **Server-side validation**: The frontend sends the computed surcharge, but the backend independently recalculates and rejects mismatches. This prevents client-side tampering.
2. **Rate limiting**: The surcharge update endpoint shares the payment page rate limit (20 req/min per IP).
3. **No auth required**: The endpoint is under `/api/v1/public/` — secured by the payment token, same as the existing payment page.
4. **Surcharge stored in PI metadata**: The surcharge amount is stored in Stripe's PaymentIntent metadata, providing an audit trail independent of our database.
5. **Credential safety**: Surcharge settings are read from `org.settings` JSONB — no integration credentials involved. The PaymentIntent update uses the platform secret key via `get_stripe_secret_key()` (DB-backed, cached).

## Components and Interfaces

### Backend — Surcharge Calculation Engine

#### 1. Surcharge Calculator Module

**File:** `app/modules/payments/surcharge.py`

A pure-function module with no database or I/O dependencies — easy to test with property-based tests.

```python
"""Surcharge calculation engine.

Pure functions for computing payment method surcharges.
No database or I/O dependencies — all inputs are passed explicitly.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN

# Default NZ Stripe Connect fee rates
DEFAULT_SURCHARGE_RATES: dict[str, dict] = {
    "card": {"percentage": "2.90", "fixed": "0.30", "enabled": True},
    "afterpay_clearpay": {"percentage": "6.00", "fixed": "0.30", "enabled": True},
    "klarna": {"percentage": "5.99", "fixed": "0.00", "enabled": True},
    "bank_transfer": {"percentage": "1.00", "fixed": "0.00", "enabled": True},
}

# Validation limits
MAX_PERCENTAGE = Decimal("10.00")
MAX_FIXED = Decimal("5.00")


def calculate_surcharge(
    balance_due: Decimal,
    percentage: Decimal,
    fixed: Decimal,
) -> Decimal:
    """Compute surcharge amount using banker's rounding.

    surcharge = (balance_due * percentage / 100) + fixed
    Rounded to 2 decimal places using ROUND_HALF_EVEN.

    The surcharge is computed on the original balance_due only —
    no compounding (surcharge is never applied to itself).
    """
    pct_component = balance_due * percentage / Decimal("100")
    raw = pct_component + fixed
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def get_surcharge_for_method(
    balance_due: Decimal,
    payment_method_type: str,
    surcharge_rates: dict[str, dict],
) -> Decimal:
    """Get the surcharge amount for a specific payment method.

    Returns Decimal("0.00") if the method is not configured or disabled.
    """
    rate = surcharge_rates.get(payment_method_type)
    if not rate or not rate.get("enabled", False):
        return Decimal("0.00")
    pct = Decimal(str(rate.get("percentage", "0")))
    fixed = Decimal(str(rate.get("fixed", "0")))
    return calculate_surcharge(balance_due, pct, fixed)


def validate_surcharge_rates(rates: dict[str, dict]) -> list[str]:
    """Validate surcharge rate configuration. Returns list of error messages."""
    errors = []
    for method, rate in rates.items():
        try:
            pct = Decimal(str(rate.get("percentage", "0")))
            fixed = Decimal(str(rate.get("fixed", "0")))
        except Exception:
            errors.append(f"{method}: invalid numeric values")
            continue
        if pct < 0:
            errors.append(f"{method}: percentage must not be negative")
        if pct > MAX_PERCENTAGE:
            errors.append(f"{method}: percentage must not exceed {MAX_PERCENTAGE}%")
        if fixed < 0:
            errors.append(f"{method}: fixed fee must not be negative")
        if fixed > MAX_FIXED:
            errors.append(f"{method}: fixed fee must not exceed ${MAX_FIXED}")
    return errors


def serialise_rates(rates: dict[str, dict]) -> dict[str, dict]:
    """Serialise surcharge rates to JSON-safe format with string decimals."""
    result = {}
    for method, rate in rates.items():
        result[method] = {
            "percentage": f"{Decimal(str(rate.get('percentage', '0'))):.2f}",
            "fixed": f"{Decimal(str(rate.get('fixed', '0'))):.2f}",
            "enabled": bool(rate.get("enabled", False)),
        }
    return result


def deserialise_rates(
    raw: dict[str, dict],
    defaults: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Deserialise surcharge rates from JSON, falling back to defaults on error."""
    if defaults is None:
        defaults = DEFAULT_SURCHARGE_RATES
    result = {}
    for method, rate in raw.items():
        try:
            result[method] = {
                "percentage": Decimal(str(rate["percentage"])),
                "fixed": Decimal(str(rate["fixed"])),
                "enabled": bool(rate.get("enabled", False)),
            }
        except (KeyError, ValueError, TypeError) as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Malformed surcharge rate for %s, using default: %s", method, exc,
            )
            default = defaults.get(method, {"percentage": "0", "fixed": "0", "enabled": False})
            result[method] = {
                "percentage": Decimal(str(default["percentage"])),
                "fixed": Decimal(str(default["fixed"])),
                "enabled": bool(default.get("enabled", False)),
            }
    return result
```

### Backend — Surcharge Settings Endpoints

#### 2. Surcharge Settings API

**File:** `app/modules/payments/router.py` (add to existing router)

Two new endpoints for managing surcharge configuration:

**GET /api/v1/payments/online-payments/surcharge-settings**
- Auth: `require_role("org_admin")`
- Returns the org's current surcharge configuration from `org.settings`
- If no config exists, returns defaults with `surcharge_enabled: false`

**PUT /api/v1/payments/online-payments/surcharge-settings**
- Auth: `require_role("org_admin")`
- Validates rates via `validate_surcharge_rates()`
- Serialises rates via `serialise_rates()`
- Saves to `org.settings["surcharge_enabled"]` and `org.settings["surcharge_rates"]`
- Writes audit log: `org.surcharge_settings_updated`

```python
# Pydantic schemas (in schemas.py)

class SurchargeRateConfig(BaseModel):
    percentage: str = Field(..., description="Percentage fee as string e.g. '2.90'")
    fixed: str = Field(..., description="Fixed fee as string e.g. '0.30'")
    enabled: bool = Field(True, description="Whether surcharge is active for this method")

class SurchargeSettingsResponse(BaseModel):
    surcharge_enabled: bool = False
    surcharge_acknowledged: bool = False
    surcharge_rates: dict[str, SurchargeRateConfig] = {}

class UpdateSurchargeSettingsRequest(BaseModel):
    surcharge_enabled: bool
    surcharge_acknowledged: bool = False
    surcharge_rates: dict[str, SurchargeRateConfig]
```

### Backend — PaymentIntent Surcharge Update Endpoint

#### 3. Surcharge Update Endpoint

**File:** `app/modules/payments/public_router.py` (add to existing public router)

**POST /api/v1/public/pay/{token}/update-surcharge**

This is a public endpoint (no auth — secured by payment token). Called by the frontend when the customer selects or changes a payment method.

```python
class UpdateSurchargeRequest(BaseModel):
    payment_method_type: str = Field(..., description="e.g. 'card', 'afterpay_clearpay', 'klarna'")

class UpdateSurchargeResponse(BaseModel):
    surcharge_amount: str  # Decimal as string e.g. "2.90"
    total_amount: str      # balance_due + surcharge as string
    payment_intent_updated: bool
```

**Logic:**
1. Validate payment token (same as existing `get_payment_page`)
2. Fetch invoice and org
3. Read surcharge config from `org.settings`
4. If surcharging disabled or method not surcharged → surcharge = 0
5. Compute surcharge server-side via `get_surcharge_for_method()`
6. Calculate new PI amount: `int((balance_due + surcharge) * 100)` cents
7. Update PaymentIntent via Stripe API:
   ```
   POST https://api.stripe.com/v1/payment_intents/{pi_id}
   Headers: Stripe-Account: {connected_account_id}
   Body:
     amount={new_amount_cents}
     metadata[surcharge_amount]={surcharge}
     metadata[surcharge_method]={payment_method_type}
     metadata[original_amount]={balance_due}
   ```
8. Return the surcharge amount and updated total

**Security:**
- Server-side calculation only — the frontend does NOT send the surcharge amount
- The frontend sends only the `payment_method_type`; the backend computes everything
- Rate limited (shares payment page rate limit)
- PaymentIntent metadata provides an audit trail

### Backend — Enhanced Payment Page Response

#### 4. Surcharge Config in Payment Page Response

**File:** `app/modules/payments/public_router.py` → `get_payment_page()`

Add surcharge configuration to the `PaymentPageResponse` so the frontend can compute surcharges locally for instant display:

```python
# New fields on PaymentPageResponse
class SurchargeRateInfo(BaseModel):
    percentage: str
    fixed: str
    enabled: bool

class PaymentPageResponse(BaseModel):
    # ... existing fields ...

    # Surcharge config (only when surcharging is enabled)
    surcharge_enabled: bool = False
    surcharge_rates: dict[str, SurchargeRateInfo] = {}
```

The backend reads `org.settings["surcharge_enabled"]` and `org.settings["surcharge_rates"]` and includes them in the response when surcharging is enabled.

### Backend — Enhanced Payment Recording

#### 5. New Columns on `payments` Table

**Alembic migration** adds two columns:

```python
op.add_column('payments', sa.Column(
    'surcharge_amount', sa.Numeric(12, 2), nullable=False, server_default='0.00',
))
op.add_column('payments', sa.Column(
    'payment_method_type', sa.String(50), nullable=True,
))
```

**Updated Payment model:**
```python
class Payment(Base):
    # ... existing columns ...
    surcharge_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0.00",
    )
    payment_method_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
    )
```

The existing `amount` column continues to represent the invoice payment amount (excluding surcharge). The `surcharge_amount` is stored separately for reconciliation.

#### 6. Enhanced Webhook Handler

**File:** `app/modules/payments/service.py` → `handle_stripe_webhook()`

After extracting the payment amount, also extract surcharge metadata:

```python
# Extract surcharge from PI metadata
metadata = obj.get("metadata", {})
surcharge_str = metadata.get("surcharge_amount", "0")
surcharge_method = metadata.get("surcharge_method", "")
try:
    surcharge = Decimal(surcharge_str)
except Exception:
    surcharge = Decimal("0")

# The PI amount includes surcharge, but we record them separately:
# amount_received = invoice_amount + surcharge (in cents)
# We need the original invoice amount:
original_amount_str = metadata.get("original_amount")
if original_amount_str:
    amount = Decimal(original_amount_str)
else:
    # Fallback: subtract surcharge from total
    amount = Decimal(amount_cents) / Decimal("100") - surcharge

# Create payment record with surcharge
payment = Payment(
    org_id=invoice.org_id,
    invoice_id=invoice.id,
    amount=pay_amount,  # invoice amount only
    surcharge_amount=surcharge,
    payment_method_type=surcharge_method or None,
    method="stripe",
    stripe_payment_intent_id=stripe_payment_intent,
    recorded_by=invoice.created_by,
)
```

The invoice's `amount_paid` and `balance_due` are updated based on the invoice amount only (excluding surcharge). The surcharge goes to the org's Stripe account as part of the total charge but is tracked separately in our records.

#### 7. Enhanced Confirm Endpoint

**File:** `app/modules/payments/public_router.py` → `confirm_payment()`

Same surcharge extraction logic as the webhook handler — the PI metadata contains `surcharge_amount` and `surcharge_method`, which are passed through to `handle_stripe_webhook()`.

### Backend — Enhanced Receipt Email

#### 8. Receipt Email Surcharge Breakdown

**File:** `app/modules/payments/service.py` → `_send_receipt_email()`

Update the function signature to accept surcharge info:

```python
async def _send_receipt_email(
    db: AsyncSession,
    *,
    to_email: str,
    invoice: Invoice,
    pay_amount: Decimal,
    surcharge_amount: Decimal = Decimal("0"),
    payment_method_type: str | None = None,
) -> None:
```

Update the email body:

```python
if surcharge_amount > 0:
    method_label = _payment_method_display_name(payment_method_type or "")
    body = (
        f"Hi,\n\n"
        f"Thank you for your payment.\n\n"
        f"Invoice: {inv_number}\n"
        f"Invoice amount: {currency} {pay_amount}\n"
        f"Payment method surcharge ({method_label}): {currency} {surcharge_amount}\n"
        f"Total paid: {currency} {pay_amount + surcharge_amount}\n"
        f"Remaining balance: {currency} {invoice.balance_due}\n\n"
        f"Thank you for your business.\n\n"
        f"{org_name}\n"
    )
else:
    # Existing format — no surcharge line
    body = (
        f"Hi,\n\n"
        f"Thank you for your payment of {currency} {pay_amount}.\n\n"
        f"Invoice: {inv_number}\n"
        f"Amount paid: {currency} {pay_amount}\n"
        f"Remaining balance: {currency} {invoice.balance_due}\n\n"
        f"Thank you for your business.\n\n"
        f"{org_name}\n"
    )
```

Helper for display names:
```python
_METHOD_DISPLAY_NAMES = {
    "card": "Credit/Debit Card",
    "afterpay_clearpay": "Afterpay",
    "klarna": "Klarna",
    "bank_transfer": "Bank Transfer",
}

def _payment_method_display_name(method_type: str) -> str:
    return _METHOD_DISPLAY_NAMES.get(method_type, method_type.replace("_", " ").title())
```

### Frontend — Surcharge Settings Section

#### 9. Surcharge Settings Panel

**File:** `frontend/src/pages/settings/OnlinePaymentsSettings.tsx`

Add a new `SurchargeSettingsSection` component rendered inside the "Connected" state block, after `PaymentMethodsSection` and before `PayoutSettingsSection`.

**UI layout:**
```
┌─────────────────────────────────────────────────────┐
│ Surcharge Settings                                   │
│                                                       │
│ ⚠️ NZ law requires surcharges to not exceed actual   │
│    merchant processing costs and to be disclosed      │
│    before payment.                                    │
│                                                       │
│ [Toggle] Pass processing fees to customers            │
│                                                       │
│ (when enabled:)                                       │
│ ┌─────────────────────────────────────────────────┐  │
│ │ Payment Method    │ Percentage │ Fixed │ Enabled │  │
│ ├───────────────────┼────────────┼───────┼─────────┤  │
│ │ Card (Visa/MC)    │ [2.90] %   │ $[0.30]│ [✓]   │  │
│ │ Afterpay          │ [6.00] %   │ $[0.30]│ [✓]   │  │
│ │ Klarna            │ [5.99] %   │ $[0.00]│ [✓]   │  │
│ │ Bank Transfer     │ [1.00] %   │ $[0.00]│ [✓]   │  │
│ └─────────────────────────────────────────────────┘  │
│                                                       │
│ ⚠️ Card rate exceeds default Stripe rate (2.9%)      │
│    by more than 0.5pp — may exceed actual costs.     │
│                                                       │
│ [✓] I acknowledge that surcharges must comply with   │
│     NZ consumer law (required for first save)         │
│                                                       │
│ [Save]  [Cancel]                                      │
└─────────────────────────────────────────────────────┘
```

**Data flow:**
1. On mount: `GET /api/v1/payments/online-payments/surcharge-settings`
2. Display current config (or defaults if not configured)
3. On save: `PUT /api/v1/payments/online-payments/surcharge-settings`
4. Validation: percentage 0–10%, fixed $0–$5, acknowledgement required on first enable

### Frontend — Dynamic Surcharge on Payment Page

#### 10. Enhanced Payment Page

**File:** `frontend/src/pages/public/InvoicePaymentPage.tsx`

**Changes to `PaymentPageData` type:**
```typescript
interface PaymentPageData {
  // ... existing fields ...
  surcharge_enabled: boolean
  surcharge_rates: Record<string, {
    percentage: string
    fixed: string
    enabled: boolean
  }>
}
```

**Changes to `PaymentForm` component:**

Add state for tracking the selected payment method and computed surcharge:

```typescript
const [selectedMethod, setSelectedMethod] = useState<string | null>(null)
const [surchargeAmount, setSurchargeAmount] = useState<number>(0)
const [updatingPI, setUpdatingPI] = useState(false)
```

Add `onChange` handler to `PaymentElement`:
```typescript
<PaymentElement
  options={{ layout: 'tabs' }}
  onChange={(event) => {
    // event.value.type gives us the payment method type
    // e.g. "card", "afterpay_clearpay", "klarna"
    const methodType = event.value?.type ?? null
    setSelectedMethod(methodType)
  }}
/>
```

When `selectedMethod` changes, compute surcharge locally for instant display, then call the backend to update the PaymentIntent:

```typescript
useEffect(() => {
  if (!selectedMethod || !surchargeEnabled) {
    setSurchargeAmount(0)
    return
  }
  const rate = surchargeRates[selectedMethod]
  if (!rate?.enabled) {
    setSurchargeAmount(0)
    return
  }
  // Local calculation for instant display
  const pct = parseFloat(rate.percentage)
  const fixed = parseFloat(rate.fixed)
  const computed = Math.round((balanceDue * pct / 100 + fixed) * 100) / 100
  setSurchargeAmount(computed)

  // Update PaymentIntent on backend
  const controller = new AbortController()
  const updatePI = async () => {
    setUpdatingPI(true)
    try {
      await axios.post(
        `/api/v1/public/pay/${token}/update-surcharge`,
        { payment_method_type: selectedMethod },
        { signal: controller.signal },
      )
    } catch (err) {
      if (!controller.signal.aborted) {
        setError('Failed to update payment amount. Please try again.')
      }
    } finally {
      if (!controller.signal.aborted) setUpdatingPI(false)
    }
  }
  updatePI()
  return () => controller.abort()
}, [selectedMethod, surchargeEnabled, balanceDue, token])
```

**Surcharge display in the payment summary:**
```tsx
{/* Amount summary */}
<div className="rounded-md border border-gray-200 bg-gray-50 p-4 space-y-2">
  <div className="flex justify-between text-sm text-gray-600">
    <span>Invoice balance</span>
    <span className="tabular-nums">{formatCurrency(balanceDue, currency)}</span>
  </div>
  {surchargeAmount > 0 && (
    <>
      <div className="flex justify-between text-sm text-gray-600">
        <span>Payment method surcharge ({methodDisplayName})</span>
        <span className="tabular-nums">{formatCurrency(surchargeAmount, currency)}</span>
      </div>
      <div className="flex justify-between text-sm font-semibold text-gray-900 border-t border-gray-200 pt-2">
        <span>Total to pay</span>
        <span className="tabular-nums">{formatCurrency(balanceDue + surchargeAmount, currency)}</span>
      </div>
      <p className="text-xs text-gray-500">
        A surcharge is applied to cover payment processing fees.
      </p>
    </>
  )}
  {surchargeAmount === 0 && (
    <div className="flex justify-between text-sm font-semibold text-gray-900">
      <span>Amount to pay</span>
      <span className="tabular-nums">{formatCurrency(balanceDue, currency)}</span>
    </div>
  )}
</div>
```

**Pay button disabled while PI is updating:**
```tsx
<Button
  type="submit"
  loading={processing}
  disabled={!stripe || processing || updatingPI}
  className="w-full"
>
  Pay {formatCurrency(balanceDue + surchargeAmount, currency)}
</Button>
```

## Data Models

### Modified Table: `payments`

| New Column | Type | Constraints | Description |
|---|---|---|---|
| `surcharge_amount` | NUMERIC(12,2) | NOT NULL, DEFAULT 0.00 | Surcharge amount charged to customer |
| `payment_method_type` | VARCHAR(50) | NULLABLE | Payment method used (card, afterpay_clearpay, klarna, etc.) |

### Modified: `organisations.settings` JSONB

New keys added to the existing JSONB column:

```json
{
  "surcharge_enabled": true,
  "surcharge_acknowledged": true,
  "surcharge_rates": {
    "card": { "percentage": "2.90", "fixed": "0.30", "enabled": true },
    "afterpay_clearpay": { "percentage": "6.00", "fixed": "0.30", "enabled": true },
    "klarna": { "percentage": "5.99", "fixed": "0.00", "enabled": true },
    "bank_transfer": { "percentage": "1.00", "fixed": "0.00", "enabled": true }
  }
}
```

Rates are stored as strings to avoid floating-point precision loss in JSONB.

### Alembic Migration

Single migration adding:
1. `surcharge_amount` column on `payments` (NOT NULL, DEFAULT 0.00)
2. `payment_method_type` column on `payments` (NULLABLE)

No new tables needed — surcharge config lives in the existing `org.settings` JSONB.

### PaymentIntent Metadata Schema

When a surcharge is applied, the PaymentIntent metadata includes:

```json
{
  "invoice_id": "uuid-string",
  "platform": "workshoppro_nz",
  "surcharge_amount": "2.90",
  "surcharge_method": "card",
  "original_amount": "100.00"
}
```

This provides an audit trail in Stripe's dashboard and is used by the webhook/confirm handlers to extract surcharge info.


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do.*

### Property 1: Surcharge calculation correctness (Metamorphic + Invariant)

*For any* valid `balance_due` (Decimal > 0, ≤ 999999.99) and any valid fee rate (percentage 0–10%, fixed $0–$5), the `calculate_surcharge()` function SHALL return a value equal to `(balance_due × percentage / 100) + fixed` rounded to 2 decimal places using banker's rounding (ROUND_HALF_EVEN). The result SHALL always be ≥ 0 and ≤ `balance_due × 0.10 + 5.00`. Furthermore, the surcharge SHALL be computed on the original `balance_due` only — applying `calculate_surcharge()` to `balance_due + surcharge` with the same rate SHALL produce a different (larger) result, confirming no compounding occurs in the design.

**Validates: Requirements 3.2, 3.4, 3.5, 5.3**

### Property 2: Surcharge rate serialisation round-trip (Round-Trip)

*For any* valid surcharge rate configuration (percentage as Decimal with 2dp in [0, 10], fixed as Decimal with 2dp in [0, 5], enabled as bool), calling `serialise_rates()` then `deserialise_rates()` then `serialise_rates()` again SHALL produce a JSON structure identical to the first serialisation output. The percentage and fixed values SHALL be preserved exactly (no floating-point drift).

**Validates: Requirements 9.1, 9.2, 9.3**

### Property 3: Surcharge rate validation rejects out-of-bounds values (Error Conditions)

*For any* surcharge rate where percentage > 10.00 OR percentage < 0 OR fixed > 5.00 OR fixed < 0, the `validate_surcharge_rates()` function SHALL return a non-empty list of error messages. *For any* rate where 0 ≤ percentage ≤ 10.00 AND 0 ≤ fixed ≤ 5.00, the function SHALL return an empty list.

**Validates: Requirements 2.2, 2.6, 2.7**

### Property 4: Payment amount invariant — surcharge never contaminates invoice balance (Invariant)

*For any* payment recorded with a surcharge, the `Payment.amount` field SHALL equal the invoice portion only (balance_due or partial amount), and `Payment.surcharge_amount` SHALL be stored separately. The sum `Payment.amount + Payment.surcharge_amount` SHALL equal the total amount charged to the customer (PaymentIntent `amount_received / 100`). The invoice's `amount_paid` SHALL increase by `Payment.amount` only, never by the surcharge.

**Validates: Requirements 6.1, 6.3**

### Property 5: Disabled method produces zero surcharge (Invariant)

*For any* payment method type where the surcharge rate has `enabled: false`, OR where `surcharge_enabled` is false on the org, the `get_surcharge_for_method()` function SHALL return `Decimal("0.00")` regardless of the configured percentage and fixed values.

**Validates: Requirements 1.4, 3.3**

### Property 6: Malformed rate deserialisation falls back to defaults (Error Conditions)

*For any* malformed surcharge rate entry (missing keys, non-numeric strings, None values, empty dicts), the `deserialise_rates()` function SHALL return the default rate for that payment method instead of raising an exception. The returned rate SHALL have valid Decimal percentage and fixed values.

**Validates: Requirements 9.4**

### Property 7: Surcharge addition produces exact total (Invariant)

*For any* valid `balance_due` (Decimal with 2dp) and any surcharge amount (Decimal with 2dp, computed by `calculate_surcharge()`), the total `balance_due + surcharge` SHALL be exactly representable as a Decimal with 2 decimal places. Converting this total to cents via `int(total * 100)` SHALL produce an integer equal to `int(balance_due * 100) + int(surcharge * 100)` — no rounding drift across the addition.

**Validates: Requirements 3.5, 4.2**

### Property 8: Rate-exceeds-cost warning threshold (Metamorphic)

*For any* configured percentage rate and its corresponding default Stripe rate, the compliance warning SHALL be triggered if and only if `configured_rate - default_rate > 0.50` (percentage points). The warning SHALL NOT be triggered when the configured rate is at or below `default_rate + 0.50`.

**Validates: Requirements 8.2**

## Error Handling

| Scenario | Component | HTTP Status | User-Facing Message |
|---|---|---|---|
| Surcharge settings save with invalid rates | Settings API | 422 | Validation error details per field |
| Surcharge settings save without acknowledgement (first time) | Settings API | 400 | "Please acknowledge the NZ compliance notice" |
| PaymentIntent update fails (Stripe API error) | Surcharge update endpoint | 502 | "Failed to update payment amount. Please try again." |
| PaymentIntent update fails (network timeout) | Surcharge update endpoint | 502 | "Failed to update payment amount. Please try again." |
| Invalid payment token on surcharge update | Surcharge update endpoint | 404 | "Invalid payment link" |
| Expired payment token on surcharge update | Surcharge update endpoint | 410 | "This payment link has expired." |
| Rate limit exceeded on surcharge update | Surcharge update endpoint | 429 | "Too many requests. Please try again later." + Retry-After |
| Malformed surcharge rate in org.settings | Payment page load | 200 | Falls back to default rates silently; warning logged |
| Surcharge config missing from org.settings | Payment page load | 200 | `surcharge_enabled: false` — no surcharge applied |
| Webhook with missing surcharge metadata | Webhook handler | 200 | Surcharge defaults to 0; payment recorded normally |
| Org not connected to Stripe (surcharge settings) | Settings page | N/A | Surcharge section not shown (only visible when connected) |

## Testing Strategy

### Property-Based Tests (Hypothesis)

**Library:** `hypothesis` (already in project dependencies)
**Location:** `tests/properties/test_surcharge_properties.py`

| Property | Test Function | Generator Strategy |
|---|---|---|
| P1: Surcharge calculation | `test_surcharge_calculation_correctness` | `st.decimals(min_value=Decimal("0.01"), max_value=Decimal("999999.99"), places=2)` for balance_due, `st.decimals(min_value=Decimal("0"), max_value=Decimal("10"), places=2)` for percentage, `st.decimals(min_value=Decimal("0"), max_value=Decimal("5"), places=2)` for fixed |
| P2: Rate serialisation round-trip | `test_surcharge_rate_serialisation_roundtrip` | `st.dictionaries(keys=st.sampled_from(["card","afterpay_clearpay","klarna","bank_transfer"]), values=st.fixed_dictionaries({"percentage": st.decimals(...), "fixed": st.decimals(...), "enabled": st.booleans()}))` |
| P3: Rate validation boundaries | `test_surcharge_rate_validation_boundaries` | `st.decimals(min_value=Decimal("-5"), max_value=Decimal("20"), places=2)` for percentage, same for fixed |
| P4: Payment amount invariant | `test_payment_amount_excludes_surcharge` | `st.decimals(...)` for balance_due and surcharge, `st.uuids()` for IDs |
| P5: Disabled method zero surcharge | `test_disabled_method_zero_surcharge` | `st.sampled_from(method_types)` for method, `st.decimals(...)` for balance, `st.booleans()` for enabled |
| P6: Malformed rate fallback | `test_malformed_rate_fallback` | `st.one_of(st.none(), st.integers(), st.text(), st.dictionaries(...))` for malformed rate values |
| P7: Surcharge addition exactness | `test_surcharge_addition_no_rounding_drift` | `st.decimals(min_value=Decimal("0.01"), max_value=Decimal("999999.99"), places=2)` for balance_due, valid rates |
| P8: Rate warning threshold | `test_rate_exceeds_cost_warning` | `st.decimals(min_value=Decimal("0"), max_value=Decimal("10"), places=2)` for configured and default rates |

Each test tagged: `# Feature: payment-method-surcharge, Property N: <description>`
Configuration: `@settings(max_examples=100, deadline=None)`

### Unit Tests

| Test | What It Verifies |
|---|---|
| `test_calculate_surcharge_card_default` | Card: 2.9% + $0.30 on $100 = $3.20 |
| `test_calculate_surcharge_afterpay_default` | Afterpay: 6% + $0.30 on $100 = $6.30 |
| `test_calculate_surcharge_klarna_default` | Klarna: 5.99% + $0 on $100 = $5.99 |
| `test_calculate_surcharge_zero_balance` | $0 balance → $0.30 (fixed only) or $0 if no fixed |
| `test_get_surcharge_disabled_method` | Disabled method returns $0.00 |
| `test_get_surcharge_unknown_method` | Unknown method returns $0.00 |
| `test_validate_rates_valid` | Valid rates pass validation |
| `test_validate_rates_pct_too_high` | 11% rejected |
| `test_validate_rates_negative_fixed` | -$1 rejected |
| `test_serialise_rates_string_format` | Rates serialised as "2.90" not "2.9" |
| `test_deserialise_rates_malformed` | Malformed entry falls back to default |
| `test_surcharge_settings_get_default` | No config returns defaults with enabled=false |
| `test_surcharge_settings_save` | Config saved to org.settings JSONB |
| `test_surcharge_settings_requires_acknowledgement` | First enable without ack returns 400 |
| `test_update_surcharge_endpoint_valid` | PI amount updated correctly |
| `test_update_surcharge_endpoint_invalid_token` | Returns 404 |
| `test_update_surcharge_endpoint_disabled` | Returns surcharge=0 when disabled |
| `test_webhook_extracts_surcharge` | Payment record has correct surcharge_amount |
| `test_webhook_no_surcharge_metadata` | Payment record has surcharge_amount=0 |
| `test_receipt_email_with_surcharge` | Email body contains surcharge breakdown |
| `test_receipt_email_without_surcharge` | Email body has no surcharge line |
| `test_payment_page_includes_surcharge_config` | Response includes surcharge_rates when enabled |
| `test_payment_page_no_surcharge_config` | Response has surcharge_enabled=false when disabled |

### Integration / E2E Test

**Script:** `scripts/test_surcharge_e2e.py`

Following the project's e2e testing pattern:

1. Login as org_admin
2. GET surcharge settings → verify defaults
3. PUT surcharge settings (enable, set rates) → verify saved
4. Create and issue invoice with Stripe gateway
5. GET payment page → verify surcharge_rates in response
6. POST update-surcharge with "card" → verify PI updated, surcharge returned
7. POST update-surcharge with "klarna" → verify different surcharge
8. POST update-surcharge with disabled method → verify surcharge=0
9. Simulate webhook with surcharge metadata → verify payment record
10. Verify receipt email contains surcharge breakdown
11. OWASP checks: no auth on public endpoints returns 401 on settings, rate limiting works
