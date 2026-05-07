# Requirements Document

## Introduction

This feature enhances the existing Kiosk check-in flow with a vehicle registration lookup step. When an organisation has the "vehicles" module enabled, customers checking in at the kiosk will be prompted to enter their vehicle registration number. The system performs a cascading lookup (org vehicles → global vehicles → CarJam API) to retrieve vehicle details, displays the results to the customer, allows optional kilometer entry, supports adding multiple vehicles, and links all vehicles to the customer record upon check-in completion.

## Glossary

- **Kiosk_System**: The self-service tablet check-in interface used by walk-in customers
- **Vehicle_Lookup_Service**: The backend service that performs cascading vehicle registration lookups (org DB → global DB → CarJam API)
- **Module_Gate**: The mechanism that checks whether a specific module (e.g. "vehicles") is enabled for the current organisation
- **Registration_Screen**: The new kiosk screen where customers enter their vehicle registration number
- **Vehicle_Summary_Screen**: The screen displaying looked-up vehicle details and kilometer entry field
- **Customer_Details_Screen**: The existing screen where customers enter their personal details (name, phone, email)
- **CarJam_API**: External NZ vehicle data provider used for registration lookups when no cached data exists
- **Global_Vehicle_DB**: The shared `global_vehicles` table containing cached vehicle data from CarJam lookups
- **Org_Vehicle_DB**: The organisation-scoped `org_vehicles` table containing manually-entered vehicle records
- **Customer_Vehicle_Link**: The `customer_vehicles` association record connecting a vehicle to a customer within an organisation

## Requirements

### Requirement 1: Module-Gated Vehicle Step

**User Story:** As a kiosk customer, I want the vehicle registration step to only appear when the organisation supports vehicle tracking, so that I am not presented with irrelevant steps.

#### Acceptance Criteria

1. WHILE the "vehicles" module is enabled for the organisation, THE Kiosk_System SHALL display the Registration_Screen after the customer taps "Check In" on the welcome screen
2. WHILE the "vehicles" module is disabled for the organisation, THE Kiosk_System SHALL navigate directly from the welcome screen to the Customer_Details_Screen, bypassing the Registration_Screen entirely
3. THE Module_Gate SHALL evaluate the organisation's enabled modules using the existing ModuleContext on the frontend

### Requirement 2: Vehicle Registration Entry

**User Story:** As a kiosk customer, I want to enter my vehicle registration number on a dedicated screen, so that the system can look up my vehicle details.

#### Acceptance Criteria

1. THE Registration_Screen SHALL display a text input field for the vehicle registration number with a minimum tap target of 48×48 CSS pixels and a font size of at least 18px
2. THE Registration_Screen SHALL display a "Confirm" button that initiates the vehicle lookup
3. THE Registration_Screen SHALL display a "Skip" button that navigates the customer directly to the Customer_Details_Screen without performing a vehicle lookup
4. WHEN the customer enters a registration number, THE Registration_Screen SHALL strip whitespace and convert the input to uppercase before submission
5. WHEN the customer taps "Confirm" with an empty registration field, THE Registration_Screen SHALL display a validation message indicating that a registration number is required
6. THE Registration_Screen SHALL display a "Back" button that returns the customer to the welcome screen

### Requirement 3: Cascading Vehicle Lookup

**User Story:** As a kiosk customer, I want the system to automatically find my vehicle details from its registration number, so that I do not have to enter them manually.

#### Acceptance Criteria

1. WHEN the customer confirms a registration number, THE Vehicle_Lookup_Service SHALL first search the Org_Vehicle_DB for a matching registration within the current organisation
2. WHEN no match is found in the Org_Vehicle_DB, THE Vehicle_Lookup_Service SHALL search the Global_Vehicle_DB for a matching registration
3. WHEN no match is found in the Global_Vehicle_DB, THE Vehicle_Lookup_Service SHALL query the CarJam_API for the registration number
4. WHEN the CarJam_API returns vehicle data, THE Vehicle_Lookup_Service SHALL store the result in the Global_Vehicle_DB for future cache hits
5. IF the CarJam_API returns no result and no cached data exists, THEN THE Kiosk_System SHALL display a message indicating the vehicle was not found and allow the customer to proceed without vehicle data or re-enter the registration
6. WHILE the vehicle lookup is in progress, THE Registration_Screen SHALL display a loading indicator and disable the "Confirm" button to prevent duplicate submissions

### Requirement 4: Vehicle Summary Display

**User Story:** As a kiosk customer, I want to see my vehicle details after lookup, so that I can confirm the correct vehicle was found.

#### Acceptance Criteria

1. WHEN a vehicle lookup succeeds, THE Vehicle_Summary_Screen SHALL display the vehicle type (body_type field)
2. WHEN a vehicle lookup succeeds, THE Vehicle_Summary_Screen SHALL display the vehicle make and model
3. WHEN a vehicle lookup succeeds, THE Vehicle_Summary_Screen SHALL display the current WOF/COF expiry date
4. WHEN a vehicle lookup succeeds, THE Vehicle_Summary_Screen SHALL display the registration expiry date
5. WHEN a vehicle lookup succeeds, THE Vehicle_Summary_Screen SHALL display the last recorded kilometers
6. THE Vehicle_Summary_Screen SHALL display an optional numeric input field labelled "Current Kilometers" for the customer to enter their current odometer reading
7. THE Vehicle_Summary_Screen SHALL display a "Confirm" button that accepts the vehicle and proceeds to the next step
8. THE Vehicle_Summary_Screen SHALL display a "Back" button that returns the customer to the Registration_Screen to re-enter or change the registration

### Requirement 5: Multi-Vehicle Support

**User Story:** As a kiosk customer, I want to add multiple vehicles during a single check-in session, so that all my vehicles are linked to my account.

#### Acceptance Criteria

1. WHEN the customer confirms a vehicle on the Vehicle_Summary_Screen, THE Kiosk_System SHALL display an "Add Another Vehicle" button alongside a "Continue" button
2. WHEN the customer taps "Add Another Vehicle", THE Kiosk_System SHALL navigate back to the Registration_Screen for a new registration entry
3. THE Kiosk_System SHALL maintain a list of all confirmed vehicles during the check-in session
4. THE Vehicle_Summary_Screen SHALL display a count of previously added vehicles (e.g. "2 vehicles added")
5. WHEN the customer taps "Continue" after confirming vehicles, THE Kiosk_System SHALL navigate to the Customer_Details_Screen

### Requirement 6: Customer Creation with Vehicle Linking

**User Story:** As a kiosk customer, I want my vehicles to be automatically linked to my customer record after check-in, so that the workshop has my vehicle information on file.

#### Acceptance Criteria

1. WHEN the customer submits the Customer_Details_Screen, THE Kiosk_System SHALL create the customer record and then link each confirmed vehicle to the customer
2. THE Kiosk_System SHALL link each vehicle to the customer by creating a Customer_Vehicle_Link record with the organisation ID, customer ID, and global vehicle ID
3. IF the customer entered a current kilometer reading for a vehicle, THEN THE Kiosk_System SHALL record an odometer reading with source "kiosk" for that vehicle
4. WHEN a vehicle is already linked to the customer within the organisation, THE Kiosk_System SHALL skip creating a duplicate link (idempotent linking)
5. IF the customer creation or vehicle linking fails, THEN THE Kiosk_System SHALL display an error message and allow the customer to retry the submission

### Requirement 7: Kiosk Backend Endpoint Enhancement

**User Story:** As a developer, I want a kiosk-specific vehicle lookup endpoint, so that the kiosk can perform registration lookups without requiring org_admin or salesperson roles.

#### Acceptance Criteria

1. THE Kiosk_System SHALL expose a vehicle lookup endpoint accessible with the "kiosk" role that performs the same cascading lookup logic as the existing vehicle lookup endpoint
2. THE Kiosk_System SHALL expose a check-in endpoint that accepts a list of vehicle entries (each with a global_vehicle_id and optional odometer reading) alongside the customer details
3. WHEN the check-in endpoint receives vehicle entries, THE Kiosk_System SHALL link each vehicle to the created or matched customer and record any provided odometer readings
4. THE Kiosk_System SHALL enforce the existing kiosk rate limit (30 requests per minute) on the vehicle lookup endpoint

### Requirement 8: Existing Customer Details Screen Preservation

**User Story:** As a kiosk customer, I want the customer details form to work exactly as it does today, so that the vehicle enhancement does not disrupt the existing check-in experience.

#### Acceptance Criteria

1. THE Customer_Details_Screen SHALL retain all existing form fields (first name, last name, phone, email, and any other current fields) without modification
2. THE Customer_Details_Screen SHALL retain all existing validation rules and submit behaviour
3. THE Kiosk_System SHALL only add the vehicle registration step as a gated preceding step; the Customer_Details_Screen itself SHALL remain functionally identical for organisations without the vehicles module enabled
4. THE Customer_Details_Screen SHALL continue to display the same layout, styling, and touch-target sizes as the current implementation

### Requirement 9: Existing Customer Auto-Fill

**User Story:** As a returning kiosk customer, I want the system to recognise me by my phone number or email and auto-fill my details, so that I do not have to re-enter information the workshop already has.

#### Acceptance Criteria

1. WHEN the customer enters a phone number or email address on the Customer_Details_Screen, THE Kiosk_System SHALL perform a debounced lookup (after 500ms of no typing) against the organisation's customer database
2. WHEN a matching customer record is found, THE Kiosk_System SHALL display an auto-fill suggestion banner (e.g. "We found your details — tap to auto-fill")
3. WHEN the customer taps the auto-fill suggestion, THE Kiosk_System SHALL populate all available fields (first name, last name, phone, email) from the matched customer record
4. AFTER auto-fill, THE Kiosk_System SHALL allow the customer to review and edit any pre-filled fields before submitting
5. WHEN the customer submits with auto-filled data from an existing customer, THE Kiosk_System SHALL update the existing customer record (if any fields changed) rather than creating a duplicate
6. WHEN the customer submits with auto-filled data, THE Kiosk_System SHALL link the confirmed vehicles to the existing customer record
7. THE auto-fill lookup SHALL match on exact phone number OR exact email address (case-insensitive for email)
8. WHEN multiple matching customers are found (e.g. same phone on two records), THE Kiosk_System SHALL display a list for the customer to select the correct match

### Requirement 10: Session State Preservation

**User Story:** As a kiosk customer, I want my entered vehicle data to be preserved if I navigate back and forth between screens, so that I do not lose my progress.

#### Acceptance Criteria

1. WHILE the customer navigates between the Registration_Screen, Vehicle_Summary_Screen, and Customer_Details_Screen, THE Kiosk_System SHALL preserve all previously confirmed vehicle data in component state
2. WHEN the customer navigates back from the Customer_Details_Screen to add more vehicles, THE Kiosk_System SHALL retain the existing vehicle list and customer form data
3. WHEN the check-in flow completes (success screen) or the customer returns to the welcome screen, THE Kiosk_System SHALL clear all session state including vehicle data
