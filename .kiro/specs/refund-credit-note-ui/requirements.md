# Requirements Document

## Introduction

This feature completes the missing frontend UI for the existing, fully-implemented backend refund and credit note APIs. The backend endpoints, business logic, database schema, and tests are 100% complete. The frontend currently displays credit notes and payment history in read-only tables on the InvoiceDetail page but lacks creation forms, action buttons, and visual distinction between payments and refunds. This spec covers three files: two new modal components (CreditNoteModal, RefundModal) and modifications to InvoiceDetail.tsx.

## Glossary

- **InvoiceDetail_Page**: The existing page component (`frontend/src/pages/invoices/InvoiceDetail.tsx`) that displays a single invoice with its line items, payment history, and credit notes.
- **CreditNote_Modal**: A new modal component (`frontend/src/components/invoices/CreditNoteModal.tsx`) for creating credit notes against an invoice.
- **Refund_Modal**: A new modal component (`frontend/src/components/invoices/RefundModal.tsx`) for processing cash refunds against an invoice.
- **Credit_Note**: A record that reduces an invoice's balance due, identified by a sequential reference number (e.g. CN-0001), with an amount, reason, and optional line items.
- **Refund**: A negative payment record against an invoice, processed via the `POST /api/v1/payments/refund` endpoint, currently limited to cash method only.
- **apiClient**: The existing Axios-based HTTP client at `frontend/src/api/client` used for all API calls.
- **NZD_Format**: New Zealand Dollar currency formatting using `Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' })`.
- **Creditable_Amount**: The maximum amount that can be credited against an invoice, calculated as invoice total minus the sum of existing credit note amounts.
- **Refundable_Amount**: The maximum amount that can be refunded, calculated as total amount paid minus total already refunded.

## Requirements

### Requirement 1: Credit Note Creation Modal

**User Story:** As a workshop staff member, I want to create a credit note against an invoice from the invoice detail page, so that I can formally reduce the amount owed by a customer.

#### Acceptance Criteria

1. WHEN the user clicks the "Create Credit Note" button, THE CreditNote_Modal SHALL open displaying a form with fields for amount (number input), reason (textarea), and an optional itemised breakdown section.
2. THE CreditNote_Modal SHALL display the Creditable_Amount as helper text on the amount field, calculated as invoice total minus the sum of existing credit note amounts.
3. WHEN the user submits the form with a valid amount greater than zero and less than or equal to the Creditable_Amount and a non-empty reason, THE CreditNote_Modal SHALL send a POST request to `/api/v1/invoices/{invoice_id}/credit-note` via apiClient with the fields `amount`, `reason`, `items`, and `process_stripe_refund` set to false.
4. WHEN the API returns a successful response, THE CreditNote_Modal SHALL close, trigger a parent data refresh callback, and display a success toast notification.
5. WHEN the API returns an error response, THE CreditNote_Modal SHALL display the error message inline within the modal and remain open.
6. IF the user submits the form with an empty reason, THEN THE CreditNote_Modal SHALL display a validation error "Reason is required" and prevent submission.
7. IF the user submits the form with an amount of zero or less, THEN THE CreditNote_Modal SHALL display a validation error "Amount must be greater than zero" and prevent submission.
8. IF the user submits the form with an amount exceeding the Creditable_Amount, THEN THE CreditNote_Modal SHALL display a validation error indicating the maximum creditable amount and prevent submission.
9. WHILE the API request is in progress, THE CreditNote_Modal SHALL disable the submit button and display a loading indicator.
10. THE CreditNote_Modal SHALL format all monetary values using NZD_Format.

### Requirement 2: Credit Note Itemised Breakdown

**User Story:** As a workshop staff member, I want to optionally add line item details to a credit note, so that the credit note records which specific charges are being credited.

#### Acceptance Criteria

1. THE CreditNote_Modal SHALL include an "Add Item" button that appends a new row with description (text input) and amount (number input) fields.
2. WHEN the user clicks a remove button on an item row, THE CreditNote_Modal SHALL remove that row from the items list.
3. WHEN item rows are present, THE CreditNote_Modal SHALL display a running total of all item amounts.
4. IF the sum of item amounts does not equal the credit note amount field, THEN THE CreditNote_Modal SHALL display a warning message indicating the mismatch but still allow submission.

### Requirement 3: Refund Processing Modal

**User Story:** As a workshop staff member, I want to process a cash refund against an invoice, so that I can record money returned to a customer.

#### Acceptance Criteria

1. WHEN the user clicks the "Process Refund" button, THE Refund_Modal SHALL open displaying a form with fields for amount (number input), refund method (select), and notes (textarea).
2. THE Refund_Modal SHALL display the Refundable_Amount as helper text on the amount field.
3. THE Refund_Modal SHALL pre-select "Cash" as the refund method and disable the "Stripe" option with a tooltip or label indicating "Stripe refunds are currently disabled (ISSUE-072)".
4. WHEN the user fills in a valid amount greater than zero and less than or equal to the Refundable_Amount and confirms the refund, THE Refund_Modal SHALL send a POST request to `/api/v1/payments/refund` via apiClient with the fields `invoice_id`, `amount`, `method` set to "cash", and `notes`.
5. WHEN the API returns a successful response, THE Refund_Modal SHALL close, trigger a parent data refresh callback, and display a success toast notification.
6. WHEN the API returns an error response, THE Refund_Modal SHALL display the error message inline within the modal and remain open.
7. IF the user submits the form with an amount of zero or less, THEN THE Refund_Modal SHALL display a validation error "Amount must be greater than zero" and prevent submission.
8. IF the user submits the form with an amount exceeding the Refundable_Amount, THEN THE Refund_Modal SHALL display a validation error indicating the maximum refundable amount and prevent submission.
9. WHILE the API request is in progress, THE Refund_Modal SHALL disable the submit button and display a loading indicator.
10. THE Refund_Modal SHALL format all monetary values using NZD_Format.

### Requirement 4: Refund Confirmation Step

**User Story:** As a workshop staff member, I want to confirm before processing a refund, so that I do not accidentally issue refunds.

#### Acceptance Criteria

1. WHEN the user clicks the submit button on the Refund_Modal, THE Refund_Modal SHALL display a confirmation summary showing the refund amount, method, and notes before sending the API request.
2. WHEN the user confirms the summary, THE Refund_Modal SHALL proceed with the API request.
3. WHEN the user cancels the confirmation, THE Refund_Modal SHALL return to the form editing state without sending the API request.

### Requirement 5: Invoice Detail Action Buttons

**User Story:** As a workshop staff member, I want "Create Credit Note" and "Process Refund" buttons on the invoice detail page, so that I can access these actions directly from the invoice.

#### Acceptance Criteria

1. WHEN the invoice status is "issued", "partially_paid", or "paid", THE InvoiceDetail_Page SHALL display a "Create Credit Note" button in the header action bar.
2. WHEN the invoice status is "draft" or "voided", THE InvoiceDetail_Page SHALL hide the "Create Credit Note" button.
3. WHEN the invoice amount_paid is greater than zero, THE InvoiceDetail_Page SHALL display a "Process Refund" button in the header action bar.
4. WHEN the invoice amount_paid is zero, THE InvoiceDetail_Page SHALL hide the "Process Refund" button.
5. WHEN the user clicks the "Create Credit Note" button, THE InvoiceDetail_Page SHALL open the CreditNote_Modal.
6. WHEN the user clicks the "Process Refund" button, THE InvoiceDetail_Page SHALL open the Refund_Modal.
7. WHEN either modal triggers its success callback, THE InvoiceDetail_Page SHALL re-fetch the invoice data to reflect updated balances, payment history, and credit notes.

### Requirement 6: Enhanced Payment History Display

**User Story:** As a workshop staff member, I want to visually distinguish between payments and refunds in the payment history, so that I can quickly understand the financial activity on an invoice.

#### Acceptance Criteria

1. THE InvoiceDetail_Page SHALL display a green "Payment" badge next to regular payment rows and a red "Refund" badge next to refund rows in the payment history table.
2. WHEN a payment record has `is_refund` set to true, THE InvoiceDetail_Page SHALL display the row with red-tinted text for the amount.
3. WHEN a refund record has a `refund_note` value, THE InvoiceDetail_Page SHALL display the refund note text below the refund row.
4. THE InvoiceDetail_Page SHALL display a summary row below the payment history table showing Total Paid, Total Refunded, and Net Paid values formatted using NZD_Format.

### Requirement 7: Enhanced Credit Notes Display

**User Story:** As a workshop staff member, I want to see a running total of credit notes and have quick access to create new ones from the credit notes section, so that I can manage credits efficiently.

#### Acceptance Criteria

1. THE InvoiceDetail_Page SHALL display a "Create Credit Note" link or button within the credit notes section header.
2. WHEN credit notes exist, THE InvoiceDetail_Page SHALL display a running total row at the bottom of the credit notes table showing the sum of all credit note amounts formatted using NZD_Format.
3. WHEN the user clicks the credit notes section "Create Credit Note" link, THE InvoiceDetail_Page SHALL open the CreditNote_Modal.

### Requirement 8: Form State Management

**User Story:** As a workshop staff member, I want the credit note and refund forms to follow the same patterns as other forms in the application, so that the experience is consistent.

#### Acceptance Criteria

1. THE CreditNote_Modal SHALL manage form state using React useState hooks, consistent with the existing InvoiceDetail void modal pattern.
2. THE Refund_Modal SHALL manage form state using React useState hooks, consistent with the existing InvoiceDetail void modal pattern.
3. THE CreditNote_Modal SHALL perform inline validation on blur and on submit, displaying field-level error messages.
4. THE Refund_Modal SHALL perform inline validation on blur and on submit, displaying field-level error messages.
5. WHEN the CreditNote_Modal is closed and reopened, THE CreditNote_Modal SHALL reset all form fields and validation errors to their initial state.
6. WHEN the Refund_Modal is closed and reopened, THE Refund_Modal SHALL reset all form fields and validation errors to their initial state.

### Requirement 9: No New Dependencies

**User Story:** As a developer, I want this feature to use only existing UI components and libraries, so that the bundle size and dependency surface remain unchanged.

#### Acceptance Criteria

1. THE CreditNote_Modal SHALL use only existing components from `frontend/src/components/ui/` (Modal, Button, Badge, Spinner, FormField, Input, Select, Toast).
2. THE Refund_Modal SHALL use only existing components from `frontend/src/components/ui/` (Modal, Button, Badge, Spinner, FormField, Input, Select, Toast).
3. THE CreditNote_Modal SHALL not introduce any new npm dependencies including form libraries (react-hook-form, formik) or validation libraries (zod, yup).
4. THE Refund_Modal SHALL not introduce any new npm dependencies including form libraries (react-hook-form, formik) or validation libraries (zod, yup).

### Requirement 10: Payment History Data Integration

**User Story:** As a workshop staff member, I want the payment history to include refund data from the backend, so that I see a complete financial picture.

#### Acceptance Criteria

1. THE InvoiceDetail_Page SHALL extend the Payment interface to include `is_refund` (boolean) and `refund_note` (string or null) fields.
2. WHEN the invoice data is fetched, THE InvoiceDetail_Page SHALL render payment history rows using the `is_refund` field to determine payment versus refund styling.
3. THE InvoiceDetail_Page SHALL compute Total Paid, Total Refunded, and Net Paid from the payments array where `is_refund` distinguishes the two categories.
