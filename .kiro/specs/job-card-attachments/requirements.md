# Requirements: Job Card Attachments & Optional Line Items

## Overview

Two enhancements to the Job Card Create/Edit experience:
1. Make line items optional and collapsible (hidden by default, shown on "Add Line Item" click)
2. Allow users to attach photos (images) and PDFs to job cards for documentation purposes

## Definitions

- **Job_Card_Attachment**: A file (image or PDF) linked to a job card, stored encrypted on the local filesystem with compression applied.
- **Attachment_Upload_Endpoint**: The existing `/api/v1/uploads/attachments` endpoint that handles file upload, compression, encryption, and storage quota enforcement.
- **Storage_Manager**: The existing service that tracks storage usage per organisation and enforces quotas.

## Functional Requirements

### Requirement 1: Optional Line Items Section

1. WHEN the Job Card Create form loads, THE Line Items section SHALL be hidden by default.
2. THE form SHALL display an "Add Line Item" button in place of the line items table.
3. WHEN the user clicks "Add Line Item", THE Line Items section SHALL expand to show the table with one empty row.
4. THE user SHALL be able to collapse the Line Items section by clicking a collapse/hide button.
5. IF the Line Items section has items with descriptions, THE collapse button SHALL warn the user that data will be preserved but hidden.
6. THE job card SHALL be saveable without any line items (line items are optional).

### Requirement 2: Job Card Attachments - File Types

1. THE system SHALL accept only the following file types for job card attachments:
   - Images: JPEG (.jpg, .jpeg), PNG (.png), WebP (.webp), GIF (.gif)
   - Documents: PDF (.pdf)
2. THE system SHALL reject video files and all other file types not listed above.
3. THE system SHALL display a clear error message when an unsupported file type is uploaded.

### Requirement 3: Job Card Attachments - File Size

1. THE maximum file size for a single attachment SHALL be 50 MB.
2. THE system SHALL reject files exceeding 50 MB with a clear error message.
3. THE system SHALL display the file size limit to users in the upload UI.

### Requirement 4: Job Card Attachments - Compression

1. Image files SHALL be compressed using the existing image compression logic:
   - Resize to max 2048px on longest edge
   - Convert to JPEG at 82% quality (except PNG which stays PNG with optimization)
2. PDF files SHALL be compressed using zlib compression.
3. All files SHALL be encrypted at rest using envelope encryption (existing pattern).

### Requirement 5: Job Card Attachments - Storage Quota

1. THE system SHALL check the organisation's storage quota before accepting an upload.
2. IF the upload would exceed the organisation's storage quota, THE system SHALL reject the upload with a clear error message.
3. THE system SHALL increment the organisation's storage usage after successful upload.
4. THE storage usage SHALL be decremented when attachments are deleted.

### Requirement 6: Job Card Attachments - Database Model

1. A new `job_card_attachments` table SHALL store attachment metadata:
   - `id` (UUID, primary key)
   - `job_card_id` (UUID, FK to job_cards.id, ON DELETE CASCADE)
   - `org_id` (UUID, FK to organisations.id)
   - `file_key` (VARCHAR 500) - path to encrypted file on disk
   - `file_name` (VARCHAR 255) - original filename
   - `file_size` (INTEGER) - size in bytes after compression/encryption
   - `mime_type` (VARCHAR 100) - e.g., "image/jpeg", "application/pdf"
   - `uploaded_by` (UUID, FK to users.id)
   - `uploaded_at` (TIMESTAMP WITH TIME ZONE)
2. THE table SHALL have RLS enabled matching `app.current_org_id`.

### Requirement 7: Job Card Attachments - API Endpoints

1. `POST /api/v1/job-cards/{job_card_id}/attachments` SHALL upload a file and create an attachment record.
2. `GET /api/v1/job-cards/{job_card_id}/attachments` SHALL list all attachments for a job card.
3. `GET /api/v1/job-cards/{job_card_id}/attachments/{attachment_id}` SHALL download/view a specific attachment.
4. `DELETE /api/v1/job-cards/{job_card_id}/attachments/{attachment_id}` SHALL delete an attachment and decrement storage usage.
5. All endpoints SHALL require authentication and org context.
6. All endpoints SHALL verify the job card belongs to the user's organisation.

### Requirement 8: Job Card Attachments - Frontend UI

1. THE Job Card Create form SHALL include an "Attachments" section below the Notes field.
2. THE Attachments section SHALL display:
   - A file drop zone with "Drag & drop files or click to browse" text
   - Accepted file types hint: "Images (JPEG, PNG, WebP, GIF) and PDFs up to 50MB"
   - List of uploaded attachments with thumbnail (for images) or PDF icon
3. EACH attachment in the list SHALL show:
   - Thumbnail or file type icon
   - Original filename
   - File size
   - Remove button (trash icon)
4. THE user SHALL be able to click an attachment to preview/download it.
5. Upload progress SHALL be shown during file upload.

### Requirement 9: Job Card Detail View

1. THE Job Card Detail page SHALL display all attachments in a gallery/list view.
2. Images SHALL be viewable in a lightbox/modal when clicked.
3. PDFs SHALL open in a new tab or download when clicked.
4. THE detail view SHALL show attachment metadata (filename, size, upload date, uploaded by).

## Non-Functional Requirements

### Performance

1. Image compression SHALL complete within 5 seconds for files up to 50MB.
2. The attachments list SHALL load within 1 second for job cards with up to 20 attachments.

### Security

1. All files SHALL be encrypted at rest using envelope encryption.
2. File access SHALL be restricted to users within the same organisation.
3. File paths SHALL be validated to prevent directory traversal attacks.

## Out of Scope

- Video file support
- Bulk upload of multiple files simultaneously (can be added later)
- Image editing/cropping before upload
- OCR or text extraction from PDFs
- Attachment versioning
