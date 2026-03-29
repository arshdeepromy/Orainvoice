# Requirements Document

## Introduction

The Vehicle Service History Report feature enables workshop staff to generate, print, and email a professional PDF report of a vehicle's service history. The report is generated from the existing Service History tab on the Vehicle Profile page and includes a branded cover page, table of contents, and individual invoice pages. Users can filter by date range and either print the report directly or email it as a PDF attachment to the linked customer.

## Glossary

- **Report_Generator**: The backend service responsible for building the PDF service history report from vehicle, invoice, and organisation data.
- **Cover_Page**: The first page of the PDF report containing the workshop's branding, vehicle details, and customer details.
- **Table_Of_Contents**: The second page of the PDF report listing all invoices included in the report with page references.
- **Invoice_Page**: A page in the PDF report displaying the full details of a single invoice.
- **Date_Range_Filter**: A UI control allowing the user to select a time period (last 1 year, last 2 years, last 3 years, or all time) to scope which invoices appear in the report.
- **Email_Service**: The existing notification module responsible for sending emails with attachments using the configured email provider.
- **Vehicle_Profile_Page**: The existing frontend page at `VehicleProfile.tsx` displaying vehicle information and service history.
- **Organisation_Settings**: The stored configuration for a workshop including logo_url, name, address, phone, email, and GST number.

## Requirements

### Requirement 1: Generate PDF Service History Report

**User Story:** As a workshop staff member, I want to generate a PDF service history report for a vehicle, so that I can provide a professional document summarising all services performed.

#### Acceptance Criteria

1. WHEN the user requests a service history report for a vehicle, THE Report_Generator SHALL produce a PDF document containing a Cover_Page, a Table_Of_Contents, and one Invoice_Page per invoice in the selected date range.
2. THE Cover_Page SHALL display the organisation's logo (from Organisation_Settings logo_url), business name, address, phone, email, and GST number.
3. THE Cover_Page SHALL display the vehicle's registration number, make, model, year, VIN, and last recorded odometer reading.
4. THE Cover_Page SHALL display the linked customer's full name, email, and phone number.
5. WHEN no invoices exist within the selected date range, THE Report_Generator SHALL produce a PDF containing only the Cover_Page with a message indicating no service records were found.

### Requirement 2: Table of Contents Page

**User Story:** As a workshop staff member, I want the report to include a table of contents, so that I can quickly locate a specific invoice within the document.

#### Acceptance Criteria

1. THE Table_Of_Contents SHALL list each invoice included in the report with its invoice number, issue date, status, and total amount.
2. THE Table_Of_Contents SHALL order invoices by issue date in descending order (most recent first).
3. WHEN the number of invoices exceeds the space available on a single page, THE Table_Of_Contents SHALL continue onto subsequent pages.

### Requirement 3: Invoice Pages

**User Story:** As a workshop staff member, I want each invoice to appear as its own page in the report, so that the document is well-organised and easy to read.

#### Acceptance Criteria

1. THE Invoice_Page SHALL display the invoice number, issue date, status, and vehicle odometer reading at the time of service.
2. THE Invoice_Page SHALL display all line items for the invoice including description, quantity, unit price, and line total.
3. THE Invoice_Page SHALL display the invoice subtotal, tax amount, and grand total.
4. THE Invoice_Page SHALL display the customer name associated with the invoice.
5. WHEN an invoice's line items exceed the space available on a single page, THE Invoice_Page SHALL continue onto subsequent pages while maintaining the invoice header context.

### Requirement 4: Date Range Filtering

**User Story:** As a workshop staff member, I want to filter the report by date range, so that I can generate reports covering a specific time period.

#### Acceptance Criteria

1. THE Date_Range_Filter SHALL provide the following options: last 1 year, last 2 years, last 3 years, and all time.
2. WHEN a date range is selected, THE Report_Generator SHALL include only invoices with an issue_date falling within the selected range.
3. THE Date_Range_Filter SHALL default to "last 1 year" when no selection has been made.
4. WHEN "all time" is selected, THE Report_Generator SHALL include all invoices associated with the vehicle regardless of issue date.

### Requirement 5: Print Report from Browser

**User Story:** As a workshop staff member, I want to print the service history report directly from the browser, so that I can produce a physical copy without downloading a file first.

#### Acceptance Criteria

1. WHEN the user clicks the "Print Report" button on the Service History tab, THE Vehicle_Profile_Page SHALL generate the PDF and open the browser's native print dialog with the report content.
2. THE printed output SHALL match the PDF layout including the Cover_Page, Table_Of_Contents, and Invoice_Pages.
3. WHILE the report is being generated, THE Vehicle_Profile_Page SHALL display a loading indicator on the "Print Report" button.

### Requirement 6: Email Report to Customer

**User Story:** As a workshop staff member, I want to email the service history report to the linked customer, so that I can share the vehicle's service records digitally.

#### Acceptance Criteria

1. WHEN the user clicks the "Email to Customer" button, THE Vehicle_Profile_Page SHALL display a modal allowing the user to select a date range and confirm the recipient email address.
2. WHEN the user confirms the email, THE Report_Generator SHALL generate the PDF for the selected date range and THE Email_Service SHALL send it as an attachment to the specified email address.
3. THE email recipient field SHALL default to the linked customer's email address.
4. IF the vehicle has no linked customer with an email address, THEN THE Vehicle_Profile_Page SHALL allow the user to manually enter a recipient email address.
5. WHILE the email is being sent, THE Vehicle_Profile_Page SHALL display a loading indicator and disable the send button.
6. WHEN the email is sent successfully, THE Vehicle_Profile_Page SHALL display a success notification.
7. IF the email fails to send, THEN THE Vehicle_Profile_Page SHALL display an error message describing the failure.

### Requirement 7: Professional Email Template

**User Story:** As a workshop owner, I want the email containing the report to use professional branding, so that communications reflect the workshop's identity.

#### Acceptance Criteria

1. THE Email_Service SHALL send the service history report email using an HTML template that includes the organisation's logo, business name, and contact details from Organisation_Settings.
2. THE email subject line SHALL include the vehicle's registration number and the text "Service History Report".
3. THE email body SHALL include a brief message identifying the attached report, the vehicle (registration, make, model, year), and the date range covered.
4. THE PDF attachment file name SHALL follow the format `{rego}_service_history_{date}.pdf` where `{rego}` is the vehicle registration and `{date}` is the generation date in YYYY-MM-DD format.

### Requirement 8: Backend Report Generation Endpoint

**User Story:** As a frontend developer, I want a backend API endpoint to generate the service history PDF, so that the frontend can request report generation and email sending.

#### Acceptance Criteria

1. THE Report_Generator SHALL expose a `POST /api/v1/vehicles/{id}/service-history-report` endpoint that accepts a date range parameter and returns the generated PDF as a binary response.
2. THE Report_Generator SHALL expose a `POST /api/v1/vehicles/{id}/service-history-report/email` endpoint that accepts a date range and recipient email, generates the PDF, and sends it via the Email_Service.
3. IF the specified vehicle does not exist or does not belong to the requesting user's organisation, THEN THE Report_Generator SHALL return a 404 error response.
4. IF the recipient email address is not a valid email format, THEN THE Report_Generator SHALL return a 422 validation error response.
5. THE Report_Generator SHALL require authentication and authorise the request against the user's organisation context.
