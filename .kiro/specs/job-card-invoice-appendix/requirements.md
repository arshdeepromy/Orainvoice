# Requirements Document

## Introduction

When a completed job card is converted to an invoice, the full job card data (excluding the description field) should be captured as an HTML snapshot and stored on the invoice record. This snapshot becomes a second page (appendix) in every PDF generated for that invoice — whether triggered by Save & Send, Mark Paid & Email, Print PDF, or any other PDF action.

The approach is a point-in-time HTML snapshot: at conversion time, the system renders the job card data into a self-contained HTML fragment (with images base64-embedded) and stores it in a new column on the `invoices` table. The existing WeasyPrint pipeline in `generate_invoice_pdf()` then appends this HTML after a CSS page break, producing a two-page PDF with no changes to the invoice's first page.

### Key Design Decisions

**Snapshot at conversion time, not live lookup:** The appendix HTML is rendered once during `convert_job_card_to_invoice()` and stored on the invoice. This ensures the appendix reflects the job card state at the moment of invoicing, even if the job card data is later modified or deleted. It also avoids runtime database queries and file decryption during PDF generation.

**Description field excluded:** The job card `description` field is an internal work summary not intended for customer-facing documents. All other job card data — customer info, service type + field values, assigned staff, line items, time tracking entries, attachments, notes, and dates — is included.

**Attachments embedded as base64:** Job card attachments are encrypted on disk. At conversion time, each attachment is decrypted, and images are embedded as base64 `data:` URIs in the HTML. PDF attachments are referenced by filename only (not embedded) since WeasyPrint cannot render inline PDFs.

## Glossary

- **Job_Card**: A work order record in the `job_cards` table containing customer info, service type, line items, time entries, attachments, notes, and status. Managed by `app/modules/job_cards/service.py`.
- **Invoice**: A customer-facing billing record in the `invoices` table. Managed by `app/modules/invoices/service.py`.
- **Appendix_HTML**: A self-contained HTML fragment stored on the Invoice record that represents the job card data snapshot. Rendered as the second page of the invoice PDF.
- **Convert_To_Invoice_Flow**: The existing `convert_job_card_to_invoice()` function in `app/modules/job_cards/service.py` that creates a draft invoice from a completed job card.
- **PDF_Pipeline**: The existing `generate_invoice_pdf()` function in `app/modules/invoices/service.py` that renders an invoice HTML template via WeasyPrint into PDF bytes.
- **Invoice_Template**: The Jinja2 HTML template at `app/templates/pdf/invoice.html` used by the PDF_Pipeline.
- **Job_Card_Attachment**: An encrypted file (image or PDF) linked to a job card via the `job_card_attachments` table. Decrypted via `download_attachment()` in `app/modules/job_cards/attachment_service.py`.
- **Service_Type_Values**: The filled-in additional info field values for a job card's assigned service type, fetched via `get_service_type_values()`.
- **WeasyPrint**: The Python library used to convert HTML to PDF. Supports CSS `page-break-before` for multi-page documents.

## Requirements

### Requirement 1: Database Schema — Appendix HTML Column

**User Story:** As a developer, I want the invoice record to store the job card appendix HTML, so that the PDF pipeline can render it without additional lookups.

#### Acceptance Criteria

1. THE Invoice model SHALL include a new nullable TEXT column named `job_card_appendix_html` that stores the rendered HTML snapshot of the job card data.
2. THE `job_card_appendix_html` column SHALL default to NULL for invoices not created from job cards.
3. WHEN an Alembic migration adds the `job_card_appendix_html` column, THE migration SHALL be backwards-compatible and not affect existing invoice records.

### Requirement 2: HTML Snapshot Rendering

**User Story:** As a developer, I want a function that renders job card data into a self-contained HTML fragment, so that it can be stored on the invoice and later appended to the PDF.

#### Acceptance Criteria

1. THE Snapshot_Renderer SHALL accept the full job card data dict (as returned by `get_job_card()`), the list of job card attachments, and the decrypted attachment file bytes, and return a complete HTML string.
2. THE Snapshot_Renderer SHALL exclude the job card `description` field from the rendered HTML.
3. THE Snapshot_Renderer SHALL include the following sections in the rendered HTML: customer information (name, email, phone, address), service type name and filled-in field values, assigned staff member name, line items (item type, description, quantity, unit price, line total), time tracking entries (staff name, start time, stop time, duration), notes, and created/updated dates.
4. WHEN a job card has image attachments (JPEG, PNG, WebP, GIF), THE Snapshot_Renderer SHALL embed each image as a base64 `data:` URI in an `<img>` tag within the HTML.
5. WHEN a job card has PDF attachments, THE Snapshot_Renderer SHALL list each PDF attachment by filename only (not embedded), since WeasyPrint cannot render inline PDFs.
6. WHEN a job card has no attachments, THE Snapshot_Renderer SHALL omit the attachments section from the HTML.
7. WHEN a job card has no time tracking entries, THE Snapshot_Renderer SHALL omit the time tracking section from the HTML.
8. WHEN a job card has no line items, THE Snapshot_Renderer SHALL omit the line items section from the HTML.
9. WHEN a job card has no service type assigned, THE Snapshot_Renderer SHALL omit the service type section from the HTML.
10. THE Snapshot_Renderer SHALL produce HTML that is self-contained (no external CSS or image references) so that it renders correctly in WeasyPrint without network access.

### Requirement 3: Appendix HTML Generation During Conversion

**User Story:** As a user, I want the job card data to be automatically captured when I convert a job card to an invoice, so that the invoice PDF includes the full job card details.

#### Acceptance Criteria

1. WHEN `convert_job_card_to_invoice()` is called, THE Convert_To_Invoice_Flow SHALL fetch the job card attachments and decrypt all image attachment files.
2. WHEN `convert_job_card_to_invoice()` is called, THE Convert_To_Invoice_Flow SHALL invoke the Snapshot_Renderer with the job card data, attachments metadata, and decrypted image bytes to produce the Appendix_HTML.
3. WHEN the Appendix_HTML is generated, THE Convert_To_Invoice_Flow SHALL store the Appendix_HTML string in the `job_card_appendix_html` column of the newly created invoice record.
4. IF an attachment file cannot be decrypted or read (e.g., file missing from disk), THEN THE Convert_To_Invoice_Flow SHALL skip that attachment and continue rendering the remaining data without failing the conversion.
5. THE Convert_To_Invoice_Flow SHALL NOT include the job card `description` field in the data passed to the Snapshot_Renderer.

### Requirement 4: PDF Pipeline — Appendix Page Rendering

**User Story:** As a user, I want every invoice PDF generated from a job-card-sourced invoice to include the job card appendix as a second page, so that the full work details accompany the invoice.

#### Acceptance Criteria

1. WHEN `generate_invoice_pdf()` is called for an invoice that has a non-null `job_card_appendix_html` value, THE PDF_Pipeline SHALL append the Appendix_HTML after the invoice content with a CSS `page-break-before: always` rule, producing a multi-page PDF.
2. WHEN `generate_invoice_pdf()` is called for an invoice that has a null `job_card_appendix_html` value, THE PDF_Pipeline SHALL produce a single-page PDF with no appendix (existing behaviour unchanged).
3. THE Invoice_Template SHALL render the Appendix_HTML using Jinja2's `| safe` filter so that the stored HTML is output without escaping.
4. THE appendix page SHALL include a header identifying it as "Job Card Summary" with the job card reference visible.
5. THE appendix page SHALL use styling consistent with the invoice's first page (same font family, similar font sizes, matching colour scheme from the organisation's branding).

### Requirement 5: Appendix Content Formatting

**User Story:** As a customer receiving an invoice PDF, I want the job card appendix to be clearly formatted and readable, so that I can review the work performed.

#### Acceptance Criteria

1. THE appendix page SHALL display customer information (name, phone, email, address) in a summary block at the top.
2. WHEN the job card has a vehicle registration, THE appendix page SHALL display the vehicle registration prominently.
3. WHEN the job card has a service type with filled-in field values, THE appendix page SHALL display the service type name followed by each field label and its value.
4. WHEN the job card has line items, THE appendix page SHALL display them in a table with columns: Type, Description, Qty, Unit Price, and Line Total.
5. WHEN the job card has time tracking entries, THE appendix page SHALL display them in a table with columns: Staff, Start, Stop, and Duration.
6. WHEN the job card has image attachments, THE appendix page SHALL display each image scaled to fit within the page width (max-width 100%, auto height) with the original filename as a caption.
7. WHEN the job card has PDF attachments, THE appendix page SHALL list each PDF filename in a text list labelled "PDF Attachments".
8. WHEN the job card has notes, THE appendix page SHALL display the notes text in a dedicated section.
9. THE appendix page SHALL display the job card created date and last updated date.
10. THE appendix page SHALL display the assigned staff member name.

### Requirement 6: Resilience and Error Handling

**User Story:** As a developer, I want the appendix feature to degrade gracefully when data is missing or corrupted, so that invoice conversion and PDF generation are never blocked.

#### Acceptance Criteria

1. IF an image attachment file is missing from disk or fails to decrypt, THEN THE Snapshot_Renderer SHALL omit that image and include a placeholder text indicating the image was unavailable.
2. IF all attachment files fail to load, THEN THE Snapshot_Renderer SHALL omit the entire attachments section rather than showing only error placeholders.
3. IF the Appendix_HTML rendering fails entirely (unexpected exception), THEN THE Convert_To_Invoice_Flow SHALL log the error, set `job_card_appendix_html` to NULL, and continue creating the invoice without an appendix.
4. IF the `job_card_appendix_html` column contains malformed HTML, THEN THE PDF_Pipeline SHALL still produce a valid PDF (WeasyPrint handles malformed HTML gracefully by rendering what it can).
5. WHEN the Snapshot_Renderer encounters a missing optional section (no attachments, no time entries, no line items, no service type), THE Snapshot_Renderer SHALL omit that section cleanly without leaving empty headers or blank space.

### Requirement 7: Appendix HTML Snapshot Rendering — Round-Trip Integrity

**User Story:** As a developer, I want confidence that the HTML snapshot stored on the invoice faithfully represents the job card data, so that the PDF appendix is accurate.

#### Acceptance Criteria

1. FOR ALL valid job card data dicts, rendering the Appendix_HTML and then parsing the HTML to extract text content SHALL contain the customer name, each line item description, each time entry staff name, and the notes text present in the original data.
2. FOR ALL valid job card data dicts, the rendered Appendix_HTML SHALL NOT contain the job card description field value anywhere in the output.
3. FOR ALL valid job card data dicts with image attachments, the rendered Appendix_HTML SHALL contain one base64 `data:` URI `<img>` tag per image attachment provided.

## Non-Functional Requirements

### Performance

1. THE Snapshot_Renderer SHALL complete HTML generation within 5 seconds for a job card with up to 20 attachments (each up to 2 MB after compression).
2. THE `convert_job_card_to_invoice()` function SHALL not add more than 10 seconds of latency compared to the current conversion time, accounting for attachment decryption and HTML rendering.

### Storage

1. THE `job_card_appendix_html` column SHALL accommodate HTML strings up to 10 MB in size (PostgreSQL TEXT type has no practical limit, but the application should warn or truncate if the rendered HTML exceeds 10 MB).

### Security

1. THE Appendix_HTML SHALL NOT contain any raw file paths, encryption keys, or internal system identifiers (file_key values) — only the rendered content and base64-embedded images.
2. THE Appendix_HTML SHALL be rendered using Jinja2 with autoescaping enabled for all text content to prevent XSS if the HTML is ever displayed in a browser context.

## Out of Scope

- Editing the appendix HTML after invoice creation (it is a point-in-time snapshot)
- Regenerating the appendix if the job card is modified after conversion
- Embedding PDF attachment content inline in the appendix (WeasyPrint limitation)
- Displaying the appendix HTML in the frontend invoice detail view (PDF-only for now)
- Adding appendix support for invoices not created from job cards
