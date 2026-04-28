# Implementation Plan: Plumbing Service Types

## Overview

Incremental implementation of the Service Type Catalogue for plumbing/gas trade organisations. Starts with database models and migration, builds the backend CRUD API, then adds frontend components for management and job card integration. Finishes with catalogue page cleanup and property-based tests.

## Tasks

- [x] 1. Create database models and Alembic migration
  - [x] 1.1 Create `app/modules/service_types/__init__.py` (empty)
  - [x] 1.2 Create `app/modules/service_types/models.py` with three SQLAlchemy models:
    - `ServiceType`: id (UUID PK), org_id (FK → organisations.id), name (VARCHAR 255), description (TEXT nullable), is_active (BOOLEAN default true), created_at, updated_at. Relationship: `fields` (list of ServiceTypeField, cascade all/delete-orphan, ordered by display_order), `organisation` backref
    - `ServiceTypeField`: id (UUID PK), service_type_id (FK → service_types.id ON DELETE CASCADE), label (VARCHAR 255), field_type (VARCHAR 20), display_order (INTEGER default 0), is_required (BOOLEAN default false), options (JSONB nullable). Relationship: `service_type` back_populates
    - `JobCardServiceTypeValue`: id (UUID PK), job_card_id (FK → job_cards.id ON DELETE CASCADE), field_id (FK → service_type_fields.id), value_text (TEXT nullable), value_array (JSONB nullable)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 7.1, 7.2_
  - [x] 1.3 Create Alembic migration `alembic/versions/YYYY_MM_DD_HHMM-0140_add_service_types.py`:
    - CREATE TABLE `service_types` with all columns and `ix_service_types_org_id` index
    - CREATE TABLE `service_type_fields` with all columns, FK, and `ix_service_type_fields_service_type_id` index
    - CREATE TABLE `job_card_service_type_values` with all columns, FKs, `ix_jcstv_job_card_id` index, and `uq_jcstv_job_card_field` UNIQUE constraint on (job_card_id, field_id)
    - ALTER TABLE `job_cards` ADD COLUMN `service_type_id UUID REFERENCES service_types(id)` (nullable)
    - CREATE UNIQUE INDEX `uq_service_types_org_name` ON service_types (org_id, name) WHERE is_active = true (partial unique index)
    - Enable RLS on all three new tables with policies matching `app.current_org_id`
    - Use `IF NOT EXISTS` for idempotency where possible
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 6.5, 7.1_
  - [x] 1.4 Add `service_type_id` column to the `JobCard` model in `app/modules/job_cards/models.py`:
    - Nullable FK to `service_types.id`, no ON DELETE CASCADE
    - Add relationship: `service_type = relationship("ServiceType")`
    - _Requirements: 6.1, 6.5, 6.6_

- [x] 2. Implement backend service layer and Pydantic schemas
  - [x] 2.1 Create `app/modules/service_types/schemas.py` with Pydantic models:
    - `ServiceTypeFieldDefinition`: label (str, min_length=1, max_length=255, strip_whitespace=True), field_type (Literal["text","select","multi_select","number"]), display_order (int, ge=0), is_required (bool, default False), options (list[str] | None)
    - `ServiceTypeCreateRequest`: name (str, min_length=1, max_length=255), description (str | None, max_length=2000), is_active (bool, default True), fields (list[ServiceTypeFieldDefinition], default_factory=list)
    - `ServiceTypeUpdateRequest`: name (str | None), description (str | None), is_active (bool | None), fields (list[ServiceTypeFieldDefinition] | None — None means no change, [] means remove all)
    - `ServiceTypeFieldResponse`: id, label, field_type, display_order, is_required, options
    - `ServiceTypeResponse`: id, name, description, is_active, fields (list[ServiceTypeFieldResponse]), created_at, updated_at
    - `ServiceTypeListResponse`: service_types (list[ServiceTypeResponse], default_factory=list), total (int, default 0)
    - Add a validator on `ServiceTypeFieldDefinition` to strip whitespace from label and reject whitespace-only labels
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 4.5_
  - [x] 2.2 Create `app/modules/service_types/service.py` with business logic functions:
    - `create_service_type(db, org_id, name, description, is_active, fields)` — creates ServiceType + ServiceTypeField children, uses `db.flush()` then `db.refresh()`, returns dict
    - `list_service_types(db, org_id, active_only, limit, offset)` — paginated list with eager-loaded fields, returns `{"service_types": [...], "total": N}`
    - `get_service_type(db, org_id, service_type_id)` — single fetch with fields, raises ValueError if not found
    - `update_service_type(db, org_id, service_type_id, **kwargs)` — updates scalar fields; if `fields` key is present and not None, deletes all existing ServiceTypeField rows and inserts new set (full replacement per Req 2.5)
    - `delete_service_type(db, org_id, service_type_id)` — checks for FK references in job_cards, returns 409 if referenced, otherwise hard-deletes
    - `_service_type_to_dict(service_type)` — helper to convert ORM object to dict for Pydantic serialization
    - All functions use `db.flush()` not `db.commit()` (per performance-and-resilience steering)
    - _Requirements: 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

- [x] 3. Implement backend router and register in main app
  - [x] 3.1 Create `app/modules/service_types/router.py` with FastAPI endpoints:
    - `GET /` — list service types, auth: org_admin + salesperson, query params: active_only, limit, offset
    - `POST /` — create service type, auth: org_admin, request body: ServiceTypeCreateRequest, returns 201
    - `GET /{service_type_id}` — get single service type with fields, auth: org_admin + salesperson
    - `PUT /{service_type_id}` — update service type, auth: org_admin, request body: ServiceTypeUpdateRequest
    - `DELETE /{service_type_id}` — delete service type, auth: org_admin, returns 409 if referenced by job cards
    - Use `_extract_org_context(request)` pattern from catalogue router for org_id/user_id extraction
    - Handle IntegrityError for duplicate name (409), ValueError for not found (404), invalid UUID (400)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_
  - [x] 3.2 Register the router in `app/main.py`:
    - `from app.modules.service_types.router import router as service_types_router`
    - `app.include_router(service_types_router, prefix="/api/v1/service-types", tags=["service-types"])`
    - _Requirements: 2.1_

- [x] 4. Checkpoint — Backend verification
  - Ensure all tests pass, ask the user if questions arise.
  - Run the Alembic migration against the dev database: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head`
  - Verify the three new tables and the `job_cards.service_type_id` column exist

- [x] 5. Create frontend ServiceTypesTab component
  - [x] 5.1 Create `frontend/src/pages/items/ServiceTypesTab.tsx`:
    - Fetch service types from `GET /service-types` with AbortController cleanup
    - Use `res.data?.service_types ?? []` and `res.data?.total ?? 0` for safe API consumption
    - Render a table with columns: Name, Description (truncated), Fields (count of additional info fields), Status (active/inactive badge), Actions (Edit, Toggle Active)
    - "+ New Service Type" button opens ServiceTypeModal in create mode
    - "Edit" action opens ServiceTypeModal in edit mode with pre-populated data
    - "Toggle Active" sends PUT to update `is_active` and refreshes the list
    - Use `useTerm('service_types', 'Service Types')` from TerminologyContext for the heading
    - _Requirements: 3.3, 3.4, 3.5, 3.6, 8.1_
  - [x] 5.2 Create `frontend/src/pages/items/ServiceTypeModal.tsx`:
    - Modal form for create/edit with fields: name (required), description (optional)
    - Dynamic "Additional Info Fields" section:
      - Each field row: label input (required), field_type select (text/select/multi_select/number), required toggle, display_order (drag or up/down), remove button
      - When field_type is "select" or "multi_select", show options editor (add/remove string values)
      - "+ Add Field" button to add new field definitions
    - Client-side validation: name required, field labels non-empty, at least warn on whitespace-only labels
    - On save: POST for create, PUT for edit (sends full field list as replacement)
    - Close modal and refresh parent list on success
    - _Requirements: 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 6. Integrate Service Types tab into Items page
  - [x] 6.1 Modify `frontend/src/pages/items/ItemsPage.tsx`:
    - Import `useTenant` from `@/contexts/TenantContext` and `useTerm` from `@/contexts/TerminologyContext`
    - Import `ServiceTypesTab` from `./ServiceTypesTab`
    - Add trade family check: `const isPlumbing = (tradeFamily ?? 'automotive-transport') === 'plumbing-gas'`
    - Conditionally add third tab: `...(isPlumbing ? [{ id: 'service-types', label: useTerm('service_types', 'Service Types'), content: <ServiceTypesTab /> }] : [])`
    - _Requirements: 3.1, 3.2, 8.1, 8.2_

- [x] 7. Modify Catalogue page to remove Services tab
  - [x] 7.1 Modify `frontend/src/pages/catalogue/CataloguePage.tsx`:
    - Remove the `ServiceCatalogue` import
    - Remove the `{ id: 'services', label: 'Services', content: <ServiceCatalogue /> }` entry from the tabs array
    - For automotive orgs: show Parts and Fluids/Oils tabs as before
    - For plumbing-gas orgs (and any non-automotive): show empty state message directing users to the Items page
    - If no tabs remain, render a message: "No catalogue sections available for your trade type. Manage your items on the Items page."
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [x] 8. Checkpoint — Frontend management UI verification
  - Ensure all tests pass, ask the user if questions arise.
  - Verify the Items page shows the Service Types tab for plumbing-gas orgs
  - Verify the Catalogue page no longer shows the Services tab

- [x] 9. Implement job card integration — backend
  - [x] 9.1 Create service functions for storing/retrieving field values in `app/modules/service_types/service.py`:
    - `save_service_type_values(db, job_card_id, service_type_id, values: list[dict])` — stores field values in `job_card_service_type_values`, each dict has `field_id`, optional `value_text`, optional `value_array`
    - `get_service_type_values(db, job_card_id)` — returns list of field values with field label and type info for display
    - _Requirements: 6.3, 7.1, 7.2, 7.4_
  - [x] 9.2 Update job card create/update service in `app/modules/job_cards/service.py`:
    - Accept optional `service_type_id` and `service_type_values` parameters
    - On create/update: set `job_card.service_type_id`, call `save_service_type_values()` if values provided
    - On get: include service type name and field values in the response
    - _Requirements: 6.1, 6.3, 6.5, 7.4_
  - [x] 9.3 Update job card schemas in `app/modules/job_cards/schemas.py`:
    - Add `service_type_id: str | None` and `service_type_values: list[dict] | None` to create/update request schemas
    - Add `service_type_name: str | None`, `service_type_id: str | None`, and `service_type_values: list[dict] | None` to response schema
    - _Requirements: 6.3, 6.4, 7.4_
  - [x] 9.4 Update job card router in `app/modules/job_cards/router.py`:
    - Pass `service_type_id` and `service_type_values` through to service functions on create/update
    - Ensure service type data is NOT included when converting job card to invoice (service types don't flow to invoices)
    - _Requirements: 6.3, 6.7_

- [x] 10. Implement job card integration — frontend
  - [x] 10.1 Create `frontend/src/components/service-types/ServiceTypeSelector.tsx`:
    - Fetch active service types from `GET /service-types?active_only=true` with AbortController
    - Render a dropdown/select to choose a service type (optional — can be left blank)
    - When a service type is selected, fetch its field definitions and dynamically render form fields:
      - `text` → text input
      - `number` → number input
      - `select` → dropdown with predefined options
      - `multi_select` → multi-select checkboxes or tag picker with predefined options
    - Respect `is_required` flag on each field for validation
    - Expose `serviceTypeId` and `serviceTypeValues` for parent form to include in payload
    - Use safe API consumption patterns (`?? []`, `?? 0`, AbortController)
    - _Requirements: 6.1, 6.2, 6.5_
  - [x] 10.2 Modify `frontend/src/pages/job-cards/JobCardCreate.tsx`:
    - Import `useTenant` and check `isPlumbing` trade family gate
    - Conditionally render `<ServiceTypeSelector />` when `isPlumbing` is true
    - Include `service_type_id` and `service_type_values` in the create payload (conditionally, only when plumbing)
    - _Requirements: 6.1, 6.2, 6.3, 6.5_
  - [x] 10.3 Modify `frontend/src/pages/job-cards/JobCardDetail.tsx`:
    - When the job card has a `service_type_name`, display it in a "Service Type" section
    - Display filled-in field values with their labels (read-only)
    - Handle deactivated service types gracefully — still show the name and values
    - Use safe API consumption patterns for all service type data access
    - _Requirements: 6.4, 6.6_

- [x] 11. Checkpoint — Full integration verification
  - Ensure all tests pass, ask the user if questions arise.
  - Verify job card create/edit with service type selection works end-to-end
  - Verify job card detail displays service type and field values
  - Verify job card → invoice conversion does NOT include service type data

- [x] 12. Property-based tests with Hypothesis
  - [x] 12.1 Write property test for CRUD round-trip (Property 1)
    - **Property 1: Service Type CRUD round-trip preserves data**
    - For any valid name, description, and field definitions, creating then retrieving should return matching data
    - Use `hypothesis.strategies` to generate random names (1-255 chars), descriptions (0-2000 chars), field definitions (0-10 fields with random labels, types, options)
    - Target `create_service_type()` and `get_service_type()` service functions directly
    - **Validates: Requirements 1.4, 2.1, 2.3, 2.4**
  - [x] 12.2 Write property test for unique name enforcement (Property 2)
    - **Property 2: Unique name enforcement within organisation**
    - For any org and name, creating two active service types with the same name in the same org should fail; same name in different orgs should succeed
    - **Validates: Requirements 1.5**
  - [x] 12.3 Write property test for field replacement (Property 3)
    - **Property 3: Field definition full replacement**
    - For any service type with initial fields, updating with a new field set should result in exactly the new set — no remnants of the old set
    - **Validates: Requirements 2.5**
  - [x] 12.4 Write property test for whitespace-only label rejection (Property 4)
    - **Property 4: Whitespace-only labels are rejected**
    - For any string of only whitespace characters, creating a field with that label should be rejected by Pydantic validation
    - **Validates: Requirements 4.5**
  - [x] 12.5 Write property test for job card field value round-trip (Property 5)
    - **Property 5: Job card service type value round-trip**
    - For any service type with fields and valid values, storing on a job card then retrieving should return identical data
    - **Validates: Requirements 6.3, 7.1, 7.2, 7.4**
  - [x] 12.6 Write property test for field value immutability (Property 6)
    - **Property 6: Field values are immutable after service type field update**
    - For any job card with stored field values, updating the parent service type's fields should not change the stored values
    - **Validates: Requirements 7.3**

- [x] 13. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Verify all requirements are covered by implementation tasks
  - Confirm no orphaned or hanging code exists

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document using Hypothesis
- Unit tests validate specific examples and edge cases
- All frontend code must follow safe-api-consumption.md patterns (optional chaining, nullish coalescing, AbortController)
- The `get_db_session` dependency uses `session.begin()` which auto-commits — use `flush()` not `commit()` in service functions (per ISSUE-044 / performance-and-resilience steering)
- Trade family gating uses `(tradeFamily ?? 'automotive-transport') === 'plumbing-gas'` pattern per steering doc
- Service Types do NOT flow to invoices — they are metadata on the job card only
