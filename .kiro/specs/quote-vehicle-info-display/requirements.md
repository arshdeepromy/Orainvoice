# Requirements Document

## Introduction

This feature adds odometer reading and WOF/COF expiry display to the issued quote across all rendering surfaces (frontend preview, PDF via WeasyPrint, and public share link). Currently, the quote shows vehicle registration and make/model/year but omits the odometer reading and WOF/COF expiry date that are available from CarJam. The data should be captured at quote creation time (from the CarJam lookup already performed during vehicle selection) and stored on the quote record so it renders consistently without requiring additional API calls.

## Glossary

- **Quote_Renderer**: The system responsible for rendering quote vehicle information across all surfaces (frontend preview in QuoteDetail, PDF via WeasyPrint, and public HTML share link)
- **Quote_Creation_Form**: The frontend form used by org users to create or edit a quote (QuoteCreate page)
- **Vehicle_Info_Section**: The section on a rendered quote that displays vehicle-related data (rego, make/model/year, odometer, WOF/COF expiry)
- **CarJam_Lookup**: The existing CarJam API integration that returns vehicle data including odometer reading, WOF expiry, and COF expiry when a registration plate is searched
- **Rendering_Surface**: Any output format where the quote is displayed — includes the frontend QuoteDetail preview, the PDF generated via WeasyPrint, and the public HTML share link

## Requirements

### Requirement 1: Store Odometer on Quote Record

**User Story:** As an org user, I want the vehicle odometer reading to be saved on the quote when I create it, so that the quote displays the odometer at the time of quoting.

#### Acceptance Criteria

1. WHEN a quote is created with a vehicle that has an odometer reading from CarJam_Lookup, THE Quote_Creation_Form SHALL store the odometer value on the quote record
2. WHEN a quote is updated and the vehicle changes, THE Quote_Creation_Form SHALL update the stored odometer to reflect the new vehicle's CarJam data
3. THE Quote_Creation_Form SHALL allow the org user to manually override the odometer value before saving the quote
4. WHEN no odometer data is available from CarJam_Lookup, THE Quote_Creation_Form SHALL allow the org user to manually enter an odometer value

### Requirement 2: Store WOF/COF Expiry on Quote Record

**User Story:** As an org user, I want the WOF or COF expiry date to be saved on the quote when I create it, so that the customer can see the current warrant status on the quote.

#### Acceptance Criteria

1. WHEN a quote is created with a vehicle that has a WOF expiry date from CarJam_Lookup, THE Quote_Creation_Form SHALL store the WOF expiry date on the quote record
2. WHEN a quote is created with a vehicle that has a COF expiry date from CarJam_Lookup, THE Quote_Creation_Form SHALL store the COF expiry date on the quote record
3. WHEN a quote is updated and the vehicle changes, THE Quote_Creation_Form SHALL update the stored WOF/COF expiry to reflect the new vehicle's CarJam data
4. THE Quote_Creation_Form SHALL store the inspection type (WOF or COF) alongside the expiry date so the renderer can label the field correctly

### Requirement 3: Display Odometer on Quote Vehicle Info Section

**User Story:** As a customer receiving a quote, I want to see the vehicle's current odometer reading on the quote, so that I can verify the correct vehicle and mileage is referenced.

#### Acceptance Criteria

1. WHEN a quote has a stored odometer value greater than zero, THE Quote_Renderer SHALL display the odometer reading in the Vehicle_Info_Section with the label "ODOMETER" and the value formatted as a comma-separated number followed by "km"
2. WHEN a quote has no odometer value or the value is zero, THE Quote_Renderer SHALL omit the odometer field from the Vehicle_Info_Section
3. THE Quote_Renderer SHALL display the odometer consistently across all Rendering_Surfaces (frontend preview, PDF, public share link)

### Requirement 4: Display WOF/COF Expiry on Quote Vehicle Info Section

**User Story:** As a customer receiving a quote, I want to see the WOF or COF expiry date on the quote, so that I know the current warrant status of my vehicle.

#### Acceptance Criteria

1. WHEN a quote has a stored WOF expiry date, THE Quote_Renderer SHALL display the expiry date in the Vehicle_Info_Section with the label "WOF EXPIRY"
2. WHEN a quote has a stored COF expiry date, THE Quote_Renderer SHALL display the expiry date in the Vehicle_Info_Section with the label "COF EXPIRY"
3. WHEN a quote has no WOF or COF expiry date stored, THE Quote_Renderer SHALL omit the expiry field from the Vehicle_Info_Section
4. THE Quote_Renderer SHALL format the expiry date in the NZ date format (DD Mon YYYY)
5. THE Quote_Renderer SHALL display the WOF/COF expiry consistently across all Rendering_Surfaces (frontend preview, PDF, public share link)

### Requirement 5: Vehicle Info Display Order

**User Story:** As an org user, I want vehicle information displayed in a consistent, logical order on quotes, so that customers see the most important vehicle identifiers first.

#### Acceptance Criteria

1. THE Quote_Renderer SHALL display vehicle information in the following order: Registration, Vehicle (make/model/year), Odometer, WOF/COF Expiry
2. THE Quote_Renderer SHALL apply this display order consistently across all Rendering_Surfaces
3. WHEN a vehicle field has no value, THE Quote_Renderer SHALL omit that field from the display without leaving a blank space or row

### Requirement 6: Additional Vehicles Display Parity

**User Story:** As an org user, I want additional vehicles on the quote to also show odometer and WOF/COF expiry, so that multi-vehicle quotes have complete vehicle information.

#### Acceptance Criteria

1. WHEN a quote has additional vehicles with odometer values, THE Quote_Renderer SHALL display the odometer for each additional vehicle following the same format as the primary vehicle
2. WHEN a quote has additional vehicles with WOF or COF expiry dates, THE Quote_Renderer SHALL display the expiry for each additional vehicle following the same format as the primary vehicle
3. THE Quote_Renderer SHALL apply the same display order (Rego, Vehicle, Odometer, WOF/COF Expiry) to additional vehicles

### Requirement 7: Database Schema Extension

**User Story:** As a system operator, I want the quote table to have dedicated columns for odometer and WOF/COF expiry, so that the data is stored reliably and queryable.

#### Acceptance Criteria

1. THE database schema SHALL include a `vehicle_odometer` integer column on the quotes table that is nullable and defaults to null
2. THE database schema SHALL include a `vehicle_wof_expiry` date column on the quotes table that is nullable and defaults to null
3. THE database schema SHALL include a `vehicle_cof_expiry` date column on the quotes table that is nullable and defaults to null
4. THE database migration SHALL be backwards-compatible, adding columns without affecting existing quote records
5. WHEN an existing quote has no odometer or expiry data, THE Quote_Renderer SHALL gracefully omit those fields (matching current behaviour)

### Requirement 8: Vehicles Module Gating

**User Story:** As a platform operator, I want vehicle info display on quotes to respect the vehicles module gating, so that organisations without the vehicles module do not see vehicle-related fields.

#### Acceptance Criteria

1. WHEN the vehicles module is disabled for an organisation, THE Quote_Creation_Form SHALL not store vehicle odometer or WOF/COF expiry data on the quote
2. WHEN the vehicles module is disabled for an organisation, THE Quote_Renderer SHALL not display odometer or WOF/COF expiry fields even if legacy data exists on the quote record
3. WHEN the vehicles module is enabled for an organisation, THE Quote_Renderer SHALL display all available vehicle fields following the defined display order
