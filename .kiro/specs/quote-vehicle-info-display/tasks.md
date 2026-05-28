# Implementation Plan: Quote Vehicle Info Display

## Overview

This plan implements WOF/COF expiry storage and display on quotes, and adds odometer + WOF/COF to the public share template. The quote model already has `vehicle_odometer`, the PDF template already renders it, and VehicleLiveSearch already returns `wof_expiry`/`cof_expiry`/`inspection_type`. The remaining work is: (1) add two new DB columns for WOF/COF expiry, (2) wire them through schemas and service, (3) update frontend form to pass them, (4) update rendering on all surfaces.

## Validated Assumptions (from code investigation)

- `vehicle_odometer` column ALREADY EXISTS on quotes table (migration 0005)
- PDF template (`quote.html`) ALREADY renders odometer conditionally
- `VehicleItem` schema ALREADY has `odometer` field
- `VehicleLiveSearch` ALREADY returns `wof_expiry`, `cof_expiry`, `inspection_type`
- `getInspectionLabel()` and `getInspectionExpiry()` helpers ALREADY exist in `@/utils/vehicleHelpers`
- Latest Alembic revision is `0198` (not 0194)
- `QuoteDetail.tsx` ALREADY has `vehicle_odometer` in its QuoteData interface

## Tasks

- [x] 1. Database migration and model changes
  - [x] 1.1 Create Alembic migration `0199` to add WOF/COF expiry columns to quotes table
    - Add `vehicle_wof_expiry DATE DEFAULT NULL` column
    - Add `vehicle_cof_expiry DATE DEFAULT NULL` column
    - Do NOT add vehicle_odometer (already exists)
    - Down revision: `0198`
    - Migration must be backwards-compatible (nullable columns, no data backfill)
    - _Requirements: 7.2, 7.3, 7.4, 7.5_

  - [x] 1.2 Update SQLAlchemy Quote model in `app/modules/quotes/models.py`
    - Add `vehicle_wof_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)`
    - Add `vehicle_cof_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)`
    - Place after existing `vehicle_year` column (near `vehicle_odometer` if it's there, or after vehicle_year)
    - Do NOT add vehicle_odometer (already exists — verify it's present)
    - _Requirements: 7.2, 7.3_

  - [x] 1.3 Update Pydantic schemas in `app/modules/quotes/schemas.py`
    - Add `vehicle_wof_expiry: date | None = None` and `vehicle_cof_expiry: date | None = None` to `QuoteCreate`
    - Add same fields to `QuoteUpdate`
    - Add same fields to `QuoteResponse`
    - Add `wof_expiry: str | None = None` and `cof_expiry: str | None = None` to `VehicleItem` schema (for additional vehicles)
    - Do NOT add vehicle_odometer to schemas (already exists — verify)
    - _Requirements: 2.1, 2.2, 2.4, 7.2, 7.3_

  - [x] 1.4 Update quote service layer in `app/modules/quotes/service.py`
    - Ensure `create_quote` and `update_quote` accept and store `vehicle_wof_expiry` and `vehicle_cof_expiry`
    - Include the fields in `_quote_to_dict` response helper
    - Verify `vehicle_odometer` is already handled (it should be)
    - After `db.flush()`, use `await db.refresh(quote)` before returning
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 2. Frontend form changes (QuoteCreate.tsx)
  - [x] 2.1 Update `frontend/src/pages/quotes/QuoteCreate.tsx` to pass WOF/COF expiry in API payload
    - Include `vehicle_wof_expiry` and `vehicle_cof_expiry` in the create/update API request body
    - Source values from the VehicleLiveSearch result (already available: `wof_expiry`, `cof_expiry` on the Vehicle interface)
    - Ensure values update when vehicle selection changes
    - Verify `vehicle_odometer` is already being passed (it should be from VehicleLiveSearch)
    - Use `?.` and `?? null` for safe access
    - _Requirements: 1.1, 2.1, 2.2, 2.3_

  - [x] 2.2 Update additional vehicles payload to include `wof_expiry` and `cof_expiry`
    - When building the `vehicles` array for the API payload, include `wof_expiry` and `cof_expiry` from each vehicle
    - The `VehicleItem` schema already has `odometer`; now also pass `wof_expiry` and `cof_expiry`
    - _Requirements: 6.1, 6.2_

- [x] 3. Frontend preview changes (QuoteDetail.tsx)
  - [x] 3.1 Update `frontend/src/pages/quotes/QuoteDetail.tsx` to display WOF/COF expiry for primary vehicle
    - Add WOF/COF expiry display after the existing odometer display
    - Use existing `getInspectionLabel()` and `getInspectionExpiry()` helpers from `@/utils/vehicleHelpers` if applicable, or format inline
    - Show label "WOF Expiry" or "COF Expiry" based on which field is populated (COF takes precedence)
    - Format date as DD Mon YYYY (NZ format)
    - Omit if no expiry date exists
    - Handle null/missing data with `?.` and `?? []`
    - _Requirements: 3.3, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1_

  - [x] 3.2 Update additional vehicles rendering in `QuoteDetail.tsx`
    - Add WOF/COF expiry display for each additional vehicle
    - Same formatting and conditional logic as primary vehicle
    - _Requirements: 6.1, 6.2, 6.3_

- [x] 4. PDF template changes
  - [x] 4.1 Update `app/templates/pdf/quote.html` to display WOF/COF expiry
    - Add WOF/COF expiry field after the existing odometer conditional block in the vehicle bar         `vehicle_cof_expiry` are included in the template context (they should be if `_quote_to_dict` is used)
    - Verify additional vehicles include `wof_expiry` and `cof_expiry` in the context
    - _Requirements: 4.5, 5.2_

- [x] 5. Public share template changes
  - [x] 5.1 Update `app/templates/pdf/quote_share.html` to display odometer and WOF/COF expiry
    - Add odometer display to the vehicle section (currently only shows rego/make/model/year)
    - Add WOF/COF expiry display after odometer
    - Use same formatting as PDF template: comma-separated number + " km" for odometer, DD Mon YYYY for dates
    - Omit fields with no value
    - Apply to additional vehicles if rendered in share template
    - _Requirements: 3.3, 4.5, 5.1, 5.2_

- [x] 6. Verify the fix
  - [x] 6.1 Run backend tests to confirm no regressions (`pytest tests/modules/quotes/ -x`)
  - [x] 6.2 Run TypeScript compilation (`npx tsc --noEmit` in frontend/) to confirm no type errors
  - [x] 6.3 Verify the quote PDF template renders correctly by checking template syntax

## Notes

- The `vehicle_odometer` column already exists on the quotes table — do NOT create a migration for it
- The PDF template already renders odometer — do NOT modify that block
- The latest Alembic revision is `0198`, so the new migration is `0199`
- VehicleLiveSearch already returns `wof_expiry`, `cof_expiry`, `inspection_type` — the data is available in the frontend
- Existing helpers `getInspectionLabel()` and `getInspectionExpiry()` in `@/utils/vehicleHelpers` can be reused
- The `QuoteDetail.tsx` Vehicle interface already has `wof_expiry`, `cof_expiry`, `odometer` fields
- Module gating (Requirement 8) is already handled by the existing vehicles module gate — no additional gating code needed
