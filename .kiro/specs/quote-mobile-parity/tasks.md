# Implementation Plan: Quote Mobile Parity (Phase 6)

## Overview

Bring `QuoteDetailScreen` up to feature parity with `InvoiceDetailScreen` on mobile — Preview PDF hero button, Download PDF and Print action-sheet items, attachments carousel with inline camera upload, and draft-only attachment deletion. No backend changes; depends on `quote-pdf-print` (Phase 1) and `quote-invoice-parity` (Phase 5) already being deployed.

## Tasks

- [x] 1. Create `QuotePDFScreen.tsx`
  - [x] 1.1 Create `mobile/src/screens/quotes/QuotePDFScreen.tsx`
    - Mirror `InvoicePDFScreen.tsx` structure: header with Back button, title "Quote PDF", Open button
    - Render `<PDFViewer url={/api/v1/quotes/${id}/pdf} title={Quote ${id} PDF} />`
    - Back button navigates via `navigate(-1)`; Open button calls `window.open(pdfUrl, '_blank')`
    - Apply `min-h-[44px]` on Back button, `dark:` variants on header border and text
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 8.5, 9.1_

- [x] 2. Register route in `StackRoutes.tsx`
  - [x] 2.1 Add lazy import and route for `QuotePDFScreen`
    - Add `const QuotePDFScreen = lazy(() => import('@/screens/quotes/QuotePDFScreen').catch(...))` alongside existing quote lazy imports
    - Add `<Route path="/quotes/:id/pdf" element={<AuthGuard><QuotePDFScreen /></AuthGuard>} />` immediately after the existing `/quotes/:id` route
    - No changes to bottom-tab bar or any other route
    - _Requirements: 1.1, NFR-1.1_

- [x] 3. Add state and handlers to `QuoteDetailScreen.tsx`
  - [x] 3.1 Extend `QuoteData` interface with attachment fields
    - Add `attachment_count?: number` and `attachments?: Array<{id?, filename?, url?, thumbnail_url?, mime_type?, size_bytes?, created_at?}> | null` to the existing interface
    - Ensure all new fields use optional chaining and nullish coalescing when consumed
    - _Requirements: 5.1, NFR-2.1, NFR-2.2_
  - [x] 3.2 Implement `handlePreviewPDF` handler
    - `navigate(/quotes/${id}/pdf)` + close action sheet
    - Shared by hero button and Download PDF action-sheet item
    - _Requirements: 1.1, 2.2_
  - [x] 3.3 Implement `handlePrint` handler
    - Call `window.print()` + close action sheet
    - No error handling needed (print cancel is native)
    - _Requirements: 3.2, 3.3_
  - [x] 3.4 Implement `handleTakePhoto` handler
    - Guard Capacitor Camera with `isNativePlatform()` check
    - Native path: dynamic `import('@capacitor/camera')`, `Camera.getPhoto({ resultType: Uri, quality: 80 })`, convert `webPath` to Blob via `fetch()`
    - Web path: trigger hidden `<input type="file" accept="image/jpeg,image/png,image/webp,image/gif,application/pdf" capture="environment">`
    - Client-side validation: reject if size > 20 MB, MIME not in allowed set, or `attachment_count >= 5` — each with specific toast
    - POST `/api/v1/quotes/:id/attachments` with multipart FormData
    - On 201: refetch quote, toast "Attachment uploaded"
    - On camera cancel/deny: silent catch
    - On 413/400/507/network error: display appropriate toast per design §8
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 4.13, 10.1, 10.2, 10.3_
  - [x] 3.5 Implement `handleDeleteAttachment` handler
    - Only callable when `quote.status === 'draft'` (defensive check)
    - DELETE `/api/v1/quotes/:id/attachments/:aid`
    - On success: refetch quote, toast "Attachment removed"
    - On 403: toast "Attachments can only be removed while the quote is a draft"
    - On network error: toast "Delete failed — please retry"
    - _Requirements: 6.3, 6.4, 6.5, 6.6_

- [x] 4. Add Preview PDF hero button to `QuoteDetailScreen.tsx`
  - [x] 4.1 Place "Preview PDF" `HapticButton` in the hero card
    - Position below the total line and above the existing portal-share button
    - `data-testid="preview-pdf-button"`, `onClick={handlePreviewPDF}`, `className="min-h-[44px]"`
    - Large, outline variant matching invoice-side pattern
    - _Requirements: 1.1, 8.1_
    - _Property: CP-2_

- [x] 5. Add action-sheet items to `QuoteDetailScreen.tsx`
  - [x] 5.1 Add "Download PDF" and "Print" ListItems to the action sheet
    - "Download PDF": `data-testid="download-pdf-action"`, `onClick={handlePreviewPDF}`
    - "Print": `data-testid="print-action"`, `onClick={handlePrint}`
    - Place after existing "Share portal link" and before existing "Duplicate"
    - Explicitly do NOT add "Print POS Receipt" — no element matching that text in JSX
    - Konsta `ListItem` provides ≥ 44px height by default
    - _Requirements: 2.1, 3.1, 7.1, 8.3_
    - _Property: CP-1_

- [x] 6. Add attachments section to `QuoteDetailScreen.tsx`
  - [x] 6.1 Implement attachments carousel and empty state
    - Render `<BlockTitle>Attachments</BlockTitle>` section after Totals and before Notes/Terms
    - When `attachment_count > 0`: horizontal `overflow-x-auto` row of 96×96 thumbnails; image MIME → `<img>`, else → `<FileIcon>`; tap opens attachment URL in new tab
    - When `attachment_count === 0`: muted "No attachments" text in a `<Block>`
    - Apply `dark:border-gray-700`, `dark:text-gray-500` on borders and muted text
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 9.2_
  - [x] 6.2 Add "Take Photo" button below the carousel
    - `HapticButton` with `data-testid="take-photo-button"`, `className="min-h-[44px]"`, large outline
    - `onClick={handleTakePhoto}`
    - _Requirements: 4.1, 4.3, 8.2_
  - [x] 6.3 Add delete affordance on attachment thumbnails (draft only)
    - Render × button (`aria-label="Delete {filename}"`) on each thumbnail ONLY when `quote.status === 'draft'`
    - Do NOT render any delete affordance when status is sent, accepted, declined, or expired
    - × button: `min-h-[44px] min-w-[44px]` touch target on mobile viewports
    - On tap: show confirmation prompt, then call `handleDeleteAttachment(attachmentId)`
    - _Requirements: 6.1, 6.2, 6.3, 8.4_
    - _Property: CP-7_

- [x] 7. Write Vitest tests
  - [x] 7.1 Property test CP-1 — POS receipt absent from action sheet
    - Across all quote statuses (`draft`, `sent`, `accepted`, `declined`, `expired`), verify no element matching `/print pos receipt/i` is rendered in the action sheet, no `pos-receipt-preview` testid exists, and no navigation to `/quotes/:id/pos-receipt` occurs
    - **Property CP-1: POS receipt absent from QuoteDetailScreen action sheet**
    - **Validates: Requirements 7.1, 7.2, 7.3**
  - [x] 7.2 Property test CP-2 — PDF URL parity
    - For any valid UUID `id`, verify the constructed URL is exactly `/api/v1/quotes/${id}/pdf` with no double slashes and no URL-encoding
    - Use `fast-check` `fc.uuid()` arbitrary
    - **Property CP-2: PDF URL parity**
    - **Validates: Requirements 1.1, 1.2, 1.4, 2.2**
  - [x] 7.3 Property test CP-3 — Upload capacity caps enforced client-side
    - Verify that files > 20 MB are rejected with toast and no API call; files with disallowed MIME types are rejected; uploads are rejected when `attachment_count >= 5`
    - **Property CP-3: Upload capacity caps enforced client-side**
    - **Validates: Requirements 4.6, 4.7, 4.8**
  - [x] 7.4 Property test CP-4 — Dark-mode parity
    - Render `QuotePDFScreen` and `QuoteDetailScreen` new elements in both light and dark modes; verify no runtime errors and key elements are present
    - **Property CP-4: Dark-mode parity**
    - **Validates: Requirements 9.1, 9.2, 9.4**
  - [x] 7.5 Property test CP-5 — Touch targets ≥ 44px
    - Verify `min-h-[44px]` class is present on Preview PDF button, Take Photo button, Back button on QuotePDFScreen, and delete button touch target
    - **Property CP-5: Touch targets ≥ 44px**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**
  - [x] 7.6 Property test CP-6 — Capacitor plugin guarding
    - When `isNativePlatform()` returns false (jsdom default), verify `Camera.getPhoto` is never called; when true, verify it is called
    - **Property CP-6: Capacitor plugin guarding**
    - **Validates: Requirements 4.1, 4.3, 10.1, 10.2**
  - [x] 7.7 Property test CP-7 — Delete affordance gated on draft status
    - For each status in `{draft, sent, accepted, declined, expired}`, verify delete buttons render if and only if `status === 'draft'`
    - **Property CP-7: Delete affordance gated on draft status**
    - **Validates: Requirements 6.1, 6.2**
  - [x] 7.8 Component tests for `QuotePDFScreen`
    - Test: renders PDFViewer with correct URL; Back button navigates back; Open button calls `window.open`; error state renders without crash
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_
  - [x] 7.9 Component tests for action-sheet additions
    - Test: "Download PDF" and "Print" items are visible; tapping Download PDF navigates to `/quotes/:id/pdf`; tapping Print calls `window.print()`
    - _Requirements: 2.1, 2.2, 3.1, 3.2_
  - [x] 7.10 Component tests for attachments section
    - Test: carousel renders when `attachment_count > 0`; empty state when 0; image thumbnails for image MIME; file icon for non-image; tap opens in new tab; Take Photo button present
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 8. Checkpoint — Run mobile tests
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Version bump to 1.6.0
  - [x] 9.1 Bump version in `mobile/package.json` to `1.6.0`
    - Per design §12: ship in the same minor as `quote-invoice-parity`
    - _Requirements: (design §12)_
  - [x] 9.2 Add CHANGELOG entry
    - Add entry under `## [1.6.0]` with the four "Added" lines from design §12
    - _Requirements: (design §12)_

- [x] 10. Release — git push and rebuild
  - [x] 10.1 Commit all changes and push to branch
    - Commit message: `feat(mobile): quote detail parity — PDF preview, print, attachments (Phase 6)`
    - Push to a new feature branch (not main)
    - _Requirements: (design §13 dependency gating)_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- This spec is mobile-only (Phase 6) — no backend changes required
- Hard dependencies: `quote-pdf-print` (Phase 1 endpoint) and `quote-invoice-parity` (Phase 5 attachments) must already be deployed
- Each task references specific requirements for traceability
- Property tests validate the 7 correctness properties (CP-1 through CP-7) from the design
- Checkpoints ensure incremental validation
- All code is TypeScript/React using the existing mobile stack (Capacitor 7, Konsta UI, Tailwind)
