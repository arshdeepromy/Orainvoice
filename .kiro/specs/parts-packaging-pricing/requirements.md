# Requirements Document

## Introduction

Add packaging and pricing fields to the Parts Catalogue, bringing it to parity with the Fluids/Oils catalogue. Parts are sold as individual units but purchased in bulk packaging (boxes, cartons, packs, etc.). The system must track purchase price per package, calculate cost per individual unit, and display margin information — mirroring the pricing workflow already established for fluids.

## Glossary

- **Parts_Catalogue**: The organisation-scoped database table and associated UI that stores parts information including pricing, packaging, and stock data.
- **Pricing_Section**: The UI panel within the Parts Catalogue form that displays purchase price, sell price, GST mode, packaging details, and auto-calculated margin fields.
- **GST_Mode**: A three-way toggle controlling tax treatment of prices. Values: "GST Inc." (inclusive), "GST Excl." (exclusive), or "Exempt".
- **Packaging_Type**: The physical container used to package parts for purchase. Values: box, carton, pack, bag, pallet, single.
- **Qty_Per_Pack**: The number of individual parts contained in one packaging unit (e.g., 10 spark plugs per box).
- **Total_Packs**: The number of packaging units in a single purchase order or stock entry.
- **Purchase_Price**: The total price paid for the entire purchase (all packs combined).
- **Cost_Per_Unit**: The calculated cost of one individual part: `purchase_price / (qty_per_pack × total_packs)`.
- **Sell_Price_Per_Unit**: The price charged to the customer for one individual part.
- **Margin**: The difference between Sell_Price_Per_Unit and Cost_Per_Unit in dollars.
- **Margin_Pct**: The margin expressed as a percentage of Sell_Price_Per_Unit: `(margin / sell_price_per_unit) × 100`.
- **Fluids_Catalogue**: The existing Fluids/Oils product catalogue used as the reference model for this feature.

## Requirements

### Requirement 1: Database Schema Extension

**User Story:** As a system administrator, I want the parts catalogue database to support packaging and pricing fields, so that parts can be priced and tracked with the same granularity as fluids.

#### Acceptance Criteria

1. THE Parts_Catalogue SHALL include a `purchase_price` column of type Numeric(12,2) that stores the total purchase price for a packaging order.
2. THE Parts_Catalogue SHALL include a `packaging_type` column of type String(20) that stores one of the allowed values: box, carton, pack, bag, pallet, single.
3. THE Parts_Catalogue SHALL include a `qty_per_pack` column of type Integer that stores the number of individual parts per packaging unit.
4. THE Parts_Catalogue SHALL include a `total_packs` column of type Integer that stores the number of packaging units purchased.
5. THE Parts_Catalogue SHALL include a `cost_per_unit` column of type Numeric(12,4) that stores the auto-calculated cost per individual part.
6. THE Parts_Catalogue SHALL include a `sell_price_per_unit` column of type Numeric(12,4) that stores the explicit sell price per individual part.
7. THE Parts_Catalogue SHALL include a `margin` column of type Numeric(12,4) that stores the calculated dollar margin per unit.
8. THE Parts_Catalogue SHALL include a `margin_pct` column of type Numeric(8,2) that stores the calculated margin percentage.
9. THE Parts_Catalogue SHALL include a `gst_mode` column of type String(10) that replaces the existing `is_gst_exempt` and `gst_inclusive` boolean columns with a single field accepting values: inclusive, exclusive, exempt.
10. THE Parts_Catalogue SHALL retain backward compatibility by keeping the existing `default_price` column functional during the migration period.

### Requirement 2: Cost Per Unit Calculation

**User Story:** As a workshop manager, I want the system to automatically calculate the cost per individual part, so that I can see the true unit cost based on bulk purchase pricing.

#### Acceptance Criteria

1. WHEN a user enters a Purchase_Price, Qty_Per_Pack, and Total_Packs, THE Parts_Catalogue SHALL calculate Cost_Per_Unit as `purchase_price / (qty_per_pack × total_packs)`.
2. WHEN Qty_Per_Pack is zero or not provided, THE Parts_Catalogue SHALL leave Cost_Per_Unit empty and display no calculated value.
3. WHEN Total_Packs is zero or not provided, THE Parts_Catalogue SHALL leave Cost_Per_Unit empty and display no calculated value.
4. WHEN Purchase_Price is not provided, THE Parts_Catalogue SHALL leave Cost_Per_Unit empty and display no calculated value.
5. THE Parts_Catalogue SHALL recalculate Cost_Per_Unit in real time as the user modifies any of the three input fields (Purchase_Price, Qty_Per_Pack, Total_Packs).

### Requirement 3: Margin Calculation

**User Story:** As a workshop manager, I want the system to automatically calculate profit margin, so that I can make informed pricing decisions.

#### Acceptance Criteria

1. WHEN both Sell_Price_Per_Unit and Cost_Per_Unit have valid values, THE Parts_Catalogue SHALL calculate Margin as `sell_price_per_unit - cost_per_unit`.
2. WHEN both Sell_Price_Per_Unit and Cost_Per_Unit have valid values and Sell_Price_Per_Unit is greater than zero, THE Parts_Catalogue SHALL calculate Margin_Pct as `(margin / sell_price_per_unit) × 100`.
3. WHEN Sell_Price_Per_Unit is zero, THE Parts_Catalogue SHALL display Margin_Pct as 0.00.
4. WHEN Cost_Per_Unit is not available, THE Parts_Catalogue SHALL leave Margin and Margin_Pct empty.
5. THE Parts_Catalogue SHALL recalculate Margin and Margin_Pct in real time as the user modifies Sell_Price_Per_Unit or any field that affects Cost_Per_Unit.
6. THE Parts_Catalogue SHALL display Margin formatted as a dollar amount with two decimal places.
7. THE Parts_Catalogue SHALL display Margin_Pct formatted as a percentage with two decimal places.

### Requirement 4: GST Mode Consolidation

**User Story:** As a workshop manager, I want a single GST mode toggle for parts, so that tax handling is consistent with the fluids catalogue.

#### Acceptance Criteria

1. THE Pricing_Section SHALL display a three-way segmented toggle with options: "GST Inc.", "GST Excl.", "Exempt".
2. WHEN a user selects a GST_Mode value, THE Parts_Catalogue SHALL store the selected value as a single `gst_mode` string field (inclusive, exclusive, or exempt).
3. WHEN loading an existing part that uses the legacy `is_gst_exempt` and `gst_inclusive` boolean fields, THE Parts_Catalogue SHALL map the legacy values to the equivalent GST_Mode value.
4. THE Parts_Catalogue SHALL treat `is_gst_exempt = true` as GST_Mode "exempt".
5. WHILE `is_gst_exempt` is false and `gst_inclusive` is true, THE Parts_Catalogue SHALL treat the legacy values as GST_Mode "inclusive".
6. WHILE `is_gst_exempt` is false and `gst_inclusive` is false, THE Parts_Catalogue SHALL treat the legacy values as GST_Mode "exclusive".

### Requirement 5: Packaging Type Selection

**User Story:** As a workshop manager, I want to specify the packaging type for parts, so that I can accurately describe how parts are purchased and stored.

#### Acceptance Criteria

1. THE Pricing_Section SHALL display a Packaging_Type selector with options: box, carton, pack, bag, pallet, single.
2. WHEN a user selects "single" as the Packaging_Type, THE Parts_Catalogue SHALL default Qty_Per_Pack to 1 and Total_Packs to 1.
3. WHEN a user selects any Packaging_Type other than "single", THE Parts_Catalogue SHALL allow the user to enter Qty_Per_Pack and Total_Packs as positive integers.
4. THE Parts_Catalogue SHALL validate that Qty_Per_Pack is a positive integer when provided.
5. THE Parts_Catalogue SHALL validate that Total_Packs is a positive integer when provided.

### Requirement 6: Pricing Section UI

**User Story:** As a workshop manager, I want a pricing section in the parts form that matches the fluids form layout, so that the pricing workflow is consistent across catalogue types.

#### Acceptance Criteria

1. THE Pricing_Section SHALL display input fields for: Purchase_Price, Sell_Price_Per_Unit, Packaging_Type, Qty_Per_Pack, and Total_Packs.
2. THE Pricing_Section SHALL display the GST_Mode segmented toggle.
3. THE Pricing_Section SHALL display read-only auto-calculated fields for: Cost_Per_Unit, Margin, and Margin_Pct.
4. THE Pricing_Section SHALL format all currency values using the NZD currency format (e.g., $12.50).
5. WHEN the user has not yet entered sufficient data for calculations, THE Pricing_Section SHALL display dashes or empty placeholders in the calculated fields instead of $0.00.
6. THE Pricing_Section SHALL display a label "Cost/Unit" for the Cost_Per_Unit field, "Margin $" for the Margin field, and "Margin %" for the Margin_Pct field.

### Requirement 7: Backend API Support

**User Story:** As a frontend developer, I want the parts API to accept and return the new packaging and pricing fields, so that the form can persist and retrieve the data.

#### Acceptance Criteria

1. WHEN creating a new part, THE Parts_Catalogue API SHALL accept the fields: purchase_price, packaging_type, qty_per_pack, total_packs, sell_price_per_unit, and gst_mode.
2. WHEN updating an existing part, THE Parts_Catalogue API SHALL accept partial updates to any of the new packaging and pricing fields.
3. WHEN returning a part record, THE Parts_Catalogue API SHALL include all packaging and pricing fields (purchase_price, packaging_type, qty_per_pack, total_packs, cost_per_unit, sell_price_per_unit, margin, margin_pct, gst_mode) in the response.
4. THE Parts_Catalogue API SHALL compute cost_per_unit, margin, and margin_pct server-side before persisting the record.
5. IF a create or update request provides a non-positive value for qty_per_pack or total_packs, THEN THE Parts_Catalogue API SHALL return a 422 validation error with a descriptive message.
6. IF a create or update request provides a packaging_type value not in the allowed list, THEN THE Parts_Catalogue API SHALL return a 422 validation error with a descriptive message.

### Requirement 8: Database Migration

**User Story:** As a system administrator, I want a safe database migration that adds the new columns without data loss, so that existing parts data remains intact.

#### Acceptance Criteria

1. THE Migration SHALL add all new columns (purchase_price, packaging_type, qty_per_pack, total_packs, cost_per_unit, sell_price_per_unit, margin, margin_pct, gst_mode) to the parts_catalogue table as nullable columns.
2. THE Migration SHALL populate the gst_mode column for existing rows based on the legacy is_gst_exempt and gst_inclusive boolean values.
3. THE Migration SHALL copy existing default_price values into sell_price_per_unit for all existing rows.
4. THE Migration SHALL set packaging_type to "single", qty_per_pack to 1, and total_packs to 1 for all existing rows that have no packaging data.
5. THE Migration SHALL provide a downgrade path that removes the new columns without affecting existing data.
6. THE Migration SHALL preserve all existing column values and constraints on the parts_catalogue table.
