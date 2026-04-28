# Requirements Document

## Introduction

This feature introduces a **Service Type Catalogue** for plumbing, drainage, and gas trade organisations. Service Types are descriptive categories of work (e.g., "Fixture Replacement", "Drain Clearing", "Gas Compliance Check") that can be configured with additional info fields. They carry **no pricing** — they exist purely to classify the type of work being performed on a job card.

Currently, the Items page and the Catalogue page both display the same `items_catalogue` records — Items shows them as items, and the Catalogue's "Services" tab shows them as services. This duplication is confusing and must be resolved. The Catalogue page will stop showing items as services, and a new "Service Types" tab will be added to the Items page, gated to the `plumbing-gas` trade family.

When a service type is used on a job card, the worker fills in the additional info fields defined for that service type (e.g., selecting which fixtures need replacement).

### Architecture Decisions

**Why a new table instead of `items_catalogue` metadata JSONB:** The steering doc (`trade-specific-catalogue-inventory.md`) recommends using the `metadata` JSONB column on `catalogue_products` for trade-specific fields. However, Service Types are fundamentally different from catalogue items — they have no pricing, no stock, and carry configurable child field definitions. Extending `items_catalogue` with a "no price" mode would pollute the shared model. A dedicated `service_types` table is cleaner and avoids breaking the existing catalogue reference chain (booking → job card → invoice).

**Service Types do NOT flow to invoices:** Service Types are metadata on the job card that describe the type of work. They are not line items and do not propagate through the catalogue reference chain (`items_catalogue` → `job_card_items` → `line_items`). Job card line items (parts, labour, services with pricing) continue to use `catalogue_item_id` as before. The Service Type is a separate classification field on the job card itself.

**Not a separate module:** Service Types are part of the existing catalogue/items infrastructure, not a new toggleable module. They do not need a `module_registry` entry or setup question. They are gated by trade family (`plumbing-gas`), not by module enablement — consistent with how automotive parts/fluids are gated by `automotive-transport` trade family without being a separate module.

**Terminology:** The "Service Types" label in the UI should use `TerminologyContext` so that future trades can rename it (e.g., "Work Categories" for construction). The default label is "Service Types" for `plumbing-gas`.

## Glossary

- **Service_Type**: A named, non-priced category of work specific to the `plumbing-gas` trade family. Each Service_Type has a name, optional description, and zero or more configurable Additional_Info_Fields.
- **Additional_Info_Field**: A configurable field definition attached to a Service_Type. Each field has a label, a field type (text, select, multi-select, number), and optional configuration (e.g., predefined options for select fields). These fields are filled in by workers when the Service_Type is used on a job card.
- **Items_Page**: The frontend page at `frontend/src/pages/items/ItemsPage.tsx` that currently has two tabs: Items and Labour Rates.
- **Catalogue_Page**: The frontend page at `frontend/src/pages/catalogue/CataloguePage.tsx` that currently has tabs: Services, Parts, and Fluids/Oils.
- **Service_Catalogue_Component**: The `ServiceCatalogue` component rendered on the Catalogue_Page's "Services" tab, which currently displays `items_catalogue` records — the source of the duplication.
- **Job_Card**: A work order record (`job_cards` table) that tracks work to be performed. Job cards contain line items (`job_card_items`) and will now also reference a Service_Type.
- **Trade_Family**: The business type classification for an organisation. This feature targets the `plumbing-gas` trade family.
- **Org_Admin**: An organisation administrator who can create, edit, and manage Service Types.
- **Worker**: A staff member (any org role) who fills in Additional_Info_Field values when a Service_Type is assigned to a job card.

## Requirements

### Requirement 1: Service Type Data Model

**User Story:** As an Org_Admin, I want to create Service Types with configurable additional info fields, so that I can define the types of plumbing work my business performs.

#### Acceptance Criteria

1. THE Service_Type model SHALL store a unique identifier (UUID), organisation ID, name (max 255 characters), optional description (max 2000 characters), active/inactive status, and timestamps (created_at, updated_at).
2. THE Service_Type model SHALL NOT store any pricing fields (no default_price, no unit_price, no hourly_rate).
3. THE Additional_Info_Field model SHALL store a unique identifier (UUID), parent Service_Type ID, field label (max 255 characters), field type (one of: text, select, multi_select, number), display order (integer), required flag (boolean), and optional configuration stored as JSONB (e.g., predefined options for select/multi_select fields).
4. WHEN a Service_Type is created, THE system SHALL scope the Service_Type to the creating organisation using the organisation ID.
5. THE Service_Type model SHALL enforce that the name is unique within the same organisation (no two active Service Types with the same name per org).

### Requirement 2: Service Type CRUD API

**User Story:** As an Org_Admin, I want to create, view, edit, and deactivate Service Types through the API, so that I can manage my plumbing service catalogue.

#### Acceptance Criteria

1. WHEN an Org_Admin sends a POST request with a valid name and optional additional info field definitions, THE API SHALL create a new Service_Type and return the created record with a 201 status code.
2. WHEN an Org_Admin sends a GET request, THE API SHALL return a list of Service Types scoped to the requesting organisation, with pagination support (limit/offset) and optional active_only filtering.
3. WHEN an Org_Admin sends a GET request for a specific Service_Type ID, THE API SHALL return the Service_Type with all associated Additional_Info_Fields.
4. WHEN an Org_Admin sends a PUT request with updated fields, THE API SHALL update the specified Service_Type and return the updated record.
5. WHEN an Org_Admin sends a PUT request to update Additional_Info_Fields on a Service_Type, THE API SHALL replace the existing field definitions with the provided set (full replacement, not partial merge).
6. WHEN an Org_Admin sends a DELETE request for a Service_Type that is not referenced by any job card, THE API SHALL permanently delete the Service_Type and its Additional_Info_Fields.
7. IF a Service_Type is referenced by one or more job cards, THEN THE API SHALL return a 409 status code with a message advising the Org_Admin to deactivate the Service_Type instead of deleting.
8. WHEN an unauthenticated or unauthorised user sends a request, THE API SHALL return a 401 or 403 status code.

### Requirement 3: Service Types Tab on Items Page

**User Story:** As an Org_Admin of a plumbing business, I want to see a "Service Types" tab on the Items page, so that I can manage my service type catalogue alongside items and labour rates.

#### Acceptance Criteria

1. WHILE the organisation's trade family is `plumbing-gas`, THE Items_Page SHALL display a third tab labelled "Service Types" after the existing "Items" and "Labour Rates" tabs.
2. WHILE the organisation's trade family is NOT `plumbing-gas`, THE Items_Page SHALL NOT display the "Service Types" tab.
3. WHEN the "Service Types" tab is selected, THE Items_Page SHALL display a list of all Service Types for the organisation in a table with columns: Name, Description, Additional Fields count, Status, and Actions.
4. WHEN the Org_Admin clicks "+ New Service Type", THE Items_Page SHALL open a modal form to create a new Service_Type with fields for name, description, and a dynamic section to add/remove Additional_Info_Fields.
5. WHEN the Org_Admin clicks "Edit" on a Service_Type row, THE Items_Page SHALL open a modal form pre-populated with the Service_Type's current data including its Additional_Info_Fields.
6. WHEN the Org_Admin toggles the active/inactive status of a Service_Type, THE Items_Page SHALL send an update request and refresh the list.

### Requirement 4: Additional Info Field Configuration

**User Story:** As an Org_Admin, I want to configure additional info fields on each Service Type, so that workers are prompted for the right information when performing that type of work.

#### Acceptance Criteria

1. WHEN creating or editing a Service_Type, THE modal form SHALL allow the Org_Admin to add one or more Additional_Info_Fields, each with a label, field type (text, select, multi_select, number), required flag, and display order.
2. WHEN the field type is "select" or "multi_select", THE modal form SHALL display an options editor allowing the Org_Admin to define the list of selectable values.
3. WHEN the Org_Admin reorders Additional_Info_Fields using drag handles or up/down controls, THE modal form SHALL update the display_order values accordingly.
4. WHEN the Org_Admin removes an Additional_Info_Field from the form, THE system SHALL remove the field definition upon saving (full replacement strategy).
5. IF the Org_Admin attempts to save a Service_Type with an Additional_Info_Field that has an empty label, THEN THE modal form SHALL display a validation error and prevent submission.

### Requirement 5: Remove Items Duplication from Catalogue Page

**User Story:** As a user, I want the Catalogue page to stop showing items as services, so that I am not confused by seeing the same records in two places.

#### Acceptance Criteria

1. THE Catalogue_Page SHALL NOT render the Service_Catalogue_Component (the "Services" tab that currently shows `items_catalogue` records).
2. WHILE the organisation's trade family is `plumbing-gas`, THE Catalogue_Page SHALL display only trade-relevant tabs (removing the duplicated Services tab).
3. WHILE the organisation's trade family is `automotive-transport`, THE Catalogue_Page SHALL continue to display the Parts and Fluids/Oils tabs as before.
4. WHEN the Services tab is removed from the Catalogue_Page, THE Items_Page "Items" tab SHALL remain the single source of truth for `items_catalogue` records.

### Requirement 6: Job Card Integration with Service Types

**User Story:** As a Worker, I want to select a Service Type when creating or editing a job card, so that the job card accurately describes the type of plumbing work being performed.

#### Acceptance Criteria

1. WHILE the organisation's trade family is `plumbing-gas`, THE job card create/edit form SHALL display a "Service Type" selector that lists active Service Types for the organisation.
2. WHEN a Worker selects a Service_Type on a job card, THE form SHALL dynamically render the Additional_Info_Fields defined for that Service_Type, allowing the Worker to fill in the required information.
3. WHEN a Worker submits a job card with a selected Service_Type, THE system SHALL store the Service_Type reference and the filled-in Additional_Info_Field values on the job card.
4. WHEN a job card with a Service_Type is viewed, THE job card detail page SHALL display the Service_Type name and the filled-in Additional_Info_Field values.
5. THE job card's Service_Type selection SHALL be optional — a Worker may create a job card without selecting a Service_Type.
6. IF a previously selected Service_Type is deactivated, THEN THE job card detail page SHALL still display the Service_Type name and its filled-in values (historical data is preserved).
7. THE Service_Type reference on a job card SHALL NOT propagate to invoices when a job card is converted to an invoice. Service Types classify the work; they are not priced line items. Invoice line items continue to use `catalogue_item_id` from `items_catalogue` as before.

### Requirement 7: Service Type Field Value Storage

**User Story:** As a system, I want to store the additional info field values filled in on job cards, so that the data is preserved and queryable.

#### Acceptance Criteria

1. WHEN a Worker fills in Additional_Info_Field values on a job card, THE system SHALL store each field value as a separate record linking the job card, the Additional_Info_Field definition, and the entered value.
2. THE field value storage SHALL support text values (for text and number field types) and array values (for multi_select field types).
3. WHEN a Service_Type's Additional_Info_Field definitions are updated after job cards have already been created with that Service_Type, THE system SHALL preserve the existing filled-in values on those job cards (field values are immutable snapshots).
4. THE API SHALL return the filled-in Additional_Info_Field values when retrieving a job card that has a Service_Type assigned.

### Requirement 8: Terminology Support

**User Story:** As a platform, I want the "Service Types" label to be configurable via TerminologyContext, so that future trades can rename it to match their industry language.

#### Acceptance Criteria

1. THE frontend SHALL use `TerminologyContext` to resolve the display label for the "Service Types" tab and related UI elements, with a default of "Service Types" for the `plumbing-gas` trade family.
2. WHEN a future trade family overrides the terminology for "service_types", THE Items_Page tab label and all related UI text SHALL reflect the override (e.g., "Work Categories" for construction).
3. THE backend API endpoint paths and field names SHALL use `service-types` consistently (terminology overrides are frontend-only display concerns).
