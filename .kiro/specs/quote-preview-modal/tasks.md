# Implementation Plan: Quote Preview Modal

## ⚠️ Conditional Implementation Notice

> **This feature is CONDITIONAL.** Phase 4 of the Quote Preview, Print & Invoice-Parity plan (`docs/QUOTE_PREVIEW_PRINT_PLAN.md`) specifies that this modal should ONLY be built if Phases 1–3 ship and staff still report the workflow is insufficient.
>
> Do NOT execute these tasks speculatively. Only proceed if the decision is YES.

---

## Overview

This plan implements the Quote Preview Modal feature (Phase 4) — a rich in-app HTML preview of a draft quote inside a modal before sending. The backend renders the existing `quote_share.html` Jinja2 template with safety flags (`can_accept=False`, `token=None`, `is_preview=True`) and returns the HTML string. The frontend displays it in a sandboxed iframe within a Headless UI Dialog, with the option to send directly from the modal.

Target version: **1.6.0** across `pyproject.toml`, `frontend/package.json`, and `mobile/package.json`.

---

## Tasks

- [ ] 1. Backend — Template change: add `is_preview` watermark block
  - [ ] 1.1 Add the PREVIEW watermark conditional block to `app/templates/pdf/quote_share.html`
    - Insert `{% if is_preview %}` block immediately after `<body>`, before the container div
    - Render a fixed-position orange banner with text "PREVIEW — NOT THE CUSTOMER COPY"
    - Style: `position:fixed; top:0; left:0; right:0; background:rgba(255,165,0,0.9); color:#000; text-align:center; padding:8px; font-weight:bold; z-index:9999`
    - Only rendered when `is_preview=True` — never in the public customer view
    - _Requirements: 7.1, 7.2_

- [ ] 2. Backend — New endpoint `GET /quotes/{quote_id}/preview-html`
  - [ ] 2.1 Implement the preview-html endpoint in `app/modules/quotes/router.py`
    - Auth: `require_role("org_admin", "salesperson")`
    - Load quote scoped by `org_id` (org isolation — returns 404 if not found)
    - Load line items, org, customer context
    - Render `quote_share.html` with `can_accept=False`, `token=None`, `is_preview=True`
    - Return `{ "html": "<full HTML string>" }`
    - No PDF generation (Jinja2 only), no database writes (read-only)
    - _Requirements: 1.5, 1.6, 5.1, 5.2, 7.3, NFR-1.1, NFR-1.2, NFR-2.1, NFR-3.1, NFR-4.1_

- [ ] 3. Backend — End-to-end test `scripts/test_quote_preview_e2e.py`
  - [ ] 3.1 Write the e2e test script covering all backend acceptance criteria
    - Auth: unauthenticated request returns 401
    - Auth: user without `org_admin`/`salesperson` role returns 403
    - Org isolation: quote_id from another org returns 404
    - Happy path: valid request returns 200 with `{ "html": "..." }`
    - Response HTML contains the substring "PREVIEW"
    - Response HTML does NOT contain an "Accept" button or `/accept/` form action
    - No database writes: verify no new rows created (read-only endpoint)
    - Response is valid HTML (contains `<!DOCTYPE` or `<html`)
    - Cleanup: delete all test quotes/customers created during the test
    - _Requirements: 5.3, 5.4, 7.4, NFR-1.3, NFR-1.4, NFR-2.2, NFR-4.2_

- [ ] 4. Backend — Property tests for CP-1 and CP-3
  - [ ]* 4.1 Write property test for CP-1: Accept button absent in preview
    - **Property CP-1: Accept button absent in preview**
    - For any quote (any status, any line item configuration), the HTML returned by the preview endpoint SHALL NOT contain a button/input with text "Accept" and SHALL NOT contain a form with action containing "/accept/"
    - Use Hypothesis to generate varied quote data and verify the invariant holds
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
    - _Property: CP-1_

  - [ ]* 4.2 Write property test for CP-3: Watermark present in preview
    - **Property CP-3: Preview watermark present**
    - For any quote rendered by the preview endpoint, the HTML SHALL contain the substring "PREVIEW" within a visible banner element
    - Use Hypothesis to generate varied quote data and verify the watermark is always present
    - **Validates: Requirements 7.1, 7.3, 7.4**
    - _Property: CP-3_

- [ ] 5. Backend checkpoint
  - Ensure all backend tests pass (`scripts/test_quote_preview_e2e.py` and property tests), ask the user if questions arise.

- [ ] 6. Frontend — New `QuotePreviewModal.tsx` component
  - [ ] 6.1 Create `frontend/src/pages/quotes/QuotePreviewModal.tsx`
    - Headless UI `Dialog` with `Transition` for enter/leave animations
    - Props: `open`, `onClose`, `onSendSuccess`, `quoteId`, `quoteNumber`, `html`, `loading`, `fetchError`
    - Loading state: centered spinner with "Loading preview…" text
    - Error state: red error banner with descriptive message, footer shows only Close
    - Success state: `<iframe srcDoc={html} sandbox="allow-same-origin">` — NO `allow-scripts`, NO `allow-forms`
    - Footer: Close button (secondary) + Send to Customer button (primary, visible only when html loaded without error)
    - Send handler: calls `POST /quotes/{quoteId}/send`, on success calls `onSendSuccess`, on error shows footer error message
    - Send button disabled + loading indicator while request in progress
    - _Requirements: 1.2, 1.3, 2.1, 2.2, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 6.1, 6.2, 6.3, 6.4, NFR-5.1, NFR-5.2, NFR-5.3_

- [ ] 7. Frontend — State additions and handlers in `QuoteDetail.tsx`
  - [ ] 7.1 Add preview state and handlers to `frontend/src/pages/quotes/QuoteDetail.tsx`
    - Add state: `previewOpen`, `previewHtml`, `previewLoading`, `previewError`
    - Add `handlePreview`: sets loading, opens modal, fetches `GET /api/v1/quotes/{id}/preview-html`, sets html or error
    - Add `handlePreviewSendSuccess`: closes modal, clears html, shows success message "Quote sent to customer", calls `fetchQuote()`
    - Mount `QuotePreviewModal` conditionally when `previewOpen` is true
    - Pass `onClose` that resets all preview state
    - _Requirements: 1.1, 1.4, 2.3_

- [ ] 8. Frontend — Preview button placement (conditional on canSend)
  - [ ] 8.1 Add "Preview" button to the QuoteDetail action bar
    - Variant: `secondary`
    - Visible when: `quote.status === 'draft'` (same `canSend` condition as Send to Customer)
    - Disabled when: `actionLoading` or `previewLoading`
    - Position: between Edit and Send to Customer
    - onClick: calls `handlePreview`
    - _Requirements: 1.1_
    - _Property: CP-4_

- [ ] 9. Frontend — Component tests for QuotePreviewModal
  - [ ]* 9.1 Write component tests for `QuotePreviewModal.tsx`
    - Test loading state renders spinner and "Loading preview…" text
    - Test error state renders error banner and hides Send button
    - Test iframe has `sandbox="allow-same-origin"` attribute (no allow-scripts, no allow-forms)
    - Test successful send calls `onSendSuccess` and closes modal
    - Test send error keeps modal open and displays error in footer
    - Test Close button calls `onClose`
    - _Requirements: 1.2, 2.1, 3.1, 3.2, 4.1, 6.1_

- [ ] 10. Frontend — Property tests for CP-2, CP-4, CP-5
  - [ ]* 10.1 Write property test for CP-2: Iframe sandbox blocks scripts and forms
    - **Property CP-2: Iframe sandbox blocks scripts and forms**
    - For any rendered state of QuotePreviewModal where the iframe is visible, the iframe element SHALL have `sandbox="allow-same-origin"` and SHALL NOT include `allow-scripts` or `allow-forms`
    - Use fast-check to generate varied props (different html strings, quote numbers) and verify the sandbox attribute is always exactly `"allow-same-origin"`
    - **Validates: Requirements 6.1, 6.2, 6.3**
    - _Property: CP-2_

  - [ ]* 10.2 Write property test for CP-4: Preview button visibility
    - **Property CP-4: Preview button visibility**
    - For any quote status, the Preview button renders if and only if `quote.status === 'draft'`
    - Use fast-check to generate all possible quote statuses and verify button presence/absence
    - **Validates: Requirement 1.1**
    - _Property: CP-4_

  - [ ]* 10.3 Write property test for CP-5: Send from modal updates quote status
    - **Property CP-5: Send from modal updates quote status**
    - For any successful POST /quotes/{id}/send triggered from the modal, the modal SHALL close (previewOpen becomes false) and the quote status SHALL transition to sent
    - Mock the API, verify `onSendSuccess` is called which triggers modal close and quote refresh
    - **Validates: Requirements 2.2, 2.3**
    - _Property: CP-5_

- [ ] 11. Frontend checkpoint
  - Ensure all frontend tests pass (component tests and property tests via `vitest --run`), ask the user if questions arise.

- [ ] 12. Version bump to 1.6.0 and CHANGELOG update
  - [ ] 12.1 Bump version to 1.6.0 in all three packages
    - Update `pyproject.toml` version from `1.5.0` to `1.6.0`
    - Update `frontend/package.json` version from `1.5.0` to `1.6.0`
    - Update `mobile/package.json` version from `1.5.0` to `1.6.0` (no-op bump for three-way alignment)
    - _Requirements: (versioning steering rule)_

  - [ ] 12.2 Add CHANGELOG.md entry for 1.6.0
    - Add entry under `## [1.6.0] - YYYY-MM-DD` with:
      - **Added:** Quotes: Preview modal for reviewing quote HTML before sending
      - **Added:** Quotes: `GET /api/v1/quotes/{id}/preview-html` backend endpoint (Jinja2-only, no PDF)
      - **Added:** Quotes: PREVIEW watermark banner on staff-only preview renders
      - **Changed:** mobile: version bumped to 1.6.0 (no functional change) to align with backend + frontend
    - _Requirements: (versioning steering rule)_

- [ ] 13. Release — git push and rebuild
  - [ ] 13.1 Commit, push to main, and rebuild production
    - Stage all changed files
    - Commit with message: `feat(quotes): add preview modal before sending (Phase 4) — v1.6.0`
    - Push to `main` branch on GitHub
    - Sync to Pi via tar+SSH and rebuild app container
    - _Requirements: (deployment process)_

- [ ] 14. Final checkpoint
  - Ensure all tests pass end-to-end on production, ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests validate universal correctness properties from the design document
- The backend uses Python (FastAPI, Jinja2, Hypothesis for property tests)
- The frontend uses TypeScript (React, Headless UI, Vitest + fast-check for property tests)
- Checkpoints ensure incremental validation at each layer boundary
- This feature targets desktop only — mobile parity is Phase 6 (out of scope)
