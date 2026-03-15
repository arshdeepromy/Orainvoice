# Implementation Plan: Refund & Credit Note UI

## Overview

Frontend-only implementation across 3 files: shared validation utilities, two new modal components (CreditNoteModal, RefundModal), and modifications to InvoiceDetail.tsx. Validation logic is extracted into pure functions for testability. All property-based tests use fast-check with Vitest.

## Tasks

- [x] 1. Create shared validation and formatting utilities
  - [x] 1.1 Create `frontend/src/components/invoices/refund-credit-note.utils.ts` with exported pure functions
    - `formatNZD(value: number): string` — formats using `Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' })`
    - `computeCreditableAmount(invoiceTotal: number, existingCreditNoteAmounts: number[]): number` — returns `max(0, invoiceTotal - sum(amounts))`
    - `computePaymentSummary(payments: Array<{ amount: number; is_refund?: boolean }>): { totalPaid: number; totalRefunded: number; netPaid: number }`
    - `validateAmount(amount: number, maximum: number): string | null` — returns error message or null
    - `validateReason(reason: string): string | null` — returns "Reason is required" for empty/whitespace-only strings, null otherwise
    - `computeItemsTotal(items: Array<{ amount: number }>): number` — sum of item amounts
    - `hasItemAmountMismatch(creditNoteAmount: number, items: Array<{ amount: number }>): boolean` — true iff items non-empty and sum ≠ creditNoteAmount
    - `isCreditNoteButtonVisible(status: string): boolean` — true iff status ∈ ['issued', 'partially_paid', 'paid']
    - `isRefundButtonVisible(amountPaid: number): boolean` — true iff amountPaid > 0
    - `getPaymentBadgeType(isRefund: boolean): { label: string; color: 'green' | 'red' }` — returns badge config
    - `shouldShowRefundNote(isRefund: boolean, refundNote: string | null | undefined): boolean` — true iff isRefund and refundNote is non-empty
    - `getInitialCreditNoteFormState(): CreditNoteFormState` — returns default form state
    - `getInitialRefundFormState(): RefundFormState` — returns default form state
    - _Requirements: 1.2, 1.6, 1.7, 1.8, 1.10, 2.3, 2.4, 3.2, 3.7, 3.8, 3.10, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 8.5, 8.6, 10.3_

  - [x] 1.2 Write property-based tests for validation and formatting utilities
    - Create `frontend/src/pages/invoices/__tests__/refund-credit-note.properties.test.ts`
    - **Property 1: Creditable amount computation** — generate random invoice totals and credit note amount arrays, verify `computeCreditableAmount` returns `max(0, total - sum)`. **Validates: Requirements 1.2, 7.2**
    - **Property 2: Payment summary computation** — generate random payment arrays with `is_refund` flags, verify `computePaymentSummary` returns correct `totalPaid`, `totalRefunded`, `netPaid`. **Validates: Requirements 3.2, 6.4, 10.3**
    - **Property 3: Amount validation bounds** — generate random amounts and positive maximums, verify `validateAmount` accepts iff `0 < amount ≤ max`. **Validates: Requirements 1.7, 1.8, 3.7, 3.8**
    - **Property 4: Empty reason rejection** — generate random whitespace-only strings, verify `validateReason` returns "Reason is required". **Validates: Requirements 1.6**
    - **Property 5: NZD currency formatting** — generate random finite numbers, verify `formatNZD` output starts with "$", has exactly 2 decimal digits, uses comma thousands separators. **Validates: Requirements 1.10, 3.10**
    - **Property 6: Credit note item running total** — generate random item amount arrays, verify `computeItemsTotal` equals sum. **Validates: Requirements 2.3**
    - **Property 7: Item amount mismatch detection** — generate random credit note amounts and item arrays, verify `hasItemAmountMismatch` returns true iff items non-empty and sum ≠ amount. **Validates: Requirements 2.4**
    - **Property 8: Credit note button visibility by invoice status** — generate random statuses, verify `isCreditNoteButtonVisible` returns true iff status ∈ allowed set. **Validates: Requirements 5.1, 5.2**
    - **Property 9: Refund button visibility by amount paid** — generate random `amountPaid` values, verify `isRefundButtonVisible` returns true iff > 0. **Validates: Requirements 5.3, 5.4**
    - **Property 10: Payment vs refund badge assignment** — generate random `is_refund` booleans, verify `getPaymentBadgeType` returns correct label and color. **Validates: Requirements 6.1, 6.2, 10.2**
    - **Property 11: Refund note conditional display** — generate random refund records with/without `refund_note`, verify `shouldShowRefundNote` returns correct boolean. **Validates: Requirements 6.3**
    - Use `fc.assert(fc.property(...))` pattern with minimum 100 iterations per property
    - Tag format: `// Feature: refund-credit-note-ui, Property {N}: {title}`

- [x] 2. Checkpoint — Validate utilities and property tests
  - Ensure all property-based tests pass, ask the user if questions arise.

- [x] 3. Implement CreditNoteModal component
  - [x] 3.1 Create `frontend/src/components/invoices/CreditNoteModal.tsx`
    - Import and use existing UI components: Modal, Button, Spinner, FormField, Input, Toast (useToast)
    - Import validation/formatting functions from `refund-credit-note.utils.ts`
    - Implement `CreditNoteModalProps` interface: `open`, `onClose`, `onSuccess`, `invoiceId`, `creditableAmount`
    - Manage form state with `useState`: amount, reason, items (CreditNoteItem[]), errors, apiError, submitting
    - Display `creditableAmount` as helper text on amount field using `formatNZD`
    - Validate on blur and on submit using `validateAmount` and `validateReason`
    - "Add Item" button appends row with description + amount fields; remove button per row
    - Show running total of items via `computeItemsTotal`; show mismatch warning via `hasItemAmountMismatch`
    - Submit sends `POST /api/v1/invoices/{invoiceId}/credit-note` via `apiClient` with `{ amount, reason, items, process_stripe_refund: false }`
    - On success: close modal, call `onSuccess`, show success toast
    - On error: display `err?.response?.data?.detail || 'Something went wrong. Please try again.'` inline
    - Disable submit button and show Spinner while `submitting` is true
    - Reset all state on close/reopen using `useEffect` keyed on `open`
    - _Requirements: 1.1–1.10, 2.1–2.4, 8.1, 8.3, 8.5, 9.1, 9.3_

  - [x] 3.2 Write unit tests for CreditNoteModal
    - Create `frontend/src/components/invoices/__tests__/CreditNoteModal.test.tsx`
    - Test: renders form fields (amount, reason, items section) when opened
    - Test: displays creditable amount helper text
    - Test: shows validation errors on blur for empty reason and invalid amount
    - Test: submits correct payload to API endpoint
    - Test: shows success toast and calls onSuccess on API success
    - Test: shows inline error message on API failure, modal stays open
    - Test: disables submit button during loading
    - Test: add item row and remove item row
    - Test: shows item total and mismatch warning
    - Test: resets form state when closed and reopened
    - _Requirements: 1.1–1.10, 2.1–2.4, 8.1, 8.3, 8.5_

  - [x] 3.3 Write property-based test for modal form reset (CreditNoteModal)
    - Add to `frontend/src/pages/invoices/__tests__/refund-credit-note.properties.test.ts`
    - **Property 12: Modal form reset on reopen** — generate random form field values, verify `getInitialCreditNoteFormState()` always returns the same default values regardless of prior state. **Validates: Requirements 8.5, 8.6**

- [x] 4. Implement RefundModal component
  - [x] 4.1 Create `frontend/src/components/invoices/RefundModal.tsx`
    - Import and use existing UI components: Modal, Button, Spinner, FormField, Input, Select, ConfirmDialog, Toast (useToast)
    - Import validation/formatting functions from `refund-credit-note.utils.ts`
    - Implement `RefundModalProps` interface: `open`, `onClose`, `onSuccess`, `invoiceId`, `refundableAmount`
    - Manage form state with `useState`: amount, method (default 'cash'), notes, errors, apiError, submitting, showConfirm
    - Display `refundableAmount` as helper text on amount field using `formatNZD`
    - Pre-select "Cash" in method select; disable "Stripe" option with "(Disabled — ISSUE-072)" label
    - Validate on blur and on submit using `validateAmount`
    - Two-step flow: form → confirmation summary (shows amount, method, notes) → API call
    - Cancel on confirmation returns to form editing state (`showConfirm = false`)
    - Submit sends `POST /api/v1/payments/refund` via `apiClient` with `{ invoice_id, amount, method: 'cash', notes }`
    - On success: close modal, call `onSuccess`, show success toast
    - On error: display error inline, return to form state
    - Disable submit button and show Spinner while `submitting` is true
    - Reset all state on close/reopen using `useEffect` keyed on `open`
    - _Requirements: 3.1–3.10, 4.1–4.3, 8.2, 8.4, 8.6, 9.2, 9.4_

  - [x] 4.2 Write unit tests for RefundModal
    - Create `frontend/src/components/invoices/__tests__/RefundModal.test.tsx`
    - Test: renders form fields with Cash pre-selected and Stripe disabled
    - Test: displays refundable amount helper text
    - Test: shows validation errors on blur for invalid amount
    - Test: shows confirmation step with amount, method, notes before API call
    - Test: cancel confirmation returns to form editing state
    - Test: submits correct payload to API endpoint
    - Test: shows success toast and calls onSuccess on API success
    - Test: shows inline error message on API failure, modal stays open
    - Test: disables submit button during loading
    - Test: resets form state when closed and reopened
    - _Requirements: 3.1–3.10, 4.1–4.3, 8.2, 8.4, 8.6_

- [x] 5. Checkpoint — Validate modal components
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Modify InvoiceDetail.tsx for action buttons and enhanced display
  - [x] 6.1 Extend Payment interface and add modal state to InvoiceDetail.tsx
    - Add `is_refund?: boolean` and `refund_note?: string` to the existing Payment interface
    - Add `creditNoteModalOpen` and `refundModalOpen` useState hooks
    - Compute `creditableAmount` using `computeCreditableAmount` from utils
    - Compute `totalPaid`, `totalRefunded`, `netPaid` using `computePaymentSummary` from utils
    - Compute `refundableAmount` from payment summary
    - _Requirements: 10.1, 10.3_

  - [x] 6.2 Add action buttons to invoice header
    - Render "Create Credit Note" button using `isCreditNoteButtonVisible(invoice.status)` — visible for 'issued', 'partially_paid', 'paid'
    - Render "Process Refund" button using `isRefundButtonVisible(invoice.amount_paid)` — visible when amount_paid > 0
    - Wire buttons to open respective modals
    - _Requirements: 5.1–5.6_

  - [x] 6.3 Enhance payment history table
    - Add badge column: green "Payment" or red "Refund" badge per row using `getPaymentBadgeType`
    - Apply red-tinted text to refund row amounts
    - Display `refund_note` below refund rows when present using `shouldShowRefundNote`
    - Add summary row below table: Total Paid, Total Refunded, Net Paid formatted with `formatNZD`
    - _Requirements: 6.1–6.4, 10.2_

  - [x] 6.4 Enhance credit notes section
    - Add "Create Credit Note" link/button in credit notes section header, wired to open CreditNoteModal
    - Add running total row at bottom of credit notes table using `formatNZD`
    - _Requirements: 7.1–7.3_

  - [x] 6.5 Wire modals and refresh callback
    - Import and render CreditNoteModal and RefundModal with correct props
    - Pass `fetchInvoice` as `onSuccess` callback to both modals
    - Pass computed `creditableAmount` and `refundableAmount` to respective modals
    - _Requirements: 5.5–5.7_

  - [x] 6.6 Write unit tests for InvoiceDetail modifications
    - Create `frontend/src/pages/invoices/__tests__/InvoiceDetail.refund.test.tsx`
    - Test: "Create Credit Note" button visible for issued/partially_paid/paid statuses, hidden for draft/voided
    - Test: "Process Refund" button visible when amount_paid > 0, hidden when 0
    - Test: clicking buttons opens respective modals
    - Test: payment history renders green "Payment" and red "Refund" badges correctly
    - Test: refund rows show red-tinted amount text
    - Test: refund note displayed below refund rows when present
    - Test: payment summary row shows Total Paid, Total Refunded, Net Paid
    - Test: credit notes section shows "Create Credit Note" link and running total
    - Test: modal onSuccess triggers invoice data re-fetch
    - _Requirements: 5.1–5.7, 6.1–6.4, 7.1–7.3, 10.1–10.3_

- [x] 7. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- All validation logic lives in `refund-credit-note.utils.ts` as pure functions for direct PBT testing
- Property-based tests use `fast-check` with Vitest, minimum 100 iterations per property
- No new npm dependencies — uses existing UI components and `apiClient`
- Stripe refunds disabled per ISSUE-072; `process_stripe_refund` always set to `false`
