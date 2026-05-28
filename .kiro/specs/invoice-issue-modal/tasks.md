# Tasks — Invoice Issue Modal

## Task 1: Create IssueInvoiceModal component

- [x] 1. Create `IssueInvoiceModal` component
  - [x] 1.1 Create new file `frontend/src/pages/invoices/IssueInvoiceModal.tsx`
    - Import `Modal`, `Button` from `../../components/ui`
    - Define `IssueInvoiceModalProps` interface: `open`, `onClose`, `onConfirm`, `customerEmail`, `loading`, `stripeConnected`, `error`
    - Render payment method radio buttons: Cash (value `cash`), EFTPOS (value `eftpos`), Bank Transfer (value `bank_transfer`), Online Payment (value `stripe`)
    - Disable "Online Payment" radio when `stripeConnected === false`, show "(not configured)" hint text
    - Render "Email invoice to customer" checkbox, default checked when `customerEmail` is non-empty
    - Show customer email address text below checkbox when checked
    - Render "Issue Invoice" primary button that calls `onConfirm(paymentMethod, shouldEmail)`
    - Show loading spinner on "Issue Invoice" button when `loading === true`
    - Disable both "Issue Invoice" and "Cancel" buttons when `loading === true`
    - Render "Cancel" secondary button that calls `onClose`
    - Show inline red error text below buttons when `error` prop is non-null
    - Local state: `paymentMethod` (default `'cash'`), `emailInvoice` (default based on `customerEmail`)
    - Min touch target 44px on all interactive elements
  - [x] 1.2 Export the component from the new file

## Task 2: Wire modal into InvoiceCreate

- [x] 2. Integrate `IssueInvoiceModal` into `InvoiceCreate.tsx`
  - [x] 2.1 Add new state variables
    - `const [issueModalOpen, setIssueModalOpen] = useState(false)`
    - `const [issueError, setIssueError] = useState<string | null>(null)`
  - [x] 2.2 Create `handleCreateInvoice` function
    - Calls `validate()` — if fails, return early (don't open modal)
    - Sets `setIssueModalOpen(true)`
  - [x] 2.3 Create `handleIssueConfirm` function
    - Signature: `async (paymentMethod: string, shouldEmail: boolean) => void`
    - Sets `setSaving(true)` and `setIssueError(null)`
    - Sets `setPaymentGateway(paymentMethod)` so `buildPayload` picks it up
    - Determines `status`: `shouldEmail ? 'sent' : 'issued'`
    - For edit mode (`isEditMode && editId`): calls `apiClient.put(`/invoices/${editId}`, buildPayload(status))`
    - For create mode: calls `apiClient.post('/invoices', buildPayload(status))`
    - On success: calls `setIssueModalOpen(false)`, navigates to invoice detail (same pattern as existing `handleSaveAndSend`)
    - On error: sets `setIssueError(err?.response?.data?.detail ?? 'Failed to issue invoice')`
    - Finally: sets `setSaving(false)`
  - [x] 2.4 Render `IssueInvoiceModal` in JSX
    - Place after the existing "Mark Paid & Email" Modal
    - Pass props: `open={issueModalOpen}`, `onClose={() => { setIssueModalOpen(false); setIssueError(null) }}`, `onConfirm={handleIssueConfirm}`, `customerEmail={customer?.email ?? null}`, `loading={saving}`, `stripeConnected={stripeConnected}`, `error={issueError}`
  - [x] 2.5 Import `IssueInvoiceModal` at top of file

## Task 3: Rewire "Create Invoice" buttons

- [x] 3. Change "Create Invoice" button behavior
  - [x] 3.1 Header button bar (line ~1822): Change `onClick={handleSaveAndSend}` to `onClick={handleCreateInvoice}`
  - [x] 3.2 Bottom button bar (line ~2521): Change `onClick={handleSaveAndSend}` to `onClick={handleCreateInvoice}`
  - [x] 3.3 Change button text in edit mode: `{isEditMode ? 'Issue Invoice' : 'Create Invoice'}`
  - [x] 3.4 Remove or mark `handleSaveAndSend` as unused (the new `handleIssueConfirm` replaces it)

## Task 4: Remove inline payment method from form body

- [x] 4. Remove payment method radio buttons from form
  - [x] 4.1 Delete the "Payment Method" section (lines ~2406-2490) containing the radio buttons for Cash, EFTPOS, Bank Transfer, Stripe
  - [x] 4.2 Keep the `paymentGateway` state variable (still needed — set from modal via `handleIssueConfirm`)
  - [x] 4.3 Keep the `stripeConnected` state and its useEffect (still needed — passed to modal)

## Task 5: Rename "Stripe" to "Online Payment"

- [x] 5. Rename user-facing "Stripe" labels
  - [x] 5.1 In `IssueInvoiceModal.tsx`: label the stripe radio as "Online Payment"
  - [x] 5.2 In the "Mark Paid & Email" modal (line ~2527): if "stripe" appears as an option label, rename to "Online Payment" (currently it uses Cash/EFTPOS/Bank Transfer/Card/Cheque — no Stripe option here, so no change needed)
  - [x] 5.3 Search for any other user-facing "Stripe" text in InvoiceCreate.tsx and rename (the disabled state hint can say "Online Payment — not configured")

## Task 6: Verify and test

- [ ] 6. Verification
  - [x] 6.1 Run TypeScript diagnostics on `IssueInvoiceModal.tsx` — zero errors
  - [x] 6.2 Run TypeScript diagnostics on `InvoiceCreate.tsx` — zero errors
  - [ ] 6.3 Verify in browser: click "Create Invoice" → modal opens with payment method radios and email checkbox
  - [ ] 6.4 Verify: select "Online Payment" when Stripe not connected → radio is disabled
  - [ ] 6.5 Verify: uncheck email → confirm → invoice created with `status: "issued"` (no email sent)
  - [ ] 6.6 Verify: check email → confirm → invoice created with `status: "sent"` (email sent)
  - [ ] 6.7 Verify: "Save as Draft" still works without modal
  - [ ] 6.8 Verify: "Mark Paid & Email" still works with its own modal
  - [ ] 6.9 Verify: payment method radios no longer appear in the form body
  - [ ] 6.10 Verify: edit mode shows "Issue Invoice" button text and modal works the same way
