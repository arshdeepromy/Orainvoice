# Refund and Credit Note Features — Implementation Analysis

> **Reviewed & corrected**: 2026-03-15. Original doc had several factual errors (endpoint paths, test counts, library proposals). This version is verified against the actual codebase.

## Executive Summary

The app has a **fully implemented backend** for refund and credit note functionality — database schema, API endpoints, business logic, and tests. The **frontend is ~30% complete**: credit notes display read-only in InvoiceDetail, but there are no creation forms, no refund UI, and no action buttons. This doc covers what exists, what's missing, and the minimal implementation plan to close the gaps.

> **Note**: Stripe features are currently disabled org-wide (ISSUE-072). All Stripe-dependent options in the refund/credit note UI should remain disabled until Stripe Connect onboarding is implemented. See `docs/STRIPE_IMPLEMENTATION.md`.

---

## Current State Analysis

### Backend: ✅ Complete

#### Database Schema (Migration `0005`)

**`credit_notes` table:**
- `id` (UUID, PK)
- `org_id` (UUID, FK → organisations)
- `invoice_id` (UUID, FK → invoices)
- `credit_note_number` (String(50), e.g. "CN-0001")
- `amount` (Numeric(12,2))
- `reason` (Text)
- `items` (JSONB array, default `[]`)
- `stripe_refund_id` (String(255), nullable)
- `created_by` (UUID, FK → users)
- `created_at` (DateTime with timezone)

**`credit_note_sequences` table:**
- `id` (UUID, PK)
- `org_id` (UUID, FK → organisations, unique)
- `last_number` (Integer, default 0)

**`payments` table (refund-relevant columns):**
- `is_refund` (Boolean, default false)
- `refund_note` (Text, nullable)
- `amount` (Numeric(12,2) — negative for refunds)
- `method` (String(10) — constrained to `'cash'` or `'stripe'` via `ck_payments_method`)
- `stripe_payment_intent_id` (String(255), nullable)

> **⚠️ Constraint note**: The DB `CHECK` constraint on `payments.method` only allows `'cash'` and `'stripe'`. If we ever need to support eftpos/bank_transfer refunds, a migration to alter this constraint is required first.

#### API Endpoints

**Credit Notes (invoices router — `app/modules/invoices/router.py`):**
- `POST /api/v1/invoices/{invoice_id}/credit-note` — Create credit note
- `GET /api/v1/invoices/{invoice_id}/credit-notes` — List credit notes for an invoice

**Refunds (payments router — `app/modules/payments/router.py`):**
- `POST /api/v1/payments/refund` — Process refund (invoice_id is in the request body, NOT the URL path)
- `GET /api/v1/payments/invoice/{invoice_id}/history` — Payment history including refunds

**Other payment endpoints (for reference):**
- `POST /api/v1/payments/cash` — Record cash payment
- `POST /api/v1/payments/stripe-link` — Generate Stripe payment link (disabled — ISSUE-072)
- `POST /api/v1/payments/webhook/stripe` — Stripe webhook (no auth, signature-verified)

#### Business Logic

**`create_credit_note` (`app/modules/invoices/service.py`):**
- Validates invoice exists and belongs to org
- Prevents credit notes on draft/voided invoices
- Prevents over-crediting (total credits cannot exceed invoice total)
- Gap-free credit note numbering (CN-0001, CN-0002, etc.)
- Updates invoice `balance_due` automatically
- Optional `process_stripe_refund` flag (disabled for now — ISSUE-072)
- Audit logging
- Supports itemized credit details via JSONB `items` field

**`process_refund` (`app/modules/payments/service.py`):**
- Cash refund recording with notes
- Stripe API integration for automatic refunds (disabled for now — ISSUE-072)
- Invoice balance adjustment
- Payment history tracking
- Validation against available refund amounts
- Audit trail

#### Request/Response Schemas (`app/modules/payments/schemas.py`)

**`RefundRequest`:**
```python
invoice_id: UUID          # Required — the invoice to refund
amount: Decimal           # Required, > 0
method: str               # 'cash' or 'stripe'
notes: str | None         # Optional refund reason
```

**`CreditNoteCreateRequest` (`app/modules/invoices/schemas.py`):**
```python
amount: Decimal           # Required, > 0
reason: str               # Required
items: list[CreditNoteItemCreate]  # Each has description + amount
process_stripe_refund: bool = False
```

#### Test Coverage

- `tests/test_credit_notes.py` — **19 test functions** (schema validation, creation, rejection, numbering, listing)
- `tests/test_payment_history_refunds.py` — **18 test functions** (schema validation, history retrieval, cash/Stripe refund processing, rejection)

---

### Frontend: ❌ ~30% Complete

#### What Exists

1. **Credit note read-only display** (`InvoiceDetail.tsx`, lines ~689-720)
   - Table showing `reference_number`, `amount`, `reason`, `created_at`
   - "No credit notes" empty state
   - No create button

2. **Payment history display** (basic, in InvoiceDetail)
   - Shows payments list
   - No visual distinction between payments and refunds
   - No refund action

3. **Invoice action buttons** (InvoiceDetail header bar)
   - Edit (draft only), Duplicate, Void, Email, Print, Download PDF
   - **No "Create Credit Note" button**
   - **No "Process Refund" button**

#### What's Missing

1. **Credit note creation UI** — No button, no modal, no form
2. **Refund processing UI** — No button, no modal, no form
3. **Payment history enhancement** — No payment vs refund visual distinction, no net calculations
4. **Action buttons** — No credit note or refund buttons in InvoiceDetail header

---

## Implementation Plan

### Approach

- **No new libraries.** The codebase uses plain React state + manual validation everywhere (InvoiceCreate, BookingForm, etc.). We follow the same pattern — no react-hook-form, yup, or zod.
- **Minimal new files.** Two new modal components + enhancements to InvoiceDetail. Reuse existing UI components (`Modal`, `Button`, `Badge`, `ConfirmDialog`, `Spinner`).
- **Stripe options disabled.** The `processStripeRefund` toggle and Stripe refund method are hidden/disabled, consistent with ISSUE-072.

### New Components (2 files)

#### 1. `frontend/src/components/invoices/CreditNoteModal.tsx`

Modal for creating a credit note against an invoice.

**Props:**
```typescript
interface CreditNoteModalProps {
  invoice: { id: string; total: number; balance_due: number; credit_notes?: CreditNote[] }
  open: boolean
  onClose: () => void
  onSuccess: () => void  // triggers parent refetch
}
```

**Features:**
- Amount input with validation (> 0, ≤ remaining creditable amount)
- Reason textarea (required)
- Optional line item breakdown (description + amount rows, add/remove)
- Shows "remaining creditable" = invoice.total − sum of existing credit note amounts
- Preview of balance after credit
- Calls `POST /api/v1/invoices/{id}/credit-note`
- Loading state, error handling, success toast
- `processStripeRefund` checkbox hidden (disabled per ISSUE-072)

#### 2. `frontend/src/components/invoices/RefundModal.tsx`

Modal for processing a refund against an invoice.

**Props:**
```typescript
interface RefundModalProps {
  invoice: { id: string; amount_paid: number; balance_due: number }
  open: boolean
  onClose: () => void
  onSuccess: () => void  // triggers parent refetch
}
```

**Features:**
- Amount input with validation (> 0, ≤ amount_paid minus existing refunds)
- Refund note/reason textarea (required)
- Method selector: only "Cash" enabled for now (Stripe disabled per ISSUE-072)
- Confirmation step before submission
- Calls `POST /api/v1/payments/refund` with `{ invoice_id, amount, method: 'cash', notes }`
- Loading state, error handling, success toast

### Modifications to Existing Files (1 file)

#### 3. `frontend/src/pages/invoices/InvoiceDetail.tsx`

**Action buttons — add two new buttons to the header bar:**
- "Create Credit Note" — visible when invoice status is `issued`, `partially_paid`, or `paid` (not draft/voided)
- "Process Refund" — visible when `amount_paid > 0`

**Payment history section — enhance:**
- Add `is_refund` badge: green for payments, red for refunds
- Show refund note when present
- Add summary row: Total Paid | Total Refunded | Net

**Credit notes section — enhance:**
- Add "Create Credit Note" link/button at the top of the section
- Show running total of credited amount

**State additions:**
```typescript
const [creditNoteModalOpen, setCreditNoteModalOpen] = useState(false)
const [refundModalOpen, setRefundModalOpen] = useState(false)
```

**After success callback:** call `fetchInvoice()` to refresh all data.

---

## File Summary

| Action | File | What |
|--------|------|------|
| New | `frontend/src/components/invoices/CreditNoteModal.tsx` | Credit note creation modal |
| New | `frontend/src/components/invoices/RefundModal.tsx` | Refund processing modal |
| Modify | `frontend/src/pages/invoices/InvoiceDetail.tsx` | Add buttons, import modals, enhance payment history + credit notes display |

---

## Constraints & Notes

- **Stripe is disabled.** `processStripeRefund` and `method: 'stripe'` options must be hidden/disabled until Stripe Connect is implemented (see `docs/STRIPE_IMPLEMENTATION.md`).
- **Payment method DB constraint** only allows `'cash'` and `'stripe'`. No migration needed for this implementation since we're only using `'cash'` refunds.
- **No new dependencies.** Use existing `Modal`, `Button`, `Badge`, `Spinner`, `ConfirmDialog` from `frontend/src/components/ui/`.
- **Follow existing patterns.** Manual form state with `useState`, inline validation, `apiClient` for API calls — same as InvoiceCreate and BookingForm.
- **Audit trail is automatic.** Backend already logs all credit note and refund operations to the audit log.

## Out of Scope (Future Work)

These items are NOT part of this implementation. They should be separate specs if needed:

- Bulk credit note creation from multiple line items
- Quick refund presets (25%, 50%, 100%)
- Batch refund processing
- Credit note templates
- Credit note PDF generation/download
- Stripe refund integration (blocked on ISSUE-072)
- Export payment history to CSV
