# Quote Preview, Print & Invoice-Parity — Gap Closure Plan

**Created:** 2026-05-12
**Last revised:** 2026-05-12 (mobile + list/detail parity sweep)
**Author:** Arshdeep
**Status:** Planning — no phase executed yet
**Related gaps identified in:** `QuoteDetail.tsx`, `QuoteCreate.tsx`, `QuoteList.tsx`, `mobile/src/screens/quotes/QuoteDetailScreen.tsx`, `app/modules/quotes/router.py`, `app/modules/quotes/public_router.py`, `app/modules/quotes/schemas.py`, `app/modules/quotes/models.py`

---

## Background

An investigation of the quotes module revealed four classes of gap:

### Class A — Preview, print, and share (the original scope)

| # | Gap | Where |
|---|-----|--------|
| 1 | No PDF download button | `QuoteDetail.tsx` has no download action; backend `generate_quote_pdf()` exists at `service.py:673` but no endpoint exposes it |
| 2 | No browser print button or print CSS | `QuoteDetail.tsx` has none of InvoiceDetail's `window.print()`, `PRINT_STYLES`, or `data-print-*` attributes |
| 3 | No preview before sending | "Send to Customer" (`handleSend` in `QuoteDetail.tsx:94`) immediately emails — no way to review first |
| 4 | Shareable link never surfaced | `acceptance_token` is returned by the API and typed in `QuoteData` but no button in the UI ever uses it |

### Class B — Quote creation does NOT mirror invoice creation

Discovered during the review pass. `QuoteCreate.tsx` was assumed to be invoice-parity, but a field-by-field audit of both files shows the quote form is missing a large set of fields the invoice form has, and the backend schemas simply do not persist those fields for quotes. These gaps are covered in **Phase 5**.

### Class C — Mobile QuoteDetailScreen is missing every mobile invoice feature

Discovered during the mobile sweep. `mobile/src/screens/invoices/InvoiceDetailScreen.tsx` and its companion `InvoicePDFScreen.tsx` expose Preview PDF / Download PDF / Print / Print POS Receipt / attachments carousel + inline photo upload. `mobile/src/screens/quotes/QuoteDetailScreen.tsx` has none of these — it only has the portal-link share button. Covered in **Phase 6**.

### Class D — QuoteDetail + QuoteList lack the attachment/PDF surfaces InvoiceDetail + InvoiceList have

Discovered during the desktop list/detail sweep. `InvoiceDetail.tsx` mounts `<AttachmentList />` when `attachment_count > 0`; `QuoteDetail.tsx` has no attachment section at all. `InvoiceList.tsx` shows a 📎 badge using `attachment_count`, plus a PDF/Print dropdown (Download PDF / Print / Print POS Receipt); `QuoteList.tsx` shows none of these. Covered in **Phase 7**.

---

## Steering principles applied

These rules from `.kiro/steering/` govern every phase:

- **No-shortcut rule** (`no-shortcut-implementations.md`): any change that adds new API calls or state management to an existing component **must go through a spec** (requirements → design → tasks) before implementation.
- **Frontend–backend contract alignment** (`frontend-backend-contract-alignment.md`): read the Pydantic schema before writing any new `apiClient` call; validate every response field with `?.` and `?? null`.
- **Feature testing workflow** (`feature-testing-workflow.md`): every backend change requires an e2e test script in `scripts/test_*_e2e.py` covering auth, org isolation, edge cases, and cleanup.
- **Security hardening** (`security-hardening-checklist.md`): every new endpoint needs auth, org isolation check, and rate limiting where appropriate.
- **Versioning** (`versioning-and-changelog.md`): new features bump MINOR (`x.Y.0`) across `pyproject.toml`, `frontend/package.json`, and `mobile/package.json`.
- **Spec completeness** (`spec-completeness-checklist.md`): spec design docs must cover navigation, component tree, user workflow trace, error states, and toolbar specification.

### Spec docs must include (per `.kiro/steering/spec-completeness-checklist.md`)

Each spec mentioned below must have `design.md` sections for:

1. Navigation entry point — where the user starts and how they get to the new surface
2. Component tree — every screen, modal, drawer, and their parent/child relationship
3. User-workflow trace — happy path + every documented error state as a named path
4. Toolbar spec — every button's label, variant, conditional visibility, and disabled state
5. Error states — named matrix of API failure → UI treatment
6. Loading/empty states for every async data source

---

## Current version state (verified 2026-05-12)

| File | Version |
|------|---------|
| `pyproject.toml` | `1.4.0` |
| `frontend/package.json` | `1.4.0` |
| `mobile/package.json` | `1.3.0` |

**Mobile is one minor behind — this is pre-existing drift.** Decision below (per Phase 2) is to bring mobile to `1.5.0` alongside backend+frontend in the same PR, even though mobile ships no functional change. This prevents the drift from widening and makes the three-way bump rule mechanical.

---

## Phase 1 — Backend: PDF download endpoint

**Gaps closed:** Gap 1 (foundation for all other phases)
**Spec required:** No — this is a new standalone endpoint with no existing component modification
**Estimated effort:** Small (2–3 hours)

### What it does

Adds `GET /quotes/{quote_id}/pdf` to `app/modules/quotes/router.py`. The `generate_quote_pdf()` service function already exists at `app/modules/quotes/service.py:673` and is already used internally by the send endpoint. This phase simply exposes it as an in-browser-viewable endpoint — exactly mirroring `GET /invoices/{invoice_id}/pdf` at `app/modules/invoices/router.py:1463`.

### Files changed

| File | Change |
|------|--------|
| `app/modules/quotes/router.py` | Add `GET /{quote_id}/pdf` endpoint |
| `scripts/test_quote_pdf_e2e.py` | New e2e test script (mandatory per feature-testing-workflow) |

### Implementation spec

```python
@router.get(
    "/{quote_id}/pdf",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "Quote PDF"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Quote not found"},
    },
    summary="Generate and stream quote PDF on-the-fly",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_quote_pdf_endpoint(
    quote_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    from fastapi.responses import Response
    from app.modules.quotes.service import generate_quote_pdf, get_quote

    org_uuid, _user_uuid, _ip = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        pdf_bytes = await generate_quote_pdf(db, org_id=org_uuid, quote_id=quote_id)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    quote_dict = await get_quote(db, org_id=org_uuid, quote_id=quote_id)
    filename = f"{quote_dict.get('quote_number') or 'DRAFT'}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
```

- **Auth:** `require_role("org_admin", "salesperson")` — matches both the send endpoint AND the invoice PDF endpoint.
- **Org isolation:** `generate_quote_pdf()` already scopes the query by `org_id` (verified at `app/modules/quotes/service.py` — every quote load uses `Quote.id == quote_id AND Quote.org_id == org_id`). The endpoint passes `org_uuid`, so cross-org access returns 404 from the service rather than the endpoint.
- **Content-Disposition:** `inline` (NOT `attachment`). The invoice PDF endpoint uses `inline`, so we match for parity. `inline` also lets the browser open the PDF in a new tab, which organically covers the "preview as customer" flow in Phase 3 and the "review before sending" flow in Phase 4 — reducing the scope of Phase 4.
- **Rate limiting:** PDF generation is CPU-heavy (WeasyPrint is synchronous inside an async handler). The invoice PDF endpoint has no endpoint-specific limit; it relies on the global per-org cap in `app/middleware/rate_limit.py`. We match that behaviour for quotes. If PDF abuse becomes a real concern, it should be addressed cross-cuttingly for invoices AND quotes in a separate phase, not unilaterally on one side.
- **Audit log:** The invoice PDF endpoint writes NO audit entry on download. We match that behaviour. If PDF download auditing is required (e.g. for compliance), add it to both invoices and quotes in a dedicated phase — don't introduce asymmetry here.
- **No migration required** — zero DB changes.

### e2e test must cover

- Login as `org_admin`, `GET /quotes/{id}/pdf` of a draft quote → 200, `Content-Type: application/pdf`, `Content-Disposition: inline; filename="..."`
- GET PDF of a sent quote → 200
- GET PDF of an accepted quote → 200
- No token → 401
- Wrong org's `quote_id` → 404 (org isolation via service — verified at `service.py:335`)
- Non-existent `quote_id` → 404
- Salesperson role → 200 (not blocked)
- `org_admin` role → 200
- Other org roles (e.g. `branch_user` if applicable) → 403
- Response body is non-empty bytes and starts with `%PDF-`
- `Content-Disposition` header contains the quote number
- **Cleanup:** delete all test quotes and customers created

### Version bump

None standalone — rolls into Phase 2's 1.5.0 bump.

---

## Phase 2 — Frontend: Download PDF + Browser Print in QuoteDetail

**Gaps closed:** Gap 1 (download button), Gap 2 (print button + print CSS), Gap 3 partial (download-in-new-tab acts as lightweight preview via `inline` disposition)
**Spec required:** **Yes** — adds new `apiClient` call and new state to an existing component (no-shortcut rule)
**Spec location:** `.kiro/specs/quote-pdf-print/` (requirements.md, design.md, tasks.md)
**Depends on:** Phase 1 complete
**Estimated effort:** Medium (1 day)

### What it does

Adds two buttons to the `QuoteDetail` action bar:

1. **Download PDF** — fetches `GET /quotes/{id}/pdf` as a blob, creates an object URL, triggers an `<a>` download. Pattern is identical to `handleDownloadPDF` in `InvoiceDetail.tsx:450`.
2. **Print** — injects `PRINT_STYLES` CSS into `<head>` on component mount (removed on unmount), then calls `window.print()`. Pattern is identical to the print flow in `InvoiceDetail.tsx:419`.

Both buttons are visible on **all** quote statuses — a printed or downloaded copy of any quote is useful regardless of whether it is draft, sent, accepted, or expired.

#### Important acknowledgement — Print and Download are NOT interchangeable

**Print** uses `window.print()` on the current `QuoteDetail` DOM with print-only CSS applied. The printed output therefore carries the app's in-app layout, not the branded `quote_share.html` template. **Download PDF** returns the WeasyPrint-rendered branded template. This means:

- For visual parity with the emailed quote → use Download PDF.
- For a quick paper copy on the workshop floor → Print is fine.

The spec must document this difference in its user-workflow trace so staff know when to use which button.

### Files changed

| File | Change |
|------|--------|
| `frontend/src/pages/quotes/QuoteDetail.tsx` | Add Download PDF button, Print button, print CSS injection, `downloading` state |

### State additions

```typescript
const [downloading, setDownloading] = useState(false)
```

No additional state needed — print is synchronous.

### Print CSS

Inject a `<style data-quote-print="true">` block on mount, removed on unmount:

```css
@media print {
  nav, aside, header, footer,
  [data-print-hide], .no-print { display: none !important; }
  body { background: white !important; }
  [data-print-content] {
    position: static !important;
    width: 100% !important;
    max-width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    box-shadow: none !important;
    border: none !important;
  }
  -webkit-print-color-adjust: exact !important;
  print-color-adjust: exact !important;
}
```

Apply `data-print-hide` to: the back arrow, the action buttons bar, any sidebar/nav elements.
Apply `data-print-content` to: the white quote card (`<div className="bg-white rounded-lg border..."`).

### Button placement

In the existing action bar (alongside Edit / Send to Customer):

```
[← Back]  Quote #QUO-0001  [DRAFT]          [Print]  [Download PDF]  [Edit]  [Send to Customer]
```

- Print and Download are secondary actions — use `variant="secondary"`
- Download shows spinner and "Downloading…" label while `downloading === true`
- Both buttons always visible (not status-gated)

### Error handling

- Download failure: set inline `error` state (same pattern already in QuoteDetail) — `"Failed to download PDF. Please try again."`
- Print has no async step — no error state needed

### Frontend tests to add

- "Download PDF" button renders in the action bar
- Clicking it calls `GET /quotes/{id}/pdf`
- `downloading` state shows loading label during fetch
- Error message shown on API failure (mock 500)
- Print CSS `<style>` tag is injected into `<head>` on mount
- Print CSS `<style>` tag is removed from `<head>` on unmount

### Version bump

Bump all three to `1.5.0` in the same PR:

- `pyproject.toml` `1.4.0 → 1.5.0`
- `frontend/package.json` `1.4.0 → 1.5.0`
- `mobile/package.json` `1.3.0 → 1.5.0` (no-op, closes the pre-existing drift)

**CHANGELOG entry:**
```markdown
## [1.5.0] - 2026-05-XX

### Added
- Quotes: Download PDF button on quote detail page
- Quotes: Browser print button with print-optimised layout on quote detail page
- Quotes: `GET /api/v1/quotes/{id}/pdf` backend endpoint (inline disposition, matches invoice PDF)
- Quotes: Copy Link button on quote detail page (surfaces `acceptance_token` public URL)

### Changed
- mobile: version bumped to 1.5.0 (no functional change) to align with backend + frontend
```

---

## Phase 3 — Frontend: Surface the shareable acceptance link

**Gap closed:** Gap 4 — `acceptance_token` returned by API, typed in `QuoteData`, but never shown to users
**Spec required:** Fold into Phase 2's spec tasks — the change is a single conditional button, well within the scope of Phase 2's spec
**Depends on:** Phase 2 complete (share the same PR)
**Estimated effort:** Small (1–2 hours, included in Phase 2 PR)

### What it does

When `quote.acceptance_token` is non-null (the quote has been sent at least once), a **"Copy Link"** button appears in the action bar. Clicking it:

1. Copies the public share URL to clipboard (see URL format below)
2. Button label changes to "Copied!" for 2 seconds, then reverts

This solves three problems with one button:
- **Reshare**: customer lost the email — staff can resend the link manually
- **Preview as customer**: staff opens the link in a new tab to see exactly what the customer sees — the existing public HTML view renders the full branded quote with Accept button
- **Confirmation**: after clicking Send, staff can verify what was emailed

### Copy-link URL — the v1 public mount path

The backend public quote router is mounted at `/api/v1/public/quotes` (verified in `app/main.py:592`), so the real path is:

```
/api/v1/public/quotes/view/{token}
```

Two options, both acceptable — spec must pick one:

**Option A (recommended) — direct backend URL**
```typescript
const shareUrl = `${window.location.origin}/api/v1/public/quotes/view/${quote.acceptance_token}`
```
Pros: zero frontend route work. Cons: `/api/v1/...` in a customer-facing URL looks ugly.

**Option B — add a React Router SPA route that fetches and renders**
Requires a new `/quotes/shared/:token` route in `App.tsx` plus a `SharedQuotePage.tsx` that either iframes the backend response or fetches JSON and re-renders. Pros: cleaner URL. Cons: duplicates rendering, adds a new route.

**Decision for this spec:** Option A. Keep the URL mechanical; if the URL cosmetics matter later, split into a dedicated "pretty public URLs" spec.

### Files changed

| File | Change |
|------|--------|
| `frontend/src/pages/quotes/QuoteDetail.tsx` | Conditional Copy Link button; `copied` boolean state |

### State additions

```typescript
const [copied, setCopied] = useState(false)
```

### Conditional visibility

```typescript
const canCopyLink = !!quote.acceptance_token
```

Shown when: quote has been sent (token exists). Hidden when: draft (token is null).

### Button placement

```
[Print]  [Download PDF]  [Copy Link]  [Requote]  [Convert to Invoice]
```

### No backend changes

`acceptance_token` is already returned in `GET /quotes/{id}` — confirmed in the `QuoteData` interface at `QuoteDetail.tsx:48` and in the Pydantic `QuoteResponse` schema at `app/modules/quotes/schemas.py`.

### Frontend tests to add

- "Copy Link" button not rendered when `acceptance_token` is null (draft quote)
- "Copy Link" button rendered when `acceptance_token` is present (sent quote)
- Clicking it calls `navigator.clipboard.writeText` with the correct URL
- Button label shows "Copied!" after click and reverts after 2 seconds

---

## Phase 4 — Full pre-send preview modal

**Gap closed:** Gap 3 fully — rich in-app HTML preview of the quote inside a modal, before clicking Send, without generating a PDF
**Spec required:** **Yes — full spec required** (new backend endpoint + new modal component + new state in QuoteDetail)
**Spec location:** `.kiro/specs/quote-preview-modal/` (requirements.md, design.md, tasks.md)
**Depends on:** Phases 1–3 deployed and stable
**Estimated effort:** Large (2–3 days)

> **Before starting this phase, re-validate that it is still needed.** Phase 1's `inline` Content-Disposition means clicking "Download PDF" opens the branded PDF in a new browser tab. That is already a review step. Phase 3's "Copy Link" + "Preview as customer" also covers review. If both of those land and staff report the workflow is fine, Phase 4 can be shelved. Do not build the modal speculatively.

### What it does

Adds a **"Preview"** button next to "Send to Customer" on draft quotes. Clicking it opens a `QuotePreviewModal` containing an `<iframe>` rendering the live HTML of the quote (org branding, line items, totals, terms) — exactly as the customer will see it — before sending.

The user can review the quote in the modal, then either click **"Send to Customer"** directly from the modal or close and edit first.

### Backend: new endpoint

`GET /quotes/{quote_id}/preview-html`

- Renders the quote HTML using the same Jinja2 template that `view_shared_quote` in `public_router.py:27` already uses — `quote_share.html`. No new template work needed.
- Returns `{ "html": "<!DOCTYPE html>..." }` — same pattern as `POST /org/invoice-templates/preview` (see `invoice-pdf-templates` spec).
- **No PDF generation** — Jinja2-only render, fast (no WeasyPrint).
- Auth: `require_role("org_admin", "salesperson")` — admin-only preview, NOT publicly accessible.
- Rate limiting: inherits per-org cap from `rate_limit.py` (same treatment as the PDF endpoint).
- No DB writes — read-only.

#### Critical: Accept button must be disabled in preview

The `quote_share.html` template renders an Accept button gated by `can_accept = quote.status == "sent"`. If the preview endpoint reuses the template without suppressing that flag, a staff member could accept the quote on the customer's behalf by accident just by clicking inside the iframe.

**The preview endpoint MUST pass:**

```python
html_content = template.render(
    quote=quote_dict,
    org=org_context,
    customer=customer_context,
    gst_percentage=gst_percentage,
    token=None,                    # prevents the Accept POST URL from resolving
    can_accept=False,              # hides the Accept button entirely
    already_accepted=False,
    is_preview=True,               # new flag — template renders a "PREVIEW" watermark
)
```

The template needs a small addition: a visible "PREVIEW — NOT THE CUSTOMER COPY" banner when `is_preview=True`, so nobody confuses a screenshot of the preview with the real emailed quote.

### Frontend: new component

**`frontend/src/pages/quotes/QuotePreviewModal.tsx`** (new file):

```
QuotePreviewModal
├── Modal shell (title: "Quote Preview — {quote_number}")
├── iframe (srcDoc={html}, sandbox="allow-same-origin")
│   (NOTE: do NOT include "allow-scripts" or "allow-forms" in sandbox —
│    the preview is read-only; preventing scripts/forms is the second
│    line of defence behind the backend's can_accept=False flag)
├── Loading spinner (while fetching HTML)
├── Error message (if fetch fails)
└── Footer action bar
    ├── [Close] — dismiss modal, no action
    └── [Send to Customer] — calls POST /quotes/{id}/send, closes modal on success
```

**State additions to `QuoteDetail.tsx`:**

```typescript
const [previewOpen, setPreviewOpen] = useState(false)
const [previewHtml, setPreviewHtml] = useState<string | null>(null)
const [previewLoading, setPreviewLoading] = useState(false)
```

### User workflow

```
User clicks "Preview" (draft quote only)
→ QuoteDetail fetches GET /quotes/{id}/preview-html
→ QuotePreviewModal opens with <iframe srcDoc={html}>
→ User reviews the rendered quote
→ Option A: clicks "Send to Customer" in modal footer
    → POST /quotes/{id}/send fires
    → Modal closes, success message shown, quote status updates to "sent"
→ Option B: clicks "Close"
    → Modal closes, quote stays in draft
```

### Button placement in QuoteDetail

```
[Print]  [Download PDF]  [Copy Link]  [Edit]  [Preview]  [Send to Customer]
                                               ↑ new      ↑ existing
```

"Preview" only visible when `canSend` (draft status). "Copy Link" only visible when `acceptance_token` exists.

### Error handling

| Scenario | Response |
|----------|----------|
| Preview API fails (500) | Modal shows error banner: "Could not render preview. Download the PDF to review instead." |
| Send fails from inside modal | Error banner inside modal footer, modal stays open |
| Quote not in draft when modal opens | Stale state — modal closes, detail page refreshes |

### Files changed (for the spec)

| File | Change |
|------|--------|
| `app/modules/quotes/router.py` | Add `GET /{quote_id}/preview-html` endpoint |
| `app/templates/pdf/quote_share.html` | Add `is_preview` watermark block |
| `frontend/src/pages/quotes/QuotePreviewModal.tsx` | New modal component |
| `frontend/src/pages/quotes/QuoteDetail.tsx` | Preview button, preview state, modal mount |
| `scripts/test_quote_preview_e2e.py` | e2e test script |

### Version bump

`1.5.0 → 1.6.0` across all three (`pyproject.toml`, `frontend/package.json`, `mobile/package.json`) when Phase 4 ships.

---

## Phase 5 — Invoice-parity gap in `QuoteCreate.tsx`

**Discovered during review.** QuoteCreate.tsx and InvoiceCreate.tsx were assumed to be parity siblings — they are not. A field-by-field audit shows QuoteCreate is missing most of InvoiceCreate's surface, both at the UI level and at the Pydantic schema / ORM level. This phase documents and closes the gap.

**Spec required:** **Yes — full spec required.** New ORM columns, Alembic migration, Pydantic schema fields, new React components, plus one backend endpoint for quote attachments. Cannot be done as a drive-by change.
**Spec location:** `.kiro/specs/quote-invoice-parity/` (requirements.md, design.md, tasks.md)
**Depends on:** Phases 1–4 are independent of this phase. Phase 5 can run in parallel with Phase 2 if capacity allows.
**Estimated effort:** Large (4–6 days) — the biggest single phase in this plan.

### The parity matrix

Verified field-by-field from `InvoiceCreate.tsx` vs `QuoteCreate.tsx` on 2026-05-12. ✓ = present, ✗ = missing.

#### Header fields

| Field | InvoiceCreate | QuoteCreate | Backend schema has field? |
|-------|:-------------:|:-----------:|:-------------------------:|
| Customer search | ✓ (with `linked_vehicles` preload, sequential-char matching, rego-match) | ✓ (basic, no vehicle preload, no rego-match) | yes (`customer_id`) |
| **`+ Add New Customer`** via `CustomerCreateModal` | ✓ | ✗ | N/A |
| Vehicle primary | ✓ — uses `VehicleLiveSearch` with auto-lookup on typing | ✗ — manual rego entry + explicit "Lookup" button | partial (single vehicle only) |
| **Multi-vehicle** (additional vehicles array) | ✓ | ✗ | ✗ — no `additional_vehicles` JSONB/array field on Quote |
| Order number | ✓ | ✗ | ✗ — no `order_number` column on Quote |
| Invoice/Quote date | ✓ (editable) | ✓ (read-only, auto today) | ✓ |
| **Payment terms** (`due_on_receipt`, `net_7`, `net_15`, `net_30`, `net_45`, `net_60`, `net_90`, `custom`) | ✓ | ✗ — only has `validity_days` (7/14/30) | different concept; quote has `validity_days` which IS correct for a quote |
| Due date | ✓ (auto from terms) | partial — shows `expiryDate` label only, not an editable due-date | N/A — quote uses `valid_until` instead |
| **Salesperson dropdown** | ✓ — loads from `/org/salespeople`, auto-selects current user | ✗ | ✗ — no `salesperson_id` column on Quote |
| GST number | ✓ — auto-populated from `settings.gst.gst_number` | ✗ — no GST display at all | N/A (org-level) |
| Subject | ✓ | ✓ | ✓ |

#### Line items

| Field | InvoiceCreate | QuoteCreate | Backend schema has field? |
|-------|:-------------:|:-----------:|:-------------------------:|
| Catalogue item selection | ✓ | ✓ | no — quote line item stores description + unit_price, not catalogue_item_id |
| **`catalogue_item_id` persisted on line** | ✓ (sent as `catalogue_item_id` in payload) | ✗ | ✗ — QuoteLineItemCreate has no `catalogue_item_id` field |
| Inline "Add new item" form | ✓ — 3-way GST mode (inclusive/exclusive/exempt) | ✓ — 2-way only (exempt checkbox; no inclusive/exclusive split) | N/A (creates catalogue item) |
| **GST-inclusive price back-calculation** | ✓ — rate stored ex-GST, `inclusive_price` preserved | ✗ — `gst_inclusive` is typed but never sent to backend (payload omits it) | ✗ — QuoteLineItemCreate has no `gst_inclusive` or `inclusive_price` fields |
| **Stock/inventory picker** (`+ Add from Inventory`) | ✓ | ✗ | ✗ — no `stock_item_id` column on QuoteLineItem |
| Parts catalogue picker (`+ Add Parts`) | ✗ (invoices use the inventory picker instead) | ✓ | N/A (client-side) |
| Labour rate picker (`+ Labour Charge`) | ✓ | ✓ | ✓ (item_type = "labour") |
| **Fluid / oil usage tracking** | ✓ — dedicated amber section, inventory decrement, NOT on total | ✗ | ✗ — no `fluid_usage` field on Quote |
| Tax dropdown per line | ✓ | ✓ | ✓ |
| Line description (multi-line) | ✓ | ✓ | ✓ |

#### Totals

| Field | InvoiceCreate | QuoteCreate | Backend schema has field? |
|-------|:-------------:|:-----------:|:-------------------------:|
| Subtotal | ✓ | ✓ | ✓ |
| Discount (% / $) | ✓ | ✓ | ✓ |
| GST | ✓ (handles inclusive items correctly) | ✓ (uses simple `amount × tax_rate/100` — wrong for inclusive items, but see next row) | ✓ (`gst_amount`) |
| Shipping | ✓ | ✓ | ✓ |
| Adjustment | ✓ | ✓ | ✓ |
| Total | ✓ | ✓ | ✓ |

#### Notes and terms

| Field | InvoiceCreate | QuoteCreate | Backend schema has field? |
|-------|:-------------:|:-----------:|:-------------------------:|
| Customer notes | ✓ — auto-populates plain-text-stripped default from `settings.invoice.terms_and_conditions` | ✓ — empty by default | ✓ (`notes`) |
| Terms & conditions | ✓ | ✓ | ✓ (`terms`) |
| **"Save as default for all future invoices"** checkbox | ✓ | ✗ | N/A — orgs currently only have a T&C default for invoices |

#### Post-header / final sections

| Field | InvoiceCreate | QuoteCreate | Backend |
|-------|:-------------:|:-----------:|:-------:|
| **File attachments** (max 5, 20 MB) | ✓ — multipart upload via `POST /invoices/{id}/attachments`; `AttachmentList` component on detail page | ✗ | ✗ — no `/quotes/{id}/attachments` endpoint; no `quote_attachments` table |
| **Payment gateway selector** (Cash / EFTPOS / Bank Transfer / Stripe) | ✓ — reads Stripe Connect status from `/payments/online-payments/status` | ✗ | partial — quotes don't take payment directly, but quote-to-invoice conversion could carry the payment preference |
| **Make recurring** toggle | ✓ (flag only; settings configured after save) | ✗ | recurring is invoice-only by design — **not a gap**, exclude from parity spec |
| Save Draft button | ✓ | ✓ | N/A |
| **Mark Paid & Email** | ✓ (issues, records payment, emails) | ✗ | not applicable to quotes — **not a gap**, exclude |
| Save and Send | ✓ (becomes `status=sent`) | ✓ (`POST /quotes/{id}/send`) | ✓ |

#### Unsaved-changes guard

| Behaviour | InvoiceCreate | QuoteCreate |
|-----------|:-------------:|:-----------:|
| `setNavigationGuard` / `clearNavigationGuard` wired up | ✓ | ✗ |
| `beforeunload` dirty-check | (implicit via navigation guard) | ✗ |

### Summary of backend columns/fields that need to be added for parity

| Target | Column / field | Type | Rationale |
|--------|----------------|------|-----------|
| `quotes` table | `order_number` | `VARCHAR(100) NULL` | Customer-provided reference (PO number, etc.) |
| `quotes` table | `salesperson_id` | `UUID NULL`, FK → `users.id` | Attribute quote to a specific staff member |
| `quotes` table | `additional_vehicles` | `JSONB NULL` | Multi-vehicle quotes (matches invoice behaviour) |
| `quotes` table | `fluid_usage` | `JSONB NULL` | Non-invoiced inventory tracking on the quote |
| `quote_line_items` table | `catalogue_item_id` | `UUID NULL`, FK → `catalogue_items.id` | Link line back to its catalogue source |
| `quote_line_items` table | `stock_item_id` | `UUID NULL`, FK → `inventory_stock_items.id` | Link line back to a stock unit |
| `quote_line_items` table | `gst_inclusive` | `BOOLEAN NOT NULL DEFAULT false` | Preserve inclusive-pricing intent from catalogue |
| `quote_line_items` table | `inclusive_price` | `NUMERIC(12,2) NULL` | Original inclusive unit price for audit |
| `quote_line_items` table | `tax_rate` | `NUMERIC(5,2) NOT NULL DEFAULT 15` (or keep derived from `is_gst_exempt`) | Per-line tax rate display |
| New table: `quote_attachments` | `id`, `quote_id`, `file_name`, `file_size`, `mime_type`, `file_path`, `uploaded_by`, `created_at` | mirror of `invoice_attachments` | File attachments for quotes |

Pydantic schemas must grow matching fields in `QuoteCreate`, `QuoteUpdate`, `QuoteLineItemCreate`, `QuoteResponse`, and `QuoteLineItemResponse`.

### Suggested implementation order inside Phase 5

1. **Migration first** — add the columns and tables above, all nullable / defaulted so existing quotes stay valid.
2. **Backend schema + service layer** — extend `QuoteCreate`/`QuoteUpdate`/`QuoteLineItemCreate` to accept the new fields; extend `create_quote` / `update_quote` / `get_quote` / `send_quote` / `generate_quote_pdf` to read/write them; add `/quotes/{id}/attachments` endpoints mirroring the invoice ones.
3. **Frontend payload extension** — update `QuoteCreate.tsx buildPayload()` to send the new fields; extend the in-memory `LineItem` → backend mapping to include `catalogue_item_id`, `stock_item_id`, `gst_inclusive`, `inclusive_price`.
4. **Frontend UI** — add the missing sections to `QuoteCreate.tsx`:
   - Add New Customer modal
   - VehicleLiveSearch + multi-vehicle
   - Order number
   - Salesperson dropdown
   - 3-way GST mode in inline "Add new item" form
   - Inventory picker
   - Fluid / oil usage section
   - Attachments section (reuse `AttachmentList` pattern)
   - Save-terms-as-default checkbox
   - Navigation guard wiring
5. **Tests**:
   - Backend unit test per new schema field (round-trip through create → get → update → get)
   - `scripts/test_quote_parity_e2e.py` — create quote with every new field, retrieve, confirm it comes back
   - Frontend: one vitest per new UI section asserting it renders + sends the field in the payload

### Version bump

Phase 5 lands at `1.7.0` (or merged into the 1.6.0 Preview Modal bump if it ships in the same release window).

### Spec obligations per spec-completeness-checklist

This is the largest spec in the plan; the `design.md` MUST cover (per `.kiro/steering/spec-completeness-checklist.md`):

1. **Navigation entry point** — `/quotes/new` and `/quotes/:id/edit`, plus the Duplicate flow from `QuoteDetail`.
2. **Component tree** — every new component (InventoryPicker, FluidUsageSection, MultiVehicleSection, QuoteAttachmentList, etc.) and their parent/child wiring.
3. **User-workflow trace** — happy path for each new section: customer → vehicle → multi-vehicle → line items (with inventory) → fluids → attachments → save. Plus the "edit an existing quote" path where the new fields must be rehydrated.
4. **Toolbar spec** — Save Draft, Save and Send buttons (no new buttons in this phase; existing behaviour preserved).
5. **Error states** — per-section: customer create failure, vehicle lookup failure, inventory fetch failure, attachment upload failure (size cap, MIME cap, network), slug-conflict equivalents for the Duplicate flow.
6. **Loading/empty states** — every new async surface needs a documented skeleton + empty state.

---

## Phase 6 — Mobile: bring QuoteDetailScreen up to InvoiceDetailScreen parity

**Discovered during mobile sweep.** `mobile/src/screens/invoices/InvoiceDetailScreen.tsx` + `mobile/src/screens/invoices/InvoicePDFScreen.tsx` expose Preview PDF / Download PDF / Print / Print POS Receipt / attachments carousel + inline photo upload. `mobile/src/screens/quotes/QuoteDetailScreen.tsx` currently only has the customer-portal share button — no PDF preview, no print, no attachment UI.

**Spec required:** Yes — mobile changes cross module boundaries (new screen route, new Capacitor-safe platform checks, attachment upload flow). `.kiro/specs/quote-mobile-parity/`
**Depends on:** Phase 1 (backend PDF endpoint) for Preview PDF to work; Phase 5 (attachments table + `/quotes/{id}/attachments` endpoints) for the attachments section; Phases 2–4 are not prerequisites.
**Estimated effort:** Small–Medium (1–2 days) — reuses the mobile `PDFViewer` component, `ActionSheet`, `HapticButton`, and `AttachmentList` patterns wholesale from invoices.

### Mobile parity matrix

Verified from `InvoiceDetailScreen.tsx` vs `QuoteDetailScreen.tsx` on 2026-05-12. ✓ = present, ✗ = missing.

| Surface | InvoiceDetailScreen | QuoteDetailScreen | Notes |
|---------|:-------------------:|:-----------------:|-------|
| **Preview PDF button** in hero | ✓ (routes to `/invoices/:id/pdf` → `InvoicePDFScreen`) | ✗ | Add `QuotePDFScreen.tsx` + route `/quotes/:id/pdf` |
| **Download PDF** action-sheet item | ✓ | ✗ | Same handler pattern: navigate to PDF screen, tap Open → new tab / share sheet |
| **Print** action-sheet item | ✓ (`window.print()`) | ✗ | Same pattern — native iOS/Android print sheets are wired through Capacitor |
| **Print POS Receipt** action-sheet item | ✓ | ✗ | **Exclude** (quotes are not POS receipts — see "Explicitly out of scope" below) |
| Attachments carousel | ✓ (horizontal overflow-x scroll of thumbnails) | ✗ | Needs Phase 5 attachments table first |
| Inline photo upload (camera + picker) | ✓ (`POST /api/v1/invoices/:id/attachments` with `FormData`) | ✗ | Same — needs Phase 5's `/quotes/{id}/attachments` endpoint |
| Customer portal share button | ✓ (via `canSharePortalLink`) | ✓ | **Already at parity** |

### Files changed

| File | Change |
|------|--------|
| `mobile/src/screens/quotes/QuotePDFScreen.tsx` | New file — mirrors `InvoicePDFScreen.tsx`; loads `/api/v1/quotes/:id/pdf` via `<PDFViewer />` |
| `mobile/src/navigation/StackRoutes.tsx` | New route `/quotes/:id/pdf` |
| `mobile/src/screens/quotes/QuoteDetailScreen.tsx` | Add Preview PDF hero button, Download PDF + Print action-sheet items, attachments section (gated on Phase 5) |
| `mobile/src/screens/quotes/__tests__/QuoteDetailScreen.test.tsx` | Add tests mirroring the invoice suite (Preview PDF renders; navigates to PDF screen on tap) |

### Mobile steering rules (re-read before writing the spec)

From `.kiro/steering/mobile-app.md`:

- Tabs already cover Quotes via the More menu — no tab-bar change needed
- Touch targets ≥ 44×44 CSS px for every new button
- Capacitor plugin calls (if any — e.g. camera for attachment upload) MUST be guarded by `(window as any).Capacitor?.isNativePlatform?.()`
- Dark-mode variants on every new component (`dark:` Tailwind modifiers)
- Safe-area insets on the PDF screen's header (copy the invoice PDF screen's layout exactly)
- Use `offset`/`limit` for any paginated attachment list — never `skip`
- Typed API generics on every new `apiClient.get/post`

### Mobile tests to add

Vitest suites mirroring `mobile/src/screens/invoices/__tests__/InvoiceScreens.test.tsx`:

- `QuoteDetailScreen` renders "Preview PDF" button
- Tapping "Preview PDF" navigates to `/quotes/:id/pdf`
- Action sheet shows "Download PDF", "Print" items
- Action sheet does **not** show "Print POS Receipt"
- Attachments section renders when Phase 5 is live and `attachment_count > 0` (conditional; can be skipped until Phase 5 lands)

### Version bump

Rolls into Phase 5's bump (`1.6.0` or `1.7.0` depending on release window). Does not ship independently.

---

## Phase 7 — Desktop: attachment + PDF surfaces on QuoteDetail and QuoteList

**Discovered during desktop list/detail sweep.** Phase 2/3 handles the action-bar buttons on `QuoteDetail.tsx`, but two extra surfaces were not covered:

1. **QuoteDetail has no attachment section.** `InvoiceDetail.tsx` mounts `<AttachmentList invoiceId={invoice.id} isDraft={...} />` conditional on `invoice.attachment_count > 0`. `QuoteDetail.tsx` has nothing similar. Once Phase 5 ships attachment endpoints for quotes, the quote detail page must render them.
2. **QuoteList is missing the attachment badge and the PDF/Print dropdown.** `InvoiceList.tsx:983` shows `📎 {attachment_count}` badges per row. `InvoiceList.tsx:1160` shows a PDF/Print dropdown with Download PDF + Print + Print POS Receipt per selected invoice. `QuoteList.tsx` has none of this.

**Spec required:** Fold into Phase 5's spec (`.kiro/specs/quote-invoice-parity/`) — these are read-side UI additions that consume the same tables Phase 5 adds. The spec's `tasks.md` should have a dedicated top-level task for each: "Extend QuoteDetail with attachment section" and "Extend QuoteList with attachment badge + PDF dropdown".
**Depends on:** Phase 5 (attachments table + `attachment_count` surfaced on `QuoteSearchResult`).
**Estimated effort:** Small (half-day) — both are drop-in reuse of existing invoice components.

### What it adds

**On `QuoteDetail.tsx`:**

- New component `frontend/src/components/quotes/QuoteAttachmentList.tsx`, modelled on `frontend/src/components/invoices/AttachmentList.tsx` — swap `/invoices/{id}/attachments` → `/quotes/{id}/attachments`, `invoice_id` prop → `quote_id` prop. Pattern is nearly identical; consider extracting a shared `<AttachmentList entity="invoice" | "quote" entityId={id} />` if the duplication is uncomfortable.
- Mount conditional on `quote.attachment_count > 0` — needs Phase 5's `QuoteSearchResult`/`QuoteResponse` to expose `attachment_count`.

**On `QuoteList.tsx`:**

- 📎 badge per row reading `q.attachment_count ?? 0` — same markup as `InvoiceList.tsx:983`.
- PDF/Print dropdown per row — copy the `pdfMenuRef` + `handleDownloadPDF` + `handlePrint` pattern from `InvoiceList.tsx:1160`. Exclude "Print POS Receipt" (see "Explicitly out of scope" below).
- The `Quote` interface needs `attachment_count?: number` once Phase 5 adds the column to `QuoteSearchResult`.

### Files changed

| File | Change |
|------|--------|
| `frontend/src/components/quotes/QuoteAttachmentList.tsx` | New file (or shared abstraction) |
| `frontend/src/pages/quotes/QuoteDetail.tsx` | Mount `<QuoteAttachmentList />` when `attachment_count > 0` |
| `frontend/src/pages/quotes/QuoteList.tsx` | Add 📎 badge column; add PDF/Print dropdown per row |

### Tests to add

- `QuoteAttachmentList` renders when attachments are returned, 404 when not
- `QuoteList` badge renders only when `attachment_count > 0`
- `QuoteList` PDF dropdown shows Download PDF and Print items; does NOT show Print POS Receipt
- Clicking Download PDF in the list fetches `/quotes/{id}/pdf` and triggers a download

### Version bump

Rolls into Phase 5's bump. Does not ship independently.

---

## Explicitly out of scope across this plan

Consolidated here so nobody spends cycles on these before confirming they are wanted. Each is N/A by design, not an oversight:

| Feature | Why excluded |
|---------|--------------|
| **Make recurring** toggle on quotes | Invoices only by design — recurring is a billing cadence concept |
| **Mark Paid & Email** button on quotes | Quotes haven't been paid — conceptually nonsensical |
| **Payment gateway selector** (Cash / EFTPOS / Bank Transfer / Stripe) on quotes | Quotes don't take payment; payment preference carries over at convert-to-invoice time |
| **Stripe Connect status indicator** on quotes | Same — no direct payment on quotes |
| **Payment reminder SMS/email** (`send_payment_reminder`) for quotes | Quotes have `auto_expire_quotes()` instead — different lifecycle |
| **Bulk delete endpoint** for quotes (`POST /quotes/bulk-delete`) | Not currently requested; invoices have one but quote lifecycle is simpler. Can be added later if needed |
| **POS receipt** (`/quotes/:id/pos-receipt`, `POSReceiptPreview` mount, "Print POS Receipt" action) | Customer has not paid — POS receipt implies a completed transaction |
| **Multi-vehicle / attachments / fluid usage** if users say no | Phase 5 adds the columns; if Open Question 1 or 2 below returns "no", remove those rows from the Phase 5 migration before merging |

If any item above gets requested later, it needs its own spec — do not quietly add to this plan.

---

## Phase-to-gap traceability

| Gap class | Phase(s) | Notes |
|-----------|----------|-------|
| A1 — PDF endpoint | 1 | Backend-only |
| A2 — Print + Download buttons | 2 | Spec `quote-pdf-print` |
| A3 — Preview before sending | 2 (partial via inline PDF) + 4 (optional full modal) | Re-evaluate 4 after 2 ships |
| A4 — Shareable link | 3 (folded into Phase 2 PR) | Uses `/api/v1/public/quotes/view/{token}` |
| B — QuoteCreate parity with InvoiceCreate | 5 | Biggest phase; migration + schema + UI |
| C — Mobile QuoteDetailScreen parity | 6 | Depends on 1 and 5 |
| D — Desktop QuoteDetail/QuoteList attachment + PDF surfaces | 7 (folded into Phase 5 spec) | Depends on 5 |



| Phase | Gaps closed | Spec needed | Depends on | Version | PR scope |
|-------|-------------|-------------|------------|---------|----------|
| 1 — Backend PDF endpoint | Gap 1 (foundation) | No | Nothing | — | Backend only |
| 2 — Download + Print buttons | Gap 1, Gap 2, Gap 3 (partial via `inline`) | Yes — `quote-pdf-print` spec | Phase 1 | 1.5.0 | Frontend only |
| 3 — Copy Link button | Gap 4 | Fold into Phase 2 spec | Phase 2 | 1.5.0 | Same PR as Phase 2 |
| 4 — Preview modal | Gap 3 (full — only if still needed after Phases 1–3) | Yes — `quote-preview-modal` spec | Phases 1–3 stable | 1.6.0 | Backend + Frontend |
| 5 — Invoice-parity for QuoteCreate | Full field parity between InvoiceCreate and QuoteCreate | Yes — `quote-invoice-parity` spec | Independent (can run parallel to Phase 2) | 1.7.0 | Migration + Backend + Frontend |

**Recommended sequence:**

1. Implement Phase 1 immediately — pure backend, no spec needed, unblocks everything.
2. Write the `quote-pdf-print` spec, then implement Phases 2 + 3 together in one PR targeting `1.5.0`.
3. Write the `quote-invoice-parity` spec in parallel; schedule for after Phase 2 lands (can ship as `1.6.0` or `1.7.0` depending on capacity).
4. Re-evaluate whether Phase 4 is still needed after Phases 1–3 are in production. If yes, write the `quote-preview-modal` spec and ship as `1.6.0` or `1.7.0`.

---

---

## Execution order summary

| Phase | Gaps closed | Spec needed | Depends on | Version | PR scope |
|-------|-------------|-------------|------------|---------|----------|
| 1 — Backend PDF endpoint | Gap 1 (foundation) | No | Nothing | — | Backend only |
| 2 — Download + Print buttons | Gap 1, Gap 2, Gap 3 (partial via `inline`) | Yes — `quote-pdf-print` spec | Phase 1 | 1.5.0 | Frontend only |
| 3 — Copy Link button | Gap 4 | Fold into Phase 2 spec | Phase 2 | 1.5.0 | Same PR as Phase 2 |
| 4 — Preview modal | Gap 3 (full — only if still needed after Phases 1–3) | Yes — `quote-preview-modal` spec | Phases 1–3 stable | 1.6.0 | Backend + Frontend |
| 5 — Invoice-parity for QuoteCreate | Class B (field + schema parity) | Yes — `quote-invoice-parity` spec | Independent (can run parallel to Phase 2) | 1.6.0 or 1.7.0 | Migration + Backend + Frontend |
| 6 — Mobile QuoteDetailScreen parity | Class C (mobile PDF / print / attachments) | Yes — `quote-mobile-parity` spec | Phase 1 (PDF); Phase 5 (attachments) | Rolls into 5's bump | Mobile only |
| 7 — Desktop QuoteDetail/List attachment + PDF surfaces | Class D (attachment badge + PDF dropdown) | Fold into Phase 5 spec | Phase 5 | Rolls into 5's bump | Frontend only |

**Recommended sequence:**

1. Implement Phase 1 immediately — pure backend, no spec needed, unblocks Phases 2, 3, 4 and 6.
2. Write the `quote-pdf-print` spec, then implement Phases 2 + 3 together in one PR targeting `1.5.0`.
3. Write the `quote-invoice-parity` spec in parallel; schedule Phases 5 + 7 together (same PR). Write the `quote-mobile-parity` spec on the heels of Phase 5 so attachments land everywhere at once.
4. Re-evaluate whether Phase 4 is still needed after Phases 1–3 are in production. If yes, write the `quote-preview-modal` spec and ship.

---

## Open questions for the author

Before writing any spec, the author should answer:

1. **Are multi-vehicle quotes actually a customer-facing requirement, or only a mechanic-facing nice-to-have?** Invoices have them because a workshop bills a customer for work on multiple vehicles in one visit. Quotes may or may not need this — check with users. If not needed, drop that row from Phase 5.
2. **Does the business want quote attachments at all?** Attachments on invoices are common (receipts, photos, before/after shots). Quotes typically don't carry proof-of-work files. If "no" → delete the `quote_attachments` table + endpoint from Phase 5, AND remove the attachment sections from Phases 6 (mobile) and 7 (desktop list/detail).
3. **Should the `quote_share.html` template get the preview watermark now, or wait until Phase 4 actually starts?** Suggest wait — the template change is tiny and belongs in the Phase 4 PR, not upstream.
4. **Does Phase 4 survive Phase 1?** Decide after Phases 1–3 ship whether the in-app modal is worth the build. The `inline` PDF + Copy Link may cover the entire review workflow organically.

## Other findings noted but not yet promoted to phases

These surfaced during the full-scope sweep. They are not currently in-scope for any phase above — captured here so nothing is lost. Each needs an explicit decision before work begins.

- **D. POS receipt for quotes** — `InvoiceDetail.tsx`/`InvoiceList.tsx` render `POSReceiptPreview`; mobile has `/invoices/:id/pos-receipt`. The plan treats POS receipt as out of scope for quotes (customer has not paid) but the rationale has not been validated with users.
- **E. Customer portal parity** — Already confirmed at parity: `/api/v1/portal/quotes` exists, `PortalQuoteItem` schema exists, `QuoteAcceptance.tsx` already renders. Noted here so nobody re-builds it.
- **G. Quote auto-expire vs invoice payment reminders** — Quotes have `auto_expire_quotes()` (`service.py:651`). Invoices have `send_payment_reminder()`. There is no equivalent "your quote expires in N days" customer nudge today. This is a feature request, not a parity gap — open question: is it wanted?
- **H. Stale comment in `app/modules/quotes/models.py`** — Module docstring line 6 says `recurring_schedules: recurring invoice schedules per organisation (RLS enabled)` but that table lives in `app/modules/recurring_invoices/models.py`. Trivial cleanup; fold into whichever Phase 5 PR first touches that file.
- **I. v1 vs v2 quotes router direction** — `/api/v1/quotes` (this plan's target) and `/api/v2/quotes` (`app/modules/quotes_v2`) both exist. v2 already has its own versioning + acceptance token but NO PDF endpoint and was NOT audited for the Phase 5 parity gaps. If v2 is the strategic direction, Phases 1, 5, and 7 should target v2 instead. Needs an owner decision before Phase 1 starts.
