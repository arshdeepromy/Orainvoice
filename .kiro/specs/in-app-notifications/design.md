# In-App Notifications — Design

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│ Service code (quotes/invoices/bookings/auth/payments...)    │
│                                                              │
│   try:                                                       │
│       send_email_with_failover(...)                          │
│   except Exception as e:                                     │
│       await create_in_app_notification(                      │
│           db, org_id=...,                                    │
│           category="email_failure",                          │
│           severity="error",                                  │
│           title="...", body="...",                           │
│           link_url="/invoices/...",                          │
│           audience_roles=["org_admin","salesperson"],        │
│           metadata={"recipient":"...","error":"..."},        │
│       )                                                      │
│       raise   # business logic still raises as before        │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────┐    ┌──────────────────────────┐
│ app_notifications (NEW)  │    │ notification_reads (NEW) │
│ org-scoped, RLS          │◄───│ per-user state, RLS      │
│ idx(org_id, created_at)  │    │ idx(user_id, ...)        │
└──────────────────────────┘    └──────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ /api/v1/notifications/inbox  +  /api/v2/notifications/inbox │
└─────────────────────────────────────────────────────────────┘
                          │
       ┌──────────────────┴──────────────────┐
       ▼                                     ▼
┌──────────────────┐              ┌──────────────────────┐
│ Web bell + page  │              │ Mobile bell + screen │
│ 30s poll         │              │ 30s poll + pull-refresh│
└──────────────────┘              └──────────────────────┘
```

The notification helper writes one row to `app_notifications`. Per-user `notification_reads` rows are created lazily — only when a user marks a notification read or dismisses it. This avoids fan-out writes for org-wide notifications.

## 2. Data Model

### 2.1 `app_notifications` (new table)

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, default `gen_random_uuid()` |
| `org_id` | UUID | NOT NULL, FK → `organisations.id` ON DELETE CASCADE |
| `user_id` | UUID | NULL = org-wide; FK → `users.id` ON DELETE CASCADE |
| `category` | VARCHAR(50) | NOT NULL — see allowed list below |
| `severity` | VARCHAR(20) | NOT NULL, CHECK in (`info`,`success`,`warning`,`error`) |
| `title` | VARCHAR(255) | NOT NULL |
| `body` | TEXT | NULL allowed |
| `link_url` | VARCHAR(500) | NULL allowed; relative path within app |
| `entity_type` | VARCHAR(50) | NULL allowed |
| `entity_id` | UUID | NULL allowed |
| `audience_roles` | JSONB | NOT NULL, default `'["org_admin"]'::jsonb` — JSONB array of role strings; queried with the `@>` containment operator |
| `metadata` | JSONB | NOT NULL, default `'{}'` |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `now()` |
| `expires_at` | TIMESTAMPTZ | NULL allowed — for auto-cleanup hint |

Indexes:
- `idx_app_notifications_org_created` on `(org_id, created_at DESC)`
- `idx_app_notifications_org_category` on `(org_id, category)`
- `idx_app_notifications_user_created` on `(user_id, created_at DESC)` WHERE `user_id IS NOT NULL`

RLS: enabled. Policy `app_notifications_org_policy` allows SELECT/INSERT/UPDATE where `org_id = current_setting('app.current_org_id')::uuid`.

`category` allowed list (validated in service, not DB CHECK so adding new categories doesn't need migrations):
- `email_failure`
- `sms_failure`
- `stock_alert`
- `quote_accepted`
- `quote_declined`
- `payment_received`
- `payment_failed`
- `invoice_overdue`
- `account_locked`
- `xero_sync_failed`
- `system` (catch-all)

### 2.2 `notification_reads` (new table)

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `org_id` | UUID | NOT NULL — copied from notification at insert for RLS scoping |
| `notification_id` | UUID | NOT NULL, FK → `app_notifications.id` ON DELETE CASCADE |
| `user_id` | UUID | NOT NULL, FK → `users.id` ON DELETE CASCADE |
| `read_at` | TIMESTAMPTZ | NULL = unread |
| `dismissed_at` | TIMESTAMPTZ | NULL = visible |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `now()` |

Constraints:
- `UNIQUE (notification_id, user_id)` — one row per user per notification
- Index `idx_notification_reads_user` on `(user_id, dismissed_at)`

RLS: enabled. Policy scoped by `org_id`.

### 2.3 SQLAlchemy models

Both tables go in a new module `app/modules/in_app_notifications/models.py`. Module sits alongside the existing `notifications/` (delivery log) module to keep concerns separated. Keeping it named `in_app_notifications` (not `notifications`) avoids ambiguity with the existing module.

### 2.4 Migration

`alembic/versions/2026_05_13_HHMM-0185_create_in_app_notifications_tables.py`
- **Revision: `0185`. Down-revision: `0184`** (verified — current head is `0184_quote_invoice_parity`, not `0182` as the project-overview steering doc suggests).
- Creates both tables, indexes, RLS policies, and adds both tables to the `ora_publication` HA replication publication using the same `_HA_ADD_TPL` / `_HA_DROP_TPL` snippets used in `0170_create_invoice_attachments.py` and `0184_quote_invoice_parity.py`. This is mandatory — every org-scoped table in this project must replicate to the HA standby.
- RLS policy pattern, exactly matching `0184`:
  ```python
  op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
  op.execute(
      f"CREATE POLICY {tbl}_org_isolation ON {tbl} "
      "USING (org_id = current_setting('app.current_org_id')::uuid)"
  )
  ```
  No `FOR ALL` clause; the policy defaults to all commands. Matches every existing org-scoped policy in the project.
- Idempotent: `CREATE TABLE IF NOT EXISTS` plus `DROP POLICY IF EXISTS` in downgrade.
- Tested locally via `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head` per the steering doc.

## 3. Backend Module Structure

```
app/modules/in_app_notifications/
    __init__.py
    models.py          # AppNotification, NotificationRead
    schemas.py         # Pydantic schemas (request/response)
    service.py         # create_in_app_notification, list_inbox, mark_read, dismiss
    router.py          # FastAPI endpoints under /notifications/inbox
```

### 3.1 service.py — public functions

```python
async def create_in_app_notification(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    category: str,
    severity: str,
    title: str,
    body: str | None = None,
    user_id: uuid.UUID | None = None,
    link_url: str | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    audience_roles: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    expires_at: datetime | None = None,
) -> uuid.UUID | None:
    """Create one notification row. Returns the new id, or None on failure.

    Never raises. All exceptions caught and logged. The helper is safe to
    call from any service without try/except at the call site.
    """

async def list_inbox(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    limit: int = 20,
    offset: int = 0,
    unread_only: bool = False,
    category: str | None = None,
    severity: str | None = None,
) -> dict[str, Any]:
    """Return { items: [...], total, unread_count }.

    Visibility filter:
    - notifications where user_id == current user, OR
    - notifications where user_id IS NULL AND role IN audience_roles

    Excludes rows where notification_reads.dismissed_at IS NOT NULL.
    """

async def get_unread_count(
    db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> int

async def mark_read(
    db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID,
    notification_id: uuid.UUID,
) -> bool  # creates notification_reads row if missing, sets read_at

async def mark_all_read(
    db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID, role: str,
) -> int  # returns count

async def dismiss(
    db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID,
    notification_id: uuid.UUID,
) -> bool  # sets dismissed_at

async def dismiss_all_read(
    db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID,
) -> int
```

`create_in_app_notification` is the only function imported by other modules. It uses `db.flush()` (not commit) per the project pattern — caller's `session.begin()` context manager will commit.

The "never raises" contract is implemented as:

```python
try:
    notif = AppNotification(...)
    db.add(notif)
    await db.flush()
    await db.refresh(notif)
    return notif.id
except Exception as exc:
    logger.warning(
        "in_app_notification.create_failed category=%s err=%s",
        category, exc,
    )
    return None
```

### 3.2 router.py — endpoints

All endpoints use `Depends(get_db_session)` and read `request.state.user_id`, `request.state.org_id`, `request.state.role` per the established pattern in `app/modules/notifications/router.py`. They reject `global_admin`.

Pattern at the top of every endpoint, copied from the existing notifications router:

```python
def _extract_org_context(request: Request) -> tuple[uuid.UUID | None, uuid.UUID | None, str | None]:
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    role = getattr(request.state, "role", None)
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        return None, None, role
    return org_uuid, user_uuid, role

# inside endpoint:
org_uuid, user_uuid, role = _extract_org_context(request)
if not org_uuid or not user_uuid:
    return JSONResponse(status_code=403, content={"detail": "Organisation context required"})
if role == "global_admin":
    return JSONResponse(status_code=403, content={"detail": "Inbox is for org users only"})
```

Note: the existing `notifications/router.py` allows `global_admin` for the delivery-log endpoint (line 247: `if role not in ("org_admin", "global_admin")`). This new inbox is **the opposite** — it must explicitly exclude `global_admin`. Don't copy the existing pattern blindly; use the exclusion check above.

```
GET  /inbox?limit=20&offset=0&unread_only=false&category=&severity=
GET  /inbox/unread-count
POST /inbox/{id}/read
POST /inbox/mark-all-read
POST /inbox/{id}/dismiss
POST /inbox/dismiss-all-read
```

Mounted in `app/main.py` at:
- `app.include_router(in_app_notifications_router, prefix="/api/v1/notifications", tags=["in-app-notifications"])`
- `app.include_router(in_app_notifications_router, prefix="/api/v2/notifications", tags=["v2-in-app-notifications"])`

This means full paths are `/api/v1/notifications/inbox`, etc. — distinct from the existing `/api/v1/notifications/log` (delivery log), `/api/v1/notifications/templates`, `/api/v1/notifications/settings`, and `/api/v2/admin/notifications` (platform notifications). No path collisions.

### 3.3 Schemas (Pydantic)

```python
class InboxItem(BaseModel):
    id: str
    category: str
    severity: str
    title: str
    body: str | None
    link_url: str | None
    entity_type: str | None
    entity_id: str | None
    metadata: dict[str, Any]
    created_at: str           # ISO 8601
    is_read: bool             # computed from notification_reads
    read_at: str | None

class InboxResponse(BaseModel):
    items: list[InboxItem]
    total: int
    unread_count: int

class UnreadCountResponse(BaseModel):
    count: int
```

Wrapped object response shape per `frontend-backend-contract-alignment.md` rules.

## 4. Wiring Existing Email Failure Sites

For every site listed in requirement 4.3.1, the change is the same shape: wrap the existing failure point so a notification is emitted before/instead-of letting the failure propagate silently. The behaviour at the user-facing API stays identical (still 500 on `send_quote` etc.), but a notification persists.

### 4.1 Sites that currently raise (`send_quote`, `email_invoice`, `send_customer_notification`, `send_receipt_email`, `send_vehicle_report`)

Pattern at the raise point:

```python
if used_provider is None:
    error_msg = f"All email providers failed. Last error: {last_error}"
    await create_in_app_notification(
        db, org_id=org_id,
        category="email_failure",
        severity="error",
        title=f"Failed to email {entity_kind} {entity_ref} to {recipient_email}",
        body=str(last_error)[:1500],
        link_url=f"/{entity_path}/{entity_id}",
        entity_type=entity_kind,
        entity_id=entity_id,
        audience_roles=["org_admin", "salesperson"],
        metadata={
            "recipient_email": recipient_email,
            "template_type": template_type,
            "error_message": str(last_error),
        },
    )
    raise ValueError(error_msg)
```

The existing `await log_email_sent(... status='failed' ...)` call (where present) stays — it's a separate concern (delivery audit). Where it's missing (quotes, invoices), this spec adds it for parity with the customer-notify pattern.

### 4.2 Sites that currently swallow (`bookings`, `auth`, `payments`, `landing`)

Pattern: insert the helper call where the warning log currently lives. The function still returns `False` / continues silently as before, but now the org_admin sees a notification.

```python
logger.warning("All email providers failed for booking confirmation. Last error: %s", last_error)
await create_in_app_notification(
    db, org_id=booking.org_id,
    category="email_failure",
    severity="error",
    title=f"Failed to email booking confirmation to {customer_email}",
    body=str(last_error)[:1500],
    link_url=f"/bookings/{booking.id}",
    entity_type="booking", entity_id=booking.id,
    audience_roles=["org_admin"],
    metadata={"recipient_email": customer_email, "template_type": "booking_confirmation",
              "error_message": str(last_error)},
)
return False
```

For auth flows (lockout/invite/verify/reset), the `db` session may not be the one that owns the org context. These use a fresh session pattern matching the existing payment-confirmation post-commit emails (per integration-credentials-architecture lessons and `record_cash_payment_endpoint` pattern). For these we accept best-effort logging only, not a notification — auth events go to the existing audit log and `error_log`. **Decision: skip auth send-failure notifications in v1.** Add to a future spec if needed. Document this as a known limitation in the rollout.

### 4.3 Quote stock-out fix

In `app/modules/quotes/service.py`, find the existing inserts that do:

```python
db.add(NotificationLog(
    org_id=..., channel="in_app",  # ← violates CHECK constraint
    template_type="stock_reorder_alert", ...
))
```

Replace with:

```python
await create_in_app_notification(
    db, org_id=...,
    category="stock_alert",
    severity="warning",
    title=f"Restock needed: {part_name} ({quote_number} accepted)",
    body=f"Quantity required: {qty_required}. On hand: {qty_available}.",
    audience_roles=["org_admin"],
    entity_type="quote", entity_id=quote_id,
    link_url=f"/inventory?search={part_sku}",
    metadata={"sku": part_sku, "qty_required": qty_required,
              "qty_available": qty_available, "quote_id": str(quote_id)},
)
```

This also fixes the latent CHECK-constraint violation noted during exploration.

## 5. Navigation & Access (Web)

### 5.1 Bell badge

Modify `frontend/src/layouts/OrgLayout.tsx`:
- Wrap the existing notification bell `<button>` in a relative container.
- Add a new component `<InboxBellBadge />` rendered inside, absolutely positioned top-right.
- Replace the `onClick={() => navigate('/notifications')}` with toggle of a new dropdown.

### 5.2 Routes

In `frontend/src/App.tsx`:
- New lazy import: `const InboxPage = lazy(() => import('./pages/notifications/InboxPage'))`
- New route under the OrgLayout block: `<Route path="/notifications/inbox" element={<InboxPage />} />`

The existing `/notifications` route (multi-tab Notifications settings page) is unchanged; it gains a new "Inbox" tab linking to `/notifications/inbox`. Or simpler — Inbox is its own page reachable from the bell. We will go with the bell-only entry point in v1; users can also nav to `/notifications/inbox` directly.

### 5.3 Route guard

`RequireAuth` only — accessible to all org-level roles. `RequireGlobalAdmin` is not used; global_admin gets routed away from org pages by existing redirects.

## 6. Frontend Component Tree (Web)

### 6.1 New components

```
frontend/src/components/notifications/
    InboxBellBadge.tsx       — small red badge component, polls /unread-count
    InboxBellDropdown.tsx    — popover with last 10 items + footer actions
    InboxItemCard.tsx        — single notification row (used in dropdown + page)
    InboxSeverityIcon.tsx    — icon by severity
    InboxCategoryLabel.tsx   — human label by category

frontend/src/pages/notifications/
    InboxPage.tsx            — full inbox screen
    useInbox.ts              — shared hook (list, mark-read, dismiss)
```

### 6.2 InboxBellBadge.tsx — behaviour

- On mount: `apiClient.get<{count:number}>('/notifications/inbox/unread-count', { signal })`
  - The web `apiClient` has `baseURL: '/api/v1'`, so this resolves to `/api/v1/notifications/inbox/unread-count`. The interceptor in `frontend/src/api/client.ts` only rewrites paths that start with `/api/`, so relative paths like `/notifications/inbox/unread-count` go through the v1 prefix as expected.
- Polls every 30s with `setInterval` cleared on unmount
- Refetches when window regains focus (`window.addEventListener('focus', ...)`)
- Returns null if `count === 0` so no badge renders

### 6.3 InboxBellDropdown.tsx — behaviour

- Toggles open on bell click, closes on outside-click (Headless UI `<Popover>`)
- On open, fetches `apiClient.get<InboxResponse>('/notifications/inbox?limit=10')`
- Shows spinner during initial load
- Each item:
  - Click → if `link_url`: `apiClient.post('/notifications/inbox/{id}/read')` then `navigate(link_url)`; if no link: just mark read
  - Severity icon on left, title, relative-time on right
- Footer: "Mark all as read" button + "View all" link to `/notifications/inbox`
- Empty state: "No new notifications"
- Reuses `safe-api-consumption.md` patterns: `res.data?.items ?? []`, AbortController, no `as any`

### 6.4 InboxPage.tsx — toolbar

```
┌────────────────────────────────────────────────────────────┐
│ Notifications                                              │
│ [ All ] [ Unread ]  [ Severity ▾ ]  [ Category ▾ ]         │
│                                  [ Mark all read ] [ Dismiss read ] │
├────────────────────────────────────────────────────────────┤
│ [ severity icon ] Title                          12m ago   │
│   Body preview (line-clamp-2)                              │
│   [ Dismiss ]                                              │
├────────────────────────────────────────────────────────────┤
│ ...                                                        │
├────────────────────────────────────────────────────────────┤
│           ◄  1  2  3  ►                                    │
└────────────────────────────────────────────────────────────┘
```

- Pagination: 25 items per page, classic prev/next + page numbers (existing `Pagination` UI component)
- Filters update URL via `urlPersist` like the existing `NotificationsPage` tabs
- Empty state per filter: "No matching notifications" / "You're all caught up"

### 6.5 Severity colour scheme

| Severity | Icon | Tailwind |
|---|---|---|
| info | `InformationCircleIcon` | `text-blue-500 bg-blue-50` |
| success | `CheckCircleIcon` | `text-green-500 bg-green-50` |
| warning | `ExclamationTriangleIcon` | `text-amber-500 bg-amber-50` |
| error | `XCircleIcon` | `text-red-500 bg-red-50` |

Dark-mode classes added to all (`dark:bg-...-900/30`, etc.).

### 6.6 User Workflow Trace

1. **Email failure path**:
   - `org_admin` clicks "Email" on a quote.
   - Backend `send_quote` raises ValueError → 500 → frontend toast "Failed to send quote".
   - Backend also wrote an `app_notifications` row before raising.
   - Within 30s, the org_admin's bell badge updates from `0` to `1`.
   - org_admin clicks bell → dropdown shows the failure.
   - org_admin clicks the item → navigated to quote detail; row marked read; badge back to `0`.
2. **Stock alert path**:
   - Customer accepts a quote via public link.
   - Backend `accept_quote_by_token` runs, detects out-of-stock, writes notification.
   - Next polling cycle, org_admin's bell shows `1`.
   - org_admin clicks → opens inventory page filtered to that SKU.
3. **Mark all read path**:
   - Bell shows `5`.
   - User opens dropdown → clicks "Mark all read" → POST → badge → `0`.
4. **Dismiss path**:
   - Inbox page → user clicks "Dismiss" on a row → row removed from list (optimistic) → POST `/dismiss`.

## 7. Frontend Mobile Components

### 7.1 New files

```
mobile/src/screens/notifications/
    NotificationsScreen.tsx      — list screen
    NotificationDetailScreen.tsx — body view if no deep-link route
mobile/src/components/notifications/
    NotificationListItem.tsx     — row component
mobile/src/api/inbox.ts          — typed wrapper over /api/v2/notifications/inbox
mobile/src/hooks/useInboxBadge.ts — polling hook
```

The mobile `apiClient` has `baseURL: '/api/v1'` on web and `https://devin.oraflow.co.nz/api/v1` on native. Same interceptor logic as web — a request to `/api/v2/notifications/inbox/unread-count` strips the baseURL and uses the absolute path. Mobile API calls SHALL use the absolute `/api/v2/...` path per the mobile-app steering rule.

### 7.2 More menu integration

In `mobile/src/screens/more/MoreMenuScreen.tsx`, add a tile:

```tsx
{ id: 'notifications', label: 'Notifications', icon: BellIcon,
  to: '/notifications', moduleSlug: '*',
  roles: ['owner', 'admin', 'salesperson'] }
```

`moduleSlug: '*'` per mobile-app.md = always visible.

### 7.3 Routes

`mobile/src/navigation/StackRoutes.tsx`:
- Lazy import `NotificationsScreen`
- Add route `<Route path="/notifications" element={<NotificationsScreen />} />`

### 7.4 Behaviour parity

- Pull-to-refresh re-fetches inbox.
- Tap row marks read; if `link_url` maps to existing route, navigate; otherwise show body in detail screen.
- Filter toolbar same as web (Unread toggle + severity chips), simplified for mobile width.
- 44×44 touch targets, dark mode, safe-area, AbortController per mobile steering.

### 7.5 Bell badge on mobile

Mobile doesn't have a persistent header bell (it has bottom tabs). Instead:
- The "More" tab in the bottom tab bar shows the unread badge.
- `useInboxBadge()` polls every 30s and powers the badge.
- Implementation in `mobile/src/navigation/BottomTabBar.tsx` (or wherever the More tab is rendered).

## 8. Toolbar / Action Bar Specification

### 8.1 InboxPage toolbar (web)

| Position | Control | Always visible? | States |
|---|---|---|---|
| Left | All / Unread segmented toggle | Yes | persists in URL `?unread=true` |
| Left | Severity dropdown | Yes | persists in URL `?severity=error` |
| Left | Category dropdown | Yes | persists in URL `?category=email_failure` |
| Right | Mark all read | When unread > 0 | disabled while in flight |
| Right | Dismiss read | When read > 0 | disabled while in flight |

### 8.2 Bell dropdown footer

- `Mark all as read` — left-aligned link
- `View all →` — right-aligned link to `/notifications/inbox`

## 9. List/Table Specification

### 9.1 Inbox list (web + mobile)

| Field | Web column | Mobile row |
|---|---|---|
| Severity icon | left, 24px | left, 24px |
| Title | bold primary | bold primary |
| Body | line-clamp-2, secondary | hidden (tap to expand on mobile) |
| Created at | right, relative time | small below title |
| Unread indicator | left dot, blue | left bar, blue |

Search: not in v1 (filters by category/severity are sufficient).
Sorting: always newest first.
Pagination: 25/page (web), infinite scroll (mobile).
Empty states:
- "You're all caught up." (no items)
- "No matching notifications." (with active filter)
Row actions:
- Click anywhere on row → mark read (+ navigate if link)
- Inline "Dismiss" button → confirm-less dismiss

## 10. Error & Edge Case UI

| Condition | UI |
|---|---|
| API 500 on list | Red banner "Failed to load notifications" + retry button |
| API 401 (logged out) | Bubble up to global auth handler — existing behaviour |
| API 403 (global_admin tries to GET /inbox) | The page is route-guarded so this shouldn't happen, but if it does, redirect to `/admin/dashboard` |
| API timeout on poll | Silent fail — keep last-known badge count |
| Loading | Spinner in dropdown / skeleton rows in page |
| Empty inbox | Friendly empty state |
| Clicking dismissed item from stale dropdown | Optimistic UI shows it gone; re-fetch confirms |

## 11. Integration Points with Existing UI

- **OrgLayout bell**: behaviour replaced (was navigate, now opens dropdown). Existing `NotificationBadge` (compliance docs) remains untouched on the sidebar nav item.
- **Notifications settings page** (`/notifications`) — unchanged; gains a small "View activity" link in the page header pointing to `/notifications/inbox` for discoverability.
- **Mobile More menu** — gains "Notifications" tile.
- **Mobile bottom tab bar** — More tab gains badge.

## 12. Security Considerations

Per `security-hardening-checklist.md`:

- **Access control**: every endpoint requires authenticated org user; `global_admin` rejected at router level. `user_id` and `role` come from `request.state` (JWT-derived), never from request body.
- **RLS**: both new tables RLS-enabled. Cross-org reads physically impossible.
- **Input validation**: `category` validated against allow-list in service; `severity` validated by Pydantic Literal; `link_url` enforced to be relative (must start with `/` and not contain `://`).
- **PII in body**: notification body MAY contain customer email addresses (e.g. "Failed to email INV-0042 to acme@example.com"). This is no different from invoice detail pages already exposing the same email.
- **Rate limiting**: the `/unread-count` endpoint is hit every 30s × N tabs × 2 (StrictMode). With dev limits at 0 (per ISSUE-021) and prod limits at 100/user/min, this is well within budget. No exception added.
- **Audit log**: notification creation is NOT audit-logged — too noisy. Mark-read/dismiss actions are NOT audit-logged either. Only notifications themselves serve as the historical record.
- **No SQL injection risk**: all queries are parameterised SQLAlchemy.

## 13. Performance

- `unread-count` query plan (single COUNT with NOT EXISTS subquery for read state). The audience filter on org-wide rows uses the JSONB `@>` containment operator, which is the standard pattern for JSONB arrays:
  ```sql
  SELECT COUNT(*) FROM app_notifications n
  WHERE n.org_id = $1
    AND (
      n.user_id = $2
      OR (n.user_id IS NULL
          AND n.audience_roles @> jsonb_build_array($3::text))
    )
    AND NOT EXISTS (
      SELECT 1 FROM notification_reads r
      WHERE r.notification_id = n.id
        AND r.user_id = $2
        AND (r.read_at IS NOT NULL OR r.dismissed_at IS NOT NULL)
    )
  ```
  Hits `idx_app_notifications_org_created` and `idx_notification_reads_user`. The JSONB containment scan over a small `audience_roles` array (1–3 strings) is essentially free; the filter is selective enough that the (org_id, created_at) btree drives the plan.
- List query is the same shape with ORDER BY + LIMIT/OFFSET.
- No N+1: per-user state is read in a single LEFT JOIN, not a per-row sub-query.

## 14. Testing Strategy

Per `feature-testing-workflow.md`:

- Unit tests in `tests/test_in_app_notifications.py` for service helpers (create, list, mark-read, dismiss, RLS isolation).
- Property test: dismiss is idempotent for any sequence of dismiss/mark-read pairs.
- E2E script `scripts/test_in_app_notifications_e2e.py`:
  - Create org A + org B with users.
  - Trigger an email failure (mock SMTP).
  - Assert org A admin sees one notification, org B sees zero.
  - Assert dismissing as user A1 doesn't affect user A2's badge.
  - Assert global_admin endpoint returns 403.
  - Cleanup all created data with `TEST_E2E_` prefix per the steering rule.
- Frontend: vitest tests for `InboxBellBadge`, `InboxBellDropdown`, `InboxPage` covering happy path, empty state, error state.
- Mobile: vitest tests for `NotificationsScreen` covering list render, mark read, dismiss.

## 15. Rollout Plan

1. Migration `0185` (down-revision `0184`) + models + service + endpoints + tests + HA publication membership (backend only). Deploy.
2. Wire stock-alert site (replaces broken CHECK-violating insert). Deploy.
3. Wire all email-failure sites that already raise (quotes, invoices, customers, vehicle reports). Deploy.
4. Wire email-failure sites that swallow (bookings, payments). Skip auth and landing per design §4.2. Deploy.
5. Web bell badge + dropdown. Deploy.
6. Web inbox page. Deploy.
7. Mobile More tile + screen + bottom-tab badge. Deploy.
8. Bump versions per `versioning-and-changelog.md` (MINOR — new feature). Add CHANGELOG entry.

Each step is independently deployable. Steps 2–4 are silent until the UI ships in step 5; users won't see anything broken in between.

## 16. Open Questions

- Q1: Should we extend audience to per-user `branch_id` (so branch-scoped events only notify branch staff)? **Decision: no in v1.** Add later if needed.
- Q2: Should `category=email_failure` notifications auto-dismiss after the user re-sends the email successfully? **Decision: no in v1.** Manual dismiss is fine; the spec stays simple.
- Q3: Do we want WebSocket push for instant updates? **Decision: no in v1.** 30s polling is sufficient. Future spec can add SSE without data-model changes.
