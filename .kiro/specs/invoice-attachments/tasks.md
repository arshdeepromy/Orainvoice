# Invoice Attachments — Tasks

## Task 1: Database migration and model
- [ ] 1.1 Create `alembic/versions/2026_04_29_2200-0170_create_invoice_attachments.py` with `invoice_attachments` table: id (UUID PK), invoice_id (UUID FK → invoices ON DELETE CASCADE), org_id (UUID FK → organisations), file_key (VARCHAR 500), file_name (VARCHAR 255), file_size (INTEGER), mime_type (VARCHAR 100), uploaded_by (UUID FK → users, nullable), sort_order (INTEGER DEFAULT 0), created_at (TIMESTAMPTZ DEFAULT now()). Use IF NOT EXISTS for idempotency.
- [ ] 1.2 Add index `ix_invoice_attachments_invoice_org` on (invoice_id, org_id)
- [ ] 1.3 Create `app/modules/invoices/attachment_models.py` with `InvoiceAttachment` SQLAlchemy model mirroring the migration columns, with relationships to Invoice, Organisation, and User
- [ ] 1.4 Run migration on local dev: `docker compose exec app alembic upgrade head`
- [ ] 1.5 Verify migration applied: confirm table exists with correct columns

**Validates**: Req 1.1, 1.2, 1.4

## Task 2: Attachment service layer
- [ ] 2.1 Create `app/modules/invoices/attachment_service.py` with constants: `ATTACHMENT_CATEGORY = "invoice-attachments"`, `MAX_FILE_SIZE = 20 * 1024 * 1024`, `MAX_ATTACHMENTS_PER_INVOICE = 5`, `ALLOWED_MIME_TYPES` (jpeg, png, webp, gif, pdf)
- [ ] 2.2 Implement `_store_file(content, filename, org_id, mime_type)` — compress images (resize to max 2048px, JPEG quality 82) or zlib-compress PDFs, envelope-encrypt, write to `/app/uploads/invoice-attachments/{org_id}/{hash}.ext`, return (file_key, file_size). Copy pattern from `app/modules/job_cards/attachment_service.py`.
- [ ] 2.3 Implement `_read_file(file_key)` — read from disk, decrypt, decompress, return original bytes. Validate path stays within UPLOAD_BASE.
- [ ] 2.4 Implement `_delete_file(file_key)` — delete from disk with path traversal validation
- [ ] 2.5 Implement `upload_attachment(db, org_id, user_id, invoice_id, content, filename, mime_type)` — validate MIME type and size, check invoice exists and belongs to org, enforce max 5 attachments per invoice, call `_store_file`, enforce storage quota via `StorageManager`, create `InvoiceAttachment` row, increment storage usage, return metadata dict
- [ ] 2.6 Implement `list_attachments(db, org_id, invoice_id)` — query with LEFT JOIN to users for uploader name, order by sort_order then created_at, return list of dicts
- [ ] 2.7 Implement `get_attachment(db, org_id, invoice_id, attachment_id)` — return single attachment metadata or raise ValueError
- [ ] 2.8 Implement `download_attachment(org_id, file_key)` — validate file_key starts with `invoice-attachments/{org_id}/`, call `_read_file`
- [ ] 2.9 Implement `delete_attachment(db, org_id, user_id, invoice_id, attachment_id)` — get record, delete file from disk, delete DB row, decrement storage usage
- [ ] 2.10 Implement `get_attachment_count(db, org_id, invoice_id)` — return COUNT(*) for the invoice

**Validates**: Req 2.1–2.9, 3.1–3.5, 4.1–4.5, 5.1–5.4, 10.1–10.5

## Task 3: Attachment API router
- [ ] 3.1 Create `app/modules/invoices/attachment_router.py` with 4 endpoints: POST upload, GET list, GET download, DELETE
- [ ] 3.2 POST `/{invoice_id}/attachments` — read file content, validate size (20MB) and MIME type, call `upload_attachment`, return 201 with metadata. Handle 507 for quota exceeded.
- [ ] 3.3 GET `/{invoice_id}/attachments` — call `list_attachments`, return `{ attachments: [...], total: N }`
- [ ] 3.4 GET `/{invoice_id}/attachments/{attachment_id}` — call `get_attachment` for metadata, call `download_attachment` for content, return Response with correct Content-Type and Content-Disposition (inline for images/PDFs)
- [ ] 3.5 DELETE `/{invoice_id}/attachments/{attachment_id}` — check invoice status is draft (403 if issued/paid), call `delete_attachment`, return result
- [ ] 3.6 All endpoints require `org_admin` or `salesperson` role
- [ ] 3.7 Register router in `app/main.py` under `prefix="/api/v1/invoices"` with tag `"invoice-attachments"`

**Validates**: Req 2.1–2.9, 3.1–3.5, 4.1–4.5, 5.1–5.4

## Task 4: Include attachments in invoice email
- [ ] 4.1 In `app/modules/invoices/service.py` `email_invoice()`, after generating the PDF, call `list_attachments` to get all attachments for the invoice
- [ ] 4.2 For each attachment, call `download_attachment` to get decrypted bytes. Wrap in try/except — log warning and skip on failure.
- [ ] 4.3 Track cumulative email size (PDF + attachments). Stop adding attachments when total would exceed 25 MB.
- [ ] 4.4 Attach each loaded file to the MIME message using `MIMEApplication` with original filename and MIME type
- [ ] 4.5 If any attachments were skipped due to size limit, append a note to the email body text

**Validates**: Req 6.1–6.5

## Task 5: Add attachment_count to invoice responses
- [ ] 5.1 In `app/modules/invoices/service.py` `get_invoice()`, query `COUNT(*)` from `invoice_attachments` for the invoice and add `attachment_count` to the result dict
- [ ] 5.2 In `app/modules/invoices/service.py` `list_invoices()` (or equivalent search function), add `attachment_count` via a subquery or batch query for each invoice in the page
- [ ] 5.3 Add `attachment_count: int = 0` to `InvoiceResponse` in `app/modules/invoices/schemas.py`
- [ ] 5.4 Add `attachment_count: int = 0` to `InvoiceSearchResult` in `app/modules/invoices/schemas.py`

**Validates**: Req 8.5, 9.2

## Task 6: Frontend — upload attachments after invoice save
- [ ] 6.1 In `InvoiceCreate.tsx`, create `uploadAttachments(invoiceId: string)` function that uploads each file in `attachments` state sequentially via `POST /invoices/{id}/attachments` with FormData. Log warnings on failure but don't block navigation.
- [ ] 6.2 Call `uploadAttachments` in `handleSaveDraft` after the invoice is created/updated and before `navigate()`
- [ ] 6.3 Call `uploadAttachments` in `handleSaveAndSend` after the invoice is created/updated and before `navigate()`
- [ ] 6.4 Call `uploadAttachments` in `handleMarkPaidAndEmail` after the invoice is created and before the issue/payment steps
- [ ] 6.5 Add a `uploading` state to show "Uploading attachments..." text while uploads are in progress
- [ ] 6.6 Clear `attachments` state after all uploads complete

**Validates**: Req 7.1–7.5

## Task 7: Frontend — load existing attachments in edit mode
- [ ] 7.1 In `InvoiceCreate.tsx`, add `existingAttachments` state (array of attachment metadata from API)
- [ ] 7.2 When `editId` is set, fetch `GET /invoices/{editId}/attachments` on mount with AbortController cleanup
- [ ] 7.3 Display existing attachments above the file picker: filename, size, delete button (draft only)
- [ ] 7.4 Delete button calls `DELETE /invoices/{editId}/attachments/{id}` and removes from `existingAttachments` state
- [ ] 7.5 New files added via the file picker are uploaded on save (same as Task 6)

**Validates**: Req 7.6

## Task 8: Frontend — AttachmentList component for invoice detail
- [ ] 8.1 Create `frontend/src/components/invoices/AttachmentList.tsx` — accepts `invoiceId` and `isDraft` props
- [ ] 8.2 Fetch `GET /invoices/{invoiceId}/attachments` on mount with AbortController cleanup. Use `res.data?.attachments ?? []`.
- [ ] 8.3 Render each attachment as a row: file type icon (image/PDF), filename (clickable), formatted file size, upload date
- [ ] 8.4 Click on filename opens `GET /invoices/{invoiceId}/attachments/{id}` in a new tab
- [ ] 8.5 Show delete button (trash icon) only when `isDraft` is true. On click, call DELETE endpoint and remove from local state.
- [ ] 8.6 Show empty state "No attachments" when list is empty (don't render the section at all if count is 0)

**Validates**: Req 8.1–8.4

## Task 9: Frontend — integrate AttachmentList into InvoiceList detail panel
- [ ] 9.1 In `InvoiceList.tsx`, import `AttachmentList` component
- [ ] 9.2 Render `<AttachmentList>` below the invoice preview card when `(invoice?.attachment_count ?? 0) > 0`
- [ ] 9.3 Pass `isDraft={invoice?.status === 'draft'}` to control delete visibility
- [ ] 9.4 In the left sidebar invoice list items, show `📎 {attachment_count}` badge when `attachment_count > 0`

**Validates**: Req 8.1, 8.5, 9.2

## Task 10: Build, verify, and push
- [ ] 10.1 Run `docker compose exec app alembic upgrade head` to apply migration on dev
- [ ] 10.2 Rebuild frontend: `docker compose exec frontend sh -c "cd /app && npx vite build"`
- [ ] 10.3 Verify no TypeScript diagnostics on changed files
- [ ] 10.4 Test manually: create invoice → attach 2 files → save as draft → verify files appear in detail → edit invoice → verify existing attachments load → delete one → save and send → verify email has PDF + remaining attachment
- [ ] 10.5 Git commit and push all changes
