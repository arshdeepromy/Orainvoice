# Requirements Document — Quote Mobile Parity (Phase 6)

## Introduction

This document specifies the requirements for bringing the mobile `QuoteDetailScreen` up to feature parity with `InvoiceDetailScreen`. The scope covers Preview PDF via a hero button, Download PDF and Print actions in the action sheet, an attachments carousel with inline camera upload (native and web paths), draft-only attachment deletion, and the explicit exclusion of POS receipt functionality. All requirements are derived from the approved design at `.kiro/specs/quote-mobile-parity/design.md` and constrained to Phase 6 of `docs/QUOTE_PREVIEW_PRINT_PLAN.md`.

## Glossary

- **QuotePDFScreen**: A new full-screen React component at route `/quotes/:id/pdf` that renders the quote PDF inline using the existing `PDFViewer` component.
- **Action_Sheet**: The bottom sheet (Konsta `<Sheet>`) on `QuoteDetailScreen` containing contextual actions such as Download PDF, Print, and Duplicate.
- **Attachment_Carousel**: A horizontally-scrollable row of attachment thumbnails displayed in the Attachments section of `QuoteDetailScreen`.
- **Take_Photo**: The button in the Attachments section that triggers either the Capacitor Camera plugin (native) or a file input with `capture="environment"` (web) to upload a photo attachment.
- **Capacitor_Camera**: The `@capacitor/camera` plugin used on native platforms to capture photos; dynamically imported and guarded by `isNativePlatform()`.
- **PDFViewer**: An existing shared component (`mobile/src/components/common/PDFViewer.tsx`) that fetches and renders a PDF from a given URL.
- **AuthGuard**: The existing mobile route guard that restricts access to authenticated organisation users (never `global_admin`).
- **HapticButton**: An existing mobile button component that provides native-feel touch feedback on iOS and Android.
- **isNativePlatform**: A runtime check `(window as any).Capacitor?.isNativePlatform?.()` that returns `true` only when the app runs inside a Capacitor native shell.
- **Touch_Target**: The minimum interactive area (44×44 CSS pixels) required for all tappable elements per Apple HIG and WCAG 2.5.8.
- **Draft_Quote**: A quote with `status === 'draft'`; the only status that permits attachment deletion.

## Requirements

### Requirement 1: Preview PDF from Hero Button

**User Story:** As a mobile user viewing a quote, I want to preview the quote PDF directly from the detail screen, so that I can quickly review the document before sharing or printing.

#### Acceptance Criteria

1. WHEN a user taps the "Preview PDF" hero button on QuoteDetailScreen, THE QuotePDFScreen SHALL navigate to route `/quotes/:id/pdf` and render the PDF inline using PDFViewer.
2. WHEN QuotePDFScreen loads, THE PDFViewer SHALL fetch the PDF from `GET /api/v1/quotes/:id/pdf` and display it full-screen.
3. WHEN a user taps the Back button on QuotePDFScreen, THE QuotePDFScreen SHALL navigate back to the previous screen.
4. WHEN a user taps the Open button on QuotePDFScreen, THE QuotePDFScreen SHALL open the PDF URL in a new browser tab via `window.open`.
5. IF the PDF endpoint returns an error, THEN THE PDFViewer SHALL display its built-in error state without crashing the screen.

### Requirement 2: Download PDF from Action Sheet

**User Story:** As a mobile user, I want to download a quote PDF from the action sheet, so that I can save it to my device or share it via the OS share sheet.

#### Acceptance Criteria

1. WHEN a user opens the Action_Sheet on QuoteDetailScreen, THE Action_Sheet SHALL display a "Download PDF" item with `data-testid="download-pdf-action"`.
2. WHEN a user taps "Download PDF" in the Action_Sheet, THE QuoteDetailScreen SHALL navigate to `/quotes/:id/pdf` and close the Action_Sheet.
3. WHEN the user is on QuotePDFScreen after navigating via Download PDF, THE QuotePDFScreen SHALL allow the user to save the file using the browser's native PDF controls or OS share sheet.

### Requirement 3: Print from Action Sheet

**User Story:** As a mobile user, I want to print a quote from the action sheet, so that I can produce a physical copy without leaving the app.

#### Acceptance Criteria

1. WHEN a user opens the Action_Sheet on QuoteDetailScreen, THE Action_Sheet SHALL display a "Print" item with `data-testid="print-action"`.
2. WHEN a user taps "Print" in the Action_Sheet, THE QuoteDetailScreen SHALL invoke `window.print()` and close the Action_Sheet.
3. WHEN the native print dialog is cancelled by the user, THE QuoteDetailScreen SHALL remain in its current state with no error displayed.

### Requirement 4: Upload Photo from Camera

**User Story:** As a field user, I want to take a photo and attach it to a quote, so that I can document site conditions or damage directly from my phone.

#### Acceptance Criteria

1. WHEN a user taps the "Take Photo" button and isNativePlatform returns true, THE QuoteDetailScreen SHALL invoke the Capacitor_Camera plugin with `resultType: Uri` and `quality: 80`.
2. WHEN the Capacitor_Camera returns a photo, THE QuoteDetailScreen SHALL upload it via `POST /api/v1/quotes/:id/attachments` as multipart FormData.
3. WHEN a user taps the "Take Photo" button and isNativePlatform returns false, THE QuoteDetailScreen SHALL trigger a hidden file input with `accept="image/jpeg,image/png,image/webp,image/gif,application/pdf"` and `capture="environment"`.
4. WHEN the file input returns a file on the web path, THE QuoteDetailScreen SHALL upload it via `POST /api/v1/quotes/:id/attachments` as multipart FormData.
5. WHEN an upload succeeds with HTTP 201, THE QuoteDetailScreen SHALL refetch the quote data and display a "Attachment uploaded" success toast.
6. IF the selected file exceeds 20 MB, THEN THE QuoteDetailScreen SHALL reject the upload client-side and display a toast "File exceeds 20 MB" without making a network call.
7. IF the selected file has a MIME type not in the allowed set (image/jpeg, image/png, image/webp, image/gif, application/pdf), THEN THE QuoteDetailScreen SHALL reject the upload client-side and display a toast "Only JPEG, PNG, WebP, GIF, and PDF files are allowed" without making a network call.
8. IF the quote already has 5 attachments, THEN THE QuoteDetailScreen SHALL reject the upload client-side and display a toast "This quote already has the maximum 5 attachments" without making a network call.
9. IF the user cancels the camera or denies permission, THEN THE QuoteDetailScreen SHALL silently catch the error without displaying a toast.
10. IF the server returns HTTP 413, THEN THE QuoteDetailScreen SHALL display a toast "File exceeds 20 MB".
11. IF the server returns HTTP 400, THEN THE QuoteDetailScreen SHALL display a toast "File rejected — please try another".
12. IF the server returns HTTP 507, THEN THE QuoteDetailScreen SHALL display a toast "Storage quota exceeded for this organisation".
13. IF a network error or HTTP 500 occurs during upload, THEN THE QuoteDetailScreen SHALL display a toast "Upload failed — please retry".

### Requirement 5: View Attachments Carousel

**User Story:** As a mobile user, I want to see all attachments on a quote in a scrollable carousel, so that I can quickly browse uploaded documents and photos.

#### Acceptance Criteria

1. WHEN a quote has `attachment_count > 0`, THE QuoteDetailScreen SHALL render the Attachment_Carousel as a horizontally-scrollable row of thumbnails.
2. WHEN a quote has `attachment_count === 0`, THE QuoteDetailScreen SHALL display "No attachments" muted text instead of the carousel.
3. WHEN an attachment has a MIME type starting with `image/`, THE Attachment_Carousel SHALL display an image thumbnail.
4. WHEN an attachment has a non-image MIME type, THE Attachment_Carousel SHALL display a file-type icon.
5. WHEN a user taps an attachment thumbnail, THE Attachment_Carousel SHALL open the attachment URL in a new browser tab.

### Requirement 6: Delete Attachment (Draft Only)

**User Story:** As a mobile user editing a draft quote, I want to remove an attachment I uploaded by mistake, so that only relevant documents are attached when I send the quote.

#### Acceptance Criteria

1. WHILE a quote has `status === 'draft'`, THE QuoteDetailScreen SHALL render a delete button on each attachment thumbnail.
2. WHILE a quote has a status other than `'draft'`, THE QuoteDetailScreen SHALL NOT render any delete affordance on attachment thumbnails.
3. WHEN a user taps the delete button on an attachment, THE QuoteDetailScreen SHALL display a confirmation prompt before proceeding.
4. WHEN the user confirms deletion, THE QuoteDetailScreen SHALL send `DELETE /api/v1/quotes/:id/attachments/:aid` and refetch the quote on success.
5. IF the server returns HTTP 403 on delete, THEN THE QuoteDetailScreen SHALL display a toast "Attachments can only be removed while the quote is a draft".
6. IF a network error occurs during delete, THEN THE QuoteDetailScreen SHALL display a toast "Delete failed — please retry".

### Requirement 7: POS Receipt Exclusion

**User Story:** As a product owner, I want to ensure POS receipt functionality never appears on the quote detail screen, so that users are not confused by an action that has no meaning for quotes.

#### Acceptance Criteria

1. THE Action_Sheet on QuoteDetailScreen SHALL NOT render any element matching the text "Print POS Receipt" regardless of quote status, trade family, module set, or user role.
2. THE QuoteDetailScreen SHALL NOT mount a `POSReceiptPreview` component under any condition.
3. THE QuoteDetailScreen SHALL NOT navigate to any route matching `/quotes/:id/pos-receipt` under any condition.

### Requirement 8: Touch Targets

**User Story:** As a mobile user, I want all interactive elements to be easy to tap, so that I can use the app comfortably on small screens without mis-taps.

#### Acceptance Criteria

1. THE "Preview PDF" hero button SHALL have a minimum height of 44 CSS pixels.
2. THE "Take Photo" button SHALL have a minimum height of 44 CSS pixels.
3. THE Action_Sheet items (Download PDF, Print) SHALL each have a minimum height of 44 CSS pixels.
4. THE attachment delete button SHALL have a minimum touch target of 44×44 CSS pixels on viewports ≤ 430px.
5. THE Back button on QuotePDFScreen SHALL have a minimum height of 44 CSS pixels.

### Requirement 9: Dark Mode Rendering

**User Story:** As a mobile user who prefers dark mode, I want the quote detail and PDF screens to render correctly in dark mode, so that the interface is comfortable to use in low-light conditions.

#### Acceptance Criteria

1. WHEN the device is in dark mode, THE QuotePDFScreen SHALL render with appropriate dark background and text colours using Tailwind `dark:` variants.
2. WHEN the device is in dark mode, THE Attachment_Carousel borders and text SHALL use dark-mode colour tokens (`dark:border-gray-700`, `dark:text-gray-500`).
3. WHEN the device is in dark mode, THE Action_Sheet items SHALL render with legible contrast against the dark background.
4. THE QuotePDFScreen and all new QuoteDetailScreen elements SHALL render without runtime errors in both light and dark modes.

### Requirement 10: Capacitor Plugin Guarding

**User Story:** As a developer, I want all Capacitor plugin calls to be guarded by platform detection, so that the app does not crash when running in a web browser without native plugins.

#### Acceptance Criteria

1. THE QuoteDetailScreen SHALL NOT invoke `Camera.getPhoto` or any Capacitor plugin method when `isNativePlatform()` returns false.
2. WHEN isNativePlatform returns false, THE QuoteDetailScreen SHALL use the web file-input fallback path for photo capture.
3. IF the dynamic import of `@capacitor/camera` fails, THEN THE QuoteDetailScreen SHALL catch the error silently and fall back to the web path.

## Non-Functional Requirements

### NFR-1: Authentication and Authorisation

1. THE QuotePDFScreen route SHALL be protected by AuthGuard, restricting access to authenticated organisation users only.
2. THE QuoteDetailScreen SHALL NOT be accessible to users with the `global_admin` role (enforced by the mobile app's existing AuthGuard which never surfaces `global_admin` tokens).
3. THE backend endpoints called by this feature (`GET /quotes/:id/pdf`, `POST/DELETE /quotes/:id/attachments`) SHALL enforce `require_role("org_admin", "salesperson")` server-side.

### NFR-2: Safe API Consumption

1. THE QuoteDetailScreen SHALL use optional chaining (`?.`) and nullish coalescing (`?? []`, `?? 0`) on all API response data.
2. THE QuoteDetailScreen SHALL use typed generics on all API calls (no `as any`).
3. THE QuoteDetailScreen SHALL use `AbortController` in every `useEffect` that performs a fetch, returning `controller.abort()` in the cleanup function.

### NFR-3: Touch Targets (44px Minimum)

1. THE minimum interactive area for all new tappable elements SHALL be 44×44 CSS pixels on viewports between 320px and 430px, per Apple HIG and WCAG 2.5.8.

### NFR-4: Dark Mode

1. ALL new components and modified sections SHALL include Tailwind `dark:` variant classes for backgrounds, borders, and text colours.

### NFR-5: Capacitor Guarding

1. ALL Capacitor plugin invocations SHALL be preceded by a truthy check of `isNativePlatform()`.
2. ALL Capacitor plugin imports SHALL use dynamic `import()` inside the native-only branch so the bundler does not require the package on web.

### NFR-6: Viewport Range

1. ALL new UI elements SHALL render correctly and remain usable across the supported viewport range of 320px (iPhone SE) to 430px (iPhone Pro Max).

## Out of Scope

The following items are explicitly excluded from this spec per the design document and `docs/QUOTE_PREVIEW_PRINT_PLAN.md`:

| Item | Rationale |
|------|-----------|
| Print POS Receipt action / route / component | A receipt implies a completed transaction; a quote is not a transaction. |
| Record Payment action | Quotes do not take payment; payment preference carries over at convert-to-invoice. |
| Void action | Quotes have decline/expire lifecycle, not void. |
| Credit note / Refund actions | Invoice-only concepts. |
| Reminder action | Quotes auto-expire; they are not reminded. |
| Recurring quote toggle | Recurring is a billing cadence; quotes are one-time. |
| Mark Paid & Email | Same as Record Payment. |
| Desktop changes | Covered by `quote-pdf-print` and `quote-invoice-parity` specs. This spec is mobile-only. |

## Traceability Matrix

| Acceptance Criterion | Design Section | Correctness Property |
|---------------------|----------------|---------------------|
| 1.1 Preview PDF navigation | §4.1 Flow — Preview PDF, §5.7 Hero button | CP-2 (PDF URL parity) |
| 1.2 PDFViewer fetch | §5.1 QuotePDFScreen, §4.1 | CP-2 |
| 1.3 Back navigation | §4.1 (alt path), §5.1 | — |
| 1.4 Open in new tab | §4.1 (alt path), §5.1 | CP-2 |
| 1.5 PDF error state | §8 Error States Matrix | — |
| 2.1 Download PDF item | §5.5 Action Sheet spec, §6 Toolbar Matrix | — |
| 2.2 Download PDF navigation | §4.2 Flow — Download PDF | CP-2 |
| 2.3 Save via native controls | §7.2 User-Workflow Trace | — |
| 3.1 Print item | §5.5 Action Sheet spec, §6 Toolbar Matrix | — |
| 3.2 Print invocation | §4.3 Flow — Native Print | — |
| 3.3 Print cancel | §7.7 Error paths, §8 Error States Matrix | — |
| 4.1 Native camera invocation | §4.4 Flow — Camera upload, §5.3 handleTakePhoto | CP-6 |
| 4.2 Native upload | §4.4, §5.3 | — |
| 4.3 Web file input | §4.4 (else branch), §5.4 pickFileFromInput | CP-6 |
| 4.4 Web upload | §4.4, §5.3 | — |
| 4.5 Upload success | §7.4 / §7.5 Workflow Traces | — |
| 4.6 Client-side size rejection | §5.3 (validation block) | CP-3 |
| 4.7 Client-side MIME rejection | §5.3 (validation block) | CP-3 |
| 4.8 Client-side count rejection | §5.3 (validation block) | CP-3 |
| 4.9 Camera cancel silent catch | §7.7 Error paths | — |
| 4.10 Server 413 | §8 Error States Matrix | CP-3 |
| 4.11 Server 400 | §8 Error States Matrix | CP-3 |
| 4.12 Server 507 | §8 Error States Matrix | — |
| 4.13 Network error | §8 Error States Matrix | — |
| 5.1 Carousel render | §5.6 Attachments section JSX | — |
| 5.2 Empty state | §5.6, §9 Loading/Empty States | — |
| 5.3 Image thumbnail | §5.6 (conditional render) | — |
| 5.4 File icon fallback | §5.6 (conditional render) | — |
| 5.5 Tap opens attachment | §5.6 (anchor tag) | — |
| 6.1 Delete button on draft | §5.6 (canDelete), §4.5 Flow — Delete | CP-7 |
| 6.2 No delete on non-draft | §5.6 (canDelete), §4.5 | CP-7 |
| 6.3 Delete confirmation | §4.5 Flow — Delete (step 3) | — |
| 6.4 Delete success | §5.3 handleDeleteAttachment, §4.5 | — |
| 6.5 Delete 403 | §8 Error States Matrix | — |
| 6.6 Delete network error | §8 Error States Matrix | — |
| 7.1 No POS receipt text | §5.5 (ABSENT comment), §6 Toolbar Matrix, §11 | CP-1 |
| 7.2 No POSReceiptPreview | §3.2 Component Tree (REM), §11 | CP-1 |
| 7.3 No POS receipt route | §2 Navigation, §11 | CP-1 |
| 8.1–8.5 Touch targets | §5.1, §5.5, §5.6, §5.7 (min-h-[44px] classes) | CP-5 |
| 9.1–9.4 Dark mode | §5.1, §5.6 (dark: classes) | CP-4 |
| 10.1–10.3 Capacitor guarding | §5.3 handleTakePhoto (isNative branch) | CP-6 |
| NFR-1 Auth | §2 Navigation & Access | — |
| NFR-2 Safe API | §5.3 (typed generics, AbortController) | — |
| NFR-3 Touch targets | §5.1, §5.5, §5.6, §5.7 | CP-5 |
| NFR-4 Dark mode | §5.1, §5.6 | CP-4 |
| NFR-5 Capacitor guarding | §5.3 | CP-6 |
| NFR-6 Viewport range | §1.4 Guiding steering rules | — |
