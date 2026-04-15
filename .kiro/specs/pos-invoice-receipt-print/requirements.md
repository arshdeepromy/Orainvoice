# Requirements Document

## Introduction

OraInvoice's invoice detail page currently supports A4 print preview (via `window.print()`) and PDF download. There is no way to print an invoice as a POS receipt from the invoice detail page, despite the application having a complete ESC/POS builder (`escpos.ts`), protocol-aware printer drivers (Star WebPRNT, Epson ePOS, Generic HTTP, Browser Print), and a printer settings page with default printer configuration and test print capability.

This feature bridges the gap between the invoice detail page and the existing POS printer infrastructure by adding: a POS receipt print button on the invoice detail page, automatic default printer resolution, a POS receipt preview (narrow thermal format), a receipt template that maps invoice data to the ESC/POS receipt format, and graceful error handling with browser print fallback when the configured printer fails.

## Glossary

- **Invoice_Detail_Page**: The React page (`InvoiceDetail.tsx`) that displays a single invoice with customer info, line items, totals, payments, credit notes, and action buttons (Print, Download PDF, Email, etc.).
- **POS_Receipt_Printer**: The frontend module that orchestrates printing an invoice as a POS receipt by resolving the default printer, building ESC/POS data from invoice data, and sending it via the appropriate printer driver.
- **Receipt_Template_Builder**: A frontend function that transforms an `InvoiceDetail` object into the `ReceiptData` structure consumed by the existing `buildReceipt()` function in `escpos.ts`.
- **POS_Receipt_Preview**: A UI component that renders a narrow-format, monospace-styled preview of how the invoice will appear when printed on a thermal receipt printer.
- **Default_Printer**: The printer configuration marked as `is_default: true` in the organisation's printer list, retrieved from the `/api/v2/printers` endpoint.
- **Browser_Print_Fallback**: A mode where the system uses the `BrowserPrintDriver` (hidden iframe + `window.print()`) instead of a physical printer driver, activated when the configured printer fails or no default printer is set.
- **Printer_Error_Modal**: A modal dialog displayed when a POS print attempt fails, showing the error details and offering a "Use Browser Print" fallback option.
- **Fallback_Mode**: A persistent frontend state (stored in `localStorage`) indicating that the user has opted to use browser print as fallback. Cleared when the user successfully tests a printer in Printer Settings.

## Requirements

### Requirement 1: POS Receipt Print Button

**User Story:** As an invoice operator, I want a dedicated POS receipt print button on the invoice detail page, so that I can print the invoice on a thermal receipt printer without using the A4 print flow.

#### Acceptance Criteria

1. THE Invoice_Detail_Page SHALL display a "POS Print" button in the action button row alongside the existing "Print" and "Download PDF" buttons.
2. WHEN the user clicks the "POS Print" button, THE POS_Receipt_Printer SHALL initiate the POS receipt printing flow for the currently displayed invoice.
3. WHILE a POS print job is in progress, THE Invoice_Detail_Page SHALL disable the "POS Print" button and display a "Printing…" label.
4. WHEN the POS print job completes successfully, THE Invoice_Detail_Page SHALL display a success message in the action feedback area.
5. IF the POS print job fails, THEN THE Invoice_Detail_Page SHALL open the Printer_Error_Modal with the failure details.
6. THE "POS Print" button SHALL be hidden when the invoice status is `draft`.

### Requirement 2: Default Printer Resolution

**User Story:** As an invoice operator, I want the POS print button to automatically use my configured default printer, so that I can print receipts with a single click without selecting a printer each time.

#### Acceptance Criteria

1. WHEN the user clicks the "POS Print" button, THE POS_Receipt_Printer SHALL fetch the list of printers from the `/api/v2/printers` endpoint and identify the printer where `is_default` is `true` and `is_active` is `true`.
2. WHEN a default active printer is found, THE POS_Receipt_Printer SHALL create a driver using `createDriver()` with the default printer's `connection_type` and `address`, and send the receipt data using the printer's configured `paper_width`.
3. IF no default active printer is found and Fallback_Mode is not active, THEN THE POS_Receipt_Printer SHALL open the Printer_Error_Modal with a message indicating that no default printer is configured and a link to Printer Settings.
4. IF no default active printer is found and Fallback_Mode is active, THEN THE POS_Receipt_Printer SHALL use the Browser_Print_Fallback to print the receipt.

### Requirement 3: Printer Error Handling and Browser Print Fallback

**User Story:** As an invoice operator, I want a clear error message and a fallback option when my POS printer fails, so that I can still print the receipt using the browser's print dialog.

#### Acceptance Criteria

1. IF the printer driver throws an error during a POS print attempt (connection refused, timeout, protocol error), THEN THE Printer_Error_Modal SHALL display the error message from the driver.
2. THE Printer_Error_Modal SHALL display a "Use Browser Print" button that prints the receipt using the Browser_Print_Fallback.
3. THE Printer_Error_Modal SHALL display a "Enable Browser Print for Future Prints" checkbox that, when checked and the user clicks "Use Browser Print", activates Fallback_Mode.
4. WHILE Fallback_Mode is active, THE POS_Receipt_Printer SHALL skip the physical printer driver and use the Browser_Print_Fallback directly for all POS print attempts.
5. THE POS_Receipt_Printer SHALL store the Fallback_Mode flag in `localStorage` so that the preference persists across page reloads.
6. WHEN the user successfully completes a test print in Printer Settings, THE Printer_Settings_UI SHALL clear the Fallback_Mode flag from `localStorage`.
7. THE Printer_Error_Modal SHALL display a "Go to Printer Settings" link that navigates to the printer settings page.

### Requirement 4: Invoice-to-Receipt Data Mapping

**User Story:** As an invoice operator, I want the POS receipt to contain all relevant invoice information formatted for a thermal printer, so that the receipt serves as a complete record of the transaction.

#### Acceptance Criteria

1. THE Receipt_Template_Builder SHALL map the invoice's `org_name` to the receipt header organisation name.
2. THE Receipt_Template_Builder SHALL map the invoice's `org_address` and `org_phone` to the receipt header address and phone fields.
3. THE Receipt_Template_Builder SHALL map the invoice's `invoice_number` to the receipt number field, using "DRAFT" when `invoice_number` is null.
4. THE Receipt_Template_Builder SHALL map the invoice's `issue_date` to the receipt date field, formatted as DD/MM/YYYY, using the `created_at` date when `issue_date` is null.
5. THE Receipt_Template_Builder SHALL map the invoice's customer name (from `customer.display_name` or `customer.first_name` + `customer.last_name`) to a "Customer:" line on the receipt.
6. THE Receipt_Template_Builder SHALL map each line item to a receipt line showing the item description, quantity, unit price, and line total.
7. THE Receipt_Template_Builder SHALL map the invoice's `subtotal`, `gst_amount`, `discount_amount`, `total`, `amount_paid`, and `balance_due` to the receipt totals section.
8. THE Receipt_Template_Builder SHALL map the invoice's `payments` array to a payment summary section showing each payment's method and amount.
9. WHEN the invoice has a non-zero `balance_due`, THE Receipt_Template_Builder SHALL include a "BALANCE DUE" line in bold on the receipt.
10. THE Receipt_Template_Builder SHALL include the invoice's `org_gst_number` on the receipt when present, formatted as "GST: {number}".
11. FOR ALL valid InvoiceDetail objects, converting to ReceiptData and then building ESC/POS bytes SHALL produce a non-empty byte array (round-trip integrity).

### Requirement 5: POS Receipt Preview

**User Story:** As an invoice operator, I want to preview how the invoice will look as a POS receipt before printing, so that I can verify the layout and content are correct.

#### Acceptance Criteria

1. THE Invoice_Detail_Page SHALL display a "Receipt Preview" toggle or tab that switches between the current A4 invoice view and the POS receipt preview.
2. WHEN the POS receipt preview is active, THE POS_Receipt_Preview SHALL render the receipt content in a narrow column (max-width matching the configured paper width: 58mm or 80mm) with a monospace font.
3. THE POS_Receipt_Preview SHALL display the same content that would be printed: organisation header, invoice number, date, customer name, line items, totals, payment history, balance due, and footer.
4. THE POS_Receipt_Preview SHALL visually indicate the paper width boundary with a subtle border or background to simulate the receipt paper edge.
5. THE POS_Receipt_Preview SHALL update dynamically when the paper width selection changes.
6. WHEN no default printer is configured, THE POS_Receipt_Preview SHALL default to 80mm paper width for the preview.

### Requirement 6: Receipt Footer Configuration

**User Story:** As a business owner, I want to customise the footer message on POS receipts, so that I can include a thank-you message or business-specific information.

#### Acceptance Criteria

1. THE Receipt_Template_Builder SHALL use the invoice's `notes_customer` field as the receipt footer message when present.
2. WHEN the invoice has no `notes_customer`, THE Receipt_Template_Builder SHALL use a default footer message of "Thank you for your business!".
3. THE POS_Receipt_Preview SHALL display the footer message at the bottom of the receipt preview.

### Requirement 7: POS Receipt Print from POS Screen

**User Story:** As a POS operator, I want to print a receipt after completing a payment in the POS screen, so that I can hand the customer a receipt immediately.

#### Acceptance Criteria

1. WHEN a payment is completed successfully in the POS screen, THE POS_Receipt_Printer SHALL be available to print a receipt for the completed transaction.
2. THE POS screen payment completion flow SHALL display a "Print Receipt" button after a successful payment.
3. WHEN the user clicks "Print Receipt" in the POS screen, THE POS_Receipt_Printer SHALL use the same default printer resolution and fallback logic as the invoice detail page POS print.
4. IF the POS receipt print fails in the POS screen, THEN THE Printer_Error_Modal SHALL be displayed with the same error handling and browser print fallback options.

### Requirement 8: Print Job Feedback

**User Story:** As an invoice operator, I want clear visual feedback during and after a POS print operation, so that I know whether the receipt was printed successfully.

#### Acceptance Criteria

1. WHILE the POS_Receipt_Printer is sending data to the printer driver, THE Invoice_Detail_Page SHALL display a loading spinner on the "POS Print" button.
2. WHEN the printer driver resolves successfully, THE Invoice_Detail_Page SHALL display a green success toast message "Receipt printed successfully" for 3 seconds.
3. IF the printer driver rejects with an error, THEN THE Printer_Error_Modal SHALL appear within 1 second of the error occurring.
4. WHEN the user prints via Browser_Print_Fallback, THE Invoice_Detail_Page SHALL display a neutral message "Receipt sent to browser print dialog".
