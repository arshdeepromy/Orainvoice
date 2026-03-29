# Implementation Plan: Service History Report

## Overview

Add PDF service history report generation and emailing for vehicles. The backend uses WeasyPrint + Jinja2 templates (matching existing invoice PDF patterns) with two new endpoints on the vehicles router. The frontend updates VehicleProfile.tsx to call these endpoints for print and email flows.

## Tasks

- [x] 1. Create the report service module
  - [x] 1.1 Create `app/modules/vehicles/report_service.py` with `generate_service_history_pdf()`
    - Implement `compute_date_cutoff(range_years)` helper to calculate the invoice filter date
    - Query organisation settings, vehicle details, linked customer, and invoices with line items from the database
    - Filter invoices by `issue_date >= cutoff_date` (or include all when `range_years=0`)
    - Sort invoices by `issue_date` descending
    - Build the report context dict (org, vehicle, customer, invoices, date_range_label, generated_date, has_invoices)
    - Render the Jinja2 template `service_history_report.html` and convert to PDF bytes via WeasyPrint
    - Return 404 if vehicle not found or not in the requesting user's organisation
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.2, 4.2, 4.4, 8.3, 8.5_

  - [x] 1.2 Write property test: date range filtering correctness (Property 6)
    - **Property 6: Date range filtering correctness**
    - Generate random invoices with random issue dates and random `range_years` values (0, 1, 2, 3)
    - Apply `compute_date_cutoff` and filter, assert all included invoices have `issue_date >= cutoff` and all excluded have `issue_date < cutoff`; when `range_years=0` all invoices are included
    - **Validates: Requirements 4.2, 4.4**

  - [x] 1.3 Implement `email_service_history_report()` in `report_service.py`
    - Call `generate_service_history_pdf()` to produce the PDF bytes
    - Build the email subject line containing the vehicle rego and "Service History Report"
    - Render the `service_history_email.html` template for the email body with org branding, vehicle details, and date range
    - Build the PDF attachment filename as `{rego}_service_history_{YYYY-MM-DD}.pdf`
    - Send via the existing `EmailProvider` SMTP failover chain with the PDF as an attachment
    - Validate recipient email format; raise 422 on invalid format
    - Return result dict with vehicle_id, recipient_email, pdf_size_bytes, status
    - _Requirements: 6.2, 7.1, 7.2, 7.3, 7.4, 8.2, 8.4_

  - [x] 1.4 Write property test: email content completeness (Property 7)
    - **Property 7: Email content completeness**
    - Generate random org settings, vehicle (rego, make, model, year), and date range
    - Build email subject and body, assert subject contains rego and "Service History Report", body contains rego, make, model, year, and date range label
    - **Validates: Requirements 7.1, 7.2, 7.3**

  - [x] 1.5 Write property test: PDF attachment filename format (Property 8)
    - **Property 8: PDF attachment filename format**
    - Generate random rego strings and dates, build filename, assert it matches `^.+_service_history_\d{4}-\d{2}-\d{2}\.pdf$`
    - **Validates: Requirements 7.4**

- [x] 2. Create PDF and email Jinja2 templates
  - [x] 2.1 Create `app/templates/pdf/service_history_report.html`
    - Cover page section with org branding (logo, name, address, phone, email, GST number), vehicle details (rego, make, model, year, VIN, odometer), customer details (name, email, phone), report date range, generation date
    - Table of contents section listing invoices with invoice number, issue date, status, total — ordered by issue date descending
    - Invoice page sections (one per invoice) with invoice number, issue date, status, odometer, customer name, line items table (description, qty, unit price, line total), subtotal, tax, grand total
    - Use CSS `@page` rules and `page-break-before` for section separation
    - Handle TOC overflow to subsequent pages when invoice count is large
    - Handle invoice page overflow with repeated header context on continuation pages
    - Empty state: cover page with "No service records found for the selected period" message when `has_invoices` is false
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 2.2 Write property test: report structure matches invoice count (Property 1)
    - **Property 1: Report structure matches invoice count**
    - Generate random lists of invoice dicts (0–20), render the template, assert exactly 1 cover page, 1 TOC section (when N > 0), and N invoice page sections
    - **Validates: Requirements 1.1**

  - [x] 2.3 Write property test: cover page contains all required fields (Property 2)
    - **Property 2: Cover page contains all required fields**
    - Generate random org/vehicle/customer data, render cover page, assert all non-null field values appear in the HTML output
    - **Validates: Requirements 1.2, 1.3, 1.4**

  - [x] 2.4 Write property test: TOC lists all invoices with required fields (Property 3)
    - **Property 3: TOC lists all invoices with required fields**
    - Generate random invoice sets, render TOC, assert all invoice numbers, dates, statuses, and totals appear in the HTML
    - **Validates: Requirements 2.1**

  - [x] 2.5 Write property test: TOC ordering (Property 4)
    - **Property 4: Table of contents ordering**
    - Generate random invoices with random dates, render TOC, extract invoice numbers in rendered order, verify descending date sort
    - **Validates: Requirements 2.2**

  - [x] 2.6 Write property test: invoice page completeness (Property 5)
    - **Property 5: Invoice page contains all required fields**
    - Generate random invoices with random line items, render invoice pages, assert all fields (invoice number, issue date, status, odometer, customer name, line item details, subtotal, tax, grand total) are present
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4**

  - [x] 2.7 Create `app/templates/pdf/service_history_email.html`
    - HTML email template with org logo, business name, and contact details
    - Brief message identifying the attached report, vehicle (rego, make, model, year), and date range covered
    - _Requirements: 7.1, 7.3_

- [x] 3. Add API endpoints to the vehicles router
  - [x] 3.1 Add `POST /vehicles/{id}/service-history-report` endpoint to `app/modules/vehicles/router.py`
    - Accept `range_years` in request body (default to 1)
    - Call `generate_service_history_pdf()` with org context from the authenticated user
    - Return PDF bytes as `application/pdf` with `Content-Disposition: inline; filename="{rego}_service_history_{date}.pdf"`
    - Handle 404 for missing/wrong-org vehicle
    - Require authentication via existing auth middleware
    - _Requirements: 5.1, 5.2, 8.1, 8.3, 8.5_

  - [x] 3.2 Add `POST /vehicles/{id}/service-history-report/email` endpoint to `app/modules/vehicles/router.py`
    - Accept `range_years` and `recipient_email` in request body
    - Call `email_service_history_report()` with org context
    - Return JSON response with vehicle_id, recipient_email, pdf_size_bytes, status
    - Handle 404 for missing/wrong-org vehicle, 422 for invalid email
    - Require authentication via existing auth middleware
    - _Requirements: 6.2, 8.2, 8.3, 8.4, 8.5_

  - [x] 3.3 Write property test: 404 for non-existent or wrong-org vehicle (Property 9)
    - **Property 9: 404 for non-existent or wrong-org vehicle**
    - Generate random UUIDs, call the report endpoint, assert 404 response
    - **Validates: Requirements 8.3**

  - [x] 3.4 Write property test: 422 for invalid email format (Property 10)
    - **Property 10: 422 for invalid email format**
    - Generate random non-email strings (missing @, missing domain, etc.), call the email endpoint, assert 422 response
    - **Validates: Requirements 8.4**

- [x] 4. Checkpoint — Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Update frontend VehicleProfile for print and email flows
  - [x] 5.1 Update print report flow in `frontend/src/pages/vehicles/VehicleProfile.tsx`
    - Replace the existing `printServiceReport()` function that builds inline HTML
    - POST to `/api/v1/vehicles/{id}/service-history-report` with the selected `range_years`
    - Receive PDF blob, create a blob URL via `URL.createObjectURL()`, open in new tab, trigger browser print dialog
    - Add loading state to the "Print Report" button during PDF generation
    - Add date range selector with options: last 1 year (default), last 2 years, last 3 years, all time
    - _Requirements: 4.1, 4.3, 5.1, 5.2, 5.3_

  - [x] 5.2 Update email report flow in `frontend/src/pages/vehicles/VehicleProfile.tsx`
    - Update `handleEmailServiceHistory()` to POST to `/api/v1/vehicles/{id}/service-history-report/email`
    - Email modal: date range selector, recipient email field defaulting to linked customer's email
    - Add manual email input field when no customer email exists
    - Show loading indicator and disable send button while email is sending
    - Display success notification on successful send
    - Display error message on failure
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [x] 5.3 Write frontend unit tests for report flows
    - Test print button shows loading state during PDF generation (Req 5.3)
    - Test email modal opens on button click (Req 6.1)
    - Test success notification after email sent (Req 6.6)
    - Test error message on email failure (Req 6.7)
    - Test send button disabled during sending (Req 6.5)
    - Test manual email input shown when no customer email (Req 6.4)
    - _Requirements: 5.3, 6.1, 6.4, 6.5, 6.6, 6.7_

- [x] 6. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- The backend uses Python (FastAPI, WeasyPrint, Hypothesis) and the frontend uses TypeScript (React)
- No database migrations are needed — all data is read from existing tables
