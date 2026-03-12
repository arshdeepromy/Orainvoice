# Requirements Document

## Introduction

This feature transforms the existing garage-specific "Service Catalogue" into a universal "Items" concept. Items are industry-agnostic catalogue entries that can be used as line items in bookings, quotes, and invoices. The hardcoded category constraint (`warrant`, `service`, `repair`, `diagnostic`) is replaced with a free-text, organisation-defined category field. A dedicated Zoho-style Items management page is added at `/items` for full CRUD operations. All UI labels referencing "Service Type" are renamed to "Item" throughout the application.

## Glossary

- **Item**: A universal catalogue entry representing a product or service that an organisation offers. Replaces the former "Service Catalogue" concept. Stored in the `items_catalogue` table (renamed from `service_catalogue`).
- **Items_Page**: The dedicated management page at `/items` providing full CRUD for Items, styled similarly to Zoho Books Items page.
- **Items_API**: The backend REST API endpoints under `/api/v1/catalogue/items` that provide create, read, update, and delete operations for Items.
- **BookingForm**: The modal form component used to create and edit bookings, which includes an Item typeahead search and inline Item creation form.
- **QuoteCreate**: The page component for creating quotes, which uses Items as line items.
- **InvoiceCreate**: The page component for creating invoices, which uses Items as line items.
- **Organisation**: A tenant in the multi-tenant system, scoped by RLS. Each Organisation manages its own Items.
- **Category**: A free-text, organisation-defined classification for an Item. No longer constrained to a fixed set of values.

## Requirements

### Requirement 1: Rename Database Table and Remove Hardcoded Category Constraint

**User Story:** As a developer, I want the service_catalogue table renamed to items_catalogue with the hardcoded category CHECK constraint removed, so that the data model supports universal, industry-agnostic items.

#### Acceptance Criteria

1. WHEN a database migration is applied, THE Items_API SHALL rename the `service_catalogue` table to `items_catalogue` while preserving all existing data rows.
2. WHEN a database migration is applied, THE Items_API SHALL remove the CHECK constraint `ck_service_catalogue_category` from the category column.
3. THE `items_catalogue` table SHALL retain all existing columns: `id`, `org_id`, `name`, `description`, `default_price`, `is_gst_exempt`, `category`, `is_active`, `created_at`, `updated_at`.
4. WHEN an Item is created with any non-empty string as the category value, THE Items_API SHALL accept and persist the category value.
5. WHEN an Item is created without a category value, THE Items_API SHALL accept the Item with a null category.

### Requirement 2: Update Backend API Endpoints for Items

**User Story:** As a developer, I want the catalogue API endpoints updated to use "items" terminology and accept free-text categories, so that the API is consistent with the universal Items concept.

#### Acceptance Criteria

1. THE Items_API SHALL expose a `GET /api/v1/catalogue/items` endpoint that lists Items for the authenticated Organisation with support for `active_only`, `category`, `search`, `limit`, and `offset` query parameters.
2. THE Items_API SHALL expose a `POST /api/v1/catalogue/items` endpoint that creates a new Item with fields: `name` (required), `default_price` (required), `description` (optional), `is_gst_exempt` (optional, default false), `category` (optional free-text), `is_active` (optional, default true).
3. THE Items_API SHALL expose a `PUT /api/v1/catalogue/items/{id}` endpoint that updates an existing Item, applying only the provided fields.
4. THE Items_API SHALL expose a `DELETE /api/v1/catalogue/items/{id}` endpoint that soft-deletes an Item by setting `is_active` to false.
5. WHEN the `search` query parameter is provided on the list endpoint, THE Items_API SHALL filter Items whose `name` contains the search term (case-insensitive).
6. WHEN a request is made to the legacy `GET /api/v1/catalogue/services` endpoint, THE Items_API SHALL continue to serve the request by proxying to the Items list endpoint for backward compatibility.
7. WHEN a request is made to the legacy `POST /api/v1/catalogue/services` endpoint, THE Items_API SHALL continue to serve the request by proxying to the Items create endpoint for backward compatibility.
8. IF a create or update request provides a `default_price` that is not a valid non-negative decimal, THEN THE Items_API SHALL return a 400 status code with a descriptive error message.
9. IF an update or delete request references an Item ID that does not belong to the authenticated Organisation, THEN THE Items_API SHALL return a 404 status code.

### Requirement 3: Build Dedicated Items Management Page

**User Story:** As an organisation admin, I want a dedicated Items management page at `/items` so that I can view, create, edit, and deactivate items in a Zoho-style table interface.

#### Acceptance Criteria

1. THE Items_Page SHALL be accessible at the `/items` route and display a table of all Items for the Organisation.
2. THE Items_Page SHALL display the following columns in the table: Name, Category, Price, GST Exempt, Status (Active/Inactive).
3. THE Items_Page SHALL provide a "New Item" button that opens a creation form with fields: Name, Description, Default Price, Category (free-text input), GST Exempt toggle, Active toggle.
4. WHEN a user clicks on a table row, THE Items_Page SHALL open an edit form pre-populated with the Item's current values.
5. THE Items_Page SHALL provide a search input that filters the table by Item name in real time.
6. THE Items_Page SHALL support toggling an Item's active status directly from the table row.
7. WHEN an Item is successfully created or updated, THE Items_Page SHALL display a success notification and refresh the table data.
8. IF the Items_API returns an error during create or update, THEN THE Items_Page SHALL display the error message to the user.
9. THE Items_Page SHALL paginate results when the total number of Items exceeds the page size.

### Requirement 4: Update Sidebar Navigation

**User Story:** As a user, I want to see "Items" in the sidebar navigation so that I can access the Items management page.

#### Acceptance Criteria

1. THE sidebar navigation SHALL display an "Items" entry at the `/items` route, module-gated by the `catalogue` module.
2. THE sidebar navigation SHALL retain the existing "Catalogue" entry at `/catalogue` for Parts and Labour Rates management.

### Requirement 5: Update BookingForm to Use Items Terminology

**User Story:** As a user creating a booking, I want the service field labelled "Item" and the inline creation form to use a free-text category input instead of a hardcoded dropdown, so that the booking form is industry-agnostic.

#### Acceptance Criteria

1. THE BookingForm SHALL label the service typeahead field as "Item" instead of "Service Type".
2. WHEN the user triggers inline Item creation in the BookingForm, THE BookingForm SHALL display a form with fields: Name, Default Price, and Category as a free-text input.
3. THE BookingForm inline creation form SHALL NOT display a hardcoded category dropdown with values Service, Repair, Warrant, or Diagnostic.
4. WHEN the user searches for an Item in the BookingForm typeahead, THE BookingForm SHALL call `GET /api/v1/catalogue/items` with `active_only=true` and filter results by the search query.
5. WHEN the user creates an Item inline in the BookingForm, THE BookingForm SHALL call `POST /api/v1/catalogue/items` with the provided name, price, and category values.

### Requirement 6: Update QuoteCreate and InvoiceCreate to Use Items API

**User Story:** As a user creating a quote or invoice, I want line items sourced from the universal Items catalogue, so that quotes and invoices use the same item data as bookings.

#### Acceptance Criteria

1. THE QuoteCreate component SHALL fetch catalogue items from `GET /api/v1/catalogue/items` instead of `GET /api/v1/catalogue/services`.
2. THE InvoiceCreate component SHALL fetch catalogue items from `GET /api/v1/catalogue/items` instead of `GET /api/v1/catalogue/services`.
3. THE `CatalogueItem` interface used by QuoteCreate and InvoiceCreate SHALL include the fields: `id`, `name`, `description`, `default_price`, `gst_applicable`, `category` (optional string), `sku` (optional string).

### Requirement 7: Update Backend Model and Schema Definitions

**User Story:** As a developer, I want the SQLAlchemy model and Pydantic schemas updated to reflect the Items terminology and free-text category, so that the backend code is consistent with the new data model.

#### Acceptance Criteria

1. THE SQLAlchemy model SHALL be named `ItemsCatalogue` and map to the `items_catalogue` table.
2. THE `category` field in the SQLAlchemy model SHALL be defined as `String(100)` with `nullable=True` and no CHECK constraint.
3. THE Pydantic create request schema SHALL accept `category` as an optional string field with a maximum length of 100 characters.
4. THE Pydantic update request schema SHALL accept `category` as an optional string field with a maximum length of 100 characters.
5. THE Pydantic response schema SHALL include `category` as an optional string field.
6. FOR ALL valid Item objects, serialising to a response dict and then constructing a Pydantic response model SHALL produce an equivalent representation (round-trip property).
