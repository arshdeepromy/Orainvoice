# Implementation Plan: POS Invoice Receipt Printing

## Overview

This plan implements POS receipt printing from the invoice detail page and POS screen by bridging existing invoice data with the ESC/POS printer infrastructure. The work proceeds bottom-up: extend the shared ESC/POS layer, add the pure mapping function, build the printer service, create UI components, then integrate into existing pages.

## Tasks

- [x] 1. Extend ReceiptData interface and buildReceipt() in escpos.ts
  - [x] 1.1 Add new optional fields to the `ReceiptData` interface: `customerName`, `gstNumber`, `amountPaid`, `balanceDue`, `paymentBreakdown`
    - Add `customerName?: string`
    - Add `gstNumber?: string`
    - Add `amountPaid?: number`
    - Add `balanceDue?: number`
    - Add `paymentBreakdown?: Array<{ method: string; amount: number }>`
    - _Requirements: 4.5, 4.7, 4.8, 4.9, 4.10_

  - [x] 1.2 Extend `buildReceipt()` to render the new fields when present
    - After org header: render `GST: {gstNumber}` line when `gstNumber` is defined
    - After date line: render `Customer: {customerName}` when `customerName` is defined
    - After payment method: render each `paymentBreakdown` entry as `{method}: {amount}`
    - After payment section: render `Amount Paid: {amountPaid}` when defined
    - Render bold `BALANCE DUE: {balanceDue}` when `balanceDue > 0`
    - Existing receipt output must remain unchanged when new fields are undefined
    - _Requirements: 4.5, 4.7, 4.8, 4.9, 4.10, 4.11_

- [x] 2. Create invoiceToReceiptData() mapping function
  - [x] 2.1 Create `frontend/src/utils/invoiceReceiptMapper.ts` with the `invoiceToReceiptData()` function
    - Define `InvoiceForReceipt` interface matching the fields needed from `InvoiceDetail`
    - Map `org_name`, `org_address`, `org_phone`, `org_gst_number` to receipt header fields
    - Map `invoice_number` to `receiptNumber` with "DRAFT" fallback when null
    - Map `issue_date` (or `created_at` fallback) to `date` formatted as DD/MM/YYYY
    - Map customer name using `display_name` or `first_name + last_name` with trimming
    - Map `line_items` array to `ReceiptLineItem[]` (first line of description only)
    - Map `subtotal`, `gst_amount`, `discount_amount`, `total`, `amount_paid`, `balance_due`
    - Map `payments` array to `paymentBreakdown` and summarise methods for `paymentMethod`
    - Map `notes_customer` to `footer` with "Thank you for your business!" default
    - Export `formatReceiptDate()` helper
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 6.1, 6.2_

  - [x] 2.2 Write property test: field mapping preservation
    - **Property 1: Invoice-to-receipt field mapping preservation**
    - **Validates: Requirements 4.1, 4.2, 4.7, 4.10, 6.1, 6.2**

  - [x] 2.3 Write property test: invoice number DRAFT fallback
    - **Property 2: Invoice number maps to receipt number with DRAFT fallback**
    - **Validates: Requirements 4.3**

  - [x] 2.4 Write property test: date formatting with issue_date fallback
    - **Property 3: Date formatting with issue_date fallback**
    - **Validates: Requirements 4.4**

  - [x] 2.5 Write property test: customer name resolution
    - **Property 4: Customer name resolution**
    - **Validates: Requirements 4.5**

  - [x] 2.6 Write property test: line items and payments array mapping
    - **Property 5: Line items and payments array mapping**
    - **Validates: Requirements 4.6, 4.8**

- [x] 3. Checkpoint — Verify mapping layer
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Create POSReceiptPrinter service module
  - [x] 4.1 Create `frontend/src/utils/posReceiptPrinter.ts` with fallback mode management
    - Implement `isFallbackModeActive()` reading from localStorage key `pos_printer_fallback_mode`
    - Implement `setFallbackMode(active: boolean)` and `clearFallbackMode()`
    - Wrap localStorage access in try/catch for private browsing compatibility
    - _Requirements: 3.4, 3.5_

  - [x] 4.2 Implement default printer resolution and print orchestration
    - Implement `resolveDefaultPrinter()` fetching from `/api/v2/printers` with safe API patterns (`res.data?.items ?? res.data ?? []`)
    - Find first printer where `is_default === true` and `is_active === true`
    - Implement `printReceipt(receiptData, paperWidth)` — checks fallback mode, resolves printer, builds ESC/POS bytes, dispatches via `createDriver()`
    - Implement `printInvoiceReceipt(invoice)` — calls `invoiceToReceiptData()` then `printReceipt()`
    - Implement `browserPrintReceipt(receiptData, paperWidth)` for manual fallback
    - Export `NoPrinterError` class for no-default-printer scenario
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.4_

  - [x] 4.3 Write property test: default printer resolution from printer list
    - **Property 8: Default printer resolution from printer list**
    - **Validates: Requirements 2.1**

  - [x] 4.4 Write property test: fallback mode bypasses physical printer
    - **Property 9: Fallback mode bypasses physical printer**
    - **Validates: Requirements 3.4**

  - [x] 4.5 Write property test: fallback mode localStorage round-trip
    - **Property 10: Fallback mode localStorage round-trip**
    - **Validates: Requirements 3.5**

- [x] 5. Checkpoint — Verify service layer
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Create ESC/POS round-trip and bold rendering property tests
  - [x] 6.1 Write property test: invoice-to-receipt-to-ESC/POS round-trip integrity
    - **Property 6: Invoice-to-receipt-to-ESC/POS round-trip integrity**
    - **Validates: Requirements 4.11**

  - [x] 6.2 Write property test: balance due bold rendering in ESC/POS output
    - **Property 7: Balance due bold rendering in ESC/POS output**
    - **Validates: Requirements 4.9**

- [x] 7. Create POSReceiptPreview component
  - [x] 7.1 Create `frontend/src/components/pos/POSReceiptPreview.tsx`
    - Accept `receiptData: ReceiptData` and `paperWidth: number` props
    - Render narrow column with `maxWidth` matching paper width (48mm for 58mm paper, 72mm for 80mm)
    - Use monospace font (`Courier New`)
    - Display: org header, GST number, invoice number, date, customer name, line items, separator, subtotal, discount, GST, total, payment breakdown, amount paid, balance due (bold if non-zero), footer
    - Add subtle dashed border to simulate paper edge
    - Update dynamically when `paperWidth` changes
    - Default to 80mm when no printer configured
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 7.2 Write unit tests for POSReceiptPreview
    - Test renders with correct narrow width and monospace font
    - Test displays all receipt sections (header, items, totals, footer)
    - _Requirements: 5.2, 5.3_

- [x] 8. Create PrinterErrorModal component
  - [x] 8.1 Create `frontend/src/components/pos/PrinterErrorModal.tsx`
    - Accept `open`, `onClose`, `errorMessage`, `onBrowserPrint` props
    - Display error message from the driver
    - "Use Browser Print" button calling `onBrowserPrint(enableFallback)`
    - "Enable Browser Print for Future Prints" checkbox
    - "Go to Printer Settings" link navigating to `/settings/printers`
    - Use existing `Modal` component from `../../components/ui`
    - _Requirements: 3.1, 3.2, 3.3, 3.7_

  - [x] 8.2 Write unit tests for PrinterErrorModal
    - Test renders error message, browser print button, checkbox, and settings link
    - Test checkbox + browser print activates fallback mode via callback
    - _Requirements: 3.1, 3.2, 3.3, 3.7_

- [x] 9. Integrate POS Print into InvoiceDetail.tsx
  - [x] 9.1 Add POS Print button, receipt preview toggle, success toast, and error modal
    - Add "POS Print" button in the action button row (hidden when `status === 'draft'`)
    - Add loading spinner state (`posPrinting`) that disables button and shows "Printing…"
    - On success: show green success toast "Receipt printed successfully" with 3-second auto-dismiss
    - On browser fallback success: show neutral message "Receipt sent to browser print dialog"
    - On error: open `PrinterErrorModal` with error details
    - Add "Receipt Preview" toggle button that switches to `POSReceiptPreview` view
    - Wire `PrinterErrorModal` browser print callback to `browserPrintReceipt()` and `setFallbackMode()`
    - Import and use `printInvoiceReceipt`, `browserPrintReceipt`, `invoiceToReceiptData` from service modules
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 5.1, 8.1, 8.2, 8.3, 8.4_

  - [x] 9.2 Write unit tests for InvoiceDetail POS Print integration
    - Test POS Print button visibility (present for non-draft, hidden for draft)
    - Test POS Print button disabled state during printing
    - Test success toast appears and auto-dismisses after 3 seconds
    - Test NoPrinterError opens PrinterErrorModal
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.6_

- [x] 10. Integrate Print Receipt into POSScreen.tsx
  - [x] 10.1 Add Print Receipt button after payment completion
    - Add `paymentComplete` state that shows a "Print Receipt" button after `handlePaymentComplete`
    - Store the completed transaction data needed for receipt mapping
    - Wire to `printInvoiceReceipt()` or `printReceipt()` with the same default printer resolution and fallback logic
    - Add `PrinterErrorModal` for error handling with browser print fallback
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 10.2 Write unit tests for POSScreen Print Receipt integration
    - Test Print Receipt button appears after payment completion
    - Test same print flow and error handling as InvoiceDetail
    - _Requirements: 7.2, 7.3, 7.4_

- [x] 11. Update PrinterSettings.tsx to clear fallback mode on successful test print
  - [x] 11.1 Import `clearFallbackMode` and call it in the test print success path
    - In `handleTestPrint` success branch, call `clearFallbackMode()` after setting the success result
    - _Requirements: 3.6_

- [x] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (Properties 1–10)
- Unit tests validate specific examples and edge cases
- The design uses TypeScript throughout — all implementations use TypeScript/React
- All API response handling must follow safe-api-consumption patterns (`?.` and `?? []` / `?? 0`)
