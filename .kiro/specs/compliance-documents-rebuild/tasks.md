# Implementation Plan: Compliance Documents Rebuild

## Overview

Rebuild the Compliance Documents feature from its current skeleton (metadata-only CRUD, unstyled HTML, log-only expiry checks) into a production-ready module. Implementation proceeds backend-first (migrations → models → file storage → service → router → notifications), then frontend (components → wiring → badge), with checkpoints after each major phase.

The backend uses Python 3.11 / FastAPI / SQLAlchemy async / Alembic. The frontend uses React 18 / TypeScript / Vite / Tailwind CSS / Headless UI. The existing `compliance_docs` module and `ComplianceDashboard.tsx` page are extended — not replaced from scratch.

## Tasks

- [x] 1. Database migrations and new models
  - [x] 1.1 Create Alembic migration 0155 for `compliance_notification_log` table
    - Create `alembic/versions/0155_create_compliance_notification_log.py`
    - Use `IF NOT EXISTS` for idempotency per project convention
    - Table: `compliance_notification_log` with columns: `id` (UUID PK), `document_id` (UUID FK → compliance_documents ON DELETE CASCADE), `org_id` (UUID FK → organisations ON DELETE CASCADE), `threshold` (VARCHAR(10)), `sent_at` (TIMESTAMPTZ DEFAULT NOW())
    - Add unique constraint `uq_compliance_notif_doc_threshold` on `(document_id, threshold)`
    - Add indexes on `document_id` and `org_id`
    - _Requirements: 13.1, 13.3_

  - [x] 1.2 Create Alembic migration 0156 for `compliance_document_categories` table with seed data
    - Create `alembic/versions/0156_create_compliance_document_categories.py`
    - Table: `compliance_document_categories` with columns: `id` (UUID PK), `name` (VARCHAR(100)), `org_id` (UUID FK → organisations ON DELETE CASCADE, nullable), `is_predefined` (BOOLEAN DEFAULT FALSE), `created_at` (TIMESTAMPTZ DEFAULT NOW())
    - Add unique constraint `uq_compliance_cat_name_org` on `(name, org_id)`
    - Add index on `org_id`
    - Seed the 15 predefined categories from Requirement 6.1 with `org_id = NULL` and `is_predefined = TRUE`
    - _Requirements: 6.1, 6.4_

  - [x] 1.3 Add SQLAlchemy models for `ComplianceNotificationLog` and `ComplianceDocumentCategory`
    - Add both models to `app/modules/compliance_docs/models.py`
    - `ComplianceNotificationLog`: id, document_id, org_id, threshold, sent_at with UniqueConstraint
    - `ComplianceDocumentCategory`: id, name, org_id, is_predefined, created_at with UniqueConstraint
    - Follow existing mapped_column patterns from `ComplianceDocument`
    - _Requirements: 6.1, 13.1_

  - [x] 1.4 Add Docker volume mount for compliance file storage
    - Add `compliance_files:/app/compliance_files` volume to the `app` service in `docker-compose.yml`
    - Add the named volume `compliance_files` to the volumes section
    - Repeat for `docker-compose.pi.yml` if it overrides volumes
    - _Requirements: 3.6, 12.3_

- [x] 2. Backend file storage module
  - [x] 2.1 Create `app/modules/compliance_docs/file_storage.py` with `ComplianceFileStorage` class
    - Implement `save_file(org_id, file)` — validates file, writes to `compliance/{org_id}/{uuid}_{filename}`, returns file_key
    - Implement `read_file(file_key)` — returns async byte generator and content_type for streaming
    - Implement `delete_file(file_key)` — removes file from disk
    - Implement `_validate_mime_type(file)` — checks against Accepted_File_Types list
    - Implement `_validate_file_size(content, max_size=10_485_760)` — rejects files > 10MB
    - Implement `_validate_magic_bytes(content, declared_mime)` — validates file header bytes match declared MIME
    - Implement `_validate_filename(filename)` — rejects double extensions (e.g. `file.pdf.exe`)
    - Implement `_generate_storage_path(org_id, filename)` — UUID prefix, sanitised filename, no path traversal
    - Base path configurable, defaults to `/app/compliance_files`
    - _Requirements: 3.1, 3.2, 3.3, 3.6, 12.1, 12.2, 12.3, 12.4_

  - [x] 2.2 Write property test for MIME type validation
    - **Property 5: MIME type validation**
    - **Validates: Requirements 3.2, 3.4**

  - [x] 2.3 Write property test for file size validation
    - **Property 6: File size validation**
    - **Validates: Requirements 3.3, 3.5**

  - [x] 2.4 Write property test for storage path generation
    - **Property 7: Storage path generation**
    - **Validates: Requirements 3.6, 12.2**

  - [x] 2.5 Write property test for magic byte validation
    - **Property 13: Magic byte validation**
    - **Validates: Requirements 12.1, 12.5**

  - [x] 2.6 Write property test for double extension rejection
    - **Property 14: Double extension rejection**
    - **Validates: Requirements 12.4**

- [x] 3. Backend schemas and service layer enhancements
  - [x] 3.1 Update Pydantic schemas in `app/modules/compliance_docs/schemas.py`
    - Add `ComplianceDocumentUpdate` schema (document_type, description, expiry_date — all optional)
    - Add computed `status` field to `ComplianceDocumentResponse` (valid, expiring_soon, expired, no_expiry)
    - Update `ComplianceDashboard` → `ComplianceDashboardResponse` with `valid_documents` count
    - Add `CategoryResponse` schema (id, name, is_predefined)
    - Add `BadgeCountResponse` schema (count)
    - Add `CategoriesListResponse` schema (items: list[CategoryResponse], total: int)
    - Add `DocumentListResponse` schema (items: list[ComplianceDocumentResponse], total: int)
    - _Requirements: 2.6, 5.1, 6.6, 8.5, 10.6_

  - [x] 3.2 Enhance `ComplianceService` in `app/modules/compliance_docs/service.py`
    - Add `upload_document_with_file(org_id, file, metadata, uploaded_by)` — uses FileStorage, creates DB record, calls `db.refresh()` after flush
    - Add `update_document(org_id, doc_id, payload)` — validates org ownership (403), updates only provided fields
    - Add `delete_document(org_id, doc_id)` — validates org ownership (403), deletes DB record and file from storage
    - Add `list_documents_filtered(org_id, search, status, category, sort_by, sort_dir)` — server-side filtering, sorting, search
    - Add `get_badge_count(org_id)` — returns count of expired + expiring_soon documents
    - Add `get_categories(org_id)` — returns predefined categories + org-specific custom categories, predefined first
    - Add `create_custom_category(org_id, name)` — creates org-specific category, handles duplicate (409)
    - Add `get_document_for_download(org_id, doc_id)` — validates org ownership (403), returns document
    - Enhance existing `get_dashboard()` to include `valid_documents` count and computed status per document
    - All methods: `await db.refresh(obj)` after `db.flush()` before returning (MissingGreenlet prevention)
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 3.7, 4.2, 5.1, 5.2, 5.3, 6.4, 6.5, 6.6, 8.5_

  - [x] 3.3 Write property test for document status computation
    - **Property 1: Document status computation**
    - **Validates: Requirements 2.4, 2.6**

  - [x] 3.4 Write property test for badge count computation
    - **Property 12: Badge count computation**
    - **Validates: Requirements 8.1**

  - [x] 3.5 Write property test for preview eligibility
    - **Property 8: Preview eligibility**
    - **Validates: Requirements 4.6**

- [x] 4. Backend router endpoints
  - [x] 4.1 Add file upload endpoint `POST /upload` to `app/modules/compliance_docs/router.py`
    - Accept `UploadFile` + form fields (document_type, description, expiry_date, invoice_id, job_id, category_name)
    - Delegate to `ComplianceService.upload_document_with_file()`
    - Return 201 with `ComplianceDocumentResponse`
    - Return 400 for invalid MIME type, oversized file, magic byte mismatch, double extension
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 12.1, 12.4, 12.5_

  - [x] 4.2 Add file download endpoint `GET /{doc_id}/download`
    - Stream file from storage with correct `Content-Type` and `Content-Disposition: attachment` headers
    - Validate org ownership — return 403 if document belongs to another org
    - Return 404 if file missing from storage
    - _Requirements: 4.1, 4.2, 4.3, 12.6_

  - [x] 4.3 Add edit endpoint `PUT /{doc_id}` and delete endpoint `DELETE /{doc_id}`
    - PUT: accepts `ComplianceDocumentUpdate`, validates org ownership (403), returns updated `ComplianceDocumentResponse`
    - DELETE: validates org ownership (403), removes DB record + file, returns 204
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 4.4 Add categories endpoint `GET /categories` and badge-count endpoint `GET /badge-count`
    - Categories: returns `{ items: [...], total: N }` with predefined first, then org-specific custom
    - Badge-count: returns `{ count: N }` for expired + expiring-soon documents
    - _Requirements: 6.6, 8.5_

  - [x] 4.5 Enhance existing `GET /` list endpoint with query params
    - Add query parameters: `search` (str), `status` (str), `category` (str), `sort_by` (str), `sort_dir` (str)
    - Return wrapped response `{ items: [...], total: N }` per project convention
    - Enhance `GET /dashboard` to return `ComplianceDashboardResponse` with `valid_documents`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 4.6 Write unit tests for upload, download, edit, delete, categories, and badge-count endpoints
    - Test upload returns 201 with valid multipart file
    - Test upload returns 400 for invalid MIME, oversized file, magic byte mismatch
    - Test download streams file with correct headers
    - Test download returns 403 for cross-org access, 404 for missing file
    - Test edit updates only specified fields
    - Test delete removes record and file
    - Test categories returns predefined + custom with predefined first
    - Test badge-count returns 0 when no documents expiring
    - _Requirements: 3.4, 3.5, 4.2, 4.3, 5.3, 12.5_

- [x] 5. Checkpoint — Backend core complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Expiry notification service
  - [x] 6.1 Create `app/modules/compliance_docs/notification_service.py`
    - Implement `ComplianceNotificationService` class
    - `send_expiry_notifications(threshold_days)` — queries documents at exact threshold, checks dedup log, sends emails
    - `check_already_notified(doc_id, threshold)` — queries `compliance_notification_log` for existing entry
    - `log_notification(doc_id, org_id, threshold)` — inserts into `compliance_notification_log`
    - `_build_expiry_email(doc, threshold, dashboard_url)` — builds subject, HTML body, text body with doc type, file name, expiry date, dashboard link
    - Use existing `send_email_task` from `app/tasks/notifications.py` and `log_email_sent` from `app/modules/notifications/service.py`
    - Log failures with doc_id, org_id, error details — do NOT create notification log entry on failure (allows retry)
    - Wrap each document's notification in its own try/except for isolation
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 13.2_

  - [x] 6.2 Wire notification service into `check_compliance_expiry_task` in `app/tasks/scheduled.py`
    - Replace the current log-only implementation with calls to `ComplianceNotificationService`
    - Check 30-day, 7-day, and day-of thresholds
    - Maintain the existing task signature and return format
    - _Requirements: 7.7_

  - [x] 6.3 Write property test for notification threshold matching
    - **Property 9: Notification threshold matching**
    - **Validates: Requirements 7.1, 7.2, 7.3**

  - [x] 6.4 Write property test for expiry email template completeness
    - **Property 10: Expiry email template completeness**
    - **Validates: Requirements 7.4**

  - [x] 6.5 Write property test for notification deduplication
    - **Property 11: Notification deduplication**
    - **Validates: Requirements 7.5, 13.2**

- [x] 7. Checkpoint — Backend fully complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Frontend — Summary cards and page shell
  - [x] 8.1 Rebuild `ComplianceDashboard.tsx` page shell with Tailwind layout
    - Replace inline styles with Tailwind utility classes
    - Add page header with title and "Upload Document" button
    - Set up state management: documents, summary, categories, loading, error
    - Implement `useEffect` with `AbortController` cleanup for all API calls
    - Use typed generics on all `apiClient.get<T>()` calls — no `as any`
    - Guard all API response data with `?.` and `?? []` / `?? 0` fallbacks
    - Responsive container layout matching existing app patterns
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 11.6_

  - [x] 8.2 Create `SummaryCards` component
    - Four cards: Total (blue/neutral), Valid (green), Expiring Soon (amber), Expired (red)
    - Use Tailwind card pattern: `rounded-lg border border-gray-200 bg-white p-4 shadow-sm` with status colour accent
    - Responsive grid: 4-column ≥1024px, 2-column 640–1023px, 1-column <640px (`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4`)
    - Skeleton placeholders with `animate-pulse` during loading
    - Guard all count values with `?? 0`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 11.1, 11.2, 11.3_

- [x] 9. Frontend — Document table
  - [x] 9.1 Create `DocumentTable` component with columns, sorting, search, and filters
    - Columns: Document Type, File Name, Description, Expiry Date, Status, Linked Entity, Uploaded Date, Actions
    - Sortable columns (Document Type, File Name, Expiry Date, Uploaded Date) — click header to toggle asc/desc
    - Text search input filtering by file_name, document_type, description (client-side with server-side fallback)
    - Status dropdown filter: All, Valid, Expiring Soon, Expired, No Expiry
    - Category dropdown filter populated from `GET /categories`
    - Status badges: green (valid), amber (expiring_soon), red (expired), grey (no_expiry)
    - Empty state: "No documents match your filters" when filters active, "No compliance documents yet. Upload your first document to get started." when no documents exist
    - Horizontally scrollable on viewports <768px (`overflow-x-auto`)
    - Guard all `.map()` and `.filter()` calls with `?? []` fallback
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 11.4_

  - [x] 9.2 Add Actions column: download, preview, edit, delete buttons
    - Download button triggers browser file download via `GET /{doc_id}/download`
    - Preview button (PDF/image only) opens FilePreview modal
    - Edit button opens EditModal
    - Delete button opens DeleteConfirmation dialog
    - Hide preview button for Word documents — show download only
    - _Requirements: 4.4, 4.5, 4.6, 5.4, 5.5_

  - [x] 9.3 Write property tests for document sorting and text search filtering
    - **Property 2: Document sorting correctness**
    - **Property 3: Text search filtering**
    - **Property 4: Category filtering**
    - **Validates: Requirements 2.2, 2.3, 2.5**

- [x] 10. Frontend — Upload form with real file upload
  - [x] 10.1 Create `UploadForm` component with drag-and-drop file picker
    - Drag-and-drop zone + click-to-select file input
    - Display selected file name and size before submission
    - Category searchable dropdown (Headless UI Combobox) with predefined categories listed first
    - Free-text custom category entry when no predefined match
    - Optional fields: description, expiry_date, invoice/quote/job linking (searchable dropdowns)
    - Client-side validation: file type and size before upload
    - Progress indicator during upload (track XMLHttpRequest progress or use state)
    - Submit as `multipart/form-data` via `apiClient.post` with `FormData`
    - Display backend error messages on failure without crashing the page
    - Touch targets minimum 44x44px for mobile usability
    - _Requirements: 3.1, 3.8, 3.9, 3.10, 3.11, 6.2, 6.3, 9.1, 11.5_

  - [x] 10.2 Wire custom category creation into upload flow
    - When user enters a custom category name, call `POST /categories` or include in upload payload
    - New custom category appears in dropdown for subsequent uploads
    - _Requirements: 6.3, 6.4, 6.5_

- [x] 11. Frontend — Edit, delete, and preview modals
  - [x] 11.1 Create `EditModal` component using Headless UI Dialog
    - Pre-populate with current document metadata (document_type, description, expiry_date)
    - Category dropdown same as upload form
    - Submit PUT request to `PUT /{doc_id}`
    - Update table row and summary cards on success without full page reload
    - _Requirements: 5.1, 5.4_

  - [x] 11.2 Create `DeleteConfirmation` dialog using Headless UI Dialog
    - Show confirmation message with document name
    - On confirm: send DELETE request, remove row from table, update summary cards without page reload
    - _Requirements: 5.2, 5.5, 5.6_

  - [x] 11.3 Create `FilePreview` modal using Headless UI Dialog
    - PDF files: render in `<iframe>` or `<object>` using the download endpoint URL
    - Image files (JPEG, PNG, GIF): render in `<img>` tag
    - Word documents: not previewable — only download action available
    - _Requirements: 4.5, 4.6_

- [x] 12. Checkpoint — Frontend core complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Frontend — Notification badge and entity linking
  - [x] 13.1 Create `NotificationBadge` component for sidebar
    - Fetch `GET /api/v2/compliance-docs/badge-count` on mount
    - Render red circular badge with white text on the Compliance nav item in `OrgLayout.tsx`
    - Hidden when count is 0
    - Refresh count when user navigates to Compliance page
    - Use `AbortController` cleanup in useEffect
    - Guard count with `?? 0`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 13.2 Add document linking UI for invoices, quotes, and jobs
    - Searchable dropdown in upload and edit forms to link to invoice/quote/job
    - Display linked entity in Document_Table as clickable link navigating to entity detail page
    - _Requirements: 9.1, 9.2, 9.5_

  - [x] 13.3 Add compliance documents section to invoice and job detail pages
    - On invoice detail page: display section listing all compliance documents linked to that invoice
    - On job detail page: display section listing all compliance documents linked to that job
    - Fetch via existing service method `get_documents_for_invoice()` and equivalent for jobs
    - _Requirements: 9.3, 9.4, 9.6_

  - [x] 13.4 Write frontend tests for ComplianceDashboard
    - Test dashboard renders four summary cards with correct colours
    - Test document table renders all columns
    - Test search input filters documents
    - Test status filter shows only matching documents
    - Test upload form accepts drag-and-drop files
    - Test upload form shows file name and size before submit
    - Test edit modal pre-populates with current data
    - Test delete confirmation dialog appears on delete click
    - Test badge is hidden when count is 0
    - Test skeleton placeholders shown during loading
    - Test empty state messages shown when appropriate
    - _Requirements: 1.1, 1.6, 2.7, 2.8, 5.5, 8.2_

- [x] 14. Final checkpoint — All tests pass, feature complete
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation after backend core, backend full, frontend core, and final integration
- Property tests validate the 14 correctness properties defined in the design document using Hypothesis (Python) and fast-check (TypeScript)
- The backend is implemented first so the frontend can be developed against real endpoints
- All frontend code follows the safe API consumption patterns: `?.`, `?? []`, `?? 0`, `AbortController`, typed generics, no `as any`
- After every `db.flush()`, call `await db.refresh(obj)` before returning ORM objects (MissingGreenlet prevention)
- Alembic migrations follow from current head 0154 — new migrations are 0155 and 0156
- Docker volume `compliance_files` must be added before file upload/download can be tested locally
