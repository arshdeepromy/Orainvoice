# Implementation Plan: Quote ↔ Invoice Parity (Phases 5 + 7)

**Source of truth:** `.kiro/specs/quote-invoice-parity/design.md` and `.kiro/specs/quote-invoice-parity/requirements.md`
**Plan document:** `docs/QUOTE_PREVIEW_PRINT_PLAN.md` (Phases 5 + 7)
**Open questions:** OQ-1 (multi-vehicle) and OQ-2 (quote attachments) resolved **YES** — every previously OQ-gated surface is mandatory.
**Version target:** `1.6.0` (per design.md §14)

Tasks are ordered strictly by dependency. Later tasks depend on earlier — do not execute out of order. Every property `CP-1..CP-7` has its own dedicated test task.

## Tasks

- [x] 1. Backend — Alembic migration 0184
  - New file: `alembic/versions/2026_05_XX_0900-0184_quote_invoice_parity.py` with `down_revision = "0183"`.

  - [x] 1.1 Write upgrade — new columns on `quotes`
    - Add `order_number VARCHAR(100) NULL`
    - Add `salesperson_id UUID NULL REFERENCES users(id)`
    - Add `additional_vehicles JSONB NULL`
    - Add `fluid_usage JSONB NULL`
    - All additions use `ADD COLUMN IF NOT EXISTS` for idempotence
    - _Requirements: 13.1, 13.3, 13.8_ _Property: CP-4_

  - [x] 1.2 Write upgrade — new columns on `quote_line_items`
    - Add `catalogue_item_id UUID NULL`
    - Add `stock_item_id UUID NULL`
    - Add `gst_inclusive BOOLEAN NOT NULL DEFAULT false`
    - Add `inclusive_price NUMERIC(12,2) NULL`
    - Add `tax_rate NUMERIC(5,2) NOT NULL DEFAULT 15`
    - All additions use `ADD COLUMN IF NOT EXISTS`
    - _Requirements: 13.1, 13.4, 13.8_ _Property: CP-4_

  - [x] 1.3 Write upgrade — create `quote_attachments` table
    - Use `information_schema` early-return pattern from `0170_create_invoice_attachments.py` for idempotence
    - Columns: `id`, `quote_id` (FK quotes ON DELETE CASCADE), `org_id` (FK organisations), `file_key`, `file_name`, `file_size`, `mime_type`, `uploaded_by` (FK users NULL), `sort_order`, `created_at`
    - Create composite index `ix_quote_attachments_quote_org(quote_id, org_id)`
    - Enable RLS with policy `quote_attachments_org_isolation USING (org_id = current_setting('app.current_org_id')::uuid)`
    - Add to `ora_publication` inside `DO $ha_block$` guard (no-op when publication absent)
    - _Requirements: 13.1, 13.5, 13.6, 17.1, 17.2, 17.3, 17.4_ _Property: CP-4_

  - [x] 1.4 Write downgrade path (exact reverse order)
    - Drop publication membership (guarded `DO $ha_block$`)
    - Drop RLS policy `quote_attachments_org_isolation`
    - Drop index `ix_quote_attachments_quote_org`
    - Drop `quote_attachments` table
    - Drop `quote_line_items` columns in reverse order (tax_rate, inclusive_price, gst_inclusive, stock_item_id, catalogue_item_id)
    - Drop `quotes` columns in reverse order (fluid_usage, additional_vehicles, salesperson_id, order_number)
    - _Requirements: 13.7, 13.9, 17.5_ _Property: CP-4_

  - [x] 1.5 Verify locally: upgrade → downgrade is schema-bit-identical
    - `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head` → confirm head reports `0184`
    - `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic downgrade -1` → confirm head reports `0183`
    - Dump schema before upgrade and after downgrade; diff must be empty
    - Verify existing rows in `quotes` and `quote_line_items` survive both directions
    - _Requirements: 13.2, 13.8, 13.9_ _Property: CP-4_ _Test: TC-MIG-ROUND_

- [x] 2. Backend — ORM model deltas
  - [x] 2.1 Extend `Quote` class in `app/modules/quotes/models.py`
    - Add `order_number`, `salesperson_id` (with FK), `additional_vehicles` (JSONB nullable), `fluid_usage` (JSONB nullable)
    - _Requirements: 1.1, 13.3_

  - [x] 2.2 Extend `QuoteLineItem` class in `app/modules/quotes/models.py`
    - Add `catalogue_item_id` (UUID nullable), `stock_item_id` (UUID nullable), `gst_inclusive` (Boolean NOT NULL DEFAULT false), `inclusive_price` (Numeric(12,2) nullable), `tax_rate` (Numeric(5,2) NOT NULL DEFAULT 15)
    - _Requirements: 1.2, 13.4_

  - [x] 2.3 Create new `QuoteAttachment` model
    - New file `app/modules/quotes/attachment_models.py`
    - Mirror of `app/modules/invoices/attachment_models.py` with `invoice_id` → `quote_id` and FK targets updated
    - _Requirements: 13.5, 17.1_

- [x] 3. Backend — Pydantic schema deltas
  - [x] 3.1 Extend `QuoteLineItemCreate` in `app/modules/quotes/schemas.py`
    - Add `catalogue_item_id: uuid.UUID | None`, `stock_item_id: uuid.UUID | None`, `gst_inclusive: bool = False`, `inclusive_price: Decimal | None`, `tax_rate: Decimal | None`
    - _Requirements: 1.2, 15.4_

  - [x] 3.2 Extend `QuoteLineItemResponse` with the same five fields
    - _Requirements: 2.2, 15.4_

  - [x] 3.3 Create `VehicleItem` and `FluidUsageItem` Pydantic models
    - Copy from `app/modules/invoices/schemas.py` with `model_config = {"extra": "ignore"}`
    - _Requirements: 1.6, 1.7_

  - [x] 3.4 Extend `QuoteCreate`
    - Add `order_number: str | None = Field(default=None, max_length=100)`
    - Add `salesperson_id: uuid.UUID | None = None`
    - Add `vehicles: list[VehicleItem] | None = None` (multi-vehicle)
    - Add `fluid_usage: list[FluidUsageItem] = Field(default_factory=list)`
    - Add `save_terms_as_default: bool = False`
    - _Requirements: 1.1, 1.6, 1.7, 8.1, 15.1_

  - [x] 3.5 Extend `QuoteUpdate` with the same additions
    - _Requirements: 2.3, 15.2_

  - [x] 3.6 Extend `QuoteResponse`
    - Add `order_number`, `salesperson_id`, `salesperson_name`, `additional_vehicles` (list[dict]), `fluid_usage` (list[dict]), `attachment_count: int = 0`
    - _Requirements: 2.6, 5.5, 6.3, 15.3, 15.4_

  - [x] 3.7 Extend `QuoteSearchResult` with `attachment_count: int = 0`
    - _Requirements: 6.3, 15.4_ _Property: CP-6_

  - [x] 3.8 Create `QuoteAttachmentResponse` and `QuoteAttachmentListResponse` in new `app/modules/quotes/attachment_schemas.py`
    - Mirrors the invoice attachment schemas exactly
    - _Requirements: 5.5_

- [x] 4. Backend — quote attachment service
  - New file: `app/modules/quotes/attachment_service.py` — direct port of `app/modules/invoices/attachment_service.py`

  - [x] 4.1 Port all six functions with `invoice_id` → `quote_id`, `Invoice` → `Quote`, `InvoiceAttachment` → `QuoteAttachment`
    - `async def upload_attachment(db, *, org_id, user_id, quote_id, content, filename, mime_type) -> dict`
    - `async def list_attachments(db, *, org_id, quote_id) -> list[dict]`
    - `async def get_attachment(db, *, org_id, quote_id, attachment_id) -> dict`
    - `def download_attachment(org_id, file_key) -> bytes`
    - `async def delete_attachment(db, *, org_id, user_id, quote_id, attachment_id) -> dict`
    - `async def get_attachment_count(db, *, org_id, quote_id) -> int`
    - _Requirements: 3.1, 3.8, 3.9, 3.10, 4.1, 5.3, 6.4_

  - [x] 4.2 Use storage namespace `"quote-attachments"`
    - File keys generated as `quote-attachments/{org_id}/{quote_id}/{uuid}-{filename}` so they never collide with the invoice namespace
    - _Requirements: 3.1, 12.1, 12.2, 12.3, 12.4_

  - [x] 4.3 Enforce draft-only delete rule
    - `delete_attachment` raises `ValueError` with "Attachments can only be removed while the quote is a draft" when `Quote.status != 'draft'`
    - Router layer maps this to HTTP 403
    - _Requirements: 4.1, 4.2_

  - [x] 4.4 Enforce MIME allow-list, size cap (20 MB), count cap (5)
    - `ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}`
    - `MAX_FILE_SIZE = 20 * 1024 * 1024`
    - `MAX_COUNT = 5`
    - Size violation → 413; MIME violation → 400; count violation → 400; quota exhaustion → 507
    - _Requirements: 3.2, 3.3, 3.4, 3.5_

- [x] 5. Backend — quote service updates in `app/modules/quotes/service.py`
  - [x] 5.1 Extend `create_quote()` signature with new kwargs
    - Add `order_number`, `salesperson_id`, `additional_vehicles_data`, `fluid_usage_data`, `save_terms_as_default`
    - Persist each to the corresponding column / call `PUT /org/settings` when `save_terms_as_default=True` and `terms` is non-empty
    - _Requirements: 1.1, 1.6, 1.7, 1.8, 8.1, 8.2_

  - [x] 5.2 Extend `create_quote()` line-item persistence
    - Accept `catalogue_item_id`, `stock_item_id`, `gst_inclusive`, `inclusive_price`, `tax_rate` in each line dict
    - Write every field to `quote_line_items`
    - _Requirements: 1.2_ _Property: CP-5_

  - [x] 5.3 Implement GST-inclusive back-calculation
    - When a line item has `gst_inclusive=True`, store `unit_price = inclusive_price / 1.15` rounded half-up to 2 d.p. and persist `inclusive_price` verbatim
    - `line_total = quantity * unit_price` rounded half-up to 2 d.p.
    - GST on the line = `line_total * 0.15` rounded half-up to 2 d.p.
    - Totals sum ex-GST subtotal + summed per-line GST (matches invoice calculation)
    - _Requirements: 1.10, 9.1, 9.2, 9.3, 9.4, 9.5_ _Property: CP-3_

  - [x] 5.4 Handle `save_terms_as_default`
    - When `save_terms_as_default=True` and `terms` is non-empty, update `org.settings["terms_and_conditions"] = terms` in the same transaction
    - Write an audit-log entry for settings change
    - _Requirements: 8.1, 8.2_

  - [x] 5.5 Extend `get_quote()` response enrichment
    - Join `users` on `salesperson_id` → populate `salesperson_name` as `first_name last_name` (fall back to email when names blank)
    - Call `quote_attachment_service.get_attachment_count(db, org_id, quote_id)` → populate `attachment_count`
    - Pass-through `additional_vehicles` and `fluid_usage` JSONB columns
    - _Requirements: 2.6, 5.1_

  - [x] 5.6 Extend `list_quotes()` with attachment count correlated subquery
    - Mirror `app/modules/invoices/service.py:2622` pattern
    - Add `attachment_count` as a correlated scalar subquery in the SELECT
    - Include in per-row dict returned to the router
    - _Requirements: 6.3, 6.4_ _Property: CP-6_

  - [x] 5.7 Extend `update_quote()` to rehydrate + validate status-gated edits
    - Status rules unchanged: only draft allows full edits; non-draft allows only notes
    - On inclusive line-item updates, re-derive totals using same rules as §5.3
    - _Requirements: 2.3, 2.4_

  - [x] 5.8 Update `generate_quote_pdf()` template context
    - Pass `order_number` and `salesperson_name` into `quote.html` and `quote_share.html` contexts when non-null
    - Template changes in `app/templates/pdf/quote.html` and `quote_share.html` (conditional blocks)
    - _Requirements: 1.1_

- [x] 6. Backend — quote attachment router
  - New file: `app/modules/quotes/attachment_router.py` — direct port of `app/modules/invoices/attachment_router.py`

  - [x] 6.1 `POST /api/v1/quotes/{quote_id}/attachments`
    - `dependencies=[require_role("org_admin", "salesperson")]`
    - Multipart `file` input
    - Maps service errors: `FileTooLargeError` → 413, `InvalidMimeError` → 400, `AttachmentCountExceededError` → 400, `StorageQuotaError` → 507, `ValueError("not found")` → 404
    - Returns 201 `{ "attachment": QuoteAttachmentResponse }`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 12.3, 14.1, 14.5_ _Test: TC-AU-HAPPY, TC-AU-SIZE, TC-AU-MIME, TC-AU-COUNT, TC-AU-QUOTA_

  - [x] 6.2 `GET /api/v1/quotes/{quote_id}/attachments`
    - `dependencies=[require_role("org_admin", "salesperson")]`
    - Returns 200 `{ "attachments": [...], "total": N }`
    - _Requirements: 5.5, 12.1, 14.2_ _Test: TC-AU-HAPPY_

  - [x] 6.3 `GET /api/v1/quotes/{quote_id}/attachments/{attachment_id}` (download)
    - `dependencies=[require_role("org_admin", "salesperson")]`
    - Content-Disposition formula: `inline; filename="..."` when `mime_type.startswith('image/')` OR `mime_type == 'application/pdf'`, else `attachment; filename="..."`
    - Formula MUST equal the invoice router's formula character-for-character
    - _Requirements: 3.8, 3.9, 3.10, 5.4, 12.2, 14.3_ _Property: CP-1_ _Test: TC-AU-DISPOS_

  - [x] 6.4 `DELETE /api/v1/quotes/{quote_id}/attachments/{attachment_id}`
    - `dependencies=[require_role("org_admin", "salesperson")]`
    - Service raises on non-draft → router returns 403
    - Returns 200 `{ "deleted": true }` on success
    - _Requirements: 4.1, 4.2, 4.3, 12.4, 14.4_ _Test: TC-AU-DELETE-DRAFT, TC-AU-DELETE-SENT_

  - [x] 6.5 Register router in `app/main.py`
    - `from app.modules.quotes.attachment_router import router as quote_attachment_router`
    - `app.include_router(quote_attachment_router, prefix="/api/v1/quotes", tags=["quotes"])`
    - Mount next to the existing quotes router
    - _Requirements: 3.1, 5.5, 6.3_

- [x] 7. Backend — e2e test script
  - New file: `scripts/test_quote_parity_e2e.py` following `.kiro/steering/feature-testing-workflow.md` (asyncio + httpx, `TEST_E2E_` prefix on all created rows, cleanup in `finally`)

  - [ ] 7.1 TC-AU-HAPPY — org_admin uploads JPEG ≤ 20 MB, gets 201, then GET /attachments lists it
    - _Requirements: 3.1, 5.5_ _Test: TC-AU-HAPPY_

  - [ ] 7.2 TC-AU-SIZE — upload > 20 MB returns 413, not persisted
    - _Requirements: 3.2, 10.1_ _Test: TC-AU-SIZE_

  - [ ] 7.3 TC-AU-MIME — upload .exe (or .zip) returns 400, not persisted
    - _Requirements: 3.3, 10.2_ _Test: TC-AU-MIME_

  - [ ] 7.4 TC-AU-COUNT — 6th upload returns 400, not persisted
    - _Requirements: 3.4, 10.3_ _Test: TC-AU-COUNT_

  - [ ] 7.5 TC-AU-QUOTA — force org storage quota → upload returns 507
    - _Requirements: 3.5, 10.4_ _Test: TC-AU-QUOTA_

  - [ ] 7.6 TC-AU-NETWORK — simulated 500 response surfaces retry message client-side (frontend-only assertion but record the backend hook used)
    - _Requirements: 10.5_ _Test: TC-AU-NETWORK_

  - [ ] 7.7 TC-AU-ORG404 — cross-org GET list, GET file, POST, DELETE all return 404
    - Create two `TEST_E2E_` orgs with attachments in each; authenticate as org_A and hit org_B endpoints
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_ _Property: CP-2_ _Test: TC-AU-ORG404_

  - [ ] 7.8 TC-AU-DISPOS — upload identical PDF to invoice and quote; download both; assert Content-Disposition headers identical
    - _Requirements: 3.8, 3.9, 3.10_ _Property: CP-1_ _Test: TC-AU-DISPOS_

  - [ ] 7.9 TC-AU-DELETE-DRAFT — delete on draft returns 200 and removes row
    - _Requirements: 4.1_ _Test: TC-AU-DELETE-DRAFT_

  - [ ] 7.10 TC-AU-DELETE-SENT — delete on sent/accepted returns 403, row retained
    - _Requirements: 4.2_ _Test: TC-AU-DELETE-SENT_

  - [ ] 7.11 TC-GST-ROUND — create quote with `gst_inclusive=True`, `inclusive_price=P`, `quantity=q`; assert `line_total` ≈ `q*(P/1.15)` ±0.01 and GET returns `gst_inclusive=true`, `inclusive_price=P` exactly
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_ _Property: CP-3_ _Test: TC-GST-ROUND_

  - [ ] 7.12 TC-MIG-ROUND — upgrade → downgrade → dump schema; assert bit-identical
    - Use a dedicated test DB or snapshot strategy
    - _Requirements: 13.1, 13.2, 13.7, 13.8, 13.9_ _Property: CP-4_ _Test: TC-MIG-ROUND_

  - [ ] 7.13 TC-PAY-FIDELITY — POST /quotes with every new field populated; GET /quotes/{id} returns every field unchanged
    - _Requirements: 1.1, 1.2, 1.6, 1.7, 2.3, 2.6_ _Property: CP-5_ _Test: TC-PAY-FIDELITY_

  - [ ] 7.14 TC-CREATE-400 — POST with missing customer returns 4xx with field-level error
    - _Requirements: 11.1_ _Test: TC-CREATE-400_

  - [ ] 7.15 TC-EDIT-REHYDRATE — create → edit → re-create; assert all new fields match on GET
    - _Requirements: 2.1, 2.2, 2.3_ _Test: TC-EDIT-REHYDRATE_

  - [ ] 7.16 TC-SAVE-TERMS — POST with `save_terms_as_default=true` and terms=X; verify `GET /org/settings` returns terms=X; reverse: same call with false doesn't change settings
    - _Requirements: 8.1, 8.2_ _Test: TC-SAVE-TERMS_

  - [ ] 7.17 TC-AUTH-401 — all 4 attachment endpoints + POST/PUT /quotes return 401 without auth
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.6_ _Test: TC-AUTH-401_

  - [ ] 7.18 TC-AUTH-403 — authenticated non-(org_admin/salesperson) (e.g. `viewer`) hits all new endpoints and gets 403
    - _Requirements: 14.5, 14.7_ _Test: TC-AUTH-403_

  - [ ] 7.19 Cleanup verification — final `SELECT` scan for `TEST_E2E_` rows; fail test if any remain
    - _Requirements: (discipline from `.kiro/steering/feature-testing-workflow.md`)_

- [x] 8. Backend — property tests
  - [x] 8.1 `tests/test_quote_gst_inclusive_property.py` — Hypothesis test for GST-inclusive round-trip
    - **Property CP-3: GST-inclusive round-trip**
    - Strategy: `quantity=st.decimals(min_value=Decimal("0.001"), max_value=Decimal("1000"), places=3)`, `inclusive_price=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("99999.99"), places=2)`
    - Assert `line_total ≈ q*(P/1.15)` ±0.01 after round-trip through create_quote + get_quote
    - Assert `gst_inclusive=true` and `inclusive_price=P` exact on return
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**

  - [x] 8.2 `tests/test_quote_migration_property.py` — integration test for migration reversibility
    - **Property CP-4: Migration is reversible**
    - Dump schema (columns, constraints, policies, indexes) before alembic upgrade
    - Run upgrade to 0184, then downgrade back to 0183
    - Dump schema again, assert bit-identical
    - Assert row count in `quotes` and `quote_line_items` unchanged
    - **Validates: Requirements 13.1, 13.2, 13.7, 13.8, 13.9, 17.5**

- [x] 9. Backend checkpoint
  - Run backend tests in order:
    - `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app pytest tests/test_quote_gst_inclusive_property.py tests/test_quote_migration_property.py -v`
    - `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app pytest tests/ -v --ignore=tests/e2e -x`
    - `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python scripts/test_quote_parity_e2e.py`
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Frontend — TypeScript interface deltas
  - [x] 10.1 Extend `LineItem` interface in `QuoteDetail.tsx` and `QuoteCreate.tsx`
    - Add `catalogue_item_id: string | null`, `stock_item_id: string | null`, `gst_inclusive: boolean`, `inclusive_price: string | number | null`, `tax_rate: string | number`
    - _Requirements: 2.2, 5.1_

  - [x] 10.2 Extend `QuoteData` interface in `QuoteDetail.tsx`
    - Add `order_number: string | null`, `salesperson_id: string | null`, `salesperson_name: string | null`, `additional_vehicles: Vehicle[]`, `fluid_usage: FluidUsage[]`, `attachment_count: number`
    - _Requirements: 2.6, 5.1, 6.3_

  - [x] 10.3 Extend list `Quote` interface in `QuoteList.tsx`
    - Add `attachment_count?: number`
    - Every read site uses `?? 0`
    - _Requirements: 6.3, 16.2_

  - [x] 10.4 Add `FluidUsage` interface
    - `{ stock_item_id, catalogue_item_id, litres, item_name }` with strict types
    - _Requirements: 1.7_

- [x] 11. Frontend — `QuoteCreate.tsx` header fields
  - [x] 11.1 Add `orderNumber` state + input under existing Subject field
    - Write to `buildPayload().order_number`
    - _Requirements: 1.1_

  - [x] 11.2 Add `salesperson` state + dropdown
    - On mount: `apiClient.get<{ salespeople: Salesperson[] }>('/org/salespeople')`
    - Auto-select current user id if present in response
    - Write to `buildPayload().salesperson_id`
    - `AbortController` cleanup per safe-api-consumption rules
    - _Requirements: 1.3, 16.5_

  - [x] 11.3 Add GST number read-only display
    - Source: `useTenant().settings?.gst?.gst_number`
    - _Requirements: 1.4_

  - [x] 11.4 Integrate `CustomerCreateModal`
    - Reuse `frontend/src/components/customers/CustomerCreateModal.tsx` — no new component
    - Wire "+ Add New Customer" button inside `CustomerSearch` to open modal
    - On create → call existing `onSelect(customer)` path
    - _Requirements: (UI parity from design §3.1)_

  - [x] 11.5 Replace manual rego + Lookup button with `VehicleLiveSearch`
    - Reuse `frontend/src/components/vehicles/VehicleLiveSearch.tsx`
    - Gated on `isAutomotive && isEnabled('vehicles')`
    - Auto-lookup replaces the existing "Enter" keypress trigger
    - _Requirements: (UI parity from design §3.1)_

  - [x] 11.6 Auto-fill linked vehicles when a customer is selected
    - If `customer.linked_vehicles?.length > 0`, populate the vehicles array with the first linked vehicle automatically
    - Mirror the effect in `InvoiceCreate.tsx`
    - `AbortController` cleanup per safe-api-consumption
    - _Requirements: (UI parity from design §3.1), 16.5_

- [x] 12. Frontend — `QuoteMultiVehicleSection` component
  - [x] 12.1 Create new component
    - New file: `frontend/src/components/quotes/QuoteMultiVehicleSection.tsx`
    - Props: `{ vehicles: Vehicle[]; onChange: (vehicles: Vehicle[]) => void }`
    - Renders a list with "+ Add Vehicle" button, each row editable, per-row delete
    - _Requirements: 1.6_

  - [x] 12.2 Mount `QuoteMultiVehicleSection` in `QuoteCreate.tsx`
    - Gated on `isAutomotive && isEnabled('vehicles')` — matches invoice behaviour
    - Place immediately after the primary `VehicleLiveSearch`
    - _Requirements: 1.6_

  - [x] 12.3 Persist vehicles array in `buildPayload().vehicles`
    - Send only when the array is non-empty; otherwise omit the key
    - _Requirements: 1.6_ _Property: CP-5_ _Test: TC-PAY-FIDELITY_

- [x] 13. Frontend — `QuoteCreate.tsx` line items
  - [x] 13.1 Extend inline "Add new item" form with 3-way GST mode
    - Radio: `inclusive` / `exclusive` / `exempt`
    - On `inclusive` selected: UI captures the inclusive price
    - _Requirements: 1.10_

  - [x] 13.2 Create `InventoryPickerModal` component
    - New file: `frontend/src/components/quotes/InventoryPickerModal.tsx`
    - Props: `{ open, onClose, onSelect }` where `onSelect` delivers the full stock item
    - Fetch: `apiClient.get<{ stock_items: StockItem[] }>('/inventory/stock-items')` with `AbortController`
    - _Requirements: 1.5, 16.5_

  - [x] 13.3 Wire "+ Add from Inventory" button in the line-items table
    - Opens `InventoryPickerModal`
    - On select: add a new `LineItem` with `catalogue_item_id`, `stock_item_id`, `gst_inclusive`, `inclusive_price` populated
    - _Requirements: 1.5_ _Property: CP-5_ _Test: TC-PAY-FIDELITY_

  - [x] 13.4 Extend `ItemTableRow` to display GST-inclusive label per line
    - When `line.gst_inclusive === true`, show "Incl." tag next to the price
    - _Requirements: 9.3_

  - [x] 13.5 Extend `buildPayload()` to send new line-item fields
    - Per line: `catalogue_item_id`, `stock_item_id`, `gst_inclusive`, `inclusive_price`, `tax_rate`
    - Send only fields that are non-null / non-default
    - _Requirements: 1.2_ _Property: CP-5_ _Test: TC-PAY-FIDELITY_

- [x] 14. Frontend — `QuoteCreate.tsx` fluid usage section
  - [x] 14.1 Add inline `FluidUsageSection` to `QuoteCreate.tsx`
    - Gated on `isAutomotive && isEnabled('vehicles')`
    - Rows: `{ stock_item_id, catalogue_item_id, litres, item_name }` with a picker linking to `/inventory/stock-items` filtered to fluid/oil items
    - "Add" and per-row delete buttons
    - _Requirements: 1.7_

  - [x] 14.2 Persist `fluid_usage` array in `buildPayload()`
    - Send only when non-empty; server treats as non-billable
    - _Requirements: 1.7, 1.8_ _Property: CP-5_ _Test: TC-PAY-FIDELITY_

- [x] 15. Frontend — `QuoteCreate.tsx` post-header
  - [x] 15.1 Add "Save as default for all future quotes" checkbox under T&C textarea
    - Writes `save_terms_as_default` in payload
    - On successful save, call `refetchTenant()` so the next new-quote load sees the updated default
    - _Requirements: 8.1, 8.2, 8.3, 8.4_ _Test: TC-SAVE-TERMS_

  - [x] 15.2 Wire `setNavigationGuard` / `clearNavigationGuard`
    - Mount on `useEffect` with dirty-state tracking across every new field (orderNumber, salesperson, vehicles, line items, fluid_usage, attachments, saveTermsAsDefault, etc.)
    - Cleanup on unmount
    - _Requirements: (UI parity from design §3.1)_

- [x] 16. Frontend — `QuoteCreate.tsx` attachments section
  - [x] 16.1 Render attachments list + file picker
    - File picker disabled until the quote is saved (draft or later)
    - On file pick: save draft first if needed (`handleSaveDraft`), then upload sequentially
    - _Requirements: 3.1, 3.7_

  - [x] 16.2 Client-side validation before upload
    - Reject files > 20 MB with inline message (matches server 413 text)
    - Reject MIME types outside the allow-list with inline message (matches server 400 text)
    - Reject when existing attachments already = 5 with inline message
    - _Requirements: 10.1, 10.2, 10.3_

  - [x] 16.3 Surface server errors with specific messages
    - 413 → `"File exceeds 20 MB"`
    - 400 → `"Only JPEG, PNG, WebP, GIF, and PDF files are allowed"` or count-cap message depending on server detail
    - 507 → `"Storage quota exceeded for this org"`
    - 500 / network → `"Upload failed — please retry"`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 16.4 Delete flow, draft-only
    - Each attachment row has × button — only rendered when `quote.status === 'draft'` (edit mode)
    - On click → `apiClient.delete('/quotes/{id}/attachments/{aid}')`
    - On 403 → surface "Attachments can only be removed while the quote is a draft"
    - _Requirements: 4.1, 4.2, 10.6_ _Test: TC-AU-DELETE-DRAFT, TC-AU-DELETE-SENT_

- [x] 17. Frontend — `QuoteDetail.tsx`
  - [x] 17.1 Create `QuoteAttachmentList` component
    - New file: `frontend/src/components/quotes/QuoteAttachmentList.tsx`
    - Props: `{ quoteId: string; isDraft: boolean }`
    - Fetch: `apiClient.get<QuoteAttachmentListResponse>('/quotes/{id}/attachments')` with `AbortController`
    - Render: file-type icon, filename (clickable → new tab to `/api/v1/quotes/{id}/attachments/{aid}`), size + date
    - Delete affordance only when `isDraft`
    - Returns `null` when list is empty or load fails (matches invoice pattern)
    - _Requirements: 5.3, 5.4, 16.1, 16.2, 16.3, 16.5_

  - [x] 17.2 Mount `QuoteAttachmentList` conditionally
    - `{quote.attachment_count > 0 && <QuoteAttachmentList quoteId={quote.id} isDraft={quote.status === 'draft'} />}`
    - When `attachment_count === 0`, no `<QuoteAttachmentList>` renders and no attachment GET fires
    - _Requirements: 5.1, 5.2_

  - [x] 17.3 Render new `QuoteData` fields (read-only)
    - `order_number` (in the header metadata grid when non-null)
    - `salesperson_name` (in the header metadata grid when non-null)
    - `additional_vehicles` summary (list of "rego year make model" rows)
    - `fluid_usage` section (read-only list, non-billable)
    - _Requirements: 2.1, 2.6_

  - [x] 17.4 Per-line GST-inclusive / ex-GST labels
    - When `line.gst_inclusive === true`, show "Incl." next to the rate
    - When `line.gst_inclusive === false` and `line.tax_rate > 0`, show "Ex-GST"
    - _Requirements: 9.3_

- [x] 18. Frontend — `QuoteList.tsx`
  - [x] 18.1 Add 📎 attachment count badge next to quote number
    - Render `<span className="...">📎 {q.attachment_count ?? 0}</span>` only when `(q.attachment_count ?? 0) > 0`
    - Omit entirely when count is 0 or null
    - _Requirements: 6.1, 6.2_ _Property: CP-6_ _Test: TC-LIST-BADGE_

  - [x] 18.2 Add per-row PDF/Print dropdown
    - Two menu items only: "Download PDF" and "Print Quote"
    - "Download PDF": `apiClient.get('/quotes/{id}/pdf', { responseType: 'blob' })` + trigger browser download
    - "Print Quote": navigate to `/quotes/{id}` and invoke `window.print()` via a post-load hook (URL query param or store flag)
    - _Requirements: 7.1, 7.2, 7.4, 7.5_ _Test: TC-LIST-DOWNLOAD, TC-LIST-PRINT_

  - [x] 18.3 Explicitly exclude "Print POS Receipt" menu item
    - Render-time assertion: dropdown markup must not contain a menu item whose label matches `/print pos receipt/i`
    - Gated by NO conditional — unconditionally absent regardless of trade family, status, or active modules
    - _Requirements: 7.3_ _Property: CP-7_ _Test: TC-LIST-NO-POS_

- [x] 19. Frontend — component + property tests
  - [x] 19.1 Vitest: `QuoteList` badge visibility (CP-6)
    - Render list with fixtures: `attachment_count=0`, `attachment_count=null`, `attachment_count=3`
    - Assert badge absent for 0 and null, present showing "3" for 3
    - _Requirements: 6.1, 6.2_ _Property: CP-6_ _Test: TC-LIST-BADGE_

  - [x] 19.2 Vitest: `QuoteList` PDF dropdown never contains "Print POS Receipt" (CP-7)
    - Parametrise across every trade family supported in `useTenant()`
    - Render, open dropdown, assert no element matches `/print pos receipt/i`
    - Assert "Download PDF" and "Print Quote" both present
    - _Requirements: 7.3_ _Property: CP-7_ _Test: TC-LIST-NO-POS_

  - [x] 19.3 Vitest: `QuoteCreate` payload fidelity (CP-5)
    - Mock `apiClient.post` to capture argument
    - Drive every new field via user-event
    - Assert the captured payload contains `order_number`, `salesperson_id`, `vehicles`, `fluid_usage`, `save_terms_as_default`, and per-line `catalogue_item_id`, `stock_item_id`, `gst_inclusive`, `inclusive_price`, `tax_rate`
    - _Requirements: 1.1, 1.2, 1.6, 1.7_ _Property: CP-5_ _Test: TC-PAY-FIDELITY_

  - [x] 19.4 Vitest: `QuoteAttachmentList` delete affordance
    - Fixture A: `isDraft=true` → delete button rendered per row
    - Fixture B: `isDraft=false` → no delete button rendered for any row
    - _Requirements: 4.4, 4.5_ _Test: TC-AU-DELETE-DRAFT, TC-AU-DELETE-SENT_

  - [x] 19.5 Vitest: `QuoteDetail` mounts `QuoteAttachmentList` iff attachment_count > 0
    - Fixture A: `attachment_count=0` → component not mounted, no GET fires
    - Fixture B: `attachment_count=3` → component mounted, one GET fires
    - _Requirements: 5.1, 5.2_

  - [x] 19.6 Vitest: `QuoteList` Download PDF action
    - Click Download PDF on a row; assert `apiClient.get` called with `/quotes/{id}/pdf` and `{ responseType: 'blob' }`
    - _Requirements: 7.4_ _Test: TC-LIST-DOWNLOAD_

  - [x] 19.7 Vitest: `QuoteList` Print Quote action
    - Click Print Quote on a row; assert navigation happens and `window.print` fires after mount of detail page
    - _Requirements: 7.5_ _Test: TC-LIST-PRINT_

- [x] 20. Frontend checkpoint
  - `npm --prefix frontend run build` — confirm clean production build
  - `npm --prefix frontend run test -- --run` — confirm every new and existing test passes
  - Ensure all tests pass, ask the user if questions arise.

- [x] 21. Version bump and CHANGELOG (target `1.6.0`)
  - [x] 21.1 Bump `pyproject.toml` from `1.5.0` → `1.6.0`
    - _Requirements: (release discipline — `.kiro/steering/versioning-and-changelog.md`)_

  - [x] 21.2 Bump `frontend/package.json` from `1.5.0` → `1.6.0`
    - _Requirements: (release discipline)_

  - [x] 21.3 Bump `mobile/package.json` from `1.5.0` → `1.6.0`
    - No functional mobile change in this PR; bump keeps the three versions aligned
    - _Requirements: (release discipline)_

  - [x] 21.4 Add `[1.6.0]` entry to `CHANGELOG.md`
    - Content as drafted in `design.md` §14.3 (Added: parity fields, attachments endpoints, QuoteAttachmentList, 📎 badge, PDF/Print dropdown; Changed: `quotes` / `quote_line_items` columns, schemas additive, QuoteCreate payload extended)
    - _Requirements: (release discipline)_

- [ ] 22. Release — git push + Pi rebuild verification
  - [ ] 22.1 Full e2e run against dev
    - `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python scripts/test_quote_parity_e2e.py` — confirm every TC passes and cleanup leaves zero `TEST_E2E_` rows
    - _Requirements: (release discipline — `.kiro/steering/feature-testing-workflow.md`)_

  - [ ] 22.2 Commit on a new branch and push to GitHub
    - `git checkout -b feature/quote-invoice-parity`
    - Stage only the files touched by this spec
    - Commit with a message mentioning the feature name and `1.6.0`
    - `git push -u origin feature/quote-invoice-parity`
    - _Requirements: (release discipline — `project-overview.md` → Deployment Process)_

  - [ ] 22.3 Sync code to Pi and rebuild app container
    - `tar -cf - alembic/versions/2026_05_XX_0900-0184_quote_invoice_parity.py app/modules/quotes/ app/templates/pdf/quote.html app/templates/pdf/quote_share.html app/main.py scripts/test_quote_parity_e2e.py tests/test_quote_gst_inclusive_property.py tests/test_quote_migration_property.py pyproject.toml CHANGELOG.md | ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && tar -xf -"`
    - `ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate app"`
    - Confirm container comes up healthy and `alembic upgrade head` reports `0184`
    - _Requirements: 13.1, 13.2, 13.5, 13.6_

  - [ ] 22.4 Sync frontend + rebuild frontend/nginx on Pi
    - Sync `frontend/src/pages/quotes/`, `frontend/src/components/quotes/`, `frontend/src/components/invoices/AttachmentList.tsx` (if any import changes), `frontend/package.json`, `mobile/package.json`
    - Follow `project-overview.md` step 4: stop frontend+nginx, remove containers, delete `invoicing_frontend_dist` volume, rebuild with `--build`
    - Confirm `https://<pi-host>:8999/quotes/:id` renders the attachment section for a quote with attachments, and `https://<pi-host>:8999/quotes` shows the 📎 badge + PDF dropdown
    - _Requirements: (release discipline — `project-overview.md` → Deployment Process)_

  - [ ] 22.5 Final checkpoint
    - Ensure all tests pass, ask the user if questions arise.

## Notes

- Properties `CP-1..CP-7` are all mandatory per `design.md` §11. Each has a dedicated required task:
  - CP-1 → Task 6.3 + 7.8
  - CP-2 → Task 7.7
  - CP-3 → Task 5.3 + 7.11 + 8.1
  - CP-4 → Task 1.5 + 7.12 + 8.2
  - CP-5 → Task 7.13 + 19.3 (and implicitly 12.3, 13.3, 13.5, 14.2)
  - CP-6 → Task 18.1 + 19.1
  - CP-7 → Task 18.3 + 19.2
- Every explicitly-out-of-scope item from `design.md` §12 is **not** in this task list: no "Make Recurring" toggle, no "Mark Paid & Email", no payment gateway selector, no Stripe Connect indicator, no payment reminders, no bulk delete, no POS receipt. A property test enforces the POS exclusion.
- OQ-1 and OQ-2 are both resolved **YES** — every OQ-gated task is required, not conditional.
- `tasks.md` covers only coding, schema, tests, version bumps, and release. No docs, no planning, no UAT, no manual QA, no performance work.
- The 18 backend e2e cases map 1:1 to Tasks 7.1..7.18 (plus 7.19 cleanup). The 7 frontend vitest cases map 1:1 to Tasks 19.1..19.7.
