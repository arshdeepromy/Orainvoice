# Requirements Document

## Introduction

The current inventory Stock Levels page displays ALL catalogue items (parts, tyres, fluids/oils) regardless of whether they have been explicitly stocked, causing confusion where packaging quantities (e.g. "48.0 L") are mistaken for actual stock levels. This feature redesigns inventory to enforce a clear separation between the catalogue (a product database for selection) and inventory (explicitly stocked items). A new "Add to Stock" workflow allows users to selectively bring catalogue items into inventory with quantity, reason, optional barcode/serial tracking, and auto-populated supplier information.

## Glossary

- **Catalogue**: The product database containing Parts, Tyres, and Fluids/Oils entries used for selection when creating jobs, invoices, or stock entries. Stored in `parts_catalogue` and `fluid_oil_products` tables.
- **Inventory**: The set of catalogue items that have been explicitly added to stock tracking via the "Add to Stock" flow. Only these items appear on the Stock Levels page.
- **Stock_Item**: A record linking a Catalogue entry to the inventory system, carrying its own quantity, barcode/serial, supplier override, and audit trail.
- **Stock_Levels_Page**: The frontend page (`StockLevels.tsx`) that displays current inventory quantities, thresholds, and statuses.
- **Add_To_Stock_Modal**: The multi-step UI modal triggered by the "Add to Stock" button, guiding users through category selection, catalogue item picking, and stock entry details.
- **Category_Selector**: The first step of the Add_To_Stock_Modal showing category icons/images for Parts, Tyres, and Fluids/Oils.
- **Catalogue_Picker**: A searchable dropdown/list within the Add_To_Stock_Modal that lets users find and select a specific catalogue item.
- **Stock_Movement**: An audit record capturing each change to a Stock_Item's quantity, including the reason and who performed it.
- **Barcode_Field**: An optional text field on a Stock_Item for storing a barcode, product code, or serial number for tracking purposes.
- **Supplier**: A vendor record from the `suppliers` table, linked to catalogue items and optionally overridden on Stock_Items.

## Requirements

### Requirement 1: Catalogue and Inventory Separation

**User Story:** As a workshop manager, I want the Stock Levels page to show only items I have explicitly added to stock, so that I am not confused by catalogue packaging quantities appearing as stock levels.

#### Acceptance Criteria

1. THE Stock_Levels_Page SHALL display only Stock_Items that have been explicitly added to inventory via the Add_To_Stock_Modal or stock import.
2. WHEN a new catalogue item is created in the Catalogue, THE Stock_Levels_Page SHALL not include that item until a user explicitly adds the item to inventory.
3. THE Stock_Levels_Page SHALL not display catalogue packaging quantities (e.g. `qty_per_pack`, `total_volume`) as current stock levels.
4. WHEN a Stock_Item is removed from inventory, THE Stock_Levels_Page SHALL no longer display that item.

### Requirement 2: Add to Stock Button

**User Story:** As a workshop manager, I want an "Add to Stock" button on the Stock Levels page, so that I can begin the process of adding a catalogue item to inventory tracking.

#### Acceptance Criteria

1. THE Stock_Levels_Page SHALL display an "Add to Stock" button in the page header area.
2. WHEN a user clicks the "Add to Stock" button, THE Stock_Levels_Page SHALL open the Add_To_Stock_Modal.
3. THE "Add to Stock" button SHALL be visible and accessible regardless of whether the inventory is empty or populated.

### Requirement 3: Category Selection Step

**User Story:** As a workshop manager, I want to choose a product category (Parts, Tyres, Fluids/Oils) when adding stock, so that I can quickly narrow down to the right catalogue section.

#### Acceptance Criteria

1. WHEN the Add_To_Stock_Modal opens, THE Add_To_Stock_Modal SHALL display the Category_Selector as the first step.
2. THE Category_Selector SHALL display three selectable options: Parts, Tyres, and Fluids/Oils, each with a distinct icon or image.
3. WHEN a user selects a category, THE Add_To_Stock_Modal SHALL advance to the Catalogue_Picker filtered to that category.
4. THE Category_Selector SHALL allow the user to navigate back from the Catalogue_Picker to change the selected category.

### Requirement 4: Catalogue Item Picker

**User Story:** As a workshop manager, I want to search and select a specific catalogue item after choosing a category, so that I can add the correct product to my inventory.

#### Acceptance Criteria

1. WHEN a category is selected, THE Catalogue_Picker SHALL display a searchable list of active catalogue items in that category.
2. THE Catalogue_Picker SHALL support searching by item name, part number, brand, and description.
3. WHEN a user selects a catalogue item from the Catalogue_Picker, THE Add_To_Stock_Modal SHALL advance to the stock details entry step.
4. IF the selected category contains no active catalogue items, THEN THE Catalogue_Picker SHALL display a message indicating no items are available and suggest adding items to the catalogue first.
5. WHEN a catalogue item has already been added to inventory, THE Catalogue_Picker SHALL indicate that the item is already in stock.

### Requirement 5: Stock Details Entry

**User Story:** As a workshop manager, I want to enter the quantity, reason, and optional barcode when adding an item to stock, so that I have accurate records of why and how much inventory was added.

#### Acceptance Criteria

1. WHEN a catalogue item is selected, THE Add_To_Stock_Modal SHALL display a form with fields for: quantity, reason for adding, and barcode/code/serial number.
2. THE Add_To_Stock_Modal SHALL require the user to enter a quantity greater than zero before submission.
3. THE Add_To_Stock_Modal SHALL require the user to select or enter a reason for adding stock (e.g. "Purchase Order received", "Initial stock count", "Transfer in").
4. THE Add_To_Stock_Modal SHALL provide the barcode/code/serial number field as optional.
5. WHEN the user submits the stock details form, THE System SHALL create a new Stock_Item record linking the catalogue item to inventory with the provided quantity, reason, and barcode.
6. WHEN the user submits the stock details form, THE System SHALL create a Stock_Movement audit record capturing the initial quantity, reason, and the user who performed the action.

### Requirement 6: Supplier Auto-Population

**User Story:** As a workshop manager, I want the supplier to be automatically filled from the catalogue item when adding stock, so that I do not have to re-enter supplier information manually.

#### Acceptance Criteria

1. WHEN a catalogue item with an associated supplier is selected, THE Add_To_Stock_Modal SHALL auto-populate the supplier field with the catalogue item's supplier name.
2. THE Add_To_Stock_Modal SHALL allow the user to change the auto-populated supplier to a different supplier from the suppliers list.
3. THE Add_To_Stock_Modal SHALL allow the user to clear the supplier field if no supplier applies.
4. WHEN a catalogue item has no associated supplier, THE Add_To_Stock_Modal SHALL leave the supplier field empty and allow the user to optionally select one.

### Requirement 7: Barcode/Code/Serial Number Tracking

**User Story:** As a workshop manager, I want to optionally record a barcode, product code, or serial number for stocked items, so that I can track and identify physical inventory more easily.

#### Acceptance Criteria

1. THE Stock_Item SHALL include an optional Barcode_Field for storing a barcode, product code, or serial number.
2. THE Stock_Levels_Page SHALL display the Barcode_Field value for each Stock_Item that has one.
3. THE Stock_Levels_Page SHALL support searching and filtering by barcode/code/serial number values.
4. WHEN a user edits a Stock_Item, THE System SHALL allow updating the Barcode_Field value.

### Requirement 8: Stock Item Data Model

**User Story:** As a developer, I want a dedicated stock item data model separate from the catalogue, so that inventory tracking is decoupled from the product database.

#### Acceptance Criteria

1. THE System SHALL store Stock_Items in a dedicated database table separate from the catalogue tables (`parts_catalogue`, `fluid_oil_products`).
2. THE Stock_Item record SHALL reference the source catalogue item by ID and catalogue type (part, tyre, or fluid).
3. THE Stock_Item record SHALL store: current quantity, minimum threshold, reorder quantity, supplier override ID, barcode/code/serial, and timestamps.
4. THE System SHALL enforce a unique constraint so that each catalogue item can have at most one Stock_Item record per organisation.
5. THE Stock_Item record SHALL be scoped to an organisation via an `org_id` foreign key.

### Requirement 9: Stock Levels API Refactor

**User Story:** As a developer, I want the stock levels API to query from the dedicated stock items table instead of the catalogue tables, so that only explicitly stocked items are returned.

#### Acceptance Criteria

1. THE inventory stock levels API endpoint SHALL return only Stock_Items from the dedicated stock items table.
2. THE inventory stock levels API endpoint SHALL not query the `parts_catalogue` or `fluid_oil_products` tables for stock level data.
3. THE inventory stock levels API endpoint SHALL include the catalogue item name, part number, brand, and type in each response record by joining to the catalogue tables.
4. THE inventory stock levels API endpoint SHALL include the Barcode_Field value in each response record.
5. WHEN a Stock_Item's quantity falls at or below the minimum threshold, THE inventory stock levels API endpoint SHALL flag that item as below threshold.

### Requirement 10: Add to Stock API Endpoint

**User Story:** As a developer, I want an API endpoint to create a new Stock_Item from a catalogue item, so that the frontend Add_To_Stock_Modal can persist stock entries.

#### Acceptance Criteria

1. WHEN a valid request is received with catalogue item ID, catalogue type, quantity, reason, and optional barcode and supplier ID, THE add-to-stock API endpoint SHALL create a Stock_Item record and return the created record.
2. WHEN a valid request is received, THE add-to-stock API endpoint SHALL create a corresponding Stock_Movement audit record with the initial quantity and reason.
3. IF a Stock_Item already exists for the given catalogue item and organisation, THEN THE add-to-stock API endpoint SHALL return an error indicating the item is already in stock.
4. IF the referenced catalogue item does not exist or is inactive, THEN THE add-to-stock API endpoint SHALL return an error indicating the catalogue item is not valid.
5. THE add-to-stock API endpoint SHALL validate that the quantity is greater than zero.
