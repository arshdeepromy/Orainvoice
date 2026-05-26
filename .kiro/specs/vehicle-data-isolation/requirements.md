# Requirements Document

## Introduction

OraInvoice currently stores all customer-driven vehicle state (odometer, service-due date, WOF expiry, COF expiry, inspection type) on the shared `global_vehicles` table. Because `global_vehicles` is a cross-organisation cache populated by CarJam, any update by Organisation A to one of these fields is immediately visible to Organisation B as soon as B looks up the same registration. This breaks tenant isolation: B sees A's odometer reading, A's last service date, and A's WOF state without ever having serviced that vehicle.

This feature makes operational vehicle state strictly per-organisation while preserving `global_vehicles` as a read-mostly CarJam spec cache. Each organisation gets its own copy of customer-driven fields the first time it writes to a given vehicle. The copy lives in the existing `org_vehicles` table; no new tables and no new columns are introduced. Writes from customer-facing flows (invoice creation/update, kiosk check-in, fleet portal odometer/service-due updates, customer-vehicle link creation) target the organisation's `org_vehicles` row. Reads fall back to `global_vehicles` when the organisation has not yet promoted the vehicle, so existing data and existing workflows continue to function unchanged.

The CarJam-owned spec fields (make, model, year, VIN, body_type, fuel_type, colour, num_seats, registration_expiry, plus the extended attribute set: chassis, engine_no, transmission, country_of_origin, number_of_owners, vehicle_type, power_kw, tare_weight, gross_vehicle_mass, date_first_registered_nz, plate_type, submodel, second_colour) remain on `global_vehicles` and continue to be written only by CarJam refresh and admin bulk import. After promotion, an organisation refreshes its CarJam-owned spec fields explicitly via a "Refresh from CarJam" action; spec drift between `global_vehicles` and a promoted `org_vehicles` row is acceptable until that action is invoked.

The B2B Fleet Portal reads vehicle data exclusively from `org_vehicles` once the fleet operator's organisation has been promoted, and triggers promotion automatically when a fleet operator imports or links a vehicle.

## Glossary

- **Global_Vehicles**: The cross-organisation `global_vehicles` table — a shared, read-mostly cache of CarJam vehicle data keyed by rego. Acts as a global lookup cache available to every organisation.
- **Org_Vehicles**: The organisation-scoped `org_vehicles` table — a per-organisation snapshot of vehicle data, isolated by `org_id` and protected by RLS. Already exists with full column parity to `global_vehicles` for both CarJam-owned spec fields and customer-driven fields.
- **Customer_Vehicles**: The `customer_vehicles` link table — connects a `customers` row to either a `global_vehicles` row (via `global_vehicle_id`) or an `org_vehicles` row (via `org_vehicle_id`), enforced by the existing `vehicle_link_check` either-or CHECK constraint.
- **Odometer_Readings**: The `odometer_readings` history table — stores time-series odometer readings keyed by `global_vehicle_id`. Untouched by this feature; all history rows continue to point at `global_vehicles`.
- **Customer_Driven_Fields**: The five fields whose values reflect what an organisation has done to or recorded about a vehicle in the course of servicing it: `odometer_last_recorded`, `service_due_date`, `wof_expiry`, `cof_expiry`, and `inspection_type`. These are operational state owned by the servicing organisation.
- **CarJam_Owned_Spec_Fields**: The set of vehicle attribute fields sourced from CarJam: `make`, `model`, `year`, `vin`, `body_type`, `fuel_type`, `colour`, `num_seats`, `registration_expiry`, `chassis`, `engine_no`, `transmission`, `country_of_origin`, `number_of_owners`, `vehicle_type`, `power_kw`, `tare_weight`, `gross_vehicle_mass`, `date_first_registered_nz`, `plate_type`, `submodel`, and `second_colour`. These remain on `global_vehicles` as the shared cache.
- **Vehicle_Service**: The vehicles module service layer (`app/modules/vehicles/service.py`) that owns vehicle linking, lookup, and odometer recording.
- **Invoice_Service**: The invoices module service layer (`app/modules/invoices/service.py`) that owns invoice creation and update.
- **Kiosk_Service**: The kiosk module service layer (`app/modules/kiosk/service.py`) that owns walk-in customer check-in and the multi-step vehicle check-in flow.
- **Fleet_Portal_Vehicle_Service**: The B2B Fleet Portal vehicle service layer (`app/modules/fleet_portal/services/vehicle_service.py`) that exposes vehicle reads, odometer recording, and service-due updates to fleet operators.
- **Promotion**: The act of creating an `org_vehicles` row for a given organisation, sourced from an existing `global_vehicles` row, the first time that organisation performs a write or link involving that vehicle. Once an organisation has promoted a vehicle, all subsequent customer-driven writes for that organisation target the `org_vehicles` row, and the existing `customer_vehicles` link is migrated from `global_vehicle_id` to `org_vehicle_id`.
- **Promoted**: An organisation is "promoted" for a given rego when an `org_vehicles` row exists for `(org_id, rego)`. Promotion status is per-organisation per-vehicle.
- **Promotion_Trigger_Site**: A code path that initiates a customer-driven write or a customer-vehicle link creation. Each trigger site SHALL invoke promotion when it operates on a `global_vehicles` row for the first time within its organisation.
- **Manual_Refresh**: An explicit user-initiated "Refresh from CarJam" action that copies the current `global_vehicles` CarJam_Owned_Spec_Fields into the organisation's `org_vehicles` row, replacing any locally cached spec values.
- **Read_Fallback**: The behaviour where, if an organisation has no `org_vehicles` row for a given rego, reads of customer-driven fields return the value from the corresponding `global_vehicles` row. This preserves continuity for organisations that have not yet been promoted.

## Requirements

### Requirement 1: Strict Isolation of Customer-Driven Fields

**User Story:** As an organisation owner, I want odometer readings, service-due dates, and WOF/COF expiry I record against a vehicle to remain private to my organisation, so that another workshop servicing the same vehicle never sees my customer's data.

#### Acceptance Criteria

1. THE Vehicle_Service SHALL NOT write any value to `global_vehicles.odometer_last_recorded`, `global_vehicles.service_due_date`, `global_vehicles.wof_expiry`, `global_vehicles.cof_expiry`, or `global_vehicles.inspection_type` from any customer-driven flow.
2. THE Invoice_Service SHALL NOT write any value to `global_vehicles.odometer_last_recorded`, `global_vehicles.service_due_date`, `global_vehicles.wof_expiry`, `global_vehicles.cof_expiry`, or `global_vehicles.inspection_type` during invoice creation or invoice update.
3. THE Kiosk_Service SHALL NOT write any value to `global_vehicles.odometer_last_recorded`, `global_vehicles.service_due_date`, `global_vehicles.wof_expiry`, `global_vehicles.cof_expiry`, or `global_vehicles.inspection_type` during walk-in check-in.
4. THE Fleet_Portal_Vehicle_Service SHALL NOT write any value to `global_vehicles.odometer_last_recorded`, `global_vehicles.service_due_date`, `global_vehicles.wof_expiry`, `global_vehicles.cof_expiry`, or `global_vehicles.inspection_type` from any portal endpoint.
5. WHEN any code path within the Vehicle_Service, Invoice_Service, Kiosk_Service, or Fleet_Portal_Vehicle_Service produces a value for a Customer_Driven_Field for a given organisation, THE producing service SHALL persist that value to that organisation's `org_vehicles` row for the matching rego.
6. THE existing `global_vehicles.odometer_last_recorded`, `global_vehicles.service_due_date`, `global_vehicles.wof_expiry`, `global_vehicles.cof_expiry`, and `global_vehicles.inspection_type` columns SHALL remain in the schema and SHALL retain their existing values; this feature SHALL NOT delete, null, or migrate any data already present in those columns.

### Requirement 2: Lazy Promotion on First Customer-Driven Write or Link

**User Story:** As an organisation, I want my private vehicle copy to be created automatically the first time I do anything with a vehicle, so that I do not have to manually import or migrate vehicles before using them.

#### Acceptance Criteria

1. WHEN a customer-driven flow within Organisation A operates on a `global_vehicles` row that has no corresponding `org_vehicles` row for Organisation A, THE producing service SHALL create an `org_vehicles` row for Organisation A by copying the current `global_vehicles` CarJam_Owned_Spec_Fields and the current `global_vehicles` Customer_Driven_Fields into the new row, and SHALL set `org_vehicles.is_manual_entry = false`.
2. WHEN Promotion creates an `org_vehicles` row, THE producing service SHALL apply the customer-driven write that triggered promotion to the new `org_vehicles` row before returning to the caller, so the triggering write is never lost.
3. WHEN Promotion is triggered by creation of a `customer_vehicles` link, THE producing service SHALL set `customer_vehicles.org_vehicle_id` to the newly created `org_vehicles.id` and SHALL set `customer_vehicles.global_vehicle_id` to NULL, so the either-or `vehicle_link_check` constraint holds.
4. WHEN Promotion is triggered by a customer-driven write while an existing `customer_vehicles` link for the same `(org_id, customer_id, global_vehicle_id)` is present, THE producing service SHALL update that link to point at the new `org_vehicles.id` (set `org_vehicle_id`, clear `global_vehicle_id`) within the same transaction.
5. WHILE an organisation already has an `org_vehicles` row for a given rego, THE producing service SHALL NOT create a second `org_vehicles` row for the same `(org_id, rego)` and SHALL apply customer-driven writes to the existing row.
6. IF Promotion fails for any reason, THEN THE producing service SHALL roll back the entire transaction, leave `global_vehicles` unchanged, and surface the failure as a 5xx response with no partial state persisted.

### Requirement 3: Promotion Trigger Sites

**User Story:** As a developer, I want every code path that touches customer-driven vehicle state to consistently promote the vehicle, so that no flow accidentally writes private data to the shared global cache.

#### Acceptance Criteria

1. WHEN `link_vehicle_to_customer` in the Vehicle_Service is invoked with a `global_vehicles` ID for an organisation that is not yet Promoted for that rego, THE Vehicle_Service SHALL Promote the vehicle and SHALL create the `customer_vehicles` link via `org_vehicle_id`.
2. WHEN `create_invoice` in the Invoice_Service receives an invoice payload whose resolved vehicle is a `global_vehicles` row and the organisation is not yet Promoted for that rego, THE Invoice_Service SHALL Promote the vehicle before applying any invoice-driven update of Customer_Driven_Fields.
3. WHEN `update_invoice` in the Invoice_Service receives an update payload that changes any Customer_Driven_Field and the resolved vehicle is a `global_vehicles` row and the organisation is not yet Promoted for that rego, THE Invoice_Service SHALL Promote the vehicle before applying the update.
4. WHEN the kiosk v2 check-in flow in the Kiosk_Service links a vehicle to a customer and the resolved vehicle is a `global_vehicles` row and the organisation is not yet Promoted for that rego, THE Kiosk_Service SHALL Promote the vehicle before creating the `customer_vehicles` link.
5. WHEN the Fleet_Portal_Vehicle_Service receives a record-odometer or service-due update request for a vehicle whose link still uses `global_vehicle_id`, THE Fleet_Portal_Vehicle_Service SHALL Promote the vehicle before applying the update.
6. WHEN the Fleet Portal admin endpoint, the bookings link-creation flow, or the customers link-creation flow creates a new `customer_vehicles` link for a `global_vehicles` ID and the organisation is not yet Promoted for that rego, THE invoking service SHALL Promote the vehicle and SHALL create the link via `org_vehicle_id`.
7. THE odometer history flow `record_odometer_reading` in the Vehicle_Service SHALL continue to insert rows into `odometer_readings` keyed by `global_vehicle_id` and SHALL NOT update `global_vehicles.odometer_last_recorded`; instead, after inserting the history row, THE Vehicle_Service SHALL update `org_vehicles.odometer_last_recorded` for the organisation that owns the link, Promoting the vehicle if necessary.

### Requirement 4: CarJam-Owned Spec Fields Remain on Global Vehicles

**User Story:** As a platform operator, I want CarJam vehicle attributes to remain a shared cache so that we do not waste CarJam credits looking up the same registration repeatedly across organisations.

#### Acceptance Criteria

1. THE CarJam refresh path in the Vehicle_Service SHALL continue to write CarJam_Owned_Spec_Fields to `global_vehicles` for any rego it refreshes.
2. THE admin bulk import path SHALL continue to write CarJam_Owned_Spec_Fields to `global_vehicles`.
3. THE Vehicle_Service, Invoice_Service, Kiosk_Service, and Fleet_Portal_Vehicle_Service SHALL NOT write CarJam_Owned_Spec_Fields to `global_vehicles` from any customer-driven flow other than CarJam refresh and admin bulk import.
4. WHEN Promotion copies CarJam_Owned_Spec_Fields into a new `org_vehicles` row, THE producing service SHALL copy the current values from `global_vehicles` at the moment of Promotion, and SHALL NOT subsequently auto-sync changes from `global_vehicles` to the `org_vehicles` row.

### Requirement 5: Manual Refresh from CarJam Post-Promotion

**User Story:** As an organisation user, I want to refresh a vehicle's CarJam attributes on demand after I have promoted it, so that I can update spec fields when I know they have changed without giving up my private operational state.

#### Acceptance Criteria

1. WHERE an organisation has an `org_vehicles` row for a rego, THE Vehicle_Service SHALL expose a "Refresh from CarJam" action that copies the current `global_vehicles` CarJam_Owned_Spec_Fields into the organisation's `org_vehicles` row for that rego.
2. WHEN Manual_Refresh is invoked and `global_vehicles` does not contain a row for the rego or the cached row is older than the CarJam cache TTL, THE Vehicle_Service SHALL trigger a CarJam lookup, persist the result to `global_vehicles`, and then copy CarJam_Owned_Spec_Fields into the organisation's `org_vehicles` row.
3. WHEN Manual_Refresh runs, THE Vehicle_Service SHALL NOT modify the organisation's `org_vehicles` Customer_Driven_Fields.
4. WHILE Manual_Refresh has not been invoked since Promotion, THE Vehicle_Service SHALL accept that an organisation's `org_vehicles` CarJam_Owned_Spec_Fields may differ from the current `global_vehicles` row for the same rego.

### Requirement 6: Read Fallback for Pre-Promotion Vehicles

**User Story:** As an organisation user, I want to keep using vehicles I linked before this change without being forced to re-import or refresh anything, so that the change is invisible to me until I write to a vehicle.

#### Acceptance Criteria

1. WHEN any read endpoint in the Vehicle_Service, Invoice_Service, Kiosk_Service, or Fleet_Portal_Vehicle_Service returns vehicle data for an organisation that is not yet Promoted for the requested rego, THE producing service SHALL return the Customer_Driven_Fields from `global_vehicles` as the fallback values.
2. WHEN the same read endpoint runs for an organisation that is Promoted for the requested rego, THE producing service SHALL return Customer_Driven_Fields exclusively from that organisation's `org_vehicles` row and SHALL NOT consult `global_vehicles` for those fields.
3. WHEN a read endpoint returns CarJam_Owned_Spec_Fields and the organisation is not yet Promoted, THE producing service SHALL return the values from `global_vehicles`.
4. WHEN a read endpoint returns CarJam_Owned_Spec_Fields and the organisation is Promoted, THE producing service SHALL return the values from that organisation's `org_vehicles` row.
5. THE existing `customer_vehicles` rows that point at `global_vehicle_id` SHALL continue to resolve correctly through Read_Fallback for reads, and SHALL be migrated to `org_vehicle_id` only on the next customer-driven write or link operation that triggers Promotion.

### Requirement 7: B2B Fleet Portal Reads From Org Vehicles

**User Story:** As a fleet operator using the B2B portal, I want to see only my organisation's view of my vehicles so that the portal shows the WOF and odometer state my workshop has on file, not whatever another workshop last recorded.

#### Acceptance Criteria

1. WHEN the Fleet_Portal_Vehicle_Service serves any vehicle list, vehicle detail, or fleet summary endpoint for a fleet operator linked to Workshop_Org W, THE Fleet_Portal_Vehicle_Service SHALL source Customer_Driven_Fields from W's `org_vehicles` rows when W is Promoted for the rego, and SHALL fall back to `global_vehicles` per Requirement 6 when W is not yet Promoted.
2. WHEN a fleet operator initiates a CarJam import for a new rego from the B2B portal, THE Fleet_Portal_Vehicle_Service SHALL ensure a `global_vehicles` row exists, SHALL Promote the rego for Workshop_Org W (creating an `org_vehicles` row), and SHALL create the `customer_vehicles` link via `org_vehicle_id`.
3. WHEN a fleet operator initiates a manual vehicle add (no CarJam) from the B2B portal, THE Fleet_Portal_Vehicle_Service SHALL create the vehicle directly as an `org_vehicles` row with `is_manual_entry = true` for Workshop_Org W and SHALL link it via `org_vehicle_id` (existing manual-entry behaviour, unchanged).
4. THE Fleet_Portal_Vehicle_Service SHALL NOT expose any endpoint that allows a fleet operator to write Customer_Driven_Fields onto `global_vehicles`.

### Requirement 8: Schema and Migration Constraints

**User Story:** As a platform operator, I want this change to ship as a behavioural fix only, with no new tables and no new columns, so that the rollout has zero migration risk and zero impact on the existing schema.

#### Acceptance Criteria

1. THE feature SHALL NOT introduce any new database tables.
2. THE feature SHALL NOT introduce any new columns on `global_vehicles`, `org_vehicles`, `customer_vehicles`, or `odometer_readings`.
3. THE feature SHALL NOT remove or rename any existing column on `global_vehicles`, `org_vehicles`, `customer_vehicles`, or `odometer_readings`.
4. THE feature SHALL NOT introduce any data migration that backfills `org_vehicles` rows for existing `customer_vehicles` links; promotion SHALL happen lazily on first write per Requirement 2.
5. THE feature SHALL NOT alter the `vehicle_link_check` CHECK constraint on `customer_vehicles`.
6. THE feature SHALL NOT alter the `odometer_readings.global_vehicle_id` foreign key or the existing `ck_odometer_readings_source` CHECK constraint.

### Requirement 9: API and UI Contract Stability

**User Story:** As an existing user of OraInvoice, I want all my screens, payloads, and PDFs to look and behave exactly the same after this change, so that the isolation fix is invisible to me.

#### Acceptance Criteria

1. THE feature SHALL NOT change the JSON schema of any existing API response, including invoice responses, customer responses, vehicle lookup responses, kiosk check-in responses, and fleet portal vehicle responses.
2. THE feature SHALL NOT change the JSON schema of any existing API request body.
3. THE feature SHALL NOT add, remove, or rename any existing API endpoint path or HTTP method.
4. THE feature SHALL NOT alter any frontend component prop signature, displayed field, or rendered visual layout.
5. THE feature SHALL NOT change the format or content of any rendered PDF (invoice, quote, job card, report).
6. WHILE the feature is deployed, THE existing invoices, quotes, job cards, bookings, and `customer_vehicles` links SHALL continue to load, render, edit, and save exactly as they do before deployment.

### Requirement 10: Backwards Compatibility for Existing Data

**User Story:** As an organisation that has been using the platform for months, I want the values currently sitting in `global_vehicles.odometer_last_recorded` and other Customer_Driven_Fields to keep showing up for me until my next service event, so that nothing appears to disappear after the upgrade.

#### Acceptance Criteria

1. THE feature SHALL preserve every existing value in `global_vehicles.odometer_last_recorded`, `global_vehicles.service_due_date`, `global_vehicles.wof_expiry`, `global_vehicles.cof_expiry`, and `global_vehicles.inspection_type`.
2. WHILE an organisation has not yet been Promoted for a given rego, THE producing services SHALL continue to read those preserved values via Read_Fallback per Requirement 6.
3. WHEN an organisation is Promoted for a given rego, THE producing service SHALL copy those preserved values into the new `org_vehicles` row at the moment of Promotion, so the organisation's view does not regress.
4. WHEN one organisation Promotes a rego, THE producing service SHALL NOT alter the `global_vehicles` row in any way; other organisations SHALL continue to see the unchanged `global_vehicles` values via their own Read_Fallback until each one is independently Promoted.

### Requirement 11: Odometer History Continues to Use Global Vehicle ID

**User Story:** As a developer, I want odometer history to remain queryable with its existing schema so that historical reports and the `odometer_readings` table do not need to be rewritten.

#### Acceptance Criteria

1. THE Vehicle_Service SHALL continue to insert `odometer_readings` rows with `global_vehicle_id` populated, regardless of whether the recording organisation is Promoted for the rego.
2. WHEN the recording organisation is not Promoted at the time of recording, THE Vehicle_Service SHALL Promote the vehicle and update `org_vehicles.odometer_last_recorded` for that organisation, while the `odometer_readings` row SHALL still reference `global_vehicle_id`.
3. WHEN the recording organisation is already Promoted at the time of recording, THE Vehicle_Service SHALL update `org_vehicles.odometer_last_recorded` for that organisation, and the `odometer_readings` row SHALL still reference `global_vehicle_id`.
4. THE existing odometer history queries SHALL continue to work without modification.

### Requirement 12: Multi-Org Independence

**User Story:** As a platform operator, I want two organisations operating on the same rego to have completely independent operational state, so that one organisation's writes never bleed into another organisation's view.

#### Acceptance Criteria

1. WHEN Organisation A and Organisation B both link the same rego at different times, THE producing services SHALL Promote each organisation independently and SHALL create one `org_vehicles` row per organisation.
2. WHEN Organisation A writes any Customer_Driven_Field for a rego, THE producing service SHALL update only `org_vehicles` for Organisation A, and SHALL NOT modify `org_vehicles` for any other organisation or `global_vehicles`.
3. WHEN Organisation B reads any Customer_Driven_Field for the same rego after Organisation A has written, THE producing service SHALL return Organisation B's own `org_vehicles` value when B is Promoted, or the unchanged `global_vehicles` Read_Fallback value when B is not yet Promoted.
4. THE feature SHALL preserve existing RLS policies on `org_vehicles` and `customer_vehicles`, so Organisation A SHALL NOT be able to read or write Organisation B's `org_vehicles` rows under any code path.

### Requirement 13: Idempotency and Concurrency

**User Story:** As a developer, I want concurrent writes from the same organisation against a not-yet-Promoted vehicle to converge on a single `org_vehicles` row, so that a race between two simultaneous invoices does not produce duplicate rows.

#### Acceptance Criteria

1. WHEN two concurrent customer-driven writes from the same organisation both attempt to Promote the same rego, THE producing services SHALL converge on exactly one `org_vehicles` row for that `(org_id, rego)` pair, with no duplicate rows.
2. IF a Promotion attempt detects that another transaction has already created an `org_vehicles` row for the same `(org_id, rego)`, THEN THE losing transaction SHALL apply its customer-driven write to the existing row rather than failing or retrying Promotion.
3. WHEN a customer-driven write is invoked twice in succession for the same vehicle and same organisation with the same payload, THE producing service SHALL produce the same end-state in `org_vehicles` regardless of whether the first invocation triggered Promotion.

### Requirement 14: Observability of Promotion Events

**User Story:** As a platform operator, I want a log entry every time a vehicle is Promoted, so that I can audit when each organisation first started writing private state for a given vehicle.

#### Acceptance Criteria

1. WHEN Promotion creates a new `org_vehicles` row, THE producing service SHALL emit an audit log entry with `action = "vehicle.promote"`, `entity_type = "org_vehicle"`, `entity_id = <new org_vehicles.id>`, and `after_value` containing `{ "rego": <rego>, "global_vehicle_id": <source global_vehicles.id>, "trigger_site": <name of the calling code path> }`.
2. WHEN Manual_Refresh updates an existing `org_vehicles` row, THE Vehicle_Service SHALL emit an audit log entry with `action = "vehicle.manual_refresh"`, `entity_type = "org_vehicle"`, and `entity_id = <org_vehicles.id>`.
3. THE audit log entries SHALL include `org_id` and `user_id` consistent with all other audit entries written by the producing services.

### Requirement 15: Test Coverage Constraints

**User Story:** As a developer, I want regression tests that prove isolation, lazy promotion, and read fallback all work, so that future changes cannot silently reintroduce the cross-organisation leak.

#### Acceptance Criteria

1. THE test suite SHALL include a regression test that asserts Organisation A writing a Customer_Driven_Field for a rego does not change `global_vehicles` or any other organisation's `org_vehicles` row for that rego.
2. THE test suite SHALL include a test for each Promotion_Trigger_Site (vehicle link, invoice create, invoice update, kiosk check-in, fleet portal odometer record, fleet portal service-due update, bookings link, customers link, fleet portal admin link, fleet portal CarJam import) asserting that the first invocation creates an `org_vehicles` row and migrates the link to `org_vehicle_id`.
3. THE test suite SHALL include a Read_Fallback test asserting that an organisation with no `org_vehicles` row for a rego sees the `global_vehicles` Customer_Driven_Field values via the standard read endpoints.
4. THE test suite SHALL include a concurrency test asserting that two simultaneous Promotions for the same `(org_id, rego)` produce exactly one `org_vehicles` row.
5. THE test suite SHALL include a test asserting that the existing `customer_vehicles` rows pointing at `global_vehicle_id` continue to load correctly through every read endpoint after this change is deployed.

## Non-Functional Requirements

### NFR-1: Workflow Compatibility

THE feature SHALL be implementable with the minimum code change necessary to satisfy Requirements 1–15. THE feature SHALL NOT alter any API contract, frontend payload, frontend component, or rendered PDF output. THE existing user flows for invoice creation, invoice update, kiosk check-in, fleet portal vehicle management, bookings link creation, and customer link creation SHALL continue to function exactly as they do today, with the only observable behaviour change being that Customer_Driven_Field updates persist privately per organisation rather than to the shared `global_vehicles` cache.

### NFR-2: Performance

THE Promotion path SHALL add at most one `SELECT` and one `INSERT` to a customer-driven write that triggers it (lookup of existing `org_vehicles` row, plus insert of new `org_vehicles` row). THE post-Promotion steady state SHALL add no additional database round-trips beyond the existing `_resolve_vehicle_type` lookup that the Invoice_Service already performs.

### NFR-3: Security and Tenant Isolation

THE feature SHALL preserve all existing RLS policies on `org_vehicles`, `customer_vehicles`, `odometer_readings`, and `global_vehicles`. THE feature SHALL NOT introduce any code path that lets one organisation read or modify another organisation's `org_vehicles` rows. Promotion SHALL execute under the existing organisation context (via `branch_context` / RLS).

### NFR-4: Rollback Safety

THE feature SHALL be deployable and revertable without database migration. Reverting the application code SHALL leave all existing `global_vehicles` and `org_vehicles` rows intact, and existing `customer_vehicles` links (whether using `global_vehicle_id` or `org_vehicle_id`) SHALL continue to resolve.
