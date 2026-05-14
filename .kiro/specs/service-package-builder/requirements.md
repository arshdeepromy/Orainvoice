# Requirements Document

## Introduction

The Service Package Builder allows users to create bundled service items that combine labour (the existing items catalogue entry) with inventory components (parts, fluids, tyres). A package item is still an `items_catalogue` entry but carries additional metadata linking it to specific inventory products and quantities. The system calculates total cost from live inventory purchase prices and displays profit margin against the item's sell price. When a package is used on an invoice, inventory is deducted and cost is tracked for profit reporting.

**Module Gate:** This feature requires BOTH the `vehicles` AND `inventory` modules to be enabled. The "Include Inventory Usage" checkbox and all package builder functionality SHALL only be visible when both modules are active for the organisation. Organisations without both modules see the standard New Item form with no package options.

**Platform:** Package creation and editing is desktop-only (web frontend). Package items can be used on invoices from both desktop and mobile apps — the mobile app treats them as standard catalogue items with automatic cost tracking.

## Glossary

- **Package_Builder**: The UI component within the New Item modal that enables users to compose a service package from inventory components.
- **Package_Item**: An `items_catalogue` entry flagged as a package, with linked inventory components stored as package metadata.
- **Inventory_Component**: A single line within a package specifying a catalogue product (part, fluid, or tyre), its quantity, and its resolved cost from current inventory.
- **Fluid_Selector**: The sub-form within the Package Builder that allows selection of fluid type (`oil` or `non-oil`), oil type, grade, and volume in litres.
- **Package_Cost**: The sum of all inventory component costs (purchase price × quantity) for a package.
- **Package_Profit**: The difference between the Package Item sell price (default_price) and the Package Cost.
- **Package_Preview**: A read-only summary view showing all components, their current inventory prices, total cost, and profit.
- **Items_Page**: The Items Catalogue management page at `frontend/src/pages/items/ItemsCatalogue.tsx`.
- **Catalogue_API**: The backend API endpoints under `/api/v1/catalogue/` that manage items, parts, and fluids.

## Technical Context

### Fluid Type Values (from `fluid_oil_products` table)
- `fluid_type`: `"oil"` or `"non-oil"` (validated by schema pattern `^(oil|non-oil)$`)
- `oil_type` (when fluid_type is "oil"): `engine`, `hydraulic`, `brake`, `gear`, `transmission`, `power_steering`
- `grade` (for engine oils): e.g., `5W-30`, `10W-40`, `15W-40`
- `synthetic_type`: `full_synthetic`, `semi_synthetic`, `mineral`

### Cost Data Sources
- **Parts/Tyres**: Cost comes from `stock_items.purchase_price` or `stock_items.cost_per_unit` (branch-specific). Falls back to `parts_catalogue.cost_per_unit` if no stock item exists.
- **Fluids**: Cost comes from `stock_items.cost_per_unit` for the fluid stock item. Falls back to `fluid_oil_products.cost_per_unit`.
- **Priority**: stock_items (branch-specific, most accurate) → catalogue-level defaults

### Role Values
- Cost/profit visibility restricted to: `org_admin`, `global_admin`
- Other roles (`branch_admin`, `salesperson`, `kiosk`) cannot see cost data

## Requirements

### Requirement 1: Include Inventory Usage Toggle

**User Story:** As a user, I want a checkbox labelled "Include Inventory Usage" in the New Item modal, so that I can optionally attach inventory components to a service item.

#### Acceptance Criteria

1. THE "Include Inventory Usage" checkbox SHALL only be rendered when BOTH the `vehicles` AND `inventory` modules are enabled for the organisation (checked via `useModules().isEnabled('vehicles') && useModules().isEnabled('inventory')`).
2. WHEN the user opens the New Item modal on the Items Page AND both required modules are enabled, THE Package_Builder SHALL display an unchecked checkbox labelled "Include Inventory Usage" below the existing form fields.
3. WHEN the user checks the "Include Inventory Usage" checkbox, THE Package_Builder SHALL reveal the inventory type selection panel.
4. WHEN the user unchecks the "Include Inventory Usage" checkbox, THE Package_Builder SHALL hide the inventory type selection panel and clear all inventory component selections.
5. WHEN either required module is NOT enabled, THE New Item modal SHALL render the standard form without the "Include Inventory Usage" checkbox (no visual change from current behaviour).

### Requirement 2: Inventory Type Selection

**User Story:** As a user, I want to choose which types of inventory to include in my package (parts, fluid, tyre), so that I can compose a package from different inventory categories.

#### Acceptance Criteria

1. WHILE the "Include Inventory Usage" checkbox is checked, THE Package_Builder SHALL display checkboxes for three inventory types: "Parts", "Fluid", and "Tyre".
2. WHEN the user checks the "Parts" checkbox, THE Package_Builder SHALL display a parts selection sub-form allowing the user to search and add one or more parts from the parts catalogue.
3. WHEN the user checks the "Tyre" checkbox, THE Package_Builder SHALL display a tyre selection sub-form allowing the user to search and add one or more tyres from the parts catalogue where `part_type = 'tyre'`.
4. WHEN the user checks the "Fluid" checkbox, THE Package_Builder SHALL display the Fluid Selector sub-form.
5. WHEN the user unchecks any inventory type checkbox, THE Package_Builder SHALL remove the corresponding sub-form and clear its selections.

### Requirement 3: Fluid Selection

**User Story:** As a user, I want to select fluids by type (oil or non-oil), pick specific oil types and grades, and specify litres needed, so that I can accurately define fluid usage in my service package.

#### Acceptance Criteria

1. WHILE the "Fluid" checkbox is checked, THE Fluid_Selector SHALL allow the user to add multiple fluid entries to the package.
2. WHEN the user adds a fluid entry, THE Fluid_Selector SHALL present a choice between "Oil" (`fluid_type = "oil"`) and "Non-Oil" (`fluid_type = "non-oil"`) fluid types.
3. WHEN the user selects "Oil", THE Fluid_Selector SHALL display a dropdown of available oil types: engine, hydraulic, brake, gear, transmission, power_steering — fetched from the `fluid_oil_products` catalogue where `fluid_type = 'oil'` and `is_active = true`, grouped by distinct `oil_type` values.
4. WHEN the user selects an oil type (e.g., engine), THE Fluid_Selector SHALL display available grades/products for that oil type from the `fluid_oil_products` catalogue, showing product name, brand, and grade.
5. WHEN the user selects "Non-Oil", THE Fluid_Selector SHALL display a dropdown of available non-oil fluid products fetched from the `fluid_oil_products` catalogue where `fluid_type = 'non-oil'` and `is_active = true`.
6. THE Fluid_Selector SHALL require the user to specify the volume in litres for each fluid entry.
7. THE Fluid_Selector SHALL display the current `cost_per_unit` (cost per litre) from the matched stock item (or `fluid_oil_products` record as fallback) next to each fluid entry.
8. IF no matching fluid product exists in the catalogue for the selected type, THEN THE Fluid_Selector SHALL display a message "No matching product found in inventory" and prevent that entry from being saved.

### Requirement 4: Parts and Tyre Selection

**User Story:** As a user, I want to search and select parts or tyres from my existing catalogue and specify quantities, so that I can include physical components in my service package.

#### Acceptance Criteria

1. WHILE the "Parts" checkbox is checked, THE Package_Builder SHALL display a searchable dropdown populated from the `parts_catalogue` where `part_type = 'part'` and `is_active = true`, scoped to the user's organisation.
2. WHEN the user selects a part, THE Package_Builder SHALL add it to the package components list with a default quantity of 1.
3. THE Package_Builder SHALL allow the user to adjust the quantity for each selected part.
4. THE Package_Builder SHALL display the cost from the linked `stock_items.purchase_price` (or `stock_items.cost_per_unit`, or `parts_catalogue.cost_per_unit` as fallback) next to each selected part.
5. WHILE the "Tyre" checkbox is checked, THE Package_Builder SHALL display a searchable dropdown populated from the `parts_catalogue` where `part_type = 'tyre'` and `is_active = true`.
6. WHEN the user selects a tyre, THE Package_Builder SHALL add it to the package components list with a default quantity of 1.
7. THE Package_Builder SHALL allow the user to adjust the quantity for each selected tyre.
8. THE Package_Builder SHALL display the cost from the linked stock item next to each selected tyre.

### Requirement 5: Live Cost Calculation

**User Story:** As a user, I want to see the total cost of my package calculated from current inventory purchase prices, so that I can understand my cost basis before setting a sell price.

#### Acceptance Criteria

1. WHILE inventory components are selected, THE Package_Builder SHALL calculate the Package_Cost as the sum of (cost_per_unit × quantity) for all parts and tyres plus (cost_per_unit × litres) for all fluid entries.
2. WHEN any component quantity or selection changes, THE Package_Builder SHALL recalculate and display the updated Package_Cost within 200ms.
3. THE Package_Builder SHALL display the Package_Cost in a summary section labelled "Total Package Cost".
4. THE Package_Builder SHALL display the Package_Profit calculated as (default_price − Package_Cost) in the summary section labelled "Profit".
5. IF the Package_Profit is negative, THEN THE Package_Builder SHALL display the profit value in red with a warning indicator.
6. THE Package_Builder SHALL fetch current cost values from the Catalogue_API at the time of package creation to ensure costs reflect live inventory pricing.
7. THE cost summary section SHALL only be visible to users with `org_admin` or `global_admin` roles.

### Requirement 6: Package Preview

**User Story:** As a user, I want to preview the full package details including all components, their current prices, total cost, and profit before saving, so that I can verify the package composition.

#### Acceptance Criteria

1. WHEN the user has selected at least one inventory component, THE Package_Builder SHALL display a "Preview Package" button.
2. WHEN the user clicks "Preview Package", THE Package_Builder SHALL display a read-only summary showing: each component name, type (part/fluid/tyre), quantity or litres, unit cost, and line total.
3. THE Package_Preview SHALL display the total litres for all fluid entries combined.
4. THE Package_Preview SHALL display the Package_Cost (total of all component costs).
5. THE Package_Preview SHALL display the sell price (default_price entered by the user).
6. THE Package_Preview SHALL display the Package_Profit (sell price minus Package_Cost).
7. THE Package_Preview SHALL display the `current_stock_volume` (from `fluid_oil_products` or `stock_items`) for each fluid component so the user can verify inventory availability.
8. THE Package_Preview SHALL display the `current_quantity` (from `stock_items`) for each part and tyre component so the user can verify inventory availability.
9. IF any component has zero or insufficient stock, THE Package_Preview SHALL highlight that component with a warning badge "Low Stock" or "Out of Stock".

### Requirement 7: Package Persistence

**User Story:** As a user, I want my service package to be saved as a catalogue item with its component metadata, so that I can reuse it on invoices.

#### Acceptance Criteria

1. WHEN the user saves a package item, THE Catalogue_API SHALL create an `items_catalogue` record with the standard fields (name, description, default_price, gst_mode, category) and a flag indicating it is a package (e.g., `is_package = true` or a JSONB `package_components` field).
2. WHEN the user saves a package item, THE Catalogue_API SHALL persist the inventory components as package metadata linked to the `items_catalogue` record.
3. THE Catalogue_API SHALL store each component with: `catalogue_item_id` (the part or fluid product ID), `catalogue_type` (part/tyre/fluid), `quantity` or `volume`, and the `cost_per_unit` at time of creation (as a snapshot for reference).
4. WHEN the user edits an existing package item, THE Package_Builder SHALL load the saved components and allow modification.
5. WHEN the user updates a package item, THE Catalogue_API SHALL replace the existing component metadata with the updated set.
6. IF the user removes the "Include Inventory Usage" flag from an existing package item, THEN THE Catalogue_API SHALL delete the associated component metadata and convert the item back to a standard catalogue item.
7. THE package metadata storage approach (JSONB column on `items_catalogue` vs separate junction table) SHALL be determined in the design document.

### Requirement 8: Package Usage on Invoice

**User Story:** As a user, I want the package cost to be automatically tracked when I use a package item on an invoice, so that profit reporting is accurate.

#### Acceptance Criteria

1. WHEN a package item is added to an invoice, THE Invoice_System SHALL record the `cost_price` on the line item as the sum of current inventory costs for all package components (recalculated at invoice time from live prices, not the snapshot from package creation).
2. WHEN a package item is used on an issued invoice (not draft), THE Invoice_System SHALL deduct inventory quantities for each component: parts and tyres by quantity from `stock_items`, fluids by volume from `stock_items.current_quantity` (fluid stock items track volume).
3. IF any component has insufficient stock at invoice time, THEN THE Invoice_System SHALL warn the user with a message identifying which components are low but still allow the invoice to proceed.
4. THE Invoice_System SHALL record fluid usage entries in the invoice `fluid_usage` tracking within `invoice_data_json` (consistent with existing fluid usage behaviour), including `cost_per_litre` and `total_cost`.
5. WHEN a package item is added to a **quote**, THE system SHALL show cost/profit preview but SHALL NOT deduct inventory. Inventory deduction only occurs when the quote is converted to an invoice and issued.

### Requirement 9: Package Display on Items Page

**User Story:** As a user, I want to distinguish package items from standard items in the items catalogue list, so that I can quickly identify bundled services.

#### Acceptance Criteria

1. THE Items_Page SHALL display a visual badge labelled "Package" next to items that have inventory components attached.
2. WHEN the user clicks on a package item in the list, THE Items_Page SHALL open the edit modal with the Package Builder pre-populated with the saved components.
3. THE Items_Page SHALL display the Package_Cost and Package_Profit columns for package items (visible only to `org_admin` and `global_admin` roles).
4. THE Items_Page SHALL support duplicating a package item (creating a copy with all components) to allow users to create variations (e.g., "Full Service - 5W30" vs "Full Service - 10W40").

### Requirement 10: Access Control

**User Story:** As a business owner, I want package cost and profit information restricted to admin roles, so that sensitive pricing data is not exposed to all staff.

#### Acceptance Criteria

1. THE Package_Builder SHALL display cost_per_unit, Package_Cost, and Package_Profit only to users with `org_admin` or `global_admin` roles.
2. WHILE a user with a non-admin role (`branch_admin`, `salesperson`) creates or edits a package item, THE Package_Builder SHALL hide cost and profit figures but still allow component selection and quantity entry.
3. THE Catalogue_API SHALL omit cost and profit fields from package responses for users without `org_admin` or `global_admin` roles.
4. THE `kiosk` role SHALL NOT have access to the Items Page or Package Builder.

### Requirement 11: Component Availability & Deletion Handling

**User Story:** As a user, I want to be informed when inventory products referenced in my package are no longer available, so that I can update the package accordingly.

#### Acceptance Criteria

1. WHEN a package item is opened for editing AND one or more referenced catalogue products have been deactivated or deleted, THE Package_Builder SHALL display a warning banner listing the unavailable components.
2. THE Package_Builder SHALL mark unavailable components with a strikethrough and "Unavailable" badge, allowing the user to remove them or replace them.
3. WHEN a package item is used on an invoice AND a component is unavailable, THE Invoice_System SHALL skip that component's inventory deduction but still include its last-known cost in the cost_price calculation (using the snapshot cost stored in the package metadata).
4. THE Items_Page SHALL display a warning icon on package items that have one or more unavailable components.

## Non-Functional Requirements

- **Performance**: Package cost calculation must complete within 200ms on the frontend (no API call needed — costs are fetched when components are selected).
- **Backward Compatibility**: Existing `items_catalogue` entries are unaffected. The package flag defaults to false/absent for all existing items.
- **No Migration Risk**: Package metadata uses a nullable JSONB column or separate table — no existing columns are modified.
- **Mobile Compatibility**: Package items appear as standard catalogue items on mobile. Cost tracking works automatically when used on mobile invoices (the backend handles it regardless of client).
