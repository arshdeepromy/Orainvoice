# Requirements Document

## Introduction

Several organisation settings fields (Email Signature, Default Invoice Notes, Payment Terms Statement, Terms & Conditions) are stored and configurable in the Settings UI but are either completely unused or only partially connected to the invoice system. This feature adds enable/disable toggles for each setting and wires them into the appropriate output channels (email, PDF, web preview, web print, form pre-fill) so that users have full control over what appears on their invoices.

**Audit findings:** 9 of 12 selectable invoice PDF templates are missing `notes_customer` and `terms_and_conditions` rendering. The web preview (InvoiceDetail.tsx) does not show payment terms or T&C. The web print (browser print) also misses these because it prints the web preview. The "Use this in future" checkbox only saves T&C, not notes. The TenantContext does not expose `default_notes`. These gaps are all addressed below.

## Glossary

- **Settings_Page**: The frontend page at `frontend/src/pages/settings/OrgSettings.tsx` where organisation and branding settings are configured.
- **Invoice_Form**: The invoice creation/editing form at `frontend/src/pages/invoices/InvoiceCreate.tsx`.
- **Invoice_Preview**: The invoice web preview page at `frontend/src/pages/invoices/InvoiceDetail.tsx` (also used for browser print via `window.print()`).
- **PDF_Renderer**: The WeasyPrint-based PDF generation system using Jinja2 templates in `app/templates/pdf/`.
- **Email_Dispatcher**: The email sending function `send_email_task()` in `app/tasks/notifications.py`.
- **Org_Settings**: The JSONB column on the `organisations` table that stores all organisation-level configuration.
- **Settings_API**: The backend endpoints `GET /api/v1/org/settings` and `PUT /api/v1/org/settings` for reading and updating organisation settings.
- **Toggle**: A boolean enable/disable control that determines whether a setting's content is applied to invoices.
- **TenantContext**: The React context (`frontend/src/contexts/TenantContext.tsx`) that exposes org settings to all frontend components.
- **Template_Registry**: The 12 selectable invoice PDF templates defined in `app/modules/invoices/template_registry.py`.

## Existing Fields Reference (no new fields with overlapping names)

| Org Settings JSONB Key | Purpose | Currently Used |
|---|---|---|
| `default_notes` | Default customer-facing notes for new invoices | NOT used (dead) |
| `payment_terms_text` | Payment terms statement text | PDF only |
| `terms_and_conditions` | Rich HTML T&C content | PDF + form pre-fill (stripped) |
| `email_signature` | Email signature HTML | NOT used (dead) |
| `invoice_header_text` | Custom header text on PDF | PDF only |
| `invoice_footer_text` | Custom footer text on PDF | PDF only |

| Invoice Model Column | Purpose | Relationship to Org Settings |
|---|---|---|
| `notes_customer` | Per-invoice customer notes | Pre-filled from `default_notes` when enabled |
| `notes_internal` | Per-invoice internal notes | No org-level default |
| `terms_and_conditions` (in `invoice_data_json`) | Per-invoice T&C override | Falls back to org `terms_and_conditions` |

**No new fields are being created that overlap with existing ones.** We are adding 4 boolean toggle fields only: `email_signature_enabled`, `default_notes_enabled`, `payment_terms_enabled`, `terms_and_conditions_enabled`.

## Requirements

### Requirement 1: Enable/Disable Toggle Fields in Org Settings Schema

**User Story:** As an organisation admin, I want enable/disable toggles for each invoice-related setting, so that I can control which settings are applied to my invoices without deleting the content.

#### Acceptance Criteria

1. THE Settings_API SHALL expose the following boolean fields in the settings response: `email_signature_enabled`, `default_notes_enabled`, `payment_terms_enabled`, `terms_and_conditions_enabled`
2. THE Settings_API SHALL accept the following boolean fields in the settings update request: `email_signature_enabled`, `default_notes_enabled`, `payment_terms_enabled`, `terms_and_conditions_enabled`
3. WHEN `email_signature_enabled` is not present in Org_Settings, THE Settings_API SHALL default the value to `false`
4. WHEN `default_notes_enabled` is not present in Org_Settings, THE Settings_API SHALL default the value to `false`
5. WHEN `payment_terms_enabled` is not present in Org_Settings, THE Settings_API SHALL default the value to `true`
6. WHEN `terms_and_conditions_enabled` is not present in Org_Settings, THE Settings_API SHALL default the value to `true`
7. WHEN a toggle is set to `false`, THE Settings_API SHALL still store and return the associated text content unchanged
8. THE TenantContext SHALL expose `default_notes`, `default_notes_enabled`, `payment_terms_enabled`, and `terms_and_conditions_enabled` to all frontend components

### Requirement 2: Toggle UI Controls in Settings Page

**User Story:** As an organisation admin, I want to see toggle switches next to each invoice setting on the Settings page, so that I can easily enable or disable them.

#### Acceptance Criteria

1. THE Settings_Page SHALL display a toggle switch for Email Signature with label "Enable email signature on outgoing emails"
2. THE Settings_Page SHALL display a toggle switch for Default Invoice Notes with label "Pre-fill notes on new invoices"
3. THE Settings_Page SHALL display a toggle switch for Payment Terms Statement with label "Show payment terms on invoices"
4. THE Settings_Page SHALL display a toggle switch for Terms & Conditions with label "Show terms & conditions on invoices"
5. WHEN a toggle is disabled, THE Settings_Page SHALL visually dim the associated text input area to indicate the content is inactive
6. WHEN a toggle is changed, THE Settings_Page SHALL persist the new toggle value via the Settings_API on save

### Requirement 3: Email Signature Integration

**User Story:** As an organisation admin, I want my email signature appended to outgoing invoice and quote emails when enabled, so that my emails have consistent branding.

#### Acceptance Criteria

1. WHEN `email_signature_enabled` is `true` and `email_signature` content exists, THE Email_Dispatcher SHALL append the email signature HTML to the `html_body` before sending invoice emails
2. WHEN `email_signature_enabled` is `true` and `email_signature` content exists, THE Email_Dispatcher SHALL append the email signature HTML to the `html_body` before sending quote emails
3. WHEN `email_signature_enabled` is `false`, THE Email_Dispatcher SHALL send emails without appending the email signature regardless of whether content exists
4. THE Email_Dispatcher SHALL insert a horizontal rule (`<hr>`) separator between the email body and the appended signature
5. WHEN `email_signature` content is empty or null, THE Email_Dispatcher SHALL send emails without a signature regardless of the toggle state

### Requirement 4: Default Invoice Notes Pre-fill

**User Story:** As an organisation admin, I want the default notes to pre-fill the Customer Notes field when creating a new invoice, so that I do not have to type them manually each time.

#### Acceptance Criteria

1. WHEN `default_notes_enabled` is `true` and `default_notes` content exists, THE Invoice_Form SHALL pre-fill the Customer Notes field with the `default_notes` value when creating a new invoice
2. WHEN `default_notes_enabled` is `false`, THE Invoice_Form SHALL initialise the Customer Notes field as empty when creating a new invoice
3. WHEN editing an existing invoice, THE Invoice_Form SHALL use the invoice's stored `notes_customer` value regardless of the default notes setting
4. THE Invoice_Preview SHALL display customer notes when `notes_customer` is present on the invoice record regardless of the toggle state (notes are per-invoice once saved)
5. THE existing "Use this in future for all invoices" checkbox SHALL continue to save `terms_and_conditions` only — it SHALL NOT be affected by the `default_notes_enabled` toggle

### Requirement 5: Payment Terms Statement — All Render Targets

**User Story:** As an organisation admin, I want the payment terms statement to appear consistently in the invoice web preview, PDF, and print output when enabled.

#### Acceptance Criteria

1. WHEN `payment_terms_enabled` is `true` and `payment_terms_text` content exists, THE Invoice_Preview SHALL display the payment terms statement below the notes section
2. WHEN `payment_terms_enabled` is `false`, THE Invoice_Preview SHALL NOT display the payment terms statement
3. WHEN `payment_terms_enabled` is `true`, ALL 12 selectable PDF templates SHALL render the payment terms statement
4. WHEN `payment_terms_enabled` is `false`, ALL PDF templates SHALL NOT render the payment terms statement
5. WHEN the user prints from the web preview (browser print), THE printed output SHALL include the payment terms statement if it is displayed in the preview
6. THE Invoice_Preview SHALL display the payment terms under a "Payment Terms" heading with styling consistent with the notes section

### Requirement 6: Terms & Conditions — All Render Targets

**User Story:** As an organisation admin, I want the terms and conditions to appear consistently in the invoice web preview, PDF, and print output when enabled.

#### Acceptance Criteria

1. WHEN `terms_and_conditions_enabled` is `true` and the invoice has `terms_and_conditions` content, THE Invoice_Preview SHALL display the terms and conditions below the payment terms section
2. WHEN `terms_and_conditions_enabled` is `false`, THE Invoice_Preview SHALL NOT display the terms and conditions
3. WHEN `terms_and_conditions_enabled` is `true`, ALL 12 selectable PDF templates SHALL render the terms and conditions
4. WHEN `terms_and_conditions_enabled` is `false`, ALL PDF templates SHALL NOT render the terms and conditions
5. THE Invoice_Preview SHALL render the terms and conditions as HTML preserving formatting (bold, lists, links)
6. WHEN the user prints from the web preview (browser print), THE printed output SHALL include the terms and conditions if displayed in the preview

### Requirement 7: Fix HTML Stripping in Terms & Conditions Pre-fill

**User Story:** As an organisation admin, I want the terms and conditions to preserve HTML formatting when pre-filled into the invoice form, so that my lists, bold text, and links are not lost.

#### Acceptance Criteria

1. WHEN `terms_and_conditions_enabled` is `true` and `terms_and_conditions` content exists in Org_Settings, THE Invoice_Form SHALL pre-fill the terms and conditions field with the full HTML content without stripping tags
2. WHEN editing an existing invoice, THE Invoice_Form SHALL use the invoice's stored `terms_and_conditions` value regardless of the org setting
3. WHEN `terms_and_conditions_enabled` is `false`, THE Invoice_Form SHALL initialise the terms and conditions field as empty when creating a new invoice
4. THE Invoice_Form SHALL render the terms and conditions field as a rich text area that displays formatted HTML content
5. THE Invoice_Form SHALL preserve HTML formatting (bold, italic, lists, links, headings) in the terms and conditions value when submitting the invoice

### Requirement 8: All PDF Templates Must Render Notes and T&C

**User Story:** As an organisation admin, I want customer notes and terms & conditions to appear on my invoice PDF regardless of which template I have selected.

#### Acceptance Criteria

1. ALL 12 selectable invoice PDF templates SHALL render `notes_customer` when present on the invoice
2. ALL 12 selectable invoice PDF templates SHALL render `terms_and_conditions` when present and `terms_and_conditions_enabled` is `true`
3. ALL 12 selectable invoice PDF templates SHALL render `payment_terms` when present and `payment_terms_enabled` is `true`
4. THE following templates currently missing these sections SHALL be updated: classic, bold-header, compact-blue, compact-green, compact-mono, corporate, elegant, minimal, modern-dark, ocean, sunrise, trade-pro
5. THE rendering position and styling of notes, payment terms, and T&C SHALL be consistent across all templates (below line items, before footer)

### Requirement 9: Settings Toggle State in TenantContext and API

**User Story:** As a frontend developer, I want the toggle states and default values available in the TenantContext, so that the invoice form and preview can conditionally render sections without extra API calls.

#### Acceptance Criteria

1. THE TenantContext `InvoiceSettings` interface SHALL include: `default_notes: string | null`, `default_notes_enabled: boolean`, `payment_terms_enabled: boolean`, `terms_and_conditions_enabled: boolean`
2. THE Settings_API response SHALL include all four toggle boolean fields
3. THE invoice detail API response SHALL include `payment_terms_text` from org settings when `payment_terms_enabled` is `true`
4. WHEN `payment_terms_enabled` is `false`, THE invoice detail response SHALL NOT include `payment_terms_text`
5. THE invoice detail API response SHALL include `terms_and_conditions_enabled` so the frontend knows whether to render the per-invoice T&C

### Requirement 10: Backward Compatibility

**User Story:** As an existing user, I want my current invoices and settings to continue working without any changes after this update.

#### Acceptance Criteria

1. EXISTING invoices with `notes_customer` content SHALL continue to display notes in the preview and PDF regardless of the `default_notes_enabled` toggle
2. EXISTING invoices with `terms_and_conditions` content SHALL continue to display T&C in the PDF regardless of the `terms_and_conditions_enabled` toggle (per-invoice data is preserved)
3. THE "Use this in future for all invoices" checkbox SHALL continue to save `terms_and_conditions` to org settings as it does today
4. WHEN `payment_terms_enabled` defaults to `true`, EXISTING orgs that already have `payment_terms_text` configured SHALL see no change in PDF output
5. WHEN `terms_and_conditions_enabled` defaults to `true`, EXISTING orgs that already have `terms_and_conditions` configured SHALL see no change in PDF output
6. NO existing database columns or field names SHALL be renamed or removed
