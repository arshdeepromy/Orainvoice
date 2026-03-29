# Implementation Plan: Parts Packaging & Pricing

## Overview

Extend the Parts Catalogue with packaging and pricing fields to match the Fluids/Oils catalogue. Implementation proceeds bottom-up: Alembic migration → ORM model → schemas → service logic → router validation → frontend pricing UI → tests → build verification.

## Tasks

- [x] 1. Database migration and ORM model
  - [x] 1.1 Create Alembic migration `alembic/versions/2026_03_28_0900-0116_parts_packaging_pricing.py`
    - Revision `"0116"`, down_revision `"0115"`
    - `op.add_column()` for all 9 new nullable columns: `purchase_price` Numeric(12,2), `packaging_type` String(20), `qty_per_pack` Integer, `total_packs` Integer, `cost_per_unit` Numeric(12,4), `sell_price_per_unit` Numeric(12,4), `margin` Numeric(12,4), `margin_pct` Numeric(8,2), `gst_mode` String(10)
    - Data migration via `op.execute()`: map `gst_mode` from legacy booleans (`is_gst_exempt=true` → `'exempt'`, `is_gst_exempt=false AND gst_inclusive=true` → `'inclusive'`, both false → `'exclusive'`), copy `default_price` → `sell_price_per_unit`, set `packaging_type='single'`, `qty_per_pack=1`, `total_packs=1` for all existing rows
    - Downgrade: `op.drop_column()` for all 9 columns
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [x] 1.2 Add 9 `mapped_column` entries to `PartsCatalogue` in `app/modules/catalogue/models.py`
    - Add `purchase_price`, `packaging_type`, `qty_per_pack`, `total_packs`, `cost_per_unit`, `sell_price_per_unit`, `margin`, `margin_pct`, `gst_mode` as nullable mapped columns matching the migration column types
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9_


- [x] 2. Schema and service layer
  - [x] 2.1 Update `app/modules/catalogue/schemas.py` with new pricing fields
    - Add 6 optional fields to `PartCreateRequest`: `purchase_price`, `packaging_type`, `qty_per_pack` (ge=1), `total_packs` (ge=1), `sell_price_per_unit`, `gst_mode`
    - Add 9 optional fields to `PartResponse`: `purchase_price`, `packaging_type`, `qty_per_pack`, `total_packs`, `cost_per_unit`, `sell_price_per_unit`, `margin`, `margin_pct`, `gst_mode`
    - Retain legacy fields (`is_gst_exempt`, `gst_inclusive`, `default_price`) for backward compatibility
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 2.2 Implement `_compute_pricing()` helper and update service in `app/modules/catalogue/service.py`
    - Add `_compute_pricing(purchase_price, qty_per_pack, total_packs, sell_price_per_unit)` returning `(cost_per_unit, margin, margin_pct)`
    - When all three inputs are positive: `cost_per_unit = purchase_price / (qty_per_pack × total_packs)`
    - When `sell_price_per_unit` and `cost_per_unit` are both available: `margin = sell_price_per_unit - cost_per_unit`, `margin_pct = (margin / sell_price_per_unit) × 100` (or `0.00` when sell is zero)
    - Return `None` for derived fields when inputs are missing or invalid
    - Update `create_part()` to accept new kwargs, call `_compute_pricing()`, and persist all pricing fields
    - Update `_part_to_dict()` to include all 9 new fields, converting Decimals to strings
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 7.4_

  - [x] 2.3 Write property tests for cost and margin calculations (Properties 1-2)
    - **Property 1: Cost-per-unit calculation** — for any positive purchase_price, qty_per_pack, total_packs: `cost_per_unit == purchase_price / (qty_per_pack × total_packs)`; for zero/None inputs: `cost_per_unit is None`
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
    - **Property 2: Margin computation** — for any non-negative sell and cost: `margin == sell - cost`, `margin_pct == (margin / sell) × 100` when sell > 0, `margin_pct == 0.00` when sell is zero, both None when cost is None
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    - Create `tests/properties/test_parts_pricing_properties.py` using Hypothesis

  - [x] 2.4 Write unit tests for `_compute_pricing()` edge cases
    - Test known values: purchase_price=100, qty_per_pack=10, total_packs=2 → cost_per_unit=5.00
    - Test zero qty_per_pack → None, zero total_packs → None, None purchase_price → None
    - Test margin with sell=10, cost=5 → margin=5, margin_pct=50
    - Test sell_price_per_unit=0 → margin_pct=0.00
    - Create in `tests/test_parts_pricing.py`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4_

- [x] 3. Checkpoint — Verify migration, model, schemas, and service logic
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Router validation and API endpoints
  - [x] 4.1 Update `create_part_endpoint()` in `app/modules/catalogue/router.py`
    - Pass new fields from `PartCreateRequest` to `create_part()` service call
    - Add validation: reject `packaging_type` not in `{box, carton, pack, bag, pallet, single}` with 422
    - Add validation: reject non-positive `qty_per_pack` or `total_packs` with 422 and descriptive message
    - _Requirements: 7.1, 7.5, 7.6_

  - [x] 4.2 Update `update_part_endpoint()` in `app/modules/catalogue/router.py`
    - Extend body field handling to include all new pricing fields
    - Recalculate derived fields server-side via `_compute_pricing()` before flush
    - Add same packaging_type and qty/packs validation as create endpoint
    - _Requirements: 7.2, 7.4, 7.5, 7.6_

  - [x] 4.3 Write property tests for API validation (Properties 5, 8)
    - **Property 5: Positive integer validation** — for any integer ≤ 0 as qty_per_pack or total_packs, API returns 422; for any positive integer, API accepts
    - **Validates: Requirements 5.4, 5.5, 7.5**
    - **Property 8: Invalid packaging type rejection** — for any string not in allowed set, API returns 422
    - **Validates: Requirements 7.6**
    - Add to `tests/properties/test_parts_pricing_properties.py`

  - [x] 4.4 Write unit tests for API create/update endpoints
    - Test create with all new fields → verify response includes all 9 pricing fields
    - Test update with partial pricing fields → verify only updated fields change
    - Test create with invalid packaging_type → 422
    - Test create with qty_per_pack=0 → 422
    - Add to `tests/test_parts_pricing.py`
    - _Requirements: 7.1, 7.2, 7.3, 7.5, 7.6_

- [x] 5. Checkpoint — Verify API endpoints and validation
  - Ensure all tests pass, ask the user if questions arise.


- [x] 6. GST mode consolidation and legacy mapping
  - [x] 6.1 Ensure GST legacy boolean mapping works at runtime in service/router layers
    - When loading existing parts with legacy `is_gst_exempt`/`gst_inclusive` booleans and no `gst_mode`, map to equivalent gst_mode value in `_part_to_dict()`
    - `is_gst_exempt=true` → `"exempt"`, `is_gst_exempt=false AND gst_inclusive=true` → `"inclusive"`, both false → `"exclusive"`
    - _Requirements: 4.3, 4.4, 4.5, 4.6_

  - [x] 6.2 Write property test for GST legacy mapping (Property 4)
    - **Property 4: GST legacy boolean mapping** — for any (is_gst_exempt, gst_inclusive) boolean pair, mapping produces correct gst_mode string; mapping is total over the boolean domain
    - **Validates: Requirements 4.3, 4.4, 4.5, 4.6, 8.2**
    - Add to `tests/properties/test_parts_pricing_properties.py`

  - [x] 6.3 Write unit tests for GST mapping
    - Test (True, False) → "exempt", (False, True) → "inclusive", (False, False) → "exclusive"
    - Add to `tests/test_parts_pricing.py`
    - _Requirements: 4.3, 4.4, 4.5, 4.6_

- [x] 7. Frontend — Pricing section UI in PartsCatalogue.tsx
  - [x] 7.1 Update `PartForm` interface and `EMPTY_FORM` defaults in `frontend/src/pages/catalogue/PartsCatalogue.tsx`
    - Add fields: `purchase_price: string`, `packaging_type: string`, `qty_per_pack: string`, `total_packs: string`, `sell_price_per_unit: string`
    - Set EMPTY_FORM defaults: `packaging_type: 'single'`, `qty_per_pack: '1'`, `total_packs: '1'`, others empty string
    - _Requirements: 6.1, 6.2_

  - [x] 7.2 Add pricing section UI to the form modal
    - Packaging Type: `<select>` with options box, carton, pack, bag, pallet, single
    - Qty Per Pack and Total Packs: `<Input type="number">` (disabled when packaging_type is "single")
    - Purchase Price and Sell Price Per Unit: `<Input type="number" step="0.01">`
    - GST Mode: segmented toggle with "GST Inc." / "GST Excl." / "Exempt"
    - Read-only calculated displays: Cost/Unit, Margin $, Margin %
    - When packaging_type is "single", auto-set qty_per_pack to "1" and total_packs to "1"
    - _Requirements: 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.6_

  - [x] 7.3 Implement real-time pricing calculations in the frontend
    - `totalUnits = parseInt(qty_per_pack) * parseInt(total_packs)`
    - `costPerUnit = totalUnits > 0 ? parseFloat(purchase_price) / totalUnits : 0`
    - `margin = sellPerUnit - costPerUnit`, `marginPct = sellPerUnit > 0 ? (margin / sellPerUnit) * 100 : 0`
    - Display dashes (`—`) when insufficient data, not `$0.00`
    - Format currency values as NZD (e.g., `$12.50`)
    - Use labels: "Cost/Unit", "Margin $", "Margin %"
    - _Requirements: 2.5, 3.5, 3.6, 3.7, 6.3, 6.4, 6.5, 6.6_

  - [x] 7.4 Wire form submission to include new pricing fields in API payload
    - Include `purchase_price`, `packaging_type`, `qty_per_pack`, `total_packs`, `sell_price_per_unit`, `gst_mode` in POST/PUT requests
    - Map API response fields back into form state on load/edit
    - _Requirements: 7.1, 7.2, 7.3_

- [x] 8. Remaining property and integration tests
  - [x] 8.1 Write property test for currency formatting (Property 3)
    - **Property 3: Currency formatting** — for any numeric value, NZD format produces string matching `$X.XX` pattern
    - **Validates: Requirements 3.6, 3.7, 6.4**
    - Add to `tests/properties/test_parts_pricing_properties.py`

  - [x] 8.2 Write property test for API round-trip (Property 6)
    - **Property 6: API pricing fields round-trip** — create part with valid pricing payload, retrieve it, verify all submitted fields returned with original values plus computed derived fields
    - **Validates: Requirements 7.1, 7.2, 7.3**
    - Add to `tests/properties/test_parts_pricing_properties.py`

  - [x] 8.3 Write property test for server-side derived field consistency (Property 7)
    - **Property 7: Server-side derived field consistency** — for any valid inputs, persisted cost_per_unit, margin, margin_pct match the formulas exactly
    - **Validates: Requirements 7.4**
    - Add to `tests/properties/test_parts_pricing_properties.py`

  - [x] 8.4 Write property test for migration data transformation (Property 9)
    - **Property 9: Migration data transformation** — after migration, existing rows have sell_price_per_unit == default_price, packaging_type == 'single', qty_per_pack == 1, total_packs == 1
    - **Validates: Requirements 8.3, 8.4, 8.6**
    - Add to `tests/properties/test_parts_pricing_properties.py`

- [x] 9. Final checkpoint — Build & verify
  - Run `docker build` to verify the full application builds successfully
  - Run `getDiagnostics` on all modified files to check for type/lint errors
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests validate universal correctness properties from the design document (Properties 1-9)
- The backend uses Python (FastAPI, SQLAlchemy, Hypothesis for property tests)
- The frontend uses TypeScript (React)
- Checkpoints ensure incremental validation at key integration boundaries
