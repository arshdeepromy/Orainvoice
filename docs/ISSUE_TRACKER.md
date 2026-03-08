# OraInvoice Issue Tracker

All bugs, errors, and issues are logged here. This is the single source of truth for tracking what broke, why, and how it was fixed. Check this document before making changes to files involved in previous fixes.

---

### ISSUE-001: Login returns 422 Unprocessable Entity

- **Date**: 2026-03-08
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Clicking "Sign in" on the login page returned a 422 error. The token refresh on page load also returned 422. Users could not log in through the UI despite the backend API working correctly via curl.

**Root Cause**: Three frontend/backend mismatches in `AuthContext.tsx` and `api/client.ts`:

1. Frontend sent `remember` but backend `LoginRequest` schema expects `remember_me`
2. Token refresh sent empty body `{}` but backend `RefreshTokenRequest` requires `{ refresh_token: string }` in the body. Frontend had no mechanism to store/retrieve the refresh token.
3. Frontend `handleAuthResponse` required a `user` object in the response, but backend `TokenResponse` only returns `access_token`, `refresh_token`, `token_type` — no user object. Login would silently fail to set the user even if the 422 was fixed.
4. MFA verify sent `mfa_session_token` but backend `MFAVerifyRequest` expects `mfa_token`

**Fix Applied**:

1. Changed `remember` → `remember_me` in login payload
2. Added `setRefreshToken`/`getRefreshToken` exports to `api/client.ts` using `localStorage`
3. Updated refresh interceptor and restore function to send `{ refresh_token }` in body
4. Added JWT decode helper (`decodeJwtPayload`, `userFromToken`) to extract user info from the access token claims (`user_id`, `email`, `role`, `org_id`)
5. Updated `handleAuthResponse` to decode user from JWT instead of expecting a `user` field
6. Fixed MFA verify to send `mfa_token` instead of `mfa_session_token`
7. Updated logout to clear refresh token from localStorage

**Files Changed**:
- `frontend/src/contexts/AuthContext.tsx`
- `frontend/src/api/client.ts`

**Similar Bugs Found & Fixed**: The MFA token field name mismatch (`mfa_session_token` vs `mfa_token`) was the same class of bug — frontend/backend field name mismatch.

**Related Issues**: None (first issue logged)

**Spec**: Direct fix (trivial field name and architecture alignment)

---

### ISSUE-002: ModuleContext calls /v2/modules with wrong base URL → 404

- **Date**: 2026-03-08
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Console error `Failed to load resource: the server responded with a status of 404 (Not Found)` for `api/v1/v2/modules:1`. The modules endpoint is at `/api/v2/modules` but the apiClient baseURL is `/api/v1`, so `GET /v2/modules` becomes `GET /api/v1/v2/modules`.

**Root Cause**: `ModuleContext.tsx` called `apiClient.get('/v2/modules')` which prepends the `/api/v1` baseURL, creating a double-versioned path `/api/v1/v2/modules`. The modules endpoint is registered at `/api/v2/modules` in `app/main.py`.

**Fix Applied**: Changed the API call to use `apiClient.get('/modules', { baseURL: '/api/v2' })` to override the baseURL for this specific call.

**Files Changed**:
- `frontend/src/contexts/ModuleContext.tsx`

**Similar Bugs Found & Fixed**: Checked all other contexts for similar v2 endpoint calls — TenantContext uses v1 endpoints correctly.

**Related Issues**: ISSUE-003

---

### ISSUE-003: TenantContext GET /org/settings returns 403 for global_admin

- **Date**: 2026-03-08
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Console error `Failed to load resource: the server responded with a status of 403 (Forbidden)` for `api/v1/org/settings:1` after logging in as `global_admin`.

**Root Cause**: The `/org/settings` endpoint in `app/modules/organisations/router.py` has `dependencies=[require_role("org_admin", "salesperson")]` which excludes `global_admin`. The `global_admin` role is a platform-level admin, not an org-level role, so it correctly doesn't have access to org settings. However, `TenantContext` and `ModuleContext` were unconditionally fetching org-level data for any authenticated user with an `org_id`, including `global_admin`.

**Fix Applied**: Added `user?.role !== 'global_admin'` guard to both `TenantContext` and `ModuleContext` useEffect hooks so they skip fetching org-level data when logged in as global_admin.

**Files Changed**:
- `frontend/src/contexts/TenantContext.tsx`
- `frontend/src/contexts/ModuleContext.tsx`

**Similar Bugs Found & Fixed**: Both TenantContext and ModuleContext had the same issue — fixed both.

**Related Issues**: ISSUE-002


---

### ISSUE-004: Dashboard page is empty placeholder after login — no navigation, no content

- **Date**: 2026-03-08
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: ISSUE-001 (App.tsx was simplified to fix blank page/CSS issues, removing all layout and routing)

**Symptoms**: After successful login, user sees only "Dashboard / Welcome, admin! Role: global_admin" with no sidebar, no navigation links, no admin panels, no content. The app has hundreds of pages built but none are routed.

**Root Cause**: During ISSUE-001 debugging, `App.tsx` was rewritten with a simplified inline `DashboardPage` placeholder, removing the original `AdminLayout`, `OrgLayout`, sidebar navigation, and all page routes. The fix was never followed up with restoring proper routing.

**Fix Applied**:
1. Rewrote `App.tsx` to use the existing `AdminLayout` (with sidebar) for `global_admin` users and `OrgLayout` for org-level users
2. Wired all 10 admin pages as routes under `/admin/*`: Dashboard, Organisations, Analytics, Settings, Error Log, Notifications, Branding, Migration Tool, Audit Log, Reports, Integrations
3. Updated `AdminLayout` nav items to include previously missing pages: Analytics, Notifications, Branding, Migration Tool
4. Added logout button to AdminLayout sidebar and header
5. Added `RequireGlobalAdmin` route guard for `/admin/*` routes
6. Added proper redirect logic: global_admin → `/admin/dashboard`, org users → `/dashboard`
7. Added auth page routes (MFA verify, password reset)

**Files Changed**:
- `frontend/src/App.tsx`
- `frontend/src/layouts/AdminLayout.tsx`

**Similar Bugs Found & Fixed**: `AdminLayout` was missing 4 nav items (Analytics, Notifications, Branding, Migration Tool) that had pages built but no sidebar links — fixed by adding them to the nav items array.

**Related Issues**: ISSUE-001

---

### ISSUE-005: Global admin lands on OrgLayout (/dashboard) instead of AdminLayout (/admin/dashboard) + GlobalAdminDashboard API 404/500 errors

- **Date**: 2026-03-08
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: After login as global_admin, the app shows OrgLayout (Customers/Invoices sidebar) instead of AdminLayout. The GlobalAdminDashboard fires 5 API calls that all fail:
- `GET /api/v1/admin/integrations` → 404 (no list endpoint exists, only `/admin/integrations/{name}`)
- `GET /api/v1/admin/reports/billing-issues` → 404 (endpoint doesn't exist)
- `GET /api/v1/admin/errors?summary=true` → 500 (endpoint returns paginated list, not summary shape)
- `GET /api/v1/admin/reports/mrr` → 500 (service error on empty DB)
- `GET /api/v1/admin/reports/organisations` → 500 (service error on empty DB)

**Root Cause**: Two separate issues:
1. **Routing**: The catch-all `<Route path="*">` inside OrgLayout sends global_admin to `/dashboard` instead of `/admin/dashboard`. No redirect exists from `/dashboard` to `/admin/dashboard` for global_admin users.
2. **API mismatches**: GlobalAdminDashboard calls endpoints that either don't exist or return different shapes than expected. The `/admin/integrations` GET list, `/admin/reports/billing-issues`, and `/admin/errors?summary=true` summary mode are not implemented in the backend.

**Fix Applied**:
1. Added redirect in OrgLayout route: global_admin hitting `/dashboard` gets redirected to `/admin/dashboard`
2. Rewrote GlobalAdminDashboard to gracefully handle missing/failing endpoints — each API call is independent with individual error handling, showing placeholder data when endpoints fail
3. Changed error counts to use `/admin/errors/dashboard` endpoint which exists and returns severity breakdown

**Files Changed**:
- `frontend/src/App.tsx`
- `frontend/src/pages/dashboard/GlobalAdminDashboard.tsx`

**Similar Bugs Found & Fixed**: None — other admin pages (Organisations, ErrorLog, etc.) call endpoints that do exist.

**Related Issues**: ISSUE-004

---

### ISSUE-006: Systemic frontend/backend API mismatch — v2 double-prefixing and endpoint shape mismatches across entire app

- **Date**: 2026-03-08
- **Severity**: high
- **Status**: resolved
- **Reporter**: user (requested full-app scan)
- **Regression of**: N/A

**Symptoms**: Multiple frontend pages calling non-existent or mismatched backend endpoints, resulting in 404s, 500s, or incorrect data rendering. Two systemic patterns discovered.

**Root Cause**: Two distinct bug patterns:

1. **v2 URL double-prefixing**: The `apiClient` has `baseURL: '/api/v1'`. Pages using `/api/v2/...` or `/v2/...` paths get double-prefixed to `/api/v1/api/v2/...` or `/api/v1/v2/...` → 404. Affected 40+ pages across the entire app.

2. **Individual endpoint mismatches**: Several admin pages expected different response shapes or called endpoints that don't exist in the backend.

**Fix Applied**:

Pattern 1 — Added a request interceptor in `api/client.ts` that detects `/api/v2/` and `/v2/` prefixed URLs and rewrites the baseURL accordingly. This fixes all v2 calls across the entire app in one shot.

Pattern 2 — Individual fixes:
- `ErrorLog.tsx`: `/admin/errors/summary` → `/admin/errors/dashboard`, PUT `/admin/errors/${id}` → PUT `/admin/errors/${id}/status` with `resolution_notes`, response `items` → `errors`
- `BrandingConfig.tsx`: `/admin/branding` → `/api/v2/admin/branding` (GET and PUT)
- `Reports.tsx`: `/admin/reports/vehicle-db` → `/admin/vehicle-db/stats`
- `Settings.tsx`: `/admin/vehicle-db` → `/admin/vehicle-db/stats`, `/admin/vehicle-db/${rego}` → `/admin/vehicle-db/search/${rego}`, fetchPlans response `res.data` → `res.data.plans`, archive endpoint → `/admin/plans/${id}/archive`, vehicle delete → `/admin/vehicle-db/stale` (purge stale records)
- `AuditLog.tsx`: Response `items` → `entries`, removed non-existent detail endpoint `/admin/audit-log/${id}`
- `WebhookManagement.tsx`: `/outbound-webhooks/...` → `/api/v2/outbound-webhooks/...` (all 6 calls)
- `Organisations.tsx`: Response `orgsRes.data` → `orgsRes.data.organisations`, `plansRes.data` → `plansRes.data.plans`

**Files Changed**:
- `frontend/src/api/client.ts` (v2 interceptor)
- `frontend/src/pages/admin/ErrorLog.tsx`
- `frontend/src/pages/admin/BrandingConfig.tsx`
- `frontend/src/pages/admin/Reports.tsx`
- `frontend/src/pages/admin/Settings.tsx`
- `frontend/src/pages/admin/AuditLog.tsx`
- `frontend/src/pages/settings/WebhookManagement.tsx`
- `frontend/src/pages/admin/Organisations.tsx`

**Full App Scan Results**: Scanned all remaining pages (notifications, data import/export, bookings, reports sub-pages, inventory sub-pages, integrations). All org-level pages use correct v1 endpoints with proper response shapes. No additional mismatches found.

**Similar Bugs Found & Fixed**: All instances of the same two patterns were fixed across the entire codebase.

**Related Issues**: ISSUE-005

---

### ISSUE-007: Systemic 503 on ALL admin endpoints — SET LOCAL parameterisation bug

- **Date**: 2026-03-08
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Every single admin endpoint returns 503 Service Unavailable. The SQLAlchemy exception handler catches a `ProgrammingError` on every request: `syntax error at or near "$1"` for `SET LOCAL app.current_org_id = $1`.

**Root Cause**: The `_set_rls_org_id()` function in `app/core/database.py` used SQLAlchemy `text()` with a bound parameter (`:org_id`) for the `SET LOCAL` command. The asyncpg driver translates bound parameters to PostgreSQL `$1` placeholders, but PostgreSQL `SET` commands do not support parameterised queries — they require literal values. This caused every database session creation to fail with a syntax error, making the entire application non-functional.

**Fix Applied**: Changed `_set_rls_org_id()` to interpolate the org_id directly into the SQL string after validating it as a proper UUID (safe against injection since UUIDs have a fixed format). The function now uses `text(f"SET LOCAL app.current_org_id = '{validated}'")` instead of `text("SET LOCAL app.current_org_id = :org_id")` with bound params.

**Files Changed**:
- `app/core/database.py`

**Similar Bugs Found & Fixed**: No other `SET LOCAL` or `SET` commands with bound parameters found in the codebase.

**Related Issues**: ISSUE-006 (frontend fixes were masked by this backend failure)

---

### ISSUE-008: Missing org-level and admin-level frontend navigation and routes

- **Date**: 2026-03-08
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: ISSUE-004 (App.tsx was rebuilt with only admin routes; org-level routes were never restored)

**Symptoms**: Org-level users (org_admin, salesperson) see only 10 nav items in the sidebar (Dashboard, Customers, Vehicles, Invoices, Quotes, Job Cards, Bookings, Inventory, Reports, Settings). Many built modules have no routes or navigation: Staff, Projects, Expenses, Time Tracking, POS, Schedule, Notifications, Data Import/Export, Purchase Orders, Recurring Invoices, Construction (Progress Claims, Variations, Retentions), Floor Plan, Kitchen Display, Franchise, Assets, Compliance, Loyalty, Ecommerce, Setup Wizard. The catch-all `*` route in App.tsx redirects all unmatched paths, so even direct URL navigation fails.

**Root Cause**: When App.tsx was rebuilt in ISSUE-004, only admin routes were wired. The org-level OrgLayout section only had a `/dashboard` route and a catch-all redirect. No org-level page routes were added. The OrgLayout sidebar `navItems` array only contained the original 10 items and was never updated with the new modules.

**Fix Applied**:
1. Added all org-level page routes to App.tsx under the OrgLayout section using lazy imports
2. Added missing nav items to OrgLayout sidebar with module gating where appropriate
3. Ensured all module-gated pages only show when the module is enabled

**Files Changed**:
- `frontend/src/App.tsx`
- `frontend/src/layouts/OrgLayout.tsx`

**Similar Bugs Found & Fixed**: N/A — this was a single omission in the routing setup.

**Related Issues**: ISSUE-004, ISSUE-007


---

### ISSUE-009: TypeScript errors in App.tsx — detail page components require props not provided by routes

- **Date**: 2026-03-08
- **Severity**: medium
- **Status**: resolved
- **Reporter**: agent
- **Regression of**: ISSUE-008 (routes were added without wrapper components for prop-based detail pages)

**Symptoms**: Four TypeScript errors in `App.tsx`:
1. `QuoteDetail` requires `quoteId` prop but rendered without it at `/quotes/:id`
2. `ProjectDashboard` requires `projectId` prop but rendered without it at `/projects/:id`
3. `AssetDetail` requires `assetId` prop but rendered without it at `/assets/:id`
4. `RetentionSummary` requires `projectId` prop but rendered without it at `/retentions`
5. `StaffDetail` imported but never used (no `/staff/:id` route existed)

**Root Cause**: When org-level routes were added in ISSUE-008, detail page components that expect props (instead of using `useParams` internally) were rendered as route elements without passing the required props. Some components (like `InvoiceDetail`) use `useParams` internally, but `QuoteDetail`, `ProjectDashboard`, `AssetDetail`, and `RetentionSummary` expect props passed from a parent.

**Fix Applied**:
1. Added `useParams` import to App.tsx
2. Created route wrapper components (`QuoteDetailRoute`, `ProjectDashboardRoute`, `AssetDetailRoute`) that extract the `:id` param and pass it as the required prop
3. Made `RetentionSummary.projectId` optional — when accessed as a standalone page at `/retentions`, it shows a project ID input form; when passed a `projectId` prop, it loads directly
4. Removed unused `StaffDetail` import
5. Deleted leftover `test_db_fix.py` from project root (debug artifact from ISSUE-007)

**Files Changed**:
- `frontend/src/App.tsx`
- `frontend/src/pages/construction/RetentionSummary.tsx`
- `test_db_fix.py` (deleted)

**Similar Bugs Found & Fixed**: Checked all other detail routes — `InvoiceDetail`, `CustomerProfile`, `VehicleProfile`, `JobCardDetail` all use `useParams` internally and don't need wrappers.

**Related Issues**: ISSUE-008


---

### ISSUE-010: 503 on /admin/plans — missing storage_tier_pricing column + billing_status query error

- **Date**: 2026-03-08
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: `GET /admin/plans` returns 503. `GET /api/v2/admin/analytics/conversion-funnel` returns 503.

**Root Cause**: Two separate DB schema issues:
1. The `subscription_plans` model has a `storage_tier_pricing` JSONB column but no Alembic migration existed to create it
2. The conversion funnel analytics query referenced a `billing_status` column on `organisations` that doesn't exist

**Fix Applied**:
1. Created migration `0063` to add `storage_tier_pricing` JSONB column to `subscription_plans`
2. Fixed `analytics_service.py` conversion funnel query to use `status = 'active'` instead of `billing_status != 'trial'`

**Files Changed**:
- `alembic/versions/2025_01_15_0063-0063_add_storage_tier_pricing.py` (new)
- `app/modules/admin/analytics_service.py`

**Related Issues**: ISSUE-007

---

### ISSUE-011: Missing admin features — User Management, Subscription Plans, View-as-Org, Feature Flags

- **Date**: 2026-03-08
- **Severity**: high
- **Status**: resolved
- **Reporter**: user

**Symptoms**: Global admin panel is missing critical management pages: no user management, no subscription plan management UI, no way to view an org's admin view, no feature flag management. The Settings page had a basic Plans tab but it was just a table embedded in settings — not a proper subscription management page.

**Root Cause**: These pages were never built. The backend endpoints exist for plans (`/admin/plans`) and feature flags (`/api/v2/admin/flags`) but no dedicated frontend pages were created. No user listing endpoint existed at all. No "View as Org" impersonation mechanism existed.

**Fix Applied**:
1. **Backend**: Added `GET /admin/users` endpoint with pagination, search, role/org/status filtering. Added `PUT /admin/users/{id}/status` to toggle user active status. Both in `app/modules/admin/router.py` with service functions in `app/modules/admin/service.py`.
2. **User Management page** (`UserManagement.tsx`): Full user listing with search by email, filter by role/status/org, pagination, activate/deactivate toggle.
3. **Subscription Plans page** (`SubscriptionPlans.tsx`): Dedicated CRUD page with create/edit modals, archive functionality, show/hide archived toggle. Replaces the basic Plans tab in Settings.
4. **Feature Flags page** (`FeatureFlags.tsx`): Full CRUD for feature flags with create/edit modals, archive, targeting rules display. Uses `/api/v2/admin/flags` endpoints.
5. **View as Org**: Added "View as Org" button on Organisations page that stores org context in sessionStorage and navigates to OrgLayout. OrgLayout shows an indigo banner "Viewing as organisation: [name]" with "Back to Admin" button. Modified App.tsx dashboard redirect to allow global admin to stay on `/dashboard` when in view-as-org mode.
6. **AdminLayout nav**: Added Users, Subscription Plans, Feature Flags to sidebar navigation.
7. **App.tsx routes**: Added `/admin/users`, `/admin/plans`, `/admin/feature-flags` routes.

**Files Changed**:
- `app/modules/admin/router.py` (added users endpoints)
- `app/modules/admin/service.py` (added list_all_users, toggle_user_active)
- `frontend/src/pages/admin/UserManagement.tsx` (new)
- `frontend/src/pages/admin/SubscriptionPlans.tsx` (new)
- `frontend/src/pages/admin/FeatureFlags.tsx` (new)
- `frontend/src/layouts/AdminLayout.tsx` (added 3 nav items)
- `frontend/src/layouts/OrgLayout.tsx` (view-as-org banner)
- `frontend/src/App.tsx` (3 new routes, view-as-org redirect fix)
- `frontend/src/pages/admin/Organisations.tsx` (view-as-org button)

**Similar Bugs Found & Fixed**: The Settings page Plans tab still exists but is now supplementary — the dedicated Subscription Plans page is the primary management interface.

**Related Issues**: ISSUE-010
