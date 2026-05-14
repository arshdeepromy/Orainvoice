# Inventory Expense Auto-Entry — Requirements

## Introduction

This feature automatically creates an expense entry whenever a stock item is added or adjusted with a purchase price, linking the inventory and expenses modules so that stock purchases are properly tracked as business expenses. The expense records the total cost (purchase_price × quantity), inherits branch context, respects GST settings from the catalogue, and maintains traceability back to the originating stock movement.

Because the auto-expense is created via the existing `ExpenseService.create_expense()` method (which calls `auto_post_expense` for ledger journal entries), the expense automatically flows into:
- The **cash flow dashboard widget** (`get_cash_flow` queries `SELECT SUM(amount) FROM expenses WHERE org_id = :org_id AND date >= :cutoff`)
- The **expense summary report** (`GET /api/v2/expenses/summary`)
- The **expense list page** (`GET /api/v2/expenses`)
- The **ledger/accounting** (via `auto_post_expense` → journal entries → Xero sync)

No changes to reporting, dashboard widgets, or the expense list UI are needed — the auto-created expense is indistinguishable from a manually-created one.

## Glossary

- **Stock_Item_Service**: The backend service layer (`app/modules/inventory/stock_items_service.py`) responsible for creating, adjusting, and managing stock items in the inventory module.
- **Expense_Service**: The backend service layer (`app/modules/expenses/service.py` → `ExpenseService`) responsible for creating and managing expense records, including auto-posting journal entries to the ledger.
- **Stock_Movement**: An audited record (`app/modules/stock/models.py` → `StockMovement`) of a quantity change to a stock item, including type (purchase, adjustment, sale, etc.), quantity delta, and resulting quantity. Has `reference_type` (String) and `reference_id` (UUID) fields for linking to source documents.
- **Auto_Expense**: An expense record (`app/modules/expenses/models.py` → `Expense`) automatically created by the system as a side-effect of a stock purchase or positive stock adjustment when a purchase price is provided.
- **Organisation_Settings**: Per-organisation configuration stored in the `Organisation.settings` JSONB column, accessed via `get_org_settings()` / `update_org_settings()` in `app/modules/organisations/service.py`. New keys are added to the `SETTINGS_JSONB_KEYS` set.
- **Catalogue_Item**: A `PartsCatalogue` or `FluidOilProduct` entry that defines base pricing, GST mode, and supplier information for stock items.

## Technical Context (verified against codebase)

### Tables and columns involved

| Table | Key columns for this feature |
|---|---|
| `stock_items` | `id`, `org_id`, `catalogue_item_id`, `catalogue_type`, `current_quantity`, `purchase_price`, `sell_price`, `cost_per_unit`, `branch_id`, `created_by` |
| `stock_movements` | `id`, `org_id`, `stock_item_id`, `movement_type`, `quantity_change`, `resulting_quantity`, `reference_type`, `reference_id`, `performed_by`, `notes` |
| `expenses` | `id`, `org_id`, `date`, `description`, `amount`, `tax_amount`, `category`, `reference_number`, `notes`, `tax_inclusive`, `expense_type`, `created_by`, `branch_id` |
| `parts_catalogue` | `id`, `name`, `gst_mode`, `is_gst_exempt`, `gst_inclusive`, `purchase_price` |
| `fluid_oil_products` | `id`, `product_name`, `oil_type`, `grade`, `gst_mode`, `purchase_price` |
| `organisations` | `id`, `settings` (JSONB — stores `auto_expense_on_stock_purchase` key) |

### API calls involved

| Operation | Endpoint | Service function |
|---|---|---|
| Create stock item | `POST /api/v1/inventory/stock-items` | `create_stock_item(db, org_id, user_id, payload)` |
| Adjust stock item | `POST /api/v1/inventory/stock-items/{id}/adjust` | `adjust_stock_item(db, org_id, user_id, stock_item_id, payload)` |
| Delete stock item | `DELETE /api/v1/inventory/stock-items/{id}` | `delete_stock_item(db, org_id, stock_item_id)` |
| Create expense (internal) | N/A (called internally, not via API) | `ExpenseService(db).create_expense(org_id, payload, created_by=..., branch_id=...)` |
| Get org settings | `GET /api/v1/org/settings` | `get_org_settings(db, org_id=...)` |
| Update org settings | `PUT /api/v1/org/settings` | `update_org_settings(db, org_id=..., **kwargs)` |

### GST mode resolution (existing logic in `list_stock_items`)

```python
gst_mode = getattr(catalogue_item, "gst_mode", None)
if gst_mode is None:
    if getattr(catalogue_item, "is_gst_exempt", False):
        gst_mode = "exempt"
    elif getattr(catalogue_item, "gst_inclusive", False):
        gst_mode = "inclusive"
    else:
        gst_mode = "exclusive"
```

This logic must be extracted into a reusable helper for use during stock item creation and adjustment.

## Requirements

### Requirement 1: Auto-Expense Creation on Stock Item Addition

**User Story:** As a business owner, I want an expense to be automatically created when I add a stock item with a purchase price, so that my inventory purchases are immediately reflected in my expense records without manual double-entry.

#### Acceptance Criteria

1. WHEN a stock item is created via `create_stock_item()` with a non-null `purchase_price` greater than zero AND the org setting `auto_expense_on_stock_purchase` is true (or absent, defaulting to true), THEN the service SHALL create an expense via `ExpenseService(db).create_expense()` with `amount` equal to `purchase_price × quantity`.
2. WHEN a stock item is created with a null or zero `purchase_price`, THEN no expense SHALL be created.
3. THE expense SHALL have `category` set to `"materials"` (an existing value in `EXPENSE_CATEGORIES`).
4. THE expense SHALL have `description` set to a human-readable string including the catalogue item name and quantity, e.g. `"Inventory purchase: 10x Brake Pad Set"`.
5. THE expense SHALL have `date` set to `date.today()` at the time of stock item creation.
6. THE expense SHALL have `expense_type` set to `"expense"`.
7. THE expense creation SHALL use `db.flush()` (not commit) — it runs within the same transaction as the stock item creation, managed by the `get_db_session` context manager.
8. IF the expense creation fails for any reason (DB error, ledger posting failure), THEN the service SHALL log a warning but SHALL NOT fail the stock item creation. The stock item and movement are still committed.

### Requirement 2: Auto-Expense Creation on Positive Stock Adjustment

**User Story:** As a business owner, I want an expense to be automatically created when I add more stock via adjustment, so that restocking purchases are tracked as expenses consistently.

#### Acceptance Criteria

1. WHEN a stock adjustment is performed via `adjust_stock_item()` with a positive `quantity_change` AND the stock item has a non-null `purchase_price` greater than zero AND the org setting `auto_expense_on_stock_purchase` is true, THEN the service SHALL create an expense with `amount` equal to `stock_item.purchase_price × quantity_change`.
2. WHEN a stock adjustment has a negative `quantity_change` (stock removal/correction), THEN no expense SHALL be created.
3. WHEN a stock adjustment has a positive `quantity_change` but the stock item has a null or zero `purchase_price`, THEN no expense SHALL be created.
4. THE expense SHALL have `description` set to `"Stock adjustment: +{qty}x {item_name}"`.
5. THE same resilience guarantee from Requirement 1 AC-8 applies — expense failure SHALL NOT fail the adjustment.

### Requirement 3: Expense-to-Stock-Movement Traceability

**User Story:** As a business owner, I want to trace each auto-created expense back to the specific stock movement that triggered it, so that I can audit my inventory costs accurately.

#### Acceptance Criteria

1. THE expense SHALL store the stock movement UUID in its `reference_number` field formatted as `"SM:{stock_movement_id}"` (the `reference_number` column is `VARCHAR(100)`, and a UUID is 36 chars, so `"SM:"` + UUID = 39 chars — fits).
2. THE expense SHALL include the stock item name and stock_item_id in its `notes` field (Text column, unlimited length) for human-readable context, e.g. `"Auto-created for stock item: Brake Pad Set (id: {stock_item_id})"`.
3. THE stock movement SHALL store the created expense UUID in its `reference_id` field (UUID column) with `reference_type` set to `"expense"` (String column, max 50 chars).

### Requirement 4: Branch Inheritance

**User Story:** As a multi-branch business owner, I want auto-created expenses to inherit the branch from the stock item, so that expenses are correctly attributed to the branch that made the purchase.

#### Acceptance Criteria

1. WHEN the stock item has a non-null `branch_id`, THE expense SHALL be created with that `branch_id` (passed to `ExpenseService.create_expense(... branch_id=stock_item.branch_id)`).
2. WHEN the stock item has a null `branch_id`, THE expense SHALL have a null `branch_id`.
3. NOTE: The `StockItem` model already has a `branch_id` column (UUID, FK to `branches.id`, nullable). Currently `create_stock_item()` does not set it. This feature SHALL add `branch_id` propagation from the router's branch context (matching the pattern used by the expenses router where `branch_id` comes from `request.state` or is inferred from the user's assigned branch).

### Requirement 5: GST/Tax Handling

**User Story:** As a business owner, I want auto-created expenses to respect the GST settings from the catalogue item, so that tax amounts are correctly recorded without manual intervention.

#### Acceptance Criteria

1. WHEN the catalogue item's resolved `gst_mode` is `"inclusive"`, THE expense SHALL set `tax_inclusive = True` and calculate `tax_amount` by extracting GST from the total amount using the NZ 15% rate: `tax_amount = amount × 3 / 23` (this is the standard formula: `amount × rate / (100 + rate)` where rate = 15).
2. WHEN the catalogue item's resolved `gst_mode` is `"exclusive"`, THE expense SHALL set `tax_inclusive = False` and calculate `tax_amount = amount × 0.15`.
3. WHEN the catalogue item's resolved `gst_mode` is `"exempt"`, THE expense SHALL set `tax_inclusive = False` and `tax_amount = Decimal("0")`.
4. THE `gst_mode` resolution SHALL use the same logic as the existing `list_stock_items` function: check `catalogue_item.gst_mode` first, fall back to `is_gst_exempt` → "exempt", `gst_inclusive` → "inclusive", else "exclusive". This logic SHALL be extracted into a shared helper `_resolve_gst_mode(catalogue_item) -> str`.
5. THE `tax_amount` SHALL be rounded to 2 decimal places using `ROUND_HALF_UP` to match the `Numeric(12, 2)` column precision on the `expenses` table.

### Requirement 6: Organisation Opt-In Setting

**User Story:** As a business owner, I want to control whether inventory purchases automatically create expenses, so that I can disable this behaviour if I manage expenses separately.

#### Acceptance Criteria

1. THE `SETTINGS_JSONB_KEYS` set in `app/modules/organisations/service.py` SHALL include `"auto_expense_on_stock_purchase"`.
2. THE `OrgSettingsResponse` and `OrgSettingsUpdateRequest` schemas in `app/modules/organisations/schemas.py` SHALL include `auto_expense_on_stock_purchase: bool | None`.
3. WHEN the key is absent from the org's settings JSONB (i.e. existing orgs that haven't toggled it), THE system SHALL treat it as `True` (opt-out, not opt-in — the feature is on by default for all orgs).
4. WHEN the setting is `False`, THE `create_stock_item()` and `adjust_stock_item()` functions SHALL skip expense creation entirely.
5. THE setting SHALL be readable via `GET /api/v1/org/settings` and writable via `PUT /api/v1/org/settings` using the existing settings update pattern — no new endpoint needed.
6. THE frontend Settings page SHALL include a toggle for this setting under a relevant section (e.g. "Inventory" or "Expenses" tab).

### Requirement 7: Ledger Journal Entry & Reporting Integration

**User Story:** As a business owner, I want auto-created expenses to post journal entries to the ledger and appear in all reports automatically, so that my accounting records and dashboards stay in sync with inventory purchases.

#### Acceptance Criteria

1. WHEN an expense is created via `ExpenseService.create_expense()`, the existing `auto_post_expense()` call within that method SHALL create the journal entry (DR Expense Account 6xxx, DR GST Receivable 1200, CR Accounts Payable 2000). No additional code is needed — this is already built into `create_expense()`.
2. IF `auto_post_expense()` fails (e.g. missing chart of accounts), THE existing try/except in `create_expense()` logs a warning but does not fail the expense creation. The expense row is still committed.
3. THE auto-created expense SHALL appear in the **cash flow dashboard widget** automatically because `get_cash_flow()` queries `SELECT SUM(amount) FROM expenses WHERE org_id = :org_id AND date >= :cutoff` — any row in the `expenses` table with the correct `org_id` and `date` is included.
4. THE auto-created expense SHALL appear in the **expense summary report** (`GET /api/v2/expenses/summary`) automatically because it queries all expenses by `org_id` with optional category/date filters.
5. THE auto-created expense SHALL appear in the **expense list** (`GET /api/v2/expenses`) automatically.
6. NO changes to reporting endpoints, dashboard widgets, or frontend expense pages are needed.

### Requirement 8: Expense Flagging on Stock Item Deletion

**User Story:** As a business owner, I want the auto-created expense to be soft-flagged when I delete a stock item, so that I am aware of orphaned expenses but my accounting history is preserved.

#### Acceptance Criteria

1. WHEN `delete_stock_item()` is called, THE service SHALL query `StockMovement` rows where `stock_item_id = stock_item.id` AND `reference_type = 'expense'` AND `reference_id IS NOT NULL`.
2. FOR each such movement, THE service SHALL load the `Expense` by `id = movement.reference_id` and append `" [Stock item deleted]"` to its `notes` field.
3. THE service SHALL NOT delete the expense — the accounting record is preserved.
4. IF no linked expenses exist (e.g. stock item was created without a purchase price), THE deletion proceeds normally with no expense modification.

### Requirement 9: Created-By Attribution

**User Story:** As a business owner, I want auto-created expenses to record which user triggered the stock operation, so that I have a clear audit trail.

#### Acceptance Criteria

1. THE expense SHALL set `created_by` to the `user_id` parameter passed to `create_stock_item()` or `adjust_stock_item()`. Both functions already receive `user_id: uuid.UUID` from the router's `_extract_org_context(request)`.

### Requirement 10: Idempotency and Duplicate Prevention

**User Story:** As a system operator, I want the auto-expense creation to be idempotent within the same database transaction, so that retries or concurrent requests do not create duplicate expenses.

#### Acceptance Criteria

1. THE expense creation SHALL occur within the same database transaction as the stock item creation/adjustment (both use `db.flush()`, committed by the `get_db_session` context manager on request completion).
2. BEFORE creating an expense, THE service SHALL check if the stock movement's `reference_id` is already set. IF it is, no duplicate expense SHALL be created.
3. THE stock movement's `reference_id` and `reference_type` SHALL be set AFTER the expense is created and flushed (so the expense has an `id`), within the same transaction.

### Requirement 11: Branch Context on Stock Item Creation

**User Story:** As a multi-branch business owner, I want stock items to inherit the branch context from the current user session, so that branch-scoped reporting works correctly for both inventory and the auto-created expenses.

#### Acceptance Criteria

1. THE `create_stock_item()` function SHALL accept an optional `branch_id: uuid.UUID | None` parameter.
2. THE stock items router (`stock_items_router.py`) SHALL extract `branch_id` from the request context (matching the pattern used by the expenses router: `getattr(request.state, "branch_id", None)`) and pass it to `create_stock_item()`.
3. THE `StockItem` row SHALL be created with the provided `branch_id`.
4. THE auto-expense SHALL inherit this `branch_id` per Requirement 4.

## Non-Functional Requirements

- **Performance**: The expense creation adds one INSERT + one flush to the stock item creation path. This is negligible (< 5ms) and does not require async offloading.
- **Resilience**: Expense creation failure MUST NOT fail the parent stock operation. Use try/except with warning log.
- **No new dependencies**: Uses existing `ExpenseService`, `auto_post_expense`, `StockMovement` — no new packages or tables.
- **No migration needed for the expense**: The `expenses` table already has all required columns. Only the org settings JSONB needs the new key (no schema migration — it's a JSONB field).
- **Backward compatibility**: Existing stock items (created before this feature) are unaffected. The feature only triggers on new creates/adjustments going forward.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Expense creation fails and blocks stock item creation | Try/except wrapper — expense failure is logged, stock item still commits |
| Duplicate expenses on retry/race condition | Idempotency check via `movement.reference_id` before creating |
| GST calculation rounding errors | Use `Decimal` arithmetic with explicit `ROUND_HALF_UP` to 2dp |
| Org settings key missing for existing orgs | Default to `True` when key is absent from JSONB |
| Cash flow widget doesn't pick up new expenses | No risk — widget queries `expenses` table directly by `org_id` + `date` |
| Ledger accounts not set up for org | `auto_post_expense` already handles this gracefully (logs warning, doesn't fail) |
