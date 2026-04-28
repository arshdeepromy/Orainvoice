# Implementation Plan: Job Card Invoice Appendix

## Overview

Add a job card appendix page to invoice PDFs. When a completed job card is converted to an invoice, the system renders the job card data into a self-contained HTML fragment (with images base64-embedded) and stores it in a new `job_card_appendix_html` TEXT column on the `invoices` table. The existing WeasyPrint PDF pipeline then appends this HTML after a CSS page break, producing a two-page PDF.

Implementation proceeds bottom-up: database schema first, then the snapshot renderer, then the conversion flow integration, then the PDF pipeline update, and finally the invoice template change.

## Tasks

- [x] 1. Add database column and migration
  - [x] 1.1 Add `job_card_appendix_html` column to the Invoice model in `app/modules/invoices/models.py`
    - Add `job_card_appendix_html: Mapped[str | None] = mapped_column(Text, nullable=True, comment="HTML snapshot of job card data for PDF appendix")`
    - Place it after the existing `quote_id` column
    - _Requirements: 1.1, 1.2_

  - [x] 1.2 Create Alembic migration `alembic/versions/YYYY_MM_DD_HHMM-0163_add_job_card_appendix_html.py`
    - `upgrade()`: `op.add_column("invoices", sa.Column("job_card_appendix_html", sa.Text(), nullable=True, comment="HTML snapshot of job card data for PDF appendix"))`
    - `downgrade()`: `op.drop_column("invoices", "job_card_appendix_html")`
    - Set `down_revision = "0162"` (current head from job-card-attachments)
    - Run migration: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head`
    - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Create the snapshot renderer and Jinja2 template
  - [x] 2.1 Create the appendix Jinja2 template at `app/templates/pdf/job_card_appendix.html`
    - Inline CSS matching the invoice template's font family (Arial/Helvetica) and colour scheme
    - Header section: "Job Card Summary" title with job card reference
    - Customer information block: name, phone, email, address
    - Vehicle registration section gated by `trade_family == 'automotive-transport'`
    - Service type section: service type name + each field label/value pair
    - Line items table: columns Type, Description, Qty, Unit Price, Line Total
    - Time tracking table: columns Staff, Start, Stop, Duration
    - Image attachments: base64 `<img>` tags with `max-width:100%; height:auto` and filename caption
    - PDF attachments: filename-only text list labelled "PDF Attachments"
    - Notes section
    - Created/updated dates and assigned staff name
    - Each section conditionally rendered (omit if no data)
    - Placeholder text `[Image unavailable: {filename}]` for missing images
    - Autoescaping enabled
    - Exclude the `description` field entirely
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10_

  - [x] 2.2 Create the snapshot renderer module at `app/modules/job_cards/snapshot_renderer.py`
    - Implement `async def render_job_card_appendix_html(job_card_data, attachments, attachment_bytes, trade_family=None) -> str`
    - Load the `job_card_appendix.html` template using Jinja2 `Environment` with `FileSystemLoader` and `autoescape=True`
    - Build template context from the input parameters:
      - Customer info from `job_card_data["customer"]`
      - Line items from `job_card_data["line_items"]`
      - Time entries from `job_card_data["time_entries"]`
      - Service type from `job_card_data["service_type_name"]` and `job_card_data["service_type_values"]`
      - Notes from `job_card_data["notes"]`
      - Assigned staff from `job_card_data["assigned_to_name"]`
      - Vehicle rego from `job_card_data["vehicle_rego"]`
      - Dates from `job_card_data["created_at"]` and `job_card_data["updated_at"]`
    - For each image attachment: base64-encode the bytes from `attachment_bytes[str(att["id"])]` and build `data:{mime_type};base64,{b64}` URIs
    - For missing image bytes: use placeholder text `[Image unavailable: {filename}]`
    - If all image attachments fail and no PDF attachments exist, omit the entire attachments section
    - Return the rendered HTML string
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 6.1, 6.2, 6.5, NF Security 1, NF Security 2_

- [x] 3. Checkpoint — Verify renderer in isolation
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Integrate appendix generation into the conversion flow
  - [x] 4.1 Extend `convert_job_card_to_invoice()` in `app/modules/job_cards/service.py`
    - After the invoice is created (after `invoice_dict = await create_invoice(...)`), add a try/except block for appendix generation
    - Inside the try block:
      - Import `list_attachments` and `download_attachment` from `app.modules.job_cards.attachment_service`
      - Import `render_job_card_appendix_html` from `app.modules.job_cards.snapshot_renderer`
      - Fetch attachments: `attachments = await list_attachments(db, org_id=org_id, job_card_id=job_card_id)`
      - Decrypt image attachments using `asyncio.to_thread(download_attachment, org_id, att["file_key"])` for each image attachment, skipping failures with a warning log
      - Fetch org trade_family from `Organisation.settings`
      - Build `jc_data_for_snapshot` by excluding the `description` key from `jc_dict`
      - Call `render_job_card_appendix_html(job_card_data=jc_data_for_snapshot, attachments=attachments, attachment_bytes=attachment_bytes, trade_family=trade_family)`
    - On success: load the Invoice ORM object, set `inv_obj.job_card_appendix_html = appendix_html`, flush
    - On any exception: log via `logger.exception(...)`, set `appendix_html = None` — invoice creation continues unblocked
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 6.3_

  - [x] 4.2 Write property tests in `tests/test_job_card_appendix_properties.py`
    - Create a custom Hypothesis strategy that generates valid job card data dicts with random customer names, line items (0–10), time entries (0–5), notes, service type values, attachment metadata with small generated PNG bytes, vehicle_rego strings, and description strings
    - **Property 1: Round-trip content integrity** — render appendix HTML and verify extracted text contains customer name, line item descriptions, time entry staff names, assigned staff name, notes, and date values
    - **Validates: Requirements 2.3, 5.1, 5.3, 5.4, 5.5, 5.8, 5.9, 5.10, 7.1**

  - [x] 4.3 Write property test for description exclusion
    - **Property 2: Description field exclusion** — for any job card data with a non-empty `description`, the rendered HTML must not contain the description value
    - **Validates: Requirements 2.2, 7.2**

  - [x] 4.4 Write property test for image base64 embedding
    - **Property 3: Image attachment base64 embedding** — for N image attachments with provided bytes, the HTML must contain exactly N `<img` tags with `src="data:` URIs, and each filename must appear as a caption
    - **Validates: Requirements 2.4, 5.6, 7.3**

  - [x] 4.5 Write property test for PDF attachment listing
    - **Property 4: PDF attachment filename listing** — for PDF attachments, the HTML must contain each filename and must not contain any base64 `data:` URI for PDFs
    - **Validates: Requirements 2.5, 5.7**

  - [x] 4.6 Write property test for self-contained HTML
    - **Property 5: Self-contained HTML output** — the rendered HTML must not contain `<link` tags or external `http://`/`https://` references in `src`/`href` attributes
    - **Validates: Requirements 2.10**

  - [x] 4.7 Write property test for no internal identifiers
    - **Property 6: No internal identifiers in output** — the rendered HTML must not contain any `file_key` path strings or encryption key material
    - **Validates: Requirements NF Security 1**

  - [x] 4.8 Write property test for vehicle registration gating
    - **Property 7: Vehicle registration gated by trade family** — vehicle rego appears in HTML only when `trade_family == 'automotive-transport'`, and is absent for other trade families
    - **Validates: Requirements 5.2**

  - [x] 4.9 Write unit tests for snapshot renderer edge cases
    - `test_empty_job_card_renders` — minimal job card with no line items, time entries, or attachments produces valid HTML
    - `test_missing_image_shows_placeholder` — attachment metadata present but bytes missing shows `[Image unavailable: {filename}]`
    - `test_all_images_missing_omits_section` — all attachment bytes missing omits the entire attachments section
    - `test_no_time_entries_omits_section` — empty time_entries omits time tracking section
    - `test_no_line_items_omits_section` — empty line_items omits line items section
    - `test_no_service_type_omits_section` — service_type_name=None omits service type section
    - `test_appendix_header_text` — output contains "Job Card Summary" header
    - `test_autoescaping_prevents_xss` — customer name with `<script>` tag is escaped
    - _Requirements: 2.6, 2.7, 2.8, 2.9, 6.1, 6.2, 6.5, NF Security 2_

- [x] 5. Checkpoint — Verify conversion flow integration
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Update the PDF pipeline and invoice template
  - [x] 6.1 Update `generate_invoice_pdf()` in `app/modules/invoices/service.py`
    - Add `job_card_appendix_html=invoice_dict.get("job_card_appendix_html")` to the `template.render(...)` call
    - No other changes needed — `get_invoice()` already returns all invoice columns, so the new column is automatically included in `invoice_dict`
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 6.2 Update the invoice template at `app/templates/pdf/invoice.html`
    - Before the closing `</body>` tag (after the existing footer div), add:
      ```html
      {% if job_card_appendix_html %}
      <div style="page-break-before: always;"></div>
      {{ job_card_appendix_html | safe }}
      {% endif %}
      ```
    - The `| safe` filter is correct because the HTML was rendered by our own Jinja2 template with autoescaping
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 7. Create E2E test script
  - [x] 7.1 Create `scripts/test_job_card_invoice_appendix_e2e.py`
    - Log in as `demo@orainvoice.com`
    - Create a customer
    - Create a job card with line items, time entries, and at least one image attachment
    - Complete the job card
    - Convert the job card to an invoice
    - Verify the invoice record has `job_card_appendix_html` populated (non-null)
    - Call `generate_invoice_pdf()` and verify the PDF has 2+ pages (using PyPDF2 or similar)
    - Clean up test data
    - Run with: `docker exec invoicing-app-1 python scripts/test_job_card_invoice_appendix_e2e.py`
    - _Requirements: 4.1, 4.2, 3.2, 3.3_

- [x] 8. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The current Alembic head is revision 0162 — the new migration will be 0163
- After creating the migration, run: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head`
- The `get_invoice()` function already returns all invoice columns, so `job_card_appendix_html` will be included automatically once the model column exists
- Attachment decryption uses `asyncio.to_thread()` to avoid blocking the event loop
- The entire appendix generation is wrapped in try/except — failure results in NULL appendix, never blocks invoice creation
- Vehicle registration section is gated by `trade_family == 'automotive-transport'`
