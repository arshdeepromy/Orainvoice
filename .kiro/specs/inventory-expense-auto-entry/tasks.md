# Implementation Plan: Inventory Expense Auto-Entry

## Overview

Implement automatic expense creation as a side-effect of stock item creation and positive stock adjustments. The feature adds pure helper functions for GST resolution and tax calculation, a core orchestration helper `_maybe_create_stock_expense()`, modifications to existing service functions, org settings integration, and a frontend toggle. All backend changes are in `app/modules/inventory/stock_items_service.py`, `app/modules/inventory/stock_items_router.py`, `app/modules/organisations/service.py`, and `app/modules/organisations/schemas.py`.

## Tasks

- [x] 1. Add org settings key and schema fields
  - [x] 1.1 Add `auto_expense_on_stock_purchase` to `SETTINGS_JSONB_KEYS` in `app/modules/organisations/service.py`
    - Add the string `"auto_expense_on_stock_purchase"` to the `SETTINGS_JSONB_KEYS` set
    - _Requirements: 6.1_

  - [x] 1.2 Add `auto_expense_on_stock_purchase` field to `OrgSettingsResponse` and `OrgSettingsUpdateRequest` in `app/modules/organisations/schemas.py`
    - Add `auto_expense_on_stock_purchase: Optional[bool] = Field(None, description="Automatically create expense when adding stock with a purchase price")` to both schemas
    - _Requirements: 6.2, 6.5_

- [x] 2. Implement pure helper functions in `stock_items_service.py`
  - [x] 2.1 Implement `_resolve_gst_mode(catalogue_item) -> str`
    - Extract the GST mode resolution logic from `list_stock_items()` into a standalone pure function
    - Priority: check `gst_mode` attr first, then `is_gst_exempt` → "exempt", then `gst_inclusive` → "inclusive", else "exclusive"
    - Replace the inline logic in `list_stock_items()` with a call to this helper
    - _Requirements: 5.4_

  - [x] 2.2 Write property test for `_resolve_gst_mode`
    - **Property 3: GST Mode Resolution**
    - **Validates: Requirements 5.4**
    - Generate random catalogue item field combinations (gst_mode, is_gst_exempt, gst_inclusive) and verify correct priority resolution
    - Test file: `tests/test_inventory_expense_auto_entry.py`

  - [x] 2.3 Implement `_calculate_tax_amount(amount: Decimal, gst_mode: str) -> tuple[Decimal, bool]`
    - Pure function: "inclusive" → `amount × 3 / 23` rounded ROUND_HALF_UP to 2dp, tax_inclusive=True
    - "exclusive" → `amount × 0.15` rounded ROUND_HALF_UP to 2dp, tax_inclusive=False
    - "exempt" → Decimal("0"), tax_inclusive=False
    - _Requirements: 5.1, 5.2, 5.3, 5.5_

  - [x] 2.4 Write property test for `_calculate_tax_amount`
    - **Property 2: GST Calculation Correctness**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.5**
    - Generate random positive Decimal amounts × 3 GST modes, verify formula correctness and rounding
    - Test file: `tests/test_inventory_expense_auto_entry.py`

- [x] 3. Implement core `_maybe_create_stock_expense()` helper
  - [x] 3.1 Implement `_maybe_create_stock_expense()` async helper in `stock_items_service.py`
    - Add necessary imports: `ExpenseService`, `ExpenseCreate`, `get_org_settings`, `date`, `logging`, `ROUND_HALF_UP`
    - Implement the full logic flow:
      1. Idempotency guard: if `movement.reference_id` is set, return early
      2. Check `stock_item.purchase_price` is not None and > 0
      3. Fetch org settings, check `auto_expense_on_stock_purchase` (default True if absent)
      4. Call `_resolve_gst_mode(catalogue_item)`
      5. Calculate `amount = stock_item.purchase_price × quantity`
      6. Calculate `tax_amount, tax_inclusive = _calculate_tax_amount(amount, gst_mode)`
      7. Build `ExpenseCreate` payload with category="materials", expense_type="expense", reference_number=f"SM:{movement.id}", notes with stock item context
      8. Call `ExpenseService(db).create_expense(org_id, payload, created_by=user_id, branch_id=stock_item.branch_id)`
      9. Set `movement.reference_id = expense.id`, `movement.reference_type = "expense"`
      10. `await db.flush()`
    - Wrap steps 3–10 in try/except, log warning on failure (never raise)
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.1, 2.5, 3.1, 3.2, 3.3, 4.1, 4.2, 5.1, 5.2, 5.3, 6.3, 6.4, 9.1, 10.1, 10.2, 10.3_

  - [x] 3.2 Write property tests for `_maybe_create_stock_expense` behaviour
    - **Property 1: Expense Amount Correctness** — verify amount == purchase_price × quantity
    - **Property 4: Bidirectional Traceability** — verify reference_number format and movement linkage
    - **Property 5: Branch Inheritance** — verify expense branch_id matches stock_item.branch_id
    - **Property 6: Opt-Out Setting Disables Expense Creation** — verify no expense when setting=False
    - **Property 9: Idempotency — No Duplicate Expense** — verify no new expense when reference_id already set
    - **Validates: Requirements 1.1, 2.1, 3.1, 3.2, 3.3, 4.1, 4.2, 6.3, 6.4, 9.1, 10.2, 11.3, 11.4**
    - Test file: `tests/test_inventory_expense_auto_entry.py`

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Modify `create_stock_item()` to trigger auto-expense
  - [x] 5.1 Add `branch_id` parameter and set on StockItem
    - Add optional `branch_id: uuid.UUID | None = None` parameter to `create_stock_item()`
    - Set `stock_item.branch_id = branch_id` when creating the StockItem
    - _Requirements: 11.1, 11.3_

  - [x] 5.2 Call `_maybe_create_stock_expense()` after movement flush
    - After the StockMovement is flushed, call the helper with: db, org_id, user_id, stock_item, movement, catalogue_item, quantity (as Decimal), description=f"Inventory purchase: {qty}x {item_name}"
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 1.6, 1.7, 1.8_

  - [x] 5.3 Update `stock_items_router.py` to pass `branch_id`
    - In `create_stock_item_endpoint()`, extract `branch_id` from `getattr(request.state, "branch_id", None)` (convert to UUID if string)
    - Pass `branch_id` to `create_stock_item()`
    - _Requirements: 11.2_

- [x] 6. Modify `adjust_stock_item()` to trigger auto-expense
  - [x] 6.1 Call `_maybe_create_stock_expense()` after positive adjustment
    - After the adjustment StockMovement is flushed, if `payload.quantity_change > 0`:
      - Load the catalogue item using `_resolve_catalogue_query()`
      - Resolve item name for description: `"Stock adjustment: +{qty}x {item_name}"`
      - Call `_maybe_create_stock_expense()` with the stock_item, movement, catalogue_item, quantity_change (as Decimal)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 7. Modify `delete_stock_item()` to flag linked expenses
  - [x] 7.1 Query and flag linked expenses before deletion
    - Before deleting the stock item, query `StockMovement` rows where `stock_item_id = stock_item.id AND reference_type = 'expense' AND reference_id IS NOT NULL`
    - For each such movement, load the `Expense` by `id = movement.reference_id`
    - Append `" [Stock item deleted]"` to the expense's `notes` field
    - Flush, then proceed with deletion
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 7.2 Write property test for deletion flagging
    - **Property 8: Deletion Flags Linked Expenses**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
    - Test file: `tests/test_inventory_expense_auto_entry.py`

- [x] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Add frontend settings toggle
  - [x] 9.1 Add auto-expense toggle to the OrgSettings page
    - Add an "Inventory" section (or add to existing GST/Invoice tab) with a toggle for `auto_expense_on_stock_purchase`
    - Load current value from `GET /org/settings` response (default to true if absent)
    - Save via `PUT /org/settings` with `{ auto_expense_on_stock_purchase: boolean }`
    - Label: "Automatically create expense when adding stock"
    - Description text: "When enabled, adding stock items or positive adjustments with a purchase price will automatically create an expense entry."
    - Follow existing toggle pattern (role="switch", aria-checked, same styling as portal/GST toggles)
    - _Requirements: 6.6_

  - [x] 9.2 Write frontend unit test for the settings toggle
    - Verify toggle renders, reflects GET response, and calls PUT on change
    - Test file: scoped vitest for the modified component
    - _Requirements: 6.6_

- [x] 10. Write integration tests for full flow
  - [x] 10.1 Write integration test: create stock item → verify expense created with correct fields
    - Verify expense amount, category, description, reference_number, notes, branch_id, created_by, tax_amount, tax_inclusive
    - Verify movement.reference_id and reference_type are set
    - **Property 7: Resilience** — mock ExpenseService to raise, verify stock item still created
    - **Validates: Requirements 1.1–1.8, 3.1–3.3, 4.1–4.2, 5.1–5.3, 9.1, 10.1–10.3**
    - Test file: `tests/test_inventory_expense_auto_entry.py`

  - [x] 10.2 Write integration test: adjust stock item → verify expense created
    - Positive adjustment with purchase_price → expense created
    - Negative adjustment → no expense
    - Zero purchase_price → no expense
    - **Validates: Requirements 2.1–2.5**
    - Test file: `tests/test_inventory_expense_auto_entry.py`

  - [x] 10.3 Write integration test: delete stock item → verify expense notes flagged
    - Create stock item with expense, delete it, verify notes appended
    - **Validates: Requirements 8.1–8.4**
    - Test file: `tests/test_inventory_expense_auto_entry.py`

  - [x] 10.4 Write integration test: setting disabled → no expense created
    - Set `auto_expense_on_stock_purchase = False`, create stock item, verify no expense
    - **Validates: Requirements 6.3, 6.4**
    - Test file: `tests/test_inventory_expense_auto_entry.py`

- [x] 11. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- All backend tests run via: `pytest tests/test_inventory_expense_auto_entry.py`
- Frontend tests run via: `vitest --run` scoped to changed files
- No database migration needed — org settings uses existing JSONB column, expenses table already has all required columns
