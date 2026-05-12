# Requirements Document

## Introduction

Close three closely related gaps on `QuoteDetail.tsx` (Phases 1–3 of `docs/QUOTE_PREVIEW_PRINT_PLAN.md`) in one release (`1.5.0`): expose the existing `generate_quote_pdf()` service as `GET /api/v1/quotes/{quote_id}/pdf`, add Download PDF and browser Print buttons plus print-only CSS to the quote detail page, and surface the already-persisted `acceptance_token` via a Copy Link button that writes the public share URL to the clipboard. Behaviour and security posture deliberately mirror the existing invoice PDF endpoint and invoice detail page, so org_admin and salesperson users get the same PDF / Print / Share affordances for quotes that they already have for invoices. No database migration, no new environment variables, no new dependencies, and no new audit-log entries are introduced.

## Glossary

- **Quote_Record**: A row in the `quotes` table, scoped by `org_id`, identified by `quote_id`, optionally carrying a `quote_number` and an `acceptance_token`.
- **Quote_Number**: The human-facing identifier on a `Quote_Record` (for example `QUO-0001`). May be null for draft quotes that have not been numbered yet.
- **Acceptance_Token**: The opaque token stored on a `Quote_Record` and returned by `GET /api/v1/quotes/{quote_id}`. It is non-null once the quote has been sent at least once, and is the key used by the public share route.
- **Share_URL**: The URL of the form `${window.location.origin}/api/v1/public/quotes/view/${Acceptance_Token}` that allows a customer to view and accept a quote without authentication.
- **Public_Quote_View**: The existing unauthenticated endpoint `GET /api/v1/public/quotes/view/{token}` mounted in `app/main.py`; not modified by this feature.
- **Quote_PDF_Endpoint**: The new backend endpoint `GET /api/v1/quotes/{quote_id}/pdf` added by this feature.
- **Quote_PDF_Service**: The existing function `generate_quote_pdf()` in `app/modules/quotes/service.py`, which renders `quote_share.html` via Jinja2 and converts it to PDF bytes via WeasyPrint.
- **QuoteDetail_Page**: The React page `frontend/src/pages/quotes/QuoteDetail.tsx` mounted at the route `/quotes/:id` behind `RequireAuth`.
- **Action_Bar**: The right-aligned button group in the `QuoteDetail_Page` header row containing all quote actions.
- **Download_PDF**: The action, and corresponding button, that fetches `Quote_PDF_Endpoint` as a Blob and triggers a browser download dialog.
- **Print_Browser**: The action, and corresponding button, that calls `window.print()` on the `QuoteDetail_Page` DOM with `Print_Styles` applied.
- **Print_Styles**: The CSS block injected into `document.head` inside a `<style data-quote-print="true">` element on mount of `QuoteDetail_Page` and removed on unmount; it hides `[data-print-hide]` elements and expands `[data-print-content]`.
- **Copy_Link**: The action, and corresponding button, that writes the `Share_URL` to the clipboard via `navigator.clipboard.writeText`.
- **Downloading_State**: The local boolean `downloading` on `QuoteDetail_Page` that is `true` from the start of a `Download_PDF` handler call until that call terminates, and `false` otherwise.
- **Copied_State**: The local boolean `copied` on `QuoteDetail_Page` that is `true` for exactly 2000 ms after a successful `Copy_Link` action and `false` otherwise.
- **Error_Banner**: The existing red banner on `QuoteDetail_Page` driven by the `error` state variable; reused without modification for all new failure paths.
- **Org_Admin**: A user holding the `org_admin` role in the current organisation.
- **Salesperson**: A user holding the `salesperson` role in the current organisation.
- **Org_Context**: The organisation UUID extracted from the request via `_extract_org_context(request)`; used to scope `Quote_PDF_Service` lookups.

## Requirements

### Requirement 1: Backend PDF Endpoint

**User Story:** As a salesperson or org_admin, I want to download a branded PDF copy of any quote from the browser, so that I can archive it, attach it to other correspondence, or hand it to a customer in person.

#### Acceptance Criteria

1. THE Quote_PDF_Endpoint SHALL be exposed at `GET /api/v1/quotes/{quote_id}/pdf`.
2. THE Quote_PDF_Endpoint SHALL require the caller to hold the `org_admin` or `salesperson` role via `require_role("org_admin", "salesperson")`.
3. WHEN the Quote_PDF_Endpoint receives an authenticated request with a valid Org_Context and an existing `quote_id` for that organisation, THE Quote_PDF_Endpoint SHALL respond with HTTP 200, `Content-Type: application/pdf`, and a body beginning with the bytes `%PDF-`.
4. WHEN the Quote_PDF_Endpoint responds with HTTP 200, THE Quote_PDF_Endpoint SHALL set the `Content-Disposition` header to the exact value `inline; filename="<name>.pdf"` where `<name>` is the `Quote_Number` when non-null and the literal string `DRAFT` otherwise.
5. IF the request is unauthenticated, THEN THE Quote_PDF_Endpoint SHALL respond with HTTP 401.
6. IF the authenticated caller does not hold the `org_admin` or `salesperson` role, THEN THE Quote_PDF_Endpoint SHALL respond with HTTP 403.
7. IF the request does not carry a valid Org_Context, THEN THE Quote_PDF_Endpoint SHALL respond with HTTP 403 and a JSON body `{"detail": "Organisation context required"}`.
8. IF the `quote_id` does not exist in the caller's organisation, THEN THE Quote_PDF_Endpoint SHALL respond with HTTP 404 and SHALL NOT emit PDF bytes.
9. THE Quote_PDF_Endpoint SHALL delegate PDF rendering to the existing Quote_PDF_Service without modifying that service.
10. THE Quote_PDF_Endpoint SHALL NOT perform any database writes.
11. THE Quote_PDF_Endpoint SHALL NOT write an audit log entry on download.

### Requirement 2: Download a PDF Copy of a Quote at Any Status

**User Story:** As a salesperson or org_admin viewing a quote, I want a Download PDF button in the action bar that works for quotes in any status, so that I can retrieve the branded PDF regardless of whether the quote is draft, sent, accepted, declined, expired, or converted.

#### Acceptance Criteria

1. WHEN the QuoteDetail_Page has finished loading a Quote_Record, THE QuoteDetail_Page SHALL render a Download_PDF button in the Action_Bar.
2. THE Download_PDF button SHALL be rendered for every value of `quote.status` including `draft`, `sent`, `accepted`, `declined`, `expired`, and quotes with a non-null `converted_invoice_id`.
3. WHEN the user clicks the Download_PDF button, THE QuoteDetail_Page SHALL set Downloading_State to `true` before issuing the network request.
4. WHEN Downloading_State is `true`, THE Download_PDF button SHALL be disabled and SHALL display the label `Downloading…`.
5. WHEN the user clicks the Download_PDF button, THE QuoteDetail_Page SHALL call `apiClient.get` with the path `/quotes/${quote.id}/pdf` and `responseType: 'blob'`.
6. WHEN the Quote_PDF_Endpoint returns HTTP 200, THE QuoteDetail_Page SHALL wrap the response body in an object URL, trigger a synthetic `<a download="<name>.pdf">` click where `<name>` is `quote.quote_number` when non-null and `DRAFT` otherwise, and revoke the object URL after triggering the download.
7. WHEN the Download_PDF handler terminates, whether by success or failure, THE QuoteDetail_Page SHALL set Downloading_State to `false`.

### Requirement 3: Print a Quote to a Physical Printer or Save-as-PDF

**User Story:** As a salesperson or org_admin, I want a Print button in the action bar that opens the browser print dialog with a clean, app-chrome-free layout, so that I can print the quote on a physical printer or save it as a PDF using the browser's Save-as-PDF destination.

#### Acceptance Criteria

1. WHEN the QuoteDetail_Page has finished loading a Quote_Record, THE QuoteDetail_Page SHALL render a Print_Browser button in the Action_Bar.
2. THE Print_Browser button SHALL be rendered for every value of `quote.status`.
3. WHEN the QuoteDetail_Page mounts, THE QuoteDetail_Page SHALL append exactly one `<style data-quote-print="true">` element to `document.head` containing the Print_Styles CSS.
4. WHEN the QuoteDetail_Page unmounts, THE QuoteDetail_Page SHALL remove the `<style data-quote-print="true">` element from `document.head`.
5. WHEN the user clicks the Print_Browser button, THE QuoteDetail_Page SHALL call `window.print()` synchronously without setting any loading or error state.
6. WHILE the browser is applying `@media print` rules, THE Print_Styles SHALL hide every element carrying the `data-print-hide` attribute and SHALL expand the element carrying the `data-print-content` attribute to full page width with no shadow or border.
7. THE QuoteDetail_Page SHALL apply the `data-print-hide` attribute to the back arrow, the Action_Bar container, the Error_Banner, the success banner, and the converted-invoice notice banner.
8. THE QuoteDetail_Page SHALL apply the `data-print-content` attribute to the quote card container that holds the quote info grid, line items table, totals panel, and notes and terms.

### Requirement 4: Share a Quote Link With a Customer Who Has Lost the Email

**User Story:** As a salesperson or org_admin whose customer has lost the email containing a quote, I want a Copy Link button that copies the public Share_URL for the quote to my clipboard, so that I can resend or read the URL to the customer without regenerating the token or re-sending the quote.

#### Acceptance Criteria

1. WHERE the loaded Quote_Record has a non-empty `acceptance_token`, THE QuoteDetail_Page SHALL render a Copy_Link button in the Action_Bar.
2. WHERE the loaded Quote_Record has `acceptance_token` equal to `null`, `undefined`, or the empty string, THE QuoteDetail_Page SHALL NOT render a Copy_Link button.
3. WHEN the user clicks the Copy_Link button, THE QuoteDetail_Page SHALL call `navigator.clipboard.writeText` with the Share_URL computed as exactly `${window.location.origin}/api/v1/public/quotes/view/${quote.acceptance_token}` with no URL-encoding applied to the token and no trailing slash.
4. WHEN the clipboard write resolves successfully, THE QuoteDetail_Page SHALL set Copied_State to `true`.
5. WHILE Copied_State is `true`, THE Copy_Link button SHALL display the label `Copied!`.
6. WHEN Copied_State has been `true` for 2000 ms, THE QuoteDetail_Page SHALL set Copied_State to `false` and the Copy_Link button SHALL revert to the label `Copy Link`.
7. THE Copy_Link action SHALL NOT issue any network request and SHALL NOT mutate the Quote_Record on the server.

### Requirement 5: Get a Clear Error When the Clipboard Is Not Available

**User Story:** As a salesperson or org_admin using a browser where the clipboard API is unavailable or denied, I want a clear error message when a Copy Link attempt fails, so that I know to copy the URL by another means rather than silently believing the link was copied.

#### Acceptance Criteria

1. IF `navigator.clipboard.writeText` rejects, THEN THE QuoteDetail_Page SHALL set the Error_Banner text to the exact string `Could not copy link to clipboard. Please copy manually.`.
2. IF `navigator.clipboard.writeText` rejects, THEN THE QuoteDetail_Page SHALL leave Copied_State set to `false`.
3. IF `navigator.clipboard.writeText` rejects, THEN THE QuoteDetail_Page SHALL NOT change the label of the Copy_Link button to `Copied!`.

### Requirement 6: Get a Clear Error When PDF Generation Fails

**User Story:** As a salesperson or org_admin, I want a clear error message when a Download PDF attempt fails, so that I can retry or navigate away rather than being left with a stuck button or no feedback.

#### Acceptance Criteria

1. IF the Quote_PDF_Endpoint returns any non-2xx status other than 401, THEN THE QuoteDetail_Page SHALL set the Error_Banner text to the backend-provided `detail` string when present, or the exact fallback string `Failed to download PDF. Please try again.` otherwise.
2. IF the network request underlying the Download_PDF handler fails before a response is received, THEN THE QuoteDetail_Page SHALL set the Error_Banner text to `Failed to download PDF. Please try again.`.
3. IF the Quote_PDF_Endpoint returns HTTP 401, THEN THE QuoteDetail_Page SHALL rely on the existing global axios 401 interceptor for refresh or redirect and SHALL NOT set its own Error_Banner text.
4. IF the Download_PDF handler enters its error branch, THEN THE QuoteDetail_Page SHALL still set Downloading_State to `false` via its `finally` block.
5. IF the Download_PDF handler enters its error branch, THEN THE QuoteDetail_Page SHALL NOT trigger a browser download dialog.

### Requirement 7: Authentication and Organisation Isolation

**User Story:** As a platform operator, I want the PDF endpoint to match the invoice PDF endpoint's security posture, so that quote PDFs inherit proven auth, role, and org-isolation guarantees without introducing new asymmetry.

#### Acceptance Criteria

1. THE Quote_PDF_Endpoint SHALL enforce authentication via the existing auth middleware shared with all `/api/v1/quotes` routes.
2. THE Quote_PDF_Endpoint SHALL enforce role gating via `require_role("org_admin", "salesperson")`, identical to `POST /api/v1/quotes/{id}/send` and to `GET /api/v1/invoices/{id}/pdf`.
3. WHEN the Quote_PDF_Service receives an Org_Context, THE Quote_PDF_Service SHALL load the Quote_Record using both `Quote.id == quote_id` and `Quote.org_id == org_id`, producing HTTP 404 at the endpoint layer for any cross-organisation access attempt.
4. THE Quote_PDF_Endpoint SHALL NOT introduce any org-isolation logic of its own beyond propagating the Org_Context to the Quote_PDF_Service.

### Requirement 8: Rate Limiting

**User Story:** As a platform operator, I want the quote PDF endpoint to inherit the same rate-limiting posture as the invoice PDF endpoint, so that abuse mitigation is applied symmetrically across both PDF surfaces.

#### Acceptance Criteria

1. THE Quote_PDF_Endpoint SHALL NOT declare an endpoint-specific rate limit.
2. THE Quote_PDF_Endpoint SHALL inherit the existing global per-organisation rate limit configured in `app/middleware/rate_limit.py`.

### Requirement 9: No Audit Log on Download

**User Story:** As a platform operator, I want the quote PDF endpoint to match the invoice PDF endpoint's audit-log behaviour, so that introducing audit logging for PDF downloads is a future cross-cutting decision applied to both invoices and quotes together rather than creating asymmetry in this release.

#### Acceptance Criteria

1. THE Quote_PDF_Endpoint SHALL NOT write any row to the audit log table on a successful PDF response.
2. THE Quote_PDF_Endpoint SHALL NOT write any row to the audit log table on an error response.

### Requirement 10: No New Database Migration, No New Environment Variables

**User Story:** As a platform operator, I want this feature to ship without any database schema changes or new configuration, so that deployment risk is limited to application code and the feature can roll out alongside the existing alembic head.

#### Acceptance Criteria

1. THE feature SHALL NOT add any Alembic migration.
2. THE feature SHALL NOT add any new column to the `quotes` table or the `quote_line_items` table.
3. THE feature SHALL NOT require any new environment variable in `.env`, `.env.pi`, `.env.standby-prod`, or any other deployment `.env` file.
4. THE feature SHALL NOT add any new runtime dependency to `pyproject.toml`, `frontend/package.json`, or `mobile/package.json`.

## Traceability Matrix

| Acceptance Criterion | Design Section(s) | Property | e2e Test Case |
|---|---|---|---|
| 1.1 | Backend — new endpoint (router signature) | — | 1 |
| 1.2 | Backend — new endpoint; Security & Rate-Limiting (Auth) | — | 7, 8 |
| 1.3 | Backend — new endpoint (algorithm, postconditions); Response parity table | — | 1, 2, 3 |
| 1.4 | Backend — new endpoint (algorithm); Response parity table (Content-Disposition, Filename fallback) | P3 | 1, 9, 10 |
| 1.5 | Security & Rate-Limiting (Auth); Error States Matrix (401 row) | — | 4 |
| 1.6 | Security & Rate-Limiting (Auth) | — | 8 |
| 1.7 | Backend — new endpoint (algorithm: `if not org_uuid`) | — | — |
| 1.8 | Backend — new endpoint (algorithm, ValueError branch); Security & Rate-Limiting (Org isolation) | P4 | 5, 6 |
| 1.9 | Backend — new endpoint (imports, delegation); Dependencies table | — | 1 |
| 1.10 | Backend — new endpoint (postconditions) | — | — |
| 1.11 | Security & Rate-Limiting (Audit log); Response parity table (Audit log row) | — | — |
| 2.1 | Component Tree; Toolbar / Action-Bar Specification | — | — |
| 2.2 | Component Tree (Download PDF "always visible"); Toolbar matrix (Visible when = always) | — | — |
| 2.3 | Low-Level Design — `handleDownloadPDF` (setDownloading(true) precondition) | P6 | — |
| 2.4 | Toolbar / Action-Bar Specification (Label busy, Disabled when); Loading / Empty States | P6 | — |
| 2.5 | Low-Level Design — `handleDownloadPDF` (apiClient.get call); High-Level Design — Download PDF flow | — | 1 |
| 2.6 | Low-Level Design — `handleDownloadPDF` (URL.createObjectURL + `<a download>`); Rendered button JSX | — | — |
| 2.7 | Low-Level Design — `handleDownloadPDF` (finally block); User Workflow Trace — Happy path Download PDF | P6 | — |
| 3.1 | Component Tree; Toolbar / Action-Bar Specification (Print row) | — | — |
| 3.2 | Toolbar matrix (Visible when = always) | — | — |
| 3.3 | Low-Level Design — Print-styles injection (useEffect on mount) | P2 | — |
| 3.4 | Low-Level Design — Print-styles injection (cleanup return); User Workflow Trace — Unmount while download in flight | P2 | — |
| 3.5 | Low-Level Design — `handlePrint`; User Workflow Trace — Happy path Browser Print | — | — |
| 3.6 | Print CSS — `PRINT_STYLES`; `data-print-*` selector list | — | — |
| 3.7 | `data-print-*` selector list (rows for back arrow, action bar, banners, converted-invoice notice) | — | — |
| 3.8 | `data-print-*` selector list (row for the white quote card with `data-print-content`) | — | — |
| 4.1 | Component Tree (Copy Link visibility); Toolbar matrix (Visible when = `acceptance_token !== null`) | P5 | — |
| 4.2 | Toolbar matrix (Visible when); Rendered button JSX (`{quote.acceptance_token && ...}`) | P5 | — |
| 4.3 | Low-Level Design — `handleCopyLink` (shareUrl construction); High-Level Design — Copy Link flow | P1 | — |
| 4.4 | Low-Level Design — `handleCopyLink` (setCopied(true) branch); User Workflow Trace — Happy path Copy Link | — | — |
| 4.5 | Toolbar / Action-Bar Specification (Copy Link label dynamic); Rendered button JSX | — | — |
| 4.6 | Low-Level Design — `handleCopyLink` (setTimeout 2000); User Workflow Trace — Happy path Copy Link | — | — |
| 4.7 | High-Level Design — Copy Link flow ("no backend, no network"); Integration Points (Existing Send flow unchanged) | — | — |
| 5.1 | Low-Level Design — `handleCopyLink` (catch branch); Error States Matrix (`navigator.clipboard.writeText` rejects) | — | — |
| 5.2 | Low-Level Design — `handleCopyLink` (catch branch leaves `copied` false); User Workflow Trace — Error path Clipboard denied | — | — |
| 5.3 | Low-Level Design — `handleCopyLink` (catch branch) | — | — |
| 6.1 | Low-Level Design — `handleDownloadPDF` (catch branch, `detail ?? fallback`); Error States Matrix (500 / 404 / 403 rows) | — | — |
| 6.2 | Low-Level Design — `handleDownloadPDF` (catch branch); Error States Matrix (network failure row) | — | — |
| 6.3 | Error States Matrix (401 row — handled by global axios interceptor); User Workflow Trace — Error path 401 | — | — |
| 6.4 | Low-Level Design — `handleDownloadPDF` (finally block) | P6 | — |
| 6.5 | Low-Level Design — `handleDownloadPDF` (catch branch — no `<a>.click()` path); User Workflow Trace — Error path 500 | — | — |
| 7.1 | Navigation & Access (Backend guard); Security & Rate-Limiting (Auth) | — | 4 |
| 7.2 | Navigation & Access (Backend guard); Security & Rate-Limiting (Auth); Response parity table (Auth row) | — | 7, 8 |
| 7.3 | Security & Rate-Limiting (Org isolation); Backend — new endpoint (algorithm — service-layer scoping) | P4 | 5 |
| 7.4 | Security & Rate-Limiting (Org isolation); Response parity table (Org isolation row) | P4 | 5 |
| 8.1 | Security & Rate-Limiting (Rate limiting); Response parity table (Rate limiting row) | — | — |
| 8.2 | Security & Rate-Limiting (Rate limiting) | — | — |
| 9.1 | Security & Rate-Limiting (Audit log); Response parity table (Audit log row) | — | — |
| 9.2 | Security & Rate-Limiting (Audit log) | — | — |
| 10.1 | Dependencies ("No Alembic migration"); Backend — new endpoint (Response parity table — Migration row) | — | — |
| 10.2 | Dependencies; Out of Scope (attachments, parity columns excluded) | — | — |
| 10.3 | Dependencies ("No new env vars") | — | — |
| 10.4 | Dependencies ("No new packages added") | — | — |

**Property reference (from `design.md` — Correctness Properties):**

- **P1** — Share URL format is exact
- **P2** — Print style tag cleanup is unconditional
- **P3** — Content-Disposition filename invariant
- **P4** — Org isolation is absolute (stated, tested in e2e)
- **P5** — Copy Link button visibility parity with token presence
- **P6** — Download state is monotonic within a single click

**e2e test case reference (from `design.md` — Testing Strategy → e2e test — backend, `scripts/test_quote_pdf_e2e.py`):**

1. Org_admin → draft quote → 200 + `%PDF-` body
2. Org_admin → sent quote → 200
3. Org_admin → accepted quote → 200
4. No token → 401
5. Wrong org's `quote_id` → 404 (org isolation)
6. Non-existent `quote_id` → 404
7. Salesperson → 200 (not blocked)
8. Non-permitted role (e.g. viewer) → 403
9. `Content-Disposition` contains quote number for numbered quotes
10. `Content-Disposition` contains `DRAFT` for unnumbered quotes
11. Cleanup verification of `TEST_E2E_` prefixed rows
