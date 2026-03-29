---
inclusion: fileMatch
fileMatchPattern: "**/catalogue/**,**/inventory/**,**/stock_items*,**/parts*,**/FluidOil*"
---

# Trade-Specific Catalogue & Inventory Architecture

This file is loaded whenever catalogue, inventory, stock items, or parts-related files are read or edited. It defines the architecture for how trade-specific features (automotive parts, plumbing fittings, electrical supplies, etc.) are built on top of the shared inventory/catalogue system.

## Core Principle: Shared Infrastructure, Trade-Specific UI

The platform serves multiple trade types (automotive, plumbing, electrical, construction, hospitality, etc.). Each trade has unique catalogue items with different fields, but they all share the same underlying infrastructure.

### What is SHARED across all trades (do NOT duplicate per trade)

- Database tables: `stock_items`, `catalogue_products`, `stock_movements`, `suppliers`
- Inventory pages: Stock Levels, Usage History, Stock Update Log, Reorder Alerts, Suppliers, Stock Adjustment
- Invoice/quote/booking line item picker — pulls from the same `catalogue_products` table
- Stock tracking logic (movements, reorder thresholds, min/max quantities)
- Purchase order system
- Barcode scanning
- Import/export

### What is TRADE-SPECIFIC (varies per trade family)

- Catalogue form fields (the form used to create/edit a catalogue product)
- Product categories seeded during onboarding
- Trade-specific integrations (Carjam for automotive, supplier APIs for plumbing, etc.)
- Terminology labels (via TerminologyContext — "parts" vs "fittings" vs "materials")
- Default units of measure
- Trade-specific columns in inventory list views

## How to Determine the Org's Trade

The org's trade is stored on the `organisations` table via `trade_category_id`, which links to `trade_categories` → `trade_families`. The frontend gets this from the `TenantContext` or `GET /api/v1/org/settings`.

Trade families in the system:
- `automotive` — mechanics, panel beaters, auto electricians, tyre shops
- `building_construction` — builders, roofers, painters, glaziers
- `plumbing_gas` — plumbers, gasfitters, drainlayers
- `electrical` — electricians, data/comms, solar installers
- `hospitality` — cafés, restaurants, bars, food trucks
- `professional_services` — accountants, consultants, designers
- `retail` — general retail, specialty shops
- `other` — catch-all

## Catalogue Form Architecture

Each trade family can have one or more catalogue form components. These are loaded conditionally based on the org's trade family.

### File naming convention

```
frontend/src/pages/catalogue/{TradeFamily}Form.tsx
```

Examples:
- `PartsCatalogue.tsx` — automotive parts (existing)
- `FluidOilForm.tsx` — automotive fluids/oils (existing)
- `PlumbingPartsForm.tsx` — plumbing fittings (future)
- `ElectricalPartsForm.tsx` — electrical supplies (future)
- `ServiceCatalogue.tsx` — generic services (shared, all trades)

### How to add a new trade-specific catalogue form

1. Create the form component at `frontend/src/pages/catalogue/{TradeFamily}Form.tsx`
2. The form should POST/PUT to the same `/api/v1/catalogue/products` endpoint
3. Use the shared `catalogue_products` table — trade-specific fields go in the `metadata` JSONB column
4. Register the form in the Catalogue page's tab/section list, gated by trade family
5. Add trade-specific product categories to the seed data

### The `metadata` JSONB column pattern

The `catalogue_products` table has a `metadata` JSONB column for trade-specific fields that don't warrant their own columns. This avoids schema changes per trade.

Examples:
- Automotive: `{"vehicle_compatibility": ["Toyota Corolla 2018-2023"], "oem_number": "04152-YZZA1"}`
- Plumbing: `{"pipe_size_mm": 15, "material": "copper", "fitting_type": "elbow", "pressure_rating": "PN16"}`
- Electrical: `{"voltage": 230, "amperage": 10, "certification": "AS/NZS 3000"}`

The backend accepts and returns this metadata transparently. The frontend form is responsible for structuring it correctly per trade.

## Module & Trade Gating Model

There are TWO independent gating dimensions:

### Dimension 1: Trade Family (from org's trade_category)
Determines WHAT type of trade-specific UI appears. This is set during signup/onboarding and rarely changes.

### Dimension 2: Module Enablement (from org_modules)
Determines WHETHER a feature category is turned on. The org admin toggles these in Settings → Modules.

### The Gating Matrix for Automotive

An automotive org (mechanic/workshop/garage) has these independent toggles:

| What they see | Requires |
|---------------|----------|
| Vehicles sidebar, vehicle profiles, Carjam lookup, rego search | `tradeFamily === 'automotive'` (always on for automotive orgs) |
| Vehicle selector on invoices/quotes/bookings | `tradeFamily === 'automotive'` |
| Parts Catalogue, Fluids/Oils catalogue forms | `tradeFamily === 'automotive'` |
| Inventory sidebar (Stock Levels, Movements, Reorder Alerts) | `inventory` module enabled |
| Purchase Orders | `inventory` module enabled |
| Stock tracking columns on catalogue items | `inventory` module enabled |

This means a mechanic who doesn't want inventory can still:
- Look up vehicles via Carjam
- Add parts/services to invoices and quotes from the catalogue
- Link vehicles to customers and bookings
- Use the parts catalogue to manage their product list

They just won't see stock levels, reorder alerts, or stock movement tracking until they enable the `inventory` module.

### Migration from `vehicles` module to trade family gating

Currently some features are gated behind `ModuleGate module="vehicles"`. This needs to migrate:

| Current gating | New gating | Reason |
|---------------|-----------|--------|
| `ModuleGate module="vehicles"` on Vehicles sidebar | `tradeFamily === 'automotive'` | Vehicles are inherent to automotive, not an optional module |
| `ModuleGate module="vehicles"` on vehicle columns in invoices | `tradeFamily === 'automotive'` | Same — if you're a mechanic, you always have vehicles |
| `ModuleGate module="inventory"` on Inventory sidebar | Keep as-is | Inventory IS optional for all trades |
| `ModuleGate module="inventory"` on stock tracking | Keep as-is | Stock tracking IS optional |

The `vehicles` module in `module_registry` should be kept for backward compatibility but auto-enabled for all automotive orgs. Long-term, vehicle features should check trade family instead of the module toggle.

### Frontend gating pattern (revised)

```tsx
const { tradeFamily } = useTenant()
const inventoryEnabled = useModuleEnabled('inventory')

// Sidebar
{tradeFamily === 'automotive' && <SidebarLink to="/vehicles">Vehicles</SidebarLink>}
{inventoryEnabled && <SidebarLink to="/inventory">Inventory</SidebarLink>}

// Catalogue page — automotive parts only for automotive, services for all
{tradeFamily === 'automotive' && <PartsCatalogue />}
{tradeFamily === 'automotive' && <FluidOilForm />}
<ServiceCatalogue />  {/* all trades */}

// Invoice line item — vehicle column only for automotive
{tradeFamily === 'automotive' && <VehicleColumn />}

// Stock columns in catalogue — only if inventory module is on
{inventoryEnabled && <StockLevelColumn />}
{inventoryEnabled && <ReorderThresholdColumn />}

// Booking form — vehicle selector only for automotive
{tradeFamily === 'automotive' && <VehicleSelector />}
```

## Invoice/Quote/Booking Line Item Integration

When adding line items to invoices, quotes, or bookings:

1. The line item picker searches `catalogue_products` filtered by the org's ID
2. All products appear regardless of trade — the catalogue already only contains products relevant to that org
3. Trade-specific display (e.g., showing vehicle compatibility for automotive parts) is handled by the line item renderer checking the product's `metadata` fields
4. Stock deduction happens through the shared `stock_items` system

## Current Implementation Status

**What EXISTS in the database:**
- `trade_families` table with slugs like `automotive-transport`, `plumbing-gas`, `electrical-mechanical`, etc.
- `trade_categories` table with slugs like `general-automotive`, `plumber`, `electrician`, etc. — each linked to a family via `family_id`
- `organisations.trade_category_id` column (FK to trade_categories) — EXISTS but currently NULL for all orgs
- `module_registry` with `inventory` module registered
- `org_modules` table for per-org module enablement

**What EXISTS in the frontend:**
- `ModuleGate` component and `useModuleGuard` hook for module-based gating
- `ModuleContext` that fetches enabled modules from `/api/v2/modules`
- `TenantContext` that fetches org settings — but does NOT include trade family info yet

**What DOES NOT EXIST yet (needs to be built):**
- `trade_family` field in the org settings API response
- `tradeFamily` in `TenantContext` / `useTenant()`
- Any frontend component that checks trade family for conditional rendering
- `trade_category_id` set on any actual org (all are NULL)

**What needs to happen before trade-family gating works:**
1. Backfill `trade_category_id` on existing orgs (at minimum the demo org)
2. Add `trade_family` and `trade_category` to `GET /api/v1/org/settings` response
3. Expose `tradeFamily` in `TenantContext`
4. Create a `TradeGate` component or use `useTenant().tradeFamily` for conditional rendering
5. Migrate existing `ModuleGate module="vehicles"` checks to trade family checks

The following existing components are built specifically for mechanics/workshops/garages and MUST be gated behind `tradeFamily === 'automotive'`:

- `frontend/src/pages/catalogue/PartsCatalogue.tsx` — automotive parts with OEM numbers, vehicle compatibility
- `frontend/src/pages/catalogue/FluidOilForm.tsx` — engine oils, coolants, brake fluid with viscosity/spec fields
- Vehicle rego columns in inventory list views
- Carjam integration (`app/integrations/carjam.py`) — NZ vehicle data lookup
- Vehicle linking on invoice/quote/booking line items
- `frontend/src/pages/vehicles/` — entire Vehicles section in sidebar

The following are GENERIC and work for all trades as-is:

- `frontend/src/pages/catalogue/ServiceCatalogue.tsx` — labour rates, service items
- All inventory pages (Stock Levels, Usage History, Stock Update Log, Reorder Alerts, Suppliers)
- Invoice creation, line item picker (the picker itself is generic — it pulls from catalogue_products)
- Quote creation and line items
- Booking creation and line items
- Purchase orders

## Bookings, Quotes, and Invoices — Trade Adaptation

Bookings, quotes, and invoices are core features that work for ALL trades. The trade-specific parts are:

### What adapts per trade in these features

| Feature | Generic (all trades) | Automotive-specific | Future trade-specific |
|---------|---------------------|--------------------|-----------------------|
| Invoice line items | Product/service name, qty, price, tax | Vehicle rego column, Carjam part lookup | Pipe size column (plumbing), certification ref (electrical) |
| Quote line items | Same as invoice | Vehicle rego, parts compatibility | Same pattern as invoice |
| Booking form | Customer, date/time, service type, notes | Vehicle selector, odometer reading | Site address (plumbing), switchboard ref (electrical) |
| Line item picker | Search catalogue_products by name/SKU | Filter by vehicle compatibility | Filter by pipe size, material, etc. |

### How to handle this

1. The invoice/quote/booking CREATE and DETAIL pages stay generic
2. Trade-specific fields in line items come from the product's `metadata` JSONB — the renderer checks what metadata keys exist and shows relevant columns
3. Trade-specific form sections (like "Vehicle" on a booking) are conditionally rendered based on trade family
4. The line item picker's search/filter options adapt based on trade family — automotive shows a "Vehicle" filter, plumbing shows a "Pipe Size" filter, etc.

### Pattern for trade-specific sections in shared pages

```tsx
// In BookingForm.tsx
const { tradeFamily } = useTenant()

{/* Generic fields — all trades */}
<CustomerPicker />
<DateTimePicker />
<ServiceTypePicker />
<NotesField />

{/* Automotive-specific — only for mechanics */}
{tradeFamily === 'automotive' && (
  <VehicleSelector />
  <OdometerInput />
)}

{/* Plumbing-specific — only for plumbers */}
{tradeFamily === 'plumbing_gas' && (
  <SiteAddressInput />
  <AccessNotes />
)}
```

## Rules for Future Development

1. NEVER create a separate inventory module per trade — use the single `inventory` module
2. NEVER duplicate inventory pages (Stock Levels, Movements, etc.) per trade
3. NEVER duplicate invoice/quote/booking pages per trade — use conditional rendering
4. Trade-specific catalogue forms MUST write to the same `catalogue_products` table
5. Trade-specific fields go in the `metadata` JSONB column, not new database columns (unless the field is needed for queries/indexes across all trades)
6. Always use `TerminologyContext` for trade-specific labels — don't hardcode "parts" or "fittings"
7. When adding a new trade's catalogue form, check if the org's trade family matches before rendering
8. The `ServiceCatalogue` (labour/service items) is universal — every trade has services
9. Bookings, quotes, and invoices are SHARED — trade-specific sections are conditionally rendered
10. The line item picker is SHARED — trade-specific filters are conditionally added
11. When adding vehicle-specific UI to any page, ALWAYS wrap it in `tradeFamily === 'automotive'` check — NOT `ModuleGate module="vehicles"`
12. The Vehicles sidebar section and all vehicle pages are gated behind `tradeFamily === 'automotive'` (not the vehicles module)
13. The `vehicles` module should be auto-enabled for automotive orgs but the UI gating should use trade family
14. Catalogue sidebar is visible for ALL trades — it contains ServiceCatalogue (universal) plus trade-specific product forms
15. Inventory sidebar is gated behind `inventory` module — it's optional even for mechanics
16. A mechanic without `inventory` module can still use: Carjam, parts catalogue, vehicle profiles, vehicle on invoices/quotes/bookings — they just don't get stock tracking
