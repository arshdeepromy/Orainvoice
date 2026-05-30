# Requirements Document

## Introduction

The Invoice document already honours three organisation-wide settings — Notes, Payment Terms, and Terms & Conditions — end-to-end (create form pre-fill, server-side resolution, detail page rendering, and PDF rendering). The Quote document only partially honours the same settings. This feature closes the gap by making Quotes mirror the Invoice behaviour exactly, reusing the existing `organisations.settings` JSONB keys, the existing `update_org_settings` API, the existing settings UI in `OrgSettings.tsx`, and the resolution patterns already in `app/modules/invoices/service.py`.

No new settings keys, no new tables, no new endpoints, and no schema migrations on the `quotes` table are introduced. The per-quote `quotes.terms` column is preserved as-is to avoid breaking changes; the resolved render-time value is computed in the service layer alongside the existing `payment_terms_text` resolution.

## Glossary

- **Org_Settings**: The `organisations.settings` JSONB column. Read and written via `GET /org/settings` and `PUT /org/settings` (`app/modules/organisations/router.py` → `update_org_settings()` in `app/modules/organisations/service.py`). Edited in the UI at `frontend/src/pages/settings/OrgSettings.tsx`.
- **default_notes_enabled**: Boolean key in `Org_Settings.invoice` controlling whether the org-level default notes are pre-filled into newly created documents. Default: `false`.
- **default_notes**: String key in `Org_Settings.invoice` holding the org-level default notes text. Default: `""`.
- **payment_terms_enabled**: Boolean key in `Org_Settings.invoice` controlling whether the org-level payment terms statement appears on documents. Default: `true`.
- **payment_terms_text**: String key in `Org_Settings.invoice` holding the org-level payment terms statement. Default: `""`.
- **terms_and_conditions_enabled**: Boolean key in `Org_Settings.invoice` controlling whether the org-level Terms & Conditions appear when no per-document override is supplied. Default: `true`.
- **terms_and_conditions**: String key in `Org_Settings.invoice` holding the org-level Terms & Conditions text. Default: `""`.
- **Quote_Service**: The backend service module at `app/modules/quotes/service.py`. Owns quote creation, retrieval, response shaping, and PDF context construction (`generate_quote_pdf`).
- **Quote_Response_Schema**: The Pydantic schema at `app/modules/quotes/schemas.py` that defines the shape of `GET /quotes/{id}` and `GET /quotes` payloads.
- **QuoteCreate_Form**: The React component at `frontend/src/pages/quotes/QuoteCreate.tsx` used to compose a new quote.
- **Quote_Detail_Page**: The React component at `frontend/src/pages/quotes/QuoteDetail.tsx` rendering a single quote in the web UI.
- **Quote_PDF_Template**: The Jinja template at `app/templates/pdf/quote.html` rendered by WeasyPrint.
- **Quote_PDF_Generator**: The function `generate_quote_pdf` in `app/modules/quotes/service.py` that builds the Jinja context and invokes WeasyPrint.
- **Per_Quote_Terms**: The existing `quotes.terms` column on the `quotes` table (`app/modules/quotes/models.py:69`). Stores any quote-specific Terms & Conditions text supplied at create or edit time. NOT renamed by this feature.
- **Resolved_Terms_And_Conditions**: The render-time string returned to clients and used by the PDF, computed by `Quote_Service` using the same precedence as `app/modules/invoices/service.py:4153-4161`: per-quote value if non-empty, else org-level `terms_and_conditions` when `terms_and_conditions_enabled` is `true`, else `null`.
- **Invoice_Reference_Behaviour**: The existing invoice implementation that this feature mirrors. Anchor points: `app/modules/invoices/service.py:1764-1775` (detail response payment terms + T&C resolution), `app/modules/invoices/service.py:4150` (PDF payment terms), `app/modules/invoices/service.py:4153-4161` (PDF T&C resolution), `app/modules/invoices/schemas.py:299-300` (response fields), `frontend/src/pages/invoices/InvoiceCreate.tsx:901-911` (pre-fill), `frontend/src/pages/invoices/InvoiceDetail.tsx:1214-1250` (rendering), `app/templates/pdf/invoice.html:462-488` (PDF blocks).

## Requirements

### Requirement 1: Notes pre-fill on quote creation

**User Story:** As an org user creating a new quote, I want the Notes field pre-filled with my organisation's default notes when default notes are enabled, so that I do not have to retype the same standard notes for every quote and the behaviour matches what already happens on invoices.

#### Acceptance Criteria

1. WHEN the QuoteCreate_Form mounts AND `Org_Settings.invoice.default_notes_enabled` is `true` AND `Org_Settings.invoice.default_notes` is a non-empty string, THE QuoteCreate_Form SHALL pre-fill the Notes input with the value of `Org_Settings.invoice.default_notes`.
2. WHEN the QuoteCreate_Form mounts AND `Org_Settings.invoice.default_notes_enabled` is `false`, THE QuoteCreate_Form SHALL leave the Notes input empty.
3. WHEN the QuoteCreate_Form mounts AND `Org_Settings.invoice.default_notes_enabled` is `true` AND `Org_Settings.invoice.default_notes` is an empty string, THE QuoteCreate_Form SHALL leave the Notes input empty.
4. WHEN a user edits the pre-filled Notes input before saving, THE QuoteCreate_Form SHALL persist the user-edited value into the new quote's `notes` column without further reference to `Org_Settings`.
5. THE QuoteCreate_Form SHALL apply the pre-fill logic exactly once per form mount, mirroring the behaviour at `frontend/src/pages/invoices/InvoiceCreate.tsx:901-904`.

### Requirement 2: Notes rendering on quote detail page and PDF

**User Story:** As an org user viewing a quote, I want the Notes section to appear whenever the quote has notes content, so that the quote's presentation matches the invoice presentation.

#### Acceptance Criteria

1. WHEN the Quote_Detail_Page renders a quote AND the quote's `notes` field is a non-empty string, THE Quote_Detail_Page SHALL display the Notes section containing the `notes` value.
2. WHEN the Quote_Detail_Page renders a quote AND the quote's `notes` field is `null` or an empty string, THE Quote_Detail_Page SHALL omit the Notes section.
3. WHEN the Quote_PDF_Generator renders a quote AND the quote's `notes` field is a non-empty string, THE Quote_PDF_Template SHALL display the Notes section containing the `notes` value.
4. WHEN the Quote_PDF_Generator renders a quote AND the quote's `notes` field is `null` or an empty string, THE Quote_PDF_Template SHALL omit the Notes section.

### Requirement 3: Payment Terms typing on the quote response

**User Story:** As a frontend developer, I want the `payment_terms_text` field declared on the Quote response Pydantic schema and the `QuoteData` TypeScript interface, so that the Quote_Detail_Page can read the value with full type safety and without `as any`.

#### Acceptance Criteria

1. THE Quote_Response_Schema SHALL declare `payment_terms_text` as an optional string field (`Optional[str]`, default `None`).
2. THE `QuoteData` TypeScript interface in `frontend/src/pages/quotes/QuoteDetail.tsx` SHALL declare `payment_terms_text?: string | null`.
3. WHEN the Quote_Detail_Page reads the payment terms value, THE Quote_Detail_Page SHALL access `quote.payment_terms_text` directly without `as any` and without any other type assertion.
4. THE Quote_Service SHALL continue to populate `payment_terms_text` on responses using the existing resolution at `app/modules/quotes/service.py:493-497` without behavioural change.

### Requirement 4: Payment Terms rendering parity on the quote detail page and PDF

**User Story:** As an org user viewing a quote, I want the Payment Terms statement to appear when the organisation has Payment Terms enabled and configured, so that the quote shows the same payment expectations the invoice would show.

#### Acceptance Criteria

1. WHEN the Quote_Detail_Page renders a quote AND `quote.payment_terms_text` is a non-empty string, THE Quote_Detail_Page SHALL display the Payment Terms section containing the `payment_terms_text` value.
2. WHEN the Quote_Detail_Page renders a quote AND `quote.payment_terms_text` is `null` or empty, THE Quote_Detail_Page SHALL omit the Payment Terms section.
3. WHEN the Quote_PDF_Generator builds the Jinja context, THE Quote_PDF_Generator SHALL set the `payment_terms` Jinja variable to the same value the Quote_Service injects into the API response (`payment_terms_text` resolved against `payment_terms_enabled` and `payment_terms_text`).
4. WHEN the Quote_PDF_Template renders a quote AND the `payment_terms` Jinja variable is a non-empty string, THE Quote_PDF_Template SHALL display the Payment Terms section.
5. WHEN the Quote_PDF_Template renders a quote AND the `payment_terms` Jinja variable is empty or unset, THE Quote_PDF_Template SHALL omit the Payment Terms section.
6. THE Quote_Service SHALL apply the same resolution rule as `app/modules/invoices/service.py:1764-1775`: include `payment_terms_text` only when `Org_Settings.invoice.payment_terms_enabled` is `true` AND `Org_Settings.invoice.payment_terms_text` is a non-empty string.

### Requirement 5: Terms & Conditions resolution on the quote service response

**User Story:** As an org user viewing a quote, I want the Terms & Conditions to follow the same precedence I see on invoices — per-document override first, then org-level default when the toggle is on — so that quote behaviour is predictable for users who already understand invoice behaviour.

#### Acceptance Criteria

1. THE Quote_Service SHALL compute Resolved_Terms_And_Conditions for every quote response using this precedence: (a) Per_Quote_Terms when non-empty, (b) `Org_Settings.invoice.terms_and_conditions` when `Org_Settings.invoice.terms_and_conditions_enabled` is `true` AND that value is non-empty, (c) `null`.
2. THE Quote_Service SHALL include `terms_and_conditions` in every quote response, set to Resolved_Terms_And_Conditions.
3. THE Quote_Service SHALL include `terms_and_conditions_enabled` in every quote response, set to the boolean value of `Org_Settings.invoice.terms_and_conditions_enabled`.
4. WHEN Per_Quote_Terms is non-empty AND `Org_Settings.invoice.terms_and_conditions_enabled` is `false`, THE Quote_Service SHALL set Resolved_Terms_And_Conditions to the Per_Quote_Terms value (per-quote override wins regardless of the toggle).
5. WHEN Per_Quote_Terms is empty AND `Org_Settings.invoice.terms_and_conditions_enabled` is `false`, THE Quote_Service SHALL set Resolved_Terms_And_Conditions to `null`.
6. THE Quote_Service SHALL apply the same resolution to single-quote endpoints (`GET /quotes/{id}`) and list endpoints (`GET /quotes`) so the response shape is consistent.
7. THE Quote_Service SHALL NOT rename, drop, or alter the `quotes.terms` column.

### Requirement 6: Terms & Conditions on the quote response schema and TypeScript interface

**User Story:** As a frontend developer, I want the resolved Terms & Conditions value and toggle declared on the Quote response schema and TypeScript interface, so that the Quote_Detail_Page can gate rendering on the toggle without `as any`.

#### Acceptance Criteria

1. THE Quote_Response_Schema SHALL declare `terms_and_conditions` as an optional string field (`Optional[str]`, default `None`).
2. THE Quote_Response_Schema SHALL declare `terms_and_conditions_enabled` as a boolean field (`bool`, default `false`).
3. THE `QuoteData` TypeScript interface in `frontend/src/pages/quotes/QuoteDetail.tsx` SHALL declare `terms_and_conditions?: string | null` and `terms_and_conditions_enabled?: boolean`.
4. THE Quote_Response_Schema field declarations SHALL mirror the invoice schema declarations at `app/modules/invoices/schemas.py:299-300`.

### Requirement 7: Terms & Conditions rendering on the quote detail page

**User Story:** As an org user viewing a quote, I want the Terms & Conditions section to appear only when the org-level toggle is on AND there is text to show, so that the section behaves identically to the invoice detail page.

#### Acceptance Criteria

1. WHEN the Quote_Detail_Page renders a quote AND `quote.terms_and_conditions_enabled` is `true` AND `quote.terms_and_conditions` is a non-empty string, THE Quote_Detail_Page SHALL display the Terms & Conditions section containing `quote.terms_and_conditions`.
2. WHEN the Quote_Detail_Page renders a quote AND `quote.terms_and_conditions_enabled` is `false`, THE Quote_Detail_Page SHALL omit the Terms & Conditions section.
3. WHEN the Quote_Detail_Page renders a quote AND `quote.terms_and_conditions` is `null` or empty, THE Quote_Detail_Page SHALL omit the Terms & Conditions section.
4. THE Quote_Detail_Page condition SHALL mirror the invoice condition at `frontend/src/pages/invoices/InvoiceDetail.tsx:1242-1250`.

### Requirement 8: Terms & Conditions rendering on the quote PDF

**User Story:** As an org user printing or emailing a quote PDF, I want the PDF Terms & Conditions section to follow exactly the same resolution and toggle logic as the detail page, so that the PDF and the on-screen quote agree.

#### Acceptance Criteria

1. WHEN the Quote_PDF_Generator builds the Jinja context, THE Quote_PDF_Generator SHALL set the `terms_and_conditions` Jinja variable to Resolved_Terms_And_Conditions for that quote.
2. WHEN the Quote_PDF_Template renders a quote AND the `terms_and_conditions` Jinja variable is a non-empty string, THE Quote_PDF_Template SHALL display the Terms & Conditions section.
3. WHEN the Quote_PDF_Template renders a quote AND the `terms_and_conditions` Jinja variable is empty or unset, THE Quote_PDF_Template SHALL omit the Terms & Conditions section.
4. THE Quote_PDF_Generator SHALL use the same resolution function or inline logic that produces `terms_and_conditions` for the API response, so the detail page and the PDF cannot diverge.

### Requirement 9: Terms & Conditions pre-fill on quote creation (regression coverage)

**User Story:** As an org user creating a new quote, I want the Terms input pre-filled with my org-level Terms & Conditions when the toggle is on, so that the existing pre-fill behaviour at `frontend/src/pages/quotes/QuoteCreate.tsx:647-650` continues to work after this feature ships.

#### Acceptance Criteria

1. WHEN the QuoteCreate_Form mounts AND `Org_Settings.invoice.terms_and_conditions_enabled` is `true` AND `Org_Settings.invoice.terms_and_conditions` is a non-empty string, THE QuoteCreate_Form SHALL pre-fill the Terms input with the value of `Org_Settings.invoice.terms_and_conditions`.
2. WHEN the QuoteCreate_Form mounts AND `Org_Settings.invoice.terms_and_conditions_enabled` is `false`, THE QuoteCreate_Form SHALL leave the Terms input empty.
3. WHEN a user saves a new quote with an edited Terms value, THE Quote_Service SHALL persist the user-edited value into the `quotes.terms` column.
4. WHEN a user saves a new quote with the `save_terms_as_default` flag set, THE Quote_Service SHALL update `Org_Settings.invoice.terms_and_conditions` using the existing helper at `app/modules/quotes/service.py:384-399` without bypassing the standard `update_org_settings` write path.

### Requirement 10: Reuse and non-regression constraints

**User Story:** As an engineer maintaining this codebase, I want this feature to reuse the existing settings infrastructure rather than introduce a parallel one, so that quote and invoice rendering stay in lock-step over time.

#### Acceptance Criteria

1. THE Quote_Service SHALL read all three settings groups (Notes, Payment Terms, Terms & Conditions) from the existing `Org_Settings.invoice` JSONB section using the existing settings access patterns in `app/modules/invoices/service.py`.
2. THE feature SHALL NOT introduce new keys into `Org_Settings`.
3. THE feature SHALL NOT introduce a new database table, column, or Alembic migration.
4. THE feature SHALL NOT introduce a new HTTP endpoint; all settings reads continue through existing org-context loaders and all settings writes continue through `PUT /org/settings`.
5. THE OrgSettings UI at `frontend/src/pages/settings/OrgSettings.tsx` SHALL remain the single user-facing edit surface for `default_notes`, `default_notes_enabled`, `payment_terms_text`, `payment_terms_enabled`, `terms_and_conditions`, and `terms_and_conditions_enabled`.
6. THE invoice-side behaviour at the anchor points listed in Invoice_Reference_Behaviour SHALL remain functionally unchanged after this feature ships.
7. WHERE this feature requires a helper that already exists on the invoice side (for example payment terms or T&C resolution), THE Quote_Service SHALL reuse or duplicate the existing pattern, NOT invent a new one.
