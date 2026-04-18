# Requirements Document

## Introduction

This feature adds an "Invoice Template" configuration to the Organisation Settings page, allowing org admins to choose from at least 10 professionally designed PDF invoice templates. Each template has a unique visual identity (background colours, layout density, logo positioning) tailored for trade businesses (automotive, electrical, plumbing, construction). Admins can customise the colour scheme per template and preview the result before saving. The backend renders the selected template via WeasyPrint using Jinja2, and the selection is persisted in the existing `org.settings` JSONB field.

## Glossary

- **Template_Registry**: A Python module that defines the catalogue of available invoice PDF templates, including their metadata (name, description, thumbnail path, default colours, logo position, layout type) and maps each template ID to its corresponding Jinja2 HTML file.
- **Template_Selector_UI**: The React component rendered within the Organisation Settings "Invoice Template" tab that displays template cards, colour customisation controls, and a live preview panel.
- **Template_Renderer**: The section of `generate_invoice_pdf()` in `app/modules/invoices/service.py` that loads the correct Jinja2 template file based on the org's selected template ID and applies the configured colour overrides before passing the HTML to WeasyPrint.
- **Org_Settings_API**: The existing `PUT /org/settings` and `GET /org/settings` endpoints that read and write the `org.settings` JSONB field on the `organisations` table.
- **Template_Preview_Endpoint**: A new API endpoint that accepts a template ID and colour overrides, renders a sample invoice HTML, and returns a preview (HTML or image) to the frontend.
- **Colour_Override**: A JSON object stored in `org.settings` containing user-selected colour values (primary colour, accent colour, header background colour) that override the template's default palette.
- **Logo_Position**: A string enum value (`left`, `center`, `side`) indicating where the organisation logo is placed within the invoice header area.
- **Layout_Type**: A string enum value (`standard`, `compact`) indicating whether the template uses full-spacing or condensed line-item rows and reduced margins.
- **Template_Card**: A UI element in the Template_Selector_UI that displays a thumbnail, template name, and description for a single template option.
- **WeasyPrint**: The Python library used to convert Jinja2-rendered HTML into PDF bytes.

## Requirements

### Requirement 1: Template Catalogue Registration

**User Story:** As a developer, I want a central registry of all available invoice templates, so that the backend and frontend can enumerate templates consistently.

#### Acceptance Criteria

1. THE Template_Registry SHALL define at least 10 unique invoice templates, each identified by a stable string ID (e.g., `classic`, `modern-dark`, `compact-blue`).
2. FOR EACH template, THE Template_Registry SHALL store the following metadata: template ID, display name, description, thumbnail image path, default primary colour, default accent colour, default header background colour, Logo_Position value, and Layout_Type value.
3. THE Template_Registry SHALL include at least 3 templates with Layout_Type `compact` and at least 7 templates with Layout_Type `standard`.
4. THE Template_Registry SHALL include at least 2 templates with Logo_Position `left`, at least 2 with Logo_Position `center`, and at least 2 with Logo_Position `side`.
5. FOR EACH template ID in the Template_Registry, THE Template_Renderer SHALL have a corresponding Jinja2 HTML file in the `app/templates/pdf/` directory.

### Requirement 2: Template Visual Identity

**User Story:** As an org admin, I want each template to have a distinct visual design, so that I can choose one that matches my business brand.

#### Acceptance Criteria

1. EACH template Jinja2 file SHALL produce a visually distinct PDF with a unique combination of: header layout, background colour scheme, typography weight, line-item table styling, and footer arrangement.
2. THE Template_Renderer SHALL apply the template's default colour palette when no Colour_Override is configured for the organisation.
3. WHEN a Colour_Override is configured, THE Template_Renderer SHALL substitute the overridden colour values into the template's CSS, replacing the corresponding default colours.
4. EACH template SHALL render all required invoice fields: organisation name, organisation address, organisation contact details, organisation logo, GST number, customer name, customer address, customer contact details, invoice number, issue date, due date, payment terms, line items (description, quantity, rate, amount), subtotal, discount (when present), GST amount, total, balance due, payment status banner, payment history (when present), notes, payment terms text, and terms and conditions.
5. EACH template with Layout_Type `compact` SHALL use reduced vertical padding on line-item rows (no more than 6px top and bottom) and reduced page margins compared to `standard` templates.

### Requirement 3: Org Settings Persistence

**User Story:** As an org admin, I want my template selection and colour customisations to be saved, so that all future invoices use my chosen design.

#### Acceptance Criteria

1. THE Org_Settings_API SHALL accept and persist the following new fields in the `org.settings` JSONB column: `invoice_template_id` (string), `invoice_template_colours` (JSON object with keys `primary_colour`, `accent_colour`, `header_bg_colour`).
2. WHEN `invoice_template_id` is not set in `org.settings`, THE Template_Renderer SHALL fall back to the existing `invoice.html` template (current default behaviour).
3. WHEN the Org_Settings_API receives a `PUT` request with `invoice_template_id`, THE Org_Settings_API SHALL validate that the provided template ID exists in the Template_Registry before persisting.
4. IF the Org_Settings_API receives an `invoice_template_id` that does not exist in the Template_Registry, THEN THE Org_Settings_API SHALL return HTTP 422 with a descriptive error message.
5. THE Org_Settings_API SHALL return the `invoice_template_id` and `invoice_template_colours` fields in the `GET /org/settings` response.

### Requirement 4: Template Selection UI

**User Story:** As an org admin, I want to browse and select invoice templates from the settings page, so that I can pick the design I prefer.

#### Acceptance Criteria

1. THE Template_Selector_UI SHALL be rendered as a new "Invoice Template" tab within the Organisation Settings page at `frontend/src/pages/settings/OrgSettings.tsx`.
2. THE Template_Selector_UI SHALL display a grid of Template_Cards, one for each template in the Template_Registry.
3. EACH Template_Card SHALL display the template's thumbnail image, display name, description, Logo_Position label, and Layout_Type label.
4. WHEN the org admin clicks a Template_Card, THE Template_Selector_UI SHALL visually highlight the selected card with a distinct border colour.
5. THE Template_Selector_UI SHALL indicate the currently saved template with a "Current" badge on the corresponding Template_Card.
6. THE Template_Selector_UI SHALL provide filter controls to filter templates by Layout_Type (`All`, `Standard`, `Compact`) and by Logo_Position (`All`, `Left`, `Center`, `Side`).

### Requirement 5: Colour Customisation

**User Story:** As an org admin, I want to customise the colour scheme of my selected template, so that the invoice matches my brand colours.

#### Acceptance Criteria

1. WHEN a template is selected, THE Template_Selector_UI SHALL display colour picker inputs for: primary colour, accent colour, and header background colour.
2. THE Template_Selector_UI SHALL pre-populate the colour pickers with the selected template's default colours from the Template_Registry.
3. WHEN the org admin changes a colour value, THE Template_Selector_UI SHALL store the new value as a Colour_Override.
4. THE Template_Selector_UI SHALL provide a "Reset to Defaults" button that restores all colour pickers to the selected template's default values.
5. WHEN the org admin saves the template selection, THE Template_Selector_UI SHALL send both the `invoice_template_id` and the `invoice_template_colours` object to the Org_Settings_API via `PUT /org/settings`.

### Requirement 6: Template Preview

**User Story:** As an org admin, I want to preview how an invoice will look with my selected template and colours before saving, so that I can make an informed choice.

#### Acceptance Criteria

1. THE Template_Preview_Endpoint SHALL accept a template ID and optional Colour_Override values as query parameters or request body.
2. WHEN the Template_Preview_Endpoint is called, THE Template_Preview_Endpoint SHALL render a sample invoice using the specified template and colour overrides, and return the result as an HTML string.
3. THE Template_Selector_UI SHALL display a "Preview" button next to the selected template.
4. WHEN the org admin clicks the "Preview" button, THE Template_Selector_UI SHALL call the Template_Preview_Endpoint and render the returned HTML in an iframe or modal.
5. THE Template_Preview_Endpoint SHALL use realistic sample data (sample organisation name, sample customer, 3-5 sample line items, sample totals) so the preview accurately represents the final PDF layout.
6. IF the Template_Preview_Endpoint receives a template ID that does not exist in the Template_Registry, THEN THE Template_Preview_Endpoint SHALL return HTTP 404 with a descriptive error message.

### Requirement 7: PDF Generation Integration

**User Story:** As a system operator, I want the PDF generation function to use the org's selected template, so that downloaded and emailed invoices reflect the chosen design.

#### Acceptance Criteria

1. WHEN `generate_invoice_pdf()` is called, THE Template_Renderer SHALL read `invoice_template_id` from the organisation's `settings` JSONB field.
2. WHEN `invoice_template_id` is present and valid, THE Template_Renderer SHALL load the corresponding Jinja2 template file from `app/templates/pdf/` instead of the default `invoice.html`.
3. WHEN `invoice_template_colours` is present in `org.settings`, THE Template_Renderer SHALL pass the colour override values into the Jinja2 template context so that CSS colour variables are substituted.
4. WHEN `invoice_template_id` is present but does not match any file in the Template_Registry, THE Template_Renderer SHALL fall back to the default `invoice.html` template and log a warning.
5. THE Template_Renderer SHALL pass the same invoice data context (invoice, org, customer, currency_symbol, gst_percentage, payment_terms, terms_and_conditions, i18n labels) to all templates, ensuring every template receives identical data regardless of visual design.

### Requirement 8: Template Thumbnails

**User Story:** As an org admin, I want to see thumbnail previews of each template in the selection grid, so that I can quickly compare designs.

#### Acceptance Criteria

1. FOR EACH template in the Template_Registry, THE system SHALL provide a static thumbnail image (PNG or WebP format, minimum 400px wide, aspect ratio approximately 1:1.4 to match A4 proportions).
2. THE thumbnail images SHALL be stored in the `frontend/public/templates/` directory and referenced by the Template_Registry metadata.
3. EACH thumbnail SHALL accurately represent the template's header layout, colour scheme, logo position, and line-item table styling.
4. THE Template_Selector_UI SHALL display the thumbnail images in the Template_Cards with lazy loading to avoid blocking page load.

### Requirement 9: Template Data Compatibility

**User Story:** As a developer, I want all templates to handle the full range of invoice data variations, so that no template breaks on edge cases.

#### Acceptance Criteria

1. EACH template SHALL render correctly when the invoice has zero line items, displaying a "No line items" placeholder row.
2. EACH template SHALL render correctly when optional fields are absent: vehicle information, discount, payment history, customer notes, payment terms text, and terms and conditions.
3. EACH template SHALL render correctly when the organisation has no logo configured, displaying only the organisation name in the header.
4. EACH template SHALL render payment status banners (Paid, Overdue, Voided, Refunded, Partially Refunded) in a style consistent with the template's colour scheme.
5. EACH template SHALL support page breaks for invoices with more than 15 line items, ensuring the line-item table header repeats on subsequent pages.
6. WHEN the invoice includes additional vehicles, EACH template SHALL render the additional vehicle information bars below the primary vehicle bar.

### Requirement 10: Backward Compatibility

**User Story:** As an existing user, I want my current invoices to look the same after this feature is deployed, so that the upgrade does not disrupt my business.

#### Acceptance Criteria

1. WHEN an organisation has no `invoice_template_id` in `org.settings`, THE Template_Renderer SHALL use the existing `invoice.html` template with no visual changes.
2. THE existing `invoice.html` template file SHALL remain unmodified by this feature.
3. THE Org_Settings_API SHALL continue to accept and process all existing `org.settings` fields without requiring `invoice_template_id` or `invoice_template_colours`.
4. WHEN an organisation upgrades and has not selected a template, THE Template_Selector_UI SHALL display the current default template as the active selection with a "Default" badge.
