# Requirements: Inventory Page Redesign — Unified Parts & Fluids/Oils Stock Management

## Overview
The current Inventory page only tracks stock for Parts (from `parts_catalogue`). Fluids/Oils (from `fluid_oil_products`) are completely absent from inventory management. This redesign unifies both product types under a single inventory experience with type-aware filtering, stock adjustments, and reorder alerts.

## Current State
- Inventory page has 4 tabs: Stock Levels, Reorder Alerts, Adjust Stock, Suppliers
- All tabs only query `PartsCatalogue` via `/inventory/stock` endpoints
- `FluidOilProduct` has stock fields (`current_stock_volume`, `min_stock_volume`, `reorder_volume`) but no inventory endpoints
- Fluids use decimal volumes (litres/gallons), parts use integer quantities
- No way to view, adjust, or get alerts for fluid/oil stock

## Requirements

### Req 1: Unified Stock Levels View
- **1.1**: Stock Levels tab must display both Parts and Fluids/Oils in a single table
- **1.2**: Add a type filter toggle: "All" | "Parts" | "Fluids / Oils" above the stock table
- **1.3**: Add a "Type" column to the table showing a badge ("Part" or "Fluid/Oil")
- **1.4**: Parts show: name, part_number, current_stock (integer), min_threshold, reorder_qty, status
- **1.5**: Fluids show: display_name (oil_type + grade OR product_name), brand, current_stock_volume (decimal with unit), min_stock_volume, reorder_volume, status
- **1.6**: Summary cards must show combined totals across both types (Total Items Tracked, Below Threshold, Recent Movements)
- **1.7**: Search/filter must work across both types (search by name, part_number, brand, oil_type)

### Req 2: Unified Reorder Alerts
- **2.1**: Reorder Alerts tab must include fluids/oils where `current_stock_volume <= min_stock_volume` AND `min_stock_volume > 0`
- **2.2**: Alert table must show a "Type" badge column to distinguish parts from fluids
- **2.3**: Deficit calculation for fluids: `min_stock_volume - current_stock_volume` with unit label (e.g. "5.5 L short")

### Req 3: Type-Aware Stock Adjustment
- **3.1**: Adjust Stock tab must have a type selector at the top: "Parts" or "Fluids / Oils"
- **3.2**: When "Parts" is selected, show existing part dropdown with integer quantity adjustment (current behavior)
- **3.3**: When "Fluids / Oils" is selected, show fluid/oil product dropdown with decimal volume adjustment
- **3.4**: Fluid adjustment input must support decimal values (e.g. +5.5 litres) with step="0.1"
- **3.5**: Fluid adjustments must be audit-logged with reason, same as parts
- **3.6**: Show current stock volume and unit type for the selected fluid product

### Req 4: Backend — Fluid Stock Endpoints
- **4.1**: `GET /inventory/fluid-stock` — list fluid/oil stock levels for the org (mirrors `/inventory/stock` for parts)
- **4.2**: `PUT /inventory/fluid-stock/{product_id}` — adjust fluid stock volume with reason (audit logged)
- **4.3**: `GET /inventory/fluid-stock/reorder-alerts` — fluids below min_stock_volume threshold
- **4.4**: `GET /inventory/stock/report` — extend to include fluid stock in the combined report
- **4.5**: All endpoints must be org-scoped with RLS and require `org_admin` or `salesperson` role

### Req 5: Suppliers Tab — No Changes
- **5.1**: Suppliers tab remains unchanged (suppliers are shared across parts and fluids)

### Req 6: Summary Cards Update
- **6.1**: "Total Items Tracked" = count of parts + count of fluids with stock tracking
- **6.2**: "Below Threshold" = parts below threshold + fluids below threshold
- **6.3**: "Recent Movements" = combined movement count (parts movements + fluid movements when implemented)

## Out of Scope
- Fluid stock movement history table (can be added later)
- Purchase order generation for fluids (future enhancement)
- Barcode scanning for fluids
