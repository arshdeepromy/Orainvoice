# Tasks: Inventory Page Redesign — Unified Parts & Fluids/Oils Stock Management

## Task 1: Backend — Fluid Stock Schemas
- [x] Add `FluidStockLevelResponse`, `FluidStockLevelListResponse`, `FluidStockAdjustmentRequest`, `FluidReorderAlertResponse`, `FluidReorderAlertListResponse` to `app/modules/inventory/schemas.py`
- [ ] Req: 4.1, 4.2, 4.3

### Relevant files
- `app/modules/inventory/schemas.py`

---

## Task 2: Backend — Fluid Stock Service Functions
- [x] Add `get_fluid_stock_levels()` to `app/modules/inventory/service.py` — query `FluidOilProduct` for org, return stock levels with `display_name` logic and `is_below_threshold` calculation
- [x] Add `adjust_fluid_stock()` to `app/modules/inventory/service.py` — update `current_stock_volume` with validation (no negative stock), write audit log
- [x] Add `get_fluid_reorder_alerts()` to `app/modules/inventory/service.py` — query fluids where `current_stock_volume <= min_stock_volume` and `min_stock_volume > 0`
- [ ] Req: 4.1, 4.2, 4.3, 4.5

### Relevant files
- `app/modules/inventory/service.py`
- `app/modules/catalogue/fluid_oil_models.py`

---

## Task 3: Backend — Fluid Stock Router Endpoints
- [x] Add `GET /inventory/fluid-stock` endpoint to `app/modules/inventory/router.py` — calls `get_fluid_stock_levels()`, requires `org_admin` or `salesperson` role
- [x] Add `PUT /inventory/fluid-stock/{product_id}` endpoint — calls `adjust_fluid_stock()`, requires `org_admin` role
- [x] Add `GET /inventory/fluid-stock/reorder-alerts` endpoint — calls `get_fluid_reorder_alerts()`, requires `org_admin` or `salesperson` role
- [ ] Req: 4.1, 4.2, 4.3, 4.5

### Relevant files
- `app/modules/inventory/router.py`

---

## Task 4: Frontend — StockLevels.tsx Unified View
- [x] Fetch both `/inventory/stock/report` and `/inventory/fluid-stock` on mount
- [x] Add type filter toggle state: `'all' | 'parts' | 'fluids'` with 3 buttons ("All", "Parts", "Fluids / Oils")
- [x] Merge parts and fluids into a unified list with a `type` field for rendering
- [x] Add "Type" column to the table with badge ("Part" blue, "Fluid/Oil" purple)
- [x] For fluids: show `display_name` in Part column, `brand_name` in Part Number column, decimal volume + unit in Current Stock column
- [x] Summary cards show combined totals (parts + fluids)
- [x] Search/filter works across both datasets
- [ ] Req: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7

### Relevant files
- `frontend/src/pages/inventory/StockLevels.tsx`

---

## Task 5: Frontend — ReorderAlerts.tsx Include Fluids
- [x] Fetch both `/inventory/stock/reorder-alerts` and `/inventory/fluid-stock/reorder-alerts` on mount
- [x] Merge alerts with a `type` field
- [x] Add "Type" badge column to the table
- [x] Deficit for fluids shows unit label (e.g. "5.5 L short")
- [x] Alert count banner shows combined total
- [ ] Req: 2.1, 2.2, 2.3

### Relevant files
- `frontend/src/pages/inventory/ReorderAlerts.tsx`

---

## Task 6: Frontend — StockAdjustment.tsx Type-Aware Adjustment
- [x] Add type selector at top: "Parts" | "Fluids / Oils" segmented toggle (default: "Parts")
- [x] When "Parts" selected: existing behavior unchanged (integer qty, part dropdown from `/inventory/stock`)
- [x] When "Fluids / Oils" selected: fetch `/inventory/fluid-stock` for product dropdown
- [x] Fluid dropdown shows: `display_name (brand) — Volume: X L`
- [x] Show info card for selected fluid: current volume, unit, min threshold, reorder volume
- [x] Volume change input with `type="number" step="0.1"` for decimal support
- [x] Submit fluid adjustment to `PUT /inventory/fluid-stock/{product_id}` with `{ volume_change, reason }`
- [x] Same reason dropdown for both types
- [x] Success/error messages work for both types
- [x] Req: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6

### Relevant files
- `frontend/src/pages/inventory/StockAdjustment.tsx`

---

## Task 7: Build & Verify
- [x] Rebuild frontend in Docker container: `docker exec invoicing-frontend-1 npx vite build`
- [x] Verify no TypeScript compilation errors via `getDiagnostics`
- [ ] Req: All
