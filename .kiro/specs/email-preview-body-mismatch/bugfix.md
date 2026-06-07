# Bugfix Requirements Document

## Introduction

In the OraInvoice "Send Invoice" modal (`SendEmailModal`), the email body shown in the editable preview differs from the email the customer actually receives. The user reproduced this on the local dev stack via `https://devin.oraflows.co.nz/` and supplied two screenshots showing the divergence.

Root cause (verified by reading the code): the Email_Preview_Endpoint `GET /api/v2/email-preview` (`app/modules/email_compose/service.py::build_email_preview`) returns `body_html` as a **complete transactional HTML document**, produced by `app/integrations/email_sender.py::render_transactional_html(...)` then `sanitise_email_html(...)`. That document has the shape:

```
<!DOCTYPE html><html lang="en"><head><meta charset><meta viewport><title>{SUBJECT}</title></head>
<body ...><div ...>{paragraphs}{CTA button <table>}{signature}</div></body></html>
```

The frontend (`frontend-v2/src/components/email/SendEmailModal.tsx` → `BodyEditor.tsx`) feeds that whole document straight into a TipTap/ProseMirror rich-text editor (StarterKit only). ProseMirror parses the full document and extracts head/document text — including the contents of `<title>{SUBJECT}</title>` — as editable body content. Two real divergences result (plus one expected, out-of-scope difference):

- **Primary:** the subject line leaks into the body as the first editable paragraph in the modal, but the actually-sent email keeps the subject only in `<title>` (never in the visible body). So the modal shows a leading line the customer never receives.
- **Secondary:** the modal's CTA/links are built with a different origin (`http://localhost/...`) than the sent email (`https://devin.oraflows.co.nz/...`), because the preview router passes `base_url = request.headers.get("origin")` and `_resolve_base_origin` falls back to `settings.frontend_base_url` / `http://localhost`, whereas the real send (`app/modules/invoices/service.py::email_invoice`) resolves the origin differently (request origin → origin parsed from `payment_page_url` → settings → localhost).

This is a presentation-layer mismatch between "the HTML handed to the editor" and "the HTML actually sent" — not a render-path divergence. The existing Property 1 (`tests/test_email_compose_default_equivalence.py`) asserts `preview.body_html == sanitise_email_html(sent.html_body)`; those two render paths are byte-identical by construction, so it never exercised how TipTap displays the document and could not catch this bug.

Out of scope: the CTA rendering as plain text in the editor vs a styled button in the email. TipTap cannot round-trip a full inline-styled HTML `<table>` button, and this presentation difference is expected.

## Bug Analysis

### Current Behavior (Defect)

What currently happens when the bug is triggered:

1.1 WHEN the Send Invoice modal opens and loads `body_html` from `GET /api/v2/email-preview` (a complete HTML document) into the TipTap editor THEN the editor extracts the `<title>{subject}</title>` (and/or other document-head text) and the system displays the subject line (e.g. "Invoice SPINV-0057 from SP Automotive") as the first editable body paragraph, which the customer's received email does NOT contain.

1.2 WHEN the modal preview builds CTA/links from the preview-resolved origin AND that origin resolves to `http://localhost` (or otherwise differs from the send path's resolved origin) THEN the system displays links pointing to a different origin (e.g. `http://localhost/...`) than the links in the email the customer receives (e.g. `https://devin.oraflows.co.nz/...`).

1.3 WHEN the user sends the email without editing the body (the "send default" path) THEN the system sends an email whose visible body does not match what was displayed in the modal (missing the leaked subject line and using a different link origin), so the modal is not a faithful preview of what is sent.

### Expected Behavior (Correct)

What should happen instead:

2.1 WHEN the Send Invoice modal opens and loads the preview body into the TipTap editor THEN the system SHALL display editable body content that contains only the content the user can actually edit (the body paragraphs and signature) and SHALL NOT display the subject line or any document-head/chrome text (`<title>`, `<head>`, doctype) as body content.

2.2 WHEN the modal preview builds CTA/links THEN the system SHALL resolve the public origin using the SAME resolution order as the real send path (`email_invoice`: request origin → origin parsed from `payment_page_url` → `settings.frontend_base_url` → `http://localhost`), so the links shown in the modal match the links in the email the customer receives.

2.3 WHEN the user sends the email without editing the body (the "send default" path) THEN the system SHALL send an email whose visible body matches what was displayed in the modal, modulo the expected CTA-button presentation difference (plain link text in the editor vs styled button in the email).

### Unchanged Behavior (Regression Prevention)

Existing behavior that must be preserved:

3.1 WHEN the user sends the email without editing subject, body, recipients, or attachments (the "send default" path) THEN the system SHALL CONTINUE TO produce a sent email whose rendered HTML is byte-equivalent to the pre-modal auto-send render — i.e. Property 1 (`preview default render == sanitise_email_html(sent.html_body)`) SHALL CONTINUE TO hold.

3.2 WHEN the email is actually sent THEN the system SHALL CONTINUE TO wrap the body in the full transactional HTML document via `render_transactional_html` (doctype, `<head>`, `<title>{subject}</title>`, CTA button `<table>`, signature) so deliverability behavior is unchanged.

3.3 WHEN the user edits the body in the modal and sends THEN the system SHALL CONTINUE TO send the edited body content (server-sanitised), preserving the existing override-send behavior and audit hashing.

3.4 WHEN the modal renders the CTA THEN the system SHALL CONTINUE TO show the CTA as plain link text in the editor (the expected, out-of-scope presentation difference) without attempting to render an inline-styled email button inside TipTap.

3.5 WHEN the preview is requested for any non-invoice surface (quote_sent, customer_statement, payment_received, invoice_payment_link, portal_link, and the vehicle reminders) THEN the system SHALL CONTINUE TO resolve subject, body, recipients, attachments, sender identity, and blocklist exactly as before for those surfaces.

3.6 WHEN the request origin header is present and matches the send path's resolution THEN the system SHALL CONTINUE TO build links from that origin (no change for the already-correct case).

### Regression Property Requirement

A new regression property/test MUST be added (in addition to preserving Property 1) capturing the presentation-layer invariant this bug exposed:

4.1 WHEN the preview's editable body content is loaded into the editor representation THEN the system SHALL guarantee the editable content does NOT contain the subject line text and does NOT contain document-head/chrome markup (`<!DOCTYPE>`, `<head>`, `<title>`), for all supported surfaces.

4.2 WHEN the user sends the default (unedited) content THEN the system SHALL guarantee that what is displayed as the editable body corresponds to what is sent (modulo the expected CTA-button presentation difference), so the modal is a faithful preview.

4.3 WHEN resolving the link origin for the preview THEN the system SHALL guarantee the preview's resolved origin equals the send path's resolved origin for the same inputs (request origin, `payment_page_url`, settings).

---

## Bug Condition Methodology

### Bug Condition — C(X)

`X` is a Send-Email-Modal preview request: `(template_type, entity_type, entity_id, request_origin, payment_page_url, settings.frontend_base_url)` together with the resulting `body_html` handed to the editor.

```pascal
FUNCTION isBugCondition(X)
  INPUT: X = preview request + resulting editor body_html
  OUTPUT: boolean

  // Primary: the body handed to the editor is a full HTML document whose
  // head/title text becomes visible editable body content.
  leaks_subject ← editorVisibleBody(X.body_html) CONTAINS X.subject
                  OR X.body_html CONTAINS "<title>" OR "<!DOCTYPE" OR "<head>"

  // Secondary: the preview origin differs from the send-path origin.
  origin_mismatch ← resolvePreviewOrigin(X) ≠ resolveSendOrigin(X)

  RETURN leaks_subject OR origin_mismatch
END FUNCTION
```

### Property — Fix Checking

```pascal
// Property: Fix Checking — editable body has no chrome/subject leak,
// and preview links match send links.
FOR ALL X WHERE isBugCondition(X) DO
  editable ← editorVisibleBody(F'(X).body_html)
  ASSERT editable DOES NOT CONTAIN X.subject
  ASSERT editable DOES NOT CONTAIN "<title>" AND NOT "<!DOCTYPE" AND NOT "<head>"
  ASSERT resolvePreviewOrigin(F'(X)) = resolveSendOrigin(X)
END FOR
```

### Property — Preservation Checking

```pascal
// Property: Preservation Checking — for the default (unedited) send path,
// the final rendered/sent HTML is unchanged (Property 1 still holds).
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT F(X) = F'(X)
END FOR

// And specifically for the default send render across ALL inputs:
FOR ALL X DO
  ASSERT render_default(F'(X)) = sanitise_email_html(sent_html(X))   // Property 1
END FOR
```

**Definitions:**
- **F** — the current (unfixed) preview/display behavior, where `body_html` is a full HTML document fed directly to TipTap.
- **F'** — the fixed behavior, where the editable body is only the inner content and the server re-wraps it via `render_transactional_html` at send time (or the frontend extracts only the inner body before handing it to TipTap), and the preview origin resolution mirrors the send path.
- **Counterexample** — opening the Send Invoice modal for invoice `SPINV-0057`: the modal shows "Invoice SPINV-0057 from SP Automotive" as the first body line and links to `http://localhost/...`, while the received email omits that line and links to `https://devin.oraflows.co.nz/...`.
