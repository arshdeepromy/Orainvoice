# Implementation Tasks: Job Card Attachments & Optional Line Items

## Overview

Two features implemented incrementally:
1. Make line items optional and collapsible (quick UI change)
2. Job card attachments with file upload, compression, and storage quota integration

## Tasks

- [x] 1. Make Line Items section collapsible and optional
  - [x] 1.1 Modify `frontend/src/pages/job-cards/JobCardCreate.tsx`:
    - Add `showLineItems` state, default `false`
    - Replace the Line Items section with a conditional render:
      - When `showLineItems` is false: show "+ Add Line Item" button
      - When `showLineItems` is true: show the full line items table with a "Hide" button
    - Remove the validation that requires at least one line item
    - Ensure empty line items array is valid for form submission
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6_
  
  - [x] 1.2 Update backend validation in `app/modules/job_cards/service.py`:
    - Make `line_items` parameter optional (default to empty list) — ALREADY DONE
    - Allow job card creation with zero line items — ALREADY DONE
    - _Requirements: 1.6_

- [x] 2. Create database model and migration for job card attachments
  - [x] 2.1 Create `app/modules/job_cards/attachment_models.py`:
    - Define `JobCardAttachment` SQLAlchemy model with fields:
      - `id` (UUID PK)
      - `job_card_id` (UUID FK to job_cards.id, ON DELETE CASCADE)
      - `org_id` (UUID FK to organisations.id)
      - `file_key` (VARCHAR 500)
      - `file_name` (VARCHAR 255)
      - `file_size` (INTEGER)
      - `mime_type` (VARCHAR 100)
      - `uploaded_by` (UUID FK to users.id)
      - `uploaded_at` (TIMESTAMP WITH TIME ZONE)
    - Add relationship to JobCard model
    - _Requirements: 6.1, 6.2_
  
  - [x] 2.2 Create Alembic migration `alembic/versions/YYYY_MM_DD_HHMM-0162_add_job_card_attachments.py`:
    - CREATE TABLE `job_card_attachments` with all columns
    - CREATE INDEX on `job_card_id` and `org_id`
    - Enable RLS with policy matching `app.current_org_id`
    - _Requirements: 6.1, 6.2_

- [x] 3. Implement attachment service layer
  - [x] 3.1 Create `app/modules/job_cards/attachment_service.py`:
    - `upload_attachment(db, org_id, user_id, job_card_id, file_content, filename, mime_type)`:
      - Validate file type (images + PDF only)
      - Validate file size (max 50MB)
      - Validate job card exists and belongs to org
      - Use existing `_store()` logic from uploads router for compression/encryption
      - Check storage quota via StorageManager
      - Create JobCardAttachment record
      - Increment storage usage
      - Return attachment dict
    - `list_attachments(db, org_id, job_card_id)`:
      - Return list of attachments with uploader name
    - `get_attachment(db, org_id, job_card_id, attachment_id)`:
      - Return attachment record or raise ValueError
    - `download_attachment(org_id, file_key)`:
      - Read file from disk, decrypt, decompress
      - Return binary content
    - `delete_attachment(db, org_id, user_id, job_card_id, attachment_id)`:
      - Delete file from disk
      - Delete database record
      - Decrement storage usage
    - _Requirements: 2.1, 2.2, 3.1, 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 5.4_

- [x] 4. Implement attachment API endpoints
  - [x] 4.1 Create `app/modules/job_cards/attachment_router.py`:
    - `POST /job-cards/{job_card_id}/attachments`:
      - Accept multipart/form-data with `file` field
      - Validate file type and size
      - Call `upload_attachment()` service
      - Return 201 with attachment data
      - Handle 413 (too large), 400 (invalid type), 507 (quota exceeded)
    - `GET /job-cards/{job_card_id}/attachments`:
      - Return list of attachments
    - `GET /job-cards/{job_card_id}/attachments/{attachment_id}`:
      - Return file content with Content-Type header
    - `DELETE /job-cards/{job_card_id}/attachments/{attachment_id}`:
      - Delete attachment and return success message
    - All endpoints require org_admin or salesperson role
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_
  
  - [x] 4.2 Register attachment router in `app/main.py`:
    - Import and include the attachment router under `/api/v1/job-cards`
    - _Requirements: 7.1_

- [x] 5. Checkpoint — Backend verification
  - Run Alembic migration
  - Test attachment upload via curl/Postman
  - Verify storage quota enforcement
  - Verify file encryption and compression

- [x] 6. Create frontend AttachmentUploader component
  - [x] 6.1 Create `frontend/src/components/attachments/AttachmentUploader.tsx`:
    - Props: `jobCardId`, `onUploadComplete`, `onError`, `disabled`
    - Drag-and-drop zone with visual feedback
    - File input for click-to-browse
    - Client-side validation: file type (images + PDF), size (50MB max)
    - Upload progress indicator
    - Display accepted file types hint
    - Use AbortController for cleanup
    - _Requirements: 8.1, 8.2, 8.5_

  - [x] 6.2 Create `frontend/src/components/attachments/AttachmentList.tsx`:
    - Props: `attachments`, `onDelete`, `readOnly`
    - Display list of attachments with:
      - Thumbnail for images (or PDF icon)
      - Filename
      - File size (human-readable)
      - Delete button (if not readOnly)
    - Click to view/download
    - _Requirements: 8.3, 8.4_

- [x] 7. Integrate attachments into Job Card Create form
  - [x] 7.1 Modify `frontend/src/pages/job-cards/JobCardCreate.tsx`:
    - Add state for attachments list
    - Add AttachmentUploader component below Notes section
    - For new job cards: upload attachments after job card is created
    - Show AttachmentList for uploaded files
    - Handle upload errors gracefully
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

- [x] 8. Integrate attachments into Job Card Detail view
  - [x] 8.1 Modify `frontend/src/pages/job-cards/JobCardDetail.tsx`:
    - Fetch attachments on load
    - Display AttachmentList in read-only mode (or with delete for admins)
    - Add image lightbox for viewing images
    - PDFs open in new tab
    - Show upload date and uploader name
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [x] 9. Final checkpoint
  - Test full flow: create job card → upload attachments → view in detail
  - Test storage quota enforcement
  - Test file type rejection
  - Test file size rejection
  - Verify attachments are deleted when job card is deleted (CASCADE)

## Notes

- Use existing `_store()` and `_compress_image()` functions from `app/modules/uploads/router.py`
- Use existing `StorageManager` from `app/core/storage_manager.py` for quota enforcement
- File storage path: `/app/uploads/job-card-attachments/{org_id}/{uuid}.{ext}`
- All files are encrypted at rest using envelope encryption
- Maximum file size: 50MB
- Accepted types: JPEG, PNG, WebP, GIF, PDF
- Line items are now optional - job cards can be created without any line items
