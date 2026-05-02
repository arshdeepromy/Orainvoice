# Requirements Document — Platform Feature Gaps

## Introduction

This document captures all requirements derived from three independent audits of the OraInvoice platform: a runtime bug and implementation audit (23 issues, CP-001 through CP-023), a deep architecture and feature coverage review (25 numbered gaps), and a feature gap audit covering the Customer Portal, Branch Transfers, and Staff Schedule modules. The requirements are organised into seven sections covering critical bug fixes, security hardening, token lifecycle, feature coverage, UX polish, branch transfer gaps, and staff schedule gaps.

## Glossary

- **Portal_Service**: The backend service layer (`app/modules/portal/service.py`) that handles all customer portal business logic including token resolution, data retrieval, and payment processing.
- **Portal_Router**: The FastAPI router (`app/modules/portal/router.py`) that exposes public portal HTTP endpoints.
- **Portal_Frontend**: The React frontend components under `frontend/src/pages/portal/` that render the customer portal UI.
- **Portal_Token**: A UUID stored on the `Customer` record that grants public access to the customer portal via the URL `/portal/{token}`.
- **Resolve_Token**: The `_resolve_token` function in Portal_Service that validates a portal token and returns the associated customer and organisation.
- **PortalAccessResponse**: The Pydantic schema returned by `GET /portal/{token}` containing customer info, org branding, and summary statistics.
- **PortalInfo**: The TypeScript interface in `PortalPage.tsx` that defines the expected shape of the portal landing page API response.
- **Stripe_Connect**: The Stripe integration that processes payments on behalf of connected organisation Stripe accounts.
- **Transfer_Service**: The backend service layer (`app/modules/franchise/service.py`) handling stock transfer business logic.
- **Transfer_Frontend**: The React component `StockTransfers.tsx` that renders the branch transfers UI.
- **Schedule_Service**: The backend service layer (`app/modules/scheduling_v2/service.py`) handling schedule entry CRUD and conflict detection.
- **Schedule_Frontend**: The React component `ScheduleCalendar.tsx` that renders the staff roster calendar.
- **Rate_Limiter**: The middleware (`app/middleware/rate_limit.py`) that enforces request rate limits per user, org, or IP.
- **Booking_Service**: The backend service (`app/modules/bookings_v2/service.py`) handling booking creation and confirmation.
- **Customer_View_Modal**: The frontend component `CustomerViewModal.tsx` that displays customer details to org staff.
- **Invoice_History**: The portal frontend component `InvoiceHistory.tsx` that renders the customer's invoice list.
- **Vehicle_History**: The portal frontend component `VehicleHistory.tsx` that renders the customer's vehicle service history.
- **Payment_Page**: The portal frontend component `PaymentPage.tsx` that handles invoice payment via Stripe.
- **Booking_Manager**: The portal frontend component `BookingManager.tsx` that renders the customer's bookings and booking form.

---

## Requirements

### Section 1: Customer Portal — Critical Bug Fixes

### Requirement 1: Portal Landing Page Response Shape Alignment (CP-001)

**User Story:** As a portal customer, I want the portal landing page to display my name, org branding, and account summary correctly, so that I can trust the portal and navigate it effectively.

#### Acceptance Criteria

1. WHEN a customer visits `GET /portal/{token}`, THE Portal_Frontend SHALL parse the nested response structure (`customer.first_name`, `customer.last_name`, `branding.org_name`, `branding.primary_colour`, `branding.logo_url`, `branding.powered_by`, `branding.language`) and render all fields correctly.
2. THE Portal_Frontend SHALL display the customer name as `customer.first_name + " " + customer.last_name` in the welcome header.
3. THE Portal_Frontend SHALL read `branding.org_name` and display it in the portal header.
4. THE Portal_Frontend SHALL apply `branding.primary_colour` (British spelling) to the portal colour theme.
5. THE Portal_Frontend SHALL read `invoice_count` from the response and display it in the "Total Invoices" summary card.
6. THE Portal_Service SHALL include a `total_paid` field in the PortalAccessResponse by computing the sum of `amount_paid` across the customer's non-draft, non-voided invoices.
7. THE Portal_Frontend SHALL display the `total_paid` value in the "Total Paid" summary card.
8. THE Portal_Frontend SHALL render the `branding.powered_by` footer using the nested `PoweredByFooter` component data.

### Requirement 2: Vehicle History Response Shape Fix (CP-002)

**User Story:** As a portal customer, I want to view my vehicle service history without errors, so that I can see past work done on my vehicles.

#### Acceptance Criteria

1. THE Vehicle_History component SHALL unpack the API response as `res.data?.vehicles ?? []` instead of treating `res.data` as a bare array.
2. THE Vehicle_History component SHALL map the backend field `service_history` (not `services`) when rendering service records for each vehicle.
3. THE Portal_Service SHALL include `wof_expiry` and `rego_expiry` fields in the `PortalVehicleItem` schema by sourcing them from the `GlobalVehicle` or `OrgVehicle` records where available.
4. IF the `wof_expiry` or `rego_expiry` fields are null, THEN THE Vehicle_History component SHALL omit the corresponding badge rather than rendering "undefined".

### Requirement 3: Portal Bookings SQL Fix (CP-003)

**User Story:** As a portal customer, I want to view my bookings list without the page crashing, so that I can see my upcoming and past appointments.

#### Acceptance Criteria

1. THE Portal_Service `get_portal_bookings` function SHALL query the bookings table using a valid column reference (either by joining on `customer_name` or by adding a `customer_id` foreign key to the bookings table) instead of referencing the non-existent `customer_id` column.
2. WHEN the bookings query executes, THE Portal_Service SHALL return a valid list of bookings without raising `asyncpg.UndefinedColumnError`.
3. IF the customer has no bookings, THEN THE Portal_Service SHALL return an empty list rather than an error.

### Requirement 4: Payment Page Implementation (CP-004)

**User Story:** As a portal customer, I want to pay my outstanding invoices online, so that I can settle my account without contacting the business.

#### Acceptance Criteria

1. WHEN a customer clicks "Pay Now" on an invoice, THE Payment_Page SHALL call `POST /portal/{token}/pay/{invoice_id}` with the invoice amount.
2. WHEN the backend returns a `payment_url`, THE Payment_Page SHALL redirect the customer's browser to the Stripe Checkout session URL.
3. IF the backend returns an error (invoice already paid, no Stripe Connect, zero balance), THEN THE Payment_Page SHALL display a descriptive error message to the customer.
4. THE Payment_Page SHALL replace the current static "Online payments coming soon" placeholder with the functional payment flow.

### Requirement 5: Payment Success Route (CP-005)

**User Story:** As a portal customer, I want to see a confirmation page after completing a Stripe payment, so that I know my payment was received.

#### Acceptance Criteria

1. THE Portal_Frontend SHALL register a route at `/portal/:token/payment-success` in `App.tsx`.
2. WHEN a customer is redirected to the payment success route after Stripe Checkout, THE Portal_Frontend SHALL display a "Payment received" confirmation message.
3. THE payment success page SHALL include a link to return to the invoices tab.

### Requirement 6: Invoice Line Items Summary (CP-006)

**User Story:** As a portal customer, I want to see a brief description of what each invoice covers, so that I can identify invoices at a glance.

#### Acceptance Criteria

1. THE Portal_Service SHALL compute a `line_items_summary` string for each invoice by concatenating the descriptions of the invoice's line items (truncated to a reasonable length).
2. THE Portal_Service SHALL include the `line_items_summary` field in the `PortalInvoiceItem` schema.
3. THE Invoice_History component SHALL render the `line_items_summary` text below each invoice row.
4. IF an invoice has no line items, THEN THE Portal_Service SHALL return an empty string for `line_items_summary`.

---

### Section 2: Customer Portal — Security Hardening

### Requirement 7: Enforce enable_portal Flag (CP-007)

**User Story:** As an org admin, I want the `enable_portal` toggle to actually control portal access, so that I can disable a customer's portal when needed.

#### Acceptance Criteria

1. THE Resolve_Token function SHALL include `Customer.enable_portal.is_(True)` in its query filter.
2. WHEN a customer has `enable_portal = false`, THE Resolve_Token function SHALL raise a ValueError with the message "Invalid or expired portal token" regardless of whether a valid portal_token exists.
3. WHEN an org admin sets `enable_portal` to false for a customer, THE Portal_Service SHALL deny all subsequent portal requests for that customer's token.

### Requirement 8: Remove acceptance_token from Quotes Response (CP-008)

**User Story:** As a platform operator, I want internal credentials excluded from public API responses, so that the attack surface is minimised.

#### Acceptance Criteria

1. THE Portal_Service `get_portal_quotes` function SHALL exclude the `acceptance_token` field from the `PortalQuoteItem` response.
2. THE `PortalQuoteItem` schema SHALL remove the `acceptance_token` field from its serialised output.
3. THE `accept_portal_quote` function SHALL continue to look up the acceptance_token server-side using the quote_id and customer ownership check, without requiring the token from the client.

### Requirement 9: Portal Rate Limiting (CP-009)

**User Story:** As a platform operator, I want portal endpoints to be rate-limited, so that token enumeration, data scraping, and denial-of-service attacks are mitigated.

#### Acceptance Criteria

1. THE Rate_Limiter SHALL apply a per-token rate limit to all portal endpoints (recommended: 60 requests per minute per token).
2. THE Rate_Limiter SHALL apply a per-IP rate limit to the portal token resolution endpoint `GET /portal/{token}` (recommended: 20 requests per minute per IP).
3. WHEN a rate limit is exceeded, THE Rate_Limiter SHALL return HTTP 429 with a `Retry-After` header.

### Requirement 10: Service-Layer Token Expiry Validation (CP-010)

**User Story:** As a platform operator, I want expired portal tokens to be rejected at the service layer, so that expiry enforcement does not depend solely on middleware that can fail silently.

#### Acceptance Criteria

1. THE Resolve_Token function SHALL check `Customer.portal_token_expires_at` and reject tokens where `portal_token_expires_at < now()`.
2. WHEN an expired token is used, THE Resolve_Token function SHALL raise a ValueError with the message "Invalid or expired portal token".
3. THE service-layer expiry check SHALL function as defence-in-depth independently of the middleware expiry check.

### Requirement 11: Stripe Connect Webhook for Portal Payments (CP-011)

**User Story:** As a portal customer, I want my invoice to be marked as paid after I complete a Stripe payment, so that my portal shows accurate balances.

#### Acceptance Criteria

1. THE Portal_Router SHALL register a Stripe Connect webhook endpoint that receives `checkout.session.completed` events from connected Stripe accounts.
2. WHEN a `checkout.session.completed` event is received for a portal payment, THE Portal_Service SHALL update the corresponding invoice's `status`, `amount_paid`, and `balance_due` fields.
3. IF the payment covers the full balance, THEN THE Portal_Service SHALL set the invoice status to `paid`.
4. IF the payment is partial, THEN THE Portal_Service SHALL set the invoice status to `partially_paid` and update `amount_paid` and `balance_due` accordingly.
5. THE webhook endpoint SHALL validate the event signature using the Stripe Connect webhook signing secret (separate from the platform webhook secret).

---

### Section 3: Customer Portal — Token Lifecycle & Delivery

### Requirement 12: Auto-Generate Portal Token on Enable

**User Story:** As an org staff member, I want a portal token to be generated automatically when I enable portal access for a customer, so that the customer can access the portal immediately without requiring a Global Admin.

#### Acceptance Criteria

1. WHEN an org staff member sets `enable_portal = true` for a customer and `portal_token` is NULL, THE Customer service SHALL auto-generate a new UUID portal token and set `portal_token_expires_at` based on the org's configured TTL.
2. THE token generation SHALL be accessible to `org_admin` and `salesperson` roles, not restricted to `global_admin`.
3. WHEN `enable_portal` is set to false, THE Customer service SHALL nullify the `portal_token` to prevent further access.

### Requirement 13: Send Portal Link to Customer

**User Story:** As an org staff member, I want to send the portal link to a customer via email, so that the customer receives their access link without manual copy-paste.

#### Acceptance Criteria

1. THE Customer_Router SHALL expose a `POST /api/v2/customers/{id}/send-portal-link` endpoint accessible to `org_admin` and `salesperson` roles.
2. WHEN the endpoint is called, THE system SHALL send an email to the customer's email address containing the portal URL.
3. IF the customer has no email address, THEN THE endpoint SHALL return a 400 error with a descriptive message.
4. IF the customer has `enable_portal = false` or `portal_token` is NULL, THEN THE endpoint SHALL return a 400 error indicating portal access is not enabled.

### Requirement 14: Copy Portal Link in Admin UI

**User Story:** As an org staff member, I want to see and copy the customer's portal link from the customer detail view, so that I can share it manually if needed.

#### Acceptance Criteria

1. THE Customer_View_Modal SHALL display the full portal URL when `enable_portal = true` and `portal_token` is not NULL.
2. THE Customer_View_Modal SHALL include a "Copy Link" button that copies the portal URL to the clipboard.
3. WHEN `enable_portal = false` or `portal_token` is NULL, THE Customer_View_Modal SHALL display "Portal Access: Disabled" without showing a link.

### Requirement 15: Per-Org Configurable Token TTL

**User Story:** As an org admin, I want to configure how long portal tokens remain valid for my organisation, so that I can control the security window appropriate for my business.

#### Acceptance Criteria

1. THE Organisation settings SHALL include a `portal_token_ttl_days` field (default: 90 days).
2. WHEN a portal token is generated or regenerated, THE system SHALL set `portal_token_expires_at` to `now() + portal_token_ttl_days` using the org's configured value.
3. THE Org Admin settings page SHALL include a field to configure `portal_token_ttl_days`.

---

### Section 4: Customer Portal — Feature Coverage

### Requirement 16: Job Status Visibility in Portal

**User Story:** As a portal customer, I want to see the status of my active and completed jobs, so that I know whether my vehicle is ready without calling the workshop.

#### Acceptance Criteria

1. THE Portal_Router SHALL expose a `GET /portal/{token}/jobs` endpoint that returns the customer's jobs.
2. THE endpoint SHALL return active jobs with their current status (pending, in_progress, completed, invoiced), assigned staff name, and estimated completion where available.
3. THE endpoint SHALL return completed jobs with a description of work done, linked invoice reference, and vehicle reference.
4. THE Portal_Frontend SHALL include a "Jobs" tab displaying the job list with status badges.

### Requirement 17: Claims Visibility in Portal

**User Story:** As a portal customer, I want to see the status of my warranty claims and returns, so that I can track their progress without contacting the business.

#### Acceptance Criteria

1. THE Portal_Router SHALL expose a `GET /portal/{token}/claims` endpoint that returns the customer's claims.
2. THE endpoint SHALL return each claim's type, current status (submitted, under_review, approved, rejected, resolved), and resolution details where available.
3. THE Portal_Frontend SHALL include a "Claims" tab displaying the claims list with status badges and a timeline of actions.

### Requirement 18: Invoice PDF Download from Portal

**User Story:** As a portal customer, I want to download PDF copies of my invoices, so that I can keep records for expense claims, insurance, or accounting.

#### Acceptance Criteria

1. THE Portal_Router SHALL expose a `GET /portal/{token}/invoices/{invoice_id}/pdf` endpoint that returns the invoice PDF.
2. THE endpoint SHALL validate that the invoice belongs to the customer associated with the portal token.
3. THE endpoint SHALL return the PDF with `Content-Type: application/pdf` and an appropriate `Content-Disposition` header.
4. THE Invoice_History component SHALL include a "Download PDF" button on each invoice row.

### Requirement 19: Compliance Documents in Portal

**User Story:** As a portal customer, I want to view and download compliance documents linked to my invoices, so that I can access safety certificates, inspection reports, and other compliance paperwork.

#### Acceptance Criteria

1. THE Portal_Router SHALL expose a `GET /portal/{token}/documents` endpoint that returns compliance documents linked to the customer's invoices.
2. THE endpoint SHALL return each document's type, description, linked invoice reference, and a download URL.
3. THE Portal_Frontend SHALL include a "Documents" tab or section displaying compliance documents with download links.

### Requirement 20: Partial Payment UI

**User Story:** As a portal customer, I want to pay a custom amount toward an invoice (such as a deposit), so that I can make partial payments when I cannot pay the full balance at once.

#### Acceptance Criteria

1. THE Payment_Page SHALL include an amount input field pre-filled with the invoice's `balance_due`.
2. THE customer SHALL be able to edit the amount to any value between $0.01 and the `balance_due`.
3. IF the customer enters an amount exceeding `balance_due`, THEN THE Payment_Page SHALL display a validation error.
4. THE Payment_Page SHALL send the customer-specified amount to `POST /portal/{token}/pay/{invoice_id}`.

### Requirement 21: Contact Details Self-Service Update

**User Story:** As a portal customer, I want to update my contact details (phone, email) from the portal, so that the business has my current information without me needing to call them.

#### Acceptance Criteria

1. THE Portal_Router SHALL expose a `PATCH /portal/{token}/profile` endpoint that accepts updated `phone` and `email` fields.
2. THE endpoint SHALL validate the email format and phone format before persisting changes.
3. THE Portal_Frontend SHALL include a "My Details" section or tab where the customer can view and edit their contact information.
4. WHEN the customer saves changes, THE Portal_Frontend SHALL display a success confirmation.

### Requirement 22: Booking Cancellation

**User Story:** As a portal customer, I want to cancel a booking I made through the portal, so that I can free up the time slot if my plans change.

#### Acceptance Criteria

1. THE Portal_Router SHALL expose a `PATCH /portal/{token}/bookings/{booking_id}/cancel` endpoint.
2. THE endpoint SHALL validate that the booking belongs to the customer and is in a cancellable status (pending or confirmed).
3. WHEN a booking is cancelled, THE Portal_Service SHALL set the booking status to `cancelled`.
4. THE Booking_Manager component SHALL display a "Cancel" button on bookings with a cancellable status.

### Requirement 23: Quote Acceptance Notification

**User Story:** As a business owner, I want to be notified when a customer accepts a quote via the portal, so that I can act on it promptly.

#### Acceptance Criteria

1. WHEN a customer accepts a quote via `POST /portal/{token}/quotes/{quote_id}/accept`, THE Portal_Service SHALL trigger a notification to the organisation.
2. THE notification SHALL be delivered via email to the org's primary contact email.
3. THE notification SHALL include the quote number, customer name, and accepted date.

### Requirement 24: Booking Confirmation on Portal Creation

**User Story:** As a portal customer, I want my booking to be confirmed (not left as pending indefinitely), so that I know my appointment is secured.

#### Acceptance Criteria

1. WHEN a booking is created via the portal, THE Portal_Service SHALL call `BookingService.send_confirmation()` after `create_booking()`.
2. THE booking status SHALL transition from `pending` to `confirmed` upon successful confirmation.
3. THE Portal_Service SHALL trigger a notification to the organisation about the new portal booking.

---

### Section 5: Customer Portal — UX Polish

### Requirement 25: Fix Mobile "Share Portal Link" URLs (CP-017)

**User Story:** As a mobile app user, I want the "Share Portal Link" button to generate correct portal URLs, so that customers receive working links to their portal.

#### Acceptance Criteria

1. THE mobile InvoiceDetailScreen SHALL generate portal URLs in the format `/portal/{customer_portal_token}` instead of `/portal/invoices/{invoice_id}`.
2. THE mobile QuoteDetailScreen SHALL generate portal URLs in the format `/portal/{customer_portal_token}` instead of `/portal/quotes/{quote_id}`.
3. THE backend invoice and quote detail API responses SHALL include the customer's `portal_token` (or a portal URL) so the mobile app can construct the correct link.
4. IF the customer has no portal token or portal access is disabled, THEN THE mobile app SHALL hide the "Share Portal Link" button.

### Requirement 26: Portal Endpoint Pagination

**User Story:** As a portal customer with a long history, I want invoice, quote, vehicle, asset, booking, and loyalty lists to load efficiently, so that the portal remains responsive.

#### Acceptance Criteria

1. THE Portal_Router SHALL accept `limit` and `offset` query parameters on all list endpoints (`/invoices`, `/quotes`, `/vehicles`, `/assets`, `/bookings`, `/loyalty`).
2. THE Portal_Service SHALL apply the `limit` and `offset` to database queries, defaulting to `limit=20, offset=0` when not specified.
3. THE Portal_Service SHALL return a `total` count alongside the list items so the frontend can render pagination controls.

### Requirement 27: Portal Internationalisation (i18n) (CP-020)

**User Story:** As a portal customer of a Māori-language or other non-English organisation, I want the portal to display in my organisation's configured language, so that the experience matches the business's branding.

#### Acceptance Criteria

1. THE Portal_Frontend SHALL read the `branding.language` field from the API response.
2. THE Portal_Frontend SHALL set the `lang` attribute on the portal's root HTML element to the configured language code.
3. THE Portal_Frontend SHALL pass the configured locale to all `Intl.DateTimeFormat` and `Intl.NumberFormat` calls instead of hardcoding `'en-NZ'`.
4. THE Portal_Frontend SHALL use the i18n translation keys (prefixed with `portal.*`) for all UI strings when a non-English locale is configured.

### Requirement 28: Booking Form Completeness (CP-021)

**User Story:** As a portal customer, I want to specify what service I need and add notes when booking an appointment, so that the business knows what to prepare for.

**STATUS: ⚠️ PARTIALLY IMPLEMENTED** — The `BookingManager.tsx` displays `service_type` and `notes` from existing bookings, but the booking creation form only sends `start_time`. The form needs `service_type` dropdown and `notes` textarea inputs that are included in the POST request body.

#### Acceptance Criteria

1. THE Booking_Manager component SHALL include a `service_type` dropdown or text input in the booking form.
2. THE Booking_Manager component SHALL include a `notes` textarea in the booking form.
3. WHEN the customer submits a booking, THE Booking_Manager SHALL send `service_type` and `notes` in the `POST /portal/{token}/bookings` request body.

### Requirement 29: Refund Status Display (CP-023)

**User Story:** As a portal customer, I want refunded and partially refunded invoices to display with clear labels and appropriate styling, so that I understand the status of my refunds.

#### Acceptance Criteria

1. THE Invoice_History `STATUS_CONFIG` SHALL include entries for `refunded` (label: "Refunded", colour: blue or teal) and `partially_refunded` (label: "Partially Refunded", colour: blue or teal).
2. THE Invoice_History component SHALL render refund statuses with user-friendly labels and colour-coded badges instead of raw lowercase strings.

### Requirement 30: Dead Code Cleanup — PortalLayout (CP-018)

**User Story:** As a developer, I want unused portal layout code removed or integrated, so that the codebase is clean and the hardcoded "WorkshopPro NZ" text does not leak in white-label deployments.

#### Acceptance Criteria

1. THE `PortalLayout.tsx` component SHALL either be removed from the codebase or integrated into the portal routing as the portal's layout wrapper.
2. IF `PortalLayout.tsx` is retained, THEN the hardcoded "Powered by WorkshopPro NZ" footer text SHALL be replaced with the configurable `PoweredByFooter` component.

---

### Section 6: Branch Transfers — Gap Fixes

### Requirement 31: Reject Transfer Button

**User Story:** As a branch manager, I want to reject a pending stock transfer from the UI, so that I can decline inappropriate or incorrect transfer requests.

#### Acceptance Criteria

1. THE Transfer_Frontend SHALL display a "Reject" button on transfers with status `pending`, alongside the existing "Approve" button.
2. WHEN the "Reject" button is clicked, THE Transfer_Frontend SHALL call `PUT /api/v2/stock-transfers/{id}/reject` (new endpoint).
3. THE Transfer_Router SHALL expose a `PUT /api/v2/stock-transfers/{id}/reject` endpoint that calls `Transfer_Service.reject_transfer`.
4. WHEN a transfer is rejected, THE Transfer_Service SHALL set the transfer status to `rejected`.

### Requirement 32: Product Search Dropdown

**User Story:** As a branch staff member creating a transfer, I want to search and select products from a dropdown, so that I do not need to know or type product UUIDs.

#### Acceptance Criteria

1. THE Transfer_Frontend create form SHALL replace the raw "Product ID" text input with a searchable product dropdown.
2. THE product dropdown SHALL query `GET /api/v2/products` (or equivalent) with a search term and display matching product names.
3. WHEN a product is selected, THE Transfer_Frontend SHALL populate the `product_id` field with the selected product's UUID.

### Requirement 33: Receive Confirmation Step

**User Story:** As a destination branch manager, I want to confirm receipt of a transferred stock shipment, so that inventory is only updated when goods physically arrive.

#### Acceptance Criteria

1. THE Transfer_Router SHALL expose a `PUT /api/v2/stock-transfers/{id}/receive` endpoint.
2. WHEN the receive endpoint is called, THE Transfer_Service SHALL set the transfer status to `received`.
3. THE Transfer_Frontend SHALL display a "Receive" button on transfers with status `executed` when the current user is at the destination location.
4. THE stock movement (inventory deduction at source and addition at destination) SHALL occur at the `execute` step, with the `receive` step serving as an acknowledgement.

### Requirement 34: Transfer Detail View

**User Story:** As a branch manager, I want to click on a transfer to see its full details and audit trail, so that I can review the history of approvals and actions.

#### Acceptance Criteria

1. THE Transfer_Frontend SHALL navigate to a detail view when a transfer row is clicked.
2. THE detail view SHALL display all transfer fields: source location, destination location, product, quantity, status, notes, requested by, approved by, created date, and completed date.
3. THE detail view SHALL display action buttons (Approve, Reject, Execute, Receive) appropriate to the transfer's current status.

### Requirement 35: Sidebar Route Fix

**User Story:** As a user, I want the "Branch Transfers" sidebar link to navigate to the correct page, so that I do not encounter a 404 or wrong page.

**STATUS: ✅ ALREADY IMPLEMENTED** — `/branch-transfers` route exists in `App.tsx` and maps to `BranchStockTransfers` (imported from `@/pages/inventory/StockTransfers`). The sidebar entry in `OrgLayout.tsx` links to `/branch-transfers`. No action needed.

#### Acceptance Criteria

1. THE sidebar entry for "Branch Transfers" SHALL link to the same route path where the `StockTransfers` component is mounted.
2. WHEN a user clicks "Branch Transfers" in the sidebar, THE application SHALL render the StockTransfers page without a 404 error.

---

### Section 7: Staff Schedule — Gap Fixes

### Requirement 36: Create and Edit Schedule Entry UI

**User Story:** As a manager, I want to create and edit schedule entries directly from the calendar, so that I can manage staff rosters without relying on programmatic entry creation.

#### Acceptance Criteria

1. THE Schedule_Frontend SHALL include a "New Entry" button that opens a form (modal or slide-over) for creating a schedule entry.
2. THE create form SHALL include fields for: staff member (dropdown), title, entry type (job, booking, break, other), start time, end time, and notes.
3. WHEN the form is submitted, THE Schedule_Frontend SHALL call `POST /api/v2/schedule` with the entry data.
4. THE Schedule_Frontend SHALL allow clicking an existing entry card to open an edit form pre-populated with the entry's current data.
5. WHEN the edit form is submitted, THE Schedule_Frontend SHALL call `PUT /api/v2/schedule/{id}` with the updated data.
6. IF the Schedule_Service detects a conflict with another entry for the same staff member, THEN THE Schedule_Frontend SHALL display a warning to the user (the entry is still created, but the conflict is flagged).

### Requirement 37: Clarify Dual Sidebar Entries

**User Story:** As a user, I want a single clear entry point for the schedule, so that I am not confused by two sidebar links that appear to go to the same page.

#### Acceptance Criteria

1. THE sidebar SHALL have a single "Schedule" entry that navigates to the schedule calendar, OR the two entries ("Schedule" and "Staff Schedule") SHALL be differentiated with distinct functionality (e.g., "Schedule" shows the current user's own schedule, "Staff Schedule" shows the admin-level full roster view).
2. IF both entries are retained, THEN each SHALL have a distinct route and distinct page content.
3. THE `/staff-schedule` route SHALL either be removed or mapped to a component that provides differentiated functionality from `/schedule`.

### Requirement 38: Drag-and-Drop Rescheduling

**User Story:** As a manager, I want to drag schedule entries to different time slots or staff columns, so that I can quickly reschedule assignments without opening an edit form.

#### Acceptance Criteria

1. THE Schedule_Frontend SHALL support dragging an entry card from one time slot to another within the day view.
2. THE Schedule_Frontend SHALL support dragging an entry card from one staff column to another to reassign it.
3. WHEN an entry is dropped in a new position, THE Schedule_Frontend SHALL call `PUT /api/v2/schedule/{id}/reschedule` with the new `start_time` and `end_time`.
4. IF the reschedule creates a conflict, THEN THE Schedule_Frontend SHALL display a warning but still complete the move.

---

### Section 8: Portal — Advanced Security Hardening

### Requirement 39: Portal Audit Log for Customer Actions

**User Story:** As an org admin, I want all customer actions on the portal (quote acceptance, booking creation, payment initiation) to be logged with timestamps and IP addresses, so that I have an audit trail for dispute resolution.

#### Acceptance Criteria

1. WHEN a customer accepts a quote via the portal, THE Portal_Service SHALL write an audit log entry with action `portal.quote_accepted`, the customer ID, quote ID, IP address, and timestamp.
2. WHEN a customer creates a booking via the portal, THE Portal_Service SHALL write an audit log entry with action `portal.booking_created`.
3. WHEN a customer initiates a payment via the portal, THE Portal_Service SHALL write an audit log entry with action `portal.payment_initiated`.
4. WHEN a customer updates their profile via the portal, THE Portal_Service SHALL write an audit log entry with action `portal.profile_updated`.
5. ALL portal audit log entries SHALL include the customer's IP address extracted from the request.

### Requirement 40: Portal Session and Logout Mechanism

**User Story:** As a portal customer using a shared device, I want to be able to log out of the portal, so that the next person using the device cannot access my data.

#### Acceptance Criteria

1. THE Portal_Frontend SHALL display a "Sign Out" button in the portal header.
2. WHEN the customer clicks "Sign Out", THE Portal_Frontend SHALL clear any local state and redirect to a "You have been signed out" page.
3. THE portal SHALL implement a session timeout of 4 hours of inactivity — after 4 hours without a request, subsequent requests SHALL require re-accessing the portal via the token URL.
4. THE session mechanism SHALL use an HttpOnly cookie (not the token in the URL) for ongoing session validation after initial token access.

### Requirement 41: CSRF Protection on Portal POST Endpoints

**User Story:** As a platform operator, I want portal POST endpoints protected against cross-site request forgery, so that malicious pages cannot trigger actions on behalf of a customer.

#### Acceptance Criteria

1. THE Portal_Router SHALL implement CSRF protection on all state-changing endpoints (POST, PATCH, PUT, DELETE).
2. THE CSRF token SHALL be issued when the portal session is established and validated on each state-changing request.
3. IF a request fails CSRF validation, THE Portal_Router SHALL return HTTP 403 with a descriptive error message.

### Requirement 42: Strengthen Portal Token Format

**User Story:** As a platform operator, I want portal tokens to use a cryptographically strong format, so that the token space is maximised against brute-force enumeration.

#### Acceptance Criteria

1. WHEN a new portal token is generated, THE system SHALL use `secrets.token_urlsafe(32)` (256 bits) instead of `uuid.uuid4()` (122 bits).
2. THE `portal_token` column type SHALL remain `VARCHAR` to accommodate the longer token format.
3. EXISTING UUID-format tokens SHALL continue to work until they expire — the change applies only to newly generated tokens.

### Requirement 43: Mitigate Portal Token URL Exposure

**User Story:** As a platform operator, I want to reduce the risk of portal token leakage via browser history, server logs, and Referrer headers.

#### Acceptance Criteria

1. THE Portal_Frontend SHALL set a `Referrer-Policy: no-referrer` meta tag on all portal pages to prevent the token URL from leaking via Referrer headers when the customer clicks external links.
2. THE Portal_Frontend SHALL use `history.replaceState` after initial token validation to remove the token from the browser's address bar, replacing it with a clean `/portal/dashboard` URL.
3. THE Portal_Router SHALL add `Cache-Control: no-store` and `Pragma: no-cache` headers to all portal responses to prevent caching of token-bearing URLs.

---

### Section 9: Portal — Compliance and Privacy

### Requirement 44: Cookie Consent on Portal

**User Story:** As a portal customer, I want to be informed about cookie usage and give consent, so that the portal complies with privacy regulations.

#### Acceptance Criteria

1. THE Portal_Frontend SHALL display a cookie consent banner on first visit to the portal.
2. THE banner SHALL explain what cookies are used (session, analytics if any) and provide Accept/Decline options.
3. WHEN the customer accepts, THE Portal_Frontend SHALL store the consent preference and dismiss the banner.
4. WHEN the customer declines, THE Portal_Frontend SHALL function with only essential cookies (session).

### Requirement 45: Data Subject Access Request (DSAR) from Portal

**User Story:** As a portal customer, I want to request an export of all my data or request deletion of my account, so that I can exercise my privacy rights.

#### Acceptance Criteria

1. THE Portal_Frontend SHALL include a "My Privacy" section accessible from the portal.
2. THE "My Privacy" section SHALL provide a "Request Data Export" button that triggers a DSAR.
3. THE Portal_Router SHALL expose a `POST /portal/{token}/dsar` endpoint that creates a DSAR record for the org admin to process.
4. THE org admin SHALL receive a notification when a DSAR is submitted.
5. THE "My Privacy" section SHALL provide a "Request Account Deletion" button that creates a deletion request for the org admin to review.

---

### Section 10: Portal — Operational Features for Org Admins

### Requirement 46: Global Portal Enable/Disable per Organisation

**User Story:** As an org admin, I want to enable or disable the customer portal for my entire organisation, so that I can control whether any customer can access the portal.

#### Acceptance Criteria

1. THE Organisation settings SHALL include a `portal_enabled` boolean field (default: true).
2. WHEN `portal_enabled` is false, ALL portal endpoints for that organisation SHALL return HTTP 403 with the message "Customer portal is not available for this organisation."
3. THE Org Admin settings page SHALL include a toggle to enable/disable the portal.

### Requirement 47: Portal Analytics for Org Admins

**User Story:** As an org admin, I want to see portal usage statistics, so that I can understand how customers are engaging with the portal.

#### Acceptance Criteria

1. THE Portal_Service SHALL track portal access events (page views, tab switches) in a lightweight analytics table or counter.
2. THE Org Admin dashboard or settings page SHALL display portal analytics: total visits (last 30 days), unique customers who accessed the portal, invoices viewed, quotes accepted via portal, bookings created via portal, payments initiated via portal.
3. THE analytics SHALL be scoped to the organisation.

### Requirement 48: Portal Access Log

**User Story:** As an org admin, I want to see when each customer last accessed the portal, so that I can identify inactive portal users and follow up.

#### Acceptance Criteria

1. THE Portal_Service SHALL update a `last_portal_access_at` timestamp on the customer record each time the portal is accessed via `GET /portal/{token}`.
2. THE Customer list and detail views SHALL display the `last_portal_access_at` field.
3. THE Customer list SHALL be sortable/filterable by `last_portal_access_at`.

---

### Section 11: Portal — Additional Feature Coverage

### Requirement 49: Projects Visibility in Portal

**User Story:** As a portal customer of a trade/construction business, I want to see the status of my ongoing projects, so that I can track multi-stage work progress.

#### Acceptance Criteria

1. THE Portal_Router SHALL expose a `GET /portal/{token}/projects` endpoint that returns the customer's projects.
2. THE endpoint SHALL return each project's name, status, description, and linked invoices/jobs.
3. THE Portal_Frontend SHALL include a "Projects" tab displaying the project list with status badges.

### Requirement 50: Recurring Invoice Schedules Visibility

**User Story:** As a fleet customer on a recurring contract, I want to see my upcoming billing schedule, so that I can plan for future charges.

#### Acceptance Criteria

1. THE Portal_Router SHALL expose a `GET /portal/{token}/recurring` endpoint that returns the customer's recurring invoice schedules.
2. THE endpoint SHALL return each schedule's frequency, next run date, amount, and status.
3. THE Portal_Frontend SHALL include a "Recurring" section or tab displaying upcoming scheduled charges.

### Requirement 51: Progress Claims Visibility in Portal

**User Story:** As a construction client, I want to review and track progress claims online, so that I can monitor project billing milestones.

#### Acceptance Criteria

1. THE Portal_Router SHALL expose a `GET /portal/{token}/progress-claims` endpoint that returns progress claims linked to the customer's projects.
2. THE endpoint SHALL return each claim's number, status, amount, and completion percentage.
3. THE Portal_Frontend SHALL include a "Progress Claims" section within the Projects tab or as a standalone tab.

### Requirement 52: Self-Service Token Recovery ("Forgot My Link")

**User Story:** As a portal customer who has lost their portal link, I want to recover access by entering my email, so that I do not need to contact the business.

#### Acceptance Criteria

1. THE Portal_Frontend SHALL include a "Forgot your link?" option on the portal landing page.
2. WHEN the customer enters their email, THE system SHALL look up all portal-enabled customers with that email and send a new portal link to the email address.
3. IF no portal-enabled customer exists with that email, THE system SHALL display a generic "If an account exists, a link has been sent" message (to prevent email enumeration).
4. THE Portal_Router SHALL expose a `POST /portal/recover` endpoint that handles the email lookup and link delivery.

---

### Section 12: Branch Transfers — Additional Gaps

### Requirement 53: Transfer History and Audit Trail

**User Story:** As a branch manager, I want to see a full audit trail for each transfer, so that I can track who requested, approved, rejected, or executed it and when.

#### Acceptance Criteria

1. THE Transfer_Service SHALL log each status transition (created, approved, rejected, executed, received) with the user ID, timestamp, and optional notes.
2. THE Transfer detail view SHALL display the audit trail as a timeline of actions.
3. THE audit trail data SHALL be stored in a `transfer_actions` table or as JSONB on the transfer record.

### Requirement 54: Partial Transfer Support

**User Story:** As a destination branch manager, I want to receive a partial quantity from a transfer (e.g., ordered 100, received 95), so that discrepancies are tracked.

#### Acceptance Criteria

1. THE `PUT /api/v2/stock-transfers/{id}/receive` endpoint SHALL accept an optional `received_quantity` parameter.
2. IF `received_quantity` is less than the transfer quantity, THE Transfer_Service SHALL record the discrepancy and set the transfer status to `partially_received`.
3. IF `received_quantity` equals the transfer quantity (or is not specified), THE Transfer_Service SHALL set the status to `received`.

### Requirement 55: Transfer Event Notifications

**User Story:** As a branch manager, I want to be notified when a transfer is created, approved, or executed that involves my location, so that I can act on it promptly.

#### Acceptance Criteria

1. WHEN a transfer is created, THE system SHALL send a notification to the destination location's manager.
2. WHEN a transfer is approved or executed, THE system SHALL send a notification to both source and destination location managers.
3. THE notifications SHALL be delivered via the existing in-app notification system and optionally via email.

---

### Section 13: Staff Schedule — Additional Gaps

### Requirement 56: Recurring Schedule / Shift Patterns

**User Story:** As a manager, I want to define recurring shifts (e.g., "Mon–Fri 8am–5pm every week"), so that I do not need to create individual entries for each day.

#### Acceptance Criteria

1. THE Schedule_Frontend create form SHALL include a "Repeat" option with frequency choices: none, daily, weekly, fortnightly.
2. WHEN a recurring entry is created, THE Schedule_Service SHALL generate individual schedule entries for the specified recurrence period (up to 4 weeks ahead).
3. THE Schedule_Frontend SHALL visually distinguish recurring entries from one-off entries.

### Requirement 57: Shift Templates

**User Story:** As a manager, I want to save and apply shift templates (e.g., "Morning shift 7am–3pm", "Evening shift 3pm–11pm"), so that I can quickly assign common shifts.

#### Acceptance Criteria

1. THE Schedule_Frontend SHALL include a "Templates" section where managers can create, name, and save shift templates with predefined start/end times and entry type.
2. WHEN creating a new schedule entry, THE Schedule_Frontend SHALL offer a "Use Template" dropdown that pre-fills the form with the selected template's values.
3. THE Schedule_Router SHALL expose CRUD endpoints for shift templates: `GET /api/v2/schedule/templates`, `POST /api/v2/schedule/templates`, `DELETE /api/v2/schedule/templates/{id}`.

### Requirement 58: Leave and Absence Tracking

**User Story:** As a manager, I want to mark staff as on leave, sick, or unavailable for a date range, so that the schedule reflects actual availability.

#### Acceptance Criteria

1. THE Schedule_Frontend SHALL include an "Add Leave" action that creates a schedule entry with `entry_type = "leave"` spanning the leave period.
2. THE Schedule_Service SHALL treat leave entries as blocking — conflict detection SHALL flag any overlapping entries with a leave entry.
3. THE Schedule_Frontend SHALL render leave entries with a distinct visual style (e.g., grey strikethrough or hatched pattern) across the affected time slots.

### Requirement 59: Schedule Print and Export

**User Story:** As a manager, I want to print the weekly roster or export it as PDF/CSV, so that I can share it with staff who do not use the app.

#### Acceptance Criteria

1. THE Schedule_Frontend SHALL include a "Print" button that opens the browser's print dialog with a print-optimised layout of the current view (day or week).
2. THE Schedule_Frontend SHALL include an "Export CSV" button that downloads the current view's entries as a CSV file with columns: staff name, date, start time, end time, entry type, title, notes.

### Requirement 60: Mobile-Optimised Schedule View

**User Story:** As a staff member on a mobile device, I want to view my schedule in a mobile-friendly layout, so that I can check my roster on the go.

#### Acceptance Criteria

1. THE Schedule_Frontend SHALL detect viewport width and switch to a single-column layout on screens narrower than 768px.
2. THE mobile layout SHALL show one staff member at a time (the current user by default) with a day view showing time slots vertically.
3. THE mobile layout SHALL include a staff switcher dropdown for managers to view other staff members' schedules.

---

### Section 14: Portal — Loyalty Balance UX

### Requirement 61: Loyalty Balance Empty State

**User Story:** As a portal customer whose organisation has not configured loyalty, I want to see a clear explanation instead of "0 points", so that I understand why the loyalty tab appears empty.

#### Acceptance Criteria

1. IF the organisation has no loyalty programme configured, THEN THE Loyalty tab SHALL display "This business does not have a loyalty programme" instead of showing 0 points.
2. IF the organisation has loyalty configured but the customer has 0 points, THEN THE Loyalty tab SHALL display "You have 0 points" with an explanation of how to earn points.

---

### Section 15: Portal — Branding Application

### Requirement 62: Apply Organisation Branding to Portal Theme

**User Story:** As a portal customer, I want the portal to reflect my workshop's branding (logo, colours), so that the experience feels connected to the business I know.

#### Acceptance Criteria

1. THE Portal_Frontend SHALL apply `branding.primary_colour` as the accent colour for buttons, links, and active tab indicators.
2. THE Portal_Frontend SHALL display `branding.logo_url` in the portal header when available.
3. THE Portal_Frontend SHALL use `branding.secondary_colour` for secondary UI elements when available.
4. IF branding colours are not set, THE Portal_Frontend SHALL fall back to the default blue (#2563eb) theme.

---

### Section 16: Portal — SMS Conversation History

### Requirement 63: SMS Conversation History in Portal

**User Story:** As a portal customer, I want to review my SMS conversation history with the business, so that I can reference what was agreed or discussed.

#### Acceptance Criteria

1. THE Portal_Router SHALL expose a `GET /portal/{token}/messages` endpoint that returns the customer's SMS conversation history.
2. THE endpoint SHALL return messages with direction (inbound/outbound), content, and timestamp.
3. THE Portal_Frontend SHALL include a "Messages" tab displaying the conversation in a chat-style layout.
4. THE messages SHALL be ordered chronologically with the most recent at the bottom.
