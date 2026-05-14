# In-App Notifications — Requirements

## 1. Overview

Build a per-org, per-user in-app notification system so org users get timely, persistent feedback when something fails or completes outside the page they triggered the action from. The first and most important use case is **email send failures** — today, when an invoice/quote/booking confirmation/reminder email fails, the user often gets no feedback at all (silent log line) or a one-shot toast that disappears. This spec adds a durable inbox accessible from the header bell icon plus mobile parity.

This is a foundation feature: once the table and helpers exist, every async event in the app (stock alerts, payments received, quote accepted, account locked, Xero sync failed, etc.) can publish to the same inbox without per-feature plumbing.

## 2. In-Scope vs Out-of-Scope

In scope:
- Web inbox (bell dropdown + full inbox screen)
- Mobile inbox (bell + dedicated screen)
- Backend table + RLS + helper service + 5 endpoints
- Wiring up every existing "email send" call site so failures emit notifications
- Wiring the existing stock-out audit entries (in `app/modules/quotes/service.py`) to also emit notifications
- Toast on failure remains for instant feedback; the new system is additive

Out of scope (explicitly):
- Real-time push (WebSocket / SSE) — initial release is short-poll. Web sockets can be added later without schema change.
- Email/SMS digest of unread in-app notifications
- Browser push notifications
- Replacing or merging `notification_log` (delivery audit trail) — these stay separate
- Replacing or merging `platform_notifications` (global-admin → orgs announcements) — these stay separate
- Notification routing rules per user (everyone in the org with the right role gets the same notifications)
- Bulk admin tools to broadcast in-app notifications (that's `platform_notifications`' job)

## 3. User Personas

- **org_admin** — primary audience; needs to see every email failure, stock alert, payment received across the whole org
- **salesperson** — sees notifications scoped to entities they own (e.g. quotes/invoices they sent) plus org-wide informational items
- **global_admin** — does not consume org-level in-app notifications; their inbox stays in `platform_notifications` admin views
- **mobile org user** — same audience as web org users, in the mobile companion app

## 4. Functional Requirements

### 4.1 Notification creation (backend)
- 4.1.1 The system SHALL provide an internal helper `create_in_app_notification(db, org_id, ...)` callable from any service.
- 4.1.2 Every notification SHALL belong to exactly one organisation.
- 4.1.3 A notification MAY target a specific user (`user_id != NULL`) or be org-wide (`user_id IS NULL`). Org-wide notifications are visible to every active user with role in the notification's `audience_roles` set.
- 4.1.4 A notification SHALL have a severity in {`info`, `success`, `warning`, `error`} for visual treatment.
- 4.1.5 A notification SHALL have a category enum string identifying its source (e.g. `email_failure`, `stock_alert`, `quote_accepted`, `payment_received`, `account_locked`, `xero_sync_failed`). Frontend uses category to pick an icon and group in filters.
- 4.1.6 A notification SHALL have a short title (≤120 chars) and a body (≤2000 chars). Body MAY contain plain text only — no HTML or markdown rendering in v1.
- 4.1.7 A notification MAY have a deep-link `link_url` (relative path within the app, e.g. `/invoices/abc-123`).
- 4.1.8 A notification MAY reference an entity via `entity_type` + `entity_id` so the UI can render an entity preview if needed later.
- 4.1.9 A notification MAY carry a `metadata` JSONB blob for category-specific structured fields (e.g. `{ "recipient_email": "...", "error_message": "..." }` for `email_failure`). The metadata is opaque to the system and SHALL NOT be required to render.
- 4.1.10 The helper SHALL never raise on failure. If the insert fails for any reason (DB error, encoding error), it SHALL log a warning and return None. A failed notification insert MUST NOT abort the calling business operation (e.g. an email failure that itself fails to log a notification must not return a 500 to the user).

### 4.2 Notification consumption (read/dismiss)
- 4.2.1 Each user SHALL have a per-user `is_read` and `dismissed_at` state for every visible notification, even when the notification is org-wide.
- 4.2.2 An org-wide notification SHALL appear unread for every targeted user until each user marks it read individually.
- 4.2.3 Marking a notification as read SHALL be idempotent.
- 4.2.4 Dismissing a notification SHALL hide it from the inbox and badge count for that user only. Other users still see it.
- 4.2.5 Notifications SHALL not be hard-deleted via API. Cleanup of old notifications is a separate cron concern (see 4.5).
- 4.2.6 The unread-count endpoint SHALL be cheap to call (single indexed COUNT) so the UI can poll on a 30-second interval without performance impact.

### 4.3 Email failure notifications (the must-have)
- 4.3.1 Every "All email providers failed" code path SHALL call the helper and emit one `email_failure` notification per failure. Affected sites:
  - `app/modules/quotes/service.py` (`send_quote`)
  - `app/modules/invoices/service.py` (`email_invoice` and `send_receipt_email`)
  - `app/modules/customers/service.py` (`send_customer_notification`)
  - `app/modules/bookings/service.py` (`send_booking_confirmation_email`)
  - `app/modules/auth/service.py` (lockout, invite, verify, password-reset emails)
  - `app/modules/payments/service.py` (Stripe payment receipts)
  - `app/modules/vehicles/report_service.py` (vehicle reports)
  - `app/modules/landing/router.py` (demo request)
  - `app/tasks/scheduled.py`, `app/tasks/subscriptions.py` (cron-driven sends)
- 4.3.2 Severity SHALL be `error`.
- 4.3.3 Title SHALL summarise context, e.g. `"Email failed: Invoice INV-0042 to acme@example.com"`.
- 4.3.4 Body SHALL include the recipient address and the last error message (truncated to 1500 chars).
- 4.3.5 `link_url` SHALL deep-link to the relevant entity when one exists (invoice, quote, customer, booking).
- 4.3.6 `metadata` SHALL include `{ recipient_email, template_type, error_message, entity_type, entity_id }`.
- 4.3.7 Audience SHALL be `audience_roles=['org_admin','salesperson']` for entity-scoped sends; `audience_roles=['org_admin']` only for system emails (lockout, payment failed).
- 4.3.8 The notification helper SHALL also be invoked for any send that is currently logged-and-swallowed (booking confirmation, auth emails, payment receipts) — these sites MUST be wired even though they don't currently raise.

### 4.4 Stock-out alert notifications
- 4.4.1 The existing `accept_quote_by_token` and `convert_quote_to_invoice` flows in `app/modules/quotes/service.py` already detect out-of-stock items and write `notification_log` rows with `template_type='stock_reorder_alert'` (which currently violates the `ck_notification_log_channel` CHECK constraint with `channel='in_app'`). This spec replaces those broken inserts with calls to the new helper.
- 4.4.2 Severity SHALL be `warning`.
- 4.4.3 Title SHALL identify the part and the trigger entity (e.g. `"Restock needed: Brake Pad #BP-04 (quote QT-0011 accepted)"`).
- 4.4.4 Audience SHALL be `audience_roles=['org_admin']`.

### 4.5 Retention
- 4.5.1 Read or dismissed notifications older than 90 days MAY be hard-deleted by a scheduled cleanup task. Unread notifications MAY be hard-deleted after 180 days.
- 4.5.2 Cleanup SHALL be a separate concern; this spec adds the table + indexes that make cleanup efficient but does not implement the cron job. (Implementation can ride on the existing `app/tasks/scheduled.py` later.)

## 5. API Endpoints

All endpoints under `/api/v1/notifications/inbox` (and re-registered at `/api/v2/notifications/inbox` per the platform v1/v2 convention). All endpoints require an authenticated org user; `global_admin` is excluded.

| Method | Path | Returns |
|---|---|---|
| GET | `/inbox` | paginated list `{ items: [...], total, unread_count }` with `?limit=20&offset=0&unread_only=false&category=email_failure&severity=error` filters |
| GET | `/inbox/unread-count` | `{ count }` — for the bell badge, cheap to poll |
| POST | `/inbox/{id}/read` | mark a single notification read (idempotent) |
| POST | `/inbox/mark-all-read` | mark every visible notification read for current user |
| POST | `/inbox/{id}/dismiss` | dismiss for current user only |

Optional convenience: `POST /inbox/dismiss-all-read` — dismisses everything currently read.

## 6. Frontend Web Requirements

### 6.1 Header bell
- 6.1.1 The existing bell button in `frontend/src/layouts/OrgLayout.tsx` SHALL display a red badge with the unread count when count > 0.
- 6.1.2 Badge SHALL show `99+` when count exceeds 99.
- 6.1.3 Clicking the bell SHALL open a dropdown panel listing the most recent 10 notifications (newest first).
- 6.1.4 Each item in the dropdown SHALL show severity icon, title, relative time, and (if `link_url`) be clickable.
- 6.1.5 Dropdown SHALL include a "View all" link to `/notifications/inbox` and a "Mark all as read" button.
- 6.1.6 Dropdown SHALL NOT block the page (it's a popover, not a modal).
- 6.1.7 The badge count SHALL refresh every 30 seconds via polling and immediately when the dropdown opens.

### 6.2 Inbox page
- 6.2.1 New route `/notifications/inbox` rendering full paginated list.
- 6.2.2 Filters: severity (info/success/warning/error/all), unread-only toggle, category dropdown.
- 6.2.3 Each row clickable to deep-link entity if `link_url` is set; clicking marks read.
- 6.2.4 Inline "Dismiss" button per row.
- 6.2.5 Toolbar: "Mark all as read", "Dismiss all read".
- 6.2.6 Empty state: "You're all caught up."

### 6.3 Toasts retained
- 6.3.1 The existing toast on send-action failure (Email banner on quote/invoice send) SHALL remain — it provides immediate feedback while the bell is the persistent record.

## 7. Frontend Mobile Requirements

- 7.1 The mobile More menu SHALL include a "Notifications" item (always visible — no module gate, since this is a core SaaS UX element). Roles: `owner`, `admin`, `salesperson` per `mobile-app.md`.
- 7.2 A new `NotificationsScreen.tsx` under `mobile/src/screens/notifications/` SHALL list inbox items using the existing `MobileList`/`PullRefresh` pattern.
- 7.3 The mobile dashboard SHALL show an unread count badge on the More tab when count > 0, fetched from the same `/unread-count` endpoint.
- 7.4 Touch target ≥ 44×44, dark-mode classes, safe-area insets per the mobile steering doc.
- 7.5 Tapping an item with `link_url` SHALL navigate to the in-app screen if it maps to an existing mobile route; otherwise show the body text in a detail view.

## 8. Non-Functional Requirements

- 8.1 RLS: the `app_notifications` table SHALL be RLS-protected; the per-user-state table SHALL also be RLS-protected by `org_id`. Cross-org leak is impossible by construction.
- 8.2 Indexes: composite `(org_id, created_at DESC)` for org listing; composite `(user_id, dismissed_at, created_at DESC)` for per-user inbox scans.
- 8.3 Helper performance: a single `create_in_app_notification` call SHALL execute in one INSERT (org-wide). Per-user state rows are created lazily on read (no fan-out write at create time).
- 8.4 Helper resilience: the helper SHALL be wrapped so that any DB error, encoding error, or RLS error inside it is caught and logged, never propagated.
- 8.5 No new dependencies. Reuses existing FastAPI, SQLAlchemy async, axios, React patterns.
- 8.6 Polling at 30s on `/unread-count` MUST NOT trigger rate limits in dev or prod (the unread-count query is a single COUNT against an index).

## 9. Acceptance Criteria

- AC-1 When an invoice email fails to send (no provider configured / wrong creds / SMTP down), an `email_failure` row appears in `app_notifications` with severity `error`, audience `org_admin+salesperson`, recipient/error in metadata, and `link_url=/invoices/{id}`. The bell badge shows `1` for the org_admin who didn't trigger the send.
- AC-2 The org_admin opens the bell dropdown and sees the failure with a red icon. Clicking it navigates to the invoice detail page and the badge decrements to `0`.
- AC-3 A second user (salesperson) on the same org sees the same notification in their bell — independent read state.
- AC-4 Dismissing the notification as one user does NOT remove it from the other user's inbox.
- AC-5 `global_admin` users do not see the org-level inbox bell badge or any items.
- AC-6 Quote acceptance with out-of-stock part creates a `stock_alert` notification visible to the org_admin, and the previously-broken `notification_log` insert with `channel='in_app'` is removed.
- AC-7 Mobile More menu shows the unread count and tapping opens an inbox screen with parity for read/dismiss.
- AC-8 30-second polling under React StrictMode (double mount) makes ≤2 calls per cycle and is rate-limit safe.
- AC-9 Cross-org RLS test: a notification for org A is invisible to a user in org B even with a tampered request.
- AC-10 Existing `notification_log` delivery log continues to work unchanged.

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Notification creation introduces failure points in critical flows (email → invoice issued) | Helper catches all exceptions, never propagates. Email send remains the source of truth for "did the message go". |
| Polling wastes resources on idle tabs | 30s interval, indexed COUNT, abort on tab unmount via existing `AbortController` pattern. SSE/WS upgrade is a separate spec. |
| Org-wide notifications fan out to thousands of `notification_reads` rows on busy orgs | State rows are created on read, not on broadcast. INSERT happens once at notification creation. |
| Body text too long for SMS-style truncation in mobile cards | Title is the primary surface; body is shown in detail. Both have hard length caps in the schema. |
| Spec-completeness checklist warns about HTML/markdown injection if body is rendered as HTML | Body is rendered as `whitespace-pre-line` text only; no `dangerouslySetInnerHTML`. |
| Two notification systems (`notification_log` for delivery, `app_notifications` for inbox) cause confusion | Clear naming and separate UI surfaces. The existing `/notifications` settings page (Preferences / Templates / Delivery Log / Reminders / Overdue Rules tabs) stays unchanged. The new inbox is a separate destination at `/notifications/inbox`, reached via the header bell. The settings page may gain a small "View activity" link in its header pointing to `/notifications/inbox` for discoverability — this is a one-line UI change, not a new tab. |

## 11. Glossary

- **Inbox**: the per-user feed of `app_notifications` items for the current org.
- **Delivery log**: the existing `notification_log` table — every email/SMS attempt with provider, status, error. System audit, not user-facing primary.
- **Platform notifications**: the existing `platform_notifications` table — global-admin → orgs announcements (maintenance, feature flags). Different domain.
- **Audience**: combination of `user_id` (specific) or `audience_roles` (broadcast to roles within the org).
