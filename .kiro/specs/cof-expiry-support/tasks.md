# Implementation Plan: COF Expiry Support

## Overview

Add Certificate of Fitness (COF) expiry support alongside the existing Warrant of Fitness (WOF) system. Implementation follows the design layers: CarJam integration → database → schemas → services → frontend helpers → frontend display → tests. All changes are additive — no existing data is modified.

## Tasks

- [x] 1. CarJam integration — dataclass and parser
  - [x] 1.1 Add `cof_expiry` and `inspection_type` fields to `CarjamVehicleData` dataclass in `app/integrations/carjam.py`
    - Add `cof_expiry: str | None = None` field
    - Add `inspection_type: str | None = None` field
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 1.2 Implement `_derive_inspection_type()` helper function in `app/integrations/carjam.py`
    - Return `"cof"` if `subject_to_cof` uppercased equals "Y"
    - Return `"wof"` if `subject_to_wof` uppercased equals "Y" (and cof is not "Y")
    - Return `None` otherwise
    - _Requirements: 1.2, 1.3, 1.4_

  - [x] 1.3 Update `_parse_vehicle_response()` to map COF fields
    - Map `expiry_date_of_last_successful_cof` through `_timestamp_to_date` → `cof_expiry`
    - Call `_derive_inspection_type(data.get("subject_to_wof"), data.get("subject_to_cof"))` → `inspection_type`
    - Log warning if `expiry_date_of_last_successful_cof` is present but unparseable
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [ ]* 1.4 Write property tests for CarJam COF parsing (Hypothesis)
    - **Property 1: Inspection Type Derivation** — verify `_derive_inspection_type` returns correct value for all `(subject_to_wof, subject_to_cof)` combinations
    - **Property 2: COF Timestamp Parsing** — verify `_timestamp_to_date` returns valid ISO date for valid timestamps, null for invalid
    - Test file: `tests/test_carjam_cof.py`
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**

- [x] 2. Database migration and models
  - [x] 2.1 Create Alembic migration to add COF columns
    - `ALTER TABLE global_vehicles ADD COLUMN IF NOT EXISTS cof_expiry DATE`
    - `ALTER TABLE global_vehicles ADD COLUMN IF NOT EXISTS inspection_type VARCHAR(3)`
    - `ALTER TABLE org_vehicles ADD COLUMN IF NOT EXISTS cof_expiry DATE`
    - `ALTER TABLE org_vehicles ADD COLUMN IF NOT EXISTS inspection_type VARCHAR(3)`
    - Use `IF NOT EXISTS` for idempotency
    - After creating, run: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 10.1_

  - [x] 2.2 Add columns to `GlobalVehicle` model in `app/modules/admin/models.py`
    - `cof_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)`
    - `inspection_type: Mapped[str | None] = mapped_column(String(3), nullable=True)`
    - _Requirements: 2.1, 2.2_

  - [x] 2.3 Add columns to `OrgVehicle` model in `app/modules/vehicles/models.py`
    - `cof_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)`
    - `inspection_type: Mapped[str | None] = mapped_column(String(3), nullable=True)`
    - _Requirements: 2.3, 2.4_

- [x] 3. Backend schemas
  - [x] 3.1 Add `cof_expiry` and `inspection_type` fields to vehicle schemas in `app/modules/vehicles/schemas.py`
    - Add to: `VehicleLookupResponse`, `ManualVehicleCreate`, `ManualVehicleResponse`, `VehicleRefreshResponse`, `VehicleProfileResponse`, `VehicleSearchResult`
    - Fields: `cof_expiry: Optional[str] = Field(None)` and `inspection_type: Optional[str] = Field(None)`
    - _Requirements: 3.1, 3.2, 3.3, 3.6, 11.4_

  - [x] 3.2 Add `cof_expiry` and `inspection_type` fields to kiosk schema in `app/modules/kiosk/schemas.py`
    - Add to `KioskVehicleLookupResponse`
    - _Requirements: 3.4_

  - [x] 3.3 Add `vehicle_cof_expiry_date` field to invoice schema in `app/modules/invoices/schemas.py`
    - Add `vehicle_cof_expiry_date: date | None = Field(default=None)` to `InvoiceCreateRequest`
    - _Requirements: 4.1_

  - [x] 3.4 Add `cof_expiry` and `inspection_type` fields to portal schema in `app/modules/portal/schemas.py`
    - Add to `PortalVehicleItem`
    - _Requirements: 3.5_

  - [x] 3.5 Add `cof_expiry_reminder` template type to `app/modules/notifications/schemas.py`
    - Add to the list of valid notification template types
    - _Requirements: 5.1, 9.2_

- [x] 4. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Backend services — vehicle, kiosk, invoice, portal
  - [x] 5.1 Update vehicle service to map COF fields from CarJam data in `app/modules/vehicles/service.py`
    - In `_carjam_data_to_global_vehicle()`: map `cof_expiry` and `inspection_type`
    - In `_update_global_vehicle_from_carjam()`: update `cof_expiry` and `inspection_type`
    - In response dict builders: include `cof_expiry` (isoformat or None) and `inspection_type`
    - Use `db.flush()` not `db.commit()`
    - _Requirements: 2.5, 2.6, 10.4_

  - [x] 5.2 Update vehicle service manual creation to accept COF fields
    - In `create_manual_vehicle()`: accept and store `cof_expiry` and `inspection_type` from request
    - _Requirements: 3.6, 11.4_

  - [x] 5.3 Update kiosk service to include COF fields in `app/modules/kiosk/service.py`
    - In `lookup_vehicle_for_kiosk()`: include `cof_expiry` and `inspection_type` in response
    - _Requirements: 3.4_

  - [x] 5.4 Update invoice service to handle COF expiry in `app/modules/invoices/service.py`
    - In `create_invoice()`: if `vehicle_cof_expiry_date` is provided, update `cof_expiry` on both GlobalVehicle and OrgVehicle
    - Use `db.flush()` not `db.commit()`
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 5.5 Update portal service to include COF fields in `app/modules/portal/service.py`
    - In `get_customer_vehicles()`: include `cof_expiry` and `inspection_type` in `PortalVehicleItem`
    - _Requirements: 3.5_

  - [ ]* 5.6 Write property test for CarJam-to-vehicle mapping (Hypothesis)
    - **Property 3: CarJam-to-Vehicle Mapping Preserves All Expiry Fields**
    - Test file: `tests/test_vehicle_service_cof.py`
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 2.5, 2.6, 10.4**

- [x] 6. Backend services — notifications and dashboard
  - [x] 6.1 Add COF tuple to notification reminder loop in `app/modules/notifications/service.py`
    - Add `("COF", "cof_expiry", "cof_expiry_reminder")` to the expiry type loop
    - Ensure deduplication logic uses `(template_type, org_id, vehicle_id, expiry_date)` key
    - Skip if vehicle `cof_expiry` is null
    - Skip if org does not have `vehicles` module enabled
    - Skip if customer has COF reminders disabled
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.6, 9.3, 10.3_

  - [x] 6.2 Update dashboard service in `app/modules/organisations/dashboard_service.py`
    - Add `OR (gv.cof_expiry IS NOT NULL AND gv.cof_expiry >= :today AND gv.cof_expiry <= :cof_cutoff)` to expiry query
    - Add COF expiry items with `expiry_type: "cof"` label
    - When vehicle has both wof_expiry and cof_expiry, display the one matching `inspection_type`
    - _Requirements: 6.1, 6.2, 6.3_

  - [ ]* 6.3 Write property tests for notifications COF (Hypothesis)
    - **Property 6: Notification Dedup Key Uniqueness** — distinct tuples produce different dedup strings, identical tuples produce same
    - **Property 7: Notification Template Variables Completeness** — COF reminder template variables contain rego, make, model, expiry_date
    - Test file: `tests/test_notifications_cof.py`
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 5.3, 5.5**

  - [ ]* 6.4 Write property test for dashboard COF labeling (Hypothesis)
    - **Property 8: Dashboard Expiry Type Labeling** — items from cof_expiry get label "cof", items from wof_expiry get label "wof"
    - Test file: `tests/test_dashboard_cof.py`
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 6.2, 6.3**

- [x] 7. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Frontend helper functions and types
  - [x] 8.1 Create `frontend/src/utils/vehicleHelpers.ts` with shared helper functions
    - Implement `getInspectionLabel(vehicle)`: returns `"COF Expiry"` when `inspection_type === 'cof'`, else `"WOF Expiry"`
    - Implement `getInspectionExpiry(vehicle)`: returns `cof_expiry` when `inspection_type === 'cof'`, else `wof_expiry`; returns `null` if selected field is undefined
    - Use `?.` and `?? null` for safe access
    - _Requirements: 7.1, 7.8, 8.1, 8.2, 8.3_

  - [ ]* 8.2 Write property tests for frontend helpers (fast-check + Vitest)
    - **Property 4: getInspectionLabel Returns Correct Label** — returns "COF Expiry" for "cof", "WOF Expiry" for all other values
    - **Property 5: getInspectionExpiry Returns Correct Date** — returns cof_expiry for "cof", wof_expiry otherwise; null if undefined
    - Test file: `frontend/src/utils/vehicleHelpers.test.ts`
    - Use `fc.assert(property, { numRuns: 100 })`
    - **Validates: Requirements 7.1, 7.8, 8.1, 8.2**

  - [x] 8.3 Add `cof_expiry` and `inspection_type` to frontend type interfaces
    - Update `frontend/src/pages/kiosk/types.ts` — add to `VehicleLookupResult`
    - Update vehicle interfaces in `VehicleLiveSearch.tsx`, `VehicleList.tsx`, `InvoiceCreate.tsx`
    - All new fields typed as `string | null`
    - _Requirements: 3.4, 7.1, 8.3_

- [x] 9. Frontend display components — dynamic labels
  - [x] 9.1 Update `frontend/src/pages/kiosk/KioskVehicleSummary.tsx`
    - Import and use `getInspectionLabel` and `getInspectionExpiry` from vehicleHelpers
    - Replace hardcoded "WOF Expiry" label with dynamic label
    - Display correct expiry date based on inspection type
    - _Requirements: 7.3, 8.1, 8.2_

  - [x] 9.2 Update `frontend/src/pages/vehicles/VehicleProfile.tsx`
    - Use `getInspectionLabel` and `getInspectionExpiry` for the expiry badge/display
    - _Requirements: 7.1, 8.1, 8.2_

  - [x] 9.3 Update `frontend/src/pages/vehicles/VehicleList.tsx` — list display and manual creation form
    - Replace "WOF" column header with dynamic label using helper
    - Add inspection type selector (WOF/COF) to manual vehicle creation form
    - Show dynamic expiry date input (COF Expiry or WOF Expiry) based on selection
    - Add `inspection_type` and `cof_expiry` to manual form state (default: "wof")
    - Update payload to send `cof_expiry` and `inspection_type` when COF selected
    - _Requirements: 7.2, 8.1, 8.2, 11.1, 11.2, 11.3_

  - [x] 9.4 Update `frontend/src/components/vehicles/VehicleLiveSearch.tsx`
    - Use `getInspectionLabel` and `getInspectionExpiry` in search result summary
    - _Requirements: 7.7, 8.1, 8.2_

  - [x] 9.5 Update `frontend/src/pages/invoices/InvoiceCreate.tsx`
    - Use dynamic label for expiry input field
    - Handle both WOF and COF expiry updates based on `inspection_type`
    - Send `vehicle_cof_expiry_date` in invoice creation payload when vehicle is COF type
    - _Requirements: 7.4, 8.1, 8.2, 4.1_

  - [x] 9.6 Update `frontend/src/pages/invoices/InvoiceDetail.tsx`
    - Use `getInspectionLabel` and `getInspectionExpiry` for vehicle card display
    - _Requirements: 7.5, 8.1, 8.2_

  - [x] 9.7 Update `frontend/src/pages/invoices/InvoiceList.tsx`
    - Use `getInspectionLabel` and `getInspectionExpiry` for vehicle details in list
    - _Requirements: 7.5, 8.1, 8.2_

  - [x] 9.8 Update `frontend/src/pages/portal/VehicleHistory.tsx`
    - Use `getInspectionLabel` and `getInspectionExpiry` for portal vehicle badge
    - _Requirements: 7.6, 8.1, 8.2_

  - [x] 9.9 Update `frontend/src/pages/customers/CustomerProfile.tsx`
    - Add COF expiry reminder toggle section (shown when customer has COF vehicles)
    - Add `cof_expiry` to `CustomerReminderConfig` and `VehicleExpiryData` interfaces
    - _Requirements: 9.1, 9.2, 9.3_

  - [x] 9.10 Update `frontend/src/pages/customers/CustomerList.tsx`
    - Add COF reminder toggle alongside existing WOF toggle in reminder column
    - _Requirements: 9.1_

  - [x] 9.11 Update `frontend/src/pages/data/JsonBulkImport.tsx`
    - Add "COF Expiry" and "Inspection Type" columns to vehicle import preview table
    - Display `cof_expiry` and `inspection_type` values from import data
    - Fields pass through to backend automatically via existing JSON payload
    - _Requirements: 12.1, 12.2_

  - [x] 9.12 Rebuild frontend container
    - Run: `docker compose -f docker-compose.yml -f docker-compose.dev.yml restart frontend`
    - _Requirements: all frontend requirements_

- [x] 10. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 11. Integration tests
  - [ ]* 11.1 Write integration test: CarJam lookup stores COF data
    - Full flow: CarJam response with COF data → stored in global_vehicles with correct cof_expiry and inspection_type
    - Test file: `tests/test_cof_integration.py`
    - _Requirements: 1.1, 2.5_

  - [ ]* 11.2 Write integration test: Invoice creation updates COF expiry
    - Invoice with `vehicle_cof_expiry_date` updates both global and org vehicle records
    - _Requirements: 4.2, 4.3_

  - [ ]* 11.3 Write integration test: Dashboard includes COF vehicles
    - Vehicles with upcoming cof_expiry appear in dashboard widget with correct label
    - _Requirements: 6.1, 6.2_

  - [ ]* 11.4 Write integration test: COF notification generation
    - COF expiry matching lead time generates reminder; disabled preferences skip
    - _Requirements: 5.2, 9.3_

  - [ ]* 11.5 Write integration test: Bulk import with COF data
    - JSON import stores cof_expiry and inspection_type on vehicle records
    - _Requirements: 12.1, 12.2_

- [x] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Git push and rebuild local dev environment
  - [x] 13.1 Git commit and push all changes to a new branch
    - Stage all changed files: `git add -A`
    - Commit with message: `feat: add COF expiry support alongside WOF`
    - Push to new branch: `git push -u origin feat/cof-expiry-support`
  - [x] 13.2 Rebuild backend container with new migration
    - Run: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --force-recreate app`
    - Verify migration applied: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head`
  - [x] 13.3 Rebuild frontend Vite inside the container
    - Run: `docker compose -f docker-compose.yml -f docker-compose.dev.yml restart frontend`
    - Verify build succeeded: `docker compose -f docker-compose.yml -f docker-compose.dev.yml logs frontend --tail 20`

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Backend uses `db.flush()` not `db.commit()` in services
- Frontend must use `?.` and `?? []` / `?? null` on all API data
- Database migration must use `IF NOT EXISTS` for idempotency
- Property tests: backend uses `@settings(max_examples=100)` (Hypothesis), frontend uses `fc.assert(property, { numRuns: 100 })` (fast-check)
