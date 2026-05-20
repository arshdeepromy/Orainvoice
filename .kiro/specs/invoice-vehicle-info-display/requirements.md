# Requirements Document

## Introduction

This feature enhances how vehicle information is displayed on invoices across all rendering surfaces (preview, HTML share link, PDF via WeasyPrint, email, and custom invoice templates). The key improvements are: a defined display order for vehicle fields, conditional display of WOF/COF expiry and Service Due Date based on whether the user updated those fields during invoice creation, a form warning when updating service due date, and persistent storage of "updated during creation" flags on the invoice record.

## Glossary

- **Invoice_Creation_Form**: The frontend form used by org users to create or edit an invoice (InvoiceCreate page)
- **Invoice_Renderer**: The system responsible for rendering invoice vehicle information across all surfaces (preview panel, HTML share link, PDF, email, POS receipt, custom templates)
- **Vehicle_Info_Section**: The section on a rendered invoice that displays vehicle-related data (rego, make/model, odometer, WOF/COF expiry, service due date)
- **Field_Update_Detection**: The logic that determines whether a vehicle field (WOF/COF expiry, service due date) was changed by the user during this invoice creation session compared to the value already stored on the vehicle record
- **Vehicle_Update_Flags**: A set of boolean flags stored on the invoice record indicating which vehicle fields were updated during invoice creation
- **Service_Due_Odometer_Hint**: The small text displayed below the service due date showing "or due at {current_odometer + 10,000} km"
- **Rendering_Surface**: Any output format where the invoice is displayed — includes preview panel, HTML share link, PDF (WeasyPrint), email attachment, custom templates, and POS receipt sidebar

## Requirements

### Requirement 1: Vehicle Info Display Order

**User Story:** As an org user, I want vehicle information displayed in a consistent, logical order on invoices, so that customers see the most important vehicle identifiers first.

#### Acceptance Criteria

1. THE Invoice_Renderer SHALL display vehicle information in the following order: Registration, Vehicle (make/model/year), Odometer, WOF/COF Expiry (conditional), Service Due Date (conditional)
2. THE Invoice_Renderer SHALL apply this display order consistently across all Rendering_Surfaces (preview panel, HTML share link, PDF, email, POS receipt, custom templates)
3. WHEN a vehicle field has no value, THE Invoice_Renderer SHALL omit that field from the display without leaving a blank row

### Requirement 2: Conditional WOF/COF Expiry Display

**User Story:** As an org user, I want WOF/COF expiry to appear on the invoice only when I updated it during invoice creation, so that customers see the new expiry date only when a WOF/COF inspection was performed.

#### Acceptance Criteria

1. WHEN the org user updates the WOF expiry field during invoice creation to a value different from the vehicle record's existing WOF expiry, THE Invoice_Renderer SHALL display the WOF expiry date on the invoice
2. WHEN the org user does not change the WOF expiry field during invoice creation, AND the existing WOF expiry date is in the future (after the invoice issue date), THE Invoice_Renderer SHALL display the WOF expiry date on the invoice
3. WHEN the org user does not change the WOF expiry field during invoice creation, AND the existing WOF expiry date has passed (before or equal to the invoice issue date), THE Invoice_Renderer SHALL omit the WOF expiry from the invoice display
4. WHEN the org user updates the COF expiry field during invoice creation to a value different from the vehicle record's existing COF expiry, THE Invoice_Renderer SHALL display the COF expiry date on the invoice
5. WHEN the org user does not change the COF expiry field during invoice creation, AND the existing COF expiry date is in the future, THE Invoice_Renderer SHALL display the COF expiry date on the invoice
6. WHEN the org user does not change the COF expiry field during invoice creation, AND the existing COF expiry date has passed, THE Invoice_Renderer SHALL omit the COF expiry from the invoice display
7. THE Invoice_Renderer SHALL label the field as "WOF Expiry" or "COF Expiry" based on the vehicle's inspection type

### Requirement 3: Conditional Service Due Date Display

**User Story:** As an org user, I want the service due date to appear on the invoice only when I updated it during creation, and when shown it should replace the odometer reading with a combined service-due display, so that customers see their next service schedule clearly.

#### Acceptance Criteria

1. WHEN the org user updates the service due date field during invoice creation to a value different from the vehicle record's existing service due date, THE Invoice_Renderer SHALL display the service due date on the invoice in place of the odometer reading
2. WHEN the service due date is displayed, THE Invoice_Renderer SHALL show a secondary line below it in small text reading "or due at {current_odometer + 10,000} km"
3. WHEN the org user does not change the service due date field during invoice creation, THE Invoice_Renderer SHALL display the odometer reading and omit the service due date section
4. THE Invoice_Renderer SHALL use the odometer value recorded on the invoice (vehicle_odometer) for the "+10,000 km" calculation

### Requirement 4: Invoice Creation Form Warning

**User Story:** As an org user, I want to see a warning when I update the service due date field, so that I remember to also update the odometer reading for an accurate "due at X km" calculation.

#### Acceptance Criteria

1. WHEN the org user changes the service due date field value in the Invoice_Creation_Form, THE Invoice_Creation_Form SHALL display a warning message below the field reading "Ensure you have updated the odometer reading too"
2. WHILE the service due date field value matches the vehicle record's existing service due date, THE Invoice_Creation_Form SHALL not display the warning message
3. THE Invoice_Creation_Form SHALL display the warning in a visually distinct style (small text, amber/warning colour) that does not block form submission

### Requirement 5: Field Update Detection Logic

**User Story:** As a system operator, I want the system to accurately detect whether WOF/COF expiry or service due date were changed during invoice creation, so that the conditional display logic works correctly.

#### Acceptance Criteria

1. THE Field_Update_Detection SHALL compare the value entered by the user in the invoice form against the value already stored on the vehicle record at the time of invoice creation
2. WHEN the user-entered value differs from the vehicle record value, THE Field_Update_Detection SHALL mark that field as "updated"
3. WHEN the user-entered value is identical to the vehicle record value or is empty, THE Field_Update_Detection SHALL mark that field as "not updated"
4. THE Field_Update_Detection SHALL evaluate WOF expiry, COF expiry, and service due date independently

### Requirement 6: Vehicle Update Flags Storage

**User Story:** As a system operator, I want the invoice record to persistently store which vehicle fields were updated during creation, so that the conditional display logic works correctly when rendering the invoice at any future time.

#### Acceptance Criteria

1. THE Invoice_Creation_Form SHALL store Vehicle_Update_Flags on the invoice record indicating which vehicle fields (WOF expiry, COF expiry, service due date) were updated during creation
2. THE Vehicle_Update_Flags SHALL be stored as part of the invoice's persistent data (invoice_data_json) so they survive across server restarts and database queries
3. WHEN rendering an invoice, THE Invoice_Renderer SHALL read the Vehicle_Update_Flags from the stored invoice record to determine which conditional fields to display
4. THE Vehicle_Update_Flags SHALL also store the actual values that were set during creation (WOF expiry date, COF expiry date, service due date, odometer at creation) so the renderer has all data needed without querying the vehicle record

### Requirement 7: Consistent Rendering Across All Surfaces

**User Story:** As an org user, I want the vehicle info section to look identical regardless of how the customer views the invoice, so that there is no confusion between different viewing methods.

#### Acceptance Criteria

1. THE Invoice_Renderer SHALL produce identical vehicle information content on the preview panel (InvoiceList split-panel and InvoiceCreate preview)
2. THE Invoice_Renderer SHALL produce identical vehicle information content on the HTML share link (public invoice page)
3. THE Invoice_Renderer SHALL produce identical vehicle information content on the PDF generated via WeasyPrint
4. THE Invoice_Renderer SHALL produce identical vehicle information content in the email attachment
5. THE Invoice_Renderer SHALL produce identical vehicle information content across all custom invoice templates in the template registry
6. THE Invoice_Renderer SHALL produce equivalent vehicle information content on the POS receipt sidebar, adapted for the narrower receipt format
