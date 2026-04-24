# Requirements Document

## Introduction

Rebuild the existing Compliance Documents page in OraInvoice from its current skeleton state into a production-ready feature for all trade businesses. The existing backend provides basic CRUD operations with metadata-only storage, unstyled frontend HTML, and a scheduled task that logs expiry reminders without sending notifications. This rebuild delivers real file upload and storage, a polished Tailwind UI with status-coded summary cards and a filterable document table, predefined and custom document categories, actual email expiry notifications at 30-day, 7-day, and day-of thresholds, in-app notification badges, document linking to invoices/quotes/jobs, and safe API consumption patterns throughout. The feature is universally available to all business types via the `compliance_docs` module slug with no trade-family gating.

## Glossary

- **Compliance_Dashboard**: The main Compliance Documents page rendered at `frontend/src/pages/compliance/ComplianceDashboard.tsx`, displaying summary cards, upload controls, and the document table
- **Compliance_Document**: A record in the `compliance_documents` database table representing an uploaded compliance or certification file with metadata including type, expiry date, and linked entities
- **Document_Category**: A classification label for a Compliance_Document (e.g. Business License, Public Liability Insurance), either predefined by the system or custom-created by an organisation
- **File_Storage**: The local filesystem volume mount used to persist uploaded compliance document files on the server
- **Upload_Service**: The backend service responsible for receiving file uploads, validating file type and size, writing files to File_Storage, and creating the corresponding Compliance_Document record
- **Expiry_Notification_Service**: The backend service that sends email notifications when a Compliance_Document approaches or reaches its expiry date
- **Notification_Badge**: A visual indicator on the Compliance nav item in the sidebar showing the count of expiring and expired Compliance_Documents for the current organisation
- **Document_Table**: The sortable, searchable, filterable table component on the Compliance_Dashboard that lists all Compliance_Documents for the organisation
- **Summary_Card**: A colour-coded card on the Compliance_Dashboard displaying an aggregate count (total, expiring soon, expired, or valid)
- **File_Preview**: An inline viewer for PDF and image files that allows users to view document contents without downloading
- **Accepted_File_Types**: The set of MIME types permitted for upload: PDF (`application/pdf`), JPEG (`image/jpeg`), PNG (`image/png`), GIF (`image/gif`), Microsoft Word (`application/msword`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`)
- **Max_File_Size**: The maximum permitted file size for a single upload, set at 10 megabytes (10,485,760 bytes)

## Requirements

### Requirement 1: Tailwind UI Summary Cards

**User Story:** As a business owner, I want to see colour-coded summary cards showing the status of my compliance documents at a glance, so that I can immediately identify documents that need attention.

#### Acceptance Criteria

1. WHEN the Compliance_Dashboard loads, THE Compliance_Dashboard SHALL display four Summary_Cards: Total Documents, Valid Documents, Expiring Soon (within 30 days), and Expired
2. THE Compliance_Dashboard SHALL render the Valid Summary_Card with a green colour scheme (green icon, green accent border or background tint)
3. THE Compliance_Dashboard SHALL render the Expiring Soon Summary_Card with an amber colour scheme (amber icon, amber accent border or background tint)
4. THE Compliance_Dashboard SHALL render the Expired Summary_Card with a red colour scheme (red icon, red accent border or background tint)
5. THE Compliance_Dashboard SHALL render each Summary_Card using the existing Tailwind CSS card pattern (`rounded-lg border border-gray-200 bg-white p-4 shadow-sm`) with the status colour applied as an accent
6. WHEN the dashboard data is loading, THE Compliance_Dashboard SHALL display skeleton placeholder cards with a pulsing animation in place of the Summary_Cards

### Requirement 2: Document Table with Sorting, Search, and Filtering

**User Story:** As a business owner, I want to search, sort, and filter my compliance documents in a table, so that I can quickly find specific documents.

#### Acceptance Criteria

1. THE Document_Table SHALL display columns for: Document Type, File Name, Description, Expiry Date, Status, Linked Entity, Uploaded Date, and Actions
2. THE Document_Table SHALL allow sorting by Document Type, File Name, Expiry Date, and Uploaded Date columns by clicking the column header
3. THE Document_Table SHALL provide a text search input that filters documents by file name, document type, and description as the user types
4. THE Document_Table SHALL provide a dropdown filter for document status (All, Valid, Expiring Soon, Expired, No Expiry)
5. THE Document_Table SHALL provide a dropdown filter for Document_Category
6. THE Document_Table SHALL display the document status as a colour-coded badge: green for valid, amber for expiring within 30 days, red for expired, grey for no expiry date set
7. IF no documents match the current search and filter criteria, THEN THE Document_Table SHALL display an empty state message reading "No documents match your filters"
8. IF the organisation has no Compliance_Documents, THEN THE Document_Table SHALL display an empty state message reading "No compliance documents yet. Upload your first document to get started."

### Requirement 3: Real File Upload with Validation

**User Story:** As a business owner, I want to upload actual compliance document files (not just metadata), so that I have a central repository of my compliance paperwork.

#### Acceptance Criteria

1. THE Upload_Service SHALL accept multipart file uploads via a new `POST /api/v2/compliance-docs/upload` endpoint
2. THE Upload_Service SHALL validate that the uploaded file MIME type is one of the Accepted_File_Types before saving
3. THE Upload_Service SHALL validate that the uploaded file size does not exceed Max_File_Size before saving
4. IF the uploaded file MIME type is not in Accepted_File_Types, THEN THE Upload_Service SHALL return HTTP 400 with a message specifying the accepted file types
5. IF the uploaded file size exceeds Max_File_Size, THEN THE Upload_Service SHALL return HTTP 400 with a message stating the maximum allowed file size
6. WHEN a valid file is uploaded, THE Upload_Service SHALL write the file to File_Storage under a path structured as `compliance/{org_id}/{uuid}_{original_filename}`
7. WHEN a valid file is uploaded, THE Upload_Service SHALL create a Compliance_Document record with the `file_key` set to the storage path and `file_name` set to the original filename
8. THE Compliance_Dashboard SHALL provide an upload form with a file picker that supports both drag-and-drop and click-to-select interactions
9. THE upload form SHALL display the selected file name and size before submission
10. THE upload form SHALL show a progress indicator during file upload
11. IF the upload fails, THEN THE upload form SHALL display the error message returned by the Upload_Service without crashing the page

### Requirement 4: File Download and Preview

**User Story:** As a business owner, I want to download and preview my uploaded compliance documents, so that I can verify document contents without leaving the application.

#### Acceptance Criteria

1. THE Upload_Service SHALL provide a `GET /api/v2/compliance-docs/{doc_id}/download` endpoint that streams the file from File_Storage with the correct Content-Type and Content-Disposition headers
2. IF the requested Compliance_Document does not belong to the requesting organisation, THEN THE Upload_Service SHALL return HTTP 403
3. IF the file is missing from File_Storage, THEN THE Upload_Service SHALL return HTTP 404 with a message indicating the file was not found
4. THE Document_Table SHALL provide a download button for each Compliance_Document that triggers a browser file download
5. WHEN the user clicks a preview action on a PDF or image file, THE Compliance_Dashboard SHALL display a File_Preview modal showing the document contents inline
6. IF the file type does not support inline preview (Word documents), THEN THE Compliance_Dashboard SHALL offer only the download action for that document

### Requirement 5: Edit and Delete Documents

**User Story:** As a business owner, I want to edit document metadata and delete documents I no longer need, so that I can keep my compliance records accurate and current.

#### Acceptance Criteria

1. THE Upload_Service SHALL provide a `PUT /api/v2/compliance-docs/{doc_id}` endpoint that updates the document_type, description, and expiry_date fields of an existing Compliance_Document
2. THE Upload_Service SHALL provide a `DELETE /api/v2/compliance-docs/{doc_id}` endpoint that deletes the Compliance_Document record and removes the associated file from File_Storage
3. IF the Compliance_Document targeted by an edit or delete does not belong to the requesting organisation, THEN THE Upload_Service SHALL return HTTP 403
4. THE Document_Table SHALL provide an edit action for each document that opens an inline edit form or modal pre-populated with the current metadata
5. THE Document_Table SHALL provide a delete action for each document that displays a confirmation dialog before proceeding
6. WHEN the user confirms deletion, THE Compliance_Dashboard SHALL remove the document from the Document_Table and update the Summary_Cards without requiring a full page reload

### Requirement 6: Predefined and Custom Document Categories

**User Story:** As a business owner, I want to select from predefined compliance document categories and also create custom ones, so that I can organise documents using standard industry labels or my own terminology.

#### Acceptance Criteria

1. THE system SHALL provide the following predefined Document_Categories available to all organisations: Business License, Public Liability Insurance, Professional Indemnity Insurance, Trade Certification, Health and Safety Certificate, Vehicle Registration, Equipment Certification, Environmental Permit, Food Safety Certificate, Workers Compensation Insurance, Building Permit, Electrical Safety Certificate, Gas Safety Certificate, Asbestos License, Fire Safety Certificate
2. THE upload form SHALL present Document_Categories in a searchable dropdown with the predefined categories listed first
3. THE upload form SHALL allow the user to enter a custom category name via a free-text option in the dropdown when no predefined category matches
4. WHEN a user enters a custom category, THE system SHALL save the custom category as a new Document_Category associated with the organisation
5. THE system SHALL include organisation-specific custom categories in the Document_Category dropdown for subsequent uploads by users in the same organisation
6. THE system SHALL provide a `GET /api/v2/compliance-docs/categories` endpoint that returns the combined list of predefined and organisation-specific custom categories

### Requirement 7: Expiry Email Notifications

**User Story:** As a business owner, I want to receive email notifications when my compliance documents are about to expire, so that I can renew them before they lapse.

#### Acceptance Criteria

1. WHEN a Compliance_Document expiry date is exactly 30 days away, THE Expiry_Notification_Service SHALL send a 30-day warning email to the organisation's primary contact email
2. WHEN a Compliance_Document expiry date is exactly 7 days away, THE Expiry_Notification_Service SHALL send a 7-day warning email to the organisation's primary contact email
3. WHEN a Compliance_Document expiry date is today, THE Expiry_Notification_Service SHALL send a day-of expiry email to the organisation's primary contact email
4. THE expiry notification email SHALL include the document type, file name, expiry date, and a link to the Compliance_Dashboard
5. THE Expiry_Notification_Service SHALL not send duplicate notifications for the same document at the same threshold (30-day, 7-day, or day-of)
6. IF the email delivery fails, THEN THE Expiry_Notification_Service SHALL log the failure with the document ID, organisation ID, and error details
7. THE Expiry_Notification_Service SHALL run as part of the existing `check_compliance_expiry_task` scheduled task

### Requirement 8: In-App Notification Badge

**User Story:** As a business owner, I want to see a badge on the Compliance nav item showing how many documents are expiring or expired, so that I am aware of compliance issues without navigating to the page.

#### Acceptance Criteria

1. THE Notification_Badge SHALL display the combined count of Compliance_Documents that are expired or expiring within 30 days for the current organisation
2. WHEN the count is zero, THE Notification_Badge SHALL not be visible
3. WHEN the count is greater than zero, THE Notification_Badge SHALL display as a red circular badge with white text on the Compliance navigation item in the sidebar
4. THE Notification_Badge count SHALL update when the user navigates to the Compliance_Dashboard (reflecting any changes from uploads or deletions)
5. THE system SHALL provide a `GET /api/v2/compliance-docs/badge-count` endpoint that returns the count of expired and expiring-soon documents for the current organisation

### Requirement 9: Document Linking to Invoices, Quotes, and Jobs

**User Story:** As a business owner, I want to link compliance documents to specific invoices, quotes, and jobs, so that I can demonstrate compliance for specific pieces of work.

#### Acceptance Criteria

1. THE upload form and edit form SHALL allow the user to optionally link a Compliance_Document to an invoice, quote, or job by selecting from a searchable dropdown
2. THE Document_Table SHALL display the linked entity (invoice number, quote number, or job reference) as a clickable link that navigates to the entity detail page
3. WHEN viewing an invoice detail page, THE invoice detail page SHALL display a section listing all Compliance_Documents linked to that invoice
4. WHEN viewing a job detail page, THE job detail page SHALL display a section listing all Compliance_Documents linked to that job
5. THE system SHALL support linking a single Compliance_Document to one invoice and one job simultaneously (using the existing `invoice_id` and `job_id` columns)
6. IF a linked invoice or job is deleted, THEN THE system SHALL set the corresponding foreign key on the Compliance_Document to null rather than deleting the document

### Requirement 10: Safe API Consumption Patterns

**User Story:** As a developer, I want all Compliance_Dashboard API calls to follow the project's safe API consumption patterns, so that the page does not crash from null or undefined API responses.

#### Acceptance Criteria

1. THE Compliance_Dashboard SHALL use optional chaining (`?.`) and nullish coalescing (`?? []`, `?? 0`) on all API response data before rendering
2. THE Compliance_Dashboard SHALL use `AbortController` cleanup in every `useEffect` that makes API calls
3. THE Compliance_Dashboard SHALL use typed generics on all `apiClient.get()` and `apiClient.post()` calls with no `as any` type assertions
4. THE Compliance_Dashboard SHALL guard all `.map()`, `.filter()`, and `.toLocaleString()` calls on API data with `?? []` or `?? 0` fallbacks
5. IF an API call fails, THEN THE Compliance_Dashboard SHALL display a localised error message within the affected component without crashing the entire page
6. THE Compliance_Dashboard SHALL ensure all frontend field names match the backend Pydantic schema field names exactly (snake_case as defined in `ComplianceDocumentResponse`)

### Requirement 11: Responsive Design

**User Story:** As a business owner, I want the Compliance Documents page to work well on desktop, tablet, and mobile devices, so that I can manage compliance from any device.

#### Acceptance Criteria

1. WHILE the viewport width is 1024px or above, THE Compliance_Dashboard SHALL render Summary_Cards in a 4-column grid layout
2. WHILE the viewport width is between 640px and 1023px, THE Compliance_Dashboard SHALL render Summary_Cards in a 2-column grid layout
3. WHILE the viewport width is below 640px, THE Compliance_Dashboard SHALL render Summary_Cards in a single-column layout
4. WHEN the Document_Table is viewed on a viewport below 768px, THE Document_Table SHALL be horizontally scrollable rather than breaking the page layout
5. THE upload form SHALL be usable on mobile viewports with appropriately sized touch targets (minimum 44x44px)
6. THE Compliance_Dashboard SHALL use the existing Tailwind CSS utility classes and Headless UI components consistent with the rest of the application

### Requirement 12: File Upload Security

**User Story:** As a developer, I want file uploads to be validated and stored securely, so that malicious files cannot compromise the system.

#### Acceptance Criteria

1. THE Upload_Service SHALL validate the file content by reading the file header bytes (magic numbers) in addition to checking the declared MIME type
2. THE Upload_Service SHALL generate a unique filename using a UUID prefix to prevent path traversal and filename collision attacks
3. THE Upload_Service SHALL store files outside the web-accessible directory tree so that files cannot be accessed by direct URL without going through the authenticated download endpoint
4. THE Upload_Service SHALL reject files with double extensions (e.g. `document.pdf.exe`) by validating the final extension against the allowed list
5. IF a file fails content validation (magic number mismatch with declared MIME type), THEN THE Upload_Service SHALL return HTTP 400 with a message indicating the file type could not be verified
6. THE download endpoint SHALL set the `Content-Disposition` header to `attachment` by default to prevent browser execution of downloaded files

### Requirement 13: Expiry Notification Deduplication

**User Story:** As a business owner, I want to receive each expiry notification only once per threshold, so that I am not spammed with duplicate emails.

#### Acceptance Criteria

1. THE system SHALL maintain a notification log table recording each notification sent, including the Compliance_Document ID, notification threshold (30-day, 7-day, or day-of), and the timestamp sent
2. WHEN the Expiry_Notification_Service runs, THE Expiry_Notification_Service SHALL check the notification log before sending and skip any notification where a matching document ID and threshold combination already exists
3. THE notification log table SHALL be created via an Alembic migration following the project's database migration checklist (idempotent, IF NOT EXISTS)
