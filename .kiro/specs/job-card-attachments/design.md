# Design: Job Card Attachments & Optional Line Items

## Architecture Overview

```mermaid
graph TD
    subgraph Frontend
        JCC[JobCardCreate.tsx]
        JCD[JobCardDetail.tsx]
        AU[AttachmentUploader component]
        AG[AttachmentGallery component]
    end
    
    subgraph Backend
        JCR[job_cards/router.py]
        JCA[job_cards/attachments.py]
        UR[uploads/router.py]
        SM[StorageManager]
    end
    
    subgraph Storage
        FS[Local Filesystem /app/uploads/job-card-attachments/]
        DB[(PostgreSQL job_card_attachments)]
    end
    
    JCC --> AU
    JCD --> AG
    AU -->|POST /job-cards/{id}/attachments| JCA
    AG -->|GET /job-cards/{id}/attachments| JCA
    JCA --> UR
    JCA --> SM
    UR --> FS
    JCA --> DB
    SM --> DB
```

## Database Schema

### New Table: job_card_attachments

```sql
CREATE TABLE job_card_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_card_id UUID NOT NULL REFERENCES job_cards(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organisations(id),
    file_key VARCHAR(500) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_size INTEGER NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    uploaded_by UUID NOT NULL REFERENCES users(id),
    uploaded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    CONSTRAINT fk_job_card_attachments_job_card 
        FOREIGN KEY (job_card_id) REFERENCES job_cards(id) ON DELETE CASCADE
);

CREATE INDEX ix_job_card_attachments_job_card_id ON job_card_attachments(job_card_id);
CREATE INDEX ix_job_card_attachments_org_id ON job_card_attachments(org_id);

-- RLS
ALTER TABLE job_card_attachments ENABLE ROW LEVEL SECURITY;

CREATE POLICY job_card_attachments_org_isolation ON job_card_attachments
    USING (org_id = current_setting('app.current_org_id', true)::uuid);
```

## API Design

### POST /api/v1/job-cards/{job_card_id}/attachments

Upload a file attachment to a job card.

**Request:**
- Content-Type: multipart/form-data
- Body: `file` (UploadFile)

**Response (201):**
```json
{
  "id": "uuid",
  "job_card_id": "uuid",
  "file_key": "job-card-attachments/{org_id}/{uuid}.jpg",
  "file_name": "photo1.jpg",
  "file_size": 123456,
  "mime_type": "image/jpeg",
  "uploaded_by": "uuid",
  "uploaded_at": "2026-04-27T15:00:00Z"
}
```

**Errors:**
- 400: Empty file or invalid file type
- 413: File too large (>50MB)
- 403: Organisation context required or job card not found
- 507: Storage quota exceeded

### GET /api/v1/job-cards/{job_card_id}/attachments

List all attachments for a job card.

**Response (200):**
```json
{
  "attachments": [
    {
      "id": "uuid",
      "file_name": "photo1.jpg",
      "file_size": 123456,
      "mime_type": "image/jpeg",
      "uploaded_by": "uuid",
      "uploaded_by_name": "John Doe",
      "uploaded_at": "2026-04-27T15:00:00Z",
      "thumbnail_url": "/api/v1/job-cards/{id}/attachments/{id}/thumbnail"
    }
  ],
  "total": 1
}
```

### GET /api/v1/job-cards/{job_card_id}/attachments/{attachment_id}

Download/view a specific attachment.

**Response:** Binary file content with appropriate Content-Type header.

### GET /api/v1/job-cards/{job_card_id}/attachments/{attachment_id}/thumbnail

Get a thumbnail for image attachments (for gallery view).

**Response:** Resized image (max 200x200) or 404 for non-image files.

### DELETE /api/v1/job-cards/{job_card_id}/attachments/{attachment_id}

Delete an attachment.

**Response (200):**
```json
{
  "message": "Attachment deleted",
  "storage_freed_bytes": 123456
}
```

## File Storage Structure

```
/app/uploads/
└── job-card-attachments/
    └── {org_id}/
        └── {uuid}.{ext}
```

Files are stored with:
1. Compression flag byte (0x01 for zlib, 0x02 for image)
2. Envelope-encrypted content

## Frontend Components

### AttachmentUploader

A reusable component for uploading files with drag-and-drop support.

```tsx
interface AttachmentUploaderProps {
  jobCardId: string
  onUploadComplete: (attachment: Attachment) => void
  onError: (error: string) => void
  maxSizeMB?: number  // default 50
  acceptedTypes?: string[]  // default images + PDF
}
```

Features:
- Drag and drop zone
- File type validation (client-side)
- File size validation (client-side)
- Upload progress indicator
- Error display

### AttachmentGallery

A component for displaying and managing attachments.

```tsx
interface AttachmentGalleryProps {
  attachments: Attachment[]
  onDelete?: (id: string) => void
  readOnly?: boolean
}
```

Features:
- Grid layout with thumbnails
- Image lightbox on click
- PDF opens in new tab
- Delete button (when not readOnly)
- File metadata display

## Line Items Collapsible Section

### State Management

```tsx
const [showLineItems, setShowLineItems] = useState(false)
const [lineItems, setLineItems] = useState<LineItem[]>([])

// Show section when user clicks "Add Line Item"
const handleAddLineItem = () => {
  setShowLineItems(true)
  if (lineItems.length === 0) {
    setLineItems([newLineItem()])
  }
}
```

### UI Structure

```tsx
{/* Line Items Section */}
{!showLineItems ? (
  <Button variant="secondary" onClick={handleAddLineItem}>
    + Add Line Item
  </Button>
) : (
  <section>
    <div className="flex items-center justify-between">
      <h2>Line Items</h2>
      <Button variant="ghost" size="sm" onClick={() => setShowLineItems(false)}>
        Hide
      </Button>
    </div>
    {/* Line items table */}
  </section>
)}
```

## Validation Changes

Current validation requires at least one line item. This needs to change:

```tsx
// OLD
const validate = (): boolean => {
  const filledItems = lineItems.filter((li) => li.description.trim())
  if (filledItems.length === 0) errs.items = 'Add at least one line item'
  // ...
}

// NEW
const validate = (): boolean => {
  // Line items are optional - no validation required
  // Only validate if items exist and have incomplete data
  const filledItems = lineItems.filter((li) => li.description.trim())
  // No error if empty - line items are optional
  // ...
}
```

## Storage Quota Integration

The existing `StorageManager` class handles quota enforcement:

```python
from app.core.storage_manager import StorageManager

sm = StorageManager(db)
await sm.enforce_quota(org_id, file_size)  # Raises if quota exceeded
await sm.increment_usage(org_id, file_size)  # After successful upload
await sm.decrement_usage(org_id, file_size)  # After deletion
```

## Security Considerations

1. **File Type Validation**: Validate both by extension AND by reading file magic bytes
2. **Path Traversal**: Use UUID-based filenames, never user-provided paths
3. **Org Isolation**: RLS + explicit org_id checks in all queries
4. **Encryption**: All files encrypted at rest using envelope encryption

## Migration Strategy

1. Create `job_card_attachments` table with RLS
2. Add attachment endpoints to job_cards router
3. Update frontend JobCardCreate with collapsible line items
4. Add AttachmentUploader to JobCardCreate
5. Add AttachmentGallery to JobCardDetail
