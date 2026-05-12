# Implementation Plan: quote-pdf-print

## Overview

Ship Phases 1–3 of `docs/QUOTE_PREVIEW_PRINT_PLAN.md` as `1.5.0` in one PR:

1. New backend endpoint `GET /api/v1/quotes/{quote_id}/pdf` that thin-wraps the existing `generate_quote_pdf()` service, with role gate and org-isolation mirroring `GET /api/v1/invoices/{id}/pdf`.
2. `QuoteDetail.tsx` gains Print, Download PDF, and (conditionally) Copy Link buttons, plus a print-only `<style>` block injected on mount and removed on unmount.
3. Version bumps across `pyproject.toml`, `frontend/package.json`, `mobile/package.json`, a CHANGELOG entry, and a prod deploy verification via the standard tar+SSH + docker rebuild flow on the Pi.

Tasks are ordered by layer: backend first (so the frontend has something real to call during its tests), frontend second, property and e2e tests kept close to the code they validate, then checkpoints, then release.

## Tasks

- [x] 1. Backend — add quote PDF endpoint to `app/modules/quotes/router.py`
  - [x] 1.1 Implement `GET /{quote_id}/pdf` endpoint
    - Add `get_quote_pdf_endpoint(quote_id, request, db)` at the path `GET /{quote_id}/pdf` on the existing `router` object in `app/modules/quotes/router.py`
    - Register it with `dependencies=[require_role("org_admin", "salesperson")]` and `responses={200, 401, 403, 404}` matching the signature block in `design.md` → _Low-Level Design — Backend — new endpoint_
    - Call `_extract_org_context(request)` and return `JSONResponse(403, {"detail": "Organisation context required"})` when `org_uuid` is falsy
    - Wrap `await generate_quote_pdf(db, org_id=org_uuid, quote_id=quote_id)` in `try/except ValueError` returning `JSONResponse(404, {"detail": str(exc)})`
    - Fetch `quote_dict = await get_quote(db, org_id=org_uuid, quote_id=quote_id)` and compute `filename = f"{quote_dict.get('quote_number') or 'DRAFT'}.pdf"`
    - Return `Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})`
    - Add `from app.modules.quotes.service import generate_quote_pdf` to the existing import block (do NOT add `fastapi.responses.Response` — already imported)
    - Do not write to the database, do not write to the audit log, do not add a route-specific rate limit
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 9.1, 9.2, 10.1, 10.2, 10.3, 10.4_

- [x] 2. Backend — e2e test script `scripts/test_quote_pdf_e2e.py`
  - Create a new e2e script following the template in `.kiro/steering/feature-testing-workflow.md` (asyncio + httpx, base URL `http://localhost:8000`, `TEST_E2E_` prefix on every created row, cleanup in `finally`)
  - Run with `docker exec invoicing-app-1 python scripts/test_quote_pdf_e2e.py`

  - [x] 2.1 Test case 1 — `org_admin` → draft quote → 200 + `%PDF-` body
    - Login as `org_admin`, create a `TEST_E2E_` customer and draft quote, `GET /api/v1/quotes/{id}/pdf`
    - Assert 200, `Content-Type: application/pdf`, body starts with `b"%PDF-"`, `Content-Disposition` starts with `inline; filename="`
    - _Requirements: 1.1, 1.2, 1.3, 1.9_

  - [x] 2.2 Test case 2 — `org_admin` → sent quote → 200
    - Promote the draft to `sent` via `POST /api/v1/quotes/{id}/send` (or direct SQL if email is stubbed), then re-fetch the PDF
    - Assert 200 and `%PDF-` body
    - _Requirements: 1.3_

  - [x] 2.3 Test case 3 — `org_admin` → accepted quote → 200
    - Mark the quote `accepted` (via the public accept endpoint or direct SQL on the test quote), re-fetch
    - Assert 200 and `%PDF-` body
    - _Requirements: 1.3_

  - [x] 2.4 Test case 4 — no token → 401
    - Fire `GET /api/v1/quotes/{id}/pdf` with no `Authorization` header
    - Assert HTTP 401
    - _Requirements: 1.5, 7.1_

  - [x] 2.5 Test case 5 — wrong org's `quote_id` → 404 (org isolation)
    - Create a second `TEST_E2E_` org with its own `org_admin` and its own quote
    - Authenticate as the first org's `org_admin` and request the second org's `quote_id`
    - Assert 404 (not 403) — confirms service-layer scoping is the isolation boundary
    - _Requirements: 1.8, 7.3, 7.4_ _Property: P4_

  - [x] 2.6 Test case 6 — non-existent `quote_id` → 404
    - Request a freshly generated random UUID not present in the DB
    - Assert 404
    - _Requirements: 1.8_

  - [x] 2.7 Test case 7 — `salesperson` → 200 (not blocked)
    - Create a `TEST_E2E_` salesperson user in the first org, authenticate, fetch the PDF
    - Assert 200 and `%PDF-` body
    - _Requirements: 1.2, 7.2_

  - [x] 2.8 Test case 8 — non-permitted role → 403
    - Create a `TEST_E2E_` user with a non-permitted role (for example `viewer` or `branch_user`, whichever the RBAC layer treats as not matching `org_admin` or `salesperson`), authenticate, fetch the PDF
    - Assert 403
    - _Requirements: 1.6, 7.2_

  - [x] 2.9 Test case 9 — `Content-Disposition` contains quote number for numbered quotes
    - Using the sent quote from 2.2 (which must have a non-null `quote_number`), assert the `Content-Disposition` header contains the exact `quote_number` substring and ends with `.pdf"`
    - _Requirements: 1.4_ _Property: P3_

  - [x] 2.10 Test case 10 — `Content-Disposition` contains `DRAFT` for unnumbered quotes
    - Using a draft quote with `quote_number IS NULL` (create via direct SQL if the service auto-numbers on save), assert `Content-Disposition: inline; filename="DRAFT.pdf"`
    - _Requirements: 1.4_ _Property: P3_

  - [x] 2.11 Test case 11 — cleanup verification of `TEST_E2E_` prefixed rows
    - In the `finally` block, delete every created quote, customer, user, and org in reverse dependency order
    - After cleanup, run a direct asyncpg query for rows whose name/email starts with `TEST_E2E_`; if any remain, record a failure
    - _Requirements: (test discipline — `.kiro/steering/feature-testing-workflow.md` cleanup rule)_

- [x] 3. Backend — property test for P3 (`tests/test_quote_pdf_filename_property.py`)
  - [x] 3.1 Write Hypothesis property test for Content-Disposition filename invariant
    - Create `tests/test_quote_pdf_filename_property.py` (sibling to existing `tests/test_invoice_content_property.py`)
    - **Property P3: Content-Disposition filename invariant**
    - Strategy: `quote_number` is `st.one_of(st.none(), st.text(alphabet=st.characters(whitelist_categories=("L","N"), whitelist_characters="-_"), min_size=1, max_size=40))`
    - Assert the constructed header matches `^inline; filename="([^"]+)\.pdf"$` and the captured `<name>` equals `quote_number or "DRAFT"` and is never the empty string
    - Use `@settings(suppress_health_check=[HealthCheck.too_slow])` if needed to keep CI stable
    - **Validates: Requirement 1.4**

- [x] 4. Backend checkpoint — run backend-only tests
  - Run `docker exec invoicing-app-1 pytest tests/test_quote_pdf_filename_property.py -v` and confirm pass
  - Run `docker exec invoicing-app-1 pytest tests/ -v --ignore=tests/e2e -x` to confirm the new endpoint did not regress any existing backend test
  - Run `docker exec invoicing-app-1 python scripts/test_quote_pdf_e2e.py` and confirm all 11 cases pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Frontend — state additions and handlers in `frontend/src/pages/quotes/QuoteDetail.tsx`
  - [x] 5.1 Add `downloading` and `copied` local state
    - Add `const [downloading, setDownloading] = useState<boolean>(false)` alongside the existing `loading`, `actionLoading`, `error`, `successMsg`, `deleteConfirm` state
    - Add `const [copied, setCopied] = useState<boolean>(false)` immediately after
    - Do not rename or remove any existing state
    - _Requirements: 2.3, 2.4, 4.4_

  - [x] 5.2 Implement `handleDownloadPDF`
    - Write an async function matching the body in `design.md` → _Low-Level Design — Handler: `handleDownloadPDF`_
    - Guard `if (!quote) return` first, then `setDownloading(true); setError(null)`
    - Call `apiClient.get(\`/quotes/${quote.id}/pdf\`, { responseType: 'blob' })`
    - On success: `URL.createObjectURL(res.data as Blob)`, create an `<a>` with `download = \`${quote.quote_number || 'DRAFT'}.pdf\``, `a.click()`, `URL.revokeObjectURL(url)`
    - On failure: read `detail` from `err.response?.data?.detail` and `setError(detail ?? 'Failed to download PDF. Please try again.')`
    - Wrap the cleanup in a `finally` that calls `setDownloading(false)`
    - Do not call `setError` for 401 — rely on the global axios interceptor
    - _Requirements: 2.3, 2.5, 2.6, 2.7, 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 5.3 Implement `handlePrint`
    - Write a synchronous function `const handlePrint = (): void => { window.print() }`
    - No state, no error handling, no loading flag
    - _Requirements: 3.5_

  - [x] 5.4 Implement `handleCopyLink`
    - Write an async function matching `design.md` → _Low-Level Design — Handler: `handleCopyLink`_
    - Guard `if (!quote?.acceptance_token) return`
    - Construct `shareUrl = \`${window.location.origin}/api/v1/public/quotes/view/${quote.acceptance_token}\`` — do not URL-encode the token and do not add a trailing slash
    - `await navigator.clipboard.writeText(shareUrl)` then `setCopied(true)` and `setTimeout(() => setCopied(false), 2000)`
    - On rejection: `setError('Could not copy link to clipboard. Please copy manually.')` and do not touch `copied`
    - Do not issue any network request and do not mutate the quote on the server
    - _Requirements: 4.3, 4.4, 4.6, 4.7, 5.1, 5.2, 5.3_

- [x] 6. Frontend — print styles injection and `data-print-*` attributes on `QuoteDetail.tsx`
  - [x] 6.1 Add `PRINT_STYLES` constant and mount/unmount `useEffect`
    - Define `const PRINT_STYLES = \`...\`` at module scope with the exact CSS block from `design.md` → _Print CSS — `PRINT_STYLES`_ (includes `@media print`, `[data-print-hide] { display: none !important }`, `[data-print-content]` full-width expansion, `@page { margin: 10mm; size: A4 }`)
    - Add a `useEffect(() => { ... }, [])` that creates `<style data-quote-print="true">`, sets `textContent = PRINT_STYLES`, appends to `document.head`, and returns a cleanup that calls `style.remove()`
    - Empty dependency array — runs exactly once on mount and cleans up exactly once on unmount regardless of `downloading`, `copied`, or any in-flight request
    - _Requirements: 3.3, 3.4, 3.6_

  - [x] 6.2 Apply `data-print-hide` to chrome elements
    - Add `data-print-hide` to the back arrow `<button>` (header row, currently around line 192)
    - Add `data-print-hide` to the action-bar container `<div className="flex items-center gap-2">` (currently around line 197) so every action button is hidden in print
    - Add `data-print-hide` to the error banner `<div role="alert">`, the success banner `<div role="status">`, and the converted-invoice notice banner
    - _Requirements: 3.7_

  - [x] 6.3 Apply `data-print-content` to the quote card
    - Add `data-print-content` to the white quote card container `<div className="bg-white rounded-lg border border-gray-200 shadow-sm">` (currently around line 258) that holds the quote info grid, line items table, totals panel, and notes/terms
    - _Requirements: 3.8_

- [x] 7. Frontend — toolbar button placement and Copy Link conditional in `QuoteDetail.tsx`
  - [x] 7.1 Insert Print and Download PDF buttons (always visible)
    - Inside the action-bar container (the one now carrying `data-print-hide`), render Print and Download PDF to the LEFT of the existing Edit / Send / Requote / Convert / Delete buttons so the primary action remains rightmost on every status
    - Print: `<Button variant="secondary" onClick={handlePrint}>Print</Button>`
    - Download PDF: `<Button variant="secondary" onClick={handleDownloadPDF} loading={downloading} disabled={downloading}>{downloading ? 'Downloading…' : 'Download PDF'}</Button>`
    - Render both regardless of `quote.status` (including draft, sent, accepted, declined, expired, and converted with `converted_invoice_id`)
    - Do not wire these buttons to `actionLoading` — `downloading` is tracked independently
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2_

  - [x] 7.2 Insert conditional Copy Link button
    - Render `{quote.acceptance_token && (<Button variant="secondary" onClick={handleCopyLink}>{copied ? 'Copied!' : 'Copy Link'}</Button>)}` immediately after Download PDF
    - Treat `null`, `undefined`, and empty string as "do not render"
    - Label must flip to `Copied!` while `copied === true` and revert to `Copy Link` after the 2000 ms timeout set in 5.4
    - _Requirements: 4.1, 4.2, 4.5_

- [x] 8. Frontend — unit/component tests in `frontend/src/pages/quotes/__tests__/QuoteDetail.test.tsx`
  - Create the test file. Mock `apiClient` via `vi.mock('../../api/client')`. Provide quote fixtures for each status.

  - [x] 8.1 Print button renders on every status
    - Parametrised over `draft | sent | accepted | declined | expired | converted`
    - _Requirements: 3.1, 3.2_

  - [x] 8.2 Download PDF button renders on every status
    - Same parameterisation as 8.1
    - _Requirements: 2.1, 2.2_

  - [x] 8.3 Copy Link conditional visibility
    - Fixture A: `acceptance_token = null` (draft) — `queryByText(/Copy Link/)` is null
    - Fixture B: `acceptance_token = "abc"` (sent) — `queryByText(/Copy Link/)` is present
    - _Requirements: 4.1, 4.2_

  - [x] 8.4 Clicking Download PDF calls the correct endpoint
    - Assert `apiClient.get` is called with `/quotes/{id}/pdf` and `{ responseType: 'blob' }`
    - _Requirements: 2.5_

  - [x] 8.5 `downloading` state flips the label during the fetch
    - Use a never-resolving mock, assert label reads `Downloading…` and button is disabled; resolve the promise, assert label reverts to `Download PDF`
    - _Requirements: 2.3, 2.4, 2.7, 6.4_

  - [x] 8.6 API failure renders the existing error banner
    - Mock `apiClient.get` to reject with `{ response: { status: 500 } }` and assert banner reads exactly `Failed to download PDF. Please try again.`
    - Also cover network rejection (no `response` object) with the same banner text
    - _Requirements: 6.1, 6.2, 6.5_

  - [x] 8.7 Print style tag is present after mount
    - After `render`, assert `document.querySelectorAll('style[data-quote-print="true"]').length === 1`
    - _Requirements: 3.3_

  - [x] 8.8 Print style tag is removed after unmount, including mid-download
    - Start a download (never resolve), assert style tag present, call `unmount`, assert style tag gone
    - _Requirements: 3.4_

  - [x] 8.9 Copy Link click writes the exact URL to clipboard
    - Mock `navigator.clipboard.writeText`, render with `acceptance_token = "tok_xyz"`, click Copy Link, assert `writeText` called with `\`${window.location.origin}/api/v1/public/quotes/view/tok_xyz\`` (no encoding, no trailing slash)
    - _Requirements: 4.3_

  - [x] 8.10 Copied label flips for 2 s then reverts
    - Use `vi.useFakeTimers()`. Click Copy Link, assert label is `Copied!`, advance timers by 2000 ms, assert label is `Copy Link`
    - _Requirements: 4.4, 4.5, 4.6_

  - [x] 8.11 Clipboard rejection shows banner and leaves `copied` false
    - Mock `navigator.clipboard.writeText` to reject. Click Copy Link. Assert banner reads exactly `Could not copy link to clipboard. Please copy manually.` and no `Copied!` label ever appears
    - _Requirements: 5.1, 5.2, 5.3_

- [x] 9. Frontend — property tests (fast-check) in `frontend/src/pages/quotes/__tests__/QuoteDetail.property.test.tsx`
  - Create the file alongside `QuoteDetail.test.tsx` (follow naming of existing `frontend/src/__tests__/*.property.test.tsx`)

  - [x] 9.1 Property P1 — share URL format is exact
    - **Property 1: Share URL format is exact**
    - Use `fc.property` with a token strategy `fc.string({ minLength: 1, maxLength: 100 }).filter(s => /^[A-Za-z0-9_\-.]+$/.test(s))` and `fc.webUrl()` for origin
    - Assert the constructed URL matches `^<origin>/api/v1/public/quotes/view/<token>$`, contains no `//` after the scheme, and ends with `/<token>`
    - **Validates: Requirement 4.3**

  - [x] 9.2 Property P2 — print style tag cleanup is unconditional
    - **Property 2: Print style tag cleanup is unconditional**
    - Use `fc.asyncProperty` over `fc.record({ downloading: fc.boolean(), copied: fc.boolean(), downloadInFlight: fc.boolean() })`
    - For every combination, `render(<QuoteDetail ... />)`, drive state via mocked handlers, assert the style tag is present, then `unmount()` and assert `document.querySelectorAll('style[data-quote-print="true"]').length === 0`
    - **Validates: Requirements 3.3, 3.4**

  - [x] 9.3 Property P5 — Copy Link button visibility parity with token presence
    - **Property 5: Copy Link button visibility parity with token presence**
    - Use `fc.property` over `fc.option(fc.string({ minLength: 0, maxLength: 64 }), { nil: null })`
    - Render with that token value as `quote.acceptance_token`. Compute `shouldShow = token !== null && token !== undefined && token !== ''`. Assert `queryByText(/Copy Link|Copied!/)` matches `shouldShow`
    - **Validates: Requirements 4.1, 4.2**

- [x] 10. Frontend checkpoint — run frontend-only tests
  - Run `npm --prefix frontend run build` and confirm a clean production build
  - Run `npm --prefix frontend run test -- --run` (single-shot, no watch mode) and confirm every test in `QuoteDetail.test.tsx` and `QuoteDetail.property.test.tsx` passes alongside the existing frontend suite
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Version bump and CHANGELOG entry
  - [x] 11.1 Bump `pyproject.toml` version `1.4.0` → `1.5.0`
    - Update the `version` field in `pyproject.toml`
    - _Requirements: (release discipline — `.kiro/steering/versioning-and-changelog.md`)_

  - [x] 11.2 Bump `frontend/package.json` version `1.4.0` → `1.5.0`
    - Update the `version` field in `frontend/package.json`
    - _Requirements: (release discipline — `.kiro/steering/versioning-and-changelog.md`)_

  - [x] 11.3 Bump `mobile/package.json` version `1.3.0` → `1.5.0`
    - Close the pre-existing drift called out in `design.md` → _Version Bump & Changelog_ and `docs/QUOTE_PREVIEW_PRINT_PLAN.md`. No functional mobile change ships in this PR.
    - _Requirements: (release discipline — `.kiro/steering/versioning-and-changelog.md`)_

  - [x] 11.4 Add `[1.5.0]` entry to `CHANGELOG.md`
    - Prepend the block from `design.md` → _Version Bump & Changelog_ at the top of `CHANGELOG.md`:
      - Added: Quotes Download PDF button; Quotes browser print button with print-optimised layout; `GET /api/v1/quotes/{id}/pdf` endpoint; Quotes Copy Link button
      - Changed: mobile version bumped to 1.5.0 (no functional change) to align with backend + frontend
    - _Requirements: (release discipline — `.kiro/steering/versioning-and-changelog.md`)_

- [x] 12. Release — git push to new branch and Pi container rebuild verification
  - [x] 12.1 Full e2e run against dev before push
    - Run `docker exec invoicing-app-1 python scripts/test_quote_pdf_e2e.py` one final time from a clean dev state and confirm all 11 cases pass and cleanup leaves zero `TEST_E2E_` rows
    - _Requirements: (release discipline — `.kiro/steering/feature-testing-workflow.md`)_

  - [x] 12.2 Commit on a new branch and push to GitHub
    - `git checkout -b feature/quote-pdf-print`
    - `git add` only the files touched by this spec (router, QuoteDetail.tsx, new test files, e2e script, version files, CHANGELOG)
    - Commit with a message that mentions the feature name and `1.5.0`
    - `git push -u origin feature/quote-pdf-print`
    - Do not push to `main` directly and do not force-push
    - _Requirements: (release discipline — `project-overview.md` → Deployment Process)_

  - [x] 12.3 Sync code to Pi and rebuild backend container
    - `tar -cf - app/modules/quotes/router.py scripts/test_quote_pdf_e2e.py tests/test_quote_pdf_filename_property.py pyproject.toml CHANGELOG.md | ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && tar -xf -"`
    - `ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate app"`
    - Confirm the container comes up healthy and `alembic upgrade head` runs cleanly on boot (this feature adds no migrations, so head must remain 0182)
    - _Requirements: 10.1, 10.2, 10.3, 10.4_ _(release discipline — `project-overview.md` → Deployment Process)_

  - [x] 12.4 Sync frontend and rebuild frontend + nginx on Pi
    - `tar -cf - frontend/src/pages/quotes/QuoteDetail.tsx frontend/src/pages/quotes/__tests__/QuoteDetail.test.tsx frontend/src/pages/quotes/__tests__/QuoteDetail.property.test.tsx frontend/package.json mobile/package.json | ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && tar -xf -"`
    - Stop frontend and nginx, remove their containers, delete the `invoicing_frontend_dist` volume, then bring them back with `--build` (per `project-overview.md` → Deployment Process step 4)
    - Confirm `https://<pi-host>:8999/quotes/:id` renders the three new buttons and that `GET /api/v1/quotes/{id}/pdf` returns `%PDF-` bytes against prod
    - _Requirements: (release discipline — `project-overview.md` → Deployment Process)_

  - [x] 12.5 Final checkpoint
    - Ensure all tests pass, ask the user if questions arise.

## Notes

- Every property P1..P6 in `design.md` is documented as mandatory, so every property test sub-task is marked `[ ]` (required) — none are optional.
- P4 (org isolation) and P6 (download state monotonic) are stated in `design.md` as covered by e2e case 5 and component tests 8.4–8.6 respectively, so they do not get their own property-test sub-tasks — they are fully exercised by tasks 2.5, 8.5, and 8.6.
- The 11 e2e cases in `design.md` → _Testing Strategy → e2e test — backend_ map 1:1 to tasks 2.1 through 2.11.
- The 11 component tests in `design.md` → _Testing Strategy → Unit / component tests — frontend_ map 1:1 to tasks 8.1 through 8.11.
- No tasks touch Alembic, `.env*`, `pyproject.toml` dependency list, `frontend/package.json` `dependencies` section, or `mobile/package.json` `dependencies` section — this is enforced by Requirement 10.
- Checkpoints at tasks 4, 10, and 12.5 gate each stage; `.kiro/steering/no-shortcut-implementations.md` rule 5 (test what you ship) is satisfied by tasks 4, 10, 12.1, and 12.4.
