# Implementation Plan: Inline Catalogue from Inventory

## Overview

This plan implements inline catalogue item creation within the AddToStockModal. The work is split into: extracting shared helpers (API mapping, response mapping), building the InlineCreateForm component, modifying CataloguePicker to show the "+ Create New" button, and wiring everything together in AddToStockModal. Property-based tests use fast-check (already installed) with Vitest.

## Tasks

- [x] 1. Create InlineCreateForm component with category-specific fields
  - [x] 1.1 Create `frontend/src/components/inventory/InlineCreateForm.tsx` with the `InlineCreateFormProps` interface (`category`, `onSuccess`, `onCancel`)
    - Implement local form state for all fields across all 4 categories (part, tyre, fluid, service)
    - Render category-specific fields based on the `category` prop:
      - Part: name (required), sell_price_per_unit (required), gst_mode (required, default "exclusive"), part_number (optional), brand (optional), description (optional)
      - Tyre: name (required), sell_price_per_unit (required), gst_mode (required, default "exclusive"), tyre_width (optional), tyre_profile (optional), tyre_rim_dia (optional), brand (optional)
      - Fluid: product_name (required), sell_price_per_unit (required), gst_mode (required, default "exclusive"), fluid_type (required, "oil"/"non-oil"), oil_type (optional, shown when fluid_type is "oil"), grade (optional), brand_name (optional)
      - Service: name (required), default_price (required), gst_mode (required, default "exclusive"), description (optional)
    - Include a GST mode segmented toggle (inclusive/exclusive/exempt)
    - Include banner text "Quick-create a new [Category] catalogue item" using the CATEGORIES label
    - Include helper message "This creates a catalogue entry. You can update full details (packaging, supplier, category) later from the Catalogue page."
    - Include Cancel button that calls `onCancel`
    - _Requirements: 2.1, 3.1, 4.1, 5.1, 8.1, 8.2, 8.3_

  - [x] 1.2 Implement form validation in InlineCreateForm
    - Validate required fields: name/product_name non-empty after trim, sell_price_per_unit/default_price is a valid positive number, gst_mode is one of "inclusive"/"exclusive"/"exempt"
    - For fluids: validate fluid_type is "oil" or "non-oil"
    - Display inline validation errors per field
    - Prevent form submission when validation fails
    - _Requirements: 2.1, 3.1, 4.1, 5.1, 10.4_

  - [x] 1.3 Implement API submission logic in InlineCreateForm
    - Map category to correct endpoint: part/tyre → `POST /catalogue/parts`, fluid → `POST /catalogue/fluids`, service → `POST /catalogue/items`
    - Include correct type discriminator: `part_type: "part"` for parts, `part_type: "tyre"` for tyres, `category: "service"` for services
    - Send optional fields as `null` when empty
    - Use `saving` state to disable submit button and show loading indicator during API call
    - Follow safe-api-consumption patterns: type-safe API call with generics, `?.` and `?? []` on response data
    - _Requirements: 2.3, 3.2, 4.2, 5.2, 8.4, 10.4_

  - [x] 1.4 Implement response mapping and error handling in InlineCreateForm
    - Map API response to `CatalogueItem` interface per category:
      - Parts/Tyres: `response.part.id`, `response.part.name`, `response.part.sell_price_per_unit`, etc.
      - Fluids: `response.product.id`, `response.product.product_name`, `response.product.sell_price_per_unit`, etc.
      - Services: `response.item.id`, `response.item.name`, `response.item.default_price`, etc.
    - Call `onSuccess(mappedItem)` on successful creation
    - On network error: display "Failed to create [category]. Please check your connection and try again."
    - On validation/duplicate error (400/422): extract and display `err?.response?.data?.detail`
    - Preserve user input on error so they can fix and retry
    - _Requirements: 2.4, 3.3, 4.3, 5.3, 6.1, 6.2, 10.1, 10.2_

  - [x] 1.5 Write property test: Category-to-API endpoint mapping (Property 1)
    - **Property 1: Category-to-API endpoint and type mapping**
    - Generate random valid form data for each category using fast-check arbitraries
    - Verify the constructed endpoint URL matches: part/tyre → `/catalogue/parts`, fluid → `/catalogue/fluids`, service → `/catalogue/items`
    - Verify the payload includes the correct type discriminator field
    - **Validates: Requirements 2.3, 3.2, 4.2, 5.2**

  - [x] 1.6 Write property test: Required field validation (Property 7)
    - **Property 7: Form validation rejects missing required fields**
    - Generate random form states with at least one required field missing or invalid (empty name, negative price, missing gst_mode)
    - Verify submission is blocked and a validation error is shown
    - **Validates: Requirements 2.1, 3.1, 4.1, 5.1**

- [x] 2. Checkpoint - Verify InlineCreateForm renders and validates correctly
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Modify CataloguePicker to show "+ Create New" button
  - [x] 3.1 Add `onCreateNew` callback prop to CataloguePicker
    - Add `onCreateNew?: () => void` to the CataloguePicker props
    - When `onCreateNew` is provided, render a "+ Create New [Category]" button:
      - Below the results list when results exist
      - In place of the "No active items found" empty state message
      - In place of the "No items match your search" empty state message
    - Use the category label from the `CATEGORIES` array for the button text
    - Style the button consistently with the existing UI (secondary variant or text link style)
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 3.2 Implement trade family gating for the create button
    - Use the existing `useTenant()` hook to get `tradeFamily`
    - Only show the "+ Create New" button for categories visible to the user's trade family (tyres and fluids only for `automotive-transport`)
    - The gating already exists in `CategorySelector` — apply the same logic to the create button visibility
    - _Requirements: 1.4_

  - [x] 3.3 Write property test: Trade family gating (Property 3)
    - **Property 3: Trade family gating of create button**
    - Generate random trade family values and category combinations
    - Verify button visibility: tyres/fluids visible only for `automotive-transport`, parts always visible
    - **Validates: Requirements 1.4**

  - [x] 3.4 Write property test: Category label mapping (Property 4)
    - **Property 4: Create button and banner label matches category**
    - Generate random categories from {part, tyre, fluid, service}
    - Verify the button text contains the correct human-readable label ("Part", "Tyre", "Fluid/Oil", "Service")
    - **Validates: Requirements 1.1, 8.1**

- [x] 4. Wire InlineCreateForm into AddToStockModal
  - [x] 4.1 Add `showInlineCreate` state and conditional rendering in AddToStockModal
    - Add `const [showInlineCreate, setShowInlineCreate] = useState(false)` state
    - When step is `'catalogue'` and `showInlineCreate` is true, render `InlineCreateForm` instead of `CataloguePicker`
    - Pass `onCreateNew={() => setShowInlineCreate(true)}` to CataloguePicker
    - Pass `onCancel={() => setShowInlineCreate(false)}` to InlineCreateForm
    - Pass `category` to InlineCreateForm
    - _Requirements: 1.1, 8.3, 9.1_

  - [x] 4.2 Implement onSuccess handler for inline creation
    - On `InlineCreateForm` success callback:
      1. Set `showInlineCreate` to `false`
      2. Set the selected catalogue item to the mapped `CatalogueItem`
      3. Advance step to `'details'`
    - The StockDetailsForm receives the same `CatalogueItem` shape whether the item was selected from the picker or created inline
    - Reset `showInlineCreate` to `false` when navigating back to category step
    - _Requirements: 6.1, 6.2, 6.3, 9.1_

  - [x] 4.3 Write property test: Successful creation advances to stock details (Property 5)
    - **Property 5: Successful inline creation advances to stock details**
    - Generate random valid API responses per category
    - Verify the modal transitions to the stock details step with the correct item ID set as selected
    - **Validates: Requirements 6.1**

  - [x] 4.4 Write property test: Response-to-CatalogueItem mapping consistency (Property 6)
    - **Property 6: Inline-created item populates stock form identically**
    - Generate random catalogue API responses for each category
    - Verify the mapped CatalogueItem has equivalent fields (name, sell_price, brand) regardless of creation path
    - **Validates: Requirements 6.2**

  - [x] 4.5 Write property test: API error detail propagation (Property 2)
    - **Property 2: API error detail propagation**
    - Generate random error detail strings using fast-check `fc.string()`
    - Verify the form displays the exact detail string from the API error response without modification
    - **Validates: Requirements 2.4, 3.3, 4.3, 5.3, 10.2**

- [x] 5. Checkpoint - Verify full inline create flow works end-to-end
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Final verification and regression check
  - [x] 6.1 Verify existing three-step flow is unchanged
    - Confirm selecting an existing catalogue item still works: category → picker → details → submit
    - Confirm the StockDetailsForm receives the same data shape for both existing and inline-created items
    - Confirm the stock creation POST to `/inventory/stock-items` works with inline-created catalogue item IDs
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 6.3, 6.4_

  - [x] 6.2 Write unit tests for InlineCreateForm
    - Test correct fields render for each category (part, tyre, fluid, service)
    - Test cancel button returns to picker without API calls
    - Test loading state disables submit button
    - Test network error displays generic message
    - Test validation error displays specific API detail
    - _Requirements: 2.1, 3.1, 4.1, 5.1, 8.3, 8.4, 10.1, 10.2_

- [x] 7. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- This is a frontend-only feature — no backend changes or migrations needed
- All API calls must follow the safe-api-consumption steering rules (`?.`, `?? []`, `?? 0`, AbortController cleanup, no `as any`)
- The InlineCreateForm calls the same catalogue API endpoints the full catalogue pages use
- Property tests use `fast-check` (already installed in frontend/package.json) with Vitest
- Test files go in `frontend/src/components/inventory/__tests__/` to match vitest config
