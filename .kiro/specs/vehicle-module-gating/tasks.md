# Implementation Plan: Vehicle Module Gating

## Overview

Gate all vehicle/CarJam functionality behind the `vehicles` module slug using the existing module system. The implementation follows a backend-first approach: register the module, add middleware gating, modify services to respect module state, then gate frontend UI and payloads. Property tests validate each gating layer.

## Tasks

- [x] 1. Register vehicles module and add middleware gating
  - [x] 1.1 Create Alembic migration to register vehicles module
    - Create `alembic/versions/2026_03_11_0900-0076_register_vehicles_module.py`
    - Insert row into `module_registry` with slug `vehicles`, display_name `Vehicles`, category `automotive`, is_core `false`, dependencies `[]`, status `available`
    - Use `INSERT ... ON CONFLICT ON CONSTRAINT uq_module_registry_slug DO NOTHING` for idempotency
    - Follow the exact pattern from migration `0068`
    - _Requirements: 1.1, 1.2_

  - [x] 1.2 Add `/api/v1/vehicles` to MODULE_ENDPOINT_MAP in middleware
    - Edit `app/middleware/modules.py`
    - Add entry `"/api/v1/vehicles": "vehicles"` to `MODULE_ENDPOINT_MAP`
    - This gates all `/api/v1/vehicles/*` endpoints automatically via the existing middleware
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 1.3 Verify `vehicles` is NOT in CORE_MODULES
    - Confirm `app/core/modules.py` does not include `vehicles` in the `CORE_MODULES` set
    - No code change expected — just verification
    - _Requirements: 1.3_

  - [x]* 1.4 Write property test for migration idempotency
    - **Property 1: Migration idempotency**
    - **Validates: Requirements 1.1, 1.2**
    - Add test to `tests/properties/test_module_properties.py` (or new file `tests/properties/test_vehicle_module_gating_properties.py`)
    - Use `hypothesis` to verify that after N ≥ 1 executions, exactly one `vehicles` row exists with correct field values

  - [x]* 1.5 Write property test for vehicle path resolution completeness
    - **Property 2: Vehicle path resolution completeness**
    - **Validates: Requirements 2.1, 2.4**
    - Test that `_resolve_module()` returns `'vehicles'` for all known vehicle endpoint paths (lookup, lookup-with-fallback, search, manual entry, link, refresh, vehicle profile, odometer recording, odometer history, odometer update)

  - [x]* 1.6 Write property test for vehicle endpoint access gating
    - **Property 3: Vehicle endpoint access gating**
    - **Validates: Requirements 2.2, 2.3**
    - Test that middleware returns 403 when module disabled and passes through when enabled, for any vehicle endpoint path and organisation

- [x] 2. Checkpoint - Ensure migration and middleware gating work
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Gate vehicle fields in invoice and customer services
  - [x] 3.1 Add vehicles module check to invoice creation
    - Edit `app/modules/invoices/service.py` — `create_invoice()` function
    - Import `ModuleService` from `app.core.modules`
    - Early in the function, check `await module_svc.is_enabled(str(org_id), "vehicles")`
    - When disabled: set `vehicle_rego`, `vehicle_make`, `vehicle_model`, `vehicle_year`, `vehicle_odometer`, `global_vehicle_id` all to `None`
    - Existing guards (`if global_vehicle_id:`, `if vehicle_odometer and ... and global_vehicle_id:`) naturally skip auto-linking and odometer recording
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 3.2 Add vehicles module check to customer search
    - Edit `app/modules/customers/service.py` — `search_customers()` function
    - Import `ModuleService` from `app.core.modules`
    - When `vehicles` module is disabled, override `include_vehicles` to `False`
    - This prevents linked_vehicles query and data leakage
    - _Requirements: 6.1, 6.2_

  - [x]* 3.3 Write property test for invoice creation vehicle field gating
    - **Property 4: Invoice creation vehicle field gating**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    - Use `hypothesis` to generate arbitrary vehicle parameters; verify all six fields are NULL when module disabled, and stored as provided when enabled

  - [x]* 3.4 Write property test for customer search linked_vehicles gating
    - **Property 5: Customer search linked_vehicles gating**
    - **Validates: Requirements 6.1, 6.2**
    - Verify that with `include_vehicles=true`, results contain no linked_vehicles when module disabled, and contain them when enabled

- [x] 4. Checkpoint - Ensure backend service gating works
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Verify PDF templates handle missing vehicle data
  - [x] 5.1 Verify PDF template conditional rendering
    - Review `app/templates/pdf/invoice.html` and `app/templates/pdf/invoice_share.html`
    - Confirm both templates already guard the vehicle section with `{% if v or invoice.vehicle_rego %}`
    - No code changes expected per design — backend nulling is sufficient
    - If guard is missing or incorrect, add/fix the conditional
    - _Requirements: 7.1, 7.2, 7.3_

  - [x]* 5.2 Write property test for PDF template vehicle section conditional rendering
    - **Property 6: PDF template vehicle section conditional rendering**
    - **Validates: Requirements 7.1, 7.2, 7.3**
    - Use `hypothesis` to generate invoice records with and without `vehicle_rego`; verify rendered HTML contains/omits vehicle bar markup accordingly

- [x] 6. Gate frontend vehicle UI in invoice pages
  - [x] 6.1 Gate vehicle UI in InvoiceCreate
    - Edit `frontend/src/pages/invoices/InvoiceCreate.tsx`
    - Import `ModuleGate` from `@/components/common/ModuleGate` and `useModules` from module context
    - Wrap the entire vehicle search section (VehicleLiveSearch, vehicle cards, odometer inputs) with `<ModuleGate module="vehicles">`
    - Gate `buildPayload` to omit vehicle fields (`vehicle_rego`, `vehicle_make`, `vehicle_model`, `vehicle_year`, `vehicle_odometer`, `global_vehicle_id`, `vehicles`) when `isEnabled('vehicles')` is false
    - Gate `onVehicleAutoSelect` callback in CustomerSearch to be a no-op when disabled
    - _Requirements: 4.1, 4.2, 4.3, 8.1, 8.2_

  - [x] 6.2 Gate vehicle UI in InvoiceList
    - Edit `frontend/src/pages/invoices/InvoiceList.tsx`
    - Import `ModuleGate` from `@/components/common/ModuleGate`
    - Wrap the vehicle info card section with `<ModuleGate module="vehicles">`
    - _Requirements: 5.1, 5.3_

  - [x] 6.3 Gate vehicle UI in InvoiceDetail
    - Edit `frontend/src/pages/invoices/InvoiceDetail.tsx`
    - Import `ModuleGate` from `@/components/common/ModuleGate`
    - Wrap the vehicle display section with `<ModuleGate module="vehicles">`
    - _Requirements: 5.2, 5.3_

  - [x]* 6.4 Write property test for frontend vehicle UI visibility
    - **Property 7: Frontend vehicle UI visibility**
    - **Validates: Requirements 4.1, 4.2, 5.1, 5.2, 5.3**
    - Use `fast-check` to verify InvoiceCreate, InvoiceList, and InvoiceDetail do not render vehicle UI sections when module disabled, and do render them when enabled

  - [x]* 6.5 Write property test for frontend payload field omission
    - **Property 8: Frontend payload omits vehicle fields when disabled**
    - **Validates: Requirements 4.3**
    - Use `fast-check` to verify `buildPayload` output never contains vehicle keys when `vehiclesEnabled` is false

- [x] 7. Gate frontend customer search vehicle inclusion
  - [x] 7.1 Gate customer search include_vehicles parameter
    - Edit the customer search component/hook to check `isEnabled('vehicles')` before adding `include_vehicles=true` to the API request
    - When module disabled, omit the `include_vehicles` query parameter
    - _Requirements: 8.3_

  - [x]* 7.2 Write property test for customer search API vehicle inclusion
    - **Property 9: Customer search API omits vehicle inclusion when disabled**
    - **Validates: Requirements 8.3**
    - Use `fast-check` to verify customer search API calls do not include `include_vehicles=true` when module disabled

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation after backend and frontend phases
- Property tests validate universal correctness properties from the design document
- PDF templates require no changes per design — backend nulling handles the gating
- The middleware approach avoids modifying the vehicle router directly
