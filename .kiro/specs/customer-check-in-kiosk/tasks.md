# Implementation Plan: Customer Check-In Kiosk

## Overview

Add a self-service tablet-facing check-in page at `/kiosk` with a new `kiosk` role. Implementation proceeds bottom-up: database migration → RBAC updates → backend kiosk module → auth service update → frontend kiosk components → settings page update. The kiosk role uses allowlist-based RBAC, a single composite check-in endpoint, and 30-day refresh tokens.

## Tasks

- [x] 1. Database migration and RBAC setup
  - [x] 1.1 Create Alembic migration to add `kiosk` to the role CHECK constraint
    - Drop existing `ck_users_role` constraint and recreate with `'kiosk'` appended to the allowed values
    - Include `downgrade()` that restores the original constraint without `'kiosk'`
    - _Requirements: 1.1_

  - [x] 1.2 Update RBAC module (`app/modules/auth/rbac.py`) with kiosk role and allowlist
    - Add `KIOSK = "kiosk"` constant and add to `ALL_ROLES` set
    - Add `KIOSK` to `ROLE_PERMISSIONS` with `["kiosk.check_in"]`
    - Define `KIOSK_ALLOWED_PREFIXES` tuple: `/api/v1/kiosk/`, `/api/v1/kiosk`, `/api/v1/org/settings`
    - Add kiosk branch in `check_role_path_access` that denies any path not in the allowlist, and restricts `/api/v1/org/settings` to GET only
    - _Requirements: 1.5, 1.6, 6.1_

  - [x] 1.3 Write property test for RBAC allowlist enforcement
    - **Property 3: Kiosk RBAC allowlist enforcement**
    - Generate random API paths and HTTP methods; verify `check_role_path_access("kiosk", path, method)` returns None only for allowed prefixes and GET-only on org/settings
    - Create test in `tests/properties/test_kiosk_properties.py` using Hypothesis
    - **Validates: Requirements 1.5, 1.6, 6.1**

- [x] 2. Checkpoint — Verify migration and RBAC
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Backend kiosk module — schemas and service
  - [x] 3.1 Create `app/modules/kiosk/schemas.py` with Pydantic request/response models
    - `KioskCheckInRequest`: first_name (1-100 chars, required), last_name (1-100 chars, required), phone (min 7 digits, required), email (optional, valid format), vehicle_rego (optional, stripped/uppercased)
    - `KioskCheckInResponse`: customer_first_name (str), is_new_customer (bool), vehicle_linked (bool)
    - Include field validators for phone (strip formatting, check ≥7 digits), email (format check, lowercase), and rego (strip/uppercase, empty→None)
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 3.2 Write property test for check-in form validation
    - **Property 7: Check-in form validation**
    - Generate random (first_name, last_name, phone, email, rego) tuples; verify `KioskCheckInRequest` accepts/rejects correctly based on validation rules
    - Add to `tests/properties/test_kiosk_properties.py`
    - **Validates: Requirements 3.2, 3.3, 3.4**

  - [x] 3.3 Create `app/modules/kiosk/service.py` with check-in orchestration logic
    - Implement `kiosk_check_in(db, org_id, user_id, data, ip_address)` function
    - Search for existing customer by phone within org → return existing or create new with `customer_type="individual"`
    - If vehicle_rego provided: attempt Carjam lookup → fallback to manual vehicle creation → link vehicle to customer (idempotent)
    - If vehicle already exists, link without creating duplicate
    - Return `KioskCheckInResponse` with resolved customer first name, is_new flag, and vehicle_linked flag
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [x] 3.4 Write property tests for customer deduplication and creation
    - **Property 8: Phone-based customer deduplication** — check-in with existing phone returns `is_new_customer: false` and doesn't create duplicates
    - **Validates: Requirements 4.1, 4.2**
    - **Property 9: New customer creation with correct fields** — new customer has correct first_name, last_name, phone, email, and `customer_type="individual"`
    - **Validates: Requirements 4.3, 4.4**
    - Add to `tests/properties/test_kiosk_properties.py`

  - [x] 3.5 Write property tests for vehicle handling
    - **Property 10: Vehicle lookup with Carjam fallback** — Carjam success uses Carjam data; Carjam failure creates manual vehicle; both cases link to customer
    - **Validates: Requirements 4.5, 4.6**
    - **Property 11: Vehicle deduplication** — existing vehicle is linked without creating a duplicate record
    - **Validates: Requirements 4.7**
    - Add to `tests/properties/test_kiosk_properties.py`

  - [x] 3.6 Write property test for check-in response shape
    - **Property 12: Check-in response shape** — response contains customer_first_name (non-empty), is_new_customer (bool), vehicle_linked (bool); customer_first_name matches resolved customer
    - **Validates: Requirements 4.8, 5.1**
    - Add to `tests/properties/test_kiosk_properties.py`

- [x] 4. Backend kiosk module — router and auth updates
  - [x] 4.1 Create `app/modules/kiosk/router.py` with the check-in endpoint
    - `POST /api/v1/kiosk/check-in` with `require_role("kiosk")` dependency
    - Rate limit: 30 requests/minute per kiosk user
    - Call `kiosk_check_in` service function and return `KioskCheckInResponse`
    - _Requirements: 3.7, 6.5_

  - [x] 4.2 Register kiosk router in `app/core/modules.py`
    - Include `app.modules.kiosk.router` in the application module registration
    - _Requirements: 3.7_

  - [x] 4.3 Update auth service (`app/modules/auth/service.py`) for 30-day kiosk refresh token
    - In `authenticate_user`, add kiosk-specific branch before the `remember_me` check: if `user.role == "kiosk"`, set `expires_delta = timedelta(days=30)`
    - _Requirements: 1.3, 1.4_

  - [x] 4.4 Write property test for kiosk authentication token
    - **Property 2: Kiosk authentication produces correct token and session**
    - Verify JWT contains `role: "kiosk"` and correct `org_id`, and session `expires_at` is approximately 30 days from auth time
    - Add to `tests/properties/test_kiosk_properties.py`
    - **Validates: Requirements 1.3, 1.4**

  - [x] 4.5 Update organisation router to allow kiosk role on GET `/org/settings`
    - Add `"kiosk"` to the `require_role` dependency on the `get_settings` endpoint in `app/modules/organisations/router.py`
    - _Requirements: 2.2_

  - [x] 4.6 Write property test for rate limiting
    - **Property 15: Rate limiting enforcement**
    - Generate random request counts; verify requests beyond 30/min are rejected with HTTP 429
    - Add to `tests/properties/test_kiosk_properties.py`
    - **Validates: Requirements 6.5**

  - [x] 4.7 Write backend unit tests (`tests/test_kiosk.py`)
    - Check-in with valid data creates customer and returns expected response
    - Check-in with existing phone returns existing customer (`is_new_customer: false`)
    - Check-in with rego triggers Carjam lookup and links vehicle
    - Check-in with rego when Carjam fails creates manual vehicle
    - Check-in with rego when vehicle already exists links without duplication
    - Check-in without rego returns `vehicle_linked: false`
    - Check-in with invalid phone returns 422
    - Check-in with empty first_name returns 422
    - Kiosk user cannot access `/api/v1/invoices` (403)
    - Kiosk user can GET `/api/v1/org/settings` (200)
    - Kiosk user cannot PUT `/api/v1/org/settings` (403)
    - Rate limiter blocks 31st request in 60 seconds (429)
    - Kiosk authentication produces 30-day session expiry
    - _Requirements: 1.3, 1.4, 1.5, 1.6, 3.2, 3.3, 4.1, 4.2, 4.3, 4.5, 4.6, 4.7, 6.1, 6.5_

- [x] 5. Checkpoint — Verify backend kiosk module end-to-end
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Frontend — Kiosk page and welcome screen
  - [x] 6.1 Create `frontend/src/pages/kiosk/KioskPage.tsx` — top-level kiosk page
    - Manage screen state machine: `'welcome' | 'form' | 'success' | 'error'`
    - Full-screen layout outside `OrgLayout` — no navigation chrome, sidebar, or header links
    - Hold form data in state for error recovery (preserve on error, clear on reset to welcome)
    - Inline error screen with "Something went wrong" message and "Try Again" button
    - _Requirements: 2.1, 5.5, 6.2, 6.3, 6.4_

  - [x] 6.2 Create `frontend/src/pages/kiosk/KioskWelcome.tsx` — welcome screen
    - Fetch org branding from `GET /api/v1/org/settings`
    - Display org logo and name at top
    - Display "Welcome to [Organisation Name]" message
    - Single large "Check In" button with min 48×48px tap target, 22px font
    - Body font min 18px
    - Handle branding fetch failure gracefully (generic welcome without logo/name)
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 6.3 Create `frontend/src/pages/kiosk/KioskCheckInForm.tsx` — check-in form
    - Fields: first name (required), last name (required), phone (required), email (optional), vehicle rego (optional)
    - All inputs min 48px height, 18px font
    - Client-side validation matching backend rules (name 1-100 chars, phone ≥7 digits, email format)
    - Submit button + Back button
    - Loading state with disabled submit to prevent double-tap
    - On submit, POST to `/api/v1/kiosk/check-in`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [x] 6.4 Create `frontend/src/pages/kiosk/KioskSuccess.tsx` — success screen
    - Display "Thanks [First Name], we'll be with you shortly"
    - Countdown timer (10 → 0) with visual display
    - "Done" button for immediate reset to welcome
    - Auto-navigate to welcome when timer hits 0
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 6.5 Register kiosk route in `frontend/src/App.tsx`
    - Add `/kiosk` route inside a `RequireAuth` wrapper but outside `OrgLayout`, at the same level as portal routes
    - Wrap with `SafePage` component
    - _Requirements: 2.1, 2.7_

  - [x] 6.6 Write frontend property tests (`frontend/src/pages/kiosk/__tests__/kiosk.properties.test.ts`)
    - **Property 6: Welcome message format** — generate random org name strings; verify rendered message matches "Welcome to [name]"
    - **Validates: Requirements 2.3**
    - **Property 7: Check-in form validation (client-side)** — generate random input tuples; verify client-side validation matches backend rules
    - **Validates: Requirements 3.2, 3.3, 3.4**
    - **Property 13: Form state preservation on error** — generate random form data; simulate API error; verify form fields retain values
    - **Validates: Requirements 5.5**
    - **Property 14: Form state cleared on reset** — generate random form data; trigger reset; verify all fields are empty and no localStorage/sessionStorage writes
    - **Validates: Requirements 6.3, 6.4**
    - Create test file using fast-check and vitest

  - [x] 6.7 Write frontend unit tests (`frontend/src/pages/kiosk/__tests__/kiosk.test.tsx`)
    - Welcome screen renders org name and logo
    - Check In button navigates to form
    - Form validates required fields before submission
    - Submit sends POST to `/api/v1/kiosk/check-in`
    - Success screen shows "Thanks [name]" message
    - Success screen auto-resets after 10 seconds (fake timers)
    - Done button resets to welcome immediately
    - Error screen preserves form data on "Try Again"
    - Back button returns to welcome from form
    - No localStorage/sessionStorage writes during check-in flow
    - _Requirements: 2.2, 2.3, 2.5, 3.1, 3.7, 5.1, 5.3, 5.4, 5.5, 6.3, 6.4_

- [x] 7. Checkpoint — Verify frontend kiosk flow
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Settings page update and kiosk user management
  - [x] 8.1 Update user creation/edit form in Settings to include "Kiosk" role option
    - Add "Kiosk" to the role selection dropdown when creating or editing a user
    - When `role = "kiosk"` is selected, make first_name and last_name optional (email and password still required)
    - Display Kiosk_User accounts with a distinct "Kiosk" badge in the user list
    - Show last activity timestamp for each Kiosk_User
    - Provide deactivate and revoke session actions for kiosk accounts
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 6.6_

  - [x] 8.2 Write property tests for kiosk user management
    - **Property 1: Kiosk role is a valid user role** — verify "kiosk" is accepted and random non-role strings are rejected
    - **Validates: Requirements 1.1, 1.2**
    - **Property 4: Session revocation on kiosk deactivation** — deactivating a kiosk user results in all sessions having `is_revoked = True`
    - **Validates: Requirements 1.7, 7.3**
    - **Property 5: Multiple kiosk accounts per organisation** — creating N kiosk users succeeds with N distinct accounts scoped to the org
    - **Validates: Requirements 1.8**
    - **Property 16: Kiosk user creation requires only email and password** — creation succeeds without first_name/last_name when `role = "kiosk"`
    - **Validates: Requirements 7.2**
    - Add to `tests/properties/test_kiosk_properties.py`

- [x] 9. Final checkpoint — Full integration verification
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests validate universal correctness properties from the design document (Properties 1-16)
- The backend uses Python (FastAPI, SQLAlchemy, Hypothesis for property tests)
- The frontend uses TypeScript (React, vitest, fast-check for property tests)
- Checkpoints ensure incremental validation at key integration boundaries
