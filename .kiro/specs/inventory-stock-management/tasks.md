# Implementation Plan: Inventory Stock Management

## Overview

Bottom-up implementation: Alembic migration → SQLAlchemy model → Pydantic schemas → service layer → API router → frontend components → refactored StockLevels page. Each task builds incrementally so the feature is wirable at every stage.

## Tasks

- [x] 1. Database migration and model layer
  - [x] 1.1 Create Alembic migration for `stock_items` table and `stock_movements.stock_item_id` column
    - Create `alembic/versions/2026_03_29_0900-0117_create_stock_items.py`
    - Define `stock_items` table with columns: `id`, `org_id`, `catalogue_item_id`, `catalogue_type`, `current_quantity`, `min_threshold`, `reorder_quantity`, `supplier_id`, `barcode`, `created_by`, `created_at`, `updated_at`
    - Add CHECK constraint on `catalogue_type IN ('part', 'tyre', 'fluid')`
    - Add UNIQUE constraint `uq_stock_items_org_catalogue` on `(org_id, catalogue_item_id, catalogue_type)`
    - Add indexes: `idx_stock_items_org` on `org_id`, `idx_stock_items_barcode` partial index on `barcode WHERE barcode IS NOT NULL`
    - Add `stock_item_id UUID REFERENCES stock_items(id)` nullable column to `stock_movements`
    - Add partial index `idx_stock_movements_stock_item` on `stock_movements(stock_item_id) WHERE stock_item_id IS NOT NULL`
    - Include downgrade to drop column and table
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 1.2 Create `StockItem` SQLAlchemy model in `app/modules/inventory/models.py`
    - Add `StockItem` class mapped to `stock_items` table with all columns, FKs, and constraints matching the migration
    - Add `UniqueConstraint` and `CheckConstraint` in `__table_args__`
    - Add relationship to existing `StockMovement` model if present, or add `stock_item_id` mapped column to `StockMovement`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

- [x] 2. Pydantic schemas
  - [x] 2.1 Create stock item schemas in `app/modules/inventory/stock_items_schemas.py`
    - `CreateStockItemRequest`: `catalogue_item_id`, `catalogue_type` (Literal["part","tyre","fluid"]), `quantity` (gt=0), `reason` (min_length=1), optional `barcode`, optional `supplier_id`
    - `UpdateStockItemRequest`: optional `barcode`, `supplier_id`, `min_threshold` (ge=0), `reorder_quantity` (ge=0)
    - `StockItemResponse`: full stock item with joined catalogue fields (`item_name`, `part_number`, `brand`, `is_below_threshold`, `supplier_name`, `barcode`)
    - `StockItemListResponse`: `stock_items: list[StockItemResponse]`, `total: int`
    - _Requirements: 5.2, 5.3, 5.4, 7.1, 9.3, 9.4, 9.5, 10.5_

- [x] 3. Service layer
  - [x] 3.1 Create stock items service in `app/modules/inventory/stock_items_service.py`
    - Implement `_resolve_catalogue_query(catalogue_type, catalogue_item_id)` helper that maps `part`/`tyre` → `parts_catalogue` and `fluid` → `fluid_oil_products`
    - Implement `list_stock_items(db, org_id, search, below_threshold_only, limit, offset)` — query `stock_items` joined to catalogue tables for display fields; support search by name, part number, brand, barcode; compute `is_below_threshold` flag as `current_quantity <= min_threshold AND min_threshold > 0`
    - Implement `create_stock_item(db, org_id, user_id, payload)` — validate catalogue item exists and is active, check uniqueness, resolve supplier from catalogue if not provided, insert `stock_items` row + initial `stock_movements` record
    - Implement `update_stock_item(db, org_id, stock_item_id, payload)` — update barcode, supplier_id, thresholds
    - Implement `delete_stock_item(db, org_id, stock_item_id)` — remove stock item from inventory
    - _Requirements: 1.1, 1.2, 1.3, 5.5, 5.6, 6.1, 6.4, 7.3, 8.4, 9.1, 9.2, 9.3, 9.5, 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 3.2 Write property tests for stock items service
    - Create `tests/properties/test_stock_items_properties.py`
    - **Property 1: Stock Items List Exclusivity** — generate random catalogue items, add subset to stock, verify list returns exactly stocked subset
    - **Validates: Requirements 1.1, 1.2, 1.4, 9.1**
    - **Property 3: Below-Threshold Flag Correctness** — generate stock items with random quantities/thresholds, verify `is_below_threshold` flag
    - **Validates: Requirements 9.5**
    - **Property 7: Creation Produces Stock Item and Movement** — generate valid payloads, verify exactly one stock_item + one stock_movement created
    - **Validates: Requirements 5.5, 5.6, 10.1, 10.2**
    - **Property 8: Creation Input Validation** — generate invalid payloads (qty ≤ 0, empty reason), verify rejection with no records created
    - **Validates: Requirements 5.2, 5.3, 10.5**
    - **Property 9: Uniqueness Constraint** — create stock item, attempt duplicate, verify error and original unchanged
    - **Validates: Requirements 8.4, 10.3**
    - **Property 10: Invalid Catalogue Item Rejection** — generate non-existent/inactive catalogue IDs, verify error
    - **Validates: Requirements 10.4**
    - **Property 11: Supplier Resolution from Catalogue** — generate catalogue items with/without suppliers, verify stock item supplier field
    - **Validates: Requirements 6.1, 6.4**

- [x] 4. Checkpoint — Ensure migration, model, schemas, and service compile and all property tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. API router
  - [x] 5.1 Create stock items router in `app/modules/inventory/stock_items_router.py`
    - `GET /inventory/stock-items` — list stock items with optional `search`, `below_threshold_only`, `limit`, `offset` query params; returns `StockItemListResponse`
    - `POST /inventory/stock-items` — create stock item from `CreateStockItemRequest`; returns 201 with `StockItemResponse`; returns 409 if duplicate, 404 if catalogue item not found/inactive
    - `PUT /inventory/stock-items/{id}` — update stock item from `UpdateStockItemRequest`; returns `StockItemResponse`
    - `DELETE /inventory/stock-items/{id}` — remove stock item; returns 204
    - All endpoints scoped to current org via dependency injection
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 5.2 Register stock items router in `app/core/modules.py`
    - Import and include `stock_items_router` with prefix `/inventory/stock-items` and appropriate tags
    - _Requirements: 9.1, 10.1_

  - [x] 5.3 Write property tests for API endpoints
    - Add to `tests/properties/test_stock_items_properties.py` or create `tests/properties/test_stock_items_api_properties.py`
    - **Property 2: Response Data Correctness** — create stock items with known catalogue data, verify API response fields match catalogue + stock_items values (not packaging quantities)
    - **Validates: Requirements 1.3, 9.3, 9.4, 7.2**
    - **Property 5: Multi-Field Search** — generate stock items with random names/barcodes, verify search matches across name, part_number, brand, barcode
    - **Validates: Requirements 4.2, 7.3**
    - **Property 12: Barcode Update Round-Trip** — update barcode via PUT, retrieve via GET, verify match
    - **Validates: Requirements 7.4**

- [x] 6. Checkpoint — Ensure API router is wired and all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Frontend: AddToStockModal component
  - [x] 7.1 Create `AddToStockModal.tsx` in `frontend/src/components/inventory/`
    - Implement multi-step modal with three steps: CategorySelector → CataloguePicker → StockDetailsForm
    - **Step 1 — CategorySelector**: render three selectable cards (Parts, Tyres, Fluids/Oils) with distinct icons; clicking a card advances to step 2
    - **Step 2 — CataloguePicker**: fetch catalogue items via `GET /catalogue/parts?part_type={type}` or `GET /catalogue/fluid-oil`; render searchable list; show "Already in stock" badge for items with existing stock records; show empty state message when no items; include back button to return to step 1
    - **Step 3 — StockDetailsForm**: quantity input (required, > 0), reason dropdown (predefined options: "Purchase Order received", "Initial stock count", "Transfer in", "Other"), barcode input (optional), supplier dropdown (auto-populated from catalogue item's supplier, editable, clearable); submit calls `POST /inventory/stock-items`
    - Client-side validation before submission; display API errors as inline form errors or toast
    - On success: close modal and trigger parent refresh
    - _Requirements: 2.2, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 6.4, 7.1_

  - [x] 7.2 Write unit tests for AddToStockModal
    - Create `frontend/src/components/inventory/__tests__/AddToStockModal.test.tsx`
    - Test category selector renders 3 options and advances on click
    - Test catalogue picker search filtering and "already in stock" badge
    - Test stock details form validation (quantity > 0, reason required)
    - Test supplier auto-population from catalogue item
    - Test back navigation between steps
    - Test empty catalogue state message
    - _Requirements: 3.1, 3.2, 3.4, 4.4, 4.5, 5.2, 5.3, 6.1_

- [x] 8. Frontend: Refactor StockLevels page
  - [x] 8.1 Update `frontend/src/pages/inventory/StockLevels.tsx`
    - Replace existing API calls (e.g. `/inventory/stock/report`, `/inventory/fluid-stock`) with single `GET /inventory/stock-items`
    - Add "Add to Stock" button in page header that opens `AddToStockModal`
    - Add barcode column to the stock levels table
    - Add barcode to the search/filter functionality
    - Show empty state when no stock items exist (with prompt to add stock)
    - Refresh table data after modal closes successfully
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 7.2, 7.3_

  - [x] 8.2 Write property tests for StockLevels page
    - Create `frontend/src/pages/inventory/__tests__/stock-levels.properties.test.ts`
    - **Property 4: Category Filtering** — generate mixed catalogue items, verify picker returns only items matching selected category
    - **Validates: Requirements 3.3, 4.1**
    - **Property 6: Already-In-Stock Indicator** — generate catalogue items with/without stock records, verify indicator correctness
    - **Validates: Requirements 4.5**

- [x] 9. Final checkpoint — Ensure all backend and frontend tests pass, full feature is wired end-to-end
  - Ensure all tests pass, ask the user if questions arise.
