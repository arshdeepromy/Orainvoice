# Design: Inventory Page Redesign — Unified Parts & Fluids/Oils Stock Management

## Architecture Overview

The redesign adds fluid/oil stock management alongside existing parts stock tracking. The backend gets new endpoints for fluid stock, and the frontend inventory pages are updated to fetch and display both types in a unified view.

## Backend Design

### New Endpoints (added to `app/modules/inventory/router.py`)

#### `GET /inventory/fluid-stock`
- Query `fluid_oil_products` where `org_id` matches and `is_active = true`
- Return: `{ fluid_stock_levels: [...], total: int }`
- Each item: `{ product_id, display_name, brand_name, fluid_type, oil_type, grade, unit_type, current_stock_volume, min_stock_volume, reorder_volume, is_below_threshold }`
- `display_name` logic: if oil → `"{oil_type_label} {grade}"`, if non-oil → `product_name`
- `is_below_threshold` = `current_stock_volume <= min_stock_volume` AND `min_stock_volume > 0`

#### `PUT /inventory/fluid-stock/{product_id}`
- Request body: `{ volume_change: float, reason: str }`
- Validate product exists and belongs to org
- Update `current_stock_volume += volume_change` (must not go below 0)
- Write audit log entry
- Return updated stock level

#### `GET /inventory/fluid-stock/reorder-alerts`
- Query `fluid_oil_products` where `current_stock_volume <= min_stock_volume` AND `min_stock_volume > 0` AND `is_active = true`
- Return: `{ alerts: [...], total: int }`

### New Schemas (added to `app/modules/inventory/schemas.py`)

```python
class FluidStockLevelResponse(BaseModel):
    product_id: str
    display_name: str
    brand_name: Optional[str]
    fluid_type: str
    oil_type: Optional[str]
    grade: Optional[str]
    unit_type: str  # "litre" or "gallon"
    current_stock_volume: float
    min_stock_volume: float
    reorder_volume: float
    is_below_threshold: bool

class FluidStockLevelListResponse(BaseModel):
    fluid_stock_levels: list[FluidStockLevelResponse]
    total: int

class FluidStockAdjustmentRequest(BaseModel):
    volume_change: float  # positive to add, negative to remove
    reason: str

class FluidReorderAlertResponse(BaseModel):
    product_id: str
    display_name: str
    brand_name: Optional[str]
    unit_type: str
    current_stock_volume: float
    min_stock_volume: float
    reorder_volume: float

class FluidReorderAlertListResponse(BaseModel):
    alerts: list[FluidReorderAlertResponse]
    total: int
```

### Service Layer (added to `app/modules/inventory/service.py`)

```python
async def get_fluid_stock_levels(db, *, org_id, limit=100, offset=0) -> dict
async def adjust_fluid_stock(db, *, org_id, user_id, product_id, volume_change, reason, ip_address=None) -> dict
async def get_fluid_reorder_alerts(db, *, org_id) -> dict
```

### Extended Stock Report
- `GET /inventory/stock/report` response adds:
  - `fluid_levels: list[FluidStockLevelResponse]`
  - `fluid_below_threshold: list[FluidStockLevelResponse]`

## Frontend Design

### StockLevels.tsx Changes

1. Fetch both `/inventory/stock/report` (existing) and `/inventory/fluid-stock` (new)
2. Add type filter state: `'all' | 'parts' | 'fluids'`
3. Render 3 toggle buttons above the table
4. Merge both datasets into a unified display list with a `type` field
5. Summary cards compute combined totals
6. Table adds "Type" column with badge
7. For fluids, "Current Stock" column shows decimal + unit (e.g. "45.5 L")
8. Search filters across both datasets

### ReorderAlerts.tsx Changes

1. Fetch both `/inventory/stock/reorder-alerts` (existing) and `/inventory/fluid-stock/reorder-alerts` (new)
2. Merge alerts with a `type` field
3. Add "Type" badge column
4. Deficit for fluids shows unit label (e.g. "5.5 L short")

### StockAdjustment.tsx Changes

1. Add type selector at top: "Parts" | "Fluids / Oils" (segmented toggle)
2. When "Parts" selected: existing behavior (integer qty, part dropdown)
3. When "Fluids / Oils" selected:
   - Fetch `/inventory/fluid-stock` for product dropdown
   - Show product info card (current volume, unit, min threshold)
   - Volume change input with `step="0.1"` and decimal support
   - Submit to `PUT /inventory/fluid-stock/{product_id}`
4. Same reason dropdown for both types

### InventoryPage.tsx — No structural changes
- Same 4 tabs, child components handle the unified logic internally

## Data Flow

```
Frontend                          Backend
─────────                         ───────
StockLevels.tsx ──GET──→ /inventory/stock/report (parts)
                ──GET──→ /inventory/fluid-stock (fluids)
                ← merge & display ←

ReorderAlerts.tsx ──GET──→ /inventory/stock/reorder-alerts (parts)
                  ──GET──→ /inventory/fluid-stock/reorder-alerts (fluids)
                  ← merge & display ←

StockAdjustment.tsx
  [Parts mode]    ──PUT──→ /inventory/stock/{part_id}
  [Fluids mode]   ──GET──→ /inventory/fluid-stock (list)
                  ──PUT──→ /inventory/fluid-stock/{product_id}
```

## File Changes Summary

| File | Change |
|------|--------|
| `app/modules/inventory/router.py` | Add 3 fluid stock endpoints |
| `app/modules/inventory/service.py` | Add 3 fluid stock service functions |
| `app/modules/inventory/schemas.py` | Add fluid stock schemas |
| `frontend/src/pages/inventory/StockLevels.tsx` | Unified view with type filter |
| `frontend/src/pages/inventory/ReorderAlerts.tsx` | Include fluid alerts |
| `frontend/src/pages/inventory/StockAdjustment.tsx` | Type selector + fluid adjustment |
