# Implementation Plan: Invoice PDF Templates

## Overview

This plan implements a configurable invoice PDF template system for OraInvoice. The implementation covers: a template registry module with 12 template definitions, a Jinja2 base template with 12 child templates using CSS custom properties for colour overrides, two new API endpoints (template list and preview), org settings schema changes for template selection persistence, modifications to `generate_invoice_pdf()` for template resolution, a React `InvoiceTemplateTab` component with grid/filters/colour pickers/preview, static thumbnail images, and property-based tests for all 7 correctness properties.

The backend is Python 3.11/FastAPI; the frontend is TypeScript/React. Property tests use Hypothesis with `@settings(max_examples=100)`. E2E tests follow the `scripts/test_*_e2e.py` pattern.

## Tasks

- [x] 1. Create template registry module and data definitions
  - [x] 1.1 Create `app/modules/invoices/template_registry.py` with `TemplateMetadata` dataclass and `TEMPLATES` dictionary
    - Define `TemplateMetadata` frozen dataclass with fields: `id`, `display_name`, `description`, `thumbnail_path`, `default_primary_colour`, `default_accent_colour`, `default_header_bg_colour`, `logo_position` (Literal["left", "center", "side"]), `layout_type` (Literal["standard", "compact"]), `template_file`
    - Populate `TEMPLATES` dict with all 12 entries from the design: `classic`, `modern-dark`, `compact-blue`, `bold-header`, `minimal`, `trade-pro`, `corporate`, `compact-green`, `elegant`, `compact-mono`, `sunrise`, `ocean`
    - Ensure 9 standard + 3 compact templates, and at least 2 per logo position (left, center, side)
    - Implement `list_templates()` → returns list of dicts (serialisable for API)
    - Implement `get_template_metadata(template_id)` → returns `TemplateMetadata | None`
    - Implement `validate_template_id(template_id)` → raises `ValueError` if not in registry
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 1.2 Write property test for template registry completeness (Property 1)
    - **Property 1: Template registry completeness**
    - **Validates: Requirements 1.2, 1.5**
    - Test file: `tests/test_invoice_templates.py`
    - Use Hypothesis: `st.sampled_from(list(TEMPLATES.keys()))` — pick any template, verify all metadata fields are non-empty strings, and the corresponding Jinja2 template file exists in `app/templates/pdf/`
    - `@settings(max_examples=100)`

  - [x] 1.3 Write property test for template ID validation (Property 4)
    - **Property 4: Template ID validation**
    - **Validates: Requirements 3.3, 3.4**
    - Test file: `tests/test_invoice_templates.py`
    - Use Hypothesis: `st.text(min_size=1, max_size=50)` — random strings, verify `validate_template_id()` raises ValueError for non-registry IDs and does not raise for registry IDs
    - `@settings(max_examples=100)`

  - [x] 1.4 Write property test for template filtering correctness (Property 5)
    - **Property 5: Template filtering correctness**
    - **Validates: Requirements 4.6**
    - Test file: `tests/test_invoice_templates.py`
    - Use Hypothesis: `st.sampled_from(["standard", "compact", "all"])` × `st.sampled_from(["left", "center", "side", "all"])` — all filter combos, verify filtered list matches exactly those templates whose metadata matches both criteria
    - `@settings(max_examples=100)`

- [x] 2. Create Jinja2 base template and all 12 child templates
  - [x] 2.1 Create `app/templates/pdf/_invoice_base.html` base template
    - Define blocks: `page_styles`, `header`, `bill_to`, `vehicle_info`, `line_items_table`, `totals`, `payment_status`, `payment_history`, `notes`, `payment_terms`, `terms_and_conditions`, `footer`
    - Include all conditional logic for optional fields: vehicle info (primary + additional vehicles), discount, payment history, customer notes, payment terms text, terms and conditions
    - Handle zero line items with a "No line items" placeholder row
    - Handle missing org logo — display org name only in header
    - Render payment status banners (Paid, Overdue, Voided, Refunded, Partially Refunded)
    - Include CSS for page breaks on invoices with many line items (`page-break-inside: avoid` on thead, `thead { display: table-header-group }` for header repeat)
    - Accept `colours` context dict with CSS custom properties (`--primary`, `--accent`, `--header-bg`)
    - Pass through all invoice data fields: org name, address, contact, logo, GST number, customer name/address/contact, invoice number, issue date, due date, payment terms, line items, subtotal, discount, GST, total, balance due, payment status, payment history, notes, terms
    - _Requirements: 2.4, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [x] 2.2 Create all 12 child templates extending `_invoice_base.html`
    - Create in `app/templates/pdf/`: `classic.html`, `modern-dark.html`, `compact-blue.html`, `bold-header.html`, `minimal.html`, `trade-pro.html`, `corporate.html`, `compact-green.html`, `elegant.html`, `compact-mono.html`, `sunrise.html`, `ocean.html`
    - Each template extends `_invoice_base.html` and overrides `page_styles` and `header`/`footer` blocks for visual identity
    - Each template uses CSS custom properties (`--primary`, `--accent`, `--header-bg`) for colour theming
    - Each template has a unique combination of: header layout, background colour scheme, typography weight, line-item table styling, footer arrangement
    - Compact templates (`compact-blue`, `compact-green`, `compact-mono`) use ≤ 6px top/bottom padding on line-item rows and reduced page margins
    - Logo position varies per template metadata (left, center, side)
    - _Requirements: 1.5, 2.1, 2.2, 2.3, 2.5_

- [x] 3. Checkpoint — Templates and registry complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Backend API — Template list, preview, and org settings changes
  - [x] 4.1 Add template list endpoint `GET /org/invoice-templates` in `app/modules/invoices/router.py`
    - Import `list_templates` from template registry
    - Return `{"templates": list_templates()}` — follows project convention of wrapping arrays in objects
    - Auth: `require_role("org_admin", "salesperson")`
    - _Requirements: 1.1, 1.2_

  - [x] 4.2 Create `app/modules/invoices/template_preview.py` with `render_template_preview()` function
    - Accept `db`, `org_id`, `template_meta`, `colour_overrides` parameters
    - Load org branding from DB (name, logo, address) or use defaults if no org context
    - Build sample invoice dict with realistic data (use `SAMPLE_INVOICE` and `SAMPLE_CUSTOMER` from design)
    - Resolve colour values: override > org settings > template defaults
    - Load and render the Jinja2 template with full context
    - Return HTML string
    - _Requirements: 6.2, 6.5_

  - [x] 4.3 Add template preview endpoint `POST /org/invoice-templates/preview` in `app/modules/invoices/router.py`
    - Define `TemplatePreviewRequest` Pydantic model with `template_id` (required), `primary_colour`, `accent_colour`, `header_bg_colour` (optional, hex pattern validated)
    - Validate template ID exists via `get_template_metadata()` — return HTTP 404 if not found
    - Call `render_template_preview()` and return `{"html": html}`
    - Auth: `require_role("org_admin")`
    - _Requirements: 6.1, 6.2, 6.5, 6.6_

  - [x] 4.4 Add `invoice_template_id` and `invoice_template_colours` fields to org settings schemas in `app/modules/organisations/schemas.py`
    - Add to update request schema: `invoice_template_id: Optional[str]` (max_length=50), `invoice_template_colours: Optional[dict]`
    - Add to response schema: `invoice_template_id: Optional[str]`, `invoice_template_colours: Optional[dict]`
    - _Requirements: 3.1, 3.5_

  - [x] 4.5 Add template ID validation in org settings service (`update_org_settings`)
    - When `invoice_template_id` is provided, call `validate_template_id()` — raises ValueError → HTTP 422
    - When `invoice_template_colours` is provided, validate each colour key (`primary_colour`, `accent_colour`, `header_bg_colour`) matches `^#[0-9A-Fa-f]{6}$`
    - Existing settings fields continue to work unchanged
    - _Requirements: 3.2, 3.3, 3.4, 10.3_

  - [x] 4.6 Write property test for colour resolution in rendered output (Property 2)
    - **Property 2: Colour resolution in rendered output**
    - **Validates: Requirements 2.2, 2.3, 7.3**
    - Test file: `tests/test_invoice_templates.py`
    - Use Hypothesis: `st.sampled_from(templates)` × `st.from_regex(r'#[0-9a-f]{6}', fullmatch=True)` — pick template + random colours, render, verify output HTML contains those exact hex values; when no overrides, verify defaults appear
    - `@settings(max_examples=100)`

  - [x] 4.7 Write property test for preview rendering for any template (Property 6)
    - **Property 6: Preview rendering for any template**
    - **Validates: Requirements 6.2, 6.5**
    - Test file: `tests/test_invoice_templates.py`
    - Use Hypothesis: `st.sampled_from(templates)` — pick any template, call preview render, verify non-empty HTML containing sample customer name, sample invoice number, sample line item descriptions
    - `@settings(max_examples=100)`

- [x] 5. Backend — Modify `generate_invoice_pdf()` for template resolution
  - [x] 5.1 Update `generate_invoice_pdf()` in `app/modules/invoices/service.py`
    - Read `invoice_template_id` and `invoice_template_colours` from `org.settings` JSONB
    - When `invoice_template_id` is present and valid: load corresponding `.html` file from registry, resolve colours (org override > template default), inject `colours` dict into Jinja2 context
    - When `invoice_template_id` is present but not in registry: log warning, fall back to `invoice.html`
    - When `invoice_template_id` is absent: use existing `invoice.html` (no changes to current behaviour)
    - Pass the same data context (invoice, org, customer, currency_symbol, gst_percentage, payment_terms, terms_and_conditions, i18n labels) to all templates
    - Do NOT modify the existing `invoice.html` template file
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 10.1, 10.2_

  - [x] 5.2 Write property test for template data rendering completeness (Property 3)
    - **Property 3: Template data rendering completeness**
    - **Validates: Requirements 2.4, 9.1, 9.2, 9.3, 9.4, 9.6**
    - Test file: `tests/test_invoice_templates.py`
    - Use Hypothesis: `st.sampled_from(templates)` × `st.builds(invoice_data)` — pick template + generated invoice data with optional fields (zero line items, absent vehicle info, absent discount, absent payment history, no logo, various payment statuses, additional vehicles), render, verify output contains all provided data values
    - `@settings(max_examples=100)`

- [x] 6. Checkpoint — Backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Frontend — InvoiceTemplateTab component
  - [x] 7.1 Create `frontend/src/pages/settings/InvoiceTemplateTab.tsx` with template grid and card components
    - Fetch templates from `GET /org/invoice-templates` on mount with AbortController cleanup
    - Fetch current org settings from `GET /org/settings` to determine saved template
    - Display grid of `TemplateCard` components — each shows: thumbnail (lazy loaded), display name, description, logo position label, layout type label
    - Highlight selected card with distinct border colour on click
    - Show "Current" badge on the currently saved template
    - Show "Default" badge on the default template when no template is saved
    - Use `?.` and `?? []` / `?? 0` on all API response data
    - Handle thumbnail load errors with placeholder showing template name
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 8.4, 10.4_

  - [x] 7.2 Add filter controls to `InvoiceTemplateTab`
    - Layout type filter: `All`, `Standard`, `Compact`
    - Logo position filter: `All`, `Left`, `Center`, `Side`
    - Filter the template grid based on selected filter values
    - _Requirements: 4.6_

  - [x] 7.3 Add colour customisation controls to `InvoiceTemplateTab`
    - Display 3 colour picker inputs when a template is selected: primary colour, accent colour, header background colour
    - Pre-populate pickers with the selected template's default colours from registry data
    - Store changed values as colour overrides in component state
    - Provide "Reset to Defaults" button that restores all pickers to the selected template's defaults
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 7.4 Add preview functionality to `InvoiceTemplateTab`
    - Display "Preview" button next to the selected template
    - On click: call `POST /org/invoice-templates/preview` with template ID and current colour overrides
    - Render returned HTML in a modal with an iframe
    - Handle preview API errors with toast notification
    - _Requirements: 6.3, 6.4_

  - [x] 7.5 Add save functionality and integrate tab into OrgSettings
    - "Save" button sends `PUT /org/settings` with `invoice_template_id` and `invoice_template_colours`
    - Handle save success (toast) and errors (422 → show error detail, network → generic toast)
    - Add `{ id: 'invoice-template', label: 'Invoice Template', content: <InvoiceTemplateTab /> }` tab entry in `OrgSettings.tsx`
    - _Requirements: 5.5, 4.1_

- [x] 8. Frontend — Static thumbnail images
  - [x] 8.1 Create placeholder thumbnail images in `frontend/public/templates/`
    - Create 12 PNG images (one per template): `classic.png`, `modern-dark.png`, `compact-blue.png`, `bold-header.png`, `minimal.png`, `trade-pro.png`, `corporate.png`, `compact-green.png`, `elegant.png`, `compact-mono.png`, `sunrise.png`, `ocean.png`
    - Each image minimum 400px wide, aspect ratio ~1:1.4 (A4 proportions)
    - Each thumbnail should represent the template's header layout, colour scheme, logo position, and line-item table styling
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 8.2 Write property test for thumbnail file integrity (Property 7)
    - **Property 7: Thumbnail file integrity**
    - **Validates: Requirements 8.1, 8.2**
    - Test file: `tests/test_invoice_templates.py`
    - Use Hypothesis: `st.sampled_from(templates)` — pick any template, verify thumbnail file exists in `frontend/public/`, is a valid PNG or WebP, and is at least 400px wide
    - `@settings(max_examples=100)`

- [x] 9. Checkpoint — Frontend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. End-to-end test script
  - [x] 10.1 Create `scripts/test_invoice_templates_e2e.py`
    - Follow feature-testing-workflow steering pattern (httpx, asyncio, ok/fail helpers)
    - Login as org_admin
    - GET `/org/invoice-templates` → verify returns 12 templates with correct metadata shape
    - POST `/org/invoice-templates/preview` with valid template ID → verify returns non-empty HTML
    - POST `/org/invoice-templates/preview` with invalid template ID → verify 404
    - PUT `/org/settings` with valid `invoice_template_id` and `invoice_template_colours` → verify 200
    - PUT `/org/settings` with invalid `invoice_template_id` → verify 422
    - GET `/org/settings` → verify `invoice_template_id` and `invoice_template_colours` are returned
    - Create and issue an invoice → download PDF → verify PDF is generated (non-empty bytes)
    - Reset `invoice_template_id` to null → verify default template is used
    - Verify backward compatibility: org with no template settings still generates PDF with `invoice.html`
    - Clean up test data
    - _Requirements: 1.1, 1.2, 2.1, 3.1, 3.3, 3.4, 3.5, 6.1, 6.2, 6.6, 7.1, 7.2, 7.3, 7.4, 10.1, 10.2, 10.3_

- [x] 11. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at templates/registry, backend, frontend, and integration milestones
- Property tests validate the 7 correctness properties defined in the design document
- The existing `invoice.html` template file MUST remain unmodified (backward compatibility)
- The `get_db_session` dependency uses `session.begin()` which auto-commits — use `flush()` not `commit()` in services; after `db.flush()`, always `await db.refresh(obj)` before returning ORM objects for Pydantic serialization
- All frontend API calls must follow safe-api-consumption patterns (`?.`, `?? []`, `?? 0`, AbortController cleanup, typed generics)
- All API responses wrap arrays in objects (`{ templates: [...] }`, `{ html: "..." }`)
- E2E test script goes in `scripts/` following the feature-testing-workflow steering pattern
- Thumbnail images are placeholder PNGs — they should be regenerated with accurate representations once templates are finalised
