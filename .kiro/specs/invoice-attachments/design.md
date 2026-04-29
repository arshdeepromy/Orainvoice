# Invoice Attachments — Design Document

## Architecture Overview

Invoice attachments follow the same pattern as job card attachments: file bytes stored on the `app_uploads` Docker volume (compressed + encrypted), metadata in a PostgreSQL table, org-scoped via RLS. The implementation reuses the existing `_store_file` / `_read_file` / `_delete_file` helpers from the job card attachment service.

```
┌─────────────────┐     POST /invoices/{id}/attachments     ┌──────────────┐
│  InvoiceCreate   │ ──────────────────────────────────────► │  Backend     │
│  (frontend)      │     multipart/form-data (file)          │  Router      │
└─────────────────┘                                          └──────┬───────┘
                                                                    │
                                                    ┌───────────────┼───────────────┐
                                                    ▼               ▼               ▼
                                              Validate        Compress +       Create DB row
                                              (MIME, size)    Encrypt → Disk   (invoice_attachments)
                                                              /app/uploads/    Enforce quota
```

---

## Database Design

### Migration 0170: `invoice_attachments` table

```sql
CREATE TABLE IF NOT EXISTS invoice_attachments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id      UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    org_id          UUID NOT NULL REFERENCES organisations(id),
    file_key        VARCHAR(500) NOT NULL,   -- path on disk: invoice-attachments/{org_id}/{hash}.ext
    file_name       VARCHAR(255) NOT NULL,   -- original filename
    file_size       INTEGER NOT NULL,        -- bytes on disk (after compression + encryption)
    mime_type       VARCHAR(100) NOT NULL,
    uploaded_by     UUID REFERENCES users(id),
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_invoice_attachments_invoice_org
    ON invoice_attachments (invoice_id, org_id);
```

RLS policy follows the standard pattern — `org_id = current_setting('app.current_org_id')::uuid`.

### Model: `InvoiceAttachment`

Located in `app/modules/invoices/attachment_models.py`. Mirrors `JobCardAttachment` structure with `invoice_id` FK instead of `job_card_id`.

---

## Backend API Design

### New file: `app/modules/invoices/attachment_service.py`

Replicates the job card attachment service pattern with these constants:

| Constant | Value | Notes |
|----------|-------|-------|
| `ATTACHMENT_CATEGORY` | `"invoice-attachments"` | Disk subdirectory under `/app/uploads/` |
| `MAX_FILE_SIZE` | `20 * 1024 * 1024` (20 MB) | Per-file limit |
| `MAX_ATTACHMENTS_PER_INVOICE` | `5` | Enforced on upload |
| `ALLOWED_MIME_TYPES` | `image/jpeg, image/png, image/webp, image/gif, application/pdf` | Same as job card |

Functions (all async, org-scoped):

| Function | Description |
|----------|-------------|
| `upload_attachment(db, org_id, user_id, invoice_id, content, filename, mime_type)` | Validate → compress → encrypt → store on disk → create DB row → enforce quota |
| `list_attachments(db, org_id, invoice_id)` | Return list of attachment metadata with uploader name, ordered by sort_order then created_at |
| `get_attachment(db, org_id, invoice_id, attachment_id)` | Return single attachment metadata |
| `download_attachment(org_id, file_key)` | Read + decrypt + decompress from disk, validate org ownership |
| `delete_attachment(db, org_id, user_id, invoice_id, attachment_id)` | Delete file from disk + DB row + decrement storage |
| `get_attachment_count(db, org_id, invoice_id)` | Return count (for list badge) |

Storage helpers (`_store_file`, `_read_file`, `_delete_file`) are copied from the job card service. A future refactor could extract these into a shared `app/core/file_storage.py`, but for now keeping them local avoids touching the working job card code.

### New file: `app/modules/invoices/attachment_router.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/{invoice_id}/attachments` | org_admin, salesperson | Upload single file |
| `GET` | `/{invoice_id}/attachments` | org_admin, salesperson | List attachments |
| `GET` | `/{invoice_id}/attachments/{attachment_id}` | org_admin, salesperson | Download/view file |
| `DELETE` | `/{invoice_id}/attachments/{attachment_id}` | org_admin, salesperson | Delete (draft only) |

Router is registered in `app/main.py` under the existing invoices prefix:
```python
from app.modules.invoices.attachment_router import router as invoice_attachment_router
app.include_router(invoice_attachment_router, prefix="/api/v1/invoices", tags=["invoice-attachments"])
```

### Modification: `app/modules/invoices/service.py` — `email_invoice()`

After generating the PDF, before building the MIME message:

```python
# Load invoice attachments
from app.modules.invoices.attachment_service import list_attachments, download_attachment

attachments = await list_attachments(db, org_id=org_id, invoice_id=invoice_id)

# Calculate total email size
total_size = len(pdf_bytes)
attachment_data = []
for att in attachments:
    try:
        data = download_attachment(org_id, att["file_key"])
        total_size += len(data)
        if total_size <= 25 * 1024 * 1024:  # 25 MB email limit
            attachment_data.append((att["file_name"], att["mime_type"], data))
        else:
            break  # Stop adding attachments if email would exceed 25 MB
    except Exception:
        logger.warning("Failed to load attachment %s for invoice email, skipping", att["id"])

# Attach to MIME message (after the PDF attachment)
for fname, mtype, data in attachment_data:
    part = MIMEApplication(data, Name=fname)
    part.add_header("Content-Disposition", "attachment", filename=fname)
    msg.attach(part)
```

### Modification: `app/modules/invoices/service.py` — `get_invoice()`

Add `attachment_count` to the invoice detail response:

```python
from app.modules.invoices.attachment_service import get_attachment_count

count = await get_attachment_count(db, org_id=org_id, invoice_id=invoice_id)
result["attachment_count"] = count
```

### Modification: `app/modules/invoices/schemas.py`

Add to `InvoiceResponse`:
```python
attachment_count: int = 0
```

Add to `InvoiceSearchResult` (for list badge):
```python
attachment_count: int = 0
```

---

## Frontend Design

### InvoiceCreate.tsx — Upload flow

After the invoice is saved (POST or PUT returns the invoice ID), upload attachments sequentially:

```typescript
const uploadAttachments = async (invoiceId: string) => {
  for (const file of attachments) {
    try {
      const formData = new FormData()
      formData.append('file', file)
      await apiClient.post(`/invoices/${invoiceId}/attachments`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    } catch {
      // Log warning but don't fail the save — invoice is already created
      console.warn(`Failed to upload attachment: ${file.name}`)
    }
  }
  setAttachments([])
}
```

Called in `handleSaveDraft`, `handleSaveAndSend`, and `handleMarkPaidAndEmail` after the invoice is created/updated, before navigation.

### InvoiceCreate.tsx — Edit mode

When loading an existing invoice for editing, fetch existing attachments:

```typescript
useEffect(() => {
  if (!editId) return
  const controller = new AbortController()
  apiClient.get(`/invoices/${editId}/attachments`, { signal: controller.signal })
    .then(res => setExistingAttachments(res.data?.attachments ?? []))
    .catch(() => {})
  return () => controller.abort()
}, [editId])
```

Display existing attachments above the file picker with delete buttons (draft only).

### InvoiceList.tsx — Detail panel

Add an "Attachments" section below the invoice preview when `invoice.attachment_count > 0`:

```tsx
{(invoice.attachment_count ?? 0) > 0 && (
  <AttachmentList invoiceId={invoice.id} isDraft={invoice.status === 'draft'} />
)}
```

### New component: `AttachmentList.tsx`

Located in `frontend/src/components/invoices/AttachmentList.tsx`:

- Fetches `GET /invoices/{id}/attachments` on mount
- Renders each attachment as a row: file type icon, filename, size (formatted), date
- Click opens in new tab (images/PDFs) or downloads
- Delete button (trash icon) visible only for draft invoices
- Uses AbortController cleanup

### InvoiceList.tsx — List item badge

In the left sidebar invoice list, show a paperclip icon + count when `attachment_count > 0`:

```tsx
{item.attachment_count > 0 && (
  <span className="text-gray-400 text-xs">📎 {item.attachment_count}</span>
)}
```

---

## File Storage Layout

```
/app/uploads/
├── invoice-attachments/
│   ├── {org_id}/
│   │   ├── a1b2c3d4e5f6.jpg    (flag byte + encrypted compressed image)
│   │   ├── f7e8d9c0b1a2.pdf    (flag byte + encrypted zlib-compressed PDF)
│   │   └── ...
│   └── {other_org_id}/
│       └── ...
├── job-card-attachments/
│   └── ...
├── receipts/
│   └── ...
└── compliance/
    └── ...
```

Each file on disk: `[1-byte flag][envelope-encrypted payload]`
- Flag `\x01`: payload is zlib-compressed original
- Flag `\x02`: payload is processed image (resized + optimized)

---

## HA Replication Considerations

- The `invoice_attachments` table is a regular table — it will be included in the publication automatically (the entrypoint's `refresh_publication` step adds new tables after migrations)
- File bytes on the `app_uploads` volume are synced between HA nodes via the existing rsync volume sync
- No special handling needed — the existing HA infrastructure covers both DB metadata and file storage

---

## Security

- Files encrypted at rest via envelope encryption (same as all other uploads)
- Org-scoped access: `file_key` includes `org_id` in the path, validated on download
- RLS on the `invoice_attachments` table prevents cross-org queries
- MIME type validated against allowlist (not just file extension)
- Path traversal prevented by validating `file_key` resolves within `UPLOAD_BASE`
- Storage quota enforced per-org via `StorageManager`

---

## Email Size Management

The 25 MB email limit is enforced by accumulating attachment sizes:

1. Start with PDF size (~50-200 KB typically)
2. Add each attachment's decrypted size
3. Stop adding when cumulative total would exceed 25 MB
4. If any attachments were skipped, add a note to the email body

This is a soft limit — most invoices with 5 attachments (compressed images) will be well under 25 MB. The limit protects against edge cases like 5 × 20 MB raw PDFs.

---

## Files to Create

| File | Description |
|------|-------------|
| `alembic/versions/2026_04_29_2200-0170_create_invoice_attachments.py` | Migration |
| `app/modules/invoices/attachment_models.py` | SQLAlchemy model |
| `app/modules/invoices/attachment_service.py` | Service layer (store, list, download, delete) |
| `app/modules/invoices/attachment_router.py` | API endpoints |
| `frontend/src/components/invoices/AttachmentList.tsx` | Attachment display component |

## Files to Modify

| File | Change |
|------|--------|
| `app/main.py` | Register attachment router |
| `app/modules/invoices/service.py` | Add attachment_count to get_invoice(), include attachments in email_invoice() |
| `app/modules/invoices/schemas.py` | Add attachment_count to InvoiceResponse and InvoiceSearchResult |
| `frontend/src/pages/invoices/InvoiceCreate.tsx` | Upload attachments after save, load existing on edit |
| `frontend/src/pages/invoices/InvoiceList.tsx` | Show AttachmentList in detail panel, badge in list |
