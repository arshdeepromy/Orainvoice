# Invoice Attachments — Requirements

## Overview

Users can attach files (images, PDFs, documents) to invoices during creation or editing. Attached files are stored securely, included as additional pages/attachments in emailed invoice PDFs, and viewable in the invoice detail preview. The feature follows the same encrypted storage pattern as job card attachments.

## Current State

- The "Attach File(s) to Invoice" UI exists in `InvoiceCreate.tsx` — file picker, file list with remove buttons, 5-file / 5MB-per-file limits displayed
- The `attachments` state holds `File[]` objects in the frontend
- **No backend infrastructure exists**: no database table, no upload endpoint, no storage, no email inclusion, no preview display
- The `buildPayload()` function does not include attachments — files are never sent to the server
- The `email_invoice()` function only attaches the generated PDF — no user-uploaded files
- The invoice detail view has no display of attached files

## Reference Implementation

The job card attachment system (`app/modules/job_cards/attachment_router.py`, `attachment_service.py`) provides the pattern to follow:
- Files stored on disk using the existing encrypted upload system (`app/modules/uploads/router.py`)
- Metadata stored in a database table (`job_card_attachments`) with org_id, file_key, file_name, mime_type, file_size, uploaded_by
- Storage quota enforcement via `StorageManager`
- Compression + encryption at rest

---

## Requirements

### Req 1: Database — `invoice_attachments` table

- 1.1: Create an `invoice_attachments` table with columns: `id` (UUID PK), `invoice_id` (UUID FK → invoices), `org_id` (UUID FK → organisations), `file_key` (VARCHAR — path in upload directory), `file_name` (VARCHAR — original filename), `mime_type` (VARCHAR), `file_size` (INTEGER — bytes on disk after compression/encryption), `uploaded_by` (UUID FK → users, nullable), `created_at` (TIMESTAMPTZ), `sort_order` (INTEGER, default 0)
- 1.2: Add index on `(invoice_id, org_id)` for fast lookups
- 1.3: Add RLS policy matching the existing pattern (org_id = current_setting('app.current_org_id'))
- 1.4: Migration must be idempotent (use IF NOT EXISTS)

### Req 2: Backend — Upload endpoint

- 2.1: `POST /api/v1/invoices/{invoice_id}/attachments` — upload a single file attachment
- 2.2: Accept `UploadFile` (multipart/form-data), max 20 MB per file (compressed on disk via existing upload system — images resized + optimized, PDFs zlib-compressed)
- 2.3: Allowed MIME types: `image/jpeg`, `image/png`, `image/webp`, `image/gif`, `application/pdf`
- 2.4: Store file using the existing encrypted upload system (compress + encrypt, same as `app/modules/uploads/router.py`)
- 2.5: Create `invoice_attachments` row with metadata
- 2.6: Enforce storage quota via `StorageManager` — return 507 if exceeded
- 2.7: Enforce max 5 attachments per invoice — return 400 if exceeded
- 2.8: Require `org_admin` or `salesperson` role
- 2.9: Return `{ id, file_name, mime_type, file_size, created_at }`

### Req 3: Backend — List endpoint

- 3.1: `GET /api/v1/invoices/{invoice_id}/attachments` — list all attachments for an invoice
- 3.2: Return `{ attachments: [...], total: N }` (standard wrapped response)
- 3.3: Each attachment includes: `id`, `file_name`, `mime_type`, `file_size`, `created_at`, `uploaded_by_name`
- 3.4: Ordered by `sort_order` then `created_at`
- 3.5: Require `org_admin` or `salesperson` role

### Req 4: Backend — Download endpoint

- 4.1: `GET /api/v1/invoices/{invoice_id}/attachments/{attachment_id}` — download/view a specific attachment
- 4.2: Decrypt and decompress the file, return with correct `Content-Type` header
- 4.3: Use `Content-Disposition: inline` for images/PDFs (browser preview), `attachment` for others
- 4.4: Validate org_id ownership — return 403 if the attachment belongs to a different org
- 4.5: Require `org_admin` or `salesperson` role

### Req 5: Backend — Delete endpoint

- 5.1: `DELETE /api/v1/invoices/{invoice_id}/attachments/{attachment_id}` — delete an attachment
- 5.2: Remove file from disk, delete DB row, decrement storage usage
- 5.3: Only allow deletion on draft invoices — return 403 for issued/paid invoices
- 5.4: Require `org_admin` or `salesperson` role

### Req 6: Backend — Email inclusion

- 6.1: When `email_invoice()` sends the invoice email, include all invoice attachments as additional email attachments (alongside the generated PDF)
- 6.2: Each attachment uses its original filename and MIME type
- 6.3: Decrypt and decompress files before attaching to the email
- 6.4: If an attachment fails to load (file missing on disk), log a warning and skip it — don't fail the entire email
- 6.5: Total email size (PDF + attachments) should not exceed 25 MB — if it would, skip attachments and add a note in the email body: "Attachments are available in the invoice portal"

### Req 7: Frontend — Upload during invoice creation

- 7.1: When the user clicks "Save as Draft", "Save and Send", or "Mark Paid & Email", upload all selected files to the server AFTER the invoice is created (need the invoice_id first)
- 7.2: Upload files sequentially (not in parallel) to avoid overwhelming the server
- 7.3: Show upload progress or at minimum a "Uploading attachments..." indicator
- 7.4: If any upload fails, show a warning but don't fail the entire save — the invoice is already created
- 7.5: Clear the `attachments` state after successful upload
- 7.6: On edit mode, load existing attachments from the API and display them alongside any new files the user adds

### Req 8: Frontend — Display in invoice detail

- 8.1: Show an "Attachments" section in the invoice detail view (InvoiceList right panel) below the invoice preview
- 8.2: Display each attachment as a clickable row with: file icon (based on MIME type), filename, file size, upload date
- 8.3: Clicking an attachment opens it in a new tab (images/PDFs) or downloads it (other types)
- 8.4: For draft invoices, show a delete button (trash icon) on each attachment
- 8.5: Show attachment count badge on the invoice list item if attachments > 0

### Req 9: Frontend — Display in invoice preview card

- 9.1: If the invoice has image attachments, show thumbnail previews below the invoice preview card
- 9.2: If the invoice has PDF attachments, show a "📎 N attachments" indicator
- 9.3: Clicking a thumbnail opens the full-size image in a new tab

### Req 10: Security & Storage

- 10.1: Files are encrypted at rest using the existing envelope encryption system
- 10.2: File access is org-scoped — RLS prevents cross-org access
- 10.3: File names are sanitized (no path traversal)
- 10.4: MIME type is validated against the allowlist (not just the file extension)
- 10.5: Storage quota is enforced per-org

---

## Out of Scope

- Drag-and-drop upload (use the existing file picker)
- Image editing/cropping
- Attachment reordering UI (sort_order is for future use)
- Attaching files to quotes (separate feature)
- Inline display of attachments within the PDF invoice itself (they're email attachments, not embedded pages)

## Acceptance Criteria

- [ ] User can upload up to 5 files (20MB each) when creating or editing an invoice
- [ ] Uploaded files appear in the invoice detail view with download/preview capability
- [ ] Emailed invoices include the uploaded files as additional email attachments
- [ ] Files are encrypted at rest and org-scoped
- [ ] Storage quota is enforced
- [ ] Deleting an attachment on a draft invoice works; deletion is blocked on issued/paid invoices
- [ ] Existing invoice creation/editing flow is not broken
