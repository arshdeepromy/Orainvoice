# Implementation Plan: Kiosk Vehicle Check-In

## Overview

This plan implements the kiosk vehicle check-in feature in incremental steps: backend schemas and endpoints first (defining the contract), then frontend types and components, then integration wiring. Each task builds on the previous, ensuring no orphaned code. Property-based tests use Hypothesis (Python) and fast-check (TypeScript).

## Tasks

- [x] 1. Backend schemas for vehicle lookup and enhanced check-in
  - [x] 1.1 Add new Pydantic schemas to `app/modules/kiosk/schemas.py`
    - Add `KioskVehicleLookupRequest` with rego field (min_length=1, max_length=10) and `clean_rego` validator (strip + uppercase)
    - Add `KioskVehicleLookupResponse` with fields: id, rego, make, model, body_type, year, colour, wof_expiry, rego_expiry, odometer, source
    - Add `KioskCustomerMatch` with fields: id, first_name, last_name, phone, email
    - Add `KioskCustomerLookupResponse` with fields: items (list[KioskCustomerMatch]), total (int)
    - Add `KioskVehicleEntry` with global_vehicle_id (UUID-validated) and optional odometer_km
    - Add `KioskCheckInRequestV2` extending existing validation patterns (first_name, last_name, phone, email, vehicles list, existing_customer_id)
    - Add `KioskCheckInResponseV2` with customer_first_name, is_new_customer, vehicles_linked
    - _Requirements: 2.4, 6.2, 6.3, 7.1, 7.2, 7.3, 9.5_

  - [x] 1.2 Write property test for rego normalization (Hypothesis)
    - **Property 2: Registration input normalization**
    - For any string input, the cleaned rego equals input.strip().upper()
    - **Validates: Requirements 2.4**

- [x] 2. Backend vehicle lookup endpoint
  - [x] 2.1 Implement `lookup_vehicle_for_kiosk()` service function in `app/modules/kiosk/service.py`
    - Cascading lookup: org_vehicles → global_vehicles → CarJam API
    - On CarJam success, store result in global_vehicles (cache)
    - On CarJam not found, raise appropriate error (404)
    - Return `KioskVehicleLookupResponse`-compatible dict
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 2.2 Add `POST /kiosk/vehicle-lookup` route to `app/modules/kiosk/router.py`
    - Require "kiosk" role via `require_role("kiosk")`
    - Apply existing `_check_kiosk_rate_limit` dependency (30/min)
    - Accept `KioskVehicleLookupRequest` body, return `KioskVehicleLookupResponse`
    - Handle CarjamNotFoundError → 404, CarjamError → 502, rate limit → 429
    - _Requirements: 7.1, 7.4_

  - [x] 2.3 Write property test for vehicle lookup cache round-trip (Hypothesis)
    - **Property 3: Vehicle lookup cache round-trip**
    - For any valid vehicle data stored in global_vehicles, subsequent lookup returns cached data (source="cache") without CarJam call
    - **Validates: Requirements 3.4**

- [x] 3. Backend customer lookup endpoint
  - [x] 3.1 Implement `customer_lookup_for_kiosk()` service function in `app/modules/kiosk/service.py`
    - Query customers table by exact phone OR case-insensitive email within org
    - Return up to 5 matches with total count
    - Filter out anonymised customers
    - _Requirements: 9.1, 9.5, 9.7, 9.8_

  - [x] 3.2 Add `GET /kiosk/customer-lookup` route to `app/modules/kiosk/router.py`
    - Require "kiosk" role, apply kiosk rate limit
    - Accept query params: phone (optional), email (optional) — at least one required
    - Return `KioskCustomerLookupResponse`
    - Return 422 if neither phone nor email provided
    - _Requirements: 7.1, 9.5, 9.7_

  - [x] 3.3 Write property test for customer lookup matching semantics (Hypothesis)
    - **Property 10: Customer lookup matching semantics**
    - For any phone/email, returns all org customers matching exact phone OR case-insensitive email, and no others
    - **Validates: Requirements 9.5, 9.7**

- [x] 4. Backend enhanced check-in endpoint
  - [x] 4.1 Implement `kiosk_check_in_v2()` service function in `app/modules/kiosk/service.py`
    - Accept `KioskCheckInRequestV2` with vehicles list and optional existing_customer_id
    - If existing_customer_id provided, update that customer; otherwise lookup by phone or create new
    - Link each vehicle via `_ensure_vehicle_linked()` (idempotent)
    - Record odometer readings (source="kiosk") for vehicles with non-null odometer_km
    - Return `KioskCheckInResponseV2` with vehicles_linked count
    - Backward compatible: empty vehicles list behaves like current endpoint
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 9.5, 9.6_

  - [x] 4.2 Add enhanced `POST /kiosk/check-in` route (v2) to `app/modules/kiosk/router.py`
    - Accept `KioskCheckInRequestV2`, return `KioskCheckInResponseV2`
    - Maintain backward compatibility with existing check-in (empty vehicles list)
    - Same role and rate limit dependencies
    - _Requirements: 7.2, 7.3_

  - [x] 4.3 Write property test for vehicle linking count (Hypothesis)
    - **Property 6: Check-in links all confirmed vehicles**
    - For any valid customer data and N vehicles, exactly N CustomerVehicle links are created
    - **Validates: Requirements 6.1, 6.2, 7.3**

  - [x] 4.4 Write property test for odometer recording (Hypothesis)
    - **Property 7: Odometer recording for vehicles with readings**
    - For any vehicle entry with non-null odometer_km, an odometer_reading record is created with source="kiosk"
    - **Validates: Requirements 6.3**

  - [x] 4.5 Write property test for idempotent vehicle linking (Hypothesis)
    - **Property 8: Idempotent vehicle linking**
    - For any vehicle+customer pair, calling link multiple times results in exactly one CustomerVehicle record
    - **Validates: Requirements 6.4**

- [x] 5. Checkpoint — Backend complete
  - Ensure all backend tests pass, ask the user if questions arise.

- [x] 6. Frontend types and API client helpers
  - [x] 6.1 Create `frontend/src/pages/kiosk/types.ts` with shared TypeScript interfaces
    - `VehicleLookupResult`, `KioskVehicleEntry`, `KioskFormData`, `KioskSuccessData`
    - `AutoFillMatch`, `CheckInPayload`, `CheckInResponse`
    - Ensure field names match backend Pydantic schemas exactly
    - _Requirements: 4.1, 6.1, 9.3_

  - [x] 6.2 Create API helper functions for kiosk endpoints
    - `lookupVehicle(rego: string)` → POST /kiosk/vehicle-lookup
    - `lookupCustomer(params: { phone?: string; email?: string })` → GET /kiosk/customer-lookup
    - Apply safe API consumption patterns (optional chaining, nullish coalescing)
    - _Requirements: 3.1, 9.1_

- [x] 7. Frontend KioskRegoEntry component
  - [x] 7.1 Create `frontend/src/pages/kiosk/KioskRegoEntry.tsx`
    - Text input for rego with 48px min tap target, 18px font
    - "Confirm" button triggers vehicle lookup (strips whitespace, uppercases before submit)
    - "Skip" button navigates to customer details form
    - "Back" button returns to welcome screen
    - Loading state: disable Confirm button, show spinner during lookup
    - Validation: show error if rego is empty on Confirm tap
    - Display "X vehicles added" badge when vehicleCount > 0
    - Handle 404 (not found), 429 (rate limit), 5xx (generic error) responses
    - Use AbortController for cleanup
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.5, 3.6_

  - [x] 7.2 Write unit tests for KioskRegoEntry
    - Test rendering with correct styles and touch targets
    - Test Skip/Back/Confirm button behaviour
    - Test empty validation message display
    - Test loading state disables Confirm
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6_

- [x] 8. Frontend KioskVehicleSummary component
  - [x] 8.1 Create `frontend/src/pages/kiosk/KioskVehicleSummary.tsx`
    - Display vehicle details: body_type, make, model, wof_expiry, rego_expiry, last odometer
    - Only render non-null fields
    - Optional numeric input for "Current Kilometers" (odometer entry)
    - "Confirm" button accepts vehicle and calls onConfirm with odometer value
    - "Add Another Vehicle" button calls onAddAnother
    - "Back" button returns to rego entry
    - Display vehicle count badge
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.1, 5.4_

  - [x] 8.2 Write property test for vehicle summary display (fast-check)
    - **Property 4: Vehicle summary displays all available fields**
    - For any vehicle lookup result with non-null fields, rendered output contains each non-null value
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**

  - [x] 8.3 Write unit tests for KioskVehicleSummary
    - Test renders vehicle details correctly
    - Test odometer input accepts numbers
    - Test Confirm/Back/Add Another buttons
    - _Requirements: 4.6, 4.7, 4.8, 5.1_

- [x] 9. Enhanced KioskCheckInForm with auto-fill
  - [x] 9.1 Enhance `frontend/src/pages/kiosk/KioskCheckInForm.tsx` with customer auto-fill
    - Add debounced lookup (500ms) on phone and email fields using GET /kiosk/customer-lookup
    - Display auto-fill suggestion banner when match found ("We found your details — tap to auto-fill")
    - When multiple matches found, display selectable list
    - On tap, populate all non-null fields (first_name, last_name, phone, email) from matched record
    - Track selected existing_customer_id for submission
    - Allow editing pre-filled fields before submit
    - Update submit payload to include vehicles list and existing_customer_id
    - Use AbortController for debounced requests (cancel previous on new keystroke)
    - Silently ignore auto-fill lookup failures (form continues normally)
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8_

  - [x] 9.2 Write property test for auto-fill population (fast-check)
    - **Property 9: Auto-fill populates all non-null fields**
    - For any customer record, tapping auto-fill populates every non-null field into form state
    - **Validates: Requirements 9.3**

  - [x] 9.3 Write unit tests for KioskCheckInForm auto-fill
    - Test debounced lookup triggers after 500ms
    - Test auto-fill banner appears on match
    - Test multiple matches show list
    - Test form fields populated correctly
    - Test existing validation rules preserved
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.8_

- [x] 10. Enhanced KioskPage state machine
  - [x] 10.1 Enhance `frontend/src/pages/kiosk/KioskPage.tsx` with vehicle flow orchestration
    - Expand screen type: 'welcome' | 'rego' | 'vehicle-summary' | 'form' | 'success' | 'error'
    - Add session state: vehicles array, currentLookupResult, formData
    - Module-gated transition: welcome → rego (vehicles enabled) OR welcome → form (vehicles disabled)
    - Use ModuleContext to check if "vehicles" module is enabled
    - Wire KioskRegoEntry: onVehicleFound → set currentLookupResult, go to vehicle-summary
    - Wire KioskVehicleSummary: onConfirm → add to vehicles list, go to form; onAddAnother → go to rego
    - Wire KioskCheckInForm: pass vehicles list and formData, handle success/error
    - Preserve all state during navigation between screens (vehicles list + form data)
    - Clear all state on success screen completion or return to welcome
    - Replace CustomerCreateModal usage with inline KioskCheckInForm
    - _Requirements: 1.1, 1.2, 1.3, 5.2, 5.3, 5.5, 8.1, 8.2, 8.3, 8.4, 10.1, 10.2, 10.3_

  - [x] 10.2 Write property test for module-gated screen transition (fast-check)
    - **Property 1: Module-gated screen transition**
    - For any org config, "Check In" leads to rego screen iff vehicles module enabled, else form screen
    - **Validates: Requirements 1.1, 1.2**

  - [x] 10.3 Write property test for vehicle list accumulation (fast-check)
    - **Property 5: Vehicle list accumulation invariant**
    - For any sequence of N vehicle confirmations, session vehicle list contains exactly N entries
    - **Validates: Requirements 5.3, 5.4**

  - [x] 10.4 Write property test for session state preservation (fast-check)
    - **Property 11: Session state preservation during navigation**
    - For any accumulated state, navigating between screens preserves all confirmed vehicles and form data
    - **Validates: Requirements 10.1, 10.2**

- [x] 11. Checkpoint — Frontend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Integration tests
  - [x] 12.1 Write integration tests for POST /kiosk/vehicle-lookup
    - Test full cascade: org_vehicles → global_vehicles → CarJam (mocked)
    - Test 404 when vehicle not found anywhere
    - Test rate limiting (31st request returns 429)
    - Test role enforcement (non-kiosk role rejected)
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 7.1, 7.4_

  - [x] 12.2 Write integration tests for GET /kiosk/customer-lookup
    - Test phone match, email match (case-insensitive), no match, multiple matches
    - Test 422 when neither phone nor email provided
    - Test role enforcement
    - _Requirements: 9.5, 9.7, 9.8_

  - [x] 12.3 Write integration tests for enhanced POST /kiosk/check-in
    - Test new customer + vehicles linked
    - Test existing customer (existing_customer_id) + vehicles linked
    - Test no vehicles (backward compatibility with current endpoint)
    - Test odometer recording
    - Test idempotent linking (duplicate vehicle entries)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 7.2, 7.3, 9.5, 9.6_

- [x] 13. Final checkpoint — All tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Backend uses `db.flush()` + `db.refresh()` pattern (not `db.commit()`) per project conventions
- Frontend follows safe-api-consumption patterns: `?.` and `?? []` / `?? 0` on all API data
- Property tests use `@settings(max_examples=100)` (Hypothesis) and `fc.assert(property, { numRuns: 100 })` (fast-check)
- The enhanced check-in endpoint maintains full backward compatibility with the existing endpoint
