# Email Preview Body Mismatch — Bugfix Design

## Overview

The "Send Invoice" (and every other Send-Email-Modal surface) shows an editable email body that does not match the email the customer receives. The root cause is a representation mismatch: the Email_Preview_Endpoint returns `body_html` as a **complete transactional HTML document** (`<!DOCTYPE html>…<head><title>{subject}</title></head><body>…<div>{paragraphs}{CTA <table>}{signature}</div></body></html>`), and the frontend feeds that whole document into a TipTap rich-text editor. ProseMirror extracts the `<title>` text and renders it as the first editable paragraph (the visible "subject leaked into the body" defect), and it cannot round-trip the inline-styled CTA `<table>`. A secondary defect is a link-origin mismatch where the preview falls back to `http://localhost` while the sent email uses the real request origin.

This design fixes the mismatch by changing the contract so the editor binds to the **inner body fragment** (the editable paragraphs + signature only — no document chrome, no generated CTA button), while the send path's full-document render and its byte-equivalence guarantee (Property 1) remain **completely unchanged**.

It also delivers a newly-requested capability that is tightly coupled to the same contract change: the body editor gains a **dual mode** — a rich-text (WYSIWYG) mode and a raw-**HTML** mode — so power users can author or paste full styled HTML email templates. Both modes operate on the same inner-body HTML fragment.

## Glossary

- **Bug_Condition (C)**: A Send-Email-Modal preview whose `body_html` is a full HTML document, causing (a) the subject/head text to leak into the editor body, and/or (b) the preview's link origin to differ from the send path's.
- **Property (P)**: The desired behavior — the editor binds to an inner-body fragment containing no subject/chrome, and preview links resolve to the same origin as the sent email.
- **Preservation**: Behaviors that must remain unchanged — the default (unedited) send render, Property 1 byte-equivalence, the edited-body override send path, sender/blocklist/attachment resolution, and every non-invoice surface.
- **Full document**: The output of `render_transactional_html(...)` — `<!DOCTYPE>` + `<head><title>` + `<body><div>{paragraphs}{CTA table}{signature}</div>`.
- **Inner-body fragment**: The editable HTML the user actually authors — paragraphs + optional signature block — with no `<!DOCTYPE>`, `<html>`, `<head>`, `<title>`, and no generated CTA button table. This is what `editor.getHTML()` already emits and what the override-send path already sends after sanitisation.
- **`build_email_preview`**: `app/modules/email_compose/service.py` — builds the preview payload.
- **`render_transactional_html`**: `app/integrations/email_sender.py` — wraps a body into the full document (UNCHANGED).
- **`sanitise_email_html`**: `app/integrations/html_sanitise.py` — allowlist sanitiser (allows `p, table, span, div, a, img, …`, `style` via CSSSanitizer) (UNCHANGED).
- **`BodyEditor` / `MobileBodyEditor`**: `frontend-v2/src/components/email/BodyEditor.tsx`, `mobile/src/components/email/MobileBodyEditor.tsx` — the TipTap editors.
- **`SendEmailModal` / `SendEmailSheet`**: the web modal and mobile sheet that host the editor.
- **Property 1**: `tests/test_email_compose_default_equivalence.py` — asserts the default-render preview equals the sanitised sent HTML.

## Bug Details

### Bug Condition

The preview endpoint returns `body_html` as a full HTML document and the editor binds to it directly. Two observable defects result, plus the link-origin fallback.

**Formal Specification:**
```
FUNCTION isBugCondition(X)
  INPUT: X = preview request (template_type, entity_type, entity_id,
             request_origin, payment_page_url, settings.frontend_base_url)
             plus the resulting body_html handed to the editor
  OUTPUT: boolean

  // (a) The editor body is a full document whose head/title text becomes
  //     visible editable content.
  leaks_chrome ← X.body_html CONTAINS "<!DOCTYPE"
              OR X.body_html CONTAINS "<head"
              OR X.body_html CONTAINS "<title"
              OR editorVisibleBody(X.body_html) CONTAINS X.subject

  // (b) The preview origin differs from the send-path origin for the
  //     same inputs.
  origin_mismatch ← resolvePreviewOrigin(X) ≠ resolveSendOrigin(X)

  RETURN leaks_chrome OR origin_mismatch
END FUNCTION
```

### Examples

- **Subject leak**: Open Send Invoice for `SPINV-0057`. The modal shows "Invoice SPINV-0057 from SP Automotive" as the first body line; the received email has no such line (subject lives only in `<title>`).
- **Link origin**: The modal's "View Invoice" link reads `http://localhost/api/v1/public/invoice/…`; the received email reads `https://devin.oraflows.co.nz/api/v1/public/invoice/…`.
- **CTA presentation (NOT a bug, out of scope)**: The CTA shows as plain link text in the editor but as a styled blue button in the email. TipTap cannot round-trip a full inline-styled `<table>` button; this is expected.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- The default (unedited) send path SHALL continue to render the full document via `render_transactional_html` and dispatch byte-for-byte identically to the pre-modal auto-send (Property 1 holds).
- The edited-body override send path SHALL continue to `sanitise_email_html(body_html)` and send the sanitised fragment as-is, with the existing audit hashing over the final strings.
- Sender identity, blocklist, attachment-token, and locale resolution in the preview SHALL be unchanged.
- Every non-invoice surface (`quote_sent`, `customer_statement`, `payment_received`, `invoice_payment_link`, `portal_link`, and the four vehicle reminders) SHALL resolve subject/body/recipients/attachments exactly as before.
- The CTA SHALL continue to render as plain link text inside the editor (the out-of-scope presentation difference) — no email-button rendering is attempted inside TipTap.
- When the request `origin` header is present and already matches the send path's resolution, link building SHALL be unchanged.

**Scope:** Any preview/send whose `body_html` is already a fragment and whose origin already matches the send path is unaffected.

## Hypothesized Root Cause

1. **The preview's editable field is a full document.** `build_email_preview` sets `body_html = sanitise_email_html(render_transactional_html(body_text, subject=…, cta_url=…, …))`. `render_transactional_html` emits `<title>{subject}</title>` in the head and a CTA `<table>` in the body. When TipTap parses this, ProseMirror's DOM parser walks the whole tree and surfaces the `<title>` text as a text node in the document body — so the subject appears as the first editable paragraph. (Defect 1.1)

2. **The editable field conflates "what is sent" with "what is edited."** The send path only ever sends an edited body as a *fragment* (`sanitise_email_html(body_html)`, no re-wrap — verified in `invoices`, `quotes`, `reports`, `customers`, `payments`, `notifications` services). So the displayed full-document body never corresponds to what an edit would send. (Defect 1.3)

3. **Origin fallback to localhost — caused by GET vs POST, not by the builders.** The surface builders already resolve the origin correctly via `_resolve_base_origin(base_url)` / the `_build_invoice_surface` chain. The real defect is at the **router boundary**: the preview endpoint `GET /api/v2/email-preview` passes `base_url = request.headers.get("origin")`, but browsers do **not** send an `Origin` header on a same-origin **GET** request, so `base_url` is `None` and resolution falls through to `settings.frontend_base_url` → `http://localhost`. The send endpoints are **POST** requests, which **do** carry `Origin`, so they resolve the real public host (`https://devin.oraflows.co.nz`). Same line of code, different HTTP method, different result. The fix is to resolve the preview origin from a source that exists on a GET — the existing `extract_request_base_url(request)` helper in `app/core/request_utils.py`, which falls back to the `Host` header when `Origin` is absent. (Defect 1.2)

4. **Property 1 never exercised the display path.** It compares two render paths that are identical by construction, so it could not catch a presentation-layer mismatch. A new regression property is required.

## Correctness Properties

Property 1 (Bug Condition — No chrome / subject leak in the editable body)

_For any_ supported `(template_type, entity)`, the inner-body fragment the editor binds to SHALL NOT contain `<!DOCTYPE>`, `<html>`, `<head>`, or `<title>`, and its rendered text SHALL NOT contain the subject line.

**Validates: Requirements 2.1, 4.1**

Property 2 (Bug Condition — Displayed body corresponds to sent body)

_For any_ supported `(template_type, entity)` sent on the default (unedited) path, the inner-body fragment displayed in the editor SHALL be the same fragment that, after the send path wraps + sanitises it, is dispatched — modulo the expected CTA-button presentation difference.

**Validates: Requirements 2.3, 4.2**

Property 3 (Bug Condition — Preview origin equals send origin)

_For any_ preview request, the origin the preview resolves for links SHALL equal the origin the corresponding POST send path resolves — specifically, on a same-origin GET (no `Origin` header) the preview SHALL resolve the public origin from the `Host` header rather than falling back to `settings.frontend_base_url`/`localhost`.

**Validates: Requirements 2.2, 4.3**

Property 4 (Preservation — Default send byte-equivalence)

_For any_ supported `(template_type, entity)`, the full-document render used by the default send path SHALL remain byte-equivalent to the sanitised sent HTML (the existing Property 1 in `tests/test_email_compose_default_equivalence.py` continues to pass unchanged).

**Validates: Requirements 3.1, 3.2**

Property 5 (Preservation — Edited override send unchanged)

_For any_ edited body submitted via the modal, the send path SHALL continue to sanitise and send the fragment as-is with unchanged audit hashing.

**Validates: Requirements 3.3**

Property 6 (Dual-mode round-trip — new capability)

_For any_ inner-body fragment, switching the editor Rich→HTML→Rich SHALL preserve the semantic HTML (the fragment displayed in HTML mode equals `editor.getHTML()`, and re-entering Rich mode with that text reproduces the same document), and the value emitted to the parent SHALL be the fragment that the send path sends.

**Validates: New dual-mode requirement; Requirements 3.3**

## Fix Implementation

### Chosen approach: server returns an explicit inner-body fragment; editor binds to the fragment

The preview response gains a dedicated **editable fragment** field that the editor binds to, while the existing full-document `body_html` is retained for backward-compatible byte-equivalence checks and as the faithful "this is the whole email" representation. This is preferred over frontend-only chrome-stripping because:

- The dual-mode HTML feature needs a well-defined fragment contract — the user authors a *body fragment*, not a document. Making the contract explicit server-side keeps web and mobile consistent and avoids each client re-deriving "what is editable" with a DOMParser.
- It keeps the byte-equivalence test meaningful: the full-document field still exists and Property 1 still compares full documents.
- The send path already accepts a fragment for edited bodies, so the editor's output already matches the send contract with zero backend send-path change.

Rejected alternative (frontend-only `DOMParser` extracting `body > div` innerHTML): simpler for the bug alone, but it (a) duplicates extraction logic across web + mobile, (b) is fragile against future `render_transactional_html` markup changes, and (c) gives the HTML-edit mode an ambiguous contract (is the user editing a fragment or a document?). We adopt a small piece of it as defence-in-depth for paste handling (below).

### Backend changes

**File: `app/modules/email_compose/service.py`**

1. Refactor the per-surface render so the **inner-body fragment** is produced separately from the full document. Today `build_email_preview` does:
   ```python
   raw_html = render_transactional_html(body_text, subject=subject, signature_html=…, cta_url=…, cta_label=…)
   body_html = sanitise_email_html(raw_html)
   ```
   Add a fragment renderer that produces only the editable inner body (paragraphs + signature block), reusing the existing `_text_to_paragraphs_html` building block from `email_sender.py` so the paragraph markup is identical to the document body. The CTA button and document chrome are intentionally excluded from the fragment (the CTA is regenerated by the send path's `render_transactional_html` from `cta_url`/`cta_label`, which are already separate preview fields the frontend can show as an informational "Call to action" line).

   Expose a small helper in `app/integrations/email_sender.py`, e.g. `render_body_fragment_html(text_body, *, signature_html=None) -> str`, that returns `"".join(paragraphs) + signature_block` using the SAME `_text_to_paragraphs_html` + signature `<hr>` markup `render_transactional_html` uses internally. `render_transactional_html` is refactored to call this helper for its inner content so the two can never drift (single source of truth). Its full-document output and signature MUST remain byte-identical (Property 1).

2. In `build_email_preview`, compute both:
   - `body_html` (existing field, unchanged meaning): `sanitise_email_html(render_transactional_html(…))` — the full document.
   - `body_editable_html` (NEW field): `sanitise_email_html(render_body_fragment_html(body_text, signature_html=…))` — the inner fragment the editor binds to. For surfaces that already produce HTML bodies (the reminder surfaces with `body_is_html`), the fragment is the sanitised body HTML directly (it is already a fragment).

3. Origin resolution: fix the **router**, not the builders. The surface builders already resolve correctly from `base_url`; the bug is that `GET /api/v2/email-preview` receives no `Origin` header (browsers omit it on same-origin GETs) so `base_url` is `None`. In `app/modules/email_compose/router.py`, replace `base_url=request.headers.get("origin") or None` with `base_url=extract_request_base_url(request)` (from `app/core/request_utils.py`), which falls back to the `Host` header (set by nginx) when `Origin` is absent — yielding the same public origin the POST send paths see. Note: the send routers (`invoices`, `quotes`, etc.) currently pass the bare `request.headers.get("origin")`; on their POSTs `Origin` is present so they already get the right value. The preview only needs the `Host` fallback to match them; do NOT change the send routers in this bugfix.

**File: `app/modules/email_compose/schemas.py`**

Add `body_editable_html: str` to `EmailPreviewResponse` (alongside the existing `body_html: str`). `OverrideSendPayload.body_html` is unchanged — the client continues to send the edited fragment in `body_html`, which is exactly what the send path already sanitises and sends.

**Send services: NO CHANGE.** `email_invoice`, `quotes.service`, `reports.service`, `customers.service`, `payments.service`, `notifications.service` all keep `if body_html is not None: html_body = sanitise_email_html(body_html)`. Because the editor now emits a fragment (as it always did via `getHTML()`), and the default-omit-when-unedited rule (R3.6) is unchanged, the byte-equivalence contract is preserved.

### Frontend changes (web)

**File: `frontend-v2/src/components/email/types.ts`**
- Add `body_editable_html: string` to `EmailPreviewResponse`.

**File: `frontend-v2/src/components/email/SendEmailModal.tsx`**
- In `hydrateFromPreview`, seed `defaultBodyRef.current` and `bodyHtml` from `data.body_editable_html ?? ''` instead of `data.body_html`. The omit-unchanged payload logic (`if (bodyWasEdited) payload.body_html = bodyHtml`) is unchanged — the fragment is what gets sent, which the server sanitises. The "send default" path still omits `body_html`, so the server renders its byte-equivalent default. All access uses `?.` / `?? ''` (safe API consumption).

**File: `frontend-v2/src/components/email/BodyEditor.tsx`** — dual-mode editor
- Add a `mode` state: `'rich' | 'html'`, defaulting to `'rich'`.
- Add a two-button segmented toggle in the toolbar ("Rich text" / "HTML"), each `min-h`/Tab-reachable, `aria-pressed`, matching the existing `ToolbarButton` styling.
- **Rich mode**: unchanged TipTap editor (StarterKit + configured Link), now seeded with the inner fragment so no `<title>` text leaks. The crash-fix guards (`immediatelyRender: false`, `if (!editor || editor.isDestroyed) return`) stay.
- **HTML mode**: a `font-mono` `<textarea>` (the established raw-input pattern in frontend-v2) bound to the current fragment HTML. Editing the textarea calls `onChange(rawHtml)` directly. Switching Rich→HTML seeds the textarea from `editor.getHTML()`; switching HTML→Rich calls `editor.commands.setContent(rawHtml, { emitUpdate: false })` then resumes WYSIWYG. `body_was_edited` is set on first divergence in EITHER mode (the existing `handleBodyChange` comparison against `defaultBodyRef.current` already covers this).
- **Paste safety in HTML mode**: when a user pastes content into the HTML textarea, run it through a hardened version of the existing `stripUnsafePastedHtml` that ALSO removes `<head>`, `<title>`, `<html>`, `<body>`, and `<!DOCTYPE>` (extract `body.innerHTML` when a full document is detected) so a pasted full document degrades to its body fragment and cannot re-introduce the title-leak. The server `sanitise_email_html` allowlist remains the authoritative defence (it strips disallowed tags but preserves their text, hence the client-side head/title removal).
- The CTA stays out of the editable area; if `cta_url`/`cta_label` are present the editor shows a read-only informational line ("Button: {label} → {url}") so users understand the email will include a button they cannot edit here. This is optional polish and may be deferred.
- Reset-to-default restores `defaultBodyRef.current` (the fragment) in whichever mode is active.

**File: `frontend-v2/src/components/email/SendEmailModal.test.tsx`**
- Update the `body_html` stub fixture to also provide `body_editable_html`. The lazy-editor textarea stub already mirrors the dual-mode textarea closely enough for the modal-level tests.

### Frontend changes (mobile)

Mirror the web changes:
- **`mobile/src/components/email/SendEmailSheet.tsx`**: seed body from `data.body_editable_html ?? ''`. Mobile does NOT declare its own `EmailPreviewResponse` — `mobile/src/components/email/types.ts` re-exports the web type verbatim via the `@email-contract` path alias, so the `body_editable_html` field added in `frontend-v2/.../types.ts` is automatically available on mobile (no separate type edit).
- **`mobile/src/components/email/MobileBodyEditor.tsx`**: add the same `rich | html` mode toggle and `font-mono` textarea, touch targets ≥44px (`min-h-[44px]`), dark-mode `dark:` variants, and the same paste hardening. Capacitor is not involved.
- Update `mobile/src/components/email/__tests__/SendEmailSheet.test.tsx` fixture with `body_editable_html`.

## Testing Strategy

### Validation Approach

Two phases: first surface the bug on unfixed code, then verify the fix and preservation. Backend tests run via `docker compose exec app python -m pytest <files>`; mobile tests + `tsc` run on the HOST in `mobile/` (the mobile container has no source mount); frontend-v2 component tests via Vitest.

### Exploratory Bug Condition Checking

**Goal**: Confirm the root cause before fixing.

- Backend: add a test asserting the CURRENT `build_email_preview().body_html` contains `<title>` and the subject string (demonstrates the chrome/leak source).
- Frontend: a `BodyEditor` test that mounts the REAL editor (not the textarea stub) with a full-document `valueHtml` and asserts the rendered editor text contains the subject (demonstrates the display leak). This closes the CI gap where the stub hid the real `useEditor` behavior.

### Fix Checking

```
FOR ALL X WHERE isBugCondition(X) DO
  frag ← preview(X).body_editable_html
  ASSERT frag DOES NOT CONTAIN "<!DOCTYPE" / "<head" / "<title"
  ASSERT editorVisibleText(frag) DOES NOT CONTAIN X.subject
  ASSERT resolvePreviewOrigin(X) = resolveSendOrigin(X)
END FOR
```

- **New backend regression property** (`tests/test_email_preview_editable_fragment.py`): Hypothesis-vary entity data across the supported surfaces; assert `body_editable_html` contains no `<!DOCTYPE>/<head>/<title>` and, when stripped to text, does not contain the subject. Assert preview origin == send origin for varied `(origin, payment_page_url)` inputs.
- **Frontend component tests** (real editor): opening the modal seeds the editor with a fragment; the editor text does not begin with the subject line.

### Preservation Checking

```
FOR ALL X DO
  ASSERT render_default_full_document(X) = sanitise_email_html(sent_html(X))   // Property 1, unchanged
END FOR
FOR ALL edited-body E DO
  ASSERT send(E) = sanitise_email_html(E.body_html)                            // override path, unchanged
END FOR
```

- **Property 1** (`tests/test_email_compose_default_equivalence.py`): MUST pass unchanged. It compares the full-document `body_html`/sent HTML, which this design does not alter. Run it explicitly after the refactor of `render_transactional_html` (since that function is touched to extract the shared fragment helper, its full-document output must stay byte-identical).
- Existing modal/sheet tests: the unedited send still omits `body_html`; edited send still includes the fragment.

### Unit / Component Tests

- `render_body_fragment_html` produces the same paragraph markup as the body region of `render_transactional_html` for the same input (shared-helper invariant).
- `BodyEditor` mode toggle: Rich→HTML shows `getHTML()`; HTML→Rich re-renders the same content (Property 6 round-trip).
- HTML-mode paste of a FULL document degrades to its body fragment (no `<title>`/`<head>` survives) before reaching `onChange`.
- `body_was_edited` flips on edit in BOTH modes; reset-to-default clears it and restores the fragment.
- Mobile: same toggle round-trip; touch targets ≥44px; dark-mode classes present.

### Integration Tests

- Open Send Invoice → no subject line in the body → send default → received email body (minus the CTA-button presentation) matches the displayed fragment, and links use the request origin.
- HTML mode: paste a styled `<table>` template → send → server sanitises (tables/styles allowed) → email body equals the authored fragment.

## Requirements Mapping

| Design section | Requirements (bugfix.md) |
|---|---|
| Backend fragment field + editor binding | 2.1, 2.3, 4.1, 4.2 |
| Origin resolution parity | 2.2, 4.3, 3.6 |
| Default send render + Property 1 untouched | 3.1, 3.2, 4 (preservation) |
| Edited override send unchanged | 3.3 |
| CTA stays plain text in editor | 3.4 |
| Other surfaces unchanged | 3.5 |
| Dual-mode rich/HTML editing | New dual-mode requirement (+3.3 fragment-send contract) |
