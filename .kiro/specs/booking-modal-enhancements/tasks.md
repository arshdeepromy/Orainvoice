# Implementation Plan: Booking Modal Enhancements

## Overview

Enhance the existing `BookingForm.tsx` modal and `bookings` backend module with inline customer creation, module-gated vehicle rego field (reusing `VehicleLiveSearch`), service catalogue selector with pricing and inline add, and subscription-aware split email/SMS confirmation and reminder notifications. Backend changes include new columns on the `bookings` table (migration 0081), enhanced `create_booking` service logic, a plan-features endpoint, and reminder scheduling. Frontend changes enhance the existing `BookingForm` component with new sections for each capability.

## Tasks

- [x] 1. Database migration and model updates
  - [x] 1.1 Create Alembic migration 0081 to add new columns to the `bookings` table
    - Add columns: `service_catalogue_id` (UUID FK → `service_catalogue.id`, nullable), `service_price` (Numeric(10,2), nullable), `send_email_confirmation` (Boolean, NOT NULL, server_default false), `send_sms_confirmation` (Boolean, NOT NULL, server_default false), `reminder_offset_hours` (Numeric(5,1), nullable), `reminder_scheduled_at` (DateTime(tz), nullable), `reminder_cancelled` (Boolean, NOT NULL, server_default false)
    - File: `alembic/versions/2026_XX_XX-0081_booking_modal_enhancements.py`
    - Include downgrade to drop all added columns
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.10_

  - [x] 1.2 Update the `Booking` SQLAlchemy model in `app/modules/bookings/models.py`
    - Add mapped columns for `service_catalogue_id`, `service_price`, `send_email_confirmation`, `send_sms_confirmation`, `reminder_offset_hours`, `reminder_scheduled_at`, `reminder_cancelled`
    - Use correct types matching the migration (UUID FK, Numeric, Boolean, DateTime)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

- [x] 2. Backend schema updates
  - [x] 2.1 Update `BookingCreate` schema in `app/modules/bookings/schemas.py`
    - Add fields: `service_catalogue_id` (uuid | None), `service_price` (Decimal | None), `send_email_confirmation` (bool, default False), `send_sms_confirmation` (bool, default False), `reminder_offset_hours` (float | None)
    - Keep existing `send_confirmation` field for backward compatibility — if `send_confirmation` is true and `send_email_confirmation` is not explicitly set, treat as `send_email_confirmation: true`
    - _Requirements: 6.8_

  - [x] 2.2 Update `BookingResponse` schema in `app/modules/bookings/schemas.py`
    - Add fields: `service_catalogue_id`, `service_price`, `send_email_confirmation`, `send_sms_confirmation`, `reminder_offset_hours`, `reminder_scheduled_at`, `reminder_cancelled`
    - _Requirements: 6.9_

  - [x] 2.3 Update `_booking_to_dict` helper in `app/modules/bookings/service.py`
    - Include all new fields in the dict output so they flow through to the response schema
    - _Requirements: 6.8, 6.9_

  - [x] 2.4 Write property test for BookingCreate/BookingResponse schema round-trip
    - **Property 14: BookingCreate/BookingResponse schema round-trip**
    - **Validates: Requirements 6.8, 6.9**

- [x] 3. Checkpoint — Run migration and verify model
  - Ensure migration 0081 applies cleanly against the database. Ensure all tests pass, ask the user if questions arise.

- [x] 4. Backend service enhancements — booking creation logic
  - [x] 4.1 Add vehicle rego module gating to `create_booking` in `app/modules/bookings/service.py`
    - Import `ModuleService` from `app/core/modules`
    - If `vehicle_rego` is provided, check `ModuleService(db).is_enabled(str(org_id), "vehicles")`; if disabled, set `vehicle_rego = None`
    - _Requirements: 2.5, 2.6_

  - [x] 4.2 Write property test for vehicle rego module gating
    - **Property 6: Vehicle rego storage is conditional on module enablement**
    - **Validates: Requirements 2.5, 2.6**

  - [x] 4.3 Add service catalogue linkage to `create_booking` in `app/modules/bookings/service.py`
    - If `service_catalogue_id` is provided, validate it exists, belongs to the org, and is active; raise ValueError if not
    - Store `service_catalogue_id`, `service_type` (from catalogue name), and `service_price` (from catalogue default_price) on the booking
    - _Requirements: 3.2, 3.8, 3.9_

  - [x] 4.4 Write property test for service catalogue linkage
    - **Property 8: Service selection stores catalogue ID, name, and price**
    - **Validates: Requirements 3.2, 3.8, 3.9**

  - [x] 4.5 Add split notification dispatch to `create_booking` in `app/modules/bookings/service.py`
    - After booking creation, if `send_email_confirmation` is true, call notification service to send email
    - If `send_sms_confirmation` is true, validate org plan has `sms_included`; if not, silently skip SMS and log warning
    - If neither flag is true, send no notifications
    - Handle backward compat: if old `send_confirmation` is true, treat as `send_email_confirmation: true`
    - _Requirements: 4.4, 4.5, 4.6_

  - [x] 4.6 Write property test for notification channel dispatch
    - **Property 9: Notification channels match confirmation flags**
    - **Validates: Requirements 4.4, 4.5, 4.6**

  - [x] 4.7 Add reminder scheduling to `create_booking` in `app/modules/bookings/service.py`
    - If `reminder_offset_hours` is provided, calculate `reminder_scheduled_at = scheduled_at - timedelta(hours=reminder_offset_hours)`
    - If `reminder_scheduled_at` is in the past, skip scheduling (set to null) and log a warning
    - Store `reminder_offset_hours` and `reminder_scheduled_at` on the booking
    - Reminder uses same channels as confirmation (stored on booking via `send_email_confirmation`/`send_sms_confirmation`)
    - _Requirements: 5.5, 5.8, 5.9_

  - [x] 4.8 Write property test for reminder scheduling
    - **Property 10: Reminder scheduled_at equals booking time minus offset**
    - **Validates: Requirements 5.5**

  - [x] 4.9 Write property test for reminder channel matching
    - **Property 13: Reminder uses same channels as confirmation**
    - **Validates: Requirements 5.9**

- [x] 5. Backend service enhancements — cancellation and update logic
  - [x] 5.1 Enhance booking cancellation in `app/modules/bookings/service.py`
    - In `delete_booking` and in `update_booking` (when status transitions to `cancelled`), if `reminder_scheduled_at` is set and `reminder_cancelled` is false, set `reminder_cancelled = True`
    - _Requirements: 5.6_

  - [x] 5.2 Write property test for cancellation reminder handling
    - **Property 11: Booking cancellation cancels pending reminder**
    - **Validates: Requirements 5.6**

  - [x] 5.3 Write property test for reminder sent-at-most-once
    - **Property 12: Reminder sent at most once per booking**
    - **Validates: Requirements 5.7**

- [x] 6. Backend — update router and add plan-features endpoint
  - [x] 6.1 Update `create_booking_endpoint` in `app/modules/bookings/router.py`
    - Pass new fields from `BookingCreate` payload to `create_booking` service: `service_catalogue_id`, `service_price`, `send_email_confirmation`, `send_sms_confirmation`, `reminder_offset_hours`
    - Update the response construction to use the enhanced `BookingResponse` schema
    - _Requirements: 6.8, 6.9_

  - [x] 6.2 Add `GET /api/v1/org/plan-features` endpoint
    - Add to the organisations router (or a suitable existing router)
    - Query the org's subscription plan for `sms_included` and return `{ sms_included: boolean }`
    - _Requirements: 4.2, 4.3_

- [x] 7. Checkpoint — Backend complete
  - Ensure all backend tests pass and the new endpoint returns correct data. Ask the user if questions arise.

- [x] 8. Frontend — Customer search with inline add
  - [x] 8.1 Add "Add new customer" option to customer search dropdown in `BookingForm.tsx`
    - When `customerResults` is empty and `customerSearch.length >= 2`, show an "Add new customer" option at the bottom of the dropdown
    - Clicking it expands an inline customer form section below the search field
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 8.2 Implement inline customer form section in `BookingForm.tsx`
    - Fields: first name (pre-populated from search query if it looks like a name — alphabetic chars and spaces only), last name, email, phone
    - On submit, call `POST /api/v1/customers` and auto-select the newly created customer
    - Display validation errors inline below the form without closing it
    - Selecting an existing customer from the dropdown collapses the inline form
    - _Requirements: 1.3, 1.4, 1.5, 1.6, 1.7_

  - [x] 8.3 Write property test for customer search minimum query length
    - **Property 1: Customer search triggers at minimum query length**
    - **Validates: Requirements 1.1**

  - [x] 8.4 Write property test for empty search results showing inline add option
    - **Property 2: Empty search results show inline add option**
    - **Validates: Requirements 1.2, 3.3**

  - [x] 8.5 Write property test for search query pre-populating customer name
    - **Property 5: Search query pre-populates inline customer name**
    - **Validates: Requirements 1.7**

- [x] 9. Frontend — Vehicle rego field with module gating
  - [x] 9.1 Replace plain-text vehicle rego input with module-gated `VehicleLiveSearch` in `BookingForm.tsx`
    - Wrap in `<ModuleGate module="vehicles">` so it's completely hidden when vehicles module is disabled
    - Reuse the existing `VehicleLiveSearch` component — do not duplicate vehicle search code
    - Wire `onVehicleFound` callback to store the selected vehicle rego in form state
    - Field is optional — staff can leave it empty
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 10. Frontend — Service type selector with pricing and inline add
  - [x] 10.1 Replace plain-text service type input with a service catalogue typeahead in `BookingForm.tsx`
    - Search `GET /api/v1/catalogue/services?search=...&active_only=true&page_size=10`
    - Display results with service name and formatted default_price (e.g. "Full Service — $185.00")
    - On selection, store `service_catalogue_id`, `service_type` (name), and `service_price` (default_price) in form state
    - Display selected service price next to the service name after selection
    - _Requirements: 3.1, 3.2, 3.7_

  - [x] 10.2 Add "Add new service" option and inline service form in `BookingForm.tsx`
    - When service search returns 0 results and query ≥ 2 chars, show "Add new service" option
    - Clicking it expands an inline service form with: service name (pre-populated from query), default price, category dropdown
    - On submit, call `POST /api/v1/catalogue/services` and auto-select the new service
    - Display validation errors inline without closing the form
    - _Requirements: 3.3, 3.4, 3.5, 3.6_

  - [x] 10.3 Write property test for service selector returning only active services with pricing
    - **Property 7: Service selector returns only active services with pricing**
    - **Validates: Requirements 3.1**

- [x] 11. Frontend — Subscription-aware notification configuration
  - [x] 11.1 Replace single confirmation checkbox with split email/SMS checkboxes and reminder section in `BookingForm.tsx`
    - Fetch `GET /api/v1/org/plan-features` on mount to determine `sms_included`
    - Always show "Send email confirmation" checkbox on create
    - Show "Send SMS confirmation" checkbox only when `sms_included` is true
    - If plan-features fetch fails, default to `sms_included: false` (hide SMS checkbox)
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 11.2 Add reminder configuration section in `BookingForm.tsx`
    - Reminder section with radio options: None, 24 hours before, 6 hours before, Custom
    - Custom option reveals a numeric input for specifying hours before booking
    - Store `reminder_offset_hours` in form state
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 11.3 Update form submission in `BookingForm.tsx` to send new fields
    - Send `service_catalogue_id`, `service_price`, `send_email_confirmation`, `send_sms_confirmation`, `reminder_offset_hours` in the POST payload
    - Remove old `send_confirmation` field from the create payload
    - _Requirements: 6.8_

- [x] 12. Final checkpoint — Full integration
  - Ensure all backend and frontend changes work together. Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- The `get_db_session` dependency auto-commits — router endpoints must NOT call `db.commit()`, use `db.flush()` instead
- Service functions use `db.flush()` only (not commit) — by design for transaction composition
- After `db.flush()`, server-generated columns need `await db.refresh(obj)`
- Current DB migration head: 0080 — new migration must be 0081
- Reuse existing `VehicleLiveSearch` component — do not duplicate vehicle search logic
- Follow vehicle module gating rules from `.kiro/steering/vehicle-carjam-module-gating.md`
