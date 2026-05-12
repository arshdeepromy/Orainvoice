# Requirements Document: Quote Preview Modal

## ⚠️ Conditional Implementation Notice

> **This feature is CONDITIONAL.** Phase 4 of the Quote Preview, Print & Invoice-Parity plan (`docs/QUOTE_PREVIEW_PRINT_PLAN.md`) specifies that this modal should ONLY be built if Phases 1–3 ship and staff still report the workflow is insufficient.
>
> Phase 1's `inline` Content-Disposition means "Download PDF" opens the branded PDF in a new browser tab — already a review step. Phase 3's "Copy Link" lets staff preview exactly what the customer sees. If both land and staff confirm the workflow is adequate, **this spec should be shelved indefinitely**.
>
> This spec exists so the work is ready to execute immediately if the decision is YES. It must NOT be implemented speculatively.

---

## Introduction

This document defines the requirements for the Quote Preview Modal feature (Phase 4). The feature provides an in-app HTML preview of a draft quote inside a modal dialog before sending, allowing staff to review the exact branded layout the customer will receive — without generating a PDF. Users can send the quote directly from the modal or close it to make edits. The preview renders the same Jinja2 template used for the public customer view but with security flags that suppress the Accept button and inject a "PREVIEW" watermark.

---

## Glossary

- **QuotePreviewModal**: The React dialog component that displays the rendered quote HTML in a sandboxed iframe, with Close and Send to Customer actions.
- **Preview_HTML_Endpoint**: The backend `GET /api/v1/quotes/{id}/preview-html` route that renders the quote template with safety flags and returns the HTML string.
- **Preview_Watermark**: A fixed-position orange banner injected at the top of the rendered HTML containing the text "PREVIEW — NOT THE CUSTOMER COPY", visible only when `is_preview=True`.
- **Iframe_Sandbox**: The `sandbox="allow-same-origin"` attribute on the preview iframe that blocks script execution and form submission while allowing inline styles to render.
- **QuoteDetail**: The existing React page component at `/quotes/:id` that hosts the Preview button and mounts the QuotePreviewModal.
- **Send_Endpoint**: The existing `POST /api/v1/quotes/{id}/send` route that transitions a draft quote to sent status and delivers it to the customer.
- **canSend**: A boolean derived from `quote.status === 'draft'` that gates visibility of the Preview and Send to Customer buttons.

---

## Requirements

### Requirement 1: Preview a Draft Quote Before Sending

**User Story:** As a salesperson, I want to preview a draft quote in a modal before sending it, so that I can verify the branded layout and content without generating a PDF.

#### Acceptance Criteria

1. WHEN a user clicks the "Preview" button on a draft quote, THE QuoteDetail SHALL open the QuotePreviewModal and fetch HTML from the Preview_HTML_Endpoint.
2. WHILE the preview HTML is loading, THE QuotePreviewModal SHALL display a centered loading spinner with the text "Loading preview…".
3. WHEN the Preview_HTML_Endpoint returns successfully, THE QuotePreviewModal SHALL render the HTML inside a sandboxed iframe.
4. WHEN a user clicks "Close" or presses Escape or clicks the backdrop, THE QuotePreviewModal SHALL close and leave the quote in its current status.
5. THE Preview_HTML_Endpoint SHALL render the quote using the same Jinja2 template (`quote_share.html`) as the public customer view.
6. THE Preview_HTML_Endpoint SHALL pass `can_accept=False`, `token=None`, and `is_preview=True` to the template on every invocation.

### Requirement 2: Send a Quote from the Preview Modal

**User Story:** As a salesperson, I want to send a quote directly from the preview modal, so that I can complete the review-and-send workflow in one step.

#### Acceptance Criteria

1. WHEN the preview HTML has loaded successfully, THE QuotePreviewModal SHALL display a "Send to Customer" button in the footer.
2. WHEN a user clicks "Send to Customer" in the modal, THE QuotePreviewModal SHALL call the Send_Endpoint for the current quote.
3. WHEN the Send_Endpoint returns 200 OK, THE QuotePreviewModal SHALL close, THE QuoteDetail SHALL display a success message "Quote sent to customer", and THE QuoteDetail SHALL refresh the quote data.
4. WHILE the send request is in progress, THE QuotePreviewModal SHALL disable the "Send to Customer" button and show a loading indicator.

### Requirement 3: Preview Fetch Error Handling

**User Story:** As a salesperson, I want to see a clear error message when the preview fails to render, so that I know to use an alternative review method.

#### Acceptance Criteria

1. IF the Preview_HTML_Endpoint returns an error (network failure, 500, 403, or 404), THEN THE QuotePreviewModal SHALL display an error banner with a descriptive message.
2. IF the preview fetch fails, THEN THE QuotePreviewModal SHALL hide the "Send to Customer" button and show only the "Close" button.
3. WHEN the Preview_HTML_Endpoint returns 403, THE QuotePreviewModal SHALL display "You don't have permission to preview this quote."
4. WHEN the Preview_HTML_Endpoint returns 404, THE QuotePreviewModal SHALL display "Quote not found."
5. WHEN the Preview_HTML_Endpoint returns 500 or a network error, THE QuotePreviewModal SHALL display "Could not render preview. Download the PDF to review instead."

### Requirement 4: Send Error Handling from Modal

**User Story:** As a salesperson, I want to see a clear error when sending fails from the modal, so that I can retry or take corrective action.

#### Acceptance Criteria

1. IF the Send_Endpoint returns an error, THEN THE QuotePreviewModal SHALL display the error message in the footer area and keep the modal open.
2. WHEN the Send_Endpoint returns 400 with a detail message, THE QuotePreviewModal SHALL display that detail message in the footer.
3. WHEN the Send_Endpoint returns 500, THE QuotePreviewModal SHALL display "Failed to send quote. Please try again."
4. WHEN a network error occurs during send, THE QuotePreviewModal SHALL display "Network error. Check your connection."
5. AFTER a send error is displayed, THE QuotePreviewModal SHALL allow the user to retry by clicking "Send to Customer" again.

### Requirement 5: Accept Button Absent in Preview (Security)

**User Story:** As a system operator, I want the Accept button to never appear in the preview, so that staff cannot accidentally accept a quote on behalf of a customer.

#### Acceptance Criteria

1. THE Preview_HTML_Endpoint SHALL pass `can_accept=False` unconditionally, regardless of quote status.
2. THE Preview_HTML_Endpoint SHALL pass `token=None` so that the accept form action URL cannot resolve.
3. FOR ALL quotes rendered by the Preview_HTML_Endpoint, the returned HTML SHALL NOT contain a button or input with the text "Accept".
4. FOR ALL quotes rendered by the Preview_HTML_Endpoint, the returned HTML SHALL NOT contain a form with an action containing "/accept/".

### Requirement 6: Iframe Sandbox Blocks Scripts and Forms (Security)

**User Story:** As a system operator, I want the preview iframe to block script execution and form submission, so that the preview is strictly read-only and cannot be exploited.

#### Acceptance Criteria

1. THE QuotePreviewModal SHALL render the iframe with `sandbox="allow-same-origin"` as a hardcoded string literal.
2. THE QuotePreviewModal SHALL NOT include `allow-scripts` in the iframe sandbox attribute.
3. THE QuotePreviewModal SHALL NOT include `allow-forms` in the iframe sandbox attribute.
4. THE Iframe_Sandbox attribute SHALL NOT be dynamically computed or derived from props or state.

### Requirement 7: Preview Watermark Always Visible

**User Story:** As a system operator, I want a visible "PREVIEW" watermark on every preview render, so that staff can clearly distinguish the preview from the customer-facing version.

#### Acceptance Criteria

1. WHEN `is_preview=True` is passed to the template, THE Preview_Watermark SHALL render a fixed-position banner containing the text "PREVIEW — NOT THE CUSTOMER COPY".
2. THE Preview_Watermark SHALL use a high-contrast style (orange background, black text) and z-index 9999 to overlay all content.
3. THE Preview_HTML_Endpoint SHALL always pass `is_preview=True` to the template.
4. FOR ALL HTML responses from the Preview_HTML_Endpoint, the response body SHALL contain the substring "PREVIEW".

---

## Non-Functional Requirements

### NFR-1: Authentication and Authorisation

1. THE Preview_HTML_Endpoint SHALL require a valid authenticated session (JWT).
2. THE Preview_HTML_Endpoint SHALL require the caller to have the role `org_admin` or `salesperson`.
3. IF an unauthenticated request is made to the Preview_HTML_Endpoint, THEN THE Preview_HTML_Endpoint SHALL return HTTP 401.
4. IF a user without the required role calls the Preview_HTML_Endpoint, THEN THE Preview_HTML_Endpoint SHALL return HTTP 403.

### NFR-2: Organisation Isolation

1. THE Preview_HTML_Endpoint SHALL only return quotes belonging to the caller's organisation.
2. IF a quote_id does not belong to the caller's organisation, THEN THE Preview_HTML_Endpoint SHALL return HTTP 404.

### NFR-3: No PDF Generation on Preview

1. THE Preview_HTML_Endpoint SHALL render HTML using Jinja2 only and SHALL NOT invoke WeasyPrint or any PDF generation library.

### NFR-4: No Database Writes on Preview

1. THE Preview_HTML_Endpoint SHALL perform only read operations against the database.
2. THE Preview_HTML_Endpoint SHALL NOT create, update, or delete any database records.

### NFR-5: Iframe Security

1. THE QuotePreviewModal SHALL use `srcDoc` to inject HTML into the iframe (no external URL fetch from the iframe).
2. THE Iframe_Sandbox SHALL prevent JavaScript execution inside the preview content.
3. THE Iframe_Sandbox SHALL prevent form submission inside the preview content.

---

## Out of Scope

| Item | Reason |
|------|--------|
| PDF generation in the preview endpoint | Preview is Jinja2-only for speed; PDF download is a separate existing endpoint |
| Mobile preview modal | Mobile parity is Phase 6; this spec covers desktop only |
| Print from inside the modal | Print uses `window.print()` on the QuoteDetail DOM, not the iframe content |
| Editing the quote from inside the modal | User must close the modal and click Edit separately |
| Preview of non-draft quotes via UI | The button is only visible on drafts; the endpoint works on any status but the UI does not expose it |
| Template redesign | The preview uses the existing `quote_share.html` template as-is (plus watermark) |
| Caching the preview HTML | Each click fetches fresh HTML; no localStorage or state persistence across navigations |
| `allow-scripts` in iframe | Explicitly excluded for security — the preview is read-only |
| `allow-forms` in iframe | Explicitly excluded — defence in depth against accidental Accept |

---

## Traceability Matrix

| Acceptance Criterion | Design Section | Correctness Property |
|---------------------|----------------|---------------------|
| 1.1 Preview button opens modal and fetches HTML | §4.1 Preview Fetch + Modal Open Flow | — |
| 1.2 Loading spinner while fetching | §9 Loading / Empty States | — |
| 1.3 HTML rendered in sandboxed iframe | §5.3 Frontend Component | CP-2 |
| 1.4 Close dismisses modal, preserves status | §7.2 Happy Path — Preview then Close | — |
| 1.5 Same Jinja2 template as public view | §5.1 Backend Endpoint | — |
| 1.6 Safety flags passed on every invocation | §5.1 Backend Endpoint (Postconditions) | CP-1, CP-3 |
| 2.1 Send button visible when HTML loaded | §6 Toolbar / Button Spec | — |
| 2.2 Send button calls Send_Endpoint | §4.2 Send from Modal Flow | CP-5 |
| 2.3 Success closes modal, shows message, refreshes | §4.2 Send from Modal Flow | CP-5 |
| 2.4 Send button disabled while in progress | §9 Loading / Empty States | — |
| 3.1 Error banner on fetch failure | §4.3 Error Flow, §8 Error States Matrix | — |
| 3.2 Send button hidden on fetch error | §4.3 Error Flow | — |
| 3.3 403 error message | §8 Error States Matrix | — |
| 3.4 404 error message | §8 Error States Matrix | — |
| 3.5 500/network error message | §8 Error States Matrix | — |
| 4.1 Send error displayed in footer, modal stays open | §7.4 Error Path — Send Fails | — |
| 4.2 400 detail message displayed | §8 Error States Matrix | — |
| 4.3 500 send error message | §8 Error States Matrix | — |
| 4.4 Network error message on send | §8 Error States Matrix | — |
| 4.5 Retry allowed after send error | §7.4 Error Path — Send Fails | — |
| 5.1 can_accept=False unconditionally | §5.1 Backend Endpoint | CP-1 |
| 5.2 token=None passed | §5.1 Backend Endpoint | CP-1 |
| 5.3 No Accept button in HTML | §10 CP-1 | CP-1 |
| 5.4 No accept form in HTML | §10 CP-1 | CP-1 |
| 6.1 sandbox="allow-same-origin" hardcoded | §5.3 Frontend Component | CP-2 |
| 6.2 No allow-scripts | §5.3 Frontend Component (Iframe sandbox spec) | CP-2 |
| 6.3 No allow-forms | §5.3 Frontend Component (Iframe sandbox spec) | CP-2 |
| 6.4 Sandbox not dynamically computed | §5.3 Frontend Component | CP-2 |
| 7.1 Watermark banner with PREVIEW text | §5.2 Template Change | CP-3 |
| 7.2 High-contrast style, z-index 9999 | §5.2 Template Change | CP-3 |
| 7.3 is_preview=True always passed | §5.1 Backend Endpoint | CP-3 |
| 7.4 Response contains "PREVIEW" substring | §10 CP-3 | CP-3 |
| NFR-1.1 JWT required | §2 Navigation & Access | — |
| NFR-1.2 Role gate (org_admin, salesperson) | §5.1 Backend Endpoint | — |
| NFR-2.1 Org-scoped query | §5.1 Backend Endpoint | — |
| NFR-3.1 No PDF generation | §5.1 Backend Endpoint (Postconditions) | — |
| NFR-4.1 Read-only DB operations | §5.1 Backend Endpoint (Postconditions) | — |
| NFR-5.1 srcDoc injection | §5.3 Frontend Component | CP-2 |
| CP-4 Preview button visibility | §6 Toolbar / Button Spec | CP-4 |
| CP-5 Send updates status | §4.2 Send from Modal Flow | CP-5 |
