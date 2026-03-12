# Implementation Plan: Universal Items Catalogue

## Overview

Transform the existing garage-specific `service_catalogue` table and API into a universal "Items" concept. Rename the DB table, remove the hardcoded category CHECK constraint, update backend model/schemas/service/router, update all frontend consumers (BookingForm, QuoteCreate, InvoiceCreate), add a dedicated Zoho-style Items management page at `/items`, and update sidebar navigation.

## Tasks

- [x] 1. Database migration and model updates
  - [x] 1.1 Create Alembic migration 0082 to rename `service_catalogue` → `items_catalogue` and remove CHECK constraint
    - Drop CHECK constraint `ck_service_catalogue_category` from `service_catalogue`
    - Rename table `service_catalogue` → `items_catalogue`
    - Drop and recreate FK `bookings_service_catalogue_id_fkey` to point to `items_catalogue`
    - Include downgrade to reverse all changes
    - File: `alembic/versions/2026_03_11_1100-0082_universal_items_catalogue.py`
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 1.2 Update `ServiceCatalogue` → `ItemsCatalogue` model in `app/modules/catalogue/models.py`
    - Rename class to `ItemsCatalogue`, set `__tablename__ = "items_catalogue"`
    - Change `category` from `String(50), nullable=False` to `String(100), nullable=True`
    - Remove `__table_args__` with CHECK constraint
    - Update backref from `service_catalogue_items` to `items_catalogue_entries`
    - _Requirements: 7.1, 7.2_

- [x] 2. Backend schema updates
  - [x] 2.1 Add `Item*` Pydantic schemas in `app/modules/catalogue/schemas.py`
    - Add `ItemCreateRequest` with `category: Optional[str]` (max_length=100) instead of `Literal[...]`
    - Add `ItemUpdateRequest` with `category: Optional[str]` (max_length=100)
    - Add `ItemResponse` with `category: Optional[str]`
    - Add `ItemListResponse` (key: `items`), `ItemCreateResponse`, `ItemUpdateResponse`
    - Keep existing `Service*` schemas for backward-compatible legacy endpoints
    - _Requirements: 7.3, 7.4, 7.5_

  - [x] 2.2 Write property test for schema round-trip preservation
    - **Property 10: Schema round-trip preservation**
    - Generate random valid Item dicts, serialize via `_item_to_dict()`, construct `ItemResponse` — assert equivalence
    - File: `tests/test_items_catalogue_property.py`
    - **Validates: Requirement 7.6**

- [x] 3. Backend service layer updates
  - [x] 3.1 Rename and update service functions in `app/modules/catalogue/service.py`
    - Rename `_service_to_dict` → `_item_to_dict`, `list_services` → `list_items`, `create_service` → `create_item`, `update_service` → `update_item`, `get_service` → `get_item`
    - Update all references from `ServiceCatalogue` to `ItemsCatalogue`
    - Add `search` parameter to `list_items` with `name.ilike(f"%{search}%")` filtering
    - Remove hardcoded `valid_categories` check from `create_item` and `update_item` — accept any string or None
    - Update audit log actions: `catalogue.service.*` → `catalogue.item.*`
    - _Requirements: 1.4, 1.5, 2.1, 2.2, 2.3, 2.5_

  - [x] 3.2 Write property test for free-text category acceptance
    - **Property 2: Category accepts any string or null**
    - Generate random strings (length 1–100) and None — assert `create_item` accepts all
    - File: `tests/test_items_catalogue_property.py`
    - **Validates: Requirement 1.4, 1.5**

  - [x] 3.3 Write property test for case-insensitive search
    - **Property 3: Search filters by name case-insensitively**
    - Generate random item names and search queries — assert filtering matches `q.lower() in n.lower()`
    - File: `tests/test_items_catalogue_property.py`
    - **Validates: Requirement 2.5**

  - [x] 3.4 Write property test for negative price rejection
    - **Property 6: Negative price rejected**
    - Generate random negative decimal values — assert `create_item` and `update_item` raise ValueError
    - File: `tests/test_items_catalogue_property.py`
    - **Validates: Requirement 2.8**

- [x] 4. Backend router updates
  - [x] 4.1 Add new `/items` endpoints to `app/modules/catalogue/router.py`
    - `GET /items` — list items with `active_only`, `category`, `search`, `limit`, `offset` params
    - `POST /items` — create item using `ItemCreateRequest` schema
    - `PUT /items/{item_id}` — update item using `ItemUpdateRequest` schema
    - `DELETE /items/{item_id}` — soft-delete (set `is_active=false`)
    - All endpoints use `ItemResponse`/`ItemListResponse`/`ItemCreateResponse`/`ItemUpdateResponse` schemas
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.8, 2.9_

  - [x] 4.2 Convert existing `/services` endpoints to legacy proxies
    - Update `list_services_endpoint` to call `list_items()` internally, return `ServiceListResponse`
    - Update `create_service_endpoint` to call `create_item()` internally, return `ServiceCreateResponse`
    - Update `update_service_endpoint` to call `update_item()` internally, return `ServiceUpdateResponse`
    - _Requirements: 2.6, 2.7_

  - [x] 4.3 Write property test for soft-delete behavior
    - **Property 5: Soft-delete sets is_active to false**
    - Create items, delete them, assert `is_active=false` and still retrievable with `active_only=false`
    - File: `tests/test_items_catalogue_property.py`
    - **Validates: Requirement 2.4**

  - [x] 4.4 Write property test for cross-org access denial
    - **Property 7: Cross-org access denied**
    - Create items for org A, attempt update/delete from org B — assert 404/ValueError
    - File: `tests/test_items_catalogue_property.py`
    - **Validates: Requirement 2.9**

  - [x] 4.5 Write property test for legacy endpoint equivalence
    - **Property 4: Legacy endpoints return equivalent data**
    - Create items, call both `/items` and `/services` list endpoints — assert same data, different response keys
    - File: `tests/test_items_catalogue_property.py`
    - **Validates: Requirement 2.6, 2.7**

- [x] 5. Checkpoint — Backend complete
  - Run migration 0082 and all backend property tests. Ensure everything passes. Ask the user if questions arise.

- [x] 6. Frontend — Items management page
  - [x] 6.1 Create `frontend/src/pages/items/ItemsPage.tsx` — Zoho-style Items CRUD page
    - Table with columns: Name, Category, Price, GST Exempt, Status (Active/Inactive)
    - Search input above table for real-time name filtering via `GET /api/v1/catalogue/items?search=...`
    - "New Item" button opens a modal/slide-over form with: Name, Description, Default Price, Category (free-text), GST Exempt toggle
    - Clicking a row opens edit form pre-populated with current values
    - Active/Inactive toggle directly in table rows via `PUT /api/v1/catalogue/items/{id}`
    - Pagination controls at bottom
    - Success/error notifications
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

  - [x] 6.2 Register `/items` route in `frontend/src/App.tsx`
    - Add lazy import for `ItemsPage`
    - Add `<Route path="/items" ...>` in the org-level routes section near the `/catalogue` route
    - _Requirements: 3.1_

  - [x] 6.3 Add "Items" entry to sidebar navigation in `frontend/src/layouts/OrgLayout.tsx`
    - Add `{ to: '/items', label: 'Items', icon: CatalogueIcon, module: 'catalogue' }` before the existing Catalogue entry
    - Keep existing Catalogue entry for Parts and Labour Rates
    - _Requirements: 4.1, 4.2_

  - [x] 6.4 Write frontend property test for Items page table columns
    - **Property 8: Items page displays all table columns**
    - Generate random Item data — assert table renders name, category, price, GST exempt, status for each
    - File: `frontend/src/__tests__/items-catalogue.property.test.tsx`
    - **Validates: Requirement 3.2**

- [x] 7. Frontend — BookingForm updates
  - [x] 7.1 Update BookingForm to use Items terminology and API in `frontend/src/pages/bookings/BookingForm.tsx`
    - Change label from "Service Type" to "Item"
    - Change placeholder from "Search services…" to "Search items…"
    - Change API call from `GET /catalogue/services` to `GET /catalogue/items`
    - Change inline creation API from `POST /catalogue/services` to `POST /catalogue/items`
    - Change "Add new service" to "Add new item", "New Service" heading to "New Item"
    - Replace the hardcoded category `<Select>` dropdown (Service/Repair/Warrant/Diagnostic) with a free-text `<Input>` for category (optional)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 7.2 Write frontend property test for BookingForm Items API usage
    - **Property 9: BookingForm uses Items API**
    - Assert typeahead calls `GET /catalogue/items` with `active_only=true`, inline creation calls `POST /catalogue/items`
    - File: `frontend/src/__tests__/items-catalogue.property.test.tsx`
    - **Validates: Requirement 5.4, 5.5**

- [x] 8. Frontend — QuoteCreate and InvoiceCreate updates
  - [x] 8.1 Update QuoteCreate to use Items API in `frontend/src/pages/quotes/QuoteCreate.tsx`
    - Change API call from `GET /catalogue/services` to `GET /catalogue/items`
    - Update response parsing from `data.services` to `data.items`
    - _Requirements: 6.1_

  - [x] 8.2 Update InvoiceCreate to use Items API in `frontend/src/pages/invoices/InvoiceCreate.tsx`
    - Change API call from `GET /catalogue/services` to `GET /catalogue/items`
    - Update response parsing from `data.services` to `data.items`
    - _Requirements: 6.2_

- [x] 9. Final checkpoint — Full integration
  - Run all backend and frontend property tests. Ensure migration applies cleanly. Verify all API endpoints work. Ask the user if questions arise.

## Notes

- Current DB migration head: 0081 — new migration must be 0082
- Use `hypothesis` with `max_examples=20` for backend property tests
- Use `fast-check` with `numRuns: 20` for frontend property tests
- Tests run in Docker: `docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec app pytest ...`
- Service functions use `db.flush()` only (not commit) — by design for transaction composition
- The `get_db_session` dependency auto-commits — router endpoints must NOT call `db.commit()`
- After `db.flush()`, server-generated columns need `await db.refresh(obj)`
- Keep existing `Service*` schemas and legacy `/services` endpoints for backward compatibility
- The catalogue router is mounted at `/api/v1/catalogue` prefix in `app/main.py`
- Existing `CataloguePage` at `/catalogue` remains for Parts and Labour Rates management
