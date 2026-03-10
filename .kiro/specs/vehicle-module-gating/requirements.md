# Requirements Document

## Introduction

OraInvoice is a multi-industry invoicing platform where vehicle-related features (global vehicle database, CarJam lookups, vehicle search, odometer tracking, vehicle info on invoices/PDFs) are currently available to all organisations with no gating. This feature registers a `vehicles` module in the existing module system and gates all vehicle/CarJam functionality behind it, so that only automotive/mechanic shop organisations that have the module enabled can access vehicle features. Organisations without the module enabled see no vehicle UI, receive no vehicle data in API responses, and get 403 errors if they attempt to call vehicle endpoints directly.

## Glossary

- **Module_Registry**: The `module_registry` database table that catalogues all available platform modules with their slug, display name, category, core status, and dependencies.
- **Org_Modules**: The `org_modules` database table that tracks which modules are enabled for each organisation.
- **ModuleService**: The backend service (`app/core/modules.py`) that checks module enablement per organisation via `is_enabled(org_id, module_slug)`, with Redis caching.
- **ModuleGate**: The frontend React component (`ModuleGate.tsx`) that conditionally renders children based on whether a module slug is enabled for the current organisation.
- **ModuleContext**: The frontend React context (`ModuleContext.tsx`) that fetches and exposes module enablement state, providing the `isEnabled(slug)` hook.
- **Vehicle_Router**: The FastAPI router (`app/modules/vehicles/router.py`) containing all vehicle-related API endpoints (lookup, search, manual entry, linking, odometer, profile).
- **Invoice_Service**: The backend service (`app/modules/invoices/service.py`) responsible for creating and managing invoices, including vehicle field storage and customer-vehicle auto-linking.
- **Customer_Service**: The backend service (`app/modules/customers/service.py`) responsible for customer search, including optional `linked_vehicles` data.
- **VehicleLiveSearch**: The frontend component (`VehicleLiveSearch.tsx`) that provides live vehicle search by registration number with CarJam lookup fallback.
- **CORE_MODULES**: The set of module slugs (`{"invoicing", "customers", "notifications"}`) that are always enabled and cannot be disabled. The `vehicles` module is not a core module.

## Requirements

### Requirement 1: Register Vehicles Module in Module Registry

**User Story:** As a platform administrator, I want the `vehicles` module registered in the module registry, so that organisations can enable or disable vehicle features through the standard module management system.

#### Acceptance Criteria

1. WHEN the Alembic migration runs, THE Module_Registry SHALL contain a row with slug `vehicles`, display_name `Vehicles`, category `automotive`, is_core `false`, dependencies `[]`, and status `available`.
2. THE migration SHALL use `INSERT ... ON CONFLICT DO NOTHING` for idempotency, so that re-running the migration does not create duplicate entries.
3. THE `vehicles` slug SHALL NOT be added to the CORE_MODULES set in ModuleService, so that the module remains optional and can be disabled per organisation.

### Requirement 2: Gate Vehicle Router Endpoints

**User Story:** As a platform developer, I want all vehicle API endpoints to check module enablement before processing, so that organisations without the vehicles module cannot access vehicle functionality.

#### Acceptance Criteria

1. WHEN a request is received on any Vehicle_Router endpoint, THE Vehicle_Router SHALL check whether the `vehicles` module is enabled for the requesting organisation using ModuleService.
2. IF the `vehicles` module is not enabled for the requesting organisation, THEN THE Vehicle_Router SHALL return HTTP 403 with the message "Vehicles module is not enabled for this organisation".
3. WHEN the `vehicles` module is enabled for the requesting organisation, THE Vehicle_Router SHALL process the request normally.
4. THE module check SHALL apply to all Vehicle_Router endpoints: lookup, lookup-with-fallback, search, manual entry, link, refresh, vehicle profile, odometer recording, odometer history, and odometer update.

### Requirement 3: Gate Vehicle Fields in Invoice Creation

**User Story:** As a platform developer, I want invoice creation to skip vehicle-related processing when the vehicles module is disabled, so that non-automotive organisations create invoices without vehicle data.

#### Acceptance Criteria

1. WHEN the `vehicles` module is disabled for the organisation, THE Invoice_Service SHALL ignore the `vehicle_rego`, `vehicle_make`, `vehicle_model`, `vehicle_year`, `vehicle_odometer`, and `global_vehicle_id` parameters during invoice creation, storing `NULL` for each vehicle field on the invoice record.
2. WHEN the `vehicles` module is disabled for the organisation, THE Invoice_Service SHALL skip the customer-vehicle auto-linking step during invoice creation.
3. WHEN the `vehicles` module is disabled for the organisation, THE Invoice_Service SHALL skip the odometer recording step during invoice creation.
4. WHEN the `vehicles` module is enabled for the organisation, THE Invoice_Service SHALL process vehicle fields, customer-vehicle auto-linking, and odometer recording normally.

### Requirement 4: Gate Frontend Vehicle UI in Invoice Creation

**User Story:** As a user of a non-automotive organisation, I want the invoice creation form to not show vehicle search or vehicle fields, so that the interface is clean and relevant to my industry.

#### Acceptance Criteria

1. WHILE the `vehicles` module is disabled for the current organisation, THE InvoiceCreate page SHALL hide the entire vehicle search section including the VehicleLiveSearch component, selected vehicle cards, and odometer input fields.
2. WHILE the `vehicles` module is enabled for the current organisation, THE InvoiceCreate page SHALL display the vehicle search section with VehicleLiveSearch, selected vehicle cards, and odometer input fields.
3. WHILE the `vehicles` module is disabled, THE InvoiceCreate page SHALL not include vehicle fields (`vehicle_rego`, `vehicle_make`, `vehicle_model`, `vehicle_year`, `vehicle_odometer`, `global_vehicle_id`) in the API payload sent to the backend.

### Requirement 5: Gate Frontend Vehicle UI in Invoice List and Detail

**User Story:** As a user of a non-automotive organisation, I want invoice list and detail views to not show vehicle information, so that the interface is relevant to my industry.

#### Acceptance Criteria

1. WHILE the `vehicles` module is disabled for the current organisation, THE InvoiceList page SHALL hide the vehicle info card section from invoice entries.
2. WHILE the `vehicles` module is disabled for the current organisation, THE InvoiceDetail page SHALL hide the vehicle display section.
3. WHILE the `vehicles` module is enabled for the current organisation, THE InvoiceList and InvoiceDetail pages SHALL display vehicle information normally when vehicle data exists on the invoice.

### Requirement 6: Gate Customer Search Linked Vehicles

**User Story:** As a platform developer, I want customer search to exclude linked vehicle data when the vehicles module is disabled, so that vehicle information does not leak to non-automotive organisations.

#### Acceptance Criteria

1. WHEN the `vehicles` module is disabled for the requesting organisation, THE Customer_Service SHALL not query or return `linked_vehicles` data in customer search results, returning an empty array or omitting the field.
2. WHEN the `vehicles` module is enabled for the requesting organisation, THE Customer_Service SHALL return `linked_vehicles` data in customer search results when `include_vehicles` is `true`.

### Requirement 7: Ensure Invoice PDF Templates Handle Missing Vehicle Data

**User Story:** As a platform developer, I want invoice PDF templates to render cleanly when no vehicle data exists on an invoice, so that non-automotive organisations get professional PDFs without empty vehicle sections.

#### Acceptance Criteria

1. THE invoice PDF template (`invoice.html`) SHALL only render the vehicle info section when vehicle data (at minimum `vehicle_rego`) exists on the invoice record.
2. THE invoice share PDF template (`invoice_share.html`) SHALL only render the vehicle info section when vehicle data (at minimum `vehicle_rego`) exists on the invoice record.
3. WHEN the `vehicles` module is disabled and no vehicle data is stored on the invoice, THE PDF templates SHALL render without any vehicle section or empty placeholder.

### Requirement 8: Gate Frontend Vehicle API Calls

**User Story:** As a platform developer, I want the frontend to not make vehicle-related API calls when the vehicles module is disabled, so that unnecessary network requests are avoided and 403 errors are prevented.

#### Acceptance Criteria

1. WHILE the `vehicles` module is disabled for the current organisation, THE VehicleLiveSearch component SHALL not make API calls to `/vehicles/search` or `/vehicles/lookup-with-fallback`.
2. WHILE the `vehicles` module is disabled for the current organisation, THE InvoiceCreate page SHALL not make API calls to any vehicle endpoint.
3. WHILE the `vehicles` module is disabled for the current organisation, THE customer search component SHALL not request `include_vehicles=true` from the customer search API.
