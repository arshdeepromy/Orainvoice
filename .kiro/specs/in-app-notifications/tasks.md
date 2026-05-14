# In-App Notifications — Implementation Tasks

Tasks are ordered for safe incremental deployment. Each top-level task is independently deployable.

## Testing scope (applies to every task below)

When a task has a verification or test step, run **only the tests relevant to that task's changes**. Do NOT run the full test suite or unrelated module tests.

- Backend changes in `app/modules/in_app_notifications/`: run `pytest tests/test_in_app_notifications.py` only
- Backend changes wiring an email-failure site (e.g. `app/modules/quotes/service.py`): run that module's existing tests only — `pytest tests/integration/test_quotes.py` (or equivalent), plus the inbox tests if the wiring writes a notification
- Frontend web component changes: run vitest scoped to the changed files — e.g. `cd frontend && npx vitest run src/components/notifications/InboxBellBadge.test.tsx`
- Mobile changes: run vitest scoped to the changed mobile files only — `cd mobile && npx vitest run src/screens/notifications/`
- E2E script in §4.5: run only `scripts/test_in_app_notifications_e2e.py`, not the full e2e battery
- TypeScript diagnostics: run `getDiagnostics` only on files actually changed in the task
- Manual gates in §10 stay as written; they're targeted at the inbox feature, not regression sweeps

If a test failure surfaces in an unrelated module while running scoped tests, log it as a separate issue per `issue-tracking-workflow.md` — do NOT broaden the test scope to chase it.

## 1. Backend foundation

- [x] 1.1 Create Alembic migration `0185_create_in_app_notifications_tables.py`
  - **Revision `0185`, down-revision `0184`** — verified against `alembic/versions/`. The current head is `0184_quote_invoice_parity`, NOT `0182` as the project-overview steering doc claims.
  - Tables `app_notifications` and `notification_reads` per design §2
  - Indexes per design §2
  - RLS enabled on both tables with org-scoped policy, exact pattern matching `0184`:
    ```python
    op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {tbl}_org_isolation ON {tbl} "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )
    ```
  - **Add both tables to the `ora_publication` HA replication publication** using the `_HA_ADD_TPL` snippet from `0184_quote_invoice_parity.py` and `0170_create_invoice_attachments.py`. Mandatory for HA standby parity. Include matching `_HA_DROP_TPL` in downgrade.
  - Idempotent `CREATE TABLE IF NOT EXISTS`, `DROP POLICY IF EXISTS` in downgrade per `database-migration-checklist.md`
  - Run `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head` and verify success (should show `Running upgrade 0184 -> 0185`)
  - Verify the policy applied: `\d+ app_notifications` in psql shows the policy
  - _Requirements: 4.1, 4.2, 8.1, 8.2_

- [x] 1.2 Add SQLAlchemy models
  - Create `app/modules/in_app_notifications/__init__.py`
  - Create `app/modules/in_app_notifications/models.py` with `AppNotification` and `NotificationRead`
  - Match column types and constraints to migration exactly
  - _Requirements: 4.1_

- [x] 1.3 Add Pydantic schemas
  - Create `app/modules/in_app_notifications/schemas.py`
  - `InboxItem`, `InboxResponse`, `UnreadCountResponse`, `MarkReadRequest`, `DismissRequest`
  - Use `Literal` for severity and category allow-list
  - All response shapes wrapped in objects per `frontend-backend-contract-alignment.md`
  - _Requirements: 5_

- [x] 1.4 Implement service helpers
  - Create `app/modules/in_app_notifications/service.py`
  - `create_in_app_notification` — must be exception-safe; catches all errors and logs warning, never raises
  - `list_inbox`, `get_unread_count`, `mark_read`, `mark_all_read`, `dismiss`, `dismiss_all_read`
  - Visibility query joins per design §13
  - Use `db.flush()` only — never `commit()` (per `setup-guide-for-new-modules.md` and `get_db_session` pattern)
  - _Requirements: 4.1, 4.2, 8.4_

- [x] 1.5 Implement router
  - Create `app/modules/in_app_notifications/router.py`
  - 6 endpoints per design §3.2
  - **Reject `global_admin` on every endpoint with 403** — note this is the OPPOSITE of the existing `app/modules/notifications/router.py` (which allows global_admin for delivery log). The inbox is an org-user feature and global_admin must not have an inbox. Use the `_extract_org_context` helper pattern from design §3.2.
  - Return JSONResponse on org-context-missing with 403
  - Validate `link_url` is relative (must start with `/`, must not contain `://`) — reject with 400 in the create helper if it fails (caller's bug, not user's)
  - _Requirements: 5_

- [x] 1.6 Mount router in main.py
  - Add v1 mount at `/api/v1/notifications` and v2 mount at `/api/v2/notifications`
  - Verify no path collision with existing `/notifications/log`, `/notifications/templates`, `/notifications/settings`, `/notifications/sms-templates`, `/notifications/sms-settings`, `/notifications/overdue-rules`, `/notifications/wof-rego-settings`, `/notifications/webhooks/*` — confirmed clear (the new prefix is `/inbox`)
  - _Requirements: 5_

- [x] 1.7 Backend unit + property tests
  - `tests/test_in_app_notifications.py`
  - Cover create, list, unread-count, mark-read, dismiss
  - Property test: any interleaving of mark-read and dismiss is idempotent
  - RLS test: insert org A notification, query as org B user, assert 0 results
  - global_admin test: endpoints return 403
  - _Requirements: 8.1, AC-9_

## 2. Replace stock-alert broken inserts

- [x] 2.1 Locate the four `db.add(NotificationLog(... channel="in_app" ...))` sites
  - Lines around 2240, 2284, 2325, 2369 in `app/modules/notifications/service.py` (branch admin notifications: branch added, branch deactivated, billing updated, stock transfer request)
  - Plus any sites in `app/modules/quotes/service.py` writing `template_type='stock_reorder_alert'` rows during `accept_quote_by_token` and `convert_quote_to_invoice` (added in TASK 15 of the previous session)
  - These all violate the `ck_notification_log_channel` CHECK constraint (`channel IN ('email','sms')`); they will fail at INSERT time. Confirmed latent bug.
  - _Requirements: 4.4_

- [x] 2.2 Replace each with `create_in_app_notification` calls
  - Stock-out cases: `category="stock_alert"`, severity `"warning"`, audience `["org_admin"]`
  - Branch admin cases: `category="system"`, severity `"info"`, audience `["org_admin"]`
  - Match the existing title/body content; keep entity_type/entity_id where present
  - _Requirements: 4.4_

- [x] 2.3 Verify the broken `notification_log` insert is gone via grep
  - `grepSearch query='channel=\"in_app\"'` should return zero results in `app/`
  - Run any existing tests that touch `notifications/service.py` to confirm no regression
  - _Requirements: 4.4_

## 3. Wire email-failure sites that currently raise

- [x] 3.1 `app/modules/quotes/service.py` `send_quote`
  - Before `raise ValueError("All email providers failed...")`, call `create_in_app_notification` with category `email_failure`, severity `error`, audience `[org_admin, salesperson]`, `link_url=/quotes/{quote_id}`, metadata `{recipient, template_type, error}`
  - Also add the missing `await log_email_sent(... status='failed' ...)` for parity with customers pattern
  - _Requirements: 4.3.1_

- [x] 3.2 `app/modules/invoices/service.py` `email_invoice` and `send_receipt_email`
  - Same pattern as 3.1 but with `link_url=/invoices/{invoice_id}` and entity_type `invoice`
  - _Requirements: 4.3.1_

- [x] 3.3 `app/modules/customers/service.py` `send_customer_notification`
  - Already calls `log_email_sent` on failure; add `create_in_app_notification` next to it
  - `link_url=/customers/{customer_id}`, entity_type `customer`
  - _Requirements: 4.3.1_

- [x] 3.4 `app/modules/vehicles/report_service.py`
  - `link_url=/vehicles/{vehicle_id}`, entity_type `vehicle`
  - _Requirements: 4.3.1_

## 4. Wire email-failure sites that currently swallow

- [x] 4.1 `app/modules/bookings/service.py` booking confirmation
  - Replace warning-log with notification call; keep the `return False` behaviour
  - `link_url=/bookings/{booking_id}`
  - _Requirements: 4.3.1_

- [x] 4.2 `app/modules/payments/service.py` Stripe receipt email
  - Notification call where `logger.warning("All email providers failed for receipt email...")` lives
  - `link_url=/invoices/{invoice_id}`
  - _Requirements: 4.3.1_

- [x] 4.3 `app/modules/landing/router.py` demo request
  - No org_id available (public form). Skip notification — these failures stay in logs only. Document in code comment.
  - _Requirements: 4.3.1 (with documented exception)_

- [x] 4.4 Auth flows (lockout, invite, verify, reset)
  - Skip in v1 — these run on sessions without org_id context. Documented as known limitation in spec section 4.2 of design.
  - _Requirements: design §4.2 (known limitation)_

- [x] 4.5 Backend e2e test
  - `scripts/test_in_app_notifications_e2e.py` per `feature-testing-workflow.md`
  - Create org + admin user + salesperson user
  - Trigger quote send with no email provider configured → assert notification created with correct fields
  - Assert salesperson sees same notification independently
  - Cleanup with `TEST_E2E_` prefix
  - _Requirements: AC-1, AC-3, AC-4_

## 5. Web frontend — bell badge + dropdown

- [x] 5.1 Create `frontend/src/components/notifications/InboxBellBadge.tsx`
  - 30s polling against `/notifications/inbox/unread-count` (use `apiClient.get<UnreadCountResponse>`)
  - AbortController cleanup per `safe-api-consumption.md`
  - Refetch on window focus
  - Returns null when count is 0
  - Show `99+` when count > 99
  - _Requirements: 6.1.1, 6.1.2, 6.1.7_

- [x] 5.2 Create `frontend/src/components/notifications/InboxBellDropdown.tsx`
  - Headless UI Popover
  - On open, fetch `apiClient.get<InboxResponse>('/notifications/inbox?limit=10')`
  - Item click → mark read + navigate
  - Footer: "Mark all as read" + "View all"
  - Empty state
  - All response access guarded with `?.items ?? []` per safe-api-consumption
  - _Requirements: 6.1.3-6.1.6_

- [x] 5.3 Create `frontend/src/components/notifications/InboxItemCard.tsx`
  - Severity icon + title + body preview + relative time
  - Used in dropdown and inbox page
  - Dark-mode classes
  - _Requirements: 6.1.4, 6.2.3_

- [x] 5.4 Update `frontend/src/layouts/OrgLayout.tsx`
  - Wrap existing bell button to render `<InboxBellBadge />` inside it
  - Replace `onClick={() => navigate('/notifications')}` with the dropdown trigger
  - Verify the existing compliance `NotificationBadge` on the sidebar is untouched
  - _Requirements: 6.1.1_

- [x] 5.5 Frontend tests
  - Vitest tests for `InboxBellBadge` (count 0 hides, count > 99 shows `99+`, polling)
  - Vitest tests for `InboxBellDropdown` (loads, marks read on click, navigates on link)
  - _Requirements: AC-2, AC-5_

## 6. Web frontend — inbox page

- [x] 6.1 Create `frontend/src/pages/notifications/InboxPage.tsx`
  - Layout per design §6.4
  - Filters: All/Unread toggle, Severity dropdown, Category dropdown
  - URL persistence via existing pattern
  - Pagination 25/page using existing `Pagination` component
  - "Mark all read" + "Dismiss read" toolbar buttons
  - Per-row "Dismiss" inline button
  - Loading + error + empty states
  - _Requirements: 6.2_

- [x] 6.2 Create shared hook `frontend/src/pages/notifications/useInbox.ts`
  - List, mark-read, dismiss, mark-all-read, dismiss-all-read
  - AbortController cleanup
  - _Requirements: 6.2_

- [x] 6.3 Add lazy import + route in `frontend/src/App.tsx`
  - `const InboxPage = lazy(() => import('./pages/notifications/InboxPage'))`
  - Route `/notifications/inbox` under OrgLayout block
  - _Requirements: 6.2.1_

- [x] 6.4 Frontend tests for inbox page
  - Vitest: list renders, filter changes URL, mark-all-read button, empty state
  - _Requirements: 6.2_

## 7. Mobile frontend

- [x] 7.1 Add inbox API client
  - `mobile/src/api/inbox.ts` — typed wrappers for the 6 endpoints
  - Use `/api/v2/notifications/inbox` (mobile prefers v2 per `mobile-app.md`)
  - _Requirements: 7_

- [x] 7.2 Create `mobile/src/hooks/useInboxBadge.ts`
  - 30s polling, AbortController cleanup, returns `count`
  - Capacitor isNative guard not needed (HTTP polling is universal)
  - _Requirements: 7.3_

- [x] 7.3 Create `mobile/src/screens/notifications/NotificationsScreen.tsx`
  - PullRefresh + MobileList
  - Filter chips: All / Unread / by severity
  - Tap row: mark read + navigate (or open detail screen if no link)
  - Touch targets ≥44px, dark mode, safe-area
  - _Requirements: 7.2, 7.4, 7.5_

- [x] 7.4 Create `mobile/src/screens/notifications/NotificationDetailScreen.tsx`
  - Body view fallback when `link_url` doesn't map to a known mobile route
  - _Requirements: 7.5_

- [x] 7.5 Wire routes in `mobile/src/navigation/StackRoutes.tsx`
  - Lazy import `NotificationsScreen` and `NotificationDetailScreen`
  - Add routes `/notifications` and `/notifications/:id`
  - _Requirements: 7.2_

- [x] 7.6 Add More menu item in `mobile/src/screens/more/MoreMenuScreen.tsx`
  - moduleSlug `'*'` (always visible)
  - roles: owner, admin, salesperson
  - Show badge count via `useInboxBadge` if > 0
  - _Requirements: 7.1_

- [x] 7.7 Add More-tab badge in bottom tab bar
  - Hook `useInboxBadge` in the bottom tab component
  - Badge on the More tab when count > 0
  - _Requirements: 7.3_

- [x] 7.8 Mobile vitest tests
  - `NotificationsScreen` renders list, filter, mark-read, dismiss, empty state
  - _Requirements: AC-7_

## 8. Versioning + Changelog

- [x] 8.1 Bump version 1.6.0 → 1.7.0 in all three files (verified current version is 1.6.0 in each):
  - `pyproject.toml` line ~3
  - `frontend/package.json` line ~4
  - `mobile/package.json` line ~4
  - Per `versioning-and-changelog.md` (MINOR — new feature)
  - _Requirements: project rule_

- [x] 8.2 Add CHANGELOG.md entry under `[1.7.0]` "Added" section
  - "In-app notification inbox: bell badge, dropdown, full inbox page (web), mobile screen and More-tab badge"
  - "Email-send failures across quotes, invoices, customers, vehicle reports, bookings, payments now surface in the inbox"
  - "Stock-out alerts on quote acceptance now surface in the inbox; replaces broken `notification_log` insert with `channel='in_app'`"
  - _Requirements: project rule_

## 9. Issue tracker entry

- [x] 9.1 Find the next available issue number in `docs/ISSUE_TRACKER.md`
  - Project-overview steering says ISSUE-106 is the latest; check the actual file before assigning. The tracker is the source of truth.
  - Add an entry describing the latent CHECK-constraint violation in `notification_log` (`channel='in_app'` would violate `ck_notification_log_channel` which restricts channel to `('email','sms')`)
  - Mark fixed in this spec, link to spec name
  - _Requirements: `issue-tracking-workflow.md`_

## 10. Manual verification before sign-off

- [ ] 10.1 Verify migration applied in dev: `docker compose ... exec app alembic current` shows `0185`
- [ ] 10.2 Verify HA replication membership: in dev, `SELECT * FROM pg_publication_tables WHERE pubname='ora_publication' AND tablename IN ('app_notifications','notification_reads')` returns two rows. Skip this gate in environments where `ora_publication` doesn't exist (the `_HA_ADD_TPL` is guarded so the migration still succeeds).
- [ ] 10.3 Manually send a quote with email provider misconfigured; confirm bell badge increments within 30s
- [ ] 10.4 Open dropdown → click item → land on quote detail → bell decrements
- [ ] 10.5 Login as second user (salesperson) on same org → confirm same notification appears with independent unread state
- [ ] 10.6 Login as global_admin → confirm bell + inbox endpoints return 403; admin layout has no inbox bell
- [ ] 10.7 Mobile build: confirm More menu shows Notifications, badge updates, list renders, mark-read works
- [ ] 10.8 Cross-org test in dev DB: insert notification for org A, verify org B user sees zero items
- [ ] 10.9 Run `getDiagnostics` on every changed file — zero warnings
- [ ] 10.10 Run e2e script — passes with cleanup verified

## Notes

- All commits should reference this spec by name in the commit message.
- Each top-level task (1–8) is independently deployable. Don't batch — push incrementally so any regression is bisectable.
- Backend changes (1–4) ship before any frontend so the API is ready when the UI lands.
- Helper resilience (`create_in_app_notification` never raises) is the most important guarantee — protects the existing email send flows from regressing.
