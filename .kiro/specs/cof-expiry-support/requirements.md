# Requirements Document

## Introduction

Add Certificate of Fitness (COF) expiry support alongside the existing Warrant of Fitness (WOF) system. In New Zealand, vehicles are subject to either WOF (light vehicles under 3,500 kg) or COF (heavy vehicles, buses, taxis, rental vehicles). The CarJam API returns separate fields for each inspection type, but the system currently only maps WOF data — COF data is silently discarded. This feature stores, displays, and sends notifications for COF expiry using the same patterns as WOF.

## Glossary

- **CarJam_Client**: The integration client that fetches vehicle data from the CarJam API by NZ registration plate
- **Global_Vehicle_DB**: The `global_vehicles` table storing vehicle data shared across all organisations
- **Org_Vehicle**: The `org_vehicles` table storing organisation-specific vehicle records linked to a global vehicle
- **Inspection_Type**: A classification field indicating whether a vehicle requires "wof" (Warrant of Fitness) or "cof" (Certificate of Fitness)
- **COF**: Certificate of Fitness — required for heavy vehicles (over 3,500 kg), buses, taxis, and vehicles used for hire/reward in New Zealand
- **WOF**: Warrant of Fitness — required for light passenger vehicles (cars, vans, motorcycles under 3,500 kg) in New Zealand
- **Notification_Service**: The backend service responsible for sending expiry reminder notifications via email and SMS
- **Dashboard_Service**: The backend service providing the upcoming expirations widget on the organisation dashboard
- **Vehicle_Module**: The `vehicles` module gate in the `org_modules` table that controls access to vehicle features

## Requirements

### Requirement 1: CarJam COF Data Parsing

**User Story:** As a system operator, I want the CarJam integration to parse COF expiry data from API responses, so that COF vehicle inspection dates are captured instead of being discarded.

#### Acceptance Criteria

1. WHEN the CarJam API returns a response containing `expiry_date_of_last_successful_cof`, THE CarJam_Client SHALL parse the value into a `cof_expiry` date field on the CarjamVehicleData container
2. WHEN the CarJam API returns a response containing `subject_to_cof` with value "Y", THE CarJam_Client SHALL set the `inspection_type` field to "cof"
3. WHEN the CarJam API returns a response containing `subject_to_wof` with value "Y", THE CarJam_Client SHALL set the `inspection_type` field to "wof"
4. WHEN the CarJam API returns a response where both `subject_to_cof` and `subject_to_wof` are absent or "N", THE CarJam_Client SHALL set the `inspection_type` field to null
5. WHEN the CarJam API returns a response containing `expiry_date_of_last_successful_cof` with an unparseable value, THE CarJam_Client SHALL set `cof_expiry` to null and log a warning

### Requirement 2: Database Storage of COF Data

**User Story:** As a system operator, I want COF expiry and inspection type stored in the database, so that the data persists for display and notification purposes.

#### Acceptance Criteria

1. THE Global_Vehicle_DB SHALL include a `cof_expiry` column of type DATE that is nullable
2. THE Global_Vehicle_DB SHALL include an `inspection_type` column of type VARCHAR(3) that is nullable, accepting values "wof", "cof", or null
3. THE Org_Vehicle SHALL include a `cof_expiry` column of type DATE that is nullable
4. THE Org_Vehicle SHALL include an `inspection_type` column of type VARCHAR(3) that is nullable, accepting values "wof", "cof", or null
5. WHEN a vehicle is looked up via CarJam and the response contains COF data, THE Vehicle_Service SHALL store the `cof_expiry` and `inspection_type` values in the Global_Vehicle_DB record
6. WHEN a vehicle is refreshed from CarJam, THE Vehicle_Service SHALL update the `cof_expiry` and `inspection_type` fields on the existing Global_Vehicle_DB record

### Requirement 3: Backend Schema Exposure

**User Story:** As a frontend developer, I want COF expiry and inspection type included in API responses, so that the frontend can display the correct inspection information.

#### Acceptance Criteria

1. THE Vehicle_Service SHALL include `cof_expiry` and `inspection_type` fields in the vehicle lookup response schema
2. THE Vehicle_Service SHALL include `cof_expiry` and `inspection_type` fields in the vehicle detail response schema
3. THE Vehicle_Service SHALL include `cof_expiry` and `inspection_type` fields in the vehicle search result schema
4. THE Kiosk_Service SHALL include `cof_expiry` and `inspection_type` fields in the kiosk vehicle lookup response schema
5. THE Portal_Service SHALL include `cof_expiry` and `inspection_type` fields in the portal vehicle item schema
6. WHEN a manual vehicle is created, THE Vehicle_Service SHALL accept optional `cof_expiry` and `inspection_type` fields in the creation request schema

### Requirement 4: Invoice COF Expiry Update

**User Story:** As a workshop operator, I want to update a vehicle's COF expiry date when creating an invoice, so that the system reflects the new inspection date after servicing a COF vehicle.

#### Acceptance Criteria

1. THE Invoice_Service SHALL accept an optional `vehicle_cof_expiry_date` field in the invoice creation request
2. WHEN an invoice is created with a `vehicle_cof_expiry_date` value, THE Invoice_Service SHALL update the `cof_expiry` field on the associated Global_Vehicle_DB record
3. WHEN an invoice is created with a `vehicle_cof_expiry_date` value, THE Invoice_Service SHALL update the `cof_expiry` field on the associated Org_Vehicle record

### Requirement 5: COF Expiry Notifications

**User Story:** As a workshop owner, I want customers with COF vehicles to receive expiry reminder notifications, so that they are prompted to book their COF inspection before it lapses.

#### Acceptance Criteria

1. THE Notification_Service SHALL include "cof_expiry_reminder" as a valid notification template type
2. WHEN a vehicle's `cof_expiry` date matches the configured reminder lead time, THE Notification_Service SHALL generate a COF expiry reminder notification for the linked customer
3. THE Notification_Service SHALL use the same deduplication logic for COF reminders as used for WOF reminders, keyed by template type, org, vehicle, and expiry date
4. THE Notification_Service SHALL support both email and SMS channels for COF expiry reminders
5. THE Notification_Service SHALL include vehicle registration, make, model, and expiry date in the COF reminder template variables
6. WHILE the `vehicles` module is not enabled for an organisation, THE Notification_Service SHALL skip COF expiry reminder processing for that organisation

### Requirement 6: Dashboard COF Expiry Widget

**User Story:** As a workshop owner, I want the dashboard upcoming expirations widget to include COF expiries, so that I can see all upcoming vehicle inspections in one place.

#### Acceptance Criteria

1. THE Dashboard_Service SHALL include vehicles with upcoming `cof_expiry` dates in the expirations widget alongside WOF expiries
2. THE Dashboard_Service SHALL label each expiration entry with the correct inspection type ("WOF" or "COF")
3. WHEN a vehicle has both `wof_expiry` and `cof_expiry` values (data anomaly), THE Dashboard_Service SHALL display the expiry matching the vehicle's `inspection_type` field

### Requirement 7: Frontend Dynamic Inspection Labels

**User Story:** As a user viewing vehicle information, I want the interface to display "WOF Expiry" or "COF Expiry" based on the vehicle's inspection type, so that the label accurately reflects the vehicle's regulatory requirement.

#### Acceptance Criteria

1. WHEN a vehicle has `inspection_type` equal to "cof", THE Frontend SHALL display the label "COF Expiry" instead of "WOF Expiry" on the vehicle profile page
2. WHEN a vehicle has `inspection_type` equal to "cof", THE Frontend SHALL display the label "COF Expiry" in the vehicle list column header and table cells
3. WHEN a vehicle has `inspection_type` equal to "cof", THE Frontend SHALL display the label "COF Expiry" on the kiosk vehicle summary screen
4. WHEN a vehicle has `inspection_type` equal to "cof", THE Frontend SHALL display the label "COF Expiry" on the invoice creation form vehicle section
5. WHEN a vehicle has `inspection_type` equal to "cof", THE Frontend SHALL display the label "COF Expiry" on the invoice detail and invoice list vehicle card
6. WHEN a vehicle has `inspection_type` equal to "cof", THE Frontend SHALL display the label "COF Expiry" on the customer portal vehicle history
7. WHEN a vehicle has `inspection_type` equal to "cof", THE Frontend SHALL display the label "COF Expiry" in the vehicle live search result summary
8. WHEN a vehicle has `inspection_type` that is null or "wof", THE Frontend SHALL display the label "WOF Expiry" as the default

### Requirement 8: Frontend COF Expiry Value Display

**User Story:** As a user viewing vehicle information, I want the correct expiry date displayed based on inspection type, so that I see the relevant inspection deadline for each vehicle.

#### Acceptance Criteria

1. WHEN a vehicle has `inspection_type` equal to "cof", THE Frontend SHALL display the `cof_expiry` date value in all expiry badge and date display locations
2. WHEN a vehicle has `inspection_type` equal to "wof" or null, THE Frontend SHALL display the `wof_expiry` date value in all expiry badge and date display locations
3. THE Frontend SHALL use optional chaining and nullish coalescing when accessing `cof_expiry` and `inspection_type` fields from API responses

### Requirement 9: Customer Notification Preferences for COF

**User Story:** As a workshop owner, I want to configure COF expiry reminders separately from WOF reminders in customer notification preferences, so that I can control which reminder types are sent.

#### Acceptance Criteria

1. THE Frontend SHALL display a COF expiry reminder toggle in the customer notification preferences section alongside the existing WOF reminder toggle
2. THE Notification_Service SHALL include "cof_expiry_reminder" in the "Vehicle Reminders" notification category
3. WHEN a customer has COF expiry reminders disabled, THE Notification_Service SHALL skip sending COF expiry reminder notifications to that customer

### Requirement 10: Backward Compatibility

**User Story:** As a system operator, I want existing WOF-only vehicles to continue working unchanged after the COF feature is deployed, so that no data or functionality is lost.

#### Acceptance Criteria

1. THE database migration SHALL add new columns as nullable with no default value, preserving all existing records unchanged
2. WHEN a vehicle has `inspection_type` equal to null, THE Frontend SHALL treat the vehicle as a WOF vehicle for display purposes
3. WHEN a vehicle has `cof_expiry` equal to null, THE Notification_Service SHALL skip COF reminder processing for that vehicle
4. THE Vehicle_Service SHALL continue to store and return `wof_expiry` data unchanged regardless of whether COF support is active

### Requirement 11: Manual Vehicle Entry COF Support

**User Story:** As a workshop operator manually entering a vehicle, I want to specify whether the vehicle requires WOF or COF and enter the corresponding expiry date, so that COF vehicles can be tracked without a CarJam lookup.

#### Acceptance Criteria

1. THE Frontend manual vehicle creation form SHALL include an inspection type selector allowing the user to choose "WOF" or "COF"
2. WHEN the user selects "COF" as the inspection type, THE Frontend SHALL display a "COF Expiry" date input instead of "WOF Expiry"
3. WHEN the user selects "WOF" as the inspection type (default), THE Frontend SHALL display the existing "WOF Expiry" date input
4. THE Vehicle_Service manual creation endpoint SHALL accept `inspection_type` and `cof_expiry` fields and store them on the created vehicle record

### Requirement 12: Bulk Import COF Support

**User Story:** As a workshop operator importing vehicles in bulk via JSON, I want the import preview and processing to support COF expiry data, so that bulk-imported COF vehicles have their inspection dates captured.

#### Acceptance Criteria

1. THE JSON bulk import preview table SHALL display a "COF Expiry" column alongside the existing "WOF Expiry" column when vehicle data contains `cof_expiry` values
2. THE JSON bulk import processing SHALL store `cof_expiry` and `inspection_type` values from the import data into the vehicle records
