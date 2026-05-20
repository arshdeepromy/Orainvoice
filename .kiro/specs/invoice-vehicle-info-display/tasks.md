# Implementation Plan: Invoice Vehicle Info Display

## Overview

This plan implements standardised vehicle information display on invoices across all rendering surfaces. The work is split into: (1) shared utility functions for both frontend and backend, (2) backend schema/service changes to store vehicle display flags, (3) frontend form changes for field update detection and warnings, and (4) rendering integration across preview panel, PDF templates, HTML share, and POS receipt.

## Tasks

- [ ] 1. Create shared `buildVehicleDisplayFields` utility (TypeScript)
  - [x] 1.1 Create `frontend/src/utils/buildVehicleDisplayFields.ts` with the pure function
    - Define `VehicleDisplayData` and `VehicleDisplayField` interfaces
    - Implement display order: Registration → Vehicle → Odometer/Service Due → WOF/COF Expiry
    - Implement conditional logic: service_due_updated replaces odometer, WOF/COF conditional on flags + date comparison
    - Implement null omission: skip fields with no value
    - Implement backward compatibility: accept fallback fields when `vehicleDisplay` is null/undefined
    - Implement hint calculation: "or due at {odometer + 10000} km" when service_due_updated and odometer > 0
    - _Requirements: 1.1, 1.3, 2.1–2.7, 3.1–3.4_

  - [ ]* 1.2 Write property tests for `buildVehicleDisplayFields` (fast-check)
    - **Property 1: Display order with null omission**
    - **Property 2: Inspection expiry conditional visibility**
    - **Property 3: Service due date replaces odometer when updated**
    - **Property 4: Service due odometer hint calculation**
    - **Validates: Requirements 1.1, 1.3, 2.1–2.7, 3.1–3.4**

- [ ] 2. Create shared `build_vehicle_display_fields` utility (Python)
  - [x] 2.1 Create `app/modules/invoices/vehicle_display.py` with the Python equivalent
    - Mirror the TypeScript logic for use in PDF/HTML template rendering
    - Accept `vehicle_display` dict (from `invoice_data_json`) and `issue_date`
    - Return list of dicts with `label`, `value`, and optional `hint`
    - Handle backward compatibility with fallback fields
    - _Requirements: 1.1, 1.2, 1.3, 2.1–2.7, 3.1–3.4, 7.2–7.5_

  - [ ]* 2.2 Write property tests for `build_vehicle_display_fields` (Hypothesis)
    - **Property 1: Display order with null omission**
    - **Property 2: Inspection expiry conditional visibility**
    - **Property 3: Service due date replaces odometer when updated**
    - **Property 4: Service due odometer hint calculation**
    - **Validates: Requirements 1.1, 1.3, 2.1–2.7, 3.1–3.4**

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Backend schema and service changes
  - [x] 4.1 Add vehicle update flag fields to `InvoiceCreateRequest` schema
    - Add `vehicle_wof_updated: bool = False` to `app/modules/invoices/schemas.py`
    - Add `vehicle_cof_updated: bool = False`
    - Add `vehicle_service_due_updated: bool = False`
    - Add `vehicle_display: dict | None = None` to `InvoiceResponse`
    - _Requirements: 5.1–5.4, 6.1–6.4_

  - [x] 4.2 Update `create_invoice` service to store `vehicle_display` in `invoice_data_json`
    - In `app/modules/invoices/service.py`, after creating the invoice record, populate `invoice_data_json["vehicle_display"]` with snapshot values (rego, make, model, year, odometer, inspection_type, wof_expiry, cof_expiry, service_due_date) and update flags (wof_updated, cof_updated, service_due_updated)
    - Determine `inspection_type` from the vehicle record (check if COF vehicle or WOF vehicle)
    - Use `flag_modified` on `invoice_data_json` to ensure SQLAlchemy detects the JSONB change
    - _Requirements: 6.1, 6.2, 6.4_

  - [x] 4.3 Update `get_invoice` service to include `vehicle_display` in response
    - In `_invoice_to_dict()`, extract `vehicle_display` from `invoice_data_json` and include it in the response dict
    - _Requirements: 6.3_

  - [ ]* 4.4 Write property test for vehicle update flags storage round-trip
    - **Property 6: Vehicle update flags and values storage round-trip**
    - **Validates: Requirements 6.1, 6.4**

- [ ] 5. Frontend form changes — field update detection and warning
  - [x] 5.1 Add field update detection logic to `InvoiceCreate.tsx`
    - Store vehicle record's original WOF/COF/service_due values when vehicle is selected
    - Compute `wof_updated`, `cof_updated`, `service_due_updated` flags by comparing user-entered values against stored originals
    - Include flags in the API payload sent to backend
    - _Requirements: 5.1–5.4, 6.1_

  - [x] 5.2 Add service due date warning to `InvoiceCreate.tsx`
    - Below the service due date input, render amber warning text "Ensure you have updated the odometer reading too" when `isServiceDueDateChanged` is true
    - Compute `isServiceDueDateChanged` as: value is non-empty AND differs from vehicle record
    - Style: `text-xs text-amber-600 mt-1`
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ]* 5.3 Write property test for field update detection correctness (fast-check)
    - **Property 5: Field update detection correctness**
    - **Validates: Requirements 5.1–5.4**

  - [ ]* 5.4 Write property test for form warning visibility (fast-check)
    - **Property 7: Form warning shown iff service due date changed**
    - **Validates: Requirements 4.1, 4.2**

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Integrate vehicle display into preview panel (InvoiceList.tsx)
  - [x] 7.1 Update vehicle info card in `InvoiceList.tsx` split-panel to use `buildVehicleDisplayFields`
    - Import and call `buildVehicleDisplayFields` with `invoice.vehicle_display` and `invoice.issue_date`
    - Render the returned fields array as label/value pairs in the vehicle info card
    - Handle backward compatibility: pass fallback fields when `vehicle_display` is null
    - _Requirements: 1.1, 1.2, 1.3, 7.1_

- [ ] 8. Integrate vehicle display into PDF template
  - [x] 8.1 Update `app/templates/pdf/invoice.html` to use `build_vehicle_display_fields`
    - Pass `vehicle_display` from `invoice_data_json` and `issue_date` to the Python utility
    - Render the returned fields as a vehicle info bar with label/value layout
    - Handle backward compatibility: pass fallback vehicle fields for old invoices
    - _Requirements: 1.1, 1.2, 7.3, 7.4_

  - [x] 8.2 Update `app/templates/pdf/_invoice_base.html` and themed templates
    - Ensure the vehicle info section uses the same data structure from `build_vehicle_display_fields`
    - Apply consistent styling across all PDF themes
    - _Requirements: 7.5_

- [ ] 9. Integrate vehicle display into HTML share and POS receipt
  - [x] 9.1 Update `app/templates/pdf/invoice_share.html` to use `build_vehicle_display_fields`
    - Same rendering logic as PDF but with HTML-appropriate styling
    - _Requirements: 7.2_

  - [x] 9.2 Update POS receipt sidebar in `InvoiceList.tsx` to use `buildVehicleDisplayFields`
    - Adapt the display for narrower receipt format (compact labels, smaller text)
    - _Requirements: 7.6_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- No database migration is needed — uses existing `invoice_data_json` JSONB column
- The `buildVehicleDisplayFields` utility is implemented in both TypeScript (frontend) and Python (backend PDF rendering) with identical logic
- Backward compatibility is maintained: existing invoices without `vehicle_display` in their JSON render using the current fallback behaviour
- Each property test maps to a correctness property defined in the design document
- The vehicles module gate (`ModuleService.is_enabled`) already prevents vehicle data from being stored when the module is disabled — no additional gating needed in this feature
