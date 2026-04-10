# Requirements Document

## Introduction

This feature enhances the "Add to Stock" flow in the Inventory Stock Levels page so that users can create catalogue items inline when the desired item does not yet exist. Currently, if a user searches the catalogue during stock addition and finds no matching item, the flow dead-ends with a message to "Add items to the catalogue first." This forces the user to leave the inventory page, navigate to the Catalogue module, create the item, and return — a disruptive multi-step detour.

The enhancement adds a "+ Create New [Type]" action inside the existing AddToStockModal's catalogue picker step. Clicking it reveals a compact inline form that collects the minimum fields needed to create a usable catalogue entry. On submission, the system creates the catalogue item AND the stock entry in a single action, then auto-selects the newly created item so the user can continue without re-searching.

## Glossary

- **AddToStockModal**: The existing React modal component (`frontend/src/components/inventory/AddToStockModal.tsx`) that guides users through category selection, catalogue item picking, and stock details entry.
- **CataloguePicker**: The second step of the AddToStockModal where users search and select an existing catalogue item.
- **InlineCreateForm**: The new compact form rendered inside the CataloguePicker step that allows users to create a catalogue item without leaving the modal.
- **Catalogue_API**: The backend FastAPI endpoints that create catalogue entries: `POST /api/v1/catalogue/parts` for parts/tyres, `POST /api/v1/catalogue/fluids` for fluids/oils, and `POST /api/v1/catalogue/items` for services.
- **Stock_API**: The backend FastAPI endpoint `POST /api/v1/inventory/stock-items` that creates a stock item linked to a catalogue entry.
- **Packaging_Quantity**: The number of individual units that come in a single package (e.g., "Box of 10 brake pads" means qty_per_pack = 10). During inline creation, this value is inferred from the stock quantity the user enters.
- **Category**: One of the four item types supported by the stock system: Part, Tyre, Fluid/Oil, or Service.
- **Trade_Family**: The business type (e.g., automotive-transport, electrical, plumbing) that gates which categories are visible to the user.

## Requirements

### Requirement 1: Inline Create Button Visibility

**User Story:** As an inventory manager, I want to see a "+ Create New [Type]" button in the catalogue picker, so that I can create a missing catalogue item without leaving the Add to Stock flow.

#### Acceptance Criteria

1. WHEN the CataloguePicker displays search results, THE AddToStockModal SHALL display a "+ Create New [Category]" button below the results list, where [Category] is the currently selected category label (e.g., "Part", "Tyre", "Fluid/Oil").
2. WHEN the CataloguePicker displays zero search results, THE AddToStockModal SHALL display the "+ Create New [Category]" button in place of the "No active items found" dead-end message.
3. WHILE the user has not yet selected a category, THE AddToStockModal SHALL NOT display the "+ Create New [Category]" button.
4. THE AddToStockModal SHALL respect Trade_Family gating for the "+ Create New [Category]" button, displaying it only for categories that are visible to the user's trade family.

### Requirement 2: Inline Create Form — Parts

**User Story:** As an inventory manager, I want a compact form to create a new Part catalogue entry inline, so that I can quickly add a part and stock it in one step.

#### Acceptance Criteria

1. WHEN the user clicks "+ Create New Part", THE InlineCreateForm SHALL display input fields for: name (required), sell price per unit (required), GST mode (required, default "exclusive"), part number (optional), brand (optional), and description (optional).
2. THE InlineCreateForm SHALL NOT display the full catalogue form fields (category search, supplier multi-select, packaging breakdown, tyre dimensions, min stock threshold, reorder quantity) — those remain available on the full Catalogue page for later editing.
3. WHEN the user submits the InlineCreateForm for a Part, THE AddToStockModal SHALL send a POST request to the Catalogue_API (`/api/v1/catalogue/parts`) with `part_type` set to "part".
4. IF the Catalogue_API returns a validation error, THEN THE InlineCreateForm SHALL display the error message inline without closing the form.

### Requirement 3: Inline Create Form — Tyres

**User Story:** As an inventory manager, I want a compact form to create a new Tyre catalogue entry inline, so that I can quickly add a tyre and stock it in one step.

#### Acceptance Criteria

1. WHEN the user clicks "+ Create New Tyre", THE InlineCreateForm SHALL display input fields for: name (required), sell price per unit (required), GST mode (required, default "exclusive"), tyre width (optional), tyre profile (optional), tyre rim diameter (optional), and brand (optional).
2. WHEN the user submits the InlineCreateForm for a Tyre, THE AddToStockModal SHALL send a POST request to the Catalogue_API (`/api/v1/catalogue/parts`) with `part_type` set to "tyre".
3. IF the Catalogue_API returns a validation error, THEN THE InlineCreateForm SHALL display the error message inline without closing the form.

### Requirement 4: Inline Create Form — Fluids/Oils

**User Story:** As an inventory manager, I want a compact form to create a new Fluid/Oil catalogue entry inline, so that I can quickly add a fluid product and stock it in one step.

#### Acceptance Criteria

1. WHEN the user clicks "+ Create New Fluid/Oil", THE InlineCreateForm SHALL display input fields for: product name (required), sell price per unit (required), GST mode (required, default "exclusive"), fluid type (required, "oil" or "non-oil"), oil type (optional, shown when fluid_type is "oil"), grade (optional), and brand (optional).
2. WHEN the user submits the InlineCreateForm for a Fluid/Oil, THE AddToStockModal SHALL send a POST request to the Catalogue_API (`/api/v1/catalogue/fluids`).
3. IF the Catalogue_API returns a validation error, THEN THE InlineCreateForm SHALL display the error message inline without closing the form.

### Requirement 5: Inline Create Form — Services

**User Story:** As an inventory manager, I want a compact form to create a new Service catalogue entry inline, so that I can quickly add a service and stock it in one step.

#### Acceptance Criteria

1. WHEN the user clicks "+ Create New Service", THE InlineCreateForm SHALL display input fields for: name (required), default price (required), GST mode (required, default "exclusive"), and description (optional).
2. WHEN the user submits the InlineCreateForm for a Service, THE AddToStockModal SHALL send a POST request to the Catalogue_API (`/api/v1/catalogue/items`).
3. IF the Catalogue_API returns a validation error, THEN THE InlineCreateForm SHALL display the error message inline without closing the form.

### Requirement 6: Combined Catalogue + Stock Creation

**User Story:** As an inventory manager, I want the system to create both the catalogue entry and the stock entry in one action, so that I do not have to perform two separate steps.

#### Acceptance Criteria

1. WHEN the InlineCreateForm is submitted successfully and the Catalogue_API returns the new catalogue item, THE AddToStockModal SHALL automatically proceed to the stock details step (Step 3) with the newly created item pre-selected.
2. THE AddToStockModal SHALL populate the stock details form with the catalogue item's data (name, sell price, brand, etc.) exactly as it does when a user selects an existing catalogue item.
3. WHEN the user completes the stock details step and submits, THE AddToStockModal SHALL send a POST request to the Stock_API (`/api/v1/inventory/stock-items`) with the new catalogue item's ID as `catalogue_item_id`.
4. IF the Stock_API returns an error, THEN THE AddToStockModal SHALL display the error message and allow the user to retry without losing the catalogue item that was already created.

### Requirement 7: Packaging Quantity Inference

**User Story:** As an inventory manager, I want the packaging quantity to be inferred from the stock quantity I enter, so that I do not have to fill in packaging details separately during inline creation.

#### Acceptance Criteria

1. THE InlineCreateForm SHALL NOT include packaging fields (packaging_type, qty_per_pack, total_packs).
2. WHEN the user enters a stock quantity in the stock details step after inline creation, THE AddToStockModal SHALL display a message explaining that the quantity represents individual units (or litres for fluids), consistent with the existing stock details form behavior.
3. WHEN the inline-created catalogue item is later edited on the full Catalogue page, THE Catalogue page SHALL allow the user to set packaging details (packaging_type, qty_per_pack, total_packs) for the item.

### Requirement 8: UX Messaging and Navigation

**User Story:** As an inventory manager, I want clear messaging throughout the inline creation flow, so that I understand I am creating a catalogue item and adding stock in one step.

#### Acceptance Criteria

1. WHEN the InlineCreateForm is displayed, THE AddToStockModal SHALL show a banner or heading that reads "Quick-create a new [Category] catalogue item" to clarify the action being taken.
2. THE InlineCreateForm SHALL display a helper message stating "This creates a catalogue entry. You can update full details (packaging, supplier, category) later from the Catalogue page."
3. WHEN the InlineCreateForm is visible, THE AddToStockModal SHALL provide a "Cancel" button that returns the user to the CataloguePicker search results without creating any catalogue item.
4. WHEN the InlineCreateForm submission is in progress, THE AddToStockModal SHALL disable the submit button and display a loading indicator.

### Requirement 9: Existing Workflows Unchanged

**User Story:** As an inventory manager, I want the existing catalogue pages and stock workflows to remain unchanged, so that the inline creation is purely an additive enhancement.

#### Acceptance Criteria

1. THE AddToStockModal SHALL preserve the existing three-step flow (category → catalogue picker → stock details) for users who select an existing catalogue item.
2. THE full Catalogue pages (Parts Catalogue, Fluids/Oils Catalogue, Services Catalogue) SHALL remain unchanged and fully functional.
3. THE inline-created catalogue items SHALL appear in the full Catalogue pages and be editable through the existing edit forms.
4. THE existing Catalogue_API and Stock_API endpoints SHALL NOT require any modifications — the inline creation uses the same endpoints that the full catalogue pages use.

### Requirement 10: Error Handling and Edge Cases

**User Story:** As an inventory manager, I want the inline creation flow to handle errors gracefully, so that I do not lose my work or end up in an inconsistent state.

#### Acceptance Criteria

1. IF the Catalogue_API request fails due to a network error, THEN THE InlineCreateForm SHALL display a generic error message and allow the user to retry.
2. IF the Catalogue_API request fails due to a duplicate name or validation error, THEN THE InlineCreateForm SHALL display the specific error detail from the API response.
3. IF the user creates a catalogue item via the InlineCreateForm but then closes the modal before completing the stock details step, THE catalogue item SHALL still exist in the catalogue (the creation is not rolled back).
4. WHEN the InlineCreateForm submit button is clicked, THE AddToStockModal SHALL prevent double-submission by disabling the button until the API response is received.
