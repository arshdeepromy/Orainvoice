# Implementation Plan — Send Email Modal

## Overview

This plan converts the Send Email Modal design into incremental, dependency-ordered
coding tasks. It builds a single shared "Send Email" composer (web modal + mobile sheet)
that pre-loads default content for seven send surfaces, lets the user review/edit
recipients, subject, body, and attachments, and dispatches through the existing unified
email sender — with server-side HTML sanitisation, attachment-token IDOR protection, and
notification-log audit columns.

This feature **depends on** the `notification-template-integration` spec's
`resolve_template()` (plus `get_template_for_locale()`, `_render_blocks_to_text()`, and
`_substitute_variables()` in `app/modules/notifications/service.py`), which is already
present in the codebase. The preview path reuses those functions so the preview body is
byte-identical to the auto-send body.

All work targets the **local dev environment only**. Pi-prod, Pi standby, and local
prod-standby deployment are out of scope (R29) — there are no deploy, `git push`, or
`git tag` tasks here. The active web app is `frontend-v2/`; the archived `frontend/` is
untouched (R16.6).

The build order is: backend leaf utilities (sanitiser, cc/bcc, migration, schemas,
attachment token) → preview endpoint → override send endpoints → shared web contract →
web components → per-surface web triggers → mobile sheet → tests → versioning → final
verification. Each increment ends in wired-together, testable functionality.

Notes:
- Tasks marked with `*` are optional polish and may be skipped. The four required
  property tests (P1–P4), the e2e script, the per-component unit tests, and the example
  backend tests are NOT optional (required by R21).
- The migration is revision `0214` with `down_revision = "0213"` (current alembic head),
  and MUST be applied inside the dev container per the database-migration-checklist.

## Tasks

- [x] 1. Backend foundations — HTML sanitiser (Body_Sanitiser)
  - [x] 1.1 Add `bleach[css]==6.4.0` and implement `app/integrations/html_sanitise.py`
    - Add `"bleach[css]==6.4.0"` to `pyproject.toml` dependencies (pulls `tinycss2` for the style-attribute allowlist). MUST be `6.4.0` — versions 6.1.0–6.3.0 cap `tinycss2<1.5` and break the installed weasyprint 68.1 (needs `tinycss2>=1.5.0`); 6.4.0 relaxes to `tinycss2>=1.1.0` and the sanitiser API is unchanged
    - Define module-level constants `ALLOWED_TAGS`, `ALLOWED_ATTRIBUTES`, `ALLOWED_PROTOCOLS` (`http`, `https`, `mailto`), `ALLOWED_STYLES`
    - Implement `sanitise_email_html(raw: str) -> str` using `bleach.Cleaner(..., strip=True, css_sanitizer=...)`; strip all `on*` handler attributes, `javascript:`/`data:`/`file:` URLs, and disallowed tags/attrs/styles; must be idempotent
    - Design ref: "Body_Sanitiser — app/integrations/html_sanitise.py"
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

  - [x] 1.2 Write example XSS unit tests in `tests/test_html_sanitise.py`
    - Assert specific OWASP payloads are neutralised: `<script>alert(1)</script>`, `<a href="javascript:alert(1)">`, `onerror=...`, `data:` URLs
    - Design ref: Testing Strategy → "Backend example/integration tests"
    - _Requirements: 10.7, 21.6_

  - [x] 1.3 Write property test for Body_Sanitiser in `tests/test_html_sanitise.py`
    - **Property 2: Sanitiser strips unsafe markup and is idempotent** (Hypothesis, min 100 iterations)
    - For any HTML input, output contains no `<script>`, no `on*` attribute, no `javascript:`/`data:`/`file:` URL; and `sanitise_email_html(sanitise_email_html(x)) == sanitise_email_html(x)`
    - Tag: `Feature: send-email-modal, Property 2: Sanitiser strips unsafe markup and is idempotent`
    - **Validates: Requirements 10.2, 10.3, 10.4, 10.5, 10.6, 10.7**

- [x] 2. Add Cc/Bcc support to the unified email sender
  - [x] 2.1 Add `cc`/`bcc` to `EmailMessage` and thread through all transports — `app/integrations/email_sender.py`
    - Add `cc: list[str]` and `bcc: list[str]` fields (default empty) to the `EmailMessage` dataclass
    - Brevo/SendGrid/Resend REST dispatchers: add provider `cc`/`bcc` arrays when non-empty
    - SMTP (`_build_mime_message` + `_dispatch_smtp`): set the `Cc` header from `cc`; do NOT set a `Bcc` header; pass all envelope recipients to `sendmail` (`[to_email, *cc, *bcc]`) so BCC stays envelope-only and never appears in any visible header
    - This is the only integration point — no new send path is introduced
    - Design ref: Data Models §1 "EmailMessage cc/bcc additions"
    - _Requirements: 4.9, 8.3, 16.5_

  - [x] 2.2 Write BCC-privacy unit test for the MIME builder + REST payload builders
    - Assert BCC addresses never appear in the `To:`/`Cc:` headers, but DO appear in the SMTP envelope RCPT TO list and the REST `bcc` arrays
    - Design ref: Testing Strategy → "BCC-privacy unit test on `_build_mime_message`"
    - _Requirements: 4.9_

- [x] 3. notification_log audit columns, migration 0214, and new template types
  - [x] 3.1 Add six audit columns to the `NotificationLog` model — `app/modules/notifications/models.py`
    - `subject_was_edited` (Boolean, default false), `body_was_edited` (Boolean, default false), `edited_subject_hash` (String(64), nullable), `edited_body_hash` (String(64), nullable), `cc_recipients` (JSONB, default `[]`), `bcc_recipients` (JSONB, default `[]`)
    - Design ref: Data Models §2 "notification_log migration 0214"
    - _Requirements: 11.1_

  - [x] 3.2 Create and apply Alembic migration `0214` adding the six columns
    - File `alembic/versions/2026_06_06_0001-0214_send_email_modal_audit.py`, `revision = "0214"`, `down_revision = "0213"`
    - Use `op.add_column` for all six columns (no index, so no `CONCURRENTLY` needed); `server_default` for the two booleans and the two JSONB `'[]'::jsonb` columns; downgrade drops all six
    - Run `docker compose exec app alembic upgrade head` inside the dev container and verify the output shows "Running upgrade 0213 -> 0214" with no errors (per database-migration-checklist)
    - _Requirements: 11.1, 11.9_

  - [x] 3.3 Add the three new template types and their defaults — `app/modules/notifications/schemas.py`
    - Add `invoice_payment_link`, `customer_statement`, `portal_link` to `EMAIL_TEMPLATE_TYPES`
    - Add default subjects and body-blocks for the three new types in `DEFAULT_SUBJECTS` / `_DEFAULT_BODY_BLOCKS`
    - (No DB CHECK constraint exists on `template_type`; the allowed list lives in this schema module per the design's investigation note)
    - Design ref: Data Models §3 "notification_templates — three new template types"
    - _Requirements: 11.9, 20.1, 20.2_

- [x] 4. notification_log serializer, response schema, and audit-aware logging
  - [x] 4.1 Expose the six audit columns on the serializer and Pydantic schema
    - Update `_log_entry_to_dict()` in `app/modules/notifications/service.py` to emit all six fields on every row
    - Add the six fields to `NotificationLogEntry` / `NotificationLogResponse` in `app/modules/notifications/schemas.py` so Pydantic does not silently drop them (frontend-backend-contract-alignment Rule 8)
    - _Requirements: 11.5, 11.6, 11.7, 11.8_

  - [x] 4.2 Add audit parameters to `log_email_sent()` — `app/modules/notifications/service.py`
    - Add optional `subject_was_edited`, `body_was_edited`, `edited_subject_hash`, `edited_body_hash`, `cc_recipients`, `bcc_recipients` params (defaulting to no-edit values)
    - Empty cc/bcc persist as the JSONB array `[]`, never `null`; preserve existing `provider_key`/`provider_message_id`/`status`/`sent_at` behaviour
    - _Requirements: 11.2, 11.3, 11.4, 11.5, 11.6_

- [x] 5. Attachment_Token (HMAC) build/validate
  - [x] 5.1 Implement the token builder/validator — `app/modules/email_compose/service.py` (new module)
    - Create `app/modules/email_compose/__init__.py` and `service.py`
    - `build_attachment_token(org_id, entity_id, attachment_kind, expires_at)`: payload `f"{org_id}:{entity_id}:{attachment_kind}:{expires_at_epoch}"`, HMAC-SHA256 with a key HKDF-derived from `settings.jwt_secret` (info `b"email-attachment-token-v1"`), base64url-encoded. NOTE: there is no `SECRET_KEY` setting in `app/config.py`; use `settings.jwt_secret` (verified to exist).
    - `validate_attachment_token(token, org_id, entity_id) -> str | None`: constant-time HMAC compare, check `expires_at > now`, assert embedded `org_id`/`entity_id` match the request; return `attachment_kind` or `None`
    - `attachment_kind` ∈ `invoice_pdf`, `invoice_pdf_paid`, `customer_statement_pdf`, `quote_pdf`; expiry now + 30 minutes
    - Design ref: Data Models §4 "Attachment_Token (HMAC) shape and signing key"
    - _Requirements: 7.6_

  - [x] 5.2 Write property test for attachment-token validation — `tests/test_email_compose_attachment_token.py`
    - **Property 3: Attachment-token validation is entity- and org-scoped** (Hypothesis, min 100 iterations)
    - A token validates (returns the original kind) only with the same `org_id`/`entity_id` and a future expiry; rejected (`None`) for any different org/entity, tampered signature, or past expiry
    - Tag: `Feature: send-email-modal, Property 3: Attachment-token validation is entity- and org-scoped`
    - **Validates: Requirements 7.6**

- [x] 6. Email compose module — schemas, service, and preview endpoint
  - [x] 6.1 Define Pydantic schemas — `app/modules/email_compose/schemas.py`
    - `EmailPreviewResponse` declaring every field: `subject`, `body_html`, `recipients`, `cc`, `bcc`, `variable_context`, `attachments`, `default_was_template`, `sender_preview`, `blocklisted`, `locale`, `email_size_limit_bytes`, `total_budget_seconds`; plus `SenderPreview`, `AttachmentSpec`, `BlocklistEntry`
    - `OverrideSendBase` with `model_config = ConfigDict(extra="forbid")` declaring `recipients`, `cc`, `bcc`, `subject` (max_length 255), `body_html`, `attachments`, `subject_was_edited`, `body_was_edited`, `override_blocklist`; plus one subclass per surface (invoice/payment-link/receipt/quote/statement/portal-link/reminder-resend)
    - Field names must match `frontend-v2/src/components/email/types.ts` exactly
    - _Requirements: 3.2, 3.9, 11.10_

  - [x] 6.2 Implement the preview service + helpers — `app/modules/email_compose/service.py`
    - `build_email_preview(...)`: load the entity RLS-scoped (raise `EntityNotFound` → 404, `PermissionError` → 403); resolve customer + locale; build variable context; call `resolve_template()` (→ `default_was_template=True`) or compute the surface's hardcoded fallback (→ `False`); pass body through `sanitise_email_html`; build attachment list (HMAC tokens via task 5) and `blocklisted` array from `bounced_addresses`; assemble `sender_preview`, `email_size_limit_bytes = EMAIL_SIZE_LIMIT`, `total_budget_seconds = EMAIL_TOTAL_BUDGET_SECONDS`
    - `build_variable_context(template_type, ...)`: per-type variable maps matching the existing send functions / `resolve_template()` (basis for Property 1)
    - `get_attachments_for_surface(...)`: documented per-surface defaults and `required` flags (R7.7)
    - `resolve_locale(...)`: Locale_Resolution_Chain — customer `language` → org `default_locale` → `en`
    - `compute_audit_hashes(subject, sanitised_body)`: pure helper returning `sha256` hex digests (consumed by override send paths; basis for Property 4)
    - Design ref: Backend Components → `service.py`; Data Models §5 variable-context map
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.10, 7.5, 7.7, 9.2, 13.1, 16.4, 20.4, 20.5_

  - [x] 6.3 Implement `GET /api/v2/email-preview` and register the router
    - `app/modules/email_compose/router.py`: route `/email-preview` with `dependencies=[require_role("org_admin", "salesperson")]`; extract org context; map `EntityNotFound` → 404 and `PermissionError` → 403; return `EmailPreviewResponse`
    - Register in `app/main.py` with `include_router(email_compose_router, prefix="/api/v2", tags=["v2-email-compose"])` so the full path is exactly `GET /api/v2/email-preview`
    - Confirm middleware posture: authenticated (not in `PUBLIC_PATHS`/`PUBLIC_PREFIXES`), RLS GUC set by the existing dependency chain, standard per-user rate limit (no exemption), no CSRF on the GET but JWT required
    - Design ref: Backend Components → `router.py`
    - _Requirements: 3.1, 3.7, 8.11, 18.3, 25.1, 25.2, 25.3, 25.4_

- [x] 7. Preview endpoint tests + property tests P1 and P4
  - [x] 7.1 Write preview endpoint example/integration tests — `tests/test_email_compose_preview.py`
    - Preview returns a complete `EmailPreviewResponse` for all 10 template types (R20.1)
    - Cross-org IDOR → 403/404; unauthenticated → 401
    - _Requirements: 20.1, 21.6, 25.1, 25.2_

  - [x] 7.2 Write property test for send-default byte-equivalence — `tests/test_email_compose_default_equivalence.py`
    - **Property 1: Send-default byte-equivalence** (Hypothesis, min 100 iterations)
    - For any supported `(template_type, entity)`, the subject + sanitised `body_html` bytes from `build_email_preview()` exactly equal the bytes the underlying send function produces on its no-override default-render path
    - Tag: `Feature: send-email-modal, Property 1: Send-default byte-equivalence`
    - **Validates: Requirements 3.6, 20.5**

  - [x] 7.3 Write property test for audit hash — `tests/test_email_compose_audit_hash.py`
    - **Property 4: Audit hash is computed over the post-sanitisation body** (Hypothesis, min 100 iterations)
    - For any edited raw `body_html`, `edited_body_hash == sha256(sanitise_email_html(raw)).hexdigest()`; whenever sanitisation changes the string the hash differs from `sha256(raw)`; equivalently `edited_subject_hash == sha256(final_subject)`
    - Tag: `Feature: send-email-modal, Property 4: Audit hash over post-sanitisation body`
    - **Validates: Requirements 11.2, 11.3**

- [x] 8. Override send endpoints + service override params (one sub-task per surface)
  - [x] 8.1 Invoice email override — `app/modules/invoices/service.py::email_invoice` + `POST /invoices/{id}/email`
    - Accept `subject`, `body_html`, `recipients`, `cc`, `bcc`, `attachments`, `subject_was_edited`, `body_was_edited`, `override_blocklist`; when `body_html` present, sanitise it; when omitted, run the unchanged default-render path (byte-equivalence)
    - Validate every `attachments` key via `validate_attachment_token()` against the preview-time set → unknown/expired/cross-entity returns 400 "Invalid attachment selection."
    - Thread cc/bcc into `EmailMessage`; ignore any client `from_email`/`from_name`/`reply_to`; honour `override_blocklist=true` only for `org_admin` (else 403)
    - Map `SendResult.failure_kind` → HTTP (HARD_RECIPIENT 400, HARD_PAYLOAD 413, SOFT_AUTH 502, SOFT_PROVIDER/BUDGET_EXCEEDED 503; success 200); write audit columns via `log_email_sent`; router does `await db.commit()`; retain existing role gate + CSRF
    - _Requirements: 2.1, 7.6, 8.1, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 9.3, 10.1, 11.2, 11.3, 11.5, 13.5, 15.2, 16.5_

  - [x] 8.2 Invoice payment-link override — `payments.service.send_invoice_payment_link_email` + `POST /payments/invoice/{id}/send-payment-link`
    - Same override set threaded through `_send_receipt_email`; same sanitise/attachment-validation/FailureKind→HTTP/audit-logging behaviour as 8.1
    - _Requirements: 2.2, 7.6, 8.1, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 9.3, 11.2, 11.3, 11.5_

  - [x] 8.3 Receipt override (new endpoint) — `invoices.service.email_invoice_receipt` + `POST /invoices/{id}/email-receipt`
    - New service wrapping `_send_receipt_email` for `payment_received`; same override set/behaviour as 8.1; does NOT replace the Stripe-webhook auto-receipt
    - _Requirements: 2.3, 7.6, 8.1, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 11.2, 11.3, 11.5, 16.3_

  - [x] 8.4 Quote send override — `quotes.service.send_quote` + `POST /quotes/{id}/send`
    - Same override set/behaviour as 8.1
    - _Requirements: 2.4, 7.6, 8.1, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 9.3, 11.2, 11.3, 11.5_

  - [x] 8.5 Customer statement override (new endpoint) — `reports.service.email_customer_statement` + `POST /api/v2/reports/customer-statement/{id}/email`
    - New service building statement defaults via `get_customer_statement`; same override set/behaviour as 8.1
    - _Requirements: 2.5, 7.6, 8.1, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 11.2, 11.3, 11.5_

  - [x] 8.6 Portal link override (switch to direct send) — `customers.service.send_portal_link` + `POST /api/v2/customers/{id}/send-portal-link`
    - Override path switches from queued `send_email_task` to a direct synchronous `send_email(db, EmailMessage(...))` so the endpoint can map `FailureKind`; leave the non-modal auto-send (enable_portal transition) path unchanged
    - _Requirements: 2.6, 7.6, 8.1, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 11.2, 11.3, 11.5, 16.2_

  - [x] 8.7 Reminder resend (new endpoint + vehicles module check) — `notifications.service.resend_notification_log_entry` + `POST /api/v2/notifications/log/{log_id}/resend`
    - Same override set/behaviour as 8.1 for `wof_expiry_reminder`/`cof_expiry_reminder`/`registration_expiry_reminder`/`service_due_reminder`
    - Call `ModuleService.is_enabled(org_id, 'vehicles')` and return 403 "Vehicles module is not enabled for this organisation" when disabled
    - _Requirements: 2.7, 7.6, 8.1, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 11.2, 11.3, 11.5, 22.2, 25.6_

- [x] 9. Checkpoint — backend
  - Ensure all new backend tests pass (tasks 1.2, 1.3, 2.2, 5.2, 7.1, 7.2, 7.3) and the migration is applied; ask the user if questions arise.

- [x] 10. Shared web contract — types and surface registry
  - [x] 10.1 Create `frontend-v2/src/components/email/types.ts` and `surfaceRegistry.ts`
    - `types.ts`: `SenderPreview`, `AttachmentSpec`, `BlocklistEntry`, `EmailPreviewResponse`, `OverrideSendPayload`, `SurfaceConfig`, `EntityType`, `SendEmailModalProps` — field names matching the Pydantic schemas exactly (single source of truth, re-used by mobile)
    - `surfaceRegistry.ts`: frozen record keyed by `template_type` mapping each surface to `buildSendUrl`, `method`, `apiV2`, and `surfaceLabel` for all seven surfaces (10 template types)
    - This is purely additive; no SMS support; the archived `frontend/` is not touched
    - _Requirements: 1.1, 1.5, 1.9, 1.10, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 16.4, 16.6, 18.1_

- [x] 11. Web modal components (frontend-v2) + TipTap dependency
  - [x] 11.1 Add TipTap dependencies to `frontend-v2/package.json`
    - `@tiptap/react`, `@tiptap/starter-kit`, `@tiptap/extension-link`, `@tiptap/extension-underline` (React 19-compatible); no collaboration/yjs; editor module lazy-loaded; bundle ≤ 80 KB gzipped
    - _Requirements: 6.1, 28.4_

  - [x] 11.2 `RecipientChips.tsx` — To/Cc/Bcc chip inputs
    - Validate each entry against `/^[^\s@]+@[^\s@]+\.[^\s@]+$/` on Enter/comma/semicolon/Tab; inline "Invalid email address" on failure; >50 combined recipients warning
    - Soft-bounce chips amber border + warning-triangle icon; hard-bounce red border + error-octagon icon (icon always accompanies colour); hard-bounce disables Send unless `canOverrideHard` (org_admin) + "Override once"; linked `<label htmlFor>`; 40–44px touch targets
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 13.2, 13.3, 13.4, 13.5, 13.6, 15.4, 27.4, 27.5_

  - [x] 11.3 `SubjectInput.tsx`
    - Wrap the `Input` primitive; max 255 chars; character count when > 200; inline "Subject is required." when empty; diff against default to drive `subject_was_edited`
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 11.4 `BodyEditor.tsx` (TipTap wrapper)
    - StarterKit + link + underline only; toolbar bold/italic/underline/bullet list/ordered list/link/Reset to default; Ctrl/Cmd+B/I/U; Tab-reachable buttons; paste handler strips styles/scripts/iframes/event-handlers; emits HTML (not Markdown); read-only "Sender: {from_name} <{from_email}>" footer + "Default content rendered in {locale}" line; `font-mono` tnum for locale/id text
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 9.1, 9.2, 3.10, 27.2_

  - [x] 11.5 `AttachmentList.tsx`
    - One row per attachment: checkbox (default from `default_attached`), label, human-readable size (`{kb} KB` < 1 MB else `{mb} MB`, font-mono tnum), disabled locked checkbox + "Required" tooltip when required; compute selected total + 10 KB body estimate; signal parent to disable Send + show over-size banner when total exceeds `email_size_limit_bytes`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 11.6 `StatusBanner.tsx`
    - `role="alert"`; red/amber tones; Dismiss (×) hides without closing; never auto-dismisses; Retry only for SOFT_PROVIDER/BUDGET_EXCEEDED; Copy details (provider_key, attempt count, timestamp) for SOFT_AUTH; reused for preview load-error + over-size banners
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 14.8, 27.3_

  - [x] 11.7 `SendEmailModal.tsx` — compose the components and wire send
    - Accept exactly `{ open, onClose, templateType, entityType, entityId, onSent, surfaceLabel, logId? }`; no per-surface branching (read `SURFACE_REGISTRY[templateType]`)
    - Fetch preview in a `useEffect` with `AbortController` aborted on unmount and on close; typed generics, no `as any`; every response read uses `?.`/`?? []`/`?? 0`; show skeleton only after 300 ms
    - Track `subjectWasEdited`/`bodyWasEdited`; build `OverrideSendPayload` omitting unchanged fields (omit `body_html` when not edited → byte-equivalent default); session-scoped per-entity draft preservation keyed by `${entityType}:${entityId}`, reset on different entity
    - Use the existing `Modal` primitive (focus trap, Escape, focus restore); 403/404 → red banner + Send disabled; 5xx/network → "Could not load defaults" + Retry; Send shows spinner + `aria-busy`, Cancel disabled in flight; on success close + green toast "Email sent to {primary_recipient}" + `onSent()`; bound to `total_budget_seconds`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 1.7, 1.8, 3.1, 3.7, 3.8, 4.8, 8.1, 8.2, 8.9, 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 24.1, 24.2, 24.3, 24.4, 27.1, 27.6, 28.2, 28.3_

- [x] 12. Per-component Vitest unit tests (frontend-v2)
  - [x] 12.1 `SendEmailModal` test — loading-state, default-render, edited-render, send-success, send-failure paths
    - _Requirements: 21.4_
  - [x] 12.2 `RecipientChips` test — validation, soft/hard blocklist styling, override-once gating
    - _Requirements: 21.4_
  - [x] 12.3 `SubjectInput` test — required/empty + char-count + edited flag
    - _Requirements: 21.4_
  - [x] 12.4 `BodyEditor` test — default render, reset-to-default, paste sanitisation, sender footer
    - _Requirements: 21.4_
  - [x] 12.5 `AttachmentList` test — size formatting, required lock, over-size disable boundary
    - _Requirements: 21.4_
  - [x] 12.6 `StatusBanner` test — FailureKind→tone/message mapping, retry visibility, copy details
    - _Requirements: 21.4_
  - [x] 12.7 `surfaceRegistry`/`types` test — every template_type resolves to the correct URL/method
    - _Requirements: 21.4_
  - [x] 12.8 fast-check property fuzz of the recipient-email regex in `RecipientChips`
    - Optional hardening beyond the required four backend properties
    - _Requirements: 4.3_

- [x] 13. Per-surface web triggers (frontend-v2)
  - [x] 13.1 `InvoiceList.tsx` — open the modal for Send Invoice, Send Payment Link, and Send Receipt
    - Replace direct `handleSendInvoice`/`handleSendPaymentLink` calls with opening `SendEmailModal`; add Send Receipt in the More menu for paid/partially-paid invoices; pass the `(template_type, entity_type, entity_id)` triple; `onSent` re-fetches the invoice; do NOT replace `IssueInvoiceModal`; button labels/positions unchanged
    - _Requirements: 2.1, 2.2, 2.3, 16.1, 17.1, 17.2, 17.7, 18.4_

  - [x] 13.2 `QuoteDetail.tsx` — open the modal for the Email action
    - Replace direct `handleSend`; `onSent` re-fetches the quote
    - _Requirements: 2.4, 17.3, 17.7, 18.4_

  - [x] 13.3 `CustomerProfile.tsx` — add Send Statement button + wire Send Portal Link
    - New **Send Statement** action in the profile actions row, gated to `org_admin`/`salesperson` and visible only when the customer has ≥1 open invoice; re-point the portal-card **Send portal link** button to the modal; `onSent` re-fetches the profile
    - _Requirements: 2.5, 2.6, 17.4, 17.5, 17.7, 18.4_

  - [x] 13.4 Notification-log **Resend** trigger
    - Open the modal in place of any direct re-enqueue; visible only when `useModuleEnabled('vehicles')` AND `(tradeFamily ?? 'automotive-transport') === 'automotive-transport'`; pass `logId` + `(customer_id, global_vehicle_id)`; `onSent` re-fetches the log
    - _Requirements: 2.7, 17.6, 17.7, 18.4, 22.1, 22.2, 22.3_

- [x] 14. Settings template editor — render the three new template types
  - [x] 14.1 Render `invoice_payment_link`, `customer_statement`, `portal_link` in `frontend-v2/src/pages/settings/Notifications*.tsx`
    - Data-driven from the template-type list so each new type gets an editable, enable-able row like existing types
    - _Requirements: 20.3_

- [x] 15. Mobile sheet (mobile companion app)
  - [x] 15.1 Add TipTap dependencies to `mobile/package.json`
    - Same four packages as web (`@tiptap/react`, `@tiptap/starter-kit`, `@tiptap/extension-link`, `@tiptap/extension-underline`); no collaboration/yjs
    - _Requirements: 6.1, 12.1, 28.4_

  - [x] 15.2 `mobile/src/components/email/SendEmailSheet.tsx` against the shared contract
    - Import `types.ts`/`surfaceRegistry.ts` from the web module (no parallel definitions); full-screen sheet on ≤640px with body editor ≥50% viewport height; top app-bar Cancel (left) / Send (right); ≥44×44px touch targets; `pb-safe`/`env(safe-area-inset-*)`; AbortController on every API call aborted on unmount; v2 endpoints + `offset`/`limit`; hidden from `global_admin`; surfaces fail closed when module disabled
    - _Requirements: 1.10, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 15.3, 18.2, 22.4, 24.2_

  - [x] 15.3 Register the mobile trigger(s)
    - Wire the in-scope mobile surface(s) to open `SendEmailSheet`; evaluate availability via module-AND-trade-family composition
    - _Requirements: 12.1, 17.7, 22.4_

  - [x] 15.4 Mobile unit test for `SendEmailSheet.tsx`
    - Loading-state, default-render, edited-render, send-success, send-failure, plus safe-area-inset render
    - _Requirements: 21.5_

- [x] 16. End-to-end test script
  - [x] 16.1 `scripts/test_send_email_modal_e2e.py`
    - Run via `docker compose exec app python scripts/test_send_email_modal_e2e.py` using `httpx.AsyncClient(base_url="http://localhost:8000")`; log in as `demo@orainvoice.com`/`demo123` (org_admin) plus a `salesperson` and a `global_admin` where role-gating is checked
    - Exercise every in-scope web surface (preview + override-send) and assert: (a) default-send, (b) edited send (subject+body+cc), (c) attachment toggle, (d) hard-bounce block, (e) soft-bounce warning, (f) HARD_PAYLOAD via forced over-size attachments → 413, (g) notification_log audit columns populated
    - **OWASP A1**: as org A, `GET /api/v2/email-preview` for org B's invoice → assert 403/404 (never 200)
    - **OWASP A3**: POST `body_html` with `<script>alert(1)</script>` and `<a href="javascript:alert(1)">` → assert tokens stripped AND `edited_body_hash` computed over the post-sanitisation string
    - Track all created rows in a `created_ids` dict prefixed `TEST_E2E_send_email_modal_`; clean up in `try/finally`; re-query and assert zero remaining test rows, exit non-zero if cleanup incomplete; record and print the preview p95 latency
    - _Requirements: 21.1, 21.2, 21.3, 25.5, 25.6, 28.1_

- [x] 17. Versioning and changelog
  - [x] 17.1 Bump MINOR version 1.19.0 → 1.20.0 and add the changelog entry
    - Update `version` in `pyproject.toml`, `frontend-v2/package.json`, and `mobile/package.json` (kept in sync)
    - Add to `CHANGELOG.md` under the new version's **Added** section: "Send Email composer modal (web + mobile) — review and edit subject, body, recipients, and attachments before sending invoices, quotes, statements, and reminders."
    - No git tag and no production deploy (out of scope)
    - _Requirements: 26.1, 26.2, 26.3, 26.4, 29.1, 29.2, 29.3_

- [x] 18. Final verification (local dev only)
  - [x] 18.1 Run new/relevant tests, run the e2e script, and browser-verify the invoice and quote surfaces
    - Run the new pytest tests in the container: `tests/test_html_sanitise.py`, `tests/test_email_compose_preview.py`, `tests/test_email_compose_default_equivalence.py`, `tests/test_email_compose_attachment_token.py`, `tests/test_email_compose_audit_hash.py`
    - Run the new Vitest tests (frontend-v2 components + mobile sheet)
    - Run `docker compose exec app python scripts/test_send_email_modal_e2e.py` and confirm it passes with clean cleanup and a reported p95
    - Browser-verify at least the invoice-send and quote-send surfaces end-to-end (open modal → preview loads → edit → Send → toast → surface refreshes; check the Network tab and console)
    - Scope: only NEW and directly-relevant tests must pass (R21.8) — do NOT run or require the full project test suite; log any bugs found in `docs/ISSUE_TRACKER.md`
    - _Requirements: 21.1, 21.4, 21.5, 21.6, 21.7, 21.8, 23.1, 23.2_

## Notes

- Tasks marked `*` are optional polish (only 12.8, the fast-check recipient-regex fuzz). The four required property tests (1.3 / P2, 5.2 / P3, 7.2 / P1, 7.3 / P4), the e2e script, the per-component unit tests, and the example backend tests are required by R21 and are NOT optional.
- Each property test is its own sub-task, annotated with its property number and the requirement clauses it validates, and placed close to the implementation it guards.
- The migration (3.2) must be applied inside the dev container (`docker compose exec app alembic upgrade head`) and verified, per the database-migration-checklist.
- Every send still flows through `email_sender.send_email` — no new send path is introduced (R16.5).

## Requirements Coverage Map

Every requirement (1–29) is covered by at least one task:

- R1 → 10.1, 11.7
- R2 → 8.1–8.7, 10.1, 13.1–13.4
- R3 → 6.2, 6.3, 7.2, 11.4, 11.7
- R4 → 2.1, 11.2, 11.7
- R5 → 11.3
- R6 → 11.1, 11.4
- R7 → 5.1, 6.2, 8.1–8.7, 11.5
- R8 → 6.3, 8.1–8.7, 11.7
- R9 → 6.2, 8.1/8.4, 11.4
- R10 → 1.1, 8.1
- R11 → 3.1, 3.2, 4.1, 4.2, 6.1, 7.3, 8.1
- R12 → 15.1, 15.2, 15.3
- R13 → 6.2, 8.1, 11.2
- R14 → 8.1, 11.6
- R15 → 8.1, 11.2, 15.2
- R16 → 2.1, 6.2, 8.3, 8.6, 10.1, 13.1
- R17 → 13.1–13.4, 15.3
- R18 → 6.3, 10.1, 13.x, 15.2
- R19 → 11.7
- R20 → 3.3, 6.2, 7.1, 7.2, 14.1
- R21 → 1.2, 1.3, 2.2, 5.2, 7.1–7.3, 12.x, 15.4, 16.1, 18.1
- R22 → 8.7, 13.4, 15.2/15.3
- R23 → 18.1
- R24 → 10.1, 11.4, 11.7
- R25 → 6.3, 8.7, 16.1
- R26 → 17.1
- R27 → 11.2, 11.4, 11.6, 11.7
- R28 → 6.2, 11.1, 11.7, 16.1
- R29 → 17.1, plus the local-dev-only scope stated in the Overview
