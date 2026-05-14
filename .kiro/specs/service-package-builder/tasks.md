# Implementation Plan: Service Package Builder

## Overview

Extends the Items Catalogue to support bundled service packages that combine labour with inventory components (parts, fluids, tyres). Implementation follows: database migration → backend service/endpoints → frontend components → invoice integration → tests. All changes are additive — existing `items_catalogue` entries are unaffected.

**Source of truth:** `.kiro/specs/service-package-builder/design.md` and `.kiro/specs/service-package-builder/requirements.md`

## Tasks

- [x] 1. Database migration — add package columns to `items_catalogue`
  - [x] 1.1 Create Alembic migration file
    - New file: `alembic/versions/2026_XX_XX_XXXX-XXXX_add_package_columns_to_items_catalogue.py`
    - `ALTER TABLE items_catalogue ADD COLUMN IF NOT EXISTS is_package BOOLEAN NOT NULL DEFAULT false`
    - `ALTER TABLE items_catalogue ADD COLUMN IF NOT EXISTS package_components JSONB NULL`
    - Use `ADD COLUMN IF NOT EXISTS` for idempotency
    - _Requirements: 7.1, 7.7_

  - [x] 1.2 Write downgrade path
    - Drop `package_components` column
    - Drop `is_package` column
    - Use reverse order of upgrade
    - _Requirements: 7.dde
find 
  - [x] 1.3 Verify migration locally
    - Run: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head`
    - Confirm existing `items_catalogue` rows unaffected (is_package defaults to false, package_components is null)
    - _Requirements: 7.7_

- [x] 2. Backend — ORM model and schema updates
  - [x] 2.1 Add columns to `ItemsCatalogue` model in `app/modules/catalogue/models.py`
    - `is_package: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")`
    - `package_components: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)`
    - _Requirements: 7.1, 7.2_

  - [x] 2.2 Create `PackageComponent` Pydantic schema in `app/modules/catalogue/schemas.py`
    - Fields: `catalogue_item_id: uuid.UUID`, `catalogue_type: Literal["part", "tyre", "fluid"]`, `quantity: int | None = None`, `volume: float | None = None`, `cost_per_unit_snapshot: float | None = None`, `fluid_type: str | None = None`, `oil_type: str | None = None`, `grade: str | None = None`
    - Validation: parts/tyres require `quantity >= 1`, fluids require `volume > 0`
    - _Requirements: 7.2, 7.3_

  - [x] 2.3 Extend item create/update request schemas
    - Add `is_package: bool = False` and `package_components: list[PackageComponent] | None = None` to `ItemCreateRequest` and `ItemUpdateRequest`
    - Validation: if `package_components` is non-empty, `is_package` must be `true`
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 2.4 Extend item response schema
    - Add `is_package: bool = False`, `package_components: list[dict] | None = None`, `package_cost: float | None = None`, `package_profit: float | None = None`, `has_unavailable_components: bool = False`
    - `package_cost` and `package_profit` are conditionally included (admin roles only)
    - _Requirements: 7.1, 9.1, 9.3, 10.3_

- [x] 3. Backend — catalogue service extensions
  - [x] 3.1 Extend `create_item()` to handle package data
    - Accept `is_package` and `package_components` in create payload
    - Validate each component's `catalogue_item_id` exists in `parts_catalogue` or `fluid_oil_products`
    - Capture `cost_per_unit_snapshot` from current stock/catalogue prices at save time
    - Persist `package_components` as JSONB on the `items_catalogue` row
    - Use `db.flush()` then `await db.refresh(obj)` before returning
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 3.2 Extend `update_item()` to handle package data
    - Replace existing `package_components` with the new set (not merge)
    - If `is_package` set to `false`, clear `package_components` to `null`
    - Re-snapshot `cost_per_unit_snapshot` from current prices on update
    - _Requirements: 7.4, 7.5, 7.6_

  - [x] 3.3 Extend `list_items()` to include package metadata
    - Add `is_package`, `has_unavailable_components` to list response for all roles
    - Add `package_cost`, `package_profit` for admin roles only (check `org_admin` or `global_admin`)
    - Check component availability by querying `parts_catalogue.is_active` and `fluid_oil_products.is_active`
    - _Requirements: 9.1, 9.3, 10.3, 11.4_

  - [x] 3.4 Implement `resolve_package_costs()` service function
    - For each component: query `stock_items` by `catalogue_item_id` and `org_id`
    - Single stock item → use its `purchase_price` or `cost_per_unit`
    - Multiple stock items → return all options (branch, cost, available qty)
    - No stock item → fall back to `parts_catalogue.cost_per_unit` or `fluid_oil_products.cost_per_unit`
    - Calculate `line_total` per component and `total_cost` sum
    - Omit cost fields for non-admin roles
    - _Requirements: 5.1, 5.6, 10.1, 10.3_

  - [x] 3.5 Implement `duplicate_item()` service function
    - Deep-copy the item with all `package_components` data
    - Append " (Copy)" to the name
    - Generate new UUID for the duplicate
    - Only allow duplication of package items (`is_package=true`)
    - _Requirements: 9.4_

- [x] 4. Checkpoint — Ensure backend service tests pass
  - Run: `pytest tests/test_package_builder_properties.py -v -k "persistence or update or remove_flag or cost_calculation" --no-header`
  - Verify syntax: `python3 -c "import ast; ast.parse(open('app/modules/catalogue/service.py').read())"`
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Backend — new API endpoints
  - [x] 5.1 Create `GET /catalogue/items/:id/package-costs` endpoint
    - Call `resolve_package_costs()` service function
    - Return component list with costs, availability, and totals
    - Access control: omit cost fields for non-admin roles
    - _Requirements: 5.1, 5.6, 10.1, 10.3_

  - [x] 5.2 Create `GET /catalogue/parts/search` endpoint
    - Query params: `q` (search string), `part_type` (filter: `part` or `tyre`), `limit` (default 20)
    - Search `parts_catalogue` where `is_active = true` and `org_id` matches
    - Return: `id`, `name`, `part_number`, `part_type`, `brand`, `cost_per_unit`, `stock_available`
    - Cost fields omitted for non-admin roles
    - _Requirements: 4.1, 4.5_

  - [x] 5.3 Create `GET /catalogue/fluids/search` endpoint
    - Query params: `q` (search), `fluid_type` (oil/non-oil), `oil_type`, `limit` (default 20)
    - Search `fluid_oil_products` where `is_active = true`
    - Return: `id`, `product_name`, `brand_name`, `fluid_type`, `oil_type`, `grade`, `cost_per_unit`, `stock_available`
    - Cost fields omitted for non-admin roles
    - _Requirements: 3.3, 3.4, 3.5_

  - [x] 5.4 Create `POST /catalogue/items/:id/duplicate` endpoint
    - Call `duplicate_item()` service function
    - Return 404 if item not found, 400 if item is not a package
    - Return the newly created item response
    - _Requirements: 9.4_

  - [x] 5.5 Register new endpoints in `app/main.py`
    - Mount alongside existing catalogue router
    - _Requirements: 5.1, 4.1, 3.3, 9.4_

- [x] 6. Checkpoint — Ensure backend endpoints work
  - Run: `pytest tests/test_package_builder_properties.py -v -k "search or endpoint or duplicate" --no-header`
  - Verify syntax: `python3 -c "import ast; ast.parse(open('app/modules/catalogue/service.py').read())"`
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Frontend — TypeScript types and API hooks
  - [x] 7.1 Create `PackageComponent` TypeScript interface
    - New file: `frontend/src/pages/items/types.ts`
    - Interface: `catalogue_item_id: string`, `catalogue_type: 'part' | 'tyre' | 'fluid'`, `quantity?: number`, `volume?: number`, `cost_per_unit_snapshot?: number`, `fluid_type?: string`, `oil_type?: string`, `grade?: string`
    - _Requirements: 7.2, 7.3_

  - [x] 7.2 Extend item list/detail interfaces
    - Add `is_package: boolean`, `package_components: PackageComponent[] | null`, `package_cost?: number`, `package_profit?: number`, `has_unavailable_components: boolean`
    - Use `?.` and `?? false` / `?? null` on all new fields
    - _Requirements: 9.1, 9.3_

  - [x] 7.3 Create API hook for package cost resolution
    - `usePackageCosts(itemId: string)` — calls `GET /catalogue/items/:id/package-costs`
    - Returns component list with costs and availability
    - Uses `AbortController` cleanup
    - _Requirements: 5.1, 5.6_

  - [x] 7.4 Create API hooks for parts/fluids search
    - `usePartsSearch(query: string, partType: 'part' | 'tyre')` — calls `GET /catalogue/parts/search`
    - `useFluidsSearch(query: string, fluidType?: string, oilType?: string)` — calls `GET /catalogue/fluids/search`
    - Both use debounced search with `AbortController` cleanup
    - _Requirements: 4.1, 4.5, 3.3, 3.5_

- [x] 8. Frontend — PackageBuilder component
  - [x] 8.1 Create `PackageBuilder.tsx` main component
    - New file: `frontend/src/pages/items/components/PackageBuilder.tsx`
    - Props: `{ components: PackageComponent[]; onChange: (components: PackageComponent[]) => void; sellPrice: number; userRole: string }`
    - Contains "Include Inventory Usage" checkbox
    - Module gate: only render when `useModules().isEnabled('vehicles') && useModules().isEnabled('inventory')`
    - Manages local state for component selections
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 8.2 Create `InventoryTypeSelector.tsx` component
    - New file: `frontend/src/pages/items/components/InventoryTypeSelector.tsx`
    - Three checkboxes: "Parts", "Fluid", "Tyre"
    - Conditionally renders sub-forms based on checked state
    - Unchecking clears selections for that type
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 8.3 Create `PartsSelector.tsx` component
    - New file: `frontend/src/pages/items/components/PartsSelector.tsx`
    - Searchable dropdown calling `GET /catalogue/parts/search?part_type=part`
    - On select: adds component with default quantity 1
    - Renders `ComponentRow` for each selected part
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 8.4 Create `TyreSelector.tsx` component
    - New file: `frontend/src/pages/items/components/TyreSelector.tsx`
    - Searchable dropdown calling `GET /catalogue/parts/search?part_type=tyre`
    - On select: adds component with default quantity 1
    - Renders `ComponentRow` for each selected tyre
    - _Requirements: 4.5, 4.6, 4.7, 4.8_

  - [x] 8.5 Create `ComponentRow.tsx` component
    - New file: `frontend/src/pages/items/components/ComponentRow.tsx`
    - Displays: name, quantity input, cost per unit (admin only), line total (admin only), remove button
    - Marks unavailable components with strikethrough and "Unavailable" badge
    - _Requirements: 4.3, 4.4, 4.7, 4.8, 11.2_

  - [x] 8.6 Create `FluidSelector.tsx` component
    - New file: `frontend/src/pages/items/components/FluidSelector.tsx`
    - Manages multiple fluid entries via "+ Add Fluid" button
    - Renders `FluidEntry` for each fluid
    - _Requirements: 3.1_

  - [x] 8.7 Create `FluidEntry.tsx` component
    - New file: `frontend/src/pages/items/components/FluidEntry.tsx`
    - Oil/Non-Oil toggle → oil_type dropdown (for oil) → product dropdown → litres input
    - Cascading dropdowns: fluid_type → oil_type → product selection
    - Calls `GET /catalogue/fluids/search` with appropriate filters
    - Displays cost per litre (admin only) and "No matching product" message when empty
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [x] 8.8 Create `CostSummary.tsx` component
    - New file: `frontend/src/pages/items/components/CostSummary.tsx`
    - Displays "Total Package Cost" and "Profit" (sell price − cost)
    - Red styling + warning indicator when profit is negative
    - Only visible to `org_admin` or `global_admin` roles
    - Recalculates on every component change (derived state, no API call)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.7_

  - [x] 8.9 Create `PackagePreview.tsx` component
    - New file: `frontend/src/pages/items/components/PackagePreview.tsx`
    - Read-only summary: component name, type, quantity/litres, unit cost, line total
    - Shows total litres for fluids, total cost, sell price, profit
    - Shows `current_stock_volume` / `current_quantity` per component
    - "Low Stock" / "Out of Stock" badges when stock insufficient
    - Triggered by "Preview Package" button (inline collapse, not separate modal)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9_

- [x] 9. Frontend — Items Catalogue page modifications
  - [x] 9.1 Add "Package" badge to items table
    - Display badge next to item name when `is_package === true`
    - Display warning icon when `has_unavailable_components === true`
    - _Requirements: 9.1, 11.4_

  - [x] 9.2 Add Cost and Profit columns to items table
    - Only visible to `org_admin` / `global_admin` roles
    - Show `package_cost` and `package_profit` for package items
    - Empty for non-package items
    - _Requirements: 9.3_

  - [x] 9.3 Add "Duplicate" action to row action menu
    - Only shown for package items (`is_package === true`)
    - Opens confirmation dialog: "Create a copy of '{name}'?"
    - On confirm: calls `POST /catalogue/items/:id/duplicate`
    - Refreshes table on success
    - _Requirements: 9.4_

  - [x] 9.4 Integrate PackageBuilder into New/Edit Item modal
    - Mount `PackageBuilder` below existing form fields in the modal
    - On edit: pre-populate with saved `package_components` from API response
    - On save: include `is_package` and `package_components` in request payload
    - Display unavailable component warning banner on edit when components are deactivated
    - _Requirements: 7.4, 9.2, 11.1, 11.2_

- [x] 10. Checkpoint — Ensure frontend builds cleanly
  - Run: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend sh -c "rm -rf /app/dist/assets/* && npx vite build"`
  - Verify no TypeScript errors in new component files
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Backend — invoice integration
  - [x] 11.1 Implement `resolve_package_line_item()` in invoice service
    - When a line item references a package `catalogue_item_id`:
    - Resolve all components from `package_components` JSONB
    - Calculate `cost_price` as sum of live component costs (from `stock_items` with catalogue fallback)
    - For unavailable components: use `cost_per_unit_snapshot`, skip stock deduction
    - _Requirements: 8.1, 11.3_

  - [x] 11.2 Implement `deduct_package_inventory()` in invoice service
    - On invoice issue (not draft): deduct stock for each component
    - Parts/tyres: decrement `stock_items.current_quantity` by component quantity
    - Fluids: decrement `stock_items.current_quantity` by component volume
    - Skip deduction for unavailable/deactivated components
    - Warn (don't block) when stock is insufficient
    - _Requirements: 8.2, 8.3, 11.3_

  - [x] 11.3 Write fluid usage entries to `invoice_data_json`
    - For each fluid component: write entry to `invoice_data_json.fluid_usage`
    - Include `stock_item_id`, `litres`, `cost_per_litre`, `total_cost`
    - Consistent with existing fluid usage behaviour
    - _Requirements: 8.4_

  - [x] 11.4 Handle quotes with package items
    - Show cost/profit preview on quotes
    - Do NOT deduct inventory for quote line items
    - Deduction only occurs when quote is converted to invoice and issued
    - _Requirements: 8.5_

- [x] 12. Frontend — StockSourceModal for multi-stock-item selection
  - [x] 12.1 Create `StockSourceModal.tsx` component
    - New file: `frontend/src/pages/items/components/StockSourceModal.tsx`
    - Triggered when adding a package item to an invoice and a component has multiple stock items
    - Displays per-component: branch name, location, available quantity, cost per unit
    - User selects one stock item per ambiguous component
    - On confirm: returns selected stock item IDs for cost calculation and deduction
    - _Requirements: 8.1, 8.2_

- [x] 13. Checkpoint — Ensure full integration works
  - Run: `pytest tests/test_package_builder_properties.py tests/test_package_lifecycle.py -v`
  - Run frontend build to confirm no regressions
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Backend — property-based tests
  - [x] 14.1 Property test: Module gating controls visibility
    - **Property 1: Module gating controls package builder visibility**
    - Test file: `tests/test_package_builder_properties.py`
    - Strategy: generate all combinations of module enabled/disabled states
    - Assert: package builder visible iff both `vehicles` AND `inventory` enabled
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 1.1, 1.5**

  - [x] 14.2 Property test: Unchecking toggle clears components
    - **Property 2: Unchecking the inventory toggle clears all component selections**
    - Test file: `frontend/src/pages/items/components/PackageBuilder.test.ts`
    - Strategy: generate random component lists, uncheck toggle, verify empty
    - Use `fc.assert(property, { numRuns: 100 })`
    - **Validates: Requirements 1.4**

  - [x] 14.3 Property test: Part type search filtering
    - **Property 3: Part type search filtering returns only matching types**
    - Test file: `tests/test_package_builder_properties.py`
    - Strategy: generate random catalogue data with mixed part_types, search with filter
    - Assert: all results match requested `part_type`
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 4.1, 4.5**

  - [x] 14.4 Property test: Package cost calculation
    - **Property 4: Package cost equals sum of component costs**
    - Test file: `tests/test_package_builder_properties.py`
    - Strategy: generate random component lists with costs and quantities/volumes
    - Assert: total cost = sum of (cost × quantity) for parts/tyres + (cost × volume) for fluids
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 5.1**

  - [x] 14.5 Property test: Package profit calculation
    - **Property 5: Package profit equals sell price minus package cost**
    - Test file: `tests/test_package_builder_properties.py`
    - Strategy: generate random sell prices and component costs
    - Assert: profit = sell_price − total_cost
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 5.4**

  - [x] 14.6 Property test: Negative profit warning
    - **Property 6: Negative profit triggers warning indicator**
    - Test file: `frontend/src/pages/items/components/CostSummary.test.ts`
    - Strategy: generate cases where cost > sell price
    - Assert: red styling and warning indicator present
    - Use `fc.assert(property, { numRuns: 100 })`
    - **Validates: Requirements 5.5**

  - [x] 14.7 Property test: Cost data role restriction
    - **Property 7: Cost data visibility is restricted to admin roles**
    - Test file: `tests/test_package_builder_properties.py`
    - Strategy: generate all role values, request package cost endpoint
    - Assert: cost fields present only for `org_admin` / `global_admin`
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 5.7, 10.1, 10.2, 10.3**

  - [x] 14.8 Property test: Stock warning badges
    - **Property 8: Stock warning badges appear when stock is insufficient**
    - Test file: `frontend/src/pages/items/components/PackagePreview.test.ts`
    - Strategy: generate components with stock < required quantity
    - Assert: warning badge rendered for insufficient stock
    - Use `fc.assert(property, { numRuns: 100 })`
    - **Validates: Requirements 6.9**

  - [x] 14.9 Property test: Persistence round-trip
    - **Property 9: Package persistence round-trip preserves all component data**
    - Test file: `tests/test_package_builder_properties.py`
    - Strategy: generate valid packages, save via API, read back
    - Assert: all component fields identical after round-trip
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 7.1, 7.2, 7.3**

  - [x] 14.10 Property test: Update replaces components
    - **Property 10: Package update replaces (not merges) component metadata**
    - Test file: `tests/test_package_builder_properties.py`
    - Strategy: generate two different component sets, update, verify only new set persisted
    - Assert: no components from previous version remain
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 7.5**

  - [x] 14.11 Property test: Remove flag clears metadata
    - **Property 11: Removing package flag clears all package metadata**
    - Test file: `tests/test_package_builder_properties.py`
    - Strategy: generate packages, set `is_package=false`, verify null
    - Assert: `is_package=false` and `package_components=null`
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 7.6**

  - [x] 14.12 Property test: Invoice cost_price from live costs
    - **Property 12: Invoice cost_price equals sum of live component costs**
    - Test file: `tests/test_package_builder_properties.py`
    - Strategy: generate packages with known stock prices, create invoice
    - Assert: `cost_price` = sum of live component costs
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 8.1**

  - [x] 14.13 Property test: Inventory deduction correctness
    - **Property 13: Invoice issuance deducts correct inventory quantities**
    - Test file: `tests/test_package_builder_properties.py`
    - Strategy: generate packages, issue invoice, check stock changes
    - Assert: each component stock decremented by exact required amount
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 8.2**

  - [x] 14.14 Property test: Fluid usage recording
    - **Property 14: Package fluid components are recorded in invoice fluid_usage**
    - Test file: `tests/test_package_builder_properties.py`
    - Strategy: generate packages with fluid components, issue invoice
    - Assert: each fluid produces a `fluid_usage` entry with correct fields
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 8.4**

  - [x] 14.15 Property test: Quotes don't deduct inventory
    - **Property 15: Quotes with package items do not deduct inventory**
    - Test file: `tests/test_package_builder_properties.py`
    - Strategy: generate packages on quotes, verify stock unchanged
    - Assert: all stock quantities remain identical before and after
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 8.5**

  - [x] 14.16 Property test: Package duplication
    - **Property 16: Package duplication preserves all components**
    - Test file: `tests/test_package_builder_properties.py`
    - Strategy: generate packages, duplicate, compare
    - Assert: new item has different `id` but identical `package_components`
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 9.4**

  - [x] 14.17 Property test: Unavailable component warning
    - **Property 17: Unavailable components trigger warning on package edit**
    - Test file: `tests/test_package_builder_properties.py`
    - Strategy: generate packages with deactivated components
    - Assert: warning displayed identifying all unavailable components
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 11.1**

  - [x] 14.18 Property test: Unavailable components on invoice
    - **Property 18: Unavailable components skip deduction but retain cost on invoice**
    - Test file: `tests/test_package_builder_properties.py`
    - Strategy: generate packages with inactive components, create invoice
    - Assert: no stock deduction for unavailable, but snapshot cost included in `cost_price`
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 11.3**

- [x] 15. Frontend — component tests
  - [x] 15.1 Vitest: PackageBuilder module gating
    - Render with modules enabled/disabled, verify checkbox visibility
    - _Requirements: 1.1, 1.5_

  - [x] 15.2 Vitest: PackageBuilder toggle clears components
    - Add components, uncheck toggle, verify component list empty
    - _Requirements: 1.4_

  - [x] 15.3 Vitest: CostSummary role-based visibility
    - Render with admin role → cost visible; non-admin role → cost hidden
    - _Requirements: 5.7, 10.1_

  - [x] 15.4 Vitest: PackagePreview stock warnings
    - Render with low/zero stock components, verify warning badges
    - _Requirements: 6.9_

  - [x] 15.5 Vitest: FluidSelector cascading dropdowns
    - Select Oil → verify oil_type dropdown appears; select Non-Oil → verify product list appears
    - _Requirements: 3.2, 3.3, 3.5_

  - [x] 15.6 Vitest: Items table Package badge and duplicate action
    - Render table with package items, verify badge and duplicate menu item
    - _Requirements: 9.1, 9.4_

- [x] 16. Integration tests
  - [x] 16.1 Full lifecycle: create → edit → duplicate → delete package item
    - Test file: `tests/test_package_lifecycle.py`
    - Create package with parts + fluids + tyres, edit quantities, duplicate, delete original
    - Verify all CRUD operations and data integrity
    - _Requirements: 7.1, 7.4, 7.5, 9.4_

  - [x] 16.2 Package item on invoice: cost calculation + inventory deduction
    - Create package, add to invoice, issue invoice
    - Verify `cost_price` matches live component costs
    - Verify stock decremented correctly for each component
    - Verify `fluid_usage` entries written
    - _Requirements: 8.1, 8.2, 8.4_

  - [x] 16.3 Package item on quote: no inventory deduction
    - Create package, add to quote
    - Verify stock quantities unchanged
    - _Requirements: 8.5_

  - [x] 16.4 Unavailable component handling
    - Create package, deactivate a component, open for edit
    - Verify warning displayed, verify invoice uses snapshot cost
    - _Requirements: 11.1, 11.3_

  - [x] 16.5 Access control: non-admin cannot see cost data
    - Request package costs as `salesperson` role
    - Verify cost fields omitted from response
    - _Requirements: 10.1, 10.2, 10.3_

- [x] 17. Final checkpoint — Ensure all relevant tests pass
  - Run backend package tests only: `pytest tests/test_package_builder_properties.py tests/test_package_lifecycle.py -v`
  - Run frontend build: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend sh -c "rm -rf /app/dist/assets/* && npx vite build"`
  - Verify syntax: `python3 -c "import ast; ast.parse(open('app/modules/catalogue/service.py').read())"`
  - Ensure all tests pass, ask the user if questions arise.

- [x] 18. Update version info
  - Bump version in `pyproject.toml` (e.g., `1.4.0` → `1.5.0`)
  - Bump version in `frontend/package.json`
  - Add entry to `CHANGELOG.md` summarizing the Service Package Builder feature
  - Update `docs/ISSUE_TRACKER.md` if any issues were resolved

- [-] 19. Git push all changes
  - `git add -A`
  - `git commit -m "feat: service package builder — bundled service items with inventory components"`
  - `git push -u origin feature/service-package-builder`

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints run ONLY relevant tests (not the full test suite) to keep feedback fast
- Property tests validate universal correctness properties from the design document (18 properties)
- Backend tests: `pytest tests/test_package_builder_properties.py tests/test_package_lifecycle.py -v`
- Frontend build: `docker compose exec frontend sh -c "rm -rf /app/dist/assets/* && npx vite build"`
- Backend uses `db.flush()` not `db.commit()` in services; always `await db.refresh(obj)` before returning
- Frontend must use `?.` and `?? []` / `?? null` / `?? false` on all API data
- Database migration must use `IF NOT EXISTS` for idempotency
- Property tests: backend uses `@settings(max_examples=30)` (Hypothesis), frontend uses `fc.assert(property, { numRuns: 30 })` (fast-check)
- Cost fields are role-gated: only `org_admin` and `global_admin` see cost/profit data
- Module gate: package features require both `vehicles` AND `inventory` modules enabled
- Version bump and git push are the final tasks after all tests pass
