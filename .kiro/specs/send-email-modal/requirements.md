# Requirements Document — Send Email Modal

## Introduction

OraInvoice currently emails customers from many surfaces (invoice send, invoice
payment-link send, quote send, customer statement, portal invite, payment
receipt, vehicle reminder resend). Today every surface ships its message
straight from server-side defaults — the user has no opportunity to review the
recipient list, edit the subject, or adjust the body before the email leaves.

This feature introduces a **single shared "Send Email" composer modal**,
modelled after Zoho Invoice's Send Email dialog, that opens whenever a user
triggers any of those surfaces. The modal pre-loads the rendered default
content (subject + sanitised HTML body + recipient + cc/bcc + attachment list)
from the existing notification-template system, lets the user edit it in place,
then dispatches via the existing unified email sender
(`app/integrations/email_sender.py`). The sender identity (from-address,
from-name, reply-to) remains system-controlled and is **never editable by the
user**.

The modal is built once as a contract-driven, surface-agnostic component and
reused across every send-email surface in `frontend-v2/` (active web app) and
the mobile companion app. It does not replace the `invoice-issue-modal`
(which handles "issue + maybe email" at create time); it is the email composer
that opens **after** issue, or any time a user re-sends an existing artefact.

This spec covers the full feature surface: the shared modal contract,
seven send surfaces, default-content loading with locale resolution,
recipient/subject/body/attachment editing, server-side HTML
sanitisation, attachment-key IDOR protection, audit columns on
`notification_log`, mobile parity, design-system compliance with
frontend-v2 tokens and primitives, accessibility (focus trap, keyboard,
screen-reader announcements), backend middleware posture, performance
budgets, and the test scope (only new and directly-relevant tests
required to pass before merge). Deployment is to the local dev
environment only; Pi-prod deployment is out of scope.

## Glossary

- **Send_Email_Modal** — The shared frontend component (one in `frontend-v2/`,
  one mobile-optimised variant in `mobile/`) that composes the email and
  triggers the send. Both share the same contract.
- **Surface** — A specific user-facing action that opens the
  Send_Email_Modal. The seven surfaces in scope are listed in the inventory in
  Requirement 2 (invoice send, invoice payment-link send, payment receipt
  resend, quote send, customer statement send, portal invite, ad-hoc reminder
  resend).
- **Email_Preview_Endpoint** — The new backend endpoint
  `GET /api/v2/email-preview` that returns the rendered default subject, body
  HTML, recipient(s), cc/bcc defaults, attachment list, and variable context
  for a given (template_type, entity_type, entity_id) combination.
- **Override_Send_Endpoint** — The existing per-surface POST endpoint that
  performs the actual send (e.g. `POST /invoices/{id}/email`,
  `PUT /quotes/{id}/send`, `POST /payments/invoice/{id}/send-payment-link`),
  extended in this spec with optional override fields: `subject`, `body_html`,
  `recipients`, `cc`, `bcc`, `attachments`.
- **Sender_Identity** — The triplet `(from_email, from_name, reply_to)`
  resolved server-side from `email_providers.config` and the org's
  `email_sender_name` / `email_reply_to` overrides. Never editable in the
  Send_Email_Modal.
- **Default_Content** — The rendered subject and sanitised HTML body produced
  by `resolve_template()` for the relevant `template_type`, with the
  surface-appropriate variable context applied. When no enabled template
  exists, the surface's existing hardcoded fallback content is used and
  marked as default.
- **User_Edited_Content** — Any subject, body, recipient, cc, or bcc value
  the user changed in the modal between the moment Default_Content was
  loaded and the moment they clicked Send.
- **Body_Sanitiser** — The server-side allowlist-based HTML sanitiser
  (bleach-derived) that processes the `body_html` override before it reaches
  `email_sender.send_email`.
- **Bounce_Blocklist** — The existing `bounced_addresses` table, queried
  per-org. Per `email_provider_unification`, addresses on this list are
  pre-checked before any provider attempt.
- **Soft_Bounced** — A recipient with a `bounced_at` event of class `soft`
  (mailbox full, transient delivery failure). Surface-able as a warning.
- **Hard_Bounced** — A recipient with a `bounced_at` event of class `hard`
  (mailbox does not exist, address rejected). Surface-able as a block with
  override.
- **Attachment_Spec** — A descriptor returned by Email_Preview_Endpoint per
  available artefact: `{ key, label, size_bytes, default_attached: bool,
  required: bool }`. The user toggles `default_attached` per attachment.
- **Send_Result** — The aggregate result returned by
  `email_sender.send_email`, exposing `success`, `provider_key`, `attempts`,
  and a final `failure_kind` from `FailureKind` (HARD_RECIPIENT,
  HARD_PAYLOAD, SOFT_AUTH, SOFT_PROVIDER, BUDGET_EXCEEDED).
- **Audit_Override_Flag** — Two booleans plus content hashes stored on
  `notification_log` per send: `subject_was_edited`, `body_was_edited`,
  `edited_subject_hash`, `edited_body_hash` (SHA-256 of the rendered final
  string, never the raw body), plus a JSONB column listing the edited
  recipient/cc/bcc lists when those differ from defaults.
- **Trade_Family_Surface** — A surface that only exists in some trade
  families (e.g. WOF reminder is automotive-only). The Send_Email_Modal
  itself is universal; surfaces that don't apply to the org's trade family
  simply don't expose the trigger.
- **Attachment_Token** — Either (a) a stable per-surface identifier scoped
  to the request entity (e.g. `invoice_pdf`, `customer_statement_pdf`) or
  (b) an HMAC-signed token encoding `(org_id, entity_id, attachment_kind,
  expires_at)`. The Override_Send_Endpoint validates Attachment_Token
  values against the preview-time set for the same
  `(entity_type, entity_id, org_id)` and refuses any unknown value.
- **Locale_Resolution_Chain** — The precedence used by
  Email_Preview_Endpoint to determine which locale to render the
  default content in: customer's `language` field if set, otherwise the
  org's `default_locale`, otherwise `en`. The resolved locale is passed
  to `get_template_for_locale()` and returned in the preview response so
  the modal can label it for the user.
- **Design_Tokens** — The frontend-v2 design system constants documented
  in `OraInvoice_Handoff/app/ds.css` (`--accent`, `--ink`, `--canvas`,
  `--card`, `--border`, `--r-card`, `--r-ctl`, etc.) and the typography
  pair (IBM Plex Sans for body, IBM Plex Mono with `tnum 1` for numbers,
  ids, hashes, and timestamps). These are the only visual primitives this
  spec is allowed to introduce; no new tokens are defined here.

## Requirements

### Requirement 1: Shared Modal Component (Contract-Driven)

**User Story:** As a developer, I want one Send_Email_Modal component
implemented against a surface-agnostic contract, so that adding a new
send-email surface in the future requires only registering it in the surface
registry — not writing a new modal.

#### Acceptance Criteria

1. THE Send_Email_Modal SHALL accept the following props:
   `{ open, onClose, templateType, entityType, entityId, onSent, surfaceLabel }`
   and SHALL NOT accept any surface-specific props beyond these.
2. WHEN Send_Email_Modal opens, THE component SHALL call
   Email_Preview_Endpoint with the four identifying values
   `(template_type, entity_type, entity_id, org_id)` and SHALL render the
   returned Default_Content into the recipient, subject, body, cc, bcc, and
   attachment fields.
3. THE Send_Email_Modal SHALL be located at
   `frontend-v2/src/components/email/SendEmailModal.tsx` for the web app and
   at `mobile/src/components/email/SendEmailSheet.tsx` for the mobile
   companion app, and BOTH SHALL implement the same contract from
   `frontend-v2/src/components/email/types.ts` (a shared type module
   re-exported by mobile).
4. THE Send_Email_Modal SHALL NOT contain any per-surface conditional
   branching in its render or send logic; surface-specific behaviour SHALL
   be expressed through the contract values returned by
   Email_Preview_Endpoint and the URL of the surface's
   Override_Send_Endpoint.
5. WHEN a new surface is added in the future, THE work required SHALL be
   limited to adding a row to the surface registry
   (`frontend-v2/src/components/email/surfaceRegistry.ts`), backend support
   for the `template_type` in Email_Preview_Endpoint, and override-field
   acceptance on the Override_Send_Endpoint — no changes to
   Send_Email_Modal itself.
6. THE web Send_Email_Modal SHALL wrap every preview-fetch and
   override-send call in a `useEffect` with an `AbortController`, AND
   SHALL abort the controller on component unmount AND on modal close,
   matching the pattern enforced by
   `.kiro/steering/safe-api-consumption.md` (Pattern 7) for the rest of
   `frontend-v2/`.
7. EVERY response field access in the web modal SHALL use optional
   chaining (`?.`) and `?? []` / `?? 0` defaults, per
   `safe-api-consumption.md` Patterns 1–4. THE modal SHALL NOT crash on a
   malformed or partial preview response.
8. EVERY API call SHALL use a typed generic
   (`apiClient.get<EmailPreviewResponse>(...)`,
   `apiClient.post<SendInvoiceResponse>(...)`); THE modal SHALL NOT use
   `as any` against any API response, per `safe-api-consumption.md`
   Pattern 5.
9. THE TypeScript types in
   `frontend-v2/src/components/email/types.ts` SHALL match the Pydantic
   response field names declared in
   `app/modules/email_compose/schemas.py` exactly, per
   `frontend-backend-contract-alignment.md` Rule 1; field renames or
   additions SHALL be made on both sides in the same change.
10. `frontend-v2/src/components/email/types.ts` SHALL be the single
    source of truth for the contract. THE mobile sheet
    (`mobile/src/components/email/SendEmailSheet.tsx`) SHALL import
    these types from the web app's email module (relative path or
    workspace alias) and SHALL NOT maintain a parallel type
    definition.

### Requirement 2: Surface Inventory

**User Story:** As a user, I want a consistent compose-then-send experience
across every existing email surface in the app, so that I can review or edit
any outbound email regardless of where I clicked Send.

#### Acceptance Criteria

1. WHEN the user clicks **Send Invoice** on the invoice detail toolbar,
   THE Send_Email_Modal SHALL open with `template_type=invoice_issued`,
   `entity_type=invoice`, and the invoice id, AND on confirm SHALL call
   `POST /invoices/{id}/email` with the override payload.
2. WHEN the user clicks **Send Payment Link** on the invoice detail
   toolbar, THE Send_Email_Modal SHALL open with
   `template_type=invoice_payment_link`, `entity_type=invoice`, and the
   invoice id, AND on confirm SHALL call
   `POST /payments/invoice/{id}/send-payment-link` with the override
   payload.
3. WHEN the user clicks **Send Receipt** on a paid or partially-paid
   invoice, THE Send_Email_Modal SHALL open with
   `template_type=payment_received`, `entity_type=invoice`, and the
   invoice id, AND on confirm SHALL call
   `POST /invoices/{id}/email-receipt` with the override payload.
4. WHEN the user clicks **Email** on the quote detail toolbar, OR
   **Save and Email** on the quote create/edit page, THE
   Send_Email_Modal SHALL open with `template_type=quote_sent`,
   `entity_type=quote`, and the quote id, AND on confirm SHALL call
   `POST /quotes/{id}/send` with the override payload.
5. WHEN the user clicks **Send Statement** on a customer profile, THE
   Send_Email_Modal SHALL open with
   `template_type=customer_statement`, `entity_type=customer`, and the
   customer id, AND on confirm SHALL call
   `POST /api/v2/reports/customer-statement/{customer_id}/email` with the
   override payload.
6. WHEN the user clicks **Send Portal Link** on a customer profile,
   THE Send_Email_Modal SHALL open with `template_type=portal_link`,
   `entity_type=customer`, and the customer id, AND on confirm SHALL call
   `POST /api/v2/customers/{id}/send-portal-link` with the override
   payload.
7. WHEN the user clicks **Resend** on a notification-log row whose
   `template_type` is one of `wof_expiry_reminder`, `cof_expiry_reminder`,
   `registration_expiry_reminder`, or `service_due_reminder`, THE
   Send_Email_Modal SHALL open with that `template_type`,
   `entity_type=customer_vehicle`, and the
   `(customer_id, global_vehicle_id)` pair, AND on confirm SHALL call
   `POST /api/v2/notifications/log/{log_id}/resend` with the override
   payload.
8. THE Send_Email_Modal SHALL NOT replace the existing
   `IssueInvoiceModal`; the issue-invoice flow SHALL continue to issue
   first, and any post-issue email SHALL be triggered by surface (1) above
   from the invoice detail.
9. THE Send_Email_Modal SHALL NOT be exposed for any platform/security
   email (login alert, MFA OTP, password reset, invitation, subscription
   dunning, storage warning); those paths SHALL continue to send from
   server-side defaults with no user-facing override.

### Requirement 3: Default Content Loading

**User Story:** As a user, I want the modal to open with the same content the
auto-send would have produced, so that I can ship the default by clicking Send
once, and only edit what I want to change.

#### Acceptance Criteria

1. WHEN the Send_Email_Modal opens, THE component SHALL call
   `GET /api/v2/email-preview?template_type=...&entity_type=...&entity_id=...`
   and SHALL display a non-blocking loading skeleton in each editable region
   until the response arrives.
2. THE Email_Preview_Endpoint SHALL return a `200` response with the shape
   `{ subject: string, body_html: string, recipients: string[], cc: string[],
   bcc: string[], variable_context: Record<string, string>, attachments:
   AttachmentSpec[], default_was_template: boolean, sender_preview:
   { from_email, from_name, reply_to }, blocklisted: { email, kind, reason }[] }`.
3. WHEN the org has an enabled notification template for the given
   `template_type` and channel `email`, THE Email_Preview_Endpoint SHALL
   resolve it via the existing `resolve_template()` service with the
   surface-appropriate variable context, AND `default_was_template` SHALL be
   `true`.
4. WHEN the org has no enabled template for the given `template_type`,
   THE Email_Preview_Endpoint SHALL produce the same hardcoded fallback
   subject and body that the existing surface sending function uses today,
   AND `default_was_template` SHALL be `false`.
5. THE returned `body_html` SHALL be passed through Body_Sanitiser before
   leaving the backend, so that the modal never has to display raw,
   untrusted HTML.
6. WHEN the user has not edited the body and clicks Send, THE override
   `body_html` field SHALL be omitted from the request payload, AND the
   server SHALL fall back to its existing default-rendering path. (This
   guarantees that "send default" is byte-equivalent to the pre-modal
   auto-send path.)
7. IF Email_Preview_Endpoint returns a `404` (entity not found) or `403`
   (user lacks permission for the entity), THEN THE Send_Email_Modal SHALL
   display a red inline banner with the server-supplied detail, AND the
   Send button SHALL be disabled.
8. IF Email_Preview_Endpoint returns a `5xx` or the request fails with a
   network error, THEN THE Send_Email_Modal SHALL display a "Could not
   load defaults" banner with a Retry button, AND the Send button SHALL
   be disabled until the retry succeeds.
9. THE `EmailPreviewResponse` Pydantic schema in
   `app/modules/email_compose/schemas.py` SHALL declare every field
   listed in 3.2 explicitly: `subject`, `body_html`, `recipients`,
   `cc`, `bcc`, `variable_context`, `attachments`,
   `default_was_template`, `sender_preview`, `blocklisted`, plus
   `email_size_limit_bytes` (per Requirement 7.3) and `locale` (per
   Requirement 3.10). Per
   `frontend-backend-contract-alignment.md` Rule 8, fields not declared
   on this schema are silently dropped by Pydantic, so additions to
   the service-layer dict SHALL also be added to the schema in the
   same change.
10. THE Email_Preview_Endpoint SHALL determine the recipient's locale
    via Locale_Resolution_Chain (customer's `language` if set,
    otherwise org's `default_locale`, otherwise `en`) and SHALL pass
    that locale to `get_template_for_locale()` so the rendered
    default exactly matches what the auto-send path would produce.
    THE response SHALL include the resolved value as
    `locale: string` so the modal can show informational text
    (e.g. "Default content rendered in English") next to the body
    editor.

### Requirement 4: Recipient, CC, and BCC Editing

**User Story:** As a user, I want to add, remove, or change the recipient
addresses (including cc and bcc) before sending, so that I can route a copy to
my accountant or fix a customer email typo without touching the customer
record.

#### Acceptance Criteria

1. THE Send_Email_Modal SHALL render three chip-input fields labelled
   **To**, **Cc**, and **Bcc**, each pre-populated with the corresponding
   array from Email_Preview_Endpoint.
2. THE **To** field SHALL be required and SHALL NOT permit zero recipients;
   the Send button SHALL be disabled when `recipients.length === 0`.
3. WHEN the user types a string into any chip-input field and presses
   Enter, comma, semicolon, or Tab, THE component SHALL validate the
   string against RFC 5322 minimum format
   (`/^[^\s@]+@[^\s@]+\.[^\s@]+$/`), AND on success SHALL convert it to a
   chip; on failure SHALL keep the raw text and show an inline red error
   "Invalid email address" beneath the field.
4. THE Cc and Bcc fields SHALL each accept zero or more chips and SHALL
   NOT have a hard upper limit, but the modal SHALL surface a warning
   when the combined recipient count exceeds 50.
5. WHEN the user adds an address that appears in the org's
   Bounce_Blocklist with `kind=soft`, THE chip SHALL render with an
   amber warning border and a tooltip "Recently soft-bounced — may not
   deliver. Continue at your own discretion."
6. WHEN the user adds an address that appears in the org's
   Bounce_Blocklist with `kind=hard`, THE chip SHALL render with a red
   border, AND the Send button SHALL be disabled while any hard-bounced
   chip is present, UNLESS the user clicks the chip's "Override once"
   action AND the user's role is `org_admin` (the action SHALL be hidden
   for `salesperson`).
7. WHEN the user removes a chip, THE chip and its email SHALL not be
   sent in the override payload.
8. THE recipient, cc, and bcc fields SHALL each preserve user input
   across modal close-and-reopen on the same entity within the same
   browser session, so that an accidental close does not lose unsaved
   work; any switch to a different entity SHALL reset the fields to the
   freshly fetched defaults.
9. WHEN dispatching to the unified email sender, BCC recipients SHALL
   be passed as separate envelope-only RCPT TO addresses (or, for
   provider REST APIs, in the provider's BCC field). BCC addresses
   SHALL NEVER appear in the rendered email's `To:` or `Cc:` headers
   that other recipients can see. THE existing `email_sender.send_email`
   contract SHALL be the integration point.

### Requirement 5: Subject Editing

**User Story:** As a user, I want to edit the subject line of the email
before sending, so that I can add context like "REVISED" or a job number.

#### Acceptance Criteria

1. THE Send_Email_Modal SHALL render a single-line text input labelled
   **Subject**, pre-populated with the rendered default subject.
2. THE subject input SHALL accept up to 255 characters and SHALL show a
   character count when the value exceeds 200.
3. WHEN the subject is empty, THE Send button SHALL be disabled, AND the
   field SHALL show inline error "Subject is required."
4. WHEN the user changes the subject from the default, THE component
   SHALL set an internal `subject_was_edited` flag to `true`. This flag
   SHALL be sent on the override payload and persisted on
   `notification_log` (Requirement 11).

### Requirement 6: Body Editing (Rich Text)

**User Story:** As a user, I want to edit the email body with basic
formatting (bold, italic, lists, links), so that I can match the tone of my
business without dropping into raw HTML.

#### Acceptance Criteria

1. THE Send_Email_Modal SHALL render a rich-text editor based on TipTap
   (the only React 18/19-compatible option that produces sanitised HTML
   with a small bundle footprint), pre-populated with the rendered
   default `body_html`.
2. THE editor toolbar SHALL expose at minimum: bold, italic, underline,
   bullet list, ordered list, link (insert/edit/remove), and a "Reset to
   default" action.
3. WHEN the user clicks **Reset to default**, THE editor SHALL replace
   its contents with the default body, set `body_was_edited` to `false`,
   and clear any pending changes.
4. WHEN the user pastes content from another source, THE editor SHALL
   strip styles, scripts, iframes, and event-handler attributes
   client-side before rendering, AND the server SHALL re-apply
   Body_Sanitiser on receipt as defence in depth.
5. THE editor SHALL produce HTML output, NOT Markdown, AND the override
   `body_html` SHALL be that HTML.
6. WHEN the user changes the body from the default in any way, THE
   component SHALL set `body_was_edited` to `true`.
7. THE editor SHALL display a footer note: "Sender: {from_name}
   <{from_email}>" rendered from the `sender_preview` field of the
   preview response. The note SHALL be read-only and SHALL NOT be a
   form field.

### Requirement 7: Attachment Toggles

**User Story:** As a user, I want to choose which attachments to include
when sending, so that I can include or omit the invoice PDF, customer
statement, or other artefacts based on the situation.

#### Acceptance Criteria

1. THE Send_Email_Modal SHALL render a list section labelled
   **Attachments**, populated from the `attachments` array of
   Email_Preview_Endpoint.
2. EACH attachment row SHALL show: a checkbox (default state from
   `default_attached`), the `label`, a human-readable size
   (`{size_kb} KB` for sizes < 1 MB, `{size_mb} MB` otherwise), and
   (when `required=true`) a disabled-locked checkbox with a "Required"
   tooltip.
3. WHEN the sum of selected attachment sizes plus an estimated body
   size (10 KB) exceeds the server-side `EMAIL_SIZE_LIMIT` (currently
   25 MB, exposed via the preview response so the modal does not
   hardcode it), THE Send button SHALL be disabled, AND a red banner
   SHALL display "Total attachment size {size_mb} MB exceeds the
   {limit_mb} MB limit. Uncheck attachments to continue."
4. WHEN no attachments are selected for a surface that has no required
   attachments, THE Send button SHALL remain enabled (a body-only email
   is valid).
5. THE override payload SHALL include the attachment selection as
   `attachments: string[]` (the `key` of each checked attachment).
   THE server SHALL re-resolve the attachment files server-side from
   the keys; the modal SHALL NOT upload bytes.
6. EACH Attachment_Spec `key` returned by Email_Preview_Endpoint SHALL
   be either (a) a stable identifier scoped to the request entity
   (e.g. `invoice_pdf`, `customer_statement_pdf`), OR (b) an
   HMAC-signed token encoding `(org_id, entity_id, attachment_kind,
   expires_at)`. THE Override_Send_Endpoint SHALL reject any
   `attachments` value not present in the preview-time set for the
   same `(entity_type, entity_id, org_id)` with HTTP 400 and detail
   "Invalid attachment selection.". THE server SHALL NEVER load or
   attach a file based purely on a client-supplied path or id; the
   Attachment_Token validation SHALL be the only path to file
   resolution.
7. THE per-surface attachment list (and each attachment's `required`
   flag) SHALL be defined in
   `app/modules/email_compose/service.py::get_attachments_for_surface(template_type, entity_id, org_id)`.
   The documented surface defaults SHALL be:
   - `invoice_issued`: invoice PDF (required); customer-statement PDF
     (optional, only offered if the customer has multiple open
     invoices)
   - `invoice_payment_link`: invoice PDF (optional, default off)
   - `payment_received`: invoice PDF showing PAID status (required)
   - `quote_sent`: quote PDF (required)
   - `customer_statement`: customer statement PDF (required)
   - `portal_link`: no attachments
   - `wof_expiry_reminder`, `cof_expiry_reminder`,
     `registration_expiry_reminder`, `service_due_reminder`: no
     attachments

### Requirement 8: Send Action

**User Story:** As a user, I want clicking Send to dispatch the email
through the same delivery path the auto-send uses, so that I get the same
provider failover, bounce-blocklist enforcement, and time budgets that
already protect non-modal email paths.

#### Acceptance Criteria

1. WHEN the user clicks **Send**, THE Send_Email_Modal SHALL POST to the
   surface's Override_Send_Endpoint with payload
   `{ recipients, cc, bcc, subject, body_html, attachments,
   subject_was_edited, body_was_edited }`. Fields that are unchanged from
   the default MAY be omitted (Requirement 3.6).
2. WHILE the request is in flight, THE Send button SHALL show a spinner
   and SHALL be disabled, AND the Cancel button SHALL also be disabled.
3. EVERY Override_Send_Endpoint SHALL pass the override payload through
   the existing service-layer email function and ultimately to
   `email_sender.send_email()`. No new SMTP/REST path SHALL be
   introduced.
4. IF the override payload is well-formed and the send succeeds (Send_Result
   `success=true`), THEN THE Override_Send_Endpoint SHALL return `200` with
   the existing per-surface response shape, AND the modal SHALL close
   itself, surface a green toast "Email sent to {primary_recipient}", and
   call `onSent()`.
5. IF Send_Result indicates `success=false` with `failure_kind=HARD_RECIPIENT`,
   THEN THE Override_Send_Endpoint SHALL return `400` with detail
   "Recipient address rejected. Check the To list and try again.", AND the
   modal SHALL display the detail in a red inline banner without closing.
6. IF Send_Result indicates `success=false` with `failure_kind=HARD_PAYLOAD`,
   THEN THE Override_Send_Endpoint SHALL return `413` with detail
   "Email too large. Reduce attachments and try again.", AND the modal SHALL
   display the detail in a red inline banner without closing.
7. IF Send_Result indicates `success=false` with `failure_kind=SOFT_AUTH`,
   THEN THE Override_Send_Endpoint SHALL return `502` with detail
   "Email provider authentication failed. Contact your platform admin.",
   AND the modal SHALL display the detail in a red inline banner without
   closing.
8. IF Send_Result indicates `success=false` with `failure_kind=SOFT_PROVIDER`
   or `BUDGET_EXCEEDED`, THEN THE Override_Send_Endpoint SHALL return `503`
   with detail "Delivery temporarily failed across all providers. Please try
   again in a few minutes.", AND the modal SHALL display the detail in an
   amber banner without closing.
9. WHEN any 4xx/5xx response is received, THE Send_Email_Modal SHALL leave
   user-edited fields intact so the user can retry without re-typing.
10. EVERY Override_Send_Endpoint SHALL continue to honour the existing
    CSRF token requirement that frontend-v2 applies to mutation
    endpoints. THE new override fields SHALL NOT introduce a CSRF
    exemption. THE web modal SHALL include the active CSRF token on
    every POST/PUT to the Override_Send_Endpoint via the existing
    `apiClient` interceptor (no per-modal CSRF wiring).
11. THE `GET /api/v2/email-preview` endpoint, being a GET, SHALL NOT
    require a CSRF token; it SHALL still require a valid JWT (see
    Requirement 25 for full middleware posture).

### Requirement 9: Sender Identity is System-Default

**User Story:** As a platform operator, I want the from-address, from-name,
and reply-to fields to remain controlled by the platform's email-provider
configuration, so that customers cannot impersonate other senders or break
SPF/DKIM alignment from the modal.

#### Acceptance Criteria

1. THE Send_Email_Modal SHALL NOT render any input or editable control for
   `from_email`, `from_name`, or `reply_to`.
2. THE modal SHALL display the resolved sender identity as a read-only
   informational footer (Requirement 6.7), sourced from
   `sender_preview` in the preview response.
3. THE Override_Send_Endpoint SHALL ignore any client-supplied
   `from_email`, `from_name`, or `reply_to` fields if present in the
   payload, AND the server-side `EmailMessage` construction SHALL use the
   org's configured `email_sender_name` / `email_reply_to` settings and
   the active `email_providers.config.from_email`, exactly as today.

### Requirement 10: Server-Side HTML Sanitisation

**User Story:** As a security engineer, I want the server to strip any
unsafe HTML (scripts, event handlers, dangerous protocols) from the body
before it reaches the email provider, so that user-supplied content cannot
introduce XSS into rendered email previews or injection into provider APIs.

#### Acceptance Criteria

1. WHEN the Override_Send_Endpoint receives an override `body_html`,
   THE service layer SHALL pass it through Body_Sanitiser before
   calling `email_sender.send_email()`.
2. Body_Sanitiser SHALL allow only the following tags:
   `p, br, hr, strong, em, u, s, b, i, ul, ol, li, blockquote, pre, code,
   h1, h2, h3, h4, h5, h6, a, img, table, thead, tbody, tr, th, td, span,
   div`. All other tags SHALL be stripped (content preserved when sensible).
3. Body_Sanitiser SHALL allow only the following attributes:
   - on `a`: `href, title, target, rel`
   - on `img`: `src, alt, title, width, height, style` (style filtered)
   - on `td, th, table`: `colspan, rowspan, width, align, style` (style filtered)
   - on any element: `style, class` (style filtered to a safe property
     allowlist of `color, background-color, font-weight, font-style,
     text-decoration, text-align, padding, margin, border, font-size`)
4. Body_Sanitiser SHALL allow only `http`, `https`, and `mailto` protocols
   in `href` and `src` attributes; `javascript:`, `data:`, and `file:` URLs
   SHALL be stripped.
5. Body_Sanitiser SHALL strip every event-handler attribute
   (`on*` patterns) regardless of element.
6. THE rendered default `body_html` returned by Email_Preview_Endpoint
   SHALL also be passed through Body_Sanitiser before being returned to
   the modal, so that any template-stored markup is consistent with what
   the user can edit.
7. Body_Sanitiser SHALL be implemented in `app/integrations/html_sanitise.py`
   using `bleach` (or equivalent), with the allowlist defined as module-level
   constants and unit-tested against known XSS payloads.

### Requirement 11: Notification Log Audit

**User Story:** As a support engineer investigating a delivery, I want the
notification_log row to show whether the user sent the default content or
edited it, and to record an integrity hash of any edits, so that I can
distinguish "template was wrong" from "user changed it" without storing the
raw body content.

#### Acceptance Criteria

1. THE `notification_log` table SHALL gain four new columns via Alembic
   migration: `subject_was_edited BOOLEAN NOT NULL DEFAULT false`,
   `body_was_edited BOOLEAN NOT NULL DEFAULT false`,
   `edited_subject_hash CHAR(64) NULL`, `edited_body_hash CHAR(64) NULL`,
   AND one new column `cc_recipients JSONB NOT NULL DEFAULT '[]'::jsonb`,
   AND one new column `bcc_recipients JSONB NOT NULL DEFAULT '[]'::jsonb`.
   THE migration SHALL be the next sequential revision after `0194`
   (current head as of this spec — the design phase SHALL pin the actual
   next number) AND SHALL be runnable via
   `docker compose exec app alembic upgrade head` in the local dev
   container per `.kiro/steering/database-migration-checklist.md`.
2. WHEN a send is logged via the modal AND `subject_was_edited` is `true`,
   THE log row SHALL set `subject_was_edited=true` AND
   `edited_subject_hash` to the SHA-256 hex digest of the final rendered
   subject string.
3. WHEN a send is logged via the modal AND `body_was_edited` is `true`,
   THE log row SHALL set `body_was_edited=true` AND `edited_body_hash` to
   the SHA-256 hex digest of the post-sanitisation final body string.
4. THE `notification_log` row SHALL never store the raw subject or body
   content of an edited send. Only the hashes SHALL be stored. The
   default-content path (where the user sent without editing) MAY continue
   to store the rendered subject in the existing `subject` column as
   today.
5. WHEN the modal sends with non-empty cc or bcc lists, THE log row's
   `cc_recipients` and `bcc_recipients` columns SHALL be populated with
   those lists; an empty list SHALL be persisted as the JSONB array
   `[]`, never as `null`.
6. THE log entry SHALL preserve the existing `provider_key`,
   `provider_message_id`, `status`, and `sent_at` fields exactly as the
   pre-modal send paths populate them today.
7. THE four new columns SHALL be added to any internal `_log_to_dict` /
   schema serialiser already in use in `app/modules/notifications/`, AND
   the corresponding Pydantic response schema SHALL list them explicitly
   (per the project rule on Pydantic-silently-drops-fields).
8. THE `NotificationLogResponse` schema in
   `app/modules/notifications/schemas.py` SHALL be updated to include
   the six new audit columns (`subject_was_edited`, `body_was_edited`,
   `edited_subject_hash`, `edited_body_hash`, `cc_recipients`,
   `bcc_recipients`). THE existing `_log_to_dict` helper SHALL emit
   them on every row, AND fields SHALL be present in API responses (per
   `frontend-backend-contract-alignment.md` Rule 8).
9. WHERE the `notification_templates` table or its `template_type` column
   has a CHECK constraint or enum restricting allowed values, the same
   migration that adds the audit columns SHALL extend that constraint to
   include the three new types from Requirement 20.2
   (`invoice_payment_link`, `customer_statement`, `portal_link`). THE
   migration SHALL be runnable via
   `docker compose exec app alembic upgrade head` in the local dev
   container, SHALL be the next sequential revision after the current
   head (`0194` as of this spec — the design phase SHALL pin the
   actual next number), AND SHALL be idempotent where possible
   (use `IF NOT EXISTS` on column adds).
10. THE Override_Send request payload schemas attached to each
    Override_Send_Endpoint SHALL declare every override field
    explicitly: `recipients`, `cc`, `bcc`, `subject`, `body_html`,
    `attachments`, `subject_was_edited`, `body_was_edited`,
    `override_blocklist`. Pydantic config SHALL reject unknown fields
    with HTTP 422 (`extra="forbid"`) so that contract drift is caught
    at request time, not silently dropped.

### Requirement 12: Mobile Parity

**User Story:** As a mobile user, I want the same Send Email composer on my
phone as on the web app, with a layout sized for a small touchscreen, so
that I can review and edit emails from the field.

#### Acceptance Criteria

1. THE mobile companion app SHALL implement Send_Email_Sheet at
   `mobile/src/components/email/SendEmailSheet.tsx` AGAINST THE SAME
   contract as the web Send_Email_Modal (Requirement 1.3).
2. ON viewports ≤ 640 px wide, THE Send_Email_Sheet SHALL render as a
   full-screen sheet with the body editor occupying at least 50 % of
   the viewport height; a top app-bar SHALL contain the Cancel button
   on the left and the Send button on the right.
3. EVERY interactive element in the sheet (chips, toolbar buttons,
   attachment toggles, Send, Cancel) SHALL meet a minimum 44 × 44 CSS px
   touch target.
4. THE sheet SHALL use `pb-safe` and `env(safe-area-inset-*)` so that
   the Send button is never obscured by the home-indicator on
   notched devices.
5. EVERY API call in the sheet SHALL be wrapped in an
   `AbortController` and the controller SHALL be aborted on unmount
   (per the mobile-app steering rule).
6. THE mobile sheet SHALL use the v2 endpoints
   (`/api/v2/email-preview`, `POST /api/v2/...`) where available, and
   SHALL pass `offset`/`limit` (not `skip`) for any paginated list it
   may consume (e.g. attachments).
7. THE mobile sheet SHALL be hidden from `global_admin` even if the
   underlying surface is somehow exposed; mobile is org-user-only.

### Requirement 13: Bounce Blocklist UX

**User Story:** As a user, I want the modal to warn me before I send to an
address that recently bounced, so that I avoid wasting send budget and
making the org's domain reputation worse.

#### Acceptance Criteria

1. THE Email_Preview_Endpoint SHALL include a `blocklisted` array
   listing every preview recipient (To, cc, bcc default) that exists in
   `bounced_addresses` for the org, with `{ email, kind: 'soft'|'hard',
   reason, bounced_at }`.
2. WHEN any default recipient is in the blocklist with `kind=soft`,
   THE modal SHALL render an amber banner above the To field:
   "{email} recently soft-bounced. Delivery may fail. You can send
   anyway."
3. WHEN any default recipient is in the blocklist with `kind=hard`,
   THE modal SHALL render a red banner: "{email} hard-bounced and is
   blocked from delivery." AND the Send button SHALL be disabled while
   that recipient is present in any list.
4. THE user SHALL be able to remove a blocked recipient chip to re-enable
   Send. Removing the chip SHALL exclude that address from the override
   payload.
5. WHEN the user has role `org_admin`, an "Override once" action SHALL
   appear on a hard-bounced chip's tooltip. Clicking it SHALL clear the
   block locally for this single send AND SHALL set
   `override_blocklist=true` on the request payload. THE server SHALL
   honour `override_blocklist=true` only when the requesting user is
   `org_admin`; for any other role THE server SHALL refuse with `403`
   regardless of the flag value.
6. THE user-typed addresses (chips added after open) that match the
   blocklist SHALL receive the same visual treatment as default
   blocklist matches.

### Requirement 14: Failure Surfacing

**User Story:** As a user, I want the error messages I see in the modal to
match the underlying delivery failure type, so that I understand whether to
retry, fix the recipient, or contact my admin.

#### Acceptance Criteria

1. THE Send_Email_Modal SHALL render an inline status banner above the
   Send button. The banner SHALL be hidden when status is idle or
   in-flight, and visible when an error or warning is present.
2. WHEN the failure_kind is `HARD_RECIPIENT`, THE banner SHALL be red
   with text "Recipient address rejected. Fix the To list and try again."
3. WHEN the failure_kind is `HARD_PAYLOAD`, THE banner SHALL be red
   with text "Email too large. Uncheck some attachments and try again."
4. WHEN the failure_kind is `SOFT_AUTH`, THE banner SHALL be red with
   text "Email provider authentication failed. Contact your platform
   admin." AND SHALL include a small "Copy details" link that copies a
   sanitised one-line debug string (provider_key, attempt count,
   timestamp) to the clipboard for support tickets.
5. WHEN the failure_kind is `SOFT_PROVIDER` or `BUDGET_EXCEEDED`, THE
   banner SHALL be amber with text "Delivery temporarily failed across
   all providers. Please try again in a few minutes."
6. THE banner SHALL include a Dismiss (×) action that hides it without
   closing the modal.
7. THE banner SHALL NOT auto-dismiss; the user SHALL retain control.
8. WHEN `failure_kind` is `SOFT_PROVIDER` or `BUDGET_EXCEEDED`, THE
   banner SHALL include a **Retry** button that re-submits the same
   override payload (subject, body, recipients, cc, bcc, attachments,
   `subject_was_edited`, `body_was_edited`, `override_blocklist`)
   without requiring the user to re-type anything. THE Retry button
   SHALL be hidden for hard-failure kinds (`HARD_RECIPIENT`,
   `HARD_PAYLOAD`, `SOFT_AUTH`) where retry would not change the
   outcome.

### Requirement 15: Permissions

**User Story:** As an org admin, I want the modal to enforce the same role
gate as the underlying send endpoint, so that a salesperson cannot bypass
permission checks by opening the modal directly.

#### Acceptance Criteria

1. THE Send_Email_Modal SHALL be rendered only inside surfaces that
   already enforce the `org_admin` or `salesperson` role gate. The
   modal itself SHALL NOT carry a route or be reachable via URL.
2. EACH Override_Send_Endpoint SHALL retain its existing
   `require_role(...)` dependency unchanged, so the modal cannot
   escalate beyond what the surface already allowed.
3. THE Send_Email_Modal SHALL NOT be exposed to `global_admin` users in
   the mobile app at all; mobile is for org-level users (per
   `.kiro/steering/mobile-app.md`).
4. WHEN a `salesperson` user opens the modal, THE "Override once" action
   on hard-bounced chips (Requirement 13.5) SHALL NOT be rendered.
5. THE per-surface permission for the Send action SHALL match the
   permission already in place for the corresponding view action; if
   the user can see the entity, the user can email it (subject to
   role gate).

### Requirement 16: Reuse vs Duplicate (Explicit Non-Goals)

**User Story:** As a developer, I want the boundary between this modal and
adjacent flows clearly stated, so that I do not inadvertently replace
working features with the new modal.

#### Acceptance Criteria

1. THE Send_Email_Modal SHALL NOT replace `IssueInvoiceModal`. The
   issue-invoice flow SHALL continue to issue with or without auto-email
   based on its own checkbox, exactly as today. Editing of the issue-time
   email is OUT OF SCOPE for this spec.
2. THE Send_Email_Modal SHALL NOT replace any auto-send path triggered
   by background tasks (overdue reminder runner, scheduled customer
   statement runner if added later, recurring invoice runner). Those
   paths SHALL continue to send from server-side defaults without user
   override.
3. THE Send_Email_Modal SHALL NOT replace the Stripe webhook receipt
   email or any post-payment auto-receipt that fires from the payment
   webhook; only the explicit "Send Receipt" surface (Requirement 2.3)
   SHALL use the modal.
4. THE Send_Email_Modal SHALL NOT introduce SMS support. SMS templates
   exist in `notification_templates` but a separate "Send SMS" modal is
   out of scope here.
5. THE Send_Email_Modal SHALL NOT introduce its own email-sending code
   path. Every send SHALL flow through the existing service-layer
   functions, which already call `email_sender.send_email`.
6. THE legacy `frontend/` archived web app SHALL NOT receive the modal;
   only `frontend-v2/` and `mobile/` are in scope.

### Requirement 17: Integration with Existing UI

**User Story:** As a user, I want the new modal to slot into existing pages
without changing the layout, so that I do not have to relearn the toolbars I
already use.

#### Acceptance Criteria

1. THE invoice-detail right-panel toolbar in
   `frontend-v2/src/pages/invoices/InvoiceList.tsx` (and the mobile
   equivalent) SHALL replace the direct-call `handleSendInvoice` with a
   call that opens the Send_Email_Modal. The button label and position
   SHALL NOT change.
2. THE Send dropdown second item ("Send Payment Link") SHALL likewise
   open the modal in place of the direct-call
   `handleSendPaymentLink`.
3. THE quote-detail toolbar's **Email** button SHALL open the modal in
   place of the direct-call `handleSend`.
4. THE customer-profile **Send Statement** action SHALL be a NEW button
   added under the customer profile actions row, gated to roles
   `org_admin` and `salesperson`, only visible when the customer has at
   least one open invoice (matching today's statement-availability
   rule).
5. THE customer-profile portal-access card's **Send portal link** button
   SHALL open the modal in place of the direct-call `handleSendLink`.
6. THE notification-log row's **Resend** action (if present today, or
   newly added behind the same role gate) SHALL open the modal in place
   of any direct re-enqueue path.
7. EVERY trigger SHALL pass the surface-specific
   `(template_type, entity_type, entity_id)` triple to the modal, AND
   SHALL provide an `onSent` callback that refreshes the surface's
   data (invoice detail, quote detail, customer profile, notification
   log) so that the new sent-status is reflected without a manual
   reload.

### Requirement 18: Component Tree (Frontend Specification)

**User Story:** As a developer, I want the file layout for the modal and
its supporting components specified, so that the design phase is grounded
in concrete file paths.

#### Acceptance Criteria

1. THE following files SHALL be created in the web app:
   - `frontend-v2/src/components/email/SendEmailModal.tsx` — top-level modal
   - `frontend-v2/src/components/email/RecipientChips.tsx` — chip-input field
   - `frontend-v2/src/components/email/SubjectInput.tsx` — subject field
   - `frontend-v2/src/components/email/BodyEditor.tsx` — TipTap wrapper
   - `frontend-v2/src/components/email/AttachmentList.tsx` — attachment toggles
   - `frontend-v2/src/components/email/StatusBanner.tsx` — failure surfacing
   - `frontend-v2/src/components/email/types.ts` — shared contract types
   - `frontend-v2/src/components/email/surfaceRegistry.ts` — surface → endpoint map
2. THE following files SHALL be created in the mobile app:
   - `mobile/src/components/email/SendEmailSheet.tsx` — bottom-sheet variant
   - Re-export of `types.ts` and `surfaceRegistry.ts` from the web app's
     shared module.
3. THE following backend files SHALL be created or modified:
   - `app/modules/email_compose/router.py` — new module hosting
     `GET /api/v2/email-preview`
   - `app/modules/email_compose/service.py` — preview resolver +
     variable context builder per template_type +
     `get_attachments_for_surface()` (Requirement 7.7) +
     `attachment_token` HMAC builder/validator (Requirement 7.6) +
     `resolve_locale()` returning the Locale_Resolution_Chain
     (Requirement 3.10)
   - `app/modules/email_compose/schemas.py` — Pydantic schemas for the
     preview response (`EmailPreviewResponse`, including `locale` and
     `email_size_limit_bytes` per Requirement 3.9) and the override
     payloads (one per surface, all with `extra="forbid"` per
     Requirement 11.10)
   - `app/integrations/html_sanitise.py` — Body_Sanitiser implementation
   - `app/modules/notifications/models.py` — add four audit columns +
     two JSONB recipient list columns (Requirement 11.1)
   - `app/modules/notifications/schemas.py` — expose the six new audit
     columns on `NotificationLogResponse` (Requirement 11.8) and
     update the allowed-template-type list with the three new types
     (Requirement 20.2)
   - new Alembic migration adding the audit columns + extending the
     template-type CHECK constraint per Requirement 11.9
   - `app/modules/invoices/router.py`, `app/modules/quotes/router.py`,
     `app/modules/payments/router.py`,
     `app/modules/customers/router.py`,
     `app/modules/reports/router.py`,
     `app/modules/notifications/router.py` — extend or add the
     surface-specific Override_Send_Endpoint to accept the override
     payload and pass it through to the existing service function
4. THE existing surface trigger files SHALL be modified to open the
   modal instead of calling the send directly (as detailed in
   Requirement 17).

### Requirement 19: User Workflow Trace (Click-to-Result)

**User Story:** As a designer reviewing this spec, I want each user-visible
flow traced end-to-end, so that I can confirm no step is missing.

#### Acceptance Criteria

1. **Default send:** User clicks Send Invoice → modal opens with
   loading state → preview endpoint returns defaults →
   modal renders pre-filled fields → user clicks Send →
   request to `POST /invoices/{id}/email` with no override fields → server
   uses default rendering path → `email_sender.send_email` succeeds →
   response 200 → modal closes → toast "Email sent to {recipient}" → list
   refreshes.
2. **Edited send:** User opens modal → edits subject and adds a cc → clicks
   Send → request payload contains `subject`, `subject_was_edited=true`,
   `cc=[…]`, no `body_html` (body unchanged) → server passes subject and cc
   through to `email_sender.send_email` → notification_log row written with
   `subject_was_edited=true`, `edited_subject_hash` populated, `cc_recipients`
   populated.
3. **Hard-bounce block:** User opens modal → preview shows red banner for
   To recipient → user removes the chip and types a new address → chip
   accepted → Send enabled → send proceeds.
4. **Soft-bounce warning:** User opens modal → preview shows amber banner
   → user clicks Send anyway → send proceeds → if delivery fails, banner
   updates to amber failure banner.
5. **Provider failure:** User clicks Send → all providers fail with
   `SOFT_PROVIDER` → server returns 503 → modal shows amber banner with
   retry guidance, fields preserved.
6. **Cancel with edits:** User opens modal → makes edits → clicks Cancel
   or backdrop → modal closes; for the same entity within the session,
   reopening restores the edits (Requirement 4.8 applies to recipients;
   subject/body/attachment selections likewise SHALL be preserved across
   close-and-reopen on the same entity in the session, AND SHALL reset
   when the modal opens for a different entity).
7. **Mobile small-screen:** User taps Send Invoice on mobile → bottom sheet
   slides up full-screen → user composes → taps Send in the top app-bar →
   sheet dismisses → toast appears at the bottom above the safe-area inset.
8. **Concurrent send race:** When two users open the modal concurrently
   for the same entity and both click Send, BOTH sends SHALL be allowed
   to dispatch AND BOTH SHALL produce their own distinct
   `notification_log` rows. This spec accepts the resulting double-send
   as a valid outcome and does NOT introduce optimistic locking,
   advisory locks, or any other duplicate-send prevention. (If
   duplicate-send prevention is required in the future, that is a
   separate spec.)

### Requirement 20: Template Coverage and New Template Types

**User Story:** As an org admin, I want every surface that uses the modal to
also be customisable via the existing notification-template settings, so
that defaults stay consistent with auto-send.

#### Acceptance Criteria

1. THE following `template_type` values SHALL be supported by the modal,
   and each MUST resolve via `resolve_template()`:
   `invoice_issued`, `invoice_payment_link`, `payment_received`,
   `quote_sent`, `customer_statement`, `portal_link`,
   `wof_expiry_reminder`, `cof_expiry_reminder`,
   `registration_expiry_reminder`, `service_due_reminder`.
2. THE three template types not currently in
   `app/modules/notifications/schemas.py`'s allowed template-type list —
   `invoice_payment_link`, `customer_statement`, `portal_link` — SHALL be
   added to that list as part of this feature.
3. WHEN any of those new template types is added, the existing template
   editor UI in `frontend-v2/src/pages/settings/Notifications*.tsx` SHALL
   render an editable row for each, AND the org SHALL be able to enable
   and customise them in the same way as today's existing types.
4. THE variable-context map per template type SHALL be defined in
   `app/modules/email_compose/service.py::build_variable_context()` and
   SHALL match the existing
   `notification-template-integration::resolve_template()` variable map
   for the types that already exist there. The three new types SHALL
   each have a documented variable list (e.g. `customer_statement`:
   `customer_first_name, customer_last_name, statement_period_start,
   statement_period_end, total_outstanding, statement_link, org_name,
   org_email, org_phone`).
5. WHEN no enabled template exists for a given type, the hardcoded
   fallback used today by the corresponding sending function SHALL be
   used. The modal SHALL NOT show a different default than the
   pre-modal auto-send path (Requirement 3.6).

### Requirement 21: Testing Workflow Compliance

**User Story:** As a release engineer, I want every requirement above
mapped to a runnable end-to-end test, so that I can verify the feature
works against the live container before merge.

#### Acceptance Criteria

1. THE following Python end-to-end test SHALL be created and pass before
   the spec is considered done:
   `scripts/test_send_email_modal_e2e.py`. Per
   `.kiro/steering/feature-testing-workflow.md`, the script SHALL run
   inside the app container via
   `docker compose exec app python scripts/test_send_email_modal_e2e.py`,
   SHALL use `httpx.AsyncClient(base_url="http://localhost:8000")`,
   AND SHALL begin by logging in as the standard demo accounts
   (`demo@orainvoice.com` / `demo123` for `org_admin`, plus a
   `salesperson` and a `global_admin` where role-gating is checked).
   The script SHALL exercise every in-scope web surface by calling
   Email_Preview_Endpoint and the Override_Send_Endpoint, with real
   provider mocks where end-to-end provider delivery would otherwise be
   exercised.
2. THE script SHALL test (a) default-send (no overrides), (b) edited
   send (subject + body + cc), (c) attachment toggle, (d) hard-bounce
   block, (e) soft-bounce warning, (f) HARD_PAYLOAD response when
   over-size attachments are forced, (g) `notification_log` row contains
   the new audit columns populated correctly,
   (h) **OWASP A1 (cross-org IDOR):** while logged in as org A, the
   script SHALL `GET /api/v2/email-preview?entity_type=invoice&entity_id={other_org_invoice_id}`
   and SHALL assert the response is HTTP 403 or 404 — never 200,
   (i) **OWASP A3 (XSS injection):** the script SHALL POST a
   `body_html` containing `<script>alert(1)</script>` and
   `<a href="javascript:alert(1)">x</a>`, and SHALL assert that
   Body_Sanitiser strips the unsafe tokens AND that the resulting
   `edited_body_hash` is computed against the **post-sanitisation**
   string, not the raw input.
3. THE script SHALL track every entity it creates in a `created_ids`
   dict (orgs, customers, invoices, quotes, notification_log rows) AND
   SHALL run all cleanup in a `try/finally` block. After cleanup, the
   script SHALL re-query the database AND SHALL assert that no rows
   prefixed `TEST_E2E_send_email_modal_` remain. If cleanup is
   incomplete the script SHALL exit non-zero, per
   `.kiro/steering/feature-testing-workflow.md`.
4. THE web app SHALL include a Vitest unit test for each of the seven
   files listed in Requirement 18.1, covering at minimum the
   loading-state, default-render, edited-render, send-success, and
   send-failure paths.
5. THE mobile app SHALL include a Vitest unit test for
   `SendEmailSheet.tsx` covering the same five paths plus the safe-area
   inset render.
6. THE backend SHALL include a `tests/test_html_sanitise.py` covering
   the XSS-payload allowlist and a
   `tests/test_email_compose_preview.py` covering the preview endpoint
   for all 10 template types listed in Requirement 20.1.
7. A pytest property test in
   `tests/test_email_compose_default_equivalence.py` SHALL assert that
   for any `(template_type, entity_id)`, the body bytes produced by
   Email_Preview_Endpoint exactly equal the body bytes produced by
   calling the underlying sending function with no overrides — to
   guard against silent divergence between the preview path and the
   auto-send path (Requirement 3.6 byte-equivalence).
8. Per user direction during this spec, only NEW and DIRECTLY-RELEVANT
   tests SHALL be required to pass before the feature is considered
   done — the full project test suite SHALL NOT block this work.
   Specifically: the tests in 21.1, 21.4, 21.5, 21.6, and 21.7 SHALL
   pass. Pre-existing tests outside the modified files SHALL be left
   unmodified and SHALL NOT be required to be re-run by this spec.

### Requirement 22: Trade-Family Awareness

**User Story:** As a non-automotive org admin, I do not want WOF / COF
reminders to appear in the modal's surface list, since those concepts do
not apply to my trade.

#### Acceptance Criteria

1. THE Send_Email_Modal itself SHALL be universal across all trade
   families and SHALL NOT contain any trade-specific code paths.
2. THE Resend trigger on a `wof_expiry_reminder`, `cof_expiry_reminder`,
   `registration_expiry_reminder`, or `service_due_reminder`
   notification_log row SHALL be visible only when BOTH of the
   following are true:
   (a) `useModuleEnabled('vehicles')` returns `true`
   (per `.kiro/steering/vehicle-carjam-module-gating.md`), AND
   (b) `(tradeFamily ?? 'automotive-transport') === 'automotive-transport'`
   (per `.kiro/steering/trade-family-gating-for-new-features.md`,
   keeping the null-fallback for backward compatibility with orgs
   that have not set their trade).
   Both checks SHALL be enforced on the frontend (to hide the
   trigger) AND on the backend: the corresponding resend endpoint
   SHALL call `ModuleService.is_enabled(org_id, 'vehicles')` and
   SHALL return HTTP 403 with detail "Vehicles module is not enabled
   for this organisation" when disabled, regardless of whether the
   frontend showed the button.
3. THE Send_Statement, Send_Portal_Link, Send_Invoice, Send_Quote,
   Send_Payment_Link, and Send_Receipt surfaces SHALL be available in
   every trade family (these are universal business actions).
4. THE mobile sheet's surface availability SHALL be evaluated via the
   same module-AND-trade-family composition. Surfaces SHALL fail
   closed (hidden) when the relevant module is disabled, matching
   the mobile module-gate pattern from
   `.kiro/steering/mobile-app.md`.

### Requirement 23: Issue Tracking

**User Story:** As a team that learns from past incidents, I want bugs
discovered while building the modal logged in the project issue tracker.

#### Acceptance Criteria

1. EVERY bug encountered during implementation SHALL be logged in
   `docs/ISSUE_TRACKER.md` per the
   `.kiro/steering/issue-tracking-workflow.md` rule, including
   regressions of any prior issue listed in `Related Issues`.
2. ANY discovered bug in the underlying email_sender, resolve_template,
   or notification_log code paths SHALL be filed in the same tracker
   with the affected surface clearly identified, even if the fix is
   outside this spec's scope.

### Requirement 24: Design System Compliance

**User Story:** As a designer, I want the modal to slot into the
frontend-v2 redesign without introducing new visual primitives, so that
it feels native to the rest of the app.

#### Acceptance Criteria

1. THE web modal SHALL use the existing UI primitives from
   `frontend-v2/src/components/ui/` (Modal/Dialog, Button, Input, Badge)
   wherever a primitive exists. THE modal SHALL NOT introduce new
   primitives or wrap existing ones with parallel implementations.
2. Typography in both web modal and mobile sheet SHALL use IBM Plex
   Sans for body text AND IBM Plex Mono with
   `font-feature-settings: "tnum" 1` for numbers, IDs, hashes, and
   timestamps (e.g. attachment sizes, `edited_body_hash` previews,
   provider message ids), per `.kiro/steering/frontend-redesign.md`.
3. Visual style SHALL use the Design_Tokens documented in
   `OraInvoice_Handoff/app/ds.css`: `--accent #2F62F0`, `--ink #0B1220`,
   `--canvas #F5F6F8`, `--card #FFFFFF`, `--border #E8EBF0`,
   `--r-card 14px`, `--r-ctl 10px`. Backgrounds, borders, and radii
   SHALL be expressed via these tokens (or their Tailwind theme
   bindings) and SHALL NOT introduce new colour or radius values.
4. Icons SHALL come from the project's existing icon library
   (Lucide). THE modal SHALL NOT add a new icon dependency.
5. EVERY interactive element on the web modal SHALL meet a minimum
   touch target of 40–44 CSS px, matching the existing redesign rule
   and the mobile-app rule (Requirement 12.3).
6. BOTH the web modal and the mobile sheet SHALL support dark mode
   via Tailwind `dark:` variants on every coloured element (background,
   border, text, and status banner colours).
7. TipTap toolbar buttons SHALL be styled to match the existing
   toolbar/button styles in the redesign (small ghost buttons with
   consistent padding, hover state, and focus ring) — they SHALL NOT
   ship with TipTap's default styling.

### Requirement 25: Backend Endpoint Middleware Posture

**User Story:** As a security engineer, I want the new endpoint traced
through every middleware layer before it ships, so that we don't repeat
the B2B Fleet Portal class of integration failure
(`.kiro/steering/implementation-completeness-checklist.md` Rule 2).

#### Acceptance Criteria

1. THE new `GET /api/v2/email-preview` endpoint SHALL be authenticated
   (require a valid JWT). It SHALL NOT be added to `PUBLIC_PATHS` or
   `PUBLIC_PREFIXES` in the auth middleware.
2. THE endpoint SHALL set the RLS GUC `app.current_org_id` for the
   requesting org via the existing dependency chain so that all
   underlying queries (template resolution, customer email lookup,
   attachment resolution, blocklist check) are RLS-filtered to the
   user's org.
3. THE endpoint SHALL apply the same role gate as the underlying
   surface: `require_role("org_admin", "salesperson")`.
4. THE endpoint SHALL be subject to the existing per-user rate limit;
   no special exemption SHALL be added. A documented per-user limit
   of at least 60 requests/minute SHALL apply (typical for a
   read-on-modal-open pattern; the modal opens once per Send click).
5. EVERY Override_Send_Endpoint SHALL retain its existing auth, role
   gate, rate-limit, and CSRF middleware. None SHALL be added to any
   exemption list as part of this feature.
6. WHERE the surface is the vehicle-reminder Resend
   (`POST /api/v2/notifications/log/{log_id}/resend`), the endpoint
   SHALL additionally call
   `ModuleService.is_enabled(org_id, 'vehicles')` and SHALL return
   HTTP 403 when disabled (Requirement 22.2 backend half).

### Requirement 26: Versioning

**User Story:** As a release engineer, I want the version numbers bumped
when this feature ships, so that the changelog stays accurate.

#### Acceptance Criteria

1. Implementation of this feature SHALL bump the **MINOR** version
   (per `.kiro/steering/versioning-and-changelog.md`) in BOTH
   `pyproject.toml` AND `frontend-v2/package.json` AND
   `mobile/package.json`. The three files SHALL stay in sync.
2. A `CHANGELOG.md` entry SHALL be added under the new version with
   the following line in the **Added** section: "Send Email composer
   modal (web + mobile) — review and edit subject, body, recipients,
   and attachments before sending invoices, quotes, statements, and
   reminders."
3. NO git tag SHALL be required by this spec.
4. NO production deploy SHALL be required by this spec — the user has
   explicitly placed Pi-prod deployment out of scope; the feature
   ships to the local dev environment for verification only (see
   Requirement 29).

### Requirement 27: Accessibility

**User Story:** As a keyboard or screen-reader user, I want the modal to
be fully usable without a mouse and to announce errors as they happen,
so that the composer is not gated on sighted-mouse-user assumptions.

#### Acceptance Criteria

1. THE modal SHALL implement focus trap: focus moves into the modal on
   open, Tab cycles within the modal only, Shift+Tab cycles in
   reverse, AND Escape closes the modal (returning focus to the
   triggering element).
2. THE TipTap editor SHALL be keyboard-navigable: every toolbar button
   SHALL be reachable by Tab, AND Bold / Italic / Underline SHALL
   have keyboard shortcuts Ctrl+B, Ctrl+I, Ctrl+U respectively
   (Cmd-equivalents on macOS).
3. THE status banner (Requirement 14.1) SHALL render with
   `role="alert"` so that screen readers announce errors immediately
   when they appear.
4. EVERY form field (chip inputs, subject, body editor, attachment
   checkboxes) SHALL have an associated `<label>` linked via
   `htmlFor` / `id`. Placeholder text SHALL NOT be the only label.
5. Colour SHALL NOT be the sole carrier of meaning on the
   bounce-blocklist chips (Requirement 4.5–4.6, 13): the icon (warning
   triangle for soft, error octagon for hard) SHALL accompany the
   colour so red/green-blind users get the same signal.
6. THE Send button SHALL announce its loading state via
   `aria-busy="true"` while the request is in flight (Requirement
   8.2).

### Requirement 28: Performance

**User Story:** As a user clicking Send, I want the modal to open
quickly and I want the Send action to be bounded so that I'm never
left staring at an unresponsive UI.

#### Acceptance Criteria

1. THE Email_Preview_Endpoint SHALL meet a p95 latency under 500 ms
   for warm-cache requests on the local dev environment, and under
   1.5 s p95 in production-like load. THE 95th-percentile target
   SHALL be measured during the e2e test (Requirement 21.1) and
   reported in the test output.
2. THE web/mobile modal SHALL show a loading skeleton ONLY when the
   preview response takes longer than 300 ms; on faster responses
   THE modal SHALL render directly with the preview content to avoid
   a flash of skeleton on fast networks.
3. THE Send action SHALL be bounded to `EMAIL_TOTAL_BUDGET_SECONDS`
   (45 s — the existing email-sender total budget). THE preview
   response SHALL include this value alongside `email_size_limit_bytes`
   as `total_budget_seconds: number` so the modal does not hardcode
   it. After this budget, the modal SHALL show the budget-exceeded
   banner from Requirement 14.5.
4. THE TipTap editor bundle on the web app SHALL not exceed 80 KB
   gzipped: the modal SHALL pull in only `@tiptap/starter-kit` and
   `@tiptap/extension-link`; it SHALL NOT pull in collaboration,
   `@tiptap/extension-collaboration`, history-with-yjs, or other
   heavy modules. The Vite bundle analyser report SHALL be checked
   as part of the design phase to confirm this.

### Requirement 29: Deployment Scope

**User Story:** As a developer, I want to know explicitly that this work
ships to local dev only, so that I do not waste time on Pi-prod
deployment steps.

#### Acceptance Criteria

1. This feature SHALL be developed and verified against the local
   dev environment ONLY. Deployment to Pi production, Pi standby, or
   the local prod-standby environment is OUT OF SCOPE for this spec.
2. NO `git push` and NO `git tag` SHALL be required by this spec; the
   work SHALL be allowed to merge through whatever local-dev review
   process the project uses.
3. The deployment instructions in
   `.kiro/steering/project-overview.md` for Pi prod SHALL NOT be
   exercised as part of this feature's task list.

