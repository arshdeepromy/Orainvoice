# Implementation Plan: Platform Feature Gaps

## Overview

This plan addresses 38 requirements across 7 sections: portal critical bug fixes, security hardening, token lifecycle, feature coverage, UX polish, branch transfer gaps, and staff schedule gaps. All changes are modifications to existing modules — Python/FastAPI backend and React/TypeScript frontend. Tasks are ordered by priority: critical bug fixes first, then security, then additive features.

## Tasks

- [x] 1. Portal Critical Bug Fixes (Req 1-6)
  - [x] 1.1 Fix PortalPage response shape alignment
    - Update `PortalInfo` interface in `frontend/src/pages/portal/PortalPage.tsx` to match `PortalAccessResponse` nested structure: `customer.first_name`, `customer.last_name`, `branding.org_name`, `branding.primary_colour`, `branding.logo_url`, `branding.powered_by`, `branding.language`
    - Update all render references: `info.customer_name` → `info.customer.first_name + ' ' + info.customer.last_name`, `info.org_name` → `info.branding.org_name`, `info.primary_color` → `info.branding.primary_colour`, `info.total_invoices` → `info.invoice_count`, `info.powered_by` → `info.branding.powered_by`
    - Add `total_paid: Decimal = Decimal("0")` field to `PortalAccessResponse` in `app/modules/portal/schemas.py`
    - Add `sa_func.coalesce(sa_func.sum(Invoice.amount_paid), 0)` to the aggregate query in `get_portal_access` in `app/modules/portal/service.py`
    - Pass `info.branding.primary_colour ?? '#2563eb'` to child components as `primaryColor`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

  - [x] 1.2 Fix VehicleHistory response parsing
    - Change API response unpacking in `frontend/src/pages/portal/VehicleHistory.tsx`: `res.data` → `res.data?.vehicles ?? []`
    - Rename `PortalVehicle.services` field to `service_history` to match `PortalVehicleItem` backend schema
    - Map service record fields: `invoice_number`, `date`, `description`, `total` from `PortalServiceRecord`
    - Add `wof_expiry: date | None = None` and `rego_expiry: date | None = None` to `PortalVehicleItem` in `app/modules/portal/schemas.py`
    - Source `wof_expiry` and `rego_expiry` from `GlobalVehicle` or `OrgVehicle` in `get_portal_vehicles` in `app/modules/portal/service.py`
    - Guard WOF/Rego badge rendering for null values
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 1.3 Fix portal bookings SQL
    - Create Alembic migration to add `customer_id UUID REFERENCES customers(id)` column to bookings table with index `ix_bookings_customer_id`
    - Update `get_portal_bookings` in `app/modules/portal/service.py` to query `WHERE customer_id = :cid` instead of the current raw SQL
    - Update `create_portal_booking` in `app/modules/portal/service.py` to pass `customer_id` to `BookingService.create_booking`
    - _Requirements: 3.1, 3.2, 3.3_

  - [x] 1.4 Implement PaymentPage with Stripe Checkout redirect
    - Replace static "coming soon" placeholder in `frontend/src/pages/portal/PaymentPage.tsx` with functional payment flow
    - Add amount input field pre-filled with `invoice.balance_due` (supports partial payments per Req 20)
    - On "Pay Now" click: `POST /portal/{token}/pay/{invoice.id}` with `{ amount }`, then `window.location.href = res.data?.payment_url`
    - Display error message from backend on failure (invoice already paid, no Stripe Connect, zero balance)
    - Add loading/submitting state to prevent double-clicks
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 20.1, 20.2, 20.3, 20.4_

  - [x] 1.5 Add payment-success route and component
    - Create `frontend/src/pages/portal/PaymentSuccess.tsx` — confirmation page with "Payment received" message and link back to invoices tab
    - Add route `/portal/:token/payment-success` in `frontend/src/App.tsx` before the existing `/portal/:token` route
    - Read `token` from URL params for the back link
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 1.6 Add line_items_summary to invoice responses
    - Add `line_items_summary: str = ""` field to `PortalInvoiceItem` in `app/modules/portal/schemas.py`
    - Compute summary in `get_portal_invoices` in `app/modules/portal/service.py`: join line item descriptions, truncate to 120 chars with "…"
    - Verify `InvoiceHistory.tsx` already renders `inv.line_items_summary` (it does — the interface already has the field)
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x] 1.7 Write property tests for portal response shapes
    - **Property 1: Portal response field extraction preserves all data**
    - **Property 2: total_paid equals sum of amount_paid across non-draft non-voided invoices**
    - **Property 4: Line items summary is correctly computed**
    - **Validates: Requirements 1.1-1.7, 6.1, 6.4**

- [x] 2. Checkpoint — Verify portal critical bug fixes
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Portal Security Hardening (Req 7-11)
  - [x] 3.1 Enforce enable_portal flag in _resolve_token
    - Add `.where(Customer.enable_portal.is_(True))` to the query in `_resolve_token` in `app/modules/portal/service.py`
    - Customers with `enable_portal = false` will get "Invalid or expired portal token" error
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 3.2 Remove acceptance_token from quotes response
    - Remove `acceptance_token: str | None = None` field from `PortalQuoteItem` in `app/modules/portal/schemas.py`
    - Update `get_portal_quotes` in `app/modules/portal/service.py` to stop selecting `acceptance_token` from the raw SQL query
    - Verify `accept_portal_quote` still works — it looks up `acceptance_token` server-side using `quote_id` + customer ownership
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 3.3 Add portal rate limiting tiers
    - Add portal per-token rate limit (60 req/min) in `app/middleware/rate_limit.py` `_apply_rate_limits` for paths starting with `/api/v1/portal/` or `/api/v2/portal/`
    - Extract token segment from path and use key `rl:portal:token:{token_segment}`
    - Add per-IP rate limit (20 req/min) on the token resolution endpoint (`GET /portal/{token}` — path with exactly 5 segments)
    - Return HTTP 429 with `Retry-After` header when limits exceeded
    - _Requirements: 9.1, 9.2, 9.3_

  - [x] 3.4 Add service-layer token expiry check
    - In `_resolve_token` in `app/modules/portal/service.py`, after fetching customer, check `customer.portal_token_expires_at`
    - If `portal_token_expires_at` is not None and is in the past, raise `ValueError("Invalid or expired portal token")`
    - This is defence-in-depth alongside the middleware check
    - _Requirements: 10.1, 10.2, 10.3_

  - [x] 3.5 Implement Stripe Connect webhook endpoint
    - Add `POST /portal/stripe-webhook` endpoint in `app/modules/portal/router.py`
    - Validate event signature using `stripe_connect_webhook_secret` (add to `app/config.py` settings)
    - Handle `checkout.session.completed` events: extract `invoice_id` from session metadata, update invoice `amount_paid`, `balance_due`, `status`
    - Set status to `paid` if `balance_due == 0`, `partially_paid` if `balance_due > 0`
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

  - [x] 3.6 Write property tests for portal security
    - **Property 5: enable_portal=false blocks token resolution**
    - **Property 6: acceptance_token is never present in portal quote responses**
    - **Property 9: Expired tokens are rejected at service layer**
    - **Property 10: Webhook payment updates invoice correctly**
    - **Validates: Requirements 7.1-7.3, 8.1-8.2, 10.1-10.2, 11.2-11.4**

  - [x] 3.7 Write property tests for portal rate limiting
    - **Property 7: Portal per-token rate limit enforces threshold**
    - **Property 8: Portal per-IP rate limit on token resolution**
    - **Validates: Requirements 9.1, 9.2, 9.3**

- [x] 4. Checkpoint — Verify portal security hardening
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Portal Token Lifecycle (Req 12-15)
  - [x] 5.1 Auto-generate token on enable_portal toggle
    - In the customer update flow (likely `app/modules/customers/service.py`), when `enable_portal` transitions to `True` and `portal_token` is NULL: generate `portal_token = uuid.uuid4()` and set `portal_token_expires_at = now() + timedelta(days=org.settings.get("portal_token_ttl_days", 90))`
    - When `enable_portal` transitions to `False`: set `portal_token = None` to revoke access
    - Ensure accessible to `org_admin` and `salesperson` roles
    - _Requirements: 12.1, 12.2, 12.3_

  - [x] 5.2 Add send-portal-link endpoint
    - Add `POST /api/v2/customers/{id}/send-portal-link` endpoint in `app/modules/customers/router.py`
    - Validate: customer has `enable_portal == True`, `portal_token is not None`, and has an email address
    - Send email with portal URL `{frontend_base_url}/portal/{portal_token}`
    - Restrict to `org_admin` and `salesperson` roles
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

  - [x] 5.3 Add copy portal link UI in CustomerViewModal
    - In `frontend/src/` find `CustomerViewModal.tsx` and update the portal access section
    - When `enable_portal == true` and `portal_token` exists: show full URL with "Copy Link" button (clipboard API) and "Send Link" button (calls send-portal-link endpoint)
    - When disabled: show "Portal Access: Disabled"
    - _Requirements: 14.1, 14.2, 14.3_

  - [x] 5.4 Add per-org configurable token TTL
    - Add `portal_token_ttl_days` to org settings JSONB (default: 90) — update org settings schema
    - When generating/regenerating tokens, read `org.settings.get("portal_token_ttl_days", 90)`
    - Add "Portal Token TTL (days)" number input in the org settings frontend page
    - _Requirements: 15.1, 15.2, 15.3_

  - [x] 5.5 Write property tests for token lifecycle
    - **Property 11: Token lifecycle on enable_portal toggle**
    - **Property 12: Token TTL uses org-configured value**
    - **Validates: Requirements 12.1, 12.3, 15.2**

- [x] 6. Portal Feature Coverage (Req 16-24)
  - [x] 6.1 Add portal jobs endpoint and frontend tab
    - Add `PortalJobItem` and `PortalJobsResponse` schemas in `app/modules/portal/schemas.py`
    - Add `get_portal_jobs` function in `app/modules/portal/service.py` — query `job_cards` by `customer_id` and `org_id`
    - Add `GET /portal/{token}/jobs` endpoint in `app/modules/portal/router.py`
    - Create `frontend/src/pages/portal/JobsTab.tsx` — display job list with status badges (pending, in_progress, completed, invoiced)
    - Add "Jobs" tab in `PortalPage.tsx`
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

  - [x] 6.2 Add portal claims endpoint and frontend tab
    - Add `PortalClaimItem` and `PortalClaimsResponse` schemas in `app/modules/portal/schemas.py`
    - Add `get_portal_claims` function in `app/modules/portal/service.py` — query claims by `customer_id` and `org_id`
    - Add `GET /portal/{token}/claims` endpoint in `app/modules/portal/router.py`
    - Create `frontend/src/pages/portal/ClaimsTab.tsx` — display claims list with status badges and timeline
    - Add "Claims" tab in `PortalPage.tsx`
    - _Requirements: 17.1, 17.2, 17.3_

  - [x] 6.3 Add portal invoice PDF download
    - Add `GET /portal/{token}/invoices/{invoice_id}/pdf` endpoint in `app/modules/portal/router.py`
    - Validate invoice belongs to customer via token, reuse existing PDF generation from `invoices/service.py`
    - Return PDF with `Content-Type: application/pdf` and `Content-Disposition: attachment`
    - Add "Download PDF" button on each invoice row in `frontend/src/pages/portal/InvoiceHistory.tsx`
    - _Requirements: 18.1, 18.2, 18.3, 18.4_

  - [x] 6.4 Add portal compliance documents endpoint and tab
    - Add `PortalDocumentItem` and `PortalDocumentsResponse` schemas in `app/modules/portal/schemas.py`
    - Add `get_portal_documents` function in `app/modules/portal/service.py` — query compliance_documents linked to customer's invoices
    - Add `GET /portal/{token}/documents` endpoint in `app/modules/portal/router.py`
    - Create `frontend/src/pages/portal/DocumentsTab.tsx` — display documents list with download links
    - Add "Documents" tab in `PortalPage.tsx`
    - _Requirements: 19.1, 19.2, 19.3_

  - [x] 6.5 Add contact details self-service update
    - Add `PortalProfileUpdateRequest` schema in `app/modules/portal/schemas.py` with `email` and `phone` fields
    - Add `update_portal_profile` function in `app/modules/portal/service.py` — validate email/phone format, update customer record
    - Add `PATCH /portal/{token}/profile` endpoint in `app/modules/portal/router.py`
    - Add "My Details" section in `frontend/src/pages/portal/PortalPage.tsx` with editable contact info form
    - _Requirements: 21.1, 21.2, 21.3, 21.4_

  - [x] 6.6 Add booking cancellation
    - Add `PATCH /portal/{token}/bookings/{booking_id}/cancel` endpoint in `app/modules/portal/router.py`
    - Add `cancel_portal_booking` function in `app/modules/portal/service.py` — validate ownership and cancellable status (pending/confirmed), set status to `cancelled`
    - Add "Cancel" button on cancellable bookings in `frontend/src/pages/portal/BookingManager.tsx`
    - _Requirements: 22.1, 22.2, 22.3, 22.4_

  - [x] 6.7 Add quote acceptance notification
    - In `accept_portal_quote` in `app/modules/portal/service.py`, after successful acceptance, trigger email notification to org's primary contact
    - Include: quote number, customer name, accepted date
    - Use existing email sending infrastructure
    - _Requirements: 23.1, 23.2, 23.3_

  - [x] 6.8 Add booking confirmation on portal creation
    - In `create_portal_booking` in `app/modules/portal/service.py`, after `svc.create_booking()`, call `svc.send_confirmation(booking)` to transition status to `confirmed`
    - Trigger notification to org about new portal booking
    - _Requirements: 24.1, 24.2, 24.3_

  - [x] 6.9 Write property tests for portal feature coverage
    - **Property 13: Portal jobs endpoint returns correct fields for all statuses**
    - **Property 14: Portal claims endpoint returns correct fields**
    - **Property 15: Invoice PDF access validates ownership**
    - **Property 17: Partial payment amount validation**
    - **Property 18: Profile update validates email and phone format**
    - **Property 19: Booking cancellation validates ownership and status**
    - **Property 20: Quote acceptance notification contains required fields**
    - **Property 21: Portal booking creation results in confirmed status**
    - **Validates: Requirements 16.2-16.3, 17.2, 18.2, 20.2-20.3, 21.2, 22.2-22.3, 23.3, 24.2**

- [x] 7. Checkpoint — Verify portal feature coverage
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Portal UX Polish (Req 25-30)
  - [x] 8.1 Fix mobile share portal link URLs
    - Update `InvoiceDetailScreen` and `QuoteDetailScreen` in the mobile app to generate URLs as `/portal/{customer_portal_token}` instead of `/portal/invoices/{id}` or `/portal/quotes/{id}`
    - Ensure backend invoice/quote detail responses include `customer_portal_token` field
    - Hide "Share Portal Link" button when customer has no portal token or portal access is disabled
    - _Requirements: 25.1, 25.2, 25.3, 25.4_

  - [x] 8.2 Add pagination to all portal list endpoints
    - Add `limit: int = Query(20)` and `offset: int = Query(0)` parameters to all portal list endpoints in `app/modules/portal/router.py`
    - Apply `.limit(limit).offset(offset)` to queries and add `SELECT COUNT(*)` for total in `app/modules/portal/service.py`
    - Add `total: int = 0` to all list response schemas in `app/modules/portal/schemas.py` (`PortalInvoicesResponse`, `PortalQuotesResponse`, `PortalVehiclesResponse`, `PortalBookingsResponse`, `PortalAssetsResponse`, `PortalLoyaltyResponse`)
    - _Requirements: 26.1, 26.2, 26.3_

  - [x] 8.3 Apply portal i18n
    - Read `branding.language` from API response in `PortalPage.tsx`
    - Set `lang` attribute on portal root element
    - Pass locale to all `Intl.DateTimeFormat` and `Intl.NumberFormat` calls instead of hardcoding `'en-NZ'` across all portal components
    - Use i18n translation keys (prefixed `portal.*`) for UI strings when non-English locale
    - _Requirements: 27.1, 27.2, 27.3, 27.4_

  - [x] 8.4 Complete booking form with service_type and notes
    - Add `service_type` dropdown/text input to booking form in `frontend/src/pages/portal/BookingManager.tsx`
    - Add `notes` textarea to booking form
    - Include both fields in `POST /portal/{token}/bookings` request body
    - _Requirements: 28.1, 28.2, 28.3_

  - [x] 8.5 Add refund status display
    - Add `refunded` and `partially_refunded` entries to `STATUS_CONFIG` in `frontend/src/pages/portal/InvoiceHistory.tsx`
    - Use appropriate labels ("Refunded", "Partially Refunded") and colour-coded badges (info variant)
    - _Requirements: 29.1, 29.2_

  - [x] 8.6 Dead code cleanup — PortalLayout
    - Check if `frontend/src/pages/portal/PortalLayout.tsx` exists
    - If it exists: either remove it or integrate it as the portal's layout wrapper in `App.tsx`, replacing hardcoded "Powered by WorkshopPro NZ" with the configurable `PoweredByFooter` component
    - If it doesn't exist: no action needed
    - _Requirements: 30.1, 30.2_

  - [x] 8.7 Write property tests for portal UX
    - **Property 22: Mobile portal URL format is correct**
    - **Property 23: Pagination returns correct subset and total**
    - **Property 24: Locale is passed to formatters**
    - **Property 25: Booking form includes service_type and notes in request**
    - **Validates: Requirements 25.1-25.2, 26.2-26.3, 27.3, 28.3**

- [x] 9. Checkpoint — Verify portal UX polish
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Branch Transfers Gap Fixes (Req 31-35)
  - [x] 10.1 Add reject transfer endpoint and UI button
    - Add `PUT /api/v2/stock-transfers/{id}/reject` endpoint in `app/modules/franchise/router.py` — call `FranchiseService.reject_transfer()`
    - Add "Reject" button alongside "Approve" on pending transfers in `frontend/src/pages/franchise/StockTransfers.tsx`
    - _Requirements: 31.1, 31.2, 31.3, 31.4_

  - [x] 10.2 Add product search dropdown to transfer form
    - Replace raw "Product ID" text input with a searchable product dropdown in `frontend/src/pages/franchise/StockTransfers.tsx`
    - Query `GET /api/v2/products?search={term}` and display product name + SKU
    - Set `product_id` to selected product's UUID on selection
    - _Requirements: 32.1, 32.2, 32.3_

  - [x] 10.3 Add receive confirmation step
    - Add `PUT /api/v2/stock-transfers/{id}/receive` endpoint in `app/modules/franchise/router.py` — set status to `received`
    - Add "Receive" button on transfers with status `executed` in `frontend/src/pages/franchise/StockTransfers.tsx` when user is at destination location
    - _Requirements: 33.1, 33.2, 33.3, 33.4_

  - [x] 10.4 Add transfer detail view
    - Create `frontend/src/pages/franchise/TransferDetail.tsx` — display all transfer fields (source/dest location, product, quantity, status, notes, requested by, approved by, dates) with status-appropriate action buttons
    - Add route `/stock-transfers/:id` in `frontend/src/App.tsx`
    - Make transfer rows clickable in `StockTransfers.tsx` to navigate to detail view
    - _Requirements: 34.1, 34.2, 34.3_

  - [x] 10.5 Verify sidebar route fix
    - Verify `/branch-transfers` route in `App.tsx` renders the `BranchStockTransfers` component correctly
    - If `BranchStockTransfers` component doesn't exist or is broken, create it or redirect to the franchise `StockTransfers`
    - Verify sidebar "Branch Transfers" link in `OrgLayout.tsx` matches the route path
    - _Requirements: 35.1, 35.2_

  - [x] 10.6 Write property tests for branch transfers
    - **Property 26: Transfer rejection sets status to rejected**
    - **Property 27: Transfer receive sets status to received**
    - **Property 28: Transfer detail view shows correct action buttons per status**
    - **Validates: Requirements 31.4, 33.2, 34.3**

- [x] 11. Checkpoint — Verify branch transfer fixes
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Staff Schedule Gap Fixes (Req 36-38)
  - [x] 12.1 Create schedule entry modal
    - Create `frontend/src/pages/schedule/ScheduleEntryModal.tsx` — modal/slide-over form with fields: staff member (dropdown), title, entry type (job/booking/break/other), start time, end time, notes
    - Create mode: `POST /api/v2/schedule`, edit mode: `PUT /api/v2/schedule/{id}` (pre-populated)
    - After submit, check for conflicts via `GET /api/v2/schedule/{id}/conflicts` and display warning if any
    - _Requirements: 36.1, 36.2, 36.3, 36.4, 36.5, 36.6_

  - [x] 12.2 Wire schedule entry modal into ScheduleCalendar
    - Add "New Entry" button in `frontend/src/pages/schedule/ScheduleCalendar.tsx` header
    - Make entry cards clickable → open edit modal with existing data
    - Pass `onSave` callback to refresh entries after create/edit
    - _Requirements: 36.1, 36.4_

  - [x] 12.3 Clarify dual sidebar entries
    - Review "Schedule" (`/schedule`, module: `scheduling`) and "Staff Schedule" (`/staff-schedule`, module: `branch_management`) entries in `frontend/src/layouts/OrgLayout.tsx`
    - Verify both entries have distinct routes and distinct page content — "Schedule" shows the full roster calendar, "Staff Schedule" shows the branch-scoped admin view
    - If `/staff-schedule` route is broken or renders the same content, differentiate or remove it
    - _Requirements: 37.1, 37.2, 37.3_

  - [x] 12.4 Add drag-and-drop rescheduling
    - Add drag-and-drop support to `EntryCard` components in `frontend/src/pages/schedule/ScheduleCalendar.tsx`
    - On drop: calculate new `start_time` and `end_time` from target slot (preserve original duration)
    - Call `PUT /api/v2/schedule/{id}/reschedule` with new times
    - Show warning if conflict detected but complete the move
    - Use HTML5 Drag and Drop API or `@dnd-kit/core` (check existing project dependencies first)
    - _Requirements: 38.1, 38.2, 38.3, 38.4_

  - [x] 12.5 Write property tests for schedule
    - **Property 29: Schedule conflict detection flags overlapping entries**
    - **Property 30: Drag-and-drop computes correct new times**
    - **Validates: Requirements 36.6, 38.3**

- [x] 13. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Verify all 38 requirements are covered by implementation tasks.
  - Run full test suite including property-based tests.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation after each phase
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The backend uses Python/FastAPI with SQLAlchemy async; the frontend uses React/TypeScript with Vite
- All frontend API consumption must follow safe-api-consumption patterns: `?.` and `?? []` / `?? 0` on all API data

- [x] 14. Portal Advanced Security (Req 39-43)
  - [x] 14.1 Add portal audit logging for customer actions
    - In `app/modules/portal/service.py`, after each state-changing action (`accept_portal_quote`, `create_portal_booking`, `create_portal_payment`, `update_portal_profile`, `cancel_portal_booking`), call `write_audit_log()` with action prefix `portal.*`, customer ID, IP address
    - Update all portal POST/PATCH router endpoints to pass `request: Request` and extract client IP
    - _Requirements: 39.1, 39.2, 39.3, 39.4, 39.5_

  - [x] 14.2 Implement portal session and logout mechanism
    - Create Alembic migration for `portal_sessions` table (id, customer_id, session_token, expires_at, last_seen, created_at)
    - In `_resolve_token`, after validating token, create a portal session and set HttpOnly `portal_session` cookie
    - Add session validation middleware/helper that checks the cookie on subsequent requests
    - Implement 4-hour inactivity timeout (check `last_seen + 4h < now`)
    - Add `POST /portal/logout` endpoint that clears session and cookie
    - Add "Sign Out" button in `PortalPage.tsx` header
    - _Requirements: 40.1, 40.2, 40.3, 40.4_

  - [x] 14.3 Add CSRF protection on portal POST endpoints
    - Implement double-submit cookie pattern: generate CSRF token on session creation, set as non-HttpOnly cookie `portal_csrf`
    - Frontend reads cookie and sends as `X-CSRF-Token` header on all state-changing requests
    - Backend validates header matches cookie on POST/PATCH/PUT/DELETE portal endpoints
    - _Requirements: 41.1, 41.2, 41.3_

  - [x] 14.4 Strengthen portal token format
    - Replace `uuid.uuid4()` with `secrets.token_urlsafe(32)` in all portal token generation code (customer service, admin regenerate endpoint)
    - No schema migration needed — column is already VARCHAR
    - Existing UUID tokens continue to work until expiry
    - _Requirements: 42.1, 42.2, 42.3_

  - [x] 14.5 Mitigate portal token URL exposure
    - Add `<meta name="referrer" content="no-referrer" />` to portal pages in `PortalPage.tsx`
    - After successful token validation, call `window.history.replaceState({}, '', '/portal/dashboard')` to remove token from address bar
    - Add `Cache-Control: no-store` and `Pragma: no-cache` response headers to all portal endpoints in `portal/router.py`
    - _Requirements: 43.1, 43.2, 43.3_

- [x] 15. Portal Compliance and Privacy (Req 44-45)
  - [x] 15.1 Add cookie consent banner to portal
    - Create `frontend/src/pages/portal/CookieConsent.tsx` — bottom banner with Accept/Decline buttons
    - Check localStorage for existing consent on mount
    - On accept: store consent, dismiss banner. On decline: only essential cookies
    - Render in `PortalPage.tsx` before main content
    - _Requirements: 44.1, 44.2, 44.3, 44.4_

  - [x] 15.2 Add DSAR (Data Subject Access Request) from portal
    - Add `POST /portal/{token}/dsar` endpoint in `app/modules/portal/router.py` accepting `{ request_type: "export" | "deletion" }`
    - Create DSAR record and notify org admin via existing notification system
    - Add "My Privacy" section in `PortalPage.tsx` with "Request Data Export" and "Request Account Deletion" buttons
    - _Requirements: 45.1, 45.2, 45.3, 45.4, 45.5_

- [x] 16. Portal Operational Features (Req 46-48)
  - [x] 16.1 Add global portal enable/disable per org
    - Add `portal_enabled` to org settings JSONB (default: true)
    - In `_resolve_token` in `app/modules/portal/service.py`, after resolving customer, check `org.settings.get("portal_enabled", True)` — if false, raise ValueError
    - Add "Customer Portal" toggle in org settings frontend page
    - _Requirements: 46.1, 46.2, 46.3_

  - [x] 16.2 Add portal analytics for org admins
    - Increment Redis counters on each portal access: `portal:analytics:{org_id}:{date}:{event_type}` (view, quote_accepted, booking_created, payment_initiated)
    - Add `GET /api/v2/org/portal-analytics` endpoint returning last 30 days of stats
    - Display portal usage stats in org admin dashboard or settings page
    - _Requirements: 47.1, 47.2, 47.3_

  - [x] 16.3 Add portal access log (last seen)
    - Create Alembic migration to add `last_portal_access_at TIMESTAMPTZ` column to customers table
    - In `get_portal_access` in `app/modules/portal/service.py`, update `customer.last_portal_access_at = now()` on each access
    - Display `last_portal_access_at` in customer list and detail views in frontend
    - _Requirements: 48.1, 48.2, 48.3_

- [x] 17. Portal Additional Feature Coverage (Req 49-52)
  - [x] 17.1 Add portal projects endpoint and tab
    - Add `PortalProjectItem` and `PortalProjectsResponse` schemas in `app/modules/portal/schemas.py`
    - Add `get_portal_projects` in `app/modules/portal/service.py` — query projects by customer_id and org_id
    - Add `GET /portal/{token}/projects` endpoint in `app/modules/portal/router.py`
    - Create `frontend/src/pages/portal/ProjectsTab.tsx` and add as tab in `PortalPage.tsx`
    - _Requirements: 49.1, 49.2, 49.3_

  - [x] 17.2 Add portal recurring schedules endpoint and tab
    - Add `PortalRecurringItem` and `PortalRecurringResponse` schemas in `app/modules/portal/schemas.py`
    - Add `get_portal_recurring` in `app/modules/portal/service.py` — query recurring_schedules by customer_id and org_id
    - Add `GET /portal/{token}/recurring` endpoint in `app/modules/portal/router.py`
    - Add "Recurring" section or tab in `PortalPage.tsx`
    - _Requirements: 50.1, 50.2, 50.3_

  - [x] 17.3 Add portal progress claims endpoint
    - Add `PortalProgressClaimItem` and `PortalProgressClaimsResponse` schemas in `app/modules/portal/schemas.py`
    - Add `get_portal_progress_claims` in `app/modules/portal/service.py` — query progress_claims linked to customer's projects
    - Add `GET /portal/{token}/progress-claims` endpoint in `app/modules/portal/router.py`
    - Add "Progress Claims" section within Projects tab or standalone tab in `PortalPage.tsx`
    - _Requirements: 51.1, 51.2, 51.3_

  - [x] 17.4 Add self-service token recovery ("Forgot my link")
    - Add `POST /portal/recover` endpoint in `app/modules/portal/router.py` accepting `{ email }`
    - Look up all portal-enabled customers with that email, send portal links via email
    - Always return 200 with generic message to prevent email enumeration
    - Add "Forgot your link?" link on portal landing page in frontend
    - _Requirements: 52.1, 52.2, 52.3, 52.4_

- [x] 18. Branch Transfers Additional Gaps (Req 53-55)
  - [x] 18.1 Add transfer audit trail
    - Create Alembic migration for `transfer_actions` table (id, transfer_id, action, performed_by, notes, created_at)
    - Log each status transition in `app/modules/franchise/service.py` (create, approve, reject, execute, receive)
    - Display audit trail timeline in `TransferDetail.tsx`
    - _Requirements: 53.1, 53.2, 53.3_

  - [x] 18.2 Add partial transfer support
    - Add `received_quantity` and `discrepancy_quantity` columns to `stock_transfers` table via migration
    - Update `PUT /api/v2/stock-transfers/{id}/receive` to accept optional `received_quantity` parameter
    - If `received_quantity < transfer.quantity`, set status to `partially_received` and record discrepancy
    - Update frontend receive form to include quantity input
    - _Requirements: 54.1, 54.2, 54.3_

  - [x] 18.3 Add transfer event notifications
    - After transfer create: notify destination location manager
    - After transfer approve/execute: notify both source and destination managers
    - Use existing in-app notification system, optionally email
    - _Requirements: 55.1, 55.2, 55.3_

- [x] 19. Staff Schedule Additional Gaps (Req 56-60)
  - [x] 19.1 Add recurring schedule / shift patterns
    - Add `recurrence_group_id UUID` column to `schedule_entries` table via migration
    - Add `create_recurring_entry` function in `app/modules/scheduling_v2/service.py` that generates individual entries for the recurrence period (up to 4 weeks)
    - Add "Repeat" option (none/daily/weekly/fortnightly) to the create entry modal in frontend
    - Visually distinguish recurring entries in `ScheduleCalendar.tsx`
    - _Requirements: 56.1, 56.2, 56.3_

  - [x] 19.2 Add shift templates
    - Create Alembic migration for `shift_templates` table (id, org_id, name, start_time, end_time, entry_type, created_at)
    - Add CRUD endpoints: `GET /api/v2/schedule/templates`, `POST /api/v2/schedule/templates`, `DELETE /api/v2/schedule/templates/{id}` in `app/modules/scheduling_v2/router.py`
    - Add "Templates" section in schedule frontend and "Use Template" dropdown in create entry modal
    - _Requirements: 57.1, 57.2, 57.3_

  - [x] 19.3 Add leave and absence tracking
    - Add `"leave"` to the `entry_type` enum/allowed values in `ScheduleEntry` model
    - Update conflict detection in `app/modules/scheduling_v2/service.py` to treat leave entries as blocking
    - Add "Add Leave" button in `ScheduleCalendar.tsx` header
    - Render leave entries with distinct visual style (grey/hatched) in the calendar
    - _Requirements: 58.1, 58.2, 58.3_

  - [x] 19.4 Add schedule print and export
    - Add "Print" button in `ScheduleCalendar.tsx` that calls `window.print()` with `@media print` CSS for the schedule grid
    - Add "Export CSV" button that generates CSV from current entries array (staff name, date, start, end, type, title, notes) and triggers download
    - _Requirements: 59.1, 59.2_

  - [x] 19.5 Add mobile-optimised schedule view
    - Add responsive breakpoint in `ScheduleCalendar.tsx` — below 768px switch to single-column layout
    - Mobile layout shows one staff member at a time (current user by default) with day view
    - Add staff switcher dropdown for managers on mobile
    - _Requirements: 60.1, 60.2, 60.3_

- [x] 20. Portal Loyalty, Branding, SMS (Req 61-63)
  - [x] 20.1 Fix loyalty balance empty state
    - In `frontend/src/pages/portal/LoyaltyBalance.tsx`, check if loyalty data indicates no programme configured vs zero balance
    - Show "This business does not have a loyalty programme" when no programme exists
    - Show "You have 0 points" with earning explanation when programme exists but balance is zero
    - _Requirements: 61.1, 61.2_

  - [x] 20.2 Apply organisation branding to portal theme
    - In `PortalPage.tsx`, set CSS custom property `--portal-accent` from `branding.primary_colour`
    - Apply to all buttons, links, active tab indicators, and summary card accents across all portal components
    - Display `branding.logo_url` in portal header
    - Use `branding.secondary_colour` for secondary elements when available
    - Fall back to default blue (#2563eb) when colours not set
    - _Requirements: 62.1, 62.2, 62.3, 62.4_

  - [x] 20.3 Add SMS conversation history tab
    - Add `GET /portal/{token}/messages` endpoint in `app/modules/portal/router.py` — query `sms_messages` by customer phone and org_id
    - Add `PortalMessageItem` and `PortalMessagesResponse` schemas in `app/modules/portal/schemas.py`
    - Create `frontend/src/pages/portal/MessagesTab.tsx` with chat-style layout (inbound left, outbound right)
    - Add "Messages" tab in `PortalPage.tsx`
    - _Requirements: 63.1, 63.2, 63.3, 63.4_

- [x] 21. Final verification — all 63 requirements covered
  - Run full test suite
  - Git push all new changes
  - Verify all new endpoints respond correctly
  - Verify all new frontend tabs/components render
  - Cross-reference requirements 1-63 against implementation
