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


---

### ISSUE-012: ModuleContext - modules.filter is not a function

- **Date**: 2026-03-09
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: When logging in as org user, console error: `modules.filter is not a function. (In 'modules.filter((m) => m.is_enabled)', 'modules.filter' is undefined)`. App crashes with white screen.

**Root Cause**: API returns `{ modules: [...], total: number }` but frontend expected the array directly as `res.data`. The `ModuleContext` was trying to call `.filter()` on the response object instead of the array.

**Fix Applied**:
1. Updated `fetchModules` to access `res.data.modules` instead of `res.data`
2. Added safety check: `(modules || []).filter(...)` in useMemo
3. Added fallback to empty array on error
4. Added AbortController for race condition protection

**Files Changed**:
- `frontend/src/contexts/ModuleContext.tsx`

**Similar Bugs Found & Fixed**: Same pattern exists in InvoiceList (ISSUE-013) and RevenueSummary (ISSUE-015)

**Related Issues**: ISSUE-002, ISSUE-013

---

### ISSUE-013: InvoiceList - data.items is undefined

- **Date**: 2026-03-09
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: When navigating to Invoices page, console error: `undefined is not an object (evaluating 'data.items.length')`. App crashes with white screen.

**Root Cause**: Accessing `data.items` when `data` is null or API returns error. No safety checks before accessing nested properties.

**Fix Applied**:
1. Added safety check in `toggleSelectAll`: `if (!data || !data.items) return`
2. Added safety check in `allSelected`: `data && data.items ? ...`
3. Added safety check in table rendering: `!data || !data.items || data.items.length === 0`
4. Added fallback data structure on API error
5. Validated response structure before setting data

**Files Changed**:
- `frontend/src/pages/invoices/InvoiceList.tsx`

**Similar Bugs Found & Fixed**: Same pattern in ModuleContext (ISSUE-012) and RevenueSummary (ISSUE-015)

**Related Issues**: ISSUE-012, ISSUE-015

---

### ISSUE-014: Race conditions in context providers causing duplicate API calls

- **Date**: 2026-03-09
- **Severity**: high
- **Status**: resolved
- **Reporter**: agent (proactive scan)
- **Regression of**: N/A

**Symptoms**: React Strict Mode causing 8+ duplicate API calls on login (4 contexts × 2 mounts). Rate limit 429 errors. Potential stale data from first request completing after second.

**Root Cause**: 4 out of 5 contexts had no cleanup for API calls in useEffect. React Strict Mode (development) double-mounts components, causing duplicate requests without proper abort handling.

**Fix Applied**: Added AbortController cleanup to all context fetch functions:
1. Added `signal` parameter to fetch functions
2. Created AbortController in useEffect
3. Return cleanup function that aborts request
4. Ignore CanceledError in catch blocks

**Files Changed**:
- `frontend/src/contexts/FeatureFlagContext.tsx`
- `frontend/src/contexts/ModuleContext.tsx`
- `frontend/src/contexts/TerminologyContext.tsx`
- `frontend/src/contexts/TenantContext.tsx`

**Similar Bugs Found & Fixed**: AuthContext already had protection using `cancelled` flag pattern - no change needed.

**Related Issues**: ISSUE-012, ISSUE-013

---

### ISSUE-015: RevenueSummary - data.monthly_breakdown is undefined

- **Date**: 2026-03-09
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: When clicking Reports page, console error: `undefined is not an object (evaluating 'data.monthly_breakdown.map')`. App crashes with white screen.

**Root Cause**: Accessing `data.monthly_breakdown` without checking if it exists. API may return null/undefined for this field when no data available.

**Fix Applied**: Added safety check before mapping: `data.monthly_breakdown && data.monthly_breakdown.length > 0 ? ... : placeholder`

**Files Changed**:
- `frontend/src/pages/reports/RevenueSummary.tsx`

**Similar Bugs Found & Fixed**: Same pattern in ModuleContext (ISSUE-012) and InvoiceList (ISSUE-013)

**Related Issues**: ISSUE-012, ISSUE-013

---

### ISSUE-016: Rate limiting too strict for development with React Strict Mode

- **Date**: 2026-03-09
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: 429 Too Many Requests errors when logging in as org user. Multiple endpoints hitting rate limits.

**Root Cause**: React Strict Mode doubles all requests in development. Rate limits were set for production (100 req/min per user) which is too low for development with double-mounting.

**Fix Applied**: Increased development rate limits 5x:
- `RATE_LIMIT_PER_USER_PER_MINUTE`: 100 → 500
- `RATE_LIMIT_PER_ORG_PER_MINUTE`: 1000 → 5000
- `RATE_LIMIT_AUTH_PER_IP_PER_MINUTE`: 100 → 500

**Files Changed**:
- `.env`

**Similar Bugs Found & Fixed**: N/A - single configuration change

**Related Issues**: ISSUE-014 (race conditions were contributing to excessive requests)

**Note**: Production should use lower limits (100-200 per user, 1000-2000 per org)

---

### ISSUE-017: Undefined data access in report pages - missing null checks on fmt() and .map() calls

- **Date**: 2026-03-09
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Multiple report pages crash with errors like:
- `undefined is not an object (evaluating 'v.toLocaleString')` in CarjamUsage.tsx
- `undefined is not an object (evaluating 'data.monthly_breakdown.map')` in RevenueSummary.tsx

**Root Cause**: Systemic pattern across 14+ report files:
1. `fmt()` functions call `.toLocaleString()` on potentially undefined values without null checks
2. `.map()` calls on data arrays without checking if the array exists first
3. API may return null/undefined for fields when no data is available

**Fix Applied**: Added safety checks to all report files:
1. Updated `fmt()` functions to handle undefined: `const fmt = (v: number | undefined) => v != null ? v.toLocaleString(...) : '0.00'` (or '$0.00' for currency)
2. Added null checks before all `.map()` calls: `data.array && data.array.length > 0 ? ... : placeholder`
3. Added fallback rendering for empty data states

**Files Changed**:
- `frontend/src/pages/reports/CarjamUsage.tsx`
- `frontend/src/pages/reports/RevenueSummary.tsx` (already fixed in ISSUE-015)
- `frontend/src/pages/reports/GstReturnSummary.tsx`
- `frontend/src/pages/reports/TopServices.tsx`
- `frontend/src/pages/reports/JobReport.tsx`
- `frontend/src/pages/reports/OutstandingInvoices.tsx`
- `frontend/src/pages/reports/FleetReport.tsx`
- `frontend/src/pages/reports/InventoryReport.tsx`
- `frontend/src/pages/reports/InvoiceStatus.tsx`
- `frontend/src/pages/reports/TaxReturnReport.tsx`
- `frontend/src/pages/reports/ProjectReport.tsx`
- `frontend/src/pages/reports/POSReport.tsx`
- `frontend/src/pages/reports/CustomerStatement.tsx`
- `frontend/src/pages/reports/SmsUsage.tsx`
- `frontend/src/pages/reports/HospitalityReport.tsx`
- `frontend/src/pages/reports/StorageUsage.tsx`

**Similar Bugs Found & Fixed**: Same pattern in ModuleContext (ISSUE-012), InvoiceList (ISSUE-013), and RevenueSummary (ISSUE-015)

**Related Issues**: ISSUE-012, ISSUE-013, ISSUE-015

---

### ISSUE-018: BranchManagement - branches.find is not a function

- **Date**: 2026-03-09
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: When navigating to Branch Management settings page, console error: `branches.find is not a function. (In 'branches.find((b) => b.id === assignBranchId)', 'branches.find' is undefined)`. App crashes with white screen.

**Root Cause**: Same pattern as ISSUE-012, ISSUE-013, ISSUE-017 - calling array methods on potentially non-array data. API may return `{ branches: [...], total: number }` but frontend expected array directly, or branches was null/undefined when API failed.

**Fix Applied**: Added safety checks to settings pages:
1. Handle both array and wrapped response formats: `Array.isArray(res.data) ? res.data : (res.data?.branches || [])`
2. Set empty array fallback on error to prevent undefined state
3. Added null check before .find() operation: `assignBranchId ? branches.find(...) : null`

**Files Changed**:
- `frontend/src/pages/settings/BranchManagement.tsx`
- `frontend/src/pages/settings/UserManagement.tsx`
- `frontend/src/pages/settings/WebhookManagement.tsx`

**Similar Bugs Found & Fixed**: Same pattern in UserManagement (/org/users) and WebhookManagement (/api/v2/outbound-webhooks). ModuleConfiguration already had proper handling.

**Related Issues**: ISSUE-012, ISSUE-013, ISSUE-015, ISSUE-017

---

### ISSUE-019: Billing page - undefined is not an object (evaluating 'billing.storage.used_bytes')

- **Date**: 2026-03-09
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: When navigating to Billing settings page, console error: `undefined is not an object (evaluating 'billing.storage.used_bytes')`. App crashes with white screen.

**Root Cause**: Same pattern as ISSUE-012, ISSUE-013, ISSUE-017, ISSUE-018 - accessing nested properties without null checks. The `billing` object had optional nested properties (`storage`, `carjam`, `estimated_next_invoice`, `storage_addon_price_per_gb`) that could be undefined when API returns incomplete data.

**Fix Applied**:
1. Made nested properties optional in BillingData interface (plan, storage, carjam, estimated_next_invoice, storage_addon_price_per_gb)
2. Added conditional rendering for StorageUsage and CarjamUsage components
3. Added null check in NextBillEstimate component with fallback UI
4. Added null check in CurrentPlanCard component with fallback UI
5. Added default value handling in StorageAddonModal for pricePerGb
6. Added array handling for invoices response (both array and wrapped formats)
7. Added error fallback to set empty array for invoices

**Files Changed**:
- `frontend/src/pages/settings/Billing.tsx`

**Similar Bugs Found & Fixed**: All nested property accesses in Billing page now have proper null checks and fallback UI.

**Related Issues**: ISSUE-012, ISSUE-013, ISSUE-015, ISSUE-017, ISSUE-018

---

### ISSUE-020: Systemic nested property access without null checks across org pages

- **Date**: 2026-03-09
- **Severity**: high
- **Status**: resolved
- **Reporter**: agent (proactive scan per steering docs)
- **Regression of**: N/A

**Symptoms**: Multiple pages crash with "undefined is not an object" errors when accessing nested properties like `data.property.nested_property` without checking if intermediate properties exist.

**Root Cause**: Same pattern as ISSUE-019 - accessing nested object properties without null checks. When API returns incomplete data or properties are optional, accessing nested properties directly causes crashes.

**Fix Applied**:
1. Made all nested properties optional in interface definitions
2. Added null checks before accessing nested properties using optional chaining (`?.`) or explicit checks
3. Added conditional rendering for components that use nested data
4. Added fallback values where appropriate (e.g., `|| 0`, `|| []`)

**Files Changed**:
- `frontend/src/pages/dashboard/OrgAdminDashboard.tsx` - Fixed storage, revenue_summary, system_alerts, activity_feed access
- `frontend/src/pages/dashboard/GlobalAdminDashboard.tsx` - Fixed error_counts, integration_health, billing_issues access
- `frontend/src/pages/settings/Billing.tsx` - Fixed plan, storage, carjam, estimated_next_invoice access (ISSUE-019)

**Similar Bugs Found & Fixed**: All dashboard pages and Billing page now have comprehensive null checks for nested properties.

**Related Issues**: ISSUE-012, ISSUE-013, ISSUE-015, ISSUE-017, ISSUE-018, ISSUE-019


---

### ISSUE-021: Rate limiting causing 429 errors on login in development mode

- **Date**: 2026-03-09
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: ISSUE-016 (rate limits were increased but still too restrictive for development)

**Symptoms**: User getting 429 (Too Many Requests) errors when trying to login. Unable to access the application in development mode.

**Root Cause**: Rate limiting was still enabled in development mode. While ISSUE-016 increased the limits from 100 to 500 req/min, this is still too restrictive for development where:
1. React Strict Mode doubles all requests
2. Multiple contexts fetch data on mount
3. Developers frequently refresh pages and test flows
4. No rate limiting should exist in development mode at all

**Fix Applied**:
1. Set all rate limits to 0 in `.env` to completely disable rate limiting:
   - `RATE_LIMIT_PER_USER_PER_MINUTE=0`
   - `RATE_LIMIT_PER_ORG_PER_MINUTE=0`
   - `RATE_LIMIT_AUTH_PER_IP_PER_MINUTE=0`

2. Updated `app/middleware/rate_limit.py` to skip rate limiting when limit <= 0:
   - Added check at start of `_check_rate_limit()`: `if limit <= 0: return True, 0`
   - This allows development mode to have zero rate limiting while production can set appropriate limits

**Files Changed**:
- `.env` - Set all rate limits to 0
- `app/middleware/rate_limit.py` - Added limit <= 0 check to disable rate limiting

**Backend Restart Required**: The backend must be restarted for the `.env` changes to take effect:
```bash
docker-compose restart app
```

**Similar Bugs Found & Fixed**: N/A - single configuration change

**Related Issues**: ISSUE-016 (previous rate limit adjustment)

**Production Note**: Production environments should set appropriate rate limits (e.g., 100-200 per user, 1000-2000 per org, 10-20 for auth endpoints)


---

### ISSUE-022: OrgAdminDashboard API mismatch - calling wrong endpoints with wrong data structure

- **Date**: 2026-03-09
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Dashboard shows "Failed to load dashboard data" error. No data displayed on org user dashboard.

**Root Cause**: The OrgAdminDashboard component was calling the correct report endpoints but expecting the wrong data structure:

1. `/reports/revenue` returns `RevenueSummaryResponse` with fields like `total_revenue`, `total_inclusive`, `invoice_count` but dashboard expected `current_period`, `previous_period`, `change_percent`
2. `/reports/outstanding` returns `OutstandingInvoicesResponse` with `total_outstanding` and `count` but dashboard expected `total` and `overdue_count`
3. `/reports/storage` returns `StorageUsageResponse` with `storage_used_bytes` and `storage_quota_bytes` but dashboard expected `used_bytes` and `quota_gb`
4. Dashboard was calling non-existent `/reports/activity` endpoint

**Fix Applied**:
1. Updated `OrgAdminData` interface to match actual API response schemas from backend
2. Removed call to non-existent `/reports/activity` endpoint
3. Updated data access to use correct field names:
   - `total_inclusive` instead of `current_period`
   - `total_outstanding` instead of `total`
   - `storage_used_bytes` / `storage_quota_bytes` instead of `used_bytes` / `quota_gb`
4. Removed change percentage display (not provided by API)
5. Added outstanding invoices table showing top 10 invoices with overdue highlighting
6. Added storage alert banner when usage is high
7. Calculate overdue count from outstanding invoices array
8. Added error logging to console for debugging
9. Removed unused ActivityItem and SystemAlert interfaces
10. Removed unused Badge import

**Files Changed**:
- `frontend/src/pages/dashboard/OrgAdminDashboard.tsx`

**Similar Bugs Found & Fixed**: N/A - dashboard-specific issue

**Related Issues**: ISSUE-005 (GlobalAdminDashboard had similar API mismatch issues)

**Backend Endpoints Used**:
- `GET /reports/revenue` - Returns RevenueSummaryResponse
- `GET /reports/outstanding` - Returns OutstandingInvoicesResponse with invoices array
- `GET /reports/storage` - Returns StorageUsageResponse



---

### ISSUE-023: Accounting integrations page - missing backend endpoint

- **Date**: 2026-03-09
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Accounting settings page showing "We couldn't load your accounting integration settings" error. Frontend unable to load accounting data.

**Root Cause**: Frontend was calling `/org/integrations/accounting` but the backend accounting router is mounted at `/org/accounting`. Additionally, the frontend expected a single consolidated endpoint returning `{ xero: {...}, myob: {...}, sync_log: [...] }` but the backend only had separate endpoints for `/connections` and `/sync-log`.

**Fix Applied**:

1. **Backend** - Created new consolidated dashboard endpoint:
   - Added `GET /org/accounting/` endpoint that returns AccountingDashboardResponse
   - Added AccountingDashboardResponse, AccountingConnectionDetail, SyncLogEntryDashboard schemas
   - Updated `_connection_to_dict()` to include account_name, sync_status, error_message (placeholder values for now)
   - Added `POST /org/accounting/sync/{entry_id}/retry` endpoint for retrying individual sync entries
   - Dashboard endpoint combines data from list_connections() and get_sync_log()

2. **Frontend** - Updated API endpoint paths:
   - Changed `/org/integrations/accounting` → `/org/accounting`
   - Changed `/org/integrations/accounting/{provider}/connect` → `/org/accounting/connect/{provider}`
   - Changed `/org/integrations/accounting/{provider}/disconnect` → `/org/accounting/disconnect/{provider}`
   - Changed `/org/integrations/accounting/sync/{id}/retry` → `/org/accounting/sync/{id}/retry`
   - Changed `redirect_url` → `authorization_url` to match backend schema

**Files Changed**:
- `app/modules/accounting/router.py` - Added dashboard endpoint and retry endpoint
- `app/modules/accounting/schemas.py` - Added AccountingDashboardResponse, AccountingConnectionDetail, SyncLogEntryDashboard
- `app/modules/accounting/service.py` - Updated _connection_to_dict to include missing fields
- `frontend/src/pages/settings/AccountingIntegrations.tsx` - Updated all API endpoint paths

**Backend Restart Required**: Yes, backend must be restarted for new endpoints to be available

**Similar Bugs Found & Fixed**: N/A - accounting-specific issue

**Related Issues**: ISSUE-022 (dashboard API mismatch)

**TODO for Future**:
- Add account_name, sync_status, error_message columns to accounting_integrations table
- Store account name from OAuth response
- Track real-time sync status
- Store last sync error message



---

### ISSUE-024: Subscription plan update hanging - missing commit + Decimal serialization error

- **Date**: 2026-03-09
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: When updating a subscription plan in the admin panel, the frontend gets stuck in loading state with "Update plan" button showing spinner indefinitely. Backend logs show UPDATE query executing but then ROLLBACK instead of COMMIT. After fixing the commit issue, a second error appeared: `TypeError: Object of type Decimal is not JSON serializable` when trying to serialize audit log data.

**Root Cause**: Two separate issues:
1. The `update_subscription_plan` endpoint in `app/modules/admin/router.py` was missing `await db.commit()` after calling the `update_plan` service function. The service function only does `await db.flush()` which writes changes to the database but doesn't commit the transaction. The `get_db_session` dependency uses `async with session.begin()` which auto-commits on context exit, but the endpoint was returning the response before the context exited, causing the transaction to roll back.
2. The `_serialise_audit` helper function didn't handle `Decimal` types, causing JSON serialization to fail when audit logging the `per_sms_cost_nzd` field (which is a Decimal in the database).

**Fix Applied**: 
1. Added explicit `await db.commit()` after the `update_plan` service call, and added proper error handling with `await db.rollback()` in exception blocks.
2. Added Decimal type handling to `_serialise_audit` function to convert Decimal values to float before JSON serialization.

**Files Changed**:
- `app/modules/admin/router.py` - Added commit/rollback to update_subscription_plan endpoint
- `app/modules/admin/service.py` - Added Decimal handling to _serialise_audit function

**Backend Restart Required**: Yes, backend must be restarted for the fix to take effect

**Similar Bugs Found & Fixed**: Checked other admin endpoints - most already have proper commit/rollback handling (e.g., hard_delete_org). This was an isolated omission in the plan update endpoint. The Decimal serialization issue may exist in other audit log calls - should be monitored.

**Related Issues**: None

**Note**: The pattern of using `flush()` in service functions and `commit()` in route handlers is correct - service functions should not commit to allow for transaction composition. Route handlers are responsible for committing or rolling back based on the overall operation success.

**Known Limitation**: Plan updates currently only update the `subscription_plans` table. Organizations on that plan will see the changes after logout/login (when ModuleContext refetches), but the system doesn't actively enforce plan-level module restrictions. The `get_all_modules_for_org` method checks the `OrgModule` table for enabled modules but doesn't validate against the plan's `enabled_modules` list. This means:
- If an org manually enabled a module that's later removed from their plan, they'll keep access until manually disabled
- Plan updates don't automatically disable modules for existing organizations
- The plan's `enabled_modules` acts more as a "default set" for new organizations rather than an enforced restriction

**Future Enhancement**: Consider adding plan-level module enforcement that:
1. Validates module enable/disable operations against the org's current plan
2. Optionally auto-disables modules when a plan is updated to remove them
3. Shows a warning in the admin panel when updating plans that will affect existing organizations


---

### ISSUE-025: Vehicle live search not working - CORS blocking requests + route order conflict

- **Date**: 2026-03-09
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Vehicle live search in InvoiceCreate page not working. User types registration but no results appear. Browser console shows CORS errors. Additionally, the `/vehicles/search` endpoint was returning 422 errors before the CORS fix was applied.

**Root Cause**: Two separate issues:
1. **CORS Configuration**: The frontend is exposed on port 3000 (via Docker port mapping 3000:5173), but the CORS configuration in `.env` only allowed `http://localhost:5173`. Requests from `http://localhost:3000` were being blocked with "Disallowed CORS origin" error.
2. **Route Order Conflict** (fixed in previous session): The `/search` and `/lookup-with-fallback` routes were defined AFTER the `/{vehicle_id}` route in `app/modules/vehicles/router.py`. FastAPI matches routes in order, so "search" was being interpreted as a vehicle_id UUID, causing 422 validation errors.

**Fix Applied**:
1. Updated `.env` to include both ports in CORS_ORIGINS: `["http://localhost:5173", "http://localhost:3000"]`
2. Recreated the app container to pick up the new environment variable: `docker-compose up -d app --force-recreate`
3. Route order was already fixed in previous session - `/search` and `/lookup-with-fallback` routes are now defined BEFORE `/{vehicle_id}` route.

**Files Changed**:
- `.env` - Added `http://localhost:3000` to CORS_ORIGINS

**Backend Restart Required**: Yes, container must be recreated (not just restarted) to pick up new .env values

**Similar Bugs Found & Fixed**: N/A - CORS configuration issue specific to Docker port mapping

**Related Issues**: None

**Note**: The vehicle live search feature is now fully functional:
- `/vehicles/search?q=XX` - Returns matching vehicles from global_vehicles database (instant, no API cost)
- `/vehicles/lookup-with-fallback` - Tries ABCD API first (~$0.05), falls back to Basic (~$0.15) if ABCD fails
- Frontend component `VehicleLiveSearch.tsx` provides live autocomplete with "Sync with Carjam" button for new vehicles

**Testing Verified**:
- Search endpoint returns results: `GET /vehicles/search?q=QT` → `{"results":[{"id":"...","rego":"QTD216","make":"TOYOTA",...}],"total":1}`
- Lookup with fallback works: `POST /vehicles/lookup-with-fallback` → `{"success":true,"vehicle":{...},"source":"cache",...}`
- CORS preflight passes: `OPTIONS /vehicles/search` → 200 OK with `access-control-allow-origin: http://localhost:3000`


---

### ISSUE-026: Inline "Create new customer" form too compacted - needs Modal popup

- **Date**: 2026-03-09
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: When clicking "Create new customer" in the customer search dropdown on InvoiceCreate, QuoteCreate, and JobCardCreate pages, the inline form was too compacted and difficult to use, especially on mobile devices.

**Root Cause**: The create customer form was rendered inline within the dropdown menu, which has limited space. This made the form cramped and hard to use on smaller screens.

**Fix Applied**:
1. Converted inline create form to Modal popup in all affected pages
2. Added `showCreateModal` state to replace `showCreateForm`
3. Added `handleOpenCreateModal()` and `handleCloseCreateModal()` functions
4. Added `resetCreateForm()` function to clear form state
5. Used the existing `Modal` component from `components/ui` for consistent styling
6. Modal is responsive and renders appropriately based on screen size

**Files Changed**:
- `frontend/src/pages/invoices/InvoiceCreate.tsx` - Converted to Modal (completed in previous session)
- `frontend/src/pages/quotes/QuoteCreate.tsx` - Converted to Modal (completed in previous session)
- `frontend/src/pages/job-cards/JobCardCreate.tsx` - Added Modal import (was missing)

**Similar Bugs Found & Fixed**: Checked all other pages with customer search:
- `frontend/src/pages/invoices/RecurringInvoices.tsx` - Already uses Modal properly
- `frontend/src/pages/bookings/BookingForm.tsx` - Already uses Modal properly
- `frontend/src/pages/customers/CustomerList.tsx` - Already uses Modal properly

**Related Issues**: None

**Note**: The Modal component (`frontend/src/components/ui/Modal.tsx`) provides:
- Responsive sizing with `max-w-md` class
- Proper focus trapping for accessibility
- Escape key to close
- Click outside to close
- Sticky header with close button


---

### ISSUE-027: Enhanced customer creation form with comprehensive fields

- **Date**: 2026-03-09
- **Severity**: enhancement
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: User requested a comprehensive customer creation form matching Zoho-style design with:
- Customer type (Business/Individual)
- Salutation, first name, last name
- Company name (for business customers)
- Display name
- Currency and language preferences
- Work phone and mobile phone (separate fields)
- Payment terms
- Company ID / business registration
- Bank payment and portal access options
- Structured billing and shipping addresses
- Contact persons
- Custom fields
- Remarks

**Root Cause**: The existing customer creation form only had basic fields (first name, last name, email, phone, address, notes). The database schema and API didn't support the comprehensive customer data needed for business use.

**Fix Applied**:

1. **Database Migration** (`0072_enhance_customer_fields`):
   - Added 17 new columns to `customers` table
   - `customer_type` (individual/business)
   - `salutation`, `company_name`, `display_name`
   - `work_phone`, `mobile_phone`
   - `currency`, `language`
   - `tax_rate_id`, `company_id`, `payment_terms`
   - `enable_bank_payment`, `enable_portal`
   - `billing_address`, `shipping_address` (JSONB)
   - `contact_persons` (JSONB array)
   - `custom_fields` (JSONB)
   - `remarks`, `documents`, `owner_user_id`
   - Created indexes for customer_type and company_name

2. **Backend Model** (`app/modules/customers/models.py`):
   - Updated Customer model with all new fields
   - Proper JSONB defaults for structured data

3. **Backend Schemas** (`app/modules/customers/schemas.py`):
   - Added `AddressSchema` and `ContactPersonSchema`
   - Updated `CustomerCreateRequest` with all new fields
   - Updated `CustomerUpdateRequest` with all new fields
   - Updated `CustomerResponse` with all new fields
   - Updated `CustomerSearchResult` with company_name and display_name

4. **Backend Service** (`app/modules/customers/service.py`):
   - Updated `_customer_to_dict()` to include all new fields
   - Updated `_customer_to_search_dict()` to include company info
   - Updated `create_customer()` to accept all new parameters
   - Auto-generates display_name if not provided

5. **Backend Router** (`app/modules/customers/router.py`):
   - Updated `create_new_customer()` to pass all new fields to service

6. **Frontend Component** (`frontend/src/components/customers/CustomerCreateModal.tsx`):
   - New comprehensive modal component with tabbed interface
   - Customer type toggle (Business/Individual)
   - Primary contact fields with salutation
   - Currency and language selectors
   - Phone fields with country code prefix
   - Tabbed sections: Other Details, Address, Contact Persons, Custom Fields, Remarks
   - Payment terms, bank payment, and portal access options
   - Billing and shipping address forms
   - Contact persons management (add/remove)
   - Responsive design matching Zoho-style UI

7. **Frontend Integration** (`frontend/src/pages/invoices/InvoiceCreate.tsx`):
   - Updated CustomerSearch to use new CustomerCreateModal
   - Removed inline form state and validation
   - Simplified component with callback pattern

**Files Changed**:
- `alembic/versions/2026_03_09_1700-0072_enhance_customer_fields.py` (new)
- `app/modules/customers/models.py`
- `app/modules/customers/schemas.py`
- `app/modules/customers/service.py`
- `app/modules/customers/router.py`
- `frontend/src/components/customers/CustomerCreateModal.tsx` (new)
- `frontend/src/components/customers/index.ts` (new)
- `frontend/src/pages/invoices/InvoiceCreate.tsx`

**Required Fields**:
- First name, last name, email, mobile phone are mandatory
- All other fields are optional

**Related Issues**: ISSUE-026 (Modal popup fix)


---

### ISSUE-028: Redesign InvoiceCreate page with Zoho-style UI

- **Date**: 2026-03-09
- **Severity**: enhancement
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: User requested a complete redesign of the invoice creation page to match Zoho-style design with:
- Customer Name dropdown with search icon
- Invoice# (auto-generated), Order Number
- Invoice Date, Terms dropdown (Due on Receipt, Net 15, etc.), Due Date
- Salesperson dropdown
- GST No* field (auto-populated from org settings)
- Subject field
- Item Table with columns: Item Details, Quantity, Rate, Tax dropdown, Amount
- Add New Row / Add Items in Bulk buttons
- Sub Total, Discount (% toggle), Shipping Charges, Adjustment, Total (NZD)
- Customer Notes textarea
- Terms & Conditions textarea
- Attach Files to Invoice
- Payment Gateway selection (Stripe, Bank Transfer)
- Save as Draft / Save and Send / Cancel buttons
- Make Recurring option

**Root Cause**: The existing invoice creation page had a different layout focused on vehicle workshop invoices with service/part/labour line items. The new design needed to be more generic and match Zoho's invoice creation UI.

**Fix Applied**:

1. **Complete UI Redesign** (`frontend/src/pages/invoices/InvoiceCreate.tsx`):
   - Clean header with action buttons (Cancel, Save as Draft, Save and Send)
   - Two-column layout for customer and invoice details
   - Customer search with search icon and dropdown
   - Auto-generated invoice number with prefix
   - Invoice date, terms dropdown, and auto-calculated due date
   - Salesperson dropdown
   - GST number auto-populated from `useTenant()` hook (org settings)
   - Subject field for invoice description

2. **Item Table Component**:
   - Table layout with columns: Item Details, Quantity, Rate, Tax, Amount
   - Inline item search with catalogue dropdown
   - Tax rate selector per line item
   - Auto-calculated line amounts
   - Add New Row and Add Items in Bulk buttons

3. **Totals Section**:
   - Sub Total calculation
   - Discount with % / $ toggle
   - Shipping Charges input
   - Adjustment input (positive or negative)
   - Total (NZD) with currency formatting

4. **Additional Fields**:
   - Customer Notes textarea
   - Terms & Conditions textarea (pre-populated from org settings)
   - File attachment section with upload button
   - Payment Gateway selection (Stripe, Bank Transfer)
   - Make Recurring checkbox

5. **GST Integration**:
   - Uses `useTenant()` hook to get `settings.gst.gst_number`
   - GST field is disabled and shows helper text
   - Auto-populates from organisation settings

**Files Changed**:
- `frontend/src/pages/invoices/InvoiceCreate.tsx` (complete rewrite)

**Key Features**:
- GST number auto-populated from org settings via TenantContext
- Due date auto-calculated based on payment terms
- Invoice number auto-generated with timestamp
- Terms & Conditions pre-populated from org settings
- Responsive design with clean Zoho-style UI

**Related Issues**: ISSUE-027 (Customer creation modal used in this page)


---

### ISSUE-029: Customer Profile page fails to load - missing exchange_rate_to_nzd column

- **Date**: 2026-03-09
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: When clicking on a customer from the customer list to view their profile, the page fails to load. Backend returns 500 error with message: `column invoices.exchange_rate_to_nzd does not exist`.

**Root Cause**: Two issues:
1. The Invoice model in `app/modules/invoices/models.py` has an `exchange_rate_to_nzd` column defined, but no migration existed to add this column to the database.
2. The alembic_version table had a `version_num` column of type `VARCHAR(32)`, which was too short for the new migration revision ID `0073_add_exchange_rate_to_invoices` (34 characters).

**Fix Applied**:
1. Created migration `0073_add_exchange_rate_to_invoices.py` to add the `exchange_rate_to_nzd` column to the invoices table with default value `1.000000`.
2. Fixed the alembic_version table column size:
   ```sql
   ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64);
   ```
3. Ran the migration successfully.
4. Updated `CustomerProfileResponse` schema in `app/modules/customers/schemas.py` to include all new customer fields from ISSUE-027.

**Files Changed**:
- `alembic/versions/2026_03_09_0930-0073_add_exchange_rate_to_invoices.py` (new)
- `app/modules/customers/schemas.py` (CustomerProfileResponse updated)

**Database Changes**:
- Added `exchange_rate_to_nzd NUMERIC(12,6) NOT NULL DEFAULT 1.000000` to `invoices` table
- Altered `alembic_version.version_num` from `VARCHAR(32)` to `VARCHAR(64)`

**Related Issues**: ISSUE-027 (customer fields enhancement)


---

### ISSUE-030: Auto-link customer and vehicle on invoice creation

- **Date**: 2026-03-09
- **Severity**: enhancement
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: User requested that when a customer and vehicle are selected on an invoice, they should be automatically linked so that:
1. When selecting a customer, their linked vehicles appear and can be auto-selected
2. When selecting a vehicle, its linked customers appear and can be auto-selected
3. When an invoice is created, the customer-vehicle link is automatically created if not already linked

**Root Cause**: No automatic linking existed between customers and vehicles during invoice creation. Users had to manually link them separately.

**Fix Applied**:

1. **Backend - Vehicle Search** (`app/modules/vehicles/service.py`, `app/modules/vehicles/router.py`):
   - Updated `search_vehicles()` to accept optional `org_id` parameter
   - When org_id is provided, returns `linked_customers` array for each vehicle
   - Router now passes org_id from request context

2. **Backend - Customer Search** (`app/modules/customers/service.py`, `app/modules/customers/router.py`):
   - Updated `search_customers()` to accept optional `include_vehicles` parameter
   - When true, returns `linked_vehicles` array for each customer
   - Router accepts `include_vehicles` query parameter

3. **Backend - Invoice Creation** (`app/modules/invoices/service.py`, `app/modules/invoices/schemas.py`, `app/modules/invoices/router.py`):
   - Added `global_vehicle_id` field to `InvoiceCreateRequest` schema
   - Updated `create_invoice()` to accept `global_vehicle_id` parameter
   - When invoice is created with both customer and vehicle, automatically creates `CustomerVehicle` link if not already linked
   - Audit log records the auto-link with `linked_via: invoice_creation`

4. **Frontend - VehicleLiveSearch** (`frontend/src/components/vehicles/VehicleLiveSearch.tsx`):
   - Added `LinkedCustomer` interface
   - Added `onCustomerAutoSelect` callback prop
   - Search results now show linked customer count badge
   - When vehicle is selected, auto-selects first linked customer if callback provided

5. **Frontend - InvoiceCreate** (`frontend/src/pages/invoices/InvoiceCreate.tsx`):
   - Added `LinkedVehicle` and `LinkedCustomer` interfaces
   - Updated CustomerSearch to pass `include_vehicles=true` to API
   - Added `onVehicleAutoSelect` callback to CustomerSearch
   - Search results now show linked vehicle count badge
   - When customer is selected, auto-selects first linked vehicle if no vehicle selected
   - When vehicle is selected, auto-selects first linked customer if no customer selected
   - Payload now includes `global_vehicle_id` for auto-linking

6. **Schema Updates** (`app/modules/customers/schemas.py`):
   - Added `LinkedVehicleSummary` schema
   - Added `linked_vehicles` optional field to `CustomerSearchResult`

**Files Changed**:
- `app/modules/vehicles/service.py`
- `app/modules/vehicles/router.py`
- `app/modules/customers/service.py`
- `app/modules/customers/router.py`
- `app/modules/customers/schemas.py`
- `app/modules/invoices/service.py`
- `app/modules/invoices/schemas.py`
- `app/modules/invoices/router.py`
- `frontend/src/components/vehicles/VehicleLiveSearch.tsx`
- `frontend/src/pages/invoices/InvoiceCreate.tsx`

**User Experience**:
- When selecting a customer, their linked vehicles are shown with a badge count
- First linked vehicle is auto-selected if no vehicle is currently selected
- When selecting a vehicle, its linked customers are shown with a badge count
- First linked customer is auto-selected if no customer is currently selected
- When invoice is saved, customer-vehicle link is automatically created if not already linked

**Related Issues**: ISSUE-029 (customer profile fix)


---

### ISSUE-031: Item search dropdown hidden/clipped in invoice table

- **Date**: 2026-03-09
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: When adding items to an invoice, the item search dropdown was hidden/clipped inside the table. Users could not see the search results when typing to search for catalogue items.

**Root Cause**: Two CSS issues:
1. The table container had `overflow-x-auto` which clips any absolutely positioned elements (like dropdowns) that extend beyond the container bounds
2. The dropdown had `z-index: 20` which was not high enough to appear above other elements

**Fix Applied**:
1. Changed table container from `overflow-x-auto` to `overflow-visible` to allow dropdown to extend beyond table bounds
2. Increased dropdown z-index from `z-20` to `z-50` to ensure it appears above other elements

**Files Changed**:
- `frontend/src/pages/invoices/InvoiceCreate.tsx`

**Related Issues**: N/A


---

### ISSUE-032: Salesperson dropdown showing mock data instead of actual org users

- **Date**: 2026-03-09
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: The salesperson dropdown in the invoice creation page was showing hardcoded mock data ("John Smith", "Jane Doe") instead of actual organisation users.

**Root Cause**: The frontend was using mock data instead of fetching from an API endpoint. The existing `/org/users` endpoint requires `org_admin` role, which would prevent salespeople from seeing the dropdown options.

**Fix Applied**:

1. **Backend - New endpoint** (`app/modules/organisations/service.py`, `app/modules/organisations/router.py`):
   - Added `list_salespeople()` service function that returns active users with id and name (email)
   - Added `GET /api/v1/org/salespeople` endpoint accessible by both `org_admin` and `salesperson` roles
   - Returns a simple list of `{id, name}` for dropdown population

2. **Backend - New schemas** (`app/modules/organisations/schemas.py`):
   - Added `SalespersonItem` schema with id and name fields
   - Added `SalespersonListResponse` schema

3. **Frontend - InvoiceCreate** (`frontend/src/pages/invoices/InvoiceCreate.tsx`):
   - Replaced mock data with API call to `/org/salespeople`
   - Handles both array and wrapped response formats

**Files Changed**:
- `app/modules/organisations/service.py`
- `app/modules/organisations/router.py`
- `app/modules/organisations/schemas.py`
- `frontend/src/pages/invoices/InvoiceCreate.tsx`

**Related Issues**: N/A


---

### ISSUE-033: Email Providers missing test, TLS/SSL encryption, and priority features

- **Date**: 2026-03-09
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: The Email Providers admin page was missing three key features:
1. No way to test individual email providers after configuration
2. No option to select TLS or SSL encryption for Custom SMTP
3. No way to set priority when multiple providers are active

**Root Cause**: These features were never implemented. The backend model and frontend UI only supported basic credential storage without encryption options, testing capability, or priority ordering.

**Fix Applied**:

1. **Database Migration** (`alembic/versions/2026_03_09_1100-0074_add_email_provider_encryption_priority.py`):
   - Added `smtp_encryption` column (varchar, default 'tls')
   - Added `priority` column (integer, default 1)

2. **Backend - Model** (`app/modules/admin/models.py`):
   - Added `smtp_encryption` and `priority` columns to EmailProvider model

3. **Backend - Schemas** (`app/modules/email_providers/schemas.py`):
   - Added `smtp_encryption` and `priority` to `EmailProviderResponse`
   - Added `smtp_encryption` to `EmailProviderCredentialsRequest`
   - Added `EmailProviderPriorityRequest` and `EmailProviderPriorityResponse`
   - Added `EmailProviderTestResponse`

4. **Backend - Service** (`app/modules/email_providers/service.py`):
   - Added `test_email_provider()` function that sends a test email via SMTP
   - Added `update_email_provider_priority()` function
   - Updated `save_email_credentials()` to handle `smtp_encryption`
   - Updated `_provider_to_dict()` to include new fields

5. **Backend - Router** (`app/modules/email_providers/router.py`):
   - Added `POST /{provider_key}/test` endpoint to send test emails
   - Added `PUT /{provider_key}/priority` endpoint to update priority
   - Updated credentials endpoint to pass `smtp_encryption`

6. **Frontend - EmailProviders** (`frontend/src/pages/admin/EmailProviders.tsx`):
   - Added `smtp_encryption` select field (none/tls/ssl) to Custom SMTP config
   - Added "Send Test Email" button for providers with credentials
   - Added priority input for active providers
   - Updated sorting to show active providers first, sorted by priority

**Files Changed**:
- `alembic/versions/2026_03_09_1100-0074_add_email_provider_encryption_priority.py`
- `app/modules/admin/models.py`
- `app/modules/email_providers/schemas.py`
- `app/modules/email_providers/service.py`
- `app/modules/email_providers/router.py`
- `frontend/src/pages/admin/EmailProviders.tsx`

**Related Issues**: N/A


---

### ISSUE-034: InvoiceDetail shows $NaN, missing data, no Edit button, broken actions

- **Date**: 2026-03-09
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Invoice detail page shows $NaN for all monetary values, no customer or vehicle info, no Edit button, and Duplicate/Email/Download PDF buttons don't work.

**Root Cause**: Multiple frontend/backend field name mismatches:
1. API returns `{ invoice: {...} }` wrapper but frontend read `res.data` directly
2. API returns `subtotal`, `total`, `balance_due` but frontend expected `subtotal_ex_gst`, `total_incl_gst`
3. API returns `item_type` on line items but frontend expected `type`
4. API returns `is_gst_exempt` but frontend expected `gst_exempt`
5. API only returned `customer_id` without customer details
6. No payments or credit notes included in response
7. No Edit button existed for draft invoices
8. No edit route existed in App.tsx

**Fix Applied**:

1. **Backend - Service** (`app/modules/invoices/service.py`): Updated `get_invoice()` to include customer details, payments, and credit notes in the response
2. **Backend - Schemas** (`app/modules/invoices/schemas.py`): Added `CustomerSummary`, `PaymentSummary`, `CreditNoteSummary` schemas and added `customer`, `payments`, `credit_notes` fields to `InvoiceResponse`
3. **Backend - Router** (`app/modules/invoices/router.py`): Updated `get_invoice_endpoint` to pass through nested objects
4. **Frontend - InvoiceDetail** (`frontend/src/pages/invoices/InvoiceDetail.tsx`): Fixed field mappings, added NaN-safe `formatNZD`, unwrapped `{ invoice: {...} }` response, added Edit button for drafts, handled both field name variants
5. **Frontend - InvoiceCreate** (`frontend/src/pages/invoices/InvoiceCreate.tsx`): Added edit mode support with `useParams`, loads existing invoice data, uses PUT for updates
6. **Frontend - App.tsx**: Added `/invoices/:id/edit` route

**Files Changed**:
- `app/modules/invoices/service.py`
- `app/modules/invoices/schemas.py`
- `app/modules/invoices/router.py`
- `frontend/src/pages/invoices/InvoiceDetail.tsx`
- `frontend/src/pages/invoices/InvoiceCreate.tsx`
- `frontend/src/App.tsx`

**Related Issues**: ISSUE-005 (same pattern of frontend/backend field mismatch)


---

### ISSUE-035: Enhanced vehicle display on invoice + odometer reading management

- **Date**: 2026-03-10
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Invoice detail page showed minimal vehicle info (just rego and make/model). No way to record odometer readings on invoices. No odometer history tracking. CarJam resync could overwrite higher local odometer with lower CarJam value.

**Root Cause**: Missing feature — odometer reading management system not implemented.

**Fix Applied**:

1. **Database**: Created `odometer_readings` history table with fields: `id`, `global_vehicle_id`, `reading_km`, `source` (carjam/manual/invoice), `recorded_by`, `invoice_id`, `org_id`, `notes`, `recorded_at`. Migration `0075_add_odometer_readings_table`.
2. **Model**: Added `OdometerReading` model in `app/modules/vehicles/models.py`.
3. **Vehicle Service** (`app/modules/vehicles/service.py`):
   - Added `record_odometer_reading()` — saves to history AND updates `global_vehicles.odometer_last_recorded` only if new reading >= current
   - Added `get_odometer_history()` — returns history newest first
   - Added `update_odometer_reading()` — corrects a reading and recalculates vehicle's max odometer
   - Updated `refresh_vehicle()` CarJam sync to use `max(local, carjam)` for odometer preservation
   - Updated `refresh_vehicle()` to record CarJam odometer in history table
   - Updated `search_vehicles()` to return odometer in results
4. **Vehicle Router** (`app/modules/vehicles/router.py`): Added 3 endpoints:
   - `POST /{vehicle_id}/odometer` — record new reading
   - `GET /{vehicle_id}/odometer-history` — get history
   - `PUT /{vehicle_id}/odometer/{reading_id}` — correct a reading
5. **Vehicle Schemas** (`app/modules/vehicles/schemas.py`): Added `OdometerReadingRequest`, `OdometerReadingResponse`, `OdometerReadingUpdateRequest`, `OdometerHistoryEntry`
6. **Invoice Service** (`app/modules/invoices/service.py`): Updated `create_invoice()` to call `record_odometer_reading()` when saving invoice with odometer + global_vehicle_id
7. **Frontend - InvoiceCreate** (`frontend/src/pages/invoices/InvoiceCreate.tsx`):
   - Added `odometer` and `newOdometer` to Vehicle interface
   - Added odometer input field per vehicle showing current reading and allowing new entry
   - Payload now sends `vehicle_odometer` from new reading
8. **Frontend - InvoiceDetail** (`frontend/src/pages/invoices/InvoiceDetail.tsx`):
   - Enhanced vehicle section with structured display: Registration, Vehicle Details (year make model), Odometer in Kms
   - Added `vehicle_odometer` to InvoiceDetail interface
9. **Frontend - VehicleLiveSearch** (`frontend/src/components/vehicles/VehicleLiveSearch.tsx`):
   - Added `odometer` to Vehicle and SearchResult interfaces
   - Shows odometer in vehicle summary display
   - Passes odometer through on selection

**Files Changed**:
- `alembic/versions/2026_03_10_0900-0075_add_odometer_readings_table.py`
- `app/modules/vehicles/models.py`
- `app/modules/vehicles/service.py`
- `app/modules/vehicles/router.py`
- `app/modules/vehicles/schemas.py`
- `app/modules/invoices/service.py`
- `frontend/src/pages/invoices/InvoiceCreate.tsx`
- `frontend/src/pages/invoices/InvoiceDetail.tsx`
- `frontend/src/components/vehicles/VehicleLiveSearch.tsx`

**Related Issues**: ISSUE-034 (InvoiceDetail improvements)

---

### ISSUE-036: Customer list page missing Receivables and Unused Credits columns

- **Date**: 2026-03-10
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Customer list page showed minimal info (just name and email). No financial summary columns. Missing work phone. User wanted Zoho-style layout with Receivables and Unused Credits columns.

**Root Cause**: Missing feature — customer list page was basic and didn't show financial data.

**Fix Applied**:

1. **Backend Service** (`app/modules/customers/service.py`):
   - Updated `search_customers()` to batch-fetch receivables (sum of `Invoice.balance_due` where status not in voided/draft) and unused credits (sum of `CreditNote.amount`) per customer
   - Added `work_phone` to `_customer_to_search_dict()`
   - Removed duplicate return statement
2. **Backend Schema** (`app/modules/customers/schemas.py`):
   - Added `receivables: float`, `unused_credits: float`, and `work_phone` to `CustomerSearchResult`
3. **Frontend** (`frontend/src/pages/customers/CustomerList.tsx`):
   - Rewritten with 6 columns: Name, Company Name, Email, Work Phone, Receivables (BCY), Unused Credits (BCY)
   - Fixed API params from `page`/`page_size`/`search` to `limit`/`offset`/`q` to match backend
   - Added `formatNZD()` helper for currency formatting
   - Added debounced search, pagination, and create customer modal

**Files Changed**:
- `app/modules/customers/service.py`
- `app/modules/customers/schemas.py`
- `frontend/src/pages/customers/CustomerList.tsx`

**Related Issues**: None

---

### ISSUE-037: Redesign invoices page with split-panel layout and invoice preview

- **Date**: 2026-03-10
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Invoice list was a basic table. No inline preview. Clicking an invoice navigated to a separate page. Missing features like Record Payment, Send/Mark as Sent, PDF/Print dropdown, Share link, and Void from the list view.

**Root Cause**: Missing feature — invoices page needed a Zoho-style split-panel redesign.

**Fix Applied**:

1. **Frontend InvoiceList** (`frontend/src/pages/invoices/InvoiceList.tsx`): Complete rewrite with:
   - Left sidebar (320px): scrollable invoice list with status filter dropdown, search, pagination, status badges with colour coding, due date warnings
   - Right panel: full invoice detail with branded preview card showing org logo/name, Bill To section, line items table with gradient header, totals breakdown with Balance Due highlight bar
   - Toolbar: Edit (draft only), Send dropdown (Send Invoice / Mark as Sent), Share (copy link), PDF/Print dropdown, Record Payment (green button), More menu (Duplicate, Copy Link, Void)
   - Draft banner with "Send Invoice" and "Mark As Sent" quick actions
   - Void modal with reason input
   - Record Payment modal with amount, method, and note fields
   - Vehicle info card, Payment History table, Credit Notes table, Internal Notes below preview
   - Auto-selects first invoice on load
2. **Backend** (`app/modules/invoices/service.py`): Added org info (name, address, phone, email, logo, GST, website) to `get_invoice()` response from Organisation settings
3. **Backend Schema** (`app/modules/invoices/schemas.py`): Added `org_name`, `org_address`, `org_phone`, `org_email`, `org_logo_url`, `org_gst_number`, `org_website` to `InvoiceResponse`
4. **Backend** (`app/modules/invoices/service.py`): Added customer `address` to invoice detail response
5. **Routes** (`frontend/src/App.tsx`): Changed `/invoices/:id` route to use InvoiceList (split-panel) instead of separate InvoiceDetail page

**Files Changed**:
- `frontend/src/pages/invoices/InvoiceList.tsx`
- `frontend/src/App.tsx`
- `app/modules/invoices/service.py`
- `app/modules/invoices/schemas.py`

**Related Issues**: ISSUE-034 (InvoiceDetail improvements)

---

### ISSUE-038: Sidebar shows "WorkshopPro" instead of org name + missing sidebar display mode option

- **Date**: 2026-03-10
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Sidebar header always shows "WorkshopPro" instead of the organisation's actual name ("Oraflows"). User also wanted the ability to choose between showing icon + name, icon only, or name only in the sidebar.

**Root Cause**: TenantContext was reading `data.name` from the API response, but the backend `OrgSettingsResponse` returns the field as `org_name`. So `data.name` was always `undefined`, triggering the `'WorkshopPro'` fallback.

**Fix Applied**:

1. **TenantContext** (`frontend/src/contexts/TenantContext.tsx`):
   - Changed `name: data.name` → `name: data.org_name || data.name || ''` to correctly read the org name
   - Added `sidebar_display_mode` to `OrgBranding` interface and data mapping
2. **OrgLayout** (`frontend/src/layouts/OrgLayout.tsx`):
   - Updated sidebar header to respect `sidebar_display_mode` setting: `icon_and_name` (default), `icon_only`, or `name_only`
   - Falls back to showing name if `icon_only` is selected but no logo is uploaded
3. **OrgSettings Branding Tab** (`frontend/src/pages/settings/OrgSettings.tsx`):
   - Added `sidebar_display_mode` to form state and data loading
   - Added visual selector with three card-style buttons for the display mode
   - Shows warning when `icon_only` is selected but no logo is uploaded
   - Added `refetchTenant()` call after save so sidebar updates immediately
   - Fixed data loading to read `data.org_name` instead of `data.name`
4. **Backend** (`app/modules/organisations/service.py`, `app/modules/organisations/schemas.py`):
   - Added `sidebar_display_mode` to `SETTINGS_JSONB_KEYS`, `OrgSettingsResponse`, and `OrgSettingsUpdateRequest`

**Files Changed**:
- `frontend/src/contexts/TenantContext.tsx`
- `frontend/src/layouts/OrgLayout.tsx`
- `frontend/src/pages/settings/OrgSettings.tsx`
- `app/modules/organisations/service.py`
- `app/modules/organisations/schemas.py`

**Related Issues**: None

---

### ISSUE-039: Broken scrolling on multiple pages — content clipped or overflows viewport

- **Date**: 2026-03-10
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Several pages throughout the app have broken scrolling. Content gets clipped at the bottom of the viewport and cannot be scrolled to. The Settings > Modules page (showing Franchise, Ecommerce, Reports, Assets toggles) is one visible example — module cards below the fold are unreachable. Other affected pages include InvoiceCreate, InvoiceList, POSScreen, KitchenDisplay, SetupWizard, and OnboardingWizard.

**Root Cause**: The OrgLayout (and AdminLayout) use a `h-screen overflow-hidden` root container with a `flex-1 overflow-y-auto` `<main>` element as the designated scroll container. Multiple child pages were setting their own viewport-relative height constraints (`min-h-screen`, `h-screen`, `min-h-[calc(100vh-8rem)]`, `h-[calc(100vh-64px)]`) which conflict with this layout pattern:

1. `min-h-screen` / `h-screen` forces the page to be at least 100vh tall, but the `<main>` scroll container is shorter than 100vh (it excludes the header). This pushes content below the scroll container's visible area.
2. `min-h-[calc(100vh-8rem)]` in Settings.tsx tried to account for the header but still referenced the viewport instead of the parent container.
3. `h-[calc(100vh-64px)] overflow-hidden` in InvoiceList.tsx created a fixed-height container that didn't account for the layout's padding, causing content to be clipped.

**Fix Applied**:

1. `Settings.tsx`: Changed `min-h-[calc(100vh-8rem)]` → `h-full` so it fills the parent scroll container. Added `md:sticky md:top-0 md:self-start` to the sidebar nav so it stays pinned while content scrolls. Added `md:overflow-y-auto md:max-h-[calc(100vh-10rem)]` to the nav list for long settings menus.
2. `InvoiceList.tsx`: Changed `h-[calc(100vh-64px)] overflow-hidden` → `h-full overflow-hidden -m-4 lg:-m-6` to fill the parent and use negative margins to cancel the `<main>` padding (split-pane layout needs edge-to-edge).
3. `InvoiceCreate.tsx`: Changed `min-h-screen` → removed (just `bg-gray-50`), allowing natural content flow within the scroll container.
4. `POSScreen.tsx`: Changed `h-screen` → `h-full -m-4 lg:-m-6` for edge-to-edge full-height layout within the scroll container.
5. `KitchenDisplay.tsx`: Changed `min-h-screen` → removed for non-fullscreen mode, added `-m-4 lg:-m-6` for edge-to-edge dark theme. Fixed disabled state container similarly.
6. `SetupWizard.tsx`: Removed `min-h-screen` from both loading and main containers.
7. `OnboardingWizard.tsx`: Removed `min-h-screen` from main container.

**Files Changed**:
- `frontend/src/pages/settings/Settings.tsx`
- `frontend/src/pages/invoices/InvoiceList.tsx`
- `frontend/src/pages/invoices/InvoiceCreate.tsx`
- `frontend/src/pages/pos/POSScreen.tsx`
- `frontend/src/pages/kitchen/KitchenDisplay.tsx`
- `frontend/src/pages/setup/SetupWizard.tsx`
- `frontend/src/pages/onboarding/OnboardingWizard.tsx`

**Key Principle**: Pages rendered inside OrgLayout/AdminLayout should never use viewport-relative heights (`h-screen`, `min-h-screen`, `100vh`). The layout's `<main>` element is the scroll container — child pages should use `h-full` to fill it or let content flow naturally. Pages that need edge-to-edge layout (like split-pane InvoiceList or POS) should use negative margins (`-m-4 lg:-m-6`) to cancel the `<main>` padding.

**Pages NOT changed** (correctly standalone/auth pages that own their viewport):
- Auth pages (Login, Signup, MFA, PasswordReset, etc.) — rendered outside OrgLayout
- BookingPage — public-facing standalone page
- App.tsx loading spinners — rendered before layout mounts

**Similar Bugs Found & Fixed**: All 7 pages with viewport-relative heights inside OrgLayout were fixed in one pass.

**Related Issues**: ISSUE-028 (InvoiceCreate redesign introduced min-h-screen), ISSUE-037 (InvoiceList redesign introduced h-[calc(100vh-64px)])


---

### ISSUE-040: Quote Save as Draft hangs — missing db.commit() in quotes router

- **Date**: 2026-03-10
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A (same class of bug as ISSUE-024)

**Symptoms**: Clicking "Save as Draft" on the QuoteCreate page shows a loading spinner indefinitely. The quote is never saved. "Save and Send" also fails for the same reason (create step fails, so send never executes).

**Root Cause**: The `create_quote_endpoint` and `update_quote_endpoint` in `app/modules/quotes/router.py` were missing `await db.commit()` after calling the service functions. The service functions use `db.flush()` which writes to the database but doesn't commit. Without an explicit commit in the router, the transaction rolls back when the session closes, discarding all changes. Backend logs confirmed: INSERT queries execute successfully, then ROLLBACK instead of COMMIT.

This is the same class of bug as ISSUE-024 (subscription plan update hanging due to missing commit).

**Fix Applied**:
1. Added `await db.commit()` to `create_quote_endpoint` after `create_quote()` call
2. Added `await db.commit()` to `update_quote_endpoint` after `update_quote()` call
3. Added proper `await db.rollback()` in exception handlers for all 4 endpoints
4. Moved `await db.commit()` inside try blocks for `send_quote_endpoint` and `convert_quote_endpoint` (were previously outside try/except, meaning errors during commit would be unhandled)

**Files Changed**:
- `app/modules/quotes/router.py`

**Backend Restart Required**: Yes

**Similar Bugs Found & Fixed**: `update_quote_endpoint` had the same missing commit. `send_quote_endpoint` and `convert_quote_endpoint` already had commits but lacked rollback handling — fixed those too.

**Related Issues**: ISSUE-024 (identical bug pattern in admin plan update endpoint)

---

### ISSUE-041: Quote "Send to Customer" email not sending + no Edit button

- **Date**: 2026-03-10
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Two issues reported:
1. Clicking "Send to Customer" on a quote appeared to succeed (status changed to "sent") but no email was actually delivered to the customer. No error was shown to the user.
2. There was no way to edit a quote after creating it — no Edit button on the QuoteDetail page and no edit route.

**Root Cause**:
1. **Email not sending**: The `send_quote` service was using `send_org_email` from `app/integrations/brevo.py`, which reads SMTP config from the `integration_configs` database table. However, the app's actual email infrastructure uses the `EmailProvider` model (from `app/modules/admin/models`) with the `email_providers` table — a completely different system. The invoice email (`email_invoice`) works because it queries `EmailProvider` directly and sends via SMTP with failover across providers. The quote email was using the wrong email system entirely.
2. **No Edit button**: `QuoteDetail.tsx` only had "Send to Customer" and "Convert to Invoice" buttons. No edit button existed. `QuoteCreate.tsx` was create-only with no edit mode support. No `/quotes/:id/edit` route existed in `App.tsx`.

**Fix Applied**:
1. **Quote send service** (`app/modules/quotes/service.py`):
   - Replaced `send_org_email` (brevo.py) with the same `EmailProvider`-based SMTP approach used by `email_invoice` in the invoice service
   - Queries `EmailProvider` table for active providers with credentials, ordered by priority
   - Builds MIME message with PDF attachment using `MIMEApplication`
   - Tries each provider in priority order with failover (same pattern as invoice email)
   - Includes a "View Quote Online" link in the email body using the acceptance token
   - Raises `ValueError` with clear message if no providers configured or all fail
3. **Edit button** (`frontend/src/pages/quotes/QuoteDetail.tsx`):
   - Added "Edit" button visible when quote status is `draft`, navigates to `/quotes/{id}/edit`
4. **Edit mode** (`frontend/src/pages/quotes/QuoteCreate.tsx`):
   - Added `useParams` to detect edit mode via URL param `id`
   - Added `loadingQuote` state and data loading effect that fetches existing quote and populates all form fields (customer, vehicle, line items, notes, terms, subject)
   - Updated `handleSaveDraft` to use PUT for edit mode, navigating back to quote detail
   - Updated `handleSaveAndSend` to use PUT for edit mode
   - Updated header title to show "Edit Quote" vs "New Quote"
   - Updated Cancel button to navigate back to quote detail in edit mode
5. **Route** (`frontend/src/App.tsx`):
   - Added `/quotes/:id/edit` route pointing to `QuoteCreate` component

**Files Changed**:
- `app/modules/quotes/service.py`
- `frontend/src/pages/quotes/QuoteDetail.tsx`
- `frontend/src/pages/quotes/QuoteCreate.tsx`
- `frontend/src/App.tsx`

**Related Issues**: ISSUE-040 (quote router commit fixes were prerequisite for these to work)

---

### ISSUE-042: Quote list missing Requote, Delete actions and Expires In column

- **Date**: 2026-03-10
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: The quote list page had no way to edit/requote sent quotes, no way to delete quotes, and no visibility into when quotes expire.

**Root Cause**: Feature gap — these actions and the expiry column were never implemented.

**Fix Applied**:
1. **Backend** — Added `delete_quote` service function (hard delete, only for draft/declined/expired quotes) and `DELETE /quotes/{id}` router endpoint. Added "draft" to valid transitions from "sent" status to support requoting.
2. **QuoteList.tsx** — Added "Expires In" column showing days until expiry with color coding (red < 0, orange ≤ 3, yellow ≤ 7). Added "Edit" button for draft quotes, "Requote" button for sent quotes (reverts to draft then navigates to edit), and "Delete" button for draft/declined/expired quotes with confirmation dialog.
3. **QuoteDetail.tsx** — Added "Requote" button for sent quotes, "Delete" button with inline confirmation for deletable statuses.

**Files Changed**:
- `app/modules/quotes/service.py`
- `app/modules/quotes/router.py`
- `frontend/src/pages/quotes/QuoteList.tsx`
- `frontend/src/pages/quotes/QuoteDetail.tsx`

**Related Issues**: ISSUE-041

---

### ISSUE-043: StaffDetail page — old schema, unstyled, double-prefixed API URL

- **Date**: 2026-03-10
- **Severity**: medium
- **Status**: resolved
- **Reporter**: agent (continuation of staff module implementation)
- **Regression of**: N/A

**Symptoms**: The StaffDetail page at `/staff/:id` used the old single `name` field, sent `name` on save instead of `first_name`/`last_name`, had a double-prefixed API URL (`/api/v2/staff/${staffId}` without baseURL override), displayed old fields (overtime_rate, skills, availability_schedule) that aren't part of the new simple onboarding, and was completely unstyled (raw HTML with inline styles).

**Root Cause**: StaffDetail was never updated when the staff schema was enhanced in migration 0080. The StaffList was rewritten but StaffDetail was left with the original placeholder implementation.

**Fix Applied**:
1. Full rewrite of `StaffDetail.tsx` with proper Tailwind styling matching the rest of the app
2. Fixed API URL to use `apiClient.get('/staff/${staffId}', { baseURL: '/api/v2' })` pattern
3. Updated form to use `first_name`/`last_name` instead of `name`
4. Added all new fields: employee_id, position, reporting_to (with dropdown), shift_start, shift_end
5. View/edit toggle — shows read-only view by default, edit mode on button click
6. Added "Reports To" dropdown populated from all active staff
7. Added deactivate button with confirmation
8. Removed unused `debounceRef` from StaffList.tsx

**Files Changed**:
- `frontend/src/pages/staff/StaffDetail.tsx` (full rewrite)
- `frontend/src/pages/staff/StaffList.tsx` (removed unused import/ref)

**Related Issues**: Part of staff module implementation (ISSUE-043 is the detail page completion)

---

### ISSUE-044: Staff router "closed transaction" error — db.commit()/db.rollback() conflicts with session.begin() context manager

- **Date**: 2026-03-10
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Creating or updating a staff member returns error: "Can't operate on closed transaction inside context manager. Please complete the context manager before emitting further commands."

**Root Cause**: `get_db_session()` uses `async with session.begin():` which auto-commits on successful exit and auto-rolls-back on exception. The staff router endpoints were manually calling `await db.commit()` inside the `session.begin()` context manager, which closed the transaction prematurely. After that, `_enrich_reporting_to()` tried to query on the closed transaction, and the context manager's `__aexit__` also failed trying to operate on the already-committed transaction.

**Fix Applied**: Removed all manual `db.commit()` and `db.rollback()` calls from the staff router. Replaced `db.commit()` with `db.flush()` where needed (to get server-generated values before `db.refresh()`). The `session.begin()` context manager handles commit/rollback automatically.

Affected endpoints: POST (create), PUT (update), DELETE (deactivate), POST assign-location, DELETE remove-from-location.

**Files Changed**:
- `app/modules/staff/router.py`

**Related Issues**: ISSUE-043

---

### ISSUE-045: No way to reactivate deactivated staff + no user account creation for staff

- **Date**: 2026-03-10
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Once a staff member was deactivated, there was no way to reactivate them. Also, no mechanism existed to create an organisation user account (login) for a staff member.

**Root Cause**: Feature gap. The deactivate endpoint existed but no activate counterpart. The staff model had a `user_id` field for linking to user accounts but no endpoint or UI to create the link.

**Fix Applied**:

1. Backend:
   - Added `POST /api/v2/staff/{id}/activate` endpoint to reactivate inactive staff
   - Added `POST /api/v2/staff/{id}/create-account` endpoint that creates a User record (org_admin role) with a password, links it to the staff member via `user_id`, and marks email as verified
   - Added `CreateStaffAccountRequest` schema (password field, min 8 chars)

2. Frontend StaffDetail:
   - Added "Activate" button (green) for inactive staff, replacing "Deactivate"
   - Added "Create User Account" button for active staff with email but no user_id
   - Shows "Has Login" badge when staff has a linked user account
   - Create Account modal with password input and validation
   - Deactivate now stays on detail page (refreshes) instead of navigating away

3. Frontend StaffList:
   - Added `handleActivate` function
   - Actions column now shows "Activate" for inactive staff instead of hiding the button

**Files Changed**:
- `app/modules/staff/router.py` (2 new endpoints)
- `app/modules/staff/schemas.py` (new CreateStaffAccountRequest)
- `frontend/src/pages/staff/StaffDetail.tsx` (activate, create account modal, has-login badge)
- `frontend/src/pages/staff/StaffList.tsx` (activate action in table)

**Related Issues**: ISSUE-043, ISSUE-044

---

### ISSUE-046: No visual way to manage staff work days/schedule

- **Date**: 2026-03-10
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Staff forms only had basic shift_start/shift_end text fields. No intuitive way to specify which days a staff member works and their hours per day.

**Root Cause**: Feature gap. The `availability_schedule` JSONB field existed on the `staff_members` table (format: `{"monday": {"start": "09:00", "end": "17:00"}, ...}`) but the frontend only exposed `shift_start`/`shift_end` text inputs.

**Fix Applied**:

1. Created `WorkSchedule.tsx` shared component — toggleable day buttons (Mon-Sun) with start/end time inputs per day. Supports read-only mode for detail view.
2. StaffList modal: Replaced shift_start/shift_end inputs with WorkSchedule component. New staff defaults to Mon-Fri 9-5. Table column shows abbreviated active day names.
3. StaffDetail page: Replaced "Shift Hours" section with WorkSchedule component under a "Work Schedule" section header. Read-only when not editing.
4. Both pages send `availability_schedule` in save payload instead of `shift_start`/`shift_end`.

**Files Changed**:
- `frontend/src/components/WorkSchedule.tsx` (new)
- `frontend/src/pages/staff/StaffList.tsx` (work schedule in modal + table column)
- `frontend/src/pages/staff/StaffDetail.tsx` (work schedule section)

**Related Issues**: ISSUE-043, ISSUE-044, ISSUE-045

---

### ISSUE-047: Discount toggle button shows garbled character for dollar sign

- **Date**: 2026-03-11
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: The discount type toggle button (% / $) in InvoiceCreate and QuoteCreate pages shows a garbled or special character instead of a clean dollar sign. The `%` button renders correctly but the `$` button appears broken.

**Root Cause**: The parent container `div` had `overflow-hidden` which was clipping the `$` glyph. The dollar sign character has ascenders (the vertical stroke extends above the S) that go beyond the normal text line-height bounds. Combined with a tight `min-w-[36px]` and `px-2.5` padding, the glyph was being visually clipped on the right side, making it appear garbled or as a special character.

**Fix Applied**:
1. Removed `overflow-hidden` from the parent `inline-flex` container — this was the primary cause of clipping. Used `rounded-l-md` / `rounded-r-md` on individual buttons instead for border radius
2. Increased minimum button width from `min-w-[36px]` to `min-w-[40px]` and padding from `px-2.5` to `px-3` to give the glyph more breathing room
3. Bumped font weight to `font-semibold` for better legibility
4. Reverted to plain `$` and `%` characters (no need for Unicode escapes or font-mono once overflow-hidden is removed)

**Files Changed**:
- `frontend/src/pages/invoices/InvoiceCreate.tsx`
- `frontend/src/pages/quotes/QuoteCreate.tsx`

**Similar Bugs Found & Fixed**: Same toggle pattern in QuoteCreate.tsx — fixed both. Scanned entire frontend for other `$` toggle buttons — DiscountRules.tsx uses `$` in text labels (not narrow buttons), no fix needed.

**Related Issues**: ISSUE-028 (InvoiceCreate redesign introduced this toggle)


---

### ISSUE-048: Record Payment does not send updated invoice email to customer

- **Date**: 2026-03-11
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: When clicking "Record Payment" on an invoice, the payment is recorded and the invoice status updates correctly (to paid or partially_paid), but no email is sent to the customer with the updated invoice showing the payment.

**Root Cause**: The `record_cash_payment_endpoint` in `app/modules/payments/router.py` calls `record_cash_payment()` which records the payment and updates the invoice status, but never triggers an email send. The `email_invoice()` function exists in `app/modules/invoices/service.py` and handles PDF generation + SMTP sending, but it's not called after payment recording.

**Fix Applied**: Added email sending after payment recording in `record_cash_payment_endpoint`. Uses a fresh session (`async_session_factory()`) with RLS context set, since the original session's transaction is already committed by the time we need to send the email (same pattern as ISSUE-005). The email is wrapped in a try/except so a failed email doesn't fail the payment response — the payment is the critical operation, the email is best-effort.

**Files Changed**:
- `app/modules/payments/router.py` — Added post-payment email via `email_invoice()` with fresh session

**Similar Bugs Found & Fixed**: The Stripe webhook handler (`handle_stripe_webhook`) already has a best-effort email, but it uses the old `brevo.send_email` (plain text, no PDF attachment). This should be upgraded to use `email_invoice()` in a future pass for consistency.

**Related Issues**: ISSUE-005 (fresh session needed after commit for email), ISSUE-037 (InvoiceList Record Payment modal)


---

### ISSUE-049: Record Payment returns 400 on second partial payment — missing partially_paid → partially_paid transition

- **Date**: 2026-03-11
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Recording a second partial payment on an invoice returns 400 Bad Request. The payment is still committed to the database (INSERT + UPDATE + COMMIT all succeed in logs) but the frontend shows "Failed to record payment" because it receives the 400 response.

**Root Cause**: The `VALID_TRANSITIONS` state machine in `app/modules/invoices/service.py` did not include `partially_paid → partially_paid` as a valid transition. When an invoice is already `partially_paid` and another partial payment is made (not enough to fully pay), the new status is still `partially_paid`. The `_validate_transition()` function raises `ValueError("Invalid status transition: partially_paid → partially_paid")` which the router catches and returns as 400. However, the `session.begin()` context manager still auto-commits the transaction on exit, so the payment INSERT and invoice UPDATE are committed despite the 400 response — causing a data inconsistency where the payment exists in the DB but the frontend thinks it failed.

**Fix Applied**: Added `"partially_paid"` to the allowed transitions from `partially_paid` in `VALID_TRANSITIONS`. Multiple partial payments on the same invoice is a normal workflow.

**Files Changed**:
- `app/modules/invoices/service.py` — Added `partially_paid → partially_paid` to VALID_TRANSITIONS

**Similar Bugs Found & Fixed**: The `overdue` status already correctly allows `overdue → partially_paid`. No other missing self-transitions found.

**Related Issues**: ISSUE-048 (Record Payment email feature), ISSUE-024 (same class of bug — transaction commits despite error)


---

### ISSUE-050: BookingForm search dropdowns reopen after selecting a customer or service item

- **Date**: 2026-03-11
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: When searching and selecting a customer or service item in the BookingForm modal, the dropdown closes momentarily but then reopens with search results, forcing the user to click/select again to dismiss it.

**Root Cause**: The search `useEffect` hooks for both customer and service catalogue run on every change to the search text. When a user selects an option, the `onClick` handler correctly sets `setShowCustomerDropdown(false)` / `setShowServiceDropdown(false)`, but then also sets the search text to the selected name (e.g. `setCustomerSearch('Arshdeep Singh')`). This triggers the search `useEffect` after 300ms, which re-runs the API search and sets `setShowCustomerDropdown(true)` again — reopening the dropdown.

**Fix Applied**:
1. Added `if (customerId) return` guard to the customer search `useEffect` — skips search when a customer is already selected (was partially applied in previous session)
2. Added `if (serviceCatalogueId) return` guard to the service catalogue search `useEffect` — same fix for service items
3. Changed customer `Input` `onChange` to always clear `customerId` when user types (not just on empty), so search re-enables if they want to change their selection
4. Changed service `Input` `onChange` to always clear `serviceCatalogueId`, `serviceType`, and `servicePrice` when user types, so search re-enables for changing selection
5. Added `customerId` and `serviceCatalogueId` to their respective `useEffect` dependency arrays

**Files Changed**:
- `frontend/src/pages/bookings/BookingForm.tsx` — Fixed customer and service search useEffects and onChange handlers

**Similar Bugs Found & Fixed**: Checked `VehicleLiveSearch` component — uses a different pattern (component unmounts search input when vehicle is selected, showing a summary view instead), so not affected. Checked `InvoiceCreate`, `QuoteCreate`, and `RecurringInvoices` customer search — `RecurringInvoices` uses `selectedCustomer` object to gate dropdown display (`!selectedCustomer`), already protected. `InvoiceCreate` and `QuoteCreate` use different search patterns not affected by this bug.

**Related Issues**: N/A


---

### ISSUE-051: Double scrolling on all pages — page content scrolls then entire app scrolls

- **Date**: 2026-03-11
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: ISSUE-039 (partial fix)

**Symptoms**: On any page where content is taller than the sidebar (e.g. Bookings with calendar + list), the page can be scrolled within the `<main>` area, but then the entire app/body also scrolls, creating a "double scroll" effect with empty space at the bottom.

**Root Cause**: Two issues working together:

1. **Missing `min-h-0` on flex column children**: The OrgLayout (and AdminLayout) use a flex column layout: root `h-screen overflow-hidden` → content area `flex flex-1 flex-col overflow-hidden` → `<main flex-1 overflow-y-auto>`. In CSS flexbox column layouts, `flex-1` sets `flex: 1 1 0%` but the default `min-height: auto` prevents the element from shrinking below its content size. When page content is tall, `<main>` grows beyond the available space, pushing the content area div beyond `h-screen`. The `overflow-hidden` clips visually but the document height still increases.

2. **No height/overflow constraint on html/body/#root**: The `html`, `body`, and `#root` elements had no `height: 100%` or `overflow: hidden`, so the browser's own scrollbar could appear when the document height exceeded the viewport (due to issue #1).

**Fix Applied**:
1. Added `min-h-0` to the main content area div (`flex flex-1 flex-col overflow-hidden min-h-0`) in both OrgLayout and AdminLayout — this allows the flex child to shrink below its content size
2. Added `min-h-0` to the `<main>` element (`flex-1 overflow-y-auto p-4 lg:p-6 min-h-0`) — belt-and-suspenders for the nested flex child
3. Added global CSS rule `html, body, #root { height: 100%; overflow: hidden; }` in `index.css` — prevents the browser from ever showing its own scrollbar on the document

**Files Changed**:
- `frontend/src/layouts/OrgLayout.tsx` — Added `min-h-0` to content area div and `<main>`
- `frontend/src/layouts/AdminLayout.tsx` — Same fix
- `frontend/src/index.css` — Added `html, body, #root { height: 100%; overflow: hidden; }`

**Similar Bugs Found & Fixed**: AdminLayout had the same pattern — fixed both. Auth pages (Login, Signup, etc.) use `min-h-screen` but they're standalone pages outside OrgLayout, so they're not affected.

**Related Issues**: ISSUE-039 (original broken scrolling fix — addressed page-level viewport heights but missed the flexbox `min-h-0` root cause)


---

### ISSUE-052: Create Job from Booking fails with FK violation — staff_member.id passed as assigned_to instead of user_id

- **Date**: 2026-03-11
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Clicking "Create Job" on a booking in the BookingListPanel returns 503 Service Unavailable. The job card is not created.

**Root Cause**: The `JobCreationModal` uses `StaffPicker` to select a staff member for assignment. `StaffPicker` fetches from `/api/v2/staff` which returns `staff_members.id` as the `id` field. This ID is sent as `assigned_to` in the POST body to `/bookings/{id}/convert?target=job_card`. The `convert_booking_to_job_card` function passes this directly to `create_job_card`, which inserts it into `job_cards.assigned_to`. However, `job_cards.assigned_to` has a foreign key constraint (`fk_job_cards_assigned_to`) referencing `users.id`, not `staff_members.id`. Since staff member IDs are different from user IDs, the FK constraint fails with `ForeignKeyViolationError`.

**Fix Applied**: Added staff_member.id → user_id resolution in `convert_booking_to_job_card`:
1. When `assigned_to` is provided, first look up `StaffMember.user_id` where `StaffMember.id == assigned_to`
2. If the staff member has a linked `user_id`, use that for the job card assignment
3. If not found as a staff member, check if it's already a valid `users.id` (backward compatibility)
4. If neither, pass `None` as `assigned_to` (graceful degradation — job card still created, just unassigned)
5. Also added `vehicle_rego=booking.vehicle_rego` to the `create_job_card` call which was missing

**Files Changed**:
- `app/modules/bookings/service.py` — Added staff→user ID resolution in `convert_booking_to_job_card`, added vehicle_rego passthrough

**Similar Bugs Found & Fixed**: The `BookingCalendarPage` also has a `handleConvert` function that calls the same endpoint but without a body (no `assigned_to`), so it's not affected. The `JobsPage` direct job creation uses `user_id` directly from auth context, not staff picker, so not affected.

**Related Issues**: N/A


---

### ISSUE-053: Job Cards list shows missing data — no rego, no assigned staff, wrong field mapping

- **Date**: 2026-03-11
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Job Cards list page shows "—" for rego and has no column for assigned staff. The "Job Card #" column always shows "—" because no such field exists on the model. When a job is created from a booking, the vehicle rego and assigned staff are not visible in the list.

**Root Cause**: Multiple frontend issues in `JobCardList.tsx`:
1. The `JobCardSummary` interface used `rego` but the backend returns `vehicle_rego` — field name mismatch
2. No `assigned_to_name` field in the interface, and no "Assigned To" column in the table
3. The `job_card_number` column was displayed but no such field exists on the `job_cards` DB table — always null
4. Frontend sent `page`/`page_size` params but backend expects `limit`/`offset`

**Fix Applied**:
1. Added `vehicle_rego` and `assigned_to_name` fields to the `JobCardSummary` interface
2. Replaced the "Job Card #" column with "Assigned To" column showing `assigned_to_name`
3. Fixed rego display to use `vehicle_rego` (with fallback to `rego` for backward compat)
4. Fixed pagination params to send `limit`/`offset` instead of `page`/`page_size`

**Files Changed**:
- `frontend/src/pages/job-cards/JobCardList.tsx` — Fixed interface, table columns, field mapping, and pagination params

**Similar Bugs Found & Fixed**: The backend `list_job_cards` service already joins `StaffMember` to resolve `assigned_to_name` and returns `vehicle_rego` — no backend changes needed.

**Related Issues**: ISSUE-052 (Create Job from Booking FK violation — fixed in same session)


---

### ISSUE-054: Job Card detail page missing most information — incomplete data mapping and minimal UI

- **Date**: 2026-03-11
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Clicking a job card in the list opens the detail page, but most information is missing: line items only show description (no type, qty, price, totals), time entries show wrong duration field (`duration_seconds` vs backend's `duration_minutes`), no cancel/complete actions, no editable assignee, no toast feedback.

**Root Cause**: The `JobCardDetail.tsx` component had several issues:
1. `JobCardItem` interface only had `id` and `description` — missing `item_type`, `quantity`, `unit_price`, `line_total`, `is_completed`, `sort_order`
2. `TimeEntry` interface used `duration_seconds` but backend returns `duration_minutes`
3. `TimeEntry` interface had `user_name` but backend doesn't return that field
4. Work items section only showed numbered descriptions — no pricing table
5. No cancel job action, no complete & invoice action
6. Assigned to section was read-only with no way to change assignee
7. Used `actionMessage` string instead of proper toast notifications

**Fix Applied**: Rewrote `JobCardDetail.tsx` with:
1. Full `JobCardItem` interface matching backend `JobCardItemResponse` schema
2. Fixed `TimeEntry` interface to use `duration_minutes` from backend
3. Line items now shown in a proper table with type badge, qty, unit price, line total, and subtotal footer
4. Added "Complete & Invoice" and "Cancel Job" action buttons for active jobs
5. Added editable assignee section with `StaffPicker` integration
6. Added proper toast notifications via `useToast`/`ToastContainer`
7. Added money/quantity formatting helpers

**Files Changed**:
- `frontend/src/pages/job-cards/JobCardDetail.tsx` — Complete rewrite with full data display

**Related Issues**: ISSUE-053


---

### ISSUE-055: Create Job from Booking — success animation and no-refresh UX

- **Date**: 2026-03-11
- **Severity**: low
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: When creating a job from a booking, the modal closes immediately and the booking list row updates, but there's no clear visual success feedback. User wanted an animated success indicator without page refresh.

**Fix Applied**: Enhanced `JobCreationModal` to show a brief animated success screen (green checkmark with SVG stroke animation) for 1.2 seconds before closing the modal and updating the booking row in-place. No page refresh occurs — the `BookingListPanel.markConverted` method updates the row with a green flash.

**Files Changed**:
- `frontend/src/pages/bookings/JobCreationModal.tsx` — Added success animation state and animated checkmark display


---

### ISSUE-056: create_job_card stores users.id or invalid ID as assigned_to — no staff member resolution

- **Date**: 2026-03-11
- **Severity**: medium
- **Status**: resolved
- **Reporter**: developer
- **Regression of**: N/A

**Symptoms**: Job cards created with an `assigned_to` value that is a `users.id` (instead of `staff_members.id`) would have the wrong FK stored, causing the `list_job_cards` join on `StaffMember.id == JobCard.assigned_to` to fail — resulting in null `assigned_to_name` in the list view.

**Root Cause**: The `create_job_card` function stored the `assigned_to` parameter directly without verifying it's a valid `staff_members.id`. While the booking conversion flow already resolved to `staff_members.id`, other callers (e.g. direct API calls) could pass a `users.id`.

**Fix Applied**: Added staff member ID resolution in `create_job_card`:
1. First check if `assigned_to` is a valid `staff_members.id` in the org
2. If not, try resolving as `users.id` → `staff_members.id`
3. If neither resolves, set `assigned_to` to `None` (graceful degradation)

**Files Changed**:
- `app/modules/job_cards/service.py` — Added staff member ID resolution in `create_job_card`

**Related Issues**: ISSUE-052, ISSUE-053


---

### ISSUE-057: greenlet_spawn error on update_job_card / assign_job — updated_at lazy refresh

- **Date**: 2026-03-11
- **Severity**: high
- **Status**: resolved
- **Reporter**: developer
- **Regression of**: N/A

**Symptoms**: PUT `/api/v1/job-cards/{id}` (status transition or assignment) returns 503 with `greenlet_spawn has not been called` error. The status change is rolled back.

**Root Cause**: The `JobCard.updated_at` column has `onupdate=func.now()`, which causes SQLAlchemy to expire the attribute after `db.flush()`. When `_job_card_to_dict` subsequently accesses `job_card.updated_at`, SQLAlchemy attempts a synchronous lazy-load refresh in an async context, triggering the greenlet error. The `selectinload(JobCard.customer)` fix from ISSUE-053 resolved the customer relationship lazy-load but not the column-level expiry.

**Fix Applied**: Added `await db.refresh(job_card)` after `db.flush()` in three functions:
1. `update_job_card` — after status/field changes and audit log
2. `assign_job` — after assignment change
3. `create_job_card` — after initial creation (server-generated `created_at`/`updated_at`)

**Files Changed**:
- `app/modules/job_cards/service.py` — Added `db.refresh(job_card)` in `update_job_card`, `assign_job`, `create_job_card`

---

### ISSUE-058: create_job_card customer lazy-load fragility

- **Date**: 2026-03-11
- **Severity**: low
- **Status**: resolved
- **Reporter**: developer
- **Regression of**: N/A

**Symptoms**: Potential `greenlet_spawn` error when creating a job card if the customer relationship isn't in the SQLAlchemy identity map.

**Root Cause**: `create_job_card` queries the `Customer` separately, creates a new `JobCard`, then calls `_job_card_to_dict` which accesses `job_card.customer`. The customer might not be populated on the new ORM instance.

**Fix Applied**: Explicitly set `job_card.customer = customer` after creating the `JobCard` instance, before `db.add()`.

**Files Changed**:
- `app/modules/job_cards/service.py` — Added explicit customer relationship assignment in `create_job_card`

---

### ISSUE-059: Mark Complete button uses wrong endpoint (PUT instead of POST /complete)

- **Date**: 2026-03-11
- **Severity**: medium
- **Status**: resolved
- **Reporter**: developer
- **Regression of**: N/A

**Symptoms**: "Mark Complete" button on job card detail page sends a PUT with `{ status: "completed" }` instead of using the POST `/complete` endpoint that also stops the timer and creates a draft invoice.

**Root Cause**: Frontend `JobCardDetail.tsx` used a generic `handleStatusTransition` for all status changes, including "Mark Complete". The dedicated `/complete` endpoint was never called.

**Fix Applied**: Rewrote `JobCardDetail.tsx`:
- "Mark Complete" now opens a confirmation modal and calls POST `/job-cards/{id}/complete`
- On success, navigates to the created invoice
- "Start Work" (Open → In Progress) still uses PUT
- Updated TypeScript interfaces to match backend response (`line_items` with full pricing, `duration_minutes` not `duration_seconds`, `notes` instead of `user_name` on time entries)
- Added line items table with grand total
- Time entries show `duration_minutes * 60` for proper formatting

**Files Changed**:
- `frontend/src/pages/job-cards/JobCardDetail.tsx` — Full rewrite with correct API calls and data model

**Related Issues**: ISSUE-056, ISSUE-057


---

### ISSUE-060: Customer search shows all results instead of filtering by sequential character match

- **Date**: 2026-03-11
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Typing "har" in the Customer Name search on InvoiceCreate shows customers that don't match (e.g. "Mr. Arshdeep Singh" alongside "Mr. Harjap Singh"). The search should only show customers where the typed characters appear in sequence in the first name, last name, phone number, or car rego.

**Root Cause**: The client-side filter used `.includes(term)` which is a simple substring match. This matched any customer where the search term appeared as a contiguous substring anywhere in the concatenated display name, email, or phone. It did not perform sequential character matching across individual fields (first name, last name, rego, phone). The backend `ILIKE '%term%'` also returns broad results, but the client-side filter was meant to be the precision layer.

**Fix Applied**: Replaced `.includes(term)` substring matching with a sequential character matching algorithm (`matchesSequence`) that checks if all characters in the search term appear in order within each field individually. The function iterates through the haystack and advances through the needle only when characters match in sequence. Fields checked: first_name, last_name, display_name, phone, company_name, and linked vehicle regos.

**Files Changed**:
- `frontend/src/pages/invoices/InvoiceCreate.tsx` — Updated CustomerSearch filter with matchesSequence
- `frontend/src/pages/quotes/QuoteCreate.tsx` — Same fix applied to customer search filter
- `frontend/src/pages/job-cards/JobCardCreate.tsx` — Same fix applied to customer search filter

**Similar Bugs Found & Fixed**: Same `.includes(term)` pattern existed in QuoteCreate and JobCardCreate — fixed all three.

**Related Issues**: ISSUE-028 (InvoiceCreate redesign), ISSUE-027 (customer creation modal)


---

### ISSUE-061: SMS sent from customer profile not tracked in usage reports

- **Date**: 2026-03-14
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: SMS sent via the "Send Email / SMS" button on the customer profile page does not appear in Reports → SMS Usage. The "Total SMS Sent" counter stays at 0. Emails sent from the same modal are also not logged in the notification log.

**Root Cause**: The `notify_customer()` function in `app/modules/customers/service.py` sends SMS via `ConnexusSmsClient.send()` and emails via SMTP, but never calls `increment_sms_usage()` (which atomically increments `org.sms_sent_this_month` — the field read by both the Reports SMS Usage page and the SMS Usage Summary widget). It also never calls `log_sms_sent()` or `log_email_sent()` to record the notification in the `notification_log` table. Every other SMS-sending path in the app (sms_chat, notifications/overdue reminders, payment receipts) correctly calls `increment_sms_usage` after a successful send.

**Fix Applied**:
1. Added `increment_sms_usage(db, org_id)` call after successful SMS send in `notify_customer`
2. Added `log_sms_sent()` for both successful and failed SMS sends
3. Added `log_email_sent()` for both successful and failed email sends
4. Added proper `client.close()` for httpx resource cleanup on the ConnexusSmsClient

**Files Changed**:
- `app/modules/customers/service.py` — Added SMS usage tracking, notification logging for both email and SMS paths, httpx client cleanup

**Similar Bugs Found & Fixed**: Checked all other SMS-sending paths (`sms_chat/service.py`, `notifications/service.py`, `payments/service.py`, `tasks/notifications.py`). All other paths already call `increment_sms_usage`. The `tasks/notifications.py` path does not close the httpx client but runs in a task context so it's lower priority.

**Related Issues**: ISSUE-062

---

### ISSUE-062: SMS provider credentials silently corrupted by masked values on re-save

- **Date**: 2026-03-14
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: SMS sending returns 401 Unauthorized from Connexus API at the token endpoint (`/auth/token`). The `client_id` and `client_secret` are not expired — regenerating and saving fresh credentials fixes the issue. The test function in Global Admin → SMS Providers works initially but SMS breaks after visiting the provider settings panel.

**Root Cause**: When the SMS Providers panel is expanded, the frontend loads saved credentials via `GET /{provider_key}/credentials`. The backend returns **masked** values (first 4 chars + `•` dots, e.g. `cid_••••••••••••`). These masked values were loaded directly into the form's editable input fields via `setCreds(res.data.credentials)`. If the user then clicked "Save credentials" — even without changing anything, or after changing just one field like sender_id — the masked values were sent back to the backend and saved as the actual credentials, overwriting the real `client_id`/`client_secret` with garbage like `cid_••••••••••••`. Subsequent SMS attempts used these corrupted credentials, causing Connexus to reject them with 401.

**Fix Applied**:

Frontend (`SmsProviders.tsx`):
1. Added separate `maskedCreds` state — masked values are stored for display as placeholders only, never in the editable `creds` state
2. Form inputs show masked values as placeholder text, not as editable values
3. Added hint text: "Only fill in fields you want to change. Blank fields keep their current value."

Backend (`sms_providers/service.py`):
1. `save_provider_credentials` now rejects any credential value containing the `•` masking character with a clear error message
2. Credentials are now merged with existing saved credentials — only fields with non-empty values are overwritten, so updating just sender_id won't wipe client_id/client_secret
3. Added `ValueError` handling in the router for the rejection case

Additional hardening (`connexus_sms.py`):
1. Added `.strip()` to all credential values in `ConnexusConfig.from_dict()` to prevent whitespace-related auth failures
2. Added `.strip()` in `_refresh_token()` payload
3. Added `close()` method to `ConnexusSmsClient` for proper httpx resource cleanup
4. Added detailed 401 logging (credential lengths, response body) for future debugging

**Files Changed**:
- `frontend/src/pages/admin/SmsProviders.tsx` — Separated masked display from editable state, placeholder-based UX
- `app/modules/sms_providers/service.py` — Masked value rejection, credential merging
- `app/modules/sms_providers/router.py` — ValueError handling for credential save
- `app/integrations/connexus_sms.py` — Whitespace stripping, close() method, 401 logging

**Similar Bugs Found & Fixed**: Checked email providers — the email provider credentials endpoint does not have a GET masked credentials endpoint, so the same bug pattern does not exist there. However, the email provider `save_email_credentials` also does a full overwrite rather than merge — this is lower risk since there's no masked-value loading, but could be improved in the future.

**Related Issues**: ISSUE-061

---

### ISSUE-063: ConnexusSmsClient httpx resource leak — client never closed

- **Date**: 2026-03-14
- **Severity**: low
- **Status**: resolved
- **Reporter**: agent
- **Regression of**: N/A

**Symptoms**: No user-visible symptoms. The `ConnexusSmsClient` creates an `httpx.AsyncClient` in `__init__` but never closes it. Each SMS send from `notify_customer`, `test_sms_provider`, and other paths creates a new client instance that leaks the underlying connection pool.

**Root Cause**: `ConnexusSmsClient` had no `close()` method. Callers created instances, used them, and let them be garbage collected without closing the httpx transport.

**Fix Applied**:
1. Added `async def close()` method to `ConnexusSmsClient` that calls `self._http.aclose()`
2. Updated `notify_customer` in `customers/service.py` to use try/finally with `client.close()`
3. Updated `_test_connexus` in `sms_providers/service.py` to use try/finally with `client.close()`

**Files Changed**:
- `app/integrations/connexus_sms.py` — Added `close()` method
- `app/modules/customers/service.py` — Added try/finally cleanup
- `app/modules/sms_providers/service.py` — Added try/finally cleanup

**Similar Bugs Found & Fixed**: Other callers (`tasks/notifications.py`, `sms_chat/service.py`, `payments/service.py`, `admin/service.py`) also create `ConnexusSmsClient` without closing. These are lower priority — task contexts and the chat service may benefit from connection reuse. Logged for future cleanup.

**Related Issues**: ISSUE-062

---

### ISSUE-064: SMS overage charge shows $0.00 — per-SMS cost not read from provider config

- **Date**: 2026-03-14
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Org admin SMS Usage report shows "Overage Charge: $0.00" despite 1 overage SMS and per-SMS cost of $0.11 configured in Global Admin → SMS Providers → Connexus → Pricing. The "Total SMS Sent" and "Overage Count" display correctly, but the cost calculation returns zero.

**Root Cause**: The per-SMS cost is stored in two places:
1. `subscription_plans.per_sms_cost_nzd` — plan-level cost (defaults to 0)
2. `sms_verification_providers.config.per_sms_cost_nzd` — provider-level cost (set to 0.11 by global admin)

Three functions in the backend only read from `plan.per_sms_cost_nzd` which is 0 by default. They never check the provider config as a fallback:
- `get_org_sms_usage()` in `admin/service.py`
- `get_all_orgs_sms_usage()` in `admin/service.py`
- `compute_sms_overage_for_billing()` in `admin/service.py`
- `get_usage_summary()` in `sms_chat/service.py`

**Fix Applied**:
1. Added `_get_provider_per_sms_cost()` helper in `admin/service.py` that queries the active Connexus provider's `config.per_sms_cost_nzd`
2. Updated all four functions to use `float(plan.per_sms_cost_nzd) or provider_cost` — falls back to provider config when plan cost is 0
3. This means the global admin's per-SMS cost setting in SMS Providers now correctly flows through to all usage calculations

**Files Changed**:
- `app/modules/admin/service.py` — Added `_get_provider_per_sms_cost()`, updated 3 functions
- `app/modules/sms_chat/service.py` — Updated `get_usage_summary()` with provider cost fallback

**Similar Bugs Found & Fixed**: All four cost calculation paths were affected and fixed in one pass.

**Related Issues**: ISSUE-061

---

### ISSUE-065: Global Admin dashboard Connexus SMS cost shows $0.00

- **Date**: 2026-03-14
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Global Admin Platform Dashboard → Integration Costs & Usage → Connexus SMS card shows Cost: $0.00 and Per Sms Cost Nzd: $0.00, despite per-SMS cost being configured as $0.11 in SMS Providers → Pricing.

**Root Cause**: In `get_integration_cost_dashboard()`, the SMS per-message cost was only read from the provider matching `is_active=True AND is_default=True`. If the Connexus provider is active but not set as default, `default_sms_provider` is `None` and `sms_per_msg_cost` stays at 0.0. The fallback `any_active` check only set status and last_checked — it never read the config for cost.

**Fix Applied**: Introduced `sms_provider_for_cost` variable that tracks whichever provider was found (default or any-active fallback). The per-SMS cost is now read from this provider after the status determination logic, so cost is correctly picked up regardless of whether the provider is marked as default.

**Files Changed**:
- `app/modules/admin/service.py` — Fixed `get_integration_cost_dashboard()` SMS cost lookup

**Similar Bugs Found & Fixed**: ISSUE-064 fixed the same class of bug (per-SMS cost not flowing through) in the org-level usage calculations.

**Related Issues**: ISSUE-064

---

### ISSUE-066: Connexus token not cached — fresh token requested on every API call

- **Date**: 2026-03-14
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Every SMS send, balance check, or number validation request to the Connexus API triggered a fresh token request to `/auth/token`. With 6 production call sites each creating a new `ConnexusSmsClient` instance, the app was making far more auth requests than necessary, risking Connexus API rate limits.

**Root Cause**: `ConnexusSmsClient` stored the Bearer token as instance attributes (`self._token`, `self._token_expires_at`). Since a new client instance is created for every operation (in `customers/service.py`, `sms_chat/service.py`, `sms_providers/service.py`, `payments/service.py`, `tasks/notifications.py`, `admin/service.py`), the token was never reused — each instance started with no token and immediately requested a new one. The 5-minute proactive refresh margin was useless because clients were discarded after each use.

**Fix Applied**:
1. Created a module-level `_TokenCache` class in `connexus_sms.py` that stores tokens keyed by `(client_id, api_base_url)` with per-key `asyncio.Lock` to prevent thundering-herd refreshes
2. `_token_cache` singleton is shared across all `ConnexusSmsClient` instances in the process
3. `_ensure_token()` uses double-check locking: fast path checks cache, slow path acquires lock and rechecks before refreshing
4. `_request()` on 401 invalidates the cached token then calls `_ensure_token()` which refreshes
5. Removed `self._token` and `self._token_expires_at` instance attributes
6. Token is now reused for ~55 minutes (refreshed 5 min before 1-hour expiry) across all requests

**Files Changed**:
- `app/integrations/connexus_sms.py` — Rewrote token management with shared `_TokenCache`
- `tests/test_connexus_client.py` — Updated to use `_token_cache` instead of instance attrs, fixed `data` vs `json` payload assertions
- `tests/properties/test_connexus_properties.py` — Updated P5/P6 tests to use `_token_cache.put()`, fixed `data` vs `json` payload assertions in P2

**Similar Bugs Found & Fixed**: Fixed pre-existing test bugs where payload assertions used `["json"]` key but `send()` and `validate_number()` pass `data=` to `_request`. These tests would have failed if the mock layer was stricter.

**Related Issues**: ISSUE-062, ISSUE-063

---

### ISSUE-067: SMS sends and scheduled reminders trigger token refresh — should be background-only

- **Date**: 2026-03-14
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Every SMS send, balance check, or scheduled reminder that hits the Connexus API could trigger a token refresh if the cached token was near expiry. This meant user-facing operations (sending SMS, auto-reminders) had unpredictable latency spikes when a token refresh was needed, and risked hitting Connexus API rate limits if multiple concurrent sends all tried to refresh simultaneously.

**Root Cause**: `_ensure_token()` performed proactive refresh when the token was within 5 minutes of expiry. Since `_ensure_token()` was called on every API request, any SMS send or scheduled reminder could trigger a token refresh. There was no separation between "read token from cache" and "refresh token proactively."

**Fix Applied**:
1. Added `_TokenRefresher` background task class that runs as an `asyncio.Task` started at app boot. It reads the Connexus provider config from DB, refreshes the token on the configured interval, and deposits it in the shared `_token_cache`. This is the only code path that proactively refreshes tokens in production.
2. `_ensure_token()` now only reads from cache using `get_unexpired()` (no margin). It only falls back to a direct refresh when no token exists at all (bootstrap/first-boot case).
3. `_request()` on 401: instead of immediately refreshing, it invalidates the stale token and calls `_wait_for_fresh_token()` which polls the cache for up to 4 seconds waiting for the background refresher to deposit a new token. If the background refresher doesn't provide one in time, falls back to a direct refresh as last resort.
4. Added `get_unexpired()` method to `_TokenCache` — returns token if not yet expired (ignoring margin).
5. Added `event_for()` and `_refresh_events` to `_TokenCache` — `asyncio.Event` per credential set, fired when `put()` stores a new token, so `_wait_for_fresh_token()` can wake up immediately.
6. Registered `_token_refresher.start()` on FastAPI startup and `_token_refresher.stop()` on shutdown in `app/main.py`.

**Files Changed**:
- `app/integrations/connexus_sms.py` — Added `_TokenRefresher`, `_wait_for_fresh_token()`, `get_unexpired()`, event mechanism; rewrote `_ensure_token()` and `_request()` 401 handling
- `app/main.py` — Added startup/shutdown hooks for `_token_refresher`
- `tests/test_connexus_client.py` — Updated `TestEnsureToken` (no proactive refresh), `TestRequest` (401 wait-and-retry), added `test_401_falls_back_to_direct_refresh`
- `tests/properties/test_connexus_properties.py` — Renamed P6 to `TestProperty6NoInlineRefresh`, updated to verify API calls never trigger refresh

**Similar Bugs Found & Fixed**: N/A — this was a design improvement, not a bug pattern.

**Related Issues**: ISSUE-066


---

### ISSUE-068: BookingForm customer search sends wrong API params — shows all customers instead of matches

- **Date**: 2026-03-14
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: ISSUE-060 (fix was applied to InvoiceCreate, QuoteCreate, JobCardCreate but missed BookingForm)

**Symptoms**: Typing "Harjap" in the Customer search on the New Booking form shows "Arshdeep Singh" (and other non-matching customers). The search should only show customers whose name, phone, email, or vehicle rego matches the typed text.

**Root Cause**: Two issues:
1. BookingForm sent `search` as the query parameter but the backend `/customers` endpoint expects `q`. Since `q` was `None`, the backend returned ALL customers unfiltered.
2. BookingForm also sent `page_size` but the backend expects `limit`. The wrong param name meant no limit was applied.
3. BookingForm had no client-side `matchesSequence` filter — the fix from ISSUE-060 was applied to InvoiceCreate, QuoteCreate, and JobCardCreate but BookingForm was missed.

**Fix Applied**:
1. Changed API params from `{ search: customerSearch, page_size: 8 }` to `{ q: customerSearch, limit: 8 }`
2. Added client-side `matchesSequence` sequential character filter (same algorithm as ISSUE-060) that checks first_name, last_name, full name, phone, email, and linked vehicle regos

**Files Changed**:
- `frontend/src/pages/bookings/BookingForm.tsx`

**Similar Bugs Found & Fixed**: Checked all other customer search implementations — InvoiceCreate, QuoteCreate, JobCardCreate already have the correct `q` param and `matchesSequence` filter from ISSUE-060.

**Related Issues**: ISSUE-060

---

### ISSUE-069: "Confirm & Invoice" button stuck loading — missing _resolve_customer_id_from_dict function

- **Date**: 2026-03-14
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A (incomplete refactor)

**Symptoms**: Clicking "Confirm & Invoice" on a booking causes the button to spin indefinitely. Backend returns 500. The "Mark Complete" flow on job cards works fine.

**Root Cause**: `convert_booking_to_invoice` was partially rewritten to use the `get_booking()` dict pattern (matching the working `convert_job_card_to_invoice` flow), but the `_resolve_customer_id_from_dict` helper it calls was never created. The function crashed with a `NameError` at runtime.

**Fix Applied**:
1. Created `_resolve_customer_id_from_dict(db, org_id, bk)` that resolves customer from a booking dict using three strategies: email match → display_name match → first/last name split match
2. Refactored the old ORM-based `_resolve_customer_id` to delegate to the new dict-based version to eliminate duplicated logic

**Files Changed**:
- `app/modules/bookings/service.py`

**Related Issues**: ISSUE-057 (same MissingGreenlet pattern)

---

### ISSUE-070: Public holiday sync fires on every app restart — no DB-level dedup

- **Date**: 2026-03-14
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user

**Symptoms**: Audit logs show `calendar.sync_public_holidays` firing every 30s–2min in dev, producing 4 entries per cycle (NZ×2 years + AU×2 years). Should be a one-time sync stored in DB.

**Root Cause**: The scheduler uses in-memory `last_run` dict initialized to `0.0` on startup. In dev mode with `--reload`, every Python file save restarts uvicorn, which resets `last_run` and triggers all tasks immediately — including the 6-month holiday sync. No DB-level check existed to skip redundant syncs.

**Fix Applied**: Added a DB-level guard in `sync_public_holidays_task` that checks `MAX(synced_at)` from the `public_holidays` table. If holidays were synced within the last 24 hours, the task returns early with `{"skipped": True}`. Manual syncs via the admin API endpoint are unaffected.

**Files Changed**:
- `app/tasks/scheduled.py`

---

### ISSUE-071: "Confirm & Invoice" returns 500 — float passed where Decimal expected

- **Date**: 2026-03-14
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: ISSUE-069 (incomplete refactor)

**Symptoms**: Clicking "Confirm & Invoice" on a booking shows the confirmation popup, user clicks confirm, API returns 500 with `'float' object has no attribute 'quantize'`. Frontend shows error toast and button resets — user can click again in a loop but it always fails.

**Root Cause**: `convert_booking_to_invoice` built line items with `unit_price` as a Python `float` (`price = float(bk["service_price"])`). The downstream `_calculate_invoice_totals` in `invoices/service.py` calls `.quantize()` on `unit_price`, which is a `Decimal`-only method. The `convert_job_card_to_invoice` reference implementation doesn't have this issue because job card line items store prices as `Decimal` already.

**Fix Applied**:
1. Changed `float(bk["service_price"])` → `Decimal(str(bk["service_price"]))` in `convert_booking_to_invoice`
2. Added broader exception handler in `convert_booking_endpoint` router to log and return meaningful 500 errors instead of generic FastAPI 500
3. Made `_resolve_customer_id_from_dict` case-insensitive and added phone-based fallback
4. Created `scripts/test_confirm_invoice.py` end-to-end test script that authenticates and exercises the full flow

**Verified**: Test script confirms 200 OK with valid `created_id` — frontend would navigate to `/invoices/{id}/edit`.

**Files Changed**:
- `app/modules/bookings/service.py` — Decimal fix + improved customer resolution
- `app/modules/bookings/router.py` — broader exception handling in convert endpoint
- `scripts/test_confirm_invoice.py` — end-to-end test script

**Related Issues**: ISSUE-069


---

### ISSUE-072: Disable Stripe features for org users — pending full implementation

- **Date**: 2026-03-15
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Stripe-related UI elements (payment gateway selector, billing buttons, portal payment page) were visible and clickable for org users despite Stripe not being connected or configured. Clicking them would fail silently or error.

**Root Cause**: Frontend was built with Stripe UI elements assuming Stripe Connect would be configured. No org has connected a Stripe account yet, so all Stripe-dependent features are non-functional.

**Fix Applied**:
1. **InvoiceCreate.tsx** — Disabled Stripe radio button in payment gateway selector, added "(coming soon)" label
2. **PaymentPanel.tsx** — Removed "via Stripe" from card payment text, now says generic "card terminal"
3. **PaymentPage.tsx** (portal) — Replaced Stripe checkout redirect with "Online payments coming soon" message
4. **TemplateEditor.tsx** — Changed `{{payment_link}}` description from "Stripe payment link" to "Online payment link (coming soon)"
5. **Billing.tsx** — Disabled "Update payment method", "Upgrade plan", "Downgrade plan", and "Buy more storage" buttons with tooltips explaining Stripe integration is pending. Removed StorageAddonModal and Stripe handler functions.
6. **InvoiceList.tsx** / **InvoiceDetail.tsx** — Expanded payment method type from `'cash' | 'stripe'` to include `'eftpos' | 'bank_transfer' | 'card' | 'cheque'`
7. Created `docs/STRIPE_IMPLEMENTATION.md` reference doc documenting all existing backend code, disabled frontend features, and phased implementation plan

**Files Changed**:
- `frontend/src/pages/invoices/InvoiceCreate.tsx`
- `frontend/src/pages/pos/PaymentPanel.tsx`
- `frontend/src/pages/portal/PaymentPage.tsx`
- `frontend/src/pages/notifications/TemplateEditor.tsx`
- `frontend/src/pages/settings/Billing.tsx`
- `frontend/src/pages/invoices/InvoiceList.tsx`
- `frontend/src/pages/invoices/InvoiceDetail.tsx`
- `docs/STRIPE_IMPLEMENTATION.md` (new)

**Backend**: No changes — all Stripe backend code left intact for future use.

**Related Issues**: None

**Reference**: See `docs/STRIPE_IMPLEMENTATION.md` for full implementation roadmap.

---

### ISSUE-073: Bulk delete invoices fails with 503 — NOT NULL violation on payments.invoice_id

- **Date**: 2026-03-15
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: `POST /api/v1/invoices/bulk-delete` returns 503 (Service Unavailable). Backend traceback shows `asyncpg.exceptions.NotNullViolationError: null value in column "invoice_id" of relation "payments" violates not-null constraint`.

**Root Cause**: The `Invoice` model's `payments` and `credit_notes` relationships were missing `cascade="all, delete-orphan"`. When SQLAlchemy's `db.delete(inv)` ran during bulk delete, it defaulted to setting `invoice_id = NULL` on related payments/credit_notes before removing the invoice row. But `invoice_id` is NOT NULL on both tables, causing the IntegrityError.

The `line_items` relationship already had `cascade="all, delete-orphan"` configured correctly — payments and credit_notes were simply missed.

**Fix Applied**:
1. Added `cascade="all, delete-orphan"` to `Invoice.payments` relationship
2. Added `cascade="all, delete-orphan"` to `Invoice.credit_notes` relationship

**Files Changed**:
- `app/modules/invoices/models.py`

**Similar Bugs Found & Fixed**: See ISSUE-074 for additional FK violations discovered during the same fix.

**Related Issues**: ISSUE-074

---

### ISSUE-074: Bulk delete invoices fails with FK violation on odometer_readings, tips, pos_transactions

- **Date**: 2026-03-15
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: After fixing ISSUE-073, bulk delete still fails with `asyncpg.exceptions.ForeignKeyViolationError: update or delete on table "invoices" violates foreign key constraint "odometer_readings_invoice_id_fkey" on table "odometer_readings"`. Three additional tables reference `invoices.id` with no ON DELETE action.

**Root Cause**: Five tables reference `invoices.id` via foreign keys, but only `line_items` had proper cascade handling:
- `payments.invoice_id` — NOT NULL, no ON DELETE CASCADE (fixed in ISSUE-073 at ORM level)
- `credit_notes.invoice_id` — NOT NULL, no ON DELETE CASCADE (fixed in ISSUE-073 at ORM level)
- `odometer_readings.invoice_id` — nullable, no ON DELETE SET NULL
- `tips.invoice_id` — nullable, no ON DELETE SET NULL
- `pos_transactions.invoice_id` — nullable, no ON DELETE SET NULL

The nullable FK tables need SET NULL (not CASCADE) since those records should survive independently.

**Fix Applied**:

ORM level:
1. Added explicit `UPDATE ... SET invoice_id = NULL` queries in `bulk_delete_invoices()` for odometer_readings, tips, and pos_transactions before deleting invoices
2. Added `update` import from sqlalchemy in `app/modules/invoices/service.py`

Database level (migration 0092):
3. Created Alembic migration `0092_fix_invoice_fk_cascade.py` to add proper ON DELETE actions:
   - `payments.invoice_id` → ON DELETE CASCADE
   - `credit_notes.invoice_id` → ON DELETE CASCADE
   - `odometer_readings.invoice_id` → ON DELETE SET NULL
   - `tips.invoice_id` → ON DELETE SET NULL
   - `pos_transactions.invoice_id` → ON DELETE SET NULL

Original migrations patched for fresh deployments:
4. Updated migration `0005` (payments, credit_notes) with `ondelete="CASCADE"`
5. Updated migration `0040` (pos_transactions) with `ondelete="SET NULL"`
6. Updated migration `0045` (tips) with `ondelete="SET NULL"`
7. Updated migration `0075` (odometer_readings) with `ondelete="SET NULL"`

SQLAlchemy models updated to match DB:
8. `Payment.invoice_id` — added `ondelete="CASCADE"`
9. `CreditNote.invoice_id` — added `ondelete="CASCADE"`
10. `OdometerReading.invoice_id` — added `ondelete="SET NULL"`
11. `Tip.invoice_id` — added `ondelete="SET NULL"`
12. `POSTransaction.invoice_id` — added `ondelete="SET NULL"`

**Files Changed**:
- `app/modules/invoices/service.py` (bulk_delete_invoices + update import)
- `app/modules/invoices/models.py` (CreditNote FK)
- `app/modules/payments/models.py` (Payment FK)
- `app/modules/vehicles/models.py` (OdometerReading FK)
- `app/modules/tipping/models.py` (Tip FK)
- `app/modules/pos/models.py` (POSTransaction FK)
- `alembic/versions/2026_03_15_1100-0092_fix_invoice_fk_cascade.py` (new)
- `alembic/versions/2025_01_15_0005-0005_create_invoice_payment_tables.py` (patched)
- `alembic/versions/2025_01_15_0040-0040_create_pos_transactions.py` (patched)
- `alembic/versions/2025_01_15_0045-0045_create_tips_tables.py` (patched)
- `alembic/versions/2026_03_10_0900-0075_add_odometer_readings_table.py` (patched)

**Similar Bugs Found & Fixed**: All 5 FK references to invoices.id were audited and fixed in one pass.

**Related Issues**: ISSUE-073

---

### ISSUE-075: GST Return report ignores refunds — shows original GST instead of adjusted amount

- **Date**: 2026-03-15
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Invoice INV-0008 was partially refunded ($50 of $172.50), showing correct adjusted amounts on the invoice detail page (Net Amount $106.52, GST Collected $15.98, Net Total $122.50). However, the GST Return report tab still showed the full original GST of $22.50 with no indication of the refund.

**Root Cause**: The `get_gst_return()` function in `app/modules/reports/service.py` only queried `Invoice.gst_amount` and `Invoice.total` — it had no awareness of credit notes or refund payments. The function simply summed invoice totals within the date range without subtracting any refunds processed in that period.

Additionally, the frontend was sending `from`/`to` query params but the backend expected `start_date`/`end_date`, meaning the date filter dropdown never actually worked — the backend always fell back to "current month" via `resolve_date_range()`.

**Fix Applied**:

Backend:
1. Updated `get_gst_return()` to query `credit_notes` table for refunds processed within the selected period (using `credit_notes.created_at` date, not the original invoice date)
2. Calculates GST component of refunds using NZ 15% rate (refund × 3/23)
3. Returns new fields: `total_refunds`, `refund_gst`, `adjusted_total_sales`, `adjusted_gst_collected`
4. `net_gst` now reflects the adjusted GST after refunds
5. Updated `GSTReturnResponse` schema with the 4 new fields

Frontend:
6. Updated `GstData` interface with new refund fields
7. Added refund breakdown rows (conditionally shown when refunds > 0): Refunds/Credit Notes, GST on refunds, Adjusted Sales, Adjusted GST Collected
8. Fixed query params: `from`/`to` → `start_date`/`end_date` to match backend expectations
9. Added `fmtNeg` formatter for negative currency display

**Files Changed**:
- `app/modules/reports/service.py` (get_gst_return)
- `app/modules/reports/schemas.py` (GSTReturnResponse)
- `frontend/src/pages/reports/GstReturnSummary.tsx`

**Design Decision**: Refunds are attributed to the period they were processed (credit note `created_at`), not the original invoice date. This matches NZ IRD GST return filing requirements — if you invoice in February and refund in March, the February return shows full GST and the March return shows the GST adjustment.

**Related Issues**: None


---

### ISSUE-076: Revenue tab ignores refunds — shows original revenue without refund adjustment

- **Date**: 2026-03-15
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Revenue summary tab shows $150 total revenue and $22.50 GST for the period, but a $50 refund was processed on one of the invoices. The revenue figures don't reflect the refund.

**Root Cause**: Same pattern as ISSUE-075 — `get_revenue_summary()` only queried invoice totals without accounting for refunds (credit notes + refund payments).

**Fix Applied**:

Backend:
1. Added refund queries to `get_revenue_summary()` — queries both `credit_notes` and `payments` (where `is_refund=True`) within the date range
2. Calculates refund GST component using NZ 15% rate (refund × 3/23)
3. Returns new fields: `total_refunds`, `refund_gst`, `net_revenue`, `net_gst`
4. Updated `RevenueSummaryResponse` schema with the 4 new fields

Frontend:
5. Updated summary cards to show refund amounts in red and net amounts in green
6. Fixed query params: `from`/`to` → `start_date`/`end_date`

**Files Changed**:
- `app/modules/reports/service.py` (get_revenue_summary)
- `app/modules/reports/schemas.py` (RevenueSummaryResponse)
- `frontend/src/pages/reports/RevenueSummary.tsx`

**Related Issues**: ISSUE-075

---

### ISSUE-077: Date filter param mismatch across ALL report tabs — filters never applied

- **Date**: 2026-03-15
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Changing the date range filter on any report tab had no effect — the data always showed the current month. The filter appeared to work (UI updated) but the API always returned default data.

**Root Cause**: Systemic frontend/backend param name mismatch. All report frontends sent `from`/`to` query params, but the v1 backend endpoints expect `start_date`/`end_date`. When the backend received `None` for both params, `resolve_date_range()` fell back to "current month".

Exception: Carjam Usage endpoint uses `alias="from"` / `alias="to"` in its Query params, so `from`/`to` is correct for that tab.

**Fix Applied**: Updated API call params AND ExportButtons params on all affected tabs:
- Revenue Summary: `from`/`to` → `start_date`/`end_date`
- GST Return: `from`/`to` → `start_date`/`end_date`
- Invoice Status: `from`/`to` → `start_date`/`end_date`
- Outstanding Invoices: `from`/`to` → `start_date`/`end_date`
- Top Services: `from`/`to` → `start_date`/`end_date`
- Fleet Report: `from`/`to` → `start_date`/`end_date`
- Customer Statement: `from`/`to` → `start_date`/`end_date`
- SMS Usage: `from`/`to` → `start_date`/`end_date`

Carjam Usage left as `from`/`to` (correct — backend uses aliases).

**Files Changed**:
- `frontend/src/pages/reports/RevenueSummary.tsx`
- `frontend/src/pages/reports/GstReturnSummary.tsx`
- `frontend/src/pages/reports/TopServices.tsx`
- `frontend/src/pages/reports/InvoiceStatus.tsx`
- `frontend/src/pages/reports/OutstandingInvoices.tsx`
- `frontend/src/pages/reports/FleetReport.tsx`
- `frontend/src/pages/reports/CustomerStatement.tsx`
- `frontend/src/pages/reports/SmsUsage.tsx`

**Related Issues**: ISSUE-075, ISSUE-076

---

### ISSUE-078: Carjam & SMS summary cards not respecting date filter — show running counters instead of period data

- **Date**: 2026-03-15
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: On the Carjam Usage tab, the daily lookup chart correctly filtered by date range, but the summary cards (Total Lookups, Overage Lookups, Overage Charge) always showed the running monthly counter from `Organisation.carjam_lookups_this_month` regardless of the selected period. Same issue on SMS Usage — summary cards read from org-level counters instead of querying actual data within the date range.

**Root Cause**:

Carjam: `get_carjam_usage()` read `Organisation.carjam_lookups_this_month` for the Total Lookups summary card — a running counter that resets monthly. The daily breakdown was correctly queried from the audit log with date filtering, but the summary card value was disconnected from the date range.

SMS: `get_sms_usage()` delegated to `get_org_sms_usage()` which reads `Organisation.sms_sent_this_month` — another running counter with no date filtering. The function had no `date_from`/`date_to` parameters at all.

**Fix Applied**:

Carjam:
1. Rewrote `get_carjam_usage()` to count total lookups from the audit log within the date range (same source as daily breakdown) instead of reading the org counter
2. Overage and overage charge now calculated from the date-filtered count

SMS:
1. Rewrote `get_sms_usage()` to count outbound messages from `sms_messages` table filtered by date range instead of reading org counters
2. Added `date_from`/`date_to` parameters to the function signature
3. Updated SMS router endpoint to accept `start_date`/`end_date` query params and pass them through
4. Updated SMS frontend to send `start_date`/`end_date` instead of `from`/`to`

**Files Changed**:
- `app/modules/reports/service.py` (get_carjam_usage, get_sms_usage)
- `app/modules/reports/router.py` (sms-usage endpoint params)
- `frontend/src/pages/reports/SmsUsage.tsx` (param fix)

**Related Issues**: ISSUE-077


---

### ISSUE-079: Additional vehicles selected during invoice creation not saved or displayed

- **Date**: 2026-03-15
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: When creating an invoice, user selects a customer with a linked vehicle (primary), then adds 3 additional vehicles via the vehicle search. After issuing the invoice, only the primary vehicle appears on the invoice detail view. The additional vehicles are lost.

**Root Cause**: The frontend correctly sends a `vehicles` array containing all selected vehicles (primary + additional) in the create invoice payload. However:
1. The `create_invoice` service function had no `vehicles` parameter — the array was silently ignored
2. The Invoice model only has single-vehicle fields (`vehicle_rego`, `vehicle_make`, etc.) — no mechanism to store multiple vehicles
3. The router never passed the `vehicles` array to the service
4. The invoice detail response never included additional vehicles

**Fix Applied**:

Backend:
1. Added `vehicles` parameter to `create_invoice()` service function
2. Additional vehicles (index 1+) stored in `invoice_data_json["additional_vehicles"]` JSONB field — no migration needed
3. Router now passes `vehicles` from the request payload to the service
4. `_invoice_to_dict()` includes `additional_vehicles` from `invoice_data_json` in all responses
5. `get_invoice()` enriches additional vehicles with GlobalVehicle data (make, model, year, WOF expiry, odometer)
6. `update_invoice()` handles `vehicles` in updates dict — stores additional vehicles in `invoice_data_json`
7. Added `vehicles` field to `UpdateInvoiceRequest` schema
8. Added `additional_vehicles` field to `InvoiceResponse` schema

Frontend:
9. `InvoiceDetail.tsx` — added `additional_vehicles` to interface, renders additional vehicles below the primary vehicle section
10. `InvoiceList.tsx` — added `additional_vehicles` to interface, renders additional vehicle bars in the invoice card view

**Design Decision**: Additional vehicles are stored in the existing `invoice_data_json` JSONB column rather than creating a new junction table. This avoids a migration and keeps the data co-located with the invoice. The primary vehicle remains in the dedicated columns (`vehicle_rego`, `vehicle_make`, etc.) for backward compatibility and query performance.

**Files Changed**:
- `app/modules/invoices/service.py` (create_invoice, update_invoice, _invoice_to_dict, get_invoice)
- `app/modules/invoices/router.py` (pass vehicles to service)
- `app/modules/invoices/schemas.py` (InvoiceResponse, UpdateInvoiceRequest)
- `frontend/src/pages/invoices/InvoiceDetail.tsx` (display additional vehicles)
- `frontend/src/pages/invoices/InvoiceList.tsx` (display additional vehicles in card view)

**Related Issues**: None

---

### ISSUE-080: Print view shows report tabs, heading, and description text

- **Date**: 2026-03-16
- **Severity**: low
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: When clicking Print on any report tab (e.g. Customer Statement), the print preview includes the tab navigation bar (Revenue, Invoice Status, Outstanding, etc.), the "Reports" page heading, and description text. Only the report content should be printed.

**Root Cause**: The `Tabs` component's tab list `div[role="tablist"]` and the `ReportsPage` heading did not have the `no-print` CSS class. The existing `print.css` already hides `.no-print` elements via `@media print`, but these elements were not marked.

**Fix Applied**:
1. Added `no-print` class to `div[role="tablist"]` in `Tabs.tsx` — hides tab navigation in print
2. Added `no-print` class to `<h1>Reports</h1>` in `ReportsPage.tsx` — hides page heading in print
3. Added `no-print` class to description `<p>` in `CustomerStatement.tsx` — hides helper text in print

**Files Changed**:
- `frontend/src/components/ui/Tabs.tsx`
- `frontend/src/pages/reports/ReportsPage.tsx`
- `frontend/src/pages/reports/CustomerStatement.tsx`

**Related Issues**: None

---

### ISSUE-081: Date range presets show rolling periods instead of calendar periods

- **Date**: 2026-03-16
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Selecting "Last year" in the Period dropdown shows a rolling 12-month window (e.g. 15 Mar 2025 — 15 Mar 2026) instead of the previous calendar year (1 Jan 2025 — 31 Dec 2025). Similarly, "Last month" and "Last quarter" showed rolling periods rather than the previous calendar month/quarter.

**Root Cause**: The `presetRange()` function in `DateRangeFilter.tsx` used relative date arithmetic (`d.setFullYear(d.getFullYear() - 1)`) which produces a rolling window from today, not a calendar period. For "Last year", this gave today minus 1 year → today. For "Last month", it gave today minus 1 month → today. For "Last quarter", today minus 3 months → today.

**Fix Applied**:
1. "Last year" now returns 1 Jan — 31 Dec of the previous year
2. "Last month" now returns 1st — last day of the previous calendar month
3. "Last quarter" now returns 1st day of previous quarter — last day of previous quarter
4. Changed `to` from `const` to `let` so it can be reassigned per preset

**Similar Bugs Found & Fixed**:
- All `defaultRange()` functions across report tabs used `from.setMonth(from.getMonth() - N)` which has a JavaScript month-rollover edge case (e.g. March 31 minus 1 month = March 3, not Feb 28). Fixed all 12 instances to use `new Date(year, month - N, 1)` which is safe.
- Added `no-print` class to description paragraphs in all 9 report tabs (Revenue, Invoice Status, Outstanding, Top Services, GST Return, Carjam, SMS, Storage, Fleet) — completing the print view fix from ISSUE-080.

**Files Changed**:
- `frontend/src/pages/reports/DateRangeFilter.tsx` (preset calculations)
- `frontend/src/pages/reports/RevenueSummary.tsx` (defaultRange + no-print)
- `frontend/src/pages/reports/InvoiceStatus.tsx` (defaultRange + no-print)
- `frontend/src/pages/reports/OutstandingInvoices.tsx` (defaultRange + no-print)
- `frontend/src/pages/reports/TopServices.tsx` (defaultRange + no-print)
- `frontend/src/pages/reports/GstReturnSummary.tsx` (no-print)
- `frontend/src/pages/reports/CarjamUsage.tsx` (no-print)
- `frontend/src/pages/reports/SmsUsage.tsx` (no-print)
- `frontend/src/pages/reports/StorageUsage.tsx` (no-print)
- `frontend/src/pages/reports/FleetReport.tsx` (defaultRange + no-print)
- `frontend/src/pages/reports/JobReport.tsx` (defaultRange)
- `frontend/src/pages/reports/InventoryReport.tsx` (defaultRange)
- `frontend/src/pages/reports/HospitalityReport.tsx` (defaultRange)
- `frontend/src/pages/reports/ProjectReport.tsx` (defaultRange)
- `frontend/src/pages/reports/ReportBuilder.tsx` (defaultRange)
- `frontend/src/pages/admin/Reports.tsx` (defaultRange)

**Related Issues**: ISSUE-080

---

### ISSUE-082: React "unique key" warning in OutstandingInvoices and other report tabs

- **Date**: 2026-03-16
- **Severity**: low
- **Status**: resolved
- **Reporter**: user (console warning)
- **Regression of**: N/A

**Symptoms**: Console warning: "Each child in a list should have a unique 'key' prop" in `OutstandingInvoices.tsx` at line 114. Occurs when the backend returns items with undefined or duplicate `id` fields.

**Root Cause**: Several report tab `.map()` calls used object properties as React keys (e.g. `inv.id`, `v.rego`, `s.status`, `item.payment_method`, `item.hour`, `b.category`, `s.id`) without index fallbacks. If the backend returns undefined or duplicate values for these fields, React warns about missing/duplicate keys.

**Fix Applied**: Added index fallback to all `.map()` key props across report tabs: `key={value || index}` or `key={value ?? index}`.

**Files Changed**:
- `frontend/src/pages/reports/OutstandingInvoices.tsx`
- `frontend/src/pages/reports/FleetReport.tsx`
- `frontend/src/pages/reports/POSReport.tsx` (2 instances)
- `frontend/src/pages/reports/StorageUsage.tsx`
- `frontend/src/pages/reports/ScheduledReports.tsx`
- `frontend/src/pages/reports/InvoiceStatus.tsx`

**Related Issues**: None


---

### ISSUE-083: 422 Unprocessable Content on PUT /invoices/{id} (save draft)

- **Date**: 2026-03-16
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user (browser console)
- **Regression of**: N/A

**Symptoms**: Clicking "Save as Draft" on an existing invoice returns 422 Unprocessable Content. The PUT request to `/api/v1/invoices/{id}` fails Pydantic validation because the frontend sends fields that the `UpdateInvoiceRequest` schema doesn't recognize, and sends empty strings for optional UUID fields.

**Root Cause**: Five issues in the invoice update flow:

1. `UpdateInvoiceRequest` schema was missing `model_config = {"extra": "ignore"}` — the frontend sends many extra fields (`order_number`, `salesperson_id`, `subject`, `gst_number`, `payment_gateway`, `is_recurring`, `invoice_number`) that Pydantic rejects by default.
2. `UpdateInvoiceRequest` was missing fields that the frontend sends and the backend should process: `line_items`, `issue_date`, `currency`, `payment_terms`, `terms_and_conditions`, `shipping_charges`, `adjustment`.
3. `VehicleItem` schema (nested in the vehicles array) was missing `model_config = {"extra": "ignore"}`, the `odometer` field, and had `id: uuid.UUID` as required — the frontend sends `id: ''` (empty string) for vehicles loaded from existing invoices that don't have a `global_vehicle_id`.
4. The `update_invoice()` service function didn't handle `line_items` (delete + recreate), `issue_date`/`currency` (direct columns), or `payment_terms`/`terms_and_conditions`/`shipping_charges`/`adjustment` (stored in `invoice_data_json` JSONB).
5. Frontend `buildPayload` sent `global_vehicle_id: ''` (empty string) and vehicles with `id: ''` which Pydantic rejected as invalid UUIDs.

**Fix Applied** (across 4 commits):

**Commit 1 — Schema & service fixes**:
1. Added `model_config = {"extra": "ignore", "populate_by_name": True}` to `UpdateInvoiceRequest`
2. Added missing fields to `UpdateInvoiceRequest`: `line_items`, `issue_date`, `currency`, `payment_terms`, `terms_and_conditions`, `shipping_charges`, `adjustment`, `global_vehicle_id`, `vehicle_service_due_date`, `vehicles`
3. Made `VehicleItem.id` optional (`uuid.UUID | None = None`), added `model_config = {"extra": "ignore"}`, `odometer` field, and empty-string-to-None validator
4. Added `empty_str_to_none` validators on `UpdateInvoiceRequest` and `InvoiceCreateRequest` for UUID fields (`global_vehicle_id`, `customer_id`, `branch_id`) and `discount_type`
5. Frontend: `global_vehicle_id: vehicles[0]?.id || undefined` (empty string → omitted)
6. Updated `update_invoice()` service to handle line_items, JSON-backed fields, and recalculation triggers

**Commit 2 — NOT NULL violation on line_items**:
7. Fixed missing `org_id=org_id` when creating LineItem in `update_invoice()` — was causing NOT NULL violation

**Commit 3 — VehicleItem.rego optional + str(None) fix**:
8. Made `VehicleItem.rego` optional
9. Fixed `str(None)` → `""` in vehicle JSON storage (both create and update paths)
10. Added actual backend error messages to frontend error display

**Commit 4 — Multi-vehicle save, edit-mode loading, PDF template**:
11. Frontend `buildPayload`: Changed `vehicles.filter(v => v.id).map(...)` to `vehicles.map(v => ({id: v.id || undefined, ...}))` — the filter was removing the primary vehicle (which has `id: ''` when loaded from existing invoice), causing the `vehicles` array to have only 1 item, so `len(vehicles_data) > 1` was false and additional vehicles weren't saved
12. Frontend edit-mode loading: Added loading of `additional_vehicles` from invoice response into the `vehicles` state array (previously only loaded primary vehicle, so re-editing a draft lost additional vehicles)
13. PDF template: Added additional vehicles section to `app/templates/pdf/invoice.html` — loops through `invoice.additional_vehicles` and renders a `vehicle-bar` div for each one with rego, make/model/year, odometer, and WOF expiry

**Files Changed**:
- `app/modules/invoices/schemas.py`
- `app/modules/invoices/service.py`
- `app/modules/invoices/router.py`
- `frontend/src/pages/invoices/InvoiceCreate.tsx`
- `app/templates/pdf/invoice.html`

**Similar Bugs Found & Fixed**: Same empty-string UUID pattern applied to `InvoiceCreateRequest` (for POST /invoices). `VehicleItem` validator added for nested vehicle IDs.

**Related Issues**: ISSUE-079 (additional vehicles feature)

---

### ISSUE-084: SMS reminder via Send Reminder button fails silently

- **Date**: 2026-03-17
- **Severity**: major
- **Status**: resolved
- **Reporter**: user

**Symptoms**: Clicking "Send SMS" in the Send Reminder dropdown shows success toast, but SMS is never delivered. Error log shows "SMS notification permanently failed after 3 retries" with the Connexus response body as the error message.

**Root Cause**: Two issues:

1. **Connexus client only accepted `status: "accepted"`** — The `ConnexusSmsClient.send()` method only treated `status == "accepted"` as success. Connexus returns `status: "queued"` when SMS is accepted but held for delivery (e.g. nighttime queue — "Message queued for delivery at 7am NZ time"). This valid 200 response was treated as failure, triggering 3 retries, all of which also returned "queued", resulting in permanent failure.

2. **Backend returned 200 on SMS failure** — `send_payment_reminder()` returned `{"status": "failed", "channel": "sms"}` with HTTP 200 when SMS send failed. The frontend only caught HTTP errors (4xx/5xx), so it showed a success toast even though the SMS failed.

**Fix Applied**:

1. Updated `ConnexusSmsClient.send()` to treat both `"accepted"` and `"queued"` as success. Also captures `queue_reason` and `queue_message` in metadata, and uses `.get("message_id")` with fallback to `websms_id`.
2. Added `db.flush()` before calling `send_sms_task()` so the notification_log row is visible to the task's independent session.
3. Added explicit error check: if `send_sms_task` returns `success=False`, raises `ValueError` with the error message, causing the router to return HTTP 400 with the detail — which the frontend catches and displays.

**Files Changed**:
- `app/integrations/connexus_sms.py`
- `app/modules/invoices/service.py`

**Similar Bugs Found & Fixed**: Same Connexus `"queued"` status would affect any SMS sent during NZ nighttime hours (not just reminders). The fix in the Connexus client covers all SMS sends globally.

---

### ISSUE-085: Invoice timestamps display UTC instead of organisation local timezone

- **Date**: 2026-03-22
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user

**Symptoms**: Payment dates in invoice detail view, PDF invoices, and credit note timestamps all display in UTC instead of the organisation's local timezone (Pacific/Auckland for NZ orgs). A payment recorded at 3:04 PM NZT shows as 2:04 AM.

**Root Cause**: Three issues:

1. **Organisation model missing `timezone` column mapping** — The `organisations` table has a `timezone` column (set to `Pacific/Auckland` by the setup wizard), but the SQLAlchemy `Organisation` model in `app/modules/admin/models.py` didn't map it. The column existed in the DB but was invisible to the ORM.

2. **Payment/credit note dates serialized as raw UTC** — `get_invoice()` in `app/modules/invoices/service.py` serialized `payment.created_at` and `credit_note.created_at` using `.isoformat()` directly, which outputs UTC timestamps without any timezone conversion.

3. **PDF template rendered raw ISO strings** — The invoice PDF template (`app/templates/pdf/invoice.html`) rendered payment dates as `{{ p.date or '' }}` which displayed raw ISO strings.

4. **Frontend only formatted dates, didn't convert timezone** — `formatDate()` in `InvoiceList.tsx` used `Intl.DateTimeFormat('en-NZ')` which formats the display but doesn't convert UTC to NZT.

**Fix Applied**:

1. Added `timezone: Mapped[str]` column to `Organisation` model in `app/modules/admin/models.py`
2. Created `app/core/timezone_utils.py` with `to_org_timezone()` and `format_datetime_local()` helpers using Python's `zoneinfo` module
3. Updated `get_invoice()` to fetch org timezone and convert all payment dates, credit note dates, and invoice timestamps (`created_at`, `voided_at`) to org-local timezone before serialization
4. Updated `generate_invoice_pdf()` to format `issue_date` and `due_date` as `dd Mon YYYY` strings, and added a `pdfdate` Jinja2 filter for payment dates in the PDF
5. Updated PDF template to use `{{ p.date | pdfdate }}` filter
6. Added `formatDateTime()` function to frontend `InvoiceList.tsx` that shows both date and time for payment and credit note timestamps
7. Added `org_timezone` field to invoice detail API response for frontend use

**Files Changed**:
- `app/modules/admin/models.py` (added `timezone` column mapping)
- `app/core/timezone_utils.py` (new — timezone conversion utilities)
- `app/modules/invoices/service.py` (timezone conversion in `get_invoice`, date formatting in `generate_invoice_pdf`)
- `app/templates/pdf/invoice.html` (pdfdate filter for payment dates)
- `frontend/src/pages/invoices/InvoiceList.tsx` (added `formatDateTime`, used for payment/credit note dates)

**Similar Bugs Found & Fixed**: The same UTC display issue would affect any future feature that displays `created_at` timestamps from the database. The `timezone_utils` module provides reusable conversion functions for all modules.

**Related Issues**: None


---

### ISSUE-086: Connection pool exhaustion on Pi — 90 connections vs max_connections=50

- **Date**: 2026-03-23
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user

**Symptoms**: Pi primary returning 503 on all endpoints. Postgres logs show "FATAL: too many connections for role postgres". App containers unable to acquire database connections.

**Root Cause**: SQLAlchemy engine was configured with `pool_size=30, max_overflow=15` (45 connections per gunicorn worker). With 2 workers, that's 90 potential connections against Pi's `max_connections=50`. The pool would exhaust all available connections, leaving none for maintenance or replication.

**Fix Applied**:
1. Made pool size configurable via `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` environment variables in `app/core/database.py` (defaults: 30/15 for dev, overridden per environment)
2. Set Pi (`.env.pi`) to `DB_POOL_SIZE=10, DB_MAX_OVERFLOW=5` (30 max connections for 2 workers, well under 50 limit)
3. Set local standby-prod (`.env.standby-prod`) to same conservative values

**Files Changed**:
- `app/core/database.py`
- `.env.pi`
- `.env.standby-prod`

**Similar Bugs Found & Fixed**: Same issue would affect any environment with low `max_connections`. The env-var approach lets each deployment tune independently.

**Related Issues**: None

---

### ISSUE-087: SSL never enabled on Pi postgres — certs and entrypoint not committed

- **Date**: 2026-03-23
- **Severity**: high
- **Status**: resolved
- **Reporter**: user

**Symptoms**: `SHOW ssl` on Pi postgres returned `off`. Replication connections from standby with `sslmode=require` were rejected with "server rejected SSL upgrade".

**Root Cause**: The SSL-related args (`ssl=on`, `ssl_cert_file`, `ssl_key_file`, `ssl_ca_file`), cert volume mounts, and the `pg-ssl-entrypoint.sh` entrypoint in `docker-compose.pi.yml` were configured locally but never committed to git. When the Pi pulled the latest code, it was running without SSL.

**Fix Applied**: Committed the SSL configuration to `docker-compose.pi.yml` including the entrypoint, cert volume mounts, and SSL postgres args. Deployed to Pi and verified `SHOW ssl` returns `on`.

**Files Changed**:
- `docker-compose.pi.yml`

**Related Issues**: ISSUE-088

---

### ISSUE-088: HMAC heartbeat secret mismatch between Pi and standby

- **Date**: 2026-03-23
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user

**Symptoms**: Heartbeat history on both Pi and standby showing "Invalid HMAC signature" errors. Peer status reported as "error" despite both nodes being reachable.

**Root Cause**: Pi's `.env` file had `HA_HEARTBEAT_SECRET=` (empty string) while the standby had `HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing`. The HMAC signatures computed with different secrets never matched.

**Fix Applied**: Set `HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing` on Pi's `.env` file directly via SSH. Recreated the app container to pick up the new value. Also updated `.env.pi` in the repo for future deploys.

**Files Changed**:
- `.env.pi`

**Related Issues**: ISSUE-087

---

### ISSUE-089: Defensive host:port parsing and URL encoding in HA peer DB connections

- **Date**: 2026-03-23
- **Severity**: low
- **Status**: resolved
- **Reporter**: agent (proactive)

**Symptoms**: If a user accidentally entered `192.168.1.90:8999` in the peer DB host field (including port), the connection string would be malformed (`host:port:port`). Passwords with special characters could also break DSN construction.

**Root Cause**: No input sanitization on the host field and no URL encoding for user/password in DSN construction in both `router.py` (test-db-connection) and `service.py` (_build_peer_db_url).

**Fix Applied**:
1. Added stripping of port from host field (split on `:` and take first part) in both `test-db-connection` endpoint and `_build_peer_db_url`
2. Added `urllib.parse.quote_plus` for user and password in DSN construction in both files

**Files Changed**:
- `app/modules/ha/router.py`
- `app/modules/ha/service.py`

**Related Issues**: None

---

### ISSUE-090: HA replication initial sync fails — slot exhaustion, RLS blocking, duplicate keys

- **Date**: 2026-03-24
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user

**Symptoms**: After creating the subscription on standby, only 35 of 122 tables completed initial sync. The remaining 87 tables were stuck in `d` (data copy) state, cycling through errors indefinitely. Three distinct error patterns in standby postgres logs:
1. `could not create replication slot: all replication slots are in use`
2. `could not start initial contents copy: unrecognized configuration parameter "app.current_org_id"`
3. `duplicate key value violates unique constraint` on `organisations_pkey` and `alembic_version_pkc`

**Root Cause**: Three separate issues blocking the initial table sync:

1. **`max_replication_slots=10` too low on Pi primary** — Each table sync worker needs a temporary replication slot. With 122 tables to sync and only 10 slots (1 used by the main subscription + 9 for sync workers), failed sync workers left stale inactive slots that blocked new workers from acquiring slots.

2. **RLS policies blocking replication COPY** — Tables with Row-Level Security have policies referencing `current_setting('app.current_org_id')`. This custom GUC parameter was not registered in the postgres server config, so when the replication worker (running as `replicator` user) tried to COPY data, the RLS policy evaluation failed with "unrecognized configuration parameter". Additionally, the `replicator` user had `BYPASSRLS=false`, so RLS policies were being applied to replication connections.

3. **Pre-existing data on standby** — The standby database had data from running Alembic migrations and seed scripts before replication was set up. When the subscription's initial COPY tried to insert rows, it hit duplicate key violations on `organisations` and `alembic_version` tables.

**Fix Applied**:

1. Increased `max_replication_slots` from 10 to 30 on Pi primary (`docker-compose.pi.yml`). Also added `max_wal_senders=10` explicitly.

2. Registered `app.current_org_id` as a custom GUC by adding `-c "app.current_org_id="` to postgres command args in all three compose files (`docker-compose.yml`, `docker-compose.pi.yml`, `docker-compose.standby-prod.yml`). Granted `BYPASSRLS` to the `replicator` user on Pi primary. Updated the `create-replication-user` endpoint in `router.py` to automatically grant `BYPASSRLS` when creating replication users.

3. Truncated all tables (except `ha_config`) on standby before re-creating the subscription, allowing a clean initial COPY.

After all three fixes, re-created the subscription and all 122 tables synced successfully. Row counts match exactly between primary and standby (7 orgs, 8 users, 5 invoices, 546 customers, 683 vehicles).

**Files Changed**:
- `docker-compose.pi.yml` (max_replication_slots=30, max_wal_senders=10, app.current_org_id GUC)
- `docker-compose.yml` (app.current_org_id GUC)
- `docker-compose.standby-prod.yml` (app.current_org_id GUC)
- `app/modules/ha/router.py` (BYPASSRLS in create-replication-user)

**Similar Bugs Found & Fixed**: The `app.current_org_id` GUC registration is needed on any postgres instance that participates in logical replication with RLS-enabled tables. Applied to all three compose files.

**Related Issues**: ISSUE-087, ISSUE-088


---

### ISSUE-091: Stripe PaymentMethod not saved during paid-plan signup

- **Date**: 2026-03-25
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user

**Symptoms**: User signed up for a paid plan, card was charged, but no payment method was saved. Billing page showed "No payment methods on file."

**Root Cause**: `create_payment_intent_no_customer` in `app/integrations/stripe_billing.py` created the PaymentIntent without `setup_future_usage="off_session"`. Stripe treated the PaymentMethod as single-use — after payment succeeded, it couldn't be attached to the newly created Customer.

**Fix Applied**: Added `setup_future_usage="off_session"` to the PaymentIntent creation. This tells Stripe to keep the PM reusable for future charges.

**Files Changed**:
- `app/integrations/stripe_billing.py`

---

### ISSUE-092: Supplier creation hangs — missing `account_number` on Supplier ORM model

- **Date**: 2026-03-25
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user

**Symptoms**: POST to `/api/v1/inventory/suppliers` hung indefinitely (504 timeout). No error in backend logs.

**Root Cause**: The `Supplier` ORM model in `app/modules/suppliers/models.py` was missing the `account_number` column. The DB had the column (from migration 0026), but the Python model didn't declare it. `create_supplier()` passed `account_number` to `Supplier()`, causing a `TypeError` that got swallowed by the middleware chain, deadlocking the async handler.

**Fix Applied**: Added `account_number` column to the `Supplier` model.

**Files Changed**:
- `app/modules/suppliers/models.py`

---

### ISSUE-093: SQLAlchemy mapper configuration errors causing request hangs

- **Date**: 2026-03-25
- **Severity**: critical
- **Status**: resolved
- **Reporter**: developer

**Symptoms**: Various POST/PUT endpoints hung indefinitely. Affected: inventory stock adjustment, invoice creation, supplier creation. GET requests worked fine.

**Root Cause**: SQLAlchemy ORM models had cross-module `relationship()` references (e.g., `PartsCatalogue` → `PartSupplier`, `Organisation` → `User`, `Invoice` → `Branch`). When a model was first accessed in a write operation, SQLAlchemy tried to configure all mappers lazily, but dependent models weren't loaded yet, causing `InvalidRequestError` that deadlocked the async handler.

**Fix Applied**:
1. Added explicit model imports in `app/main.py` for all modules with cross-references
2. Added `configure_mappers()` call after all imports to resolve relationships at startup
3. Set `lazy="noload"` on `PartsCatalogue.category` and `PartsCatalogue.supplier` relationships
4. Rewrote `adjust_stock` and `decrement_stock_for_invoice` to use raw SQL instead of ORM to avoid triggering mapper configuration

**Files Changed**:
- `app/main.py`
- `app/modules/catalogue/models.py`
- `app/modules/inventory/service.py`

---

### ISSUE-094: Invoice "Save and Send" takes 5-6 seconds — synchronous SMTP blocking

- **Date**: 2026-03-25
- **Severity**: high
- **Status**: resolved
- **Reporter**: user

**Symptoms**: Clicking "Save and Send" on invoice creation took 5-6 seconds. Sometimes timed out with 504.

**Root Cause**: When status is "sent", the invoice router synchronously called `email_invoice()` which generates a PDF and sends it via SMTP. The SMTP connection, TLS handshake, authentication, and send took 5+ seconds, blocking the HTTP response.

**Fix Applied**: Changed the auto-email to fire-and-forget using `asyncio.create_task()`. The invoice is created and returned immediately (0.04s), and the email sends in the background. Also made the "Mark Paid & Email" frontend flow fire-and-forget for the email step.

**Files Changed**:
- `app/modules/invoices/router.py`
- `frontend/src/pages/invoices/InvoiceCreate.tsx`

---

### ISSUE-095: Stock adjustment endpoint returns 504 — StockMovement model mismatch

- **Date**: 2026-03-25
- **Severity**: high
- **Status**: resolved
- **Reporter**: user

**Symptoms**: Adjusting stock via Inventory > Adjust Stock hung and returned 504.

**Root Cause**: The `adjust_stock` service created `StockMovement(part_id=..., recorded_by=...)` but the actual `StockMovement` model has `product_id` and `performed_by`. The `StockMovement` table references `products.id` (not `parts_catalogue.id`), so the FK would also fail. Additionally, the `StockAdjustmentResponse` schema required a `movement` field that was removed.

**Fix Applied**: Rewrote stock operations to use raw SQL (`UPDATE parts_catalogue SET current_stock = ...`) instead of creating `StockMovement` records. Removed `response_model` from the adjust stock endpoint. Stock changes are tracked via audit logs.

**Files Changed**:
- `app/modules/inventory/service.py`
- `app/modules/inventory/router.py`

---

### ISSUE-096: Double scroll on all app pages — document body scrolls in addition to main content area

- **Date**: 2026-03-26
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: ISSUE-051 (partial regression — the layout-level fix is intact but the global CSS guard was removed)

**Symptoms**: On any page inside OrgLayout or AdminLayout (e.g. HA Replication, Expenses, Purchase Orders), scrolling the page content also causes the entire browser document to scroll. Two scrollbars appear or the page scrolls past the intended boundary, leaving empty space at the bottom.

**Root Cause**: ISSUE-051 fixed double scroll with two complementary changes:
1. `min-h-0` on flex children in OrgLayout/AdminLayout (still intact)
2. `html, body, #root { height: 100%; overflow: hidden; }` in `index.css` (was subsequently removed in TASK 1 to fix signup page scrolling)

When the `index.css` rule was removed to fix the signup page, the document-level scroll guard was lost. The layout's `h-screen overflow-hidden` root div alone is not sufficient — if `html`/`body` have no height constraint, the browser can still scroll the document when the layout div's content overflows in edge cases (e.g. tall pages, modals, dynamic content).

The signup page fix (TASK 1) removed the global CSS rule entirely rather than finding a targeted solution that preserves both behaviours.

**Fix Applied**:
1. Restored `html, body, #root { height: 100%; overflow: hidden; }` in `index.css`
2. Wrapped the `<Outlet />` in `GuestOnly` (App.tsx) with `<div className="h-full overflow-y-auto">` — this gives guest pages (login, signup, password reset, verify email) their own scroll container within the `#root` bounds, so they can scroll without the document scrolling

**Key Principle**: `html/body/#root` must be `height: 100%; overflow: hidden` to prevent document scroll. Guest pages that need to scroll must have their own `overflow-y: auto` wrapper. OrgLayout/AdminLayout already have `h-screen overflow-hidden` + `<main overflow-y-auto>` so they're unaffected.

**Files Changed**:
- `frontend/src/index.css` — Restored `html, body, #root { height: 100%; overflow: hidden; }`
- `frontend/src/App.tsx` — Wrapped GuestOnly `<Outlet />` with scrollable div

**Related Issues**: ISSUE-051 (original double scroll fix), ISSUE-039 (original broken scrolling fix)


---

### ISSUE-097: BranchContextMiddleware blocks login — X-Branch-Id header on unauthenticated requests

- **Date**: 2026-04-06
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A (introduced by branch-admin-role spec implementation)

**Symptoms**: All login attempts return 403 Forbidden. Users cannot log in to any account. The error occurs because the axios interceptor sends `X-Branch-Id` from localStorage on every request, including `/auth/login`.

**Root Cause**: The `BranchContextMiddleware` in `app/core/branch_context.py` validates the `X-Branch-Id` header against the user's org. For unauthenticated requests (like login), there's no `user_id` or `org_id` in `request.state`, so the middleware hit the `org_id is None` check and returned 403. The middleware was added as part of the branch management feature but didn't account for public endpoints.

**Fix Applied**: Added a check for `user_id` before org validation — if no `user_id` in request.state (unauthenticated), skip branch validation and pass through.

**Files Changed**:
- `app/core/branch_context.py`

**Similar Bugs Found & Fixed**: ISSUE-098 (same root cause for global_admin)

**Related Issues**: ISSUE-098

---

### ISSUE-098: BranchContextMiddleware blocks global_admin — X-Branch-Id header with no org_id

- **Date**: 2026-04-06
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: ISSUE-097 (partial fix didn't cover authenticated users without org_id)

**Symptoms**: After logging in as global_admin, every admin endpoint returns 403. The browser still has a stale `X-Branch-Id` in localStorage from a previous org_admin session.

**Root Cause**: The fix for ISSUE-097 only handled unauthenticated requests. Global_admin users are authenticated but have `org_id = None` (they're platform-level, not org-level). The middleware still rejected them because `org_id is None` with a branch header present.

**Fix Applied**: Changed the `org_id is None` branch to set `branch_id = None` and pass through instead of returning 403. This allows global_admin (and any authenticated user without org context) to proceed without branch scoping.

**Files Changed**:
- `app/core/branch_context.py`

**Similar Bugs Found & Fixed**: Would also affect `franchise_admin` users who have no org_id.

**Related Issues**: ISSUE-097

---

### ISSUE-099: Dashboard not scoped by branch — shows all-org data regardless of branch selector

- **Date**: 2026-04-06
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Selecting "Clendon Shop" branch in the branch switcher shows the same dashboard metrics as "All Branches". Revenue, outstanding total, and overdue invoices don't change when switching branches.

**Root Cause**: Two issues: (1) The `OrgAdminDashboard` fetched `/reports/revenue` and `/reports/outstanding` without passing `branch_id` as a query parameter, and the backend endpoints read `branch_id` from query params, not from `request.state.branch_id`. (2) The dashboard fetch effect had `[]` as dependency (ran once on mount), so it never re-fetched when the branch changed.

**Fix Applied**: (1) Added `branch_id` query param to dashboard API calls when `selectedBranchId` is set. (2) Changed the fetch effect dependency to `[selectedBranchId]` so it re-fetches on branch change. (3) Added fallback in backend report endpoints to read from `request.state.branch_id` when no query param is provided.

**Files Changed**:
- `frontend/src/pages/dashboard/OrgAdminDashboard.tsx`
- `app/modules/organisations/router.py`
- `app/modules/reports/router.py`

**Similar Bugs Found & Fixed**: Same pattern in InvoiceList, QuoteList, BookingListPanel, POList — all fixed to include `selectedBranchId` in fetch dependencies.

**Related Issues**: ISSUE-100

---

### ISSUE-100: Branch selection resets to "All Branches" on page refresh

- **Date**: 2026-04-06
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Selecting a branch, then refreshing the page, resets the branch selector to "All Branches" (null). The selection doesn't persist.

**Root Cause**: Two issues: (1) `selectedBranchId` state initialized as `null` instead of reading from localStorage on mount. (2) The `validateBranchSelection` function validated the stored branch ID against `user.branch_ids` from `/auth/me`, but for org_admin users, `branch_ids` only contains explicitly assigned branches (like Main), not all accessible branches. So Clendon Shop's ID failed validation and was cleared.

**Fix Applied**: (1) Initialize `selectedBranchId` from localStorage in the `useState` initializer. (2) Validate against the full org branches list (from `/org/branches`) instead of `user.branch_ids`. (3) Removed the response interceptor that was re-validating against `branch_ids` and clearing the selection.

**Files Changed**:
- `frontend/src/contexts/BranchContext.tsx`

**Similar Bugs Found & Fixed**: N/A

**Related Issues**: ISSUE-099

---

### ISSUE-101: Invoices show empty on Main branch — NULL branch_id records excluded by filter

- **Date**: 2026-04-06
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Selecting "Main" branch shows "No invoices yet" even though invoices exist. Selecting "All Branches" shows all invoices.

**Root Cause**: The `search_invoices` function in `app/modules/invoices/service.py` filters with `Invoice.branch_id == branch_id`. Invoices created before branch management was added have `branch_id = NULL`, so they don't match any specific branch filter.

**Fix Applied**: Changed the branch filter to include NULL records: `or_(Invoice.branch_id == branch_id, Invoice.branch_id.is_(None))`. Same fix applied to quotes service.

**Files Changed**:
- `app/modules/invoices/service.py`
- `app/modules/quotes/service.py`

**Similar Bugs Found & Fixed**: Same pattern in quotes service.

**Related Issues**: ISSUE-099


---

### ISSUE-102: Demo reset endpoint returns 500 — SQLAlchemy closed transaction + FK violations + missing org_id columns

- **Date**: 2026-04-06
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A (new code added for comprehensive demo reset)

**Symptoms**: POST `/api/v1/admin/demo/reset` returns 500 Internal Server Error. Three distinct failures: (1) SAVEPOINT/ROLLBACK TO SAVEPOINT not working correctly with SQLAlchemy's async session, (2) many tables (webhook_deliveries, tip_allocations, job_attachments, etc.) don't have an `org_id` column — they reference parent tables via FK, (3) FK violation when deleting users because sessions for other org users weren't cleared first.

**Root Cause**: The hardcoded table list approach was fundamentally flawed — it assumed every table has an `org_id` column, which is wrong for child tables that reference parents via FK. Also, sessions for ALL org users needed to be deleted before deleting the users themselves, not just the demo user's sessions.

**Fix Applied**: Rewrote the reset to use a dynamic approach:
1. Find ALL user IDs in the org and delete their sessions/MFA data first
2. Query `information_schema.columns` to dynamically find all tables with an `org_id` column
3. Use multi-pass deletion with SAVEPOINTs — retry failed tables up to 5 times (FK deps resolve as parent tables get cleared in earlier passes)
4. Delete extra users after all org data is cleared
5. Reset password, ensure Main branch exists, re-sync modules/flags

**Files Changed**:
- `app/modules/admin/router.py`

**Similar Bugs Found & Fixed**: ISSUE-044 (same SQLAlchemy closed transaction pattern). The pattern of `await db.rollback()` inside a try/except within a session context manager is always wrong — use SAVEPOINTs instead.

**Related Issues**: ISSUE-044


---

### ISSUE-103: Stale X-Branch-Id header causes 403 on all requests after demo reset

- **Date**: 2026-04-06
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A (BranchContextMiddleware was too strict)

**Symptoms**: After demo reset or switching between accounts, all API requests return 403 "Invalid branch context" even in a fresh private browser. Login succeeds (200) but every subsequent request fails.

**Root Cause**: The `BranchContextMiddleware` validated the `X-Branch-Id` header against the org's branches. If the branch was deleted (by demo reset) but the browser still had the old branch UUID in localStorage, the middleware returned 403. This blocked the entire app because the axios interceptor sends `X-Branch-Id` on every request from localStorage.

**Fix Applied**: Changed the middleware to fall back to `branch_id = None` (All Branches scope) instead of returning 403 when a branch doesn't belong to the org. The frontend's BranchContext will re-validate and clear the stale selection on next fetch. A stale branch header should never block the entire application.

**Files Changed**:
- `app/core/branch_context.py`

**Similar Bugs Found & Fixed**: ISSUE-097 (unauthenticated), ISSUE-098 (global_admin) — same middleware, same pattern of being too strict.

**Related Issues**: ISSUE-097, ISSUE-098, ISSUE-102


---

### ISSUE-104: Xero auto-sync causes "closed transaction" error — DB queries after commit

- **Date**: 2026-04-07
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Creating an invoice or recording a payment returns 503 "Can't operate on closed transaction inside context manager". The invoice/payment is saved successfully but the API response fails. Frontend shows the error, but data appears on refresh.

**Root Cause**: The Xero auto-sync hooks added to the invoice and payment routers performed DB queries (customer name lookup, invoice number lookup) after `await db.commit()` was called. Once committed, the SQLAlchemy async session's transaction is closed and further queries fail.

Pattern: `db.commit()` → `await db.execute(select(...))` → CRASH

**Fix Applied**: Moved all DB queries needed for Xero sync data preparation to BEFORE `db.commit()`. The Xero-compatible payload dict is built while the session is still open, then the fire-and-forget `asyncio.create_task()` only uses the pre-built dict (no DB access).

Applied to all three sync hooks:
1. Invoice router: customer name lookup moved before commit
2. Payment router: invoice number lookup moved before commit  
3. Credit note router: already didn't commit manually, but fixed data shape to include proper fields

**Files Changed**:
- `app/modules/invoices/router.py`
- `app/modules/payments/router.py`

**Similar Bugs Found & Fixed**: Same pattern in all three Xero sync hooks (invoice, payment, credit note). All fixed.

**Related Issues**: ISSUE-044 (same "closed transaction" class of bug in staff router)


---

### ISSUE-105: Xero Credentials page fails to load on standby-prod — missing value_encrypted column

- **Date**: 2026-04-08
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: On the standby-prod environment (localhost:8082), navigating to Admin > Integrations > Xero Credentials shows "Failed to load — Could not load Xero credentials. Please try again." The endpoint `GET /admin/platform-settings/xero` returns 500.

**Root Cause**: During the standby-prod container rebuild, alembic migration 0139 was stamped (skipped) instead of executed because the `platform_settings` table already existed. However, the table was created by an earlier mechanism without the `value_encrypted BYTEA` column that migration 0139 adds. The `PlatformSetting` ORM model references `value_encrypted`, so any query against the table fails with a column-not-found error.

The migration itself uses `IF NOT EXISTS` for the column addition, so it would have been safe to run — but the stamp-past approach skipped it entirely because the table name matched.

**Fix Applied**: Manually added the missing column via direct SQL:
```sql
ALTER TABLE platform_settings ADD COLUMN value_encrypted BYTEA;
```

**Lesson**: When stamping past migrations on HA-replicated databases, check not just whether the table exists but whether all columns from the migration exist. Migrations that add columns to existing tables (like 0139) must be run, not stamped.

**Files Changed**: None (database DDL fix only)

**Similar Bugs Found & Fixed**: None — other stamped migration (0130 stock_transfers) was a pure CREATE TABLE that already existed with the correct schema.

**Related Issues**: N/A


---

### ISSUE-106: Trade family disable returns 504 — MissingGreenlet on response serialization

- **Date**: 2026-04-08
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Clicking "Disable" on a trade family (e.g. Electrical & Mechanical) in the Global Admin Trade Families page causes the button to spin indefinitely and the browser console shows `504 Gateway Timeout`. The GET list endpoint works fine.

**Root Cause**: The `update_family` method in `TradeCategoryService` called `await self.db.flush()` but did not `await self.db.refresh(family)` before returning the ORM object. When the router then called `TradeFamilyResponse.model_validate(family)`, Pydantic's `from_attributes` mode tried to access JSONB columns (`country_codes`, `gated_features`) which triggered a lazy load outside the async greenlet context, raising `MissingGreenlet: greenlet_spawn has not been called`. This is the same class of bug as ISSUE-044 and ISSUE-058.

The rate limiter middleware caught the validation error and logged it, but the response was never sent, causing gunicorn to hit its 120s timeout and nginx to return 504.

**Fix Applied**: Added `await self.db.refresh(family)` after `flush()` in both `create_family` and `update_family` methods. This eagerly loads all attributes within the async session context so Pydantic can serialize them synchronously.

**Files Changed**:
- `app/modules/trade_categories/service.py`

**Similar Bugs Found & Fixed**: Same pattern in `create_family` — fixed proactively.

**Related Issues**: ISSUE-044, ISSUE-058


---

### ISSUE-107: Claims form customer search returns no results — wrong query param and response key

- **Date**: 2026-04-10
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Typing in the Customer search field on the New Claim form (`/claims/new`) returned no results. The dropdown never appeared, making it impossible to select a customer and create a claim.

**Root Cause**: Two frontend/backend mismatches in `ClaimCreateForm.tsx`:

1. Frontend sent `search` query parameter but backend `list_customers` expects `q`
2. Frontend read `res.data.items` but backend returns `{ customers: [...] }` not `{ items: [...] }`
3. Frontend sent `page_size` but backend expects `limit`

**Fix Applied**:

1. Changed `params: { search: query, page_size: 10 }` → `params: { q: query, limit: 10 }`
2. Changed `res.data?.items ?? []` → `res.data?.customers ?? []`
3. Fixed invoice fetch: changed `customer_id` param → `search` by customer name, changed `res.data?.items` → `res.data?.invoices`, changed `page_size` → `limit`
4. Fixed job card fetch: changed `customer_id` param → `search` by customer name, changed `page_size` → `limit`

**Files Changed**:
- `frontend/src/pages/claims/ClaimCreateForm.tsx` — fixed API call params and response key

**Related Issues**: N/A

---

### ISSUE-108: Claims form crashes when selecting invoice — line_total.toFixed is not a function

- **Date**: 2026-04-10
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Selecting an invoice in the New Claim form caused a crash with error `(e.line_total ?? 0).toFixed is not a function`. The page showed the error boundary.

**Root Cause**: The backend returns `line_total` as a Decimal string (e.g. `"150.00"`), not a number. The frontend called `.toFixed(2)` on it directly, which fails because strings don't have `.toFixed()`. The `?? 0` fallback only handles null/undefined, not string values.

**Fix Applied**:

1. Changed `(li.line_total ?? 0).toFixed(2)` → `Number(li.line_total ?? 0).toFixed(2)` to coerce the string to a number first
2. Updated `LineItemOption` interface to reflect that `line_total` and `quantity` can be strings

**Files Changed**:
- `frontend/src/pages/claims/ClaimCreateForm.tsx` — safe number coercion on line_total

**Related Issues**: ISSUE-006 (same class of safe-api-consumption bug)

---

### ISSUE-109: Credit note creation fails — db.expire() causes MissingGreenlet in async context

- **Date**: 2026-04-10
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: Creating a credit note on an invoice threw a server error. The credit note modal on the invoice detail page failed silently. Claims resolution with "Credit Note" type also failed.

**Root Cause**: `create_credit_note()` in `app/modules/invoices/service.py` used `db.expire(credit_note)` and `db.expire(invoice)` which are synchronous SQLAlchemy methods. In an async context with `asyncpg`, this causes a `MissingGreenlet` error because synchronous attribute access triggers lazy loading outside the greenlet.

**Fix Applied**:

1. Replaced `db.expire(credit_note)` → `await db.refresh(credit_note)`
2. Replaced `db.expire(invoice)` → `await db.refresh(invoice)`

This follows the established pattern used everywhere else in the codebase (per project overview: "After `db.flush()`, always `await db.refresh(obj)` before returning ORM objects for Pydantic serialization").

**Files Changed**:
- `app/modules/invoices/service.py` — fixed async/sync mismatch in create_credit_note()

**Related Issues**: ISSUE-106 (same class of MissingGreenlet bug)


---

### ISSUE-110: Login returns 403 "Missing CSRF token" after org-security-settings deployment

- **Date**: 2026-04-12
- **Severity**: critical
- **Status**: resolved
- **Reporter**: user
- **Regression of**: N/A

**Symptoms**: After deploying the org-security-settings feature, login via the UI returned 403 Forbidden with "Missing CSRF token". The app container also initially crashed with `AmbiguousForeignKeysError` on the User ↔ CustomRole relationship.

**Root Cause**: Two issues:

1. **AmbiguousForeignKeysError**: The new `CustomRole` model has a `created_by` FK to `users.id`, and `User` has `custom_role_id` FK to `custom_roles.id`. SQLAlchemy couldn't determine which FK to use for the `User.custom_role` / `CustomRole.users` relationship. Both sides needed explicit `foreign_keys` arguments.

2. **CSRF 403 on login**: The `SecurityHeadersMiddleware` CSRF check blocks POST requests when a `session` cookie is present but no `X-CSRF-Token` header is sent. The login endpoint (`/api/v1/auth/login`) and token refresh (`/api/v1/auth/token/refresh`) were not in the `_CSRF_EXEMPT_PATHS` set. When a user had a stale session cookie from a previous login, the CSRF check rejected the login POST before it could authenticate.

**Fix Applied**:

1. Added `foreign_keys="[User.custom_role_id]"` to both `User.custom_role` and `CustomRole.users` relationships in `app/modules/auth/models.py`.
2. Added all pre-authentication auth endpoints to `_CSRF_EXEMPT_PATHS` in `app/middleware/security_headers.py`: login, token refresh, signup, password reset, MFA verify/challenge, passkey login, Google OAuth, email verification, and captcha verification.

**Files Changed**:
- `app/modules/auth/models.py` — added `foreign_keys` to User ↔ CustomRole relationships
- `app/middleware/security_headers.py` — expanded `_CSRF_EXEMPT_PATHS` with all pre-auth endpoints


---

### ISSUE-111: Stripe payment succeeds on frontend but invoice stays "issued" — webhook not received in local dev

- **Date**: 2026-04-17
- **Severity**: high
- **Status**: in-progress
- **Reporter**: user
- **Feature**: stripe-invoice-payment-flow

**Symptoms**: Customer pays invoice via the custom Stripe Elements payment page. The page shows "Payment Successful" with the correct amount. However:
1. Invoice remains "issued" with full balance due in the app
2. No payment record created in the database
3. No receipt email sent to the customer
4. Stripe Connect dashboard shows $0 volume (test mode)

**Root Cause**: The payment flow relies entirely on the `payment_intent.succeeded` webhook from Stripe to record the payment, update the invoice, and send the receipt email. In local development, Stripe cannot deliver webhooks to `localhost` — the webhook endpoint is unreachable from the internet. The frontend confirms payment via `stripe.confirmCardPayment()` which succeeds (the money is collected by Stripe), but the backend never learns about it.

This is a design gap: the system has no fallback mechanism when webhooks are delayed or undeliverable. In production with a public URL, webhooks will work, but there should still be a safety net for:
- Webhook delivery delays (Stripe retries over 72 hours)
- Webhook endpoint downtime
- Local development without Stripe CLI

**Fix Plan**: Add a backend endpoint `POST /api/v1/public/pay/{token}/confirm` that the frontend calls after `stripe.confirmCardPayment()` succeeds. This endpoint:
1. Retrieves the PaymentIntent from Stripe API to verify its status
2. If `status == "succeeded"`, records the payment (same logic as webhook handler)
3. Idempotent — if webhook already processed it, this is a no-op
4. Sends the receipt email if payment was just recorded

This provides a synchronous confirmation path alongside the async webhook path, ensuring payments are always recorded even if webhooks are delayed.

**Files to Change**:
- `app/modules/payments/public_router.py` — add confirm endpoint
- `frontend/src/pages/public/InvoicePaymentPage.tsx` — call confirm after payment success
- `app/modules/payments/service.py` — extract shared payment recording logic

**Related Issues**: N/A (new feature gap)
**Related Steering**: #[[file:.kiro/steering/integration-credentials-architecture.md]]


---

### ISSUE-112: PUT /catalogue/labour-rates/{id} returns 404 — endpoint missing

- **Date**: 2026-04-17
- **Severity**: medium
- **Status**: resolved
- **Reporter**: user

**Symptoms**: Updating a labour rate in the Catalogue page throws a 404 error. The frontend calls `PUT /api/v1/catalogue/labour-rates/{id}` but the backend only had GET (list) and POST (create) endpoints — no PUT for updates.

**Root Cause**: The PUT endpoint for updating labour rates was never implemented. The frontend `LabourRates.tsx` component calls `apiClient.put()` for both editing rate details and toggling active/inactive status, but the backend router only had `@router.get("/labour-rates")` and `@router.post("/labour-rates")`.

**Fix Applied**:
1. Added `LabourRateUpdateRequest` schema with optional `name`, `hourly_rate`, `is_active` fields
2. Added `update_labour_rate()` service function with validation, audit logging, and `flush()` + `refresh()` pattern
3. Added `PUT /catalogue/labour-rates/{rate_id}` router endpoint with `require_role("org_admin")`

**Files Changed**:
- `app/modules/catalogue/schemas.py` — added `LabourRateUpdateRequest`
- `app/modules/catalogue/service.py` — added `update_labour_rate()`
- `app/modules/catalogue/router.py` — added PUT endpoint + imported new schema


---

### ISSUE-113: Setup wizard v2 API calls double-prefixed — /api/v1/v2/... → 404

- **Date**: 2026-04-26
- **Severity**: high
- **Status**: resolved
- **Reporter**: user
- **Regression of**: ISSUE-006 (same bug pattern reintroduced in setup wizard files)

**Symptoms**: Setup wizard Step 1 (Country) and Step 2 (Trade) fail with 404 errors. Browser console shows requests to `/api/v1/v2/setup-wizard/progress`, `/api/v1/v2/setup-wizard/step/1`, `/api/v1/v2/trade-families`, `/api/v1/v2/trade-categories`. The Next button shows a loading spinner indefinitely.

**Root Cause**: The `apiClient` has `baseURL: '/api/v1'`. The interceptor in `api/client.ts` strips the baseURL when the URL starts with `/api/` (ISSUE-006 fix). However, the setup wizard files used `/v2/...` paths (e.g., `apiClient.get('/v2/setup-wizard/progress')`) which don't start with `/api/`, so the interceptor doesn't catch them. The result is double-prefixed URLs: `/api/v1/v2/setup-wizard/progress` → 404.

Additionally, the `_apply_country_defaults` function in `app/modules/setup_wizard/service.py` crashed with `TypeError: string indices must be integers, not 'str'` because `compliance_profiles.default_tax_rates` was stored as a double-encoded JSON string in the database (a JSON string wrapping a JSON array).

**Fix Applied**:

1. **Setup wizard API calls**: Changed all `/v2/...` paths to `/api/v2/...` so the interceptor correctly strips the baseURL:
   - `SetupWizard.tsx`: `/v2/setup-wizard/progress` → `/api/v2/setup-wizard/progress`
   - `SetupWizard.tsx`: `/v2/setup-wizard/step/${n}` → `/api/v2/setup-wizard/step/${n}`
   - `TradeStep.tsx`: `/v2/trade-families` → `/api/v2/trade-families`
   - `TradeStep.tsx`: `/v2/trade-categories` → `/api/v2/trade-categories`
   - `ModulesStep.tsx`: `/v2/modules` → `/api/v2/modules`

2. **OrgLayout wizard check**: `/v2/setup-wizard/progress` → `/api/v2/setup-wizard/progress`

3. **Country defaults crash**: Added `isinstance(tax_rates, str)` check with `json.loads()` fallback in `_apply_country_defaults` to handle double-encoded JSONB data.

4. **Full codebase scan**: Found and fixed 11 additional `/v2/...` calls in inventory pages:
   - `StockMovements.tsx`: `/v2/stock-movements/batch`
   - `ProductList.tsx`: `/v2/purchase-orders`
   - `ProductDetail.tsx`: `/v2/products/${id}`
   - `PricingRules.tsx`: 4 calls to `/v2/pricing-rules/...`
   - `CategoryTree.tsx`: 4 calls to `/v2/product-categories/...`

**Files Changed**:
- `frontend/src/pages/setup/SetupWizard.tsx`
- `frontend/src/pages/setup/steps/TradeStep.tsx`
- `frontend/src/pages/setup/steps/ModulesStep.tsx`
- `frontend/src/layouts/OrgLayout.tsx`
- `frontend/src/pages/inventory/StockMovements.tsx`
- `frontend/src/pages/inventory/ProductList.tsx`
- `frontend/src/pages/inventory/ProductDetail.tsx`
- `frontend/src/pages/inventory/PricingRules.tsx`
- `frontend/src/pages/inventory/CategoryTree.tsx`
- `app/modules/setup_wizard/service.py`

**Similar Bugs Found & Fixed**: 11 additional instances of the same `/v2/...` pattern in inventory pages — all fixed in this pass. Full scan confirmed zero remaining instances.

**Related Issues**: ISSUE-006 (original systemic v2 double-prefix fix)


---

### ISSUE-114: Sequences not replicated — post-promotion duplicate key violations

- **Date**: 2026-04-26
- **Severity**: critical
- **Status**: resolved
- **Reporter**: agent (HA audit)
- **Regression of**: N/A

**Symptoms**: After promoting a standby to primary, the first INSERT on any table with an auto-increment primary key fails with a duplicate key violation. `nextval('some_id_seq')` returns `1` because sequences were never replicated from the primary. The replication lag metric also understates true lag during low-write periods because it uses `last_msg_send_time` (updated by keepalives) instead of `last_msg_receipt_time`.

**Root Cause**: `init_primary` in `replication.py` creates a `FOR TABLE` publication that replicates row data only — sequences are excluded. PostgreSQL logical replication applies rows directly without calling `nextval()`, so standby sequences remain at their initial values. On promotion, the ORM calls `nextval()` which returns a value that conflicts with existing replicated rows. Additionally, `get_replication_lag` used `last_msg_send_time` which is refreshed by keepalive pings regardless of data changes, making the promote lag-safety guard ineffective.

**Fix Applied**:
1. Added `ALTER PUBLICATION ... ADD ALL SEQUENCES` after `CREATE PUBLICATION` in `init_primary` (PostgreSQL 16 native sequence replication)
2. Added `sync_sequences_post_promotion()` safety-net method that runs `SELECT setval(seq, MAX(id) + 1)` for all auto-increment sequences
3. Called sequence sync in `HAService.promote()` and `HeartbeatService._execute_auto_promote()`
4. Changed lag query to use `GREATEST(last_msg_send_time, last_msg_receipt_time)` in both `get_replication_lag` and `get_replication_status`

**Files Changed**:
- `app/modules/ha/replication.py`
- `app/modules/ha/service.py`
- `app/modules/ha/heartbeat.py`

**Similar Bugs Found & Fixed**: The lag metric fix also improves the promote safety guard accuracy across all promotion paths (manual and auto-promote).

**Related Issues**: ISSUE-120 (same lag metric fix)

**Spec**: `.kiro/specs/ha-replication-bugfixes/`

---

### ISSUE-115: trigger_resync does not truncate standby before re-copying — duplicate key errors

- **Date**: 2026-04-26
- **Severity**: critical
- **Status**: resolved
- **Reporter**: agent (HA audit)
- **Regression of**: N/A

**Symptoms**: Calling `POST /api/v1/ha/replication/resync` on a standby with existing replicated data fails with duplicate primary key errors on every table. The re-sync never completes.

**Root Cause**: `trigger_resync` calls `drop_subscription` then `CREATE SUBSCRIPTION ... WITH (copy_data = true)` without first truncating the standby tables. PostgreSQL's `copy_data = true` does not auto-truncate — it inserts rows into existing tables, causing PK conflicts. The `init_standby` path correctly passes `truncate_first=True`, but `trigger_resync` bypasses this safeguard.

**Fix Applied**:
1. Added `await ReplicationManager.truncate_all_tables()` as the first step in `trigger_resync`, before `drop_subscription`
2. Added INFO log: "Triggered re-sync: truncating standby tables first"
3. If truncation fails, the exception propagates and resync is aborted (no partial state)

**Files Changed**:
- `app/modules/ha/replication.py`

**Similar Bugs Found & Fixed**: N/A — `init_standby` already had correct truncation.

**Related Issues**: N/A

**Spec**: `.kiro/specs/ha-replication-bugfixes/`

---

### ISSUE-116: Hardcoded credentials committed to repository in operational scripts

- **Date**: 2026-04-26
- **Severity**: high
- **Status**: resolved
- **Reporter**: agent (HA audit)
- **Regression of**: N/A

**Symptoms**: Three scripts in `scripts/` contain hardcoded production credentials in plaintext: the sudo password (`echo <password> | sudo -S` pattern) and the replication user's database password in a connection string.

**Root Cause**: `check_repl_status.sh`, `check_sync_status.sh`, and `fix_replication.sh` were written with inline credentials for convenience during initial setup. These credentials are visible in git history to any developer, CI pipeline, or code scanner.

**Fix Applied**:
1. Removed all `echo <password> | sudo -S` prefixes — replaced with bare `sudo` (relies on SSH key auth and NOPASSWD sudoers)
2. Removed hardcoded database password from `fix_replication.sh` — replaced connection string with `${HA_PEER_DB_URL}` environment variable reference
3. Added prerequisite header comments to all three scripts documenting SSH key auth, NOPASSWD sudoers, and env var requirements
4. Rotated leaked credentials on production server

**Files Changed**:
- `scripts/check_repl_status.sh`
- `scripts/check_sync_status.sh`
- `scripts/fix_replication.sh`

**Similar Bugs Found & Fixed**: No other scripts contained hardcoded credentials.

**Related Issues**: N/A

**Spec**: `.kiro/specs/ha-replication-bugfixes/`

---

### ISSUE-117: Startup heartbeat service ignores DB-stored secret — uses env var only

- **Date**: 2026-04-26
- **Severity**: high
- **Status**: resolved
- **Reporter**: agent (HA audit)
- **Regression of**: N/A

**Symptoms**: After setting the heartbeat secret via the HA admin UI and restarting the app container, heartbeat HMAC verification fails with "Invalid HMAC signature" on every ping. The secret set through the UI is stored encrypted in the DB but the startup code reads only from `HA_HEARTBEAT_SECRET` env var.

**Root Cause**: `_start_ha_heartbeat()` in `app/main.py` used `os.environ.get("HA_HEARTBEAT_SECRET", "")` exclusively. The runtime path (`HAService.save_config`) correctly uses `_get_heartbeat_secret_from_config(cfg_orm)` which reads the encrypted DB value, but the startup path bypassed this entirely. Additionally, `local_role` was not passed to the `HeartbeatService` constructor at startup, causing split-brain detection to always compare `"standalone"` against the peer's role.

**Fix Applied**:
1. Changed startup to load `HAConfig` ORM object and call `_get_heartbeat_secret_from_config(cfg_orm)` instead of reading env var directly
2. Added `local_role=cfg_orm.role` to `HeartbeatService()` constructor call
3. Falls back to env var when no DB-stored secret exists (matching existing runtime behaviour)

**Files Changed**:
- `app/main.py`

**Similar Bugs Found & Fixed**: N/A

**Related Issues**: ISSUE-088 (HMAC mismatch between Pi and standby)

**Spec**: `.kiro/specs/ha-replication-bugfixes/`

---

### ISSUE-118: No WAL disk space guard — unbounded WAL retention can crash primary

- **Date**: 2026-04-26
- **Severity**: high
- **Status**: resolved
- **Reporter**: agent (HA audit)
- **Regression of**: N/A

**Symptoms**: When the standby goes offline, the primary's replication slot accumulates WAL indefinitely with no upper bound. On the Raspberry Pi with limited storage, this can fill the disk and crash PostgreSQL with `FATAL: could not write to file "pg_wal/..."`. The Pi compose also had `max_replication_slots=150`, allowing up to 150 orphaned slots to each accumulate WAL independently.

**Root Cause**: `max_slot_wal_keep_size` was not set in any compose file, so PostgreSQL retained all WAL from the slot's `restart_lsn` indefinitely. The base `docker-compose.yml` also had no explicit `max_wal_senders` or `max_replication_slots`, silently depending on PostgreSQL defaults.

**Fix Applied**:
1. `docker-compose.pi.yml`: Added `max_slot_wal_keep_size=2048` (2 GB ceiling), changed `max_replication_slots=150` to `max_replication_slots=10`
2. `docker-compose.yml`: Added explicit `max_wal_senders=10` and `max_replication_slots=10`
3. `docker-compose.standby-prod.yml`: Added `max_slot_wal_keep_size=2048`

**Files Changed**:
- `docker-compose.pi.yml`
- `docker-compose.yml`
- `docker-compose.standby-prod.yml`

**Similar Bugs Found & Fixed**: Base compose WAL settings (ISSUE-119) fixed in the same pass.

**Related Issues**: ISSUE-119

**Spec**: `.kiro/specs/ha-replication-bugfixes/`

---

### ISSUE-119: Base compose missing explicit WAL settings — relies on PostgreSQL defaults

- **Date**: 2026-04-26
- **Severity**: medium
- **Status**: resolved
- **Reporter**: agent (HA audit)
- **Regression of**: N/A

**Symptoms**: When a developer sets up a local dev HA environment using only `docker-compose.yml` (without the Pi overlay), the postgres command only has `wal_level=logical` but no `max_wal_senders` or `max_replication_slots`. Replication works by accident (defaults are sufficient for 1 standby) but the configuration is not intentional or auditable.

**Root Cause**: `docker-compose.yml` postgres command section only had `wal_level=logical` without explicit sender/slot settings.

**Fix Applied**: Added `-c max_wal_senders=10` and `-c max_replication_slots=10` to the postgres command in `docker-compose.yml`, making replication capability intentional and auditable.

**Files Changed**:
- `docker-compose.yml`

**Similar Bugs Found & Fixed**: Combined with ISSUE-118 WAL guard fix.

**Related Issues**: ISSUE-118

**Spec**: `.kiro/specs/ha-replication-bugfixes/`

---

### ISSUE-120: Replication lag metric uses last_msg_send_time — understates true lag

- **Date**: 2026-04-26
- **Severity**: medium
- **Status**: resolved
- **Reporter**: agent (HA audit)
- **Regression of**: N/A

**Symptoms**: The HA admin page shows near-zero replication lag even when the subscription is lagging in LSN terms. During periods of low write activity, `last_msg_send_time` is refreshed by keepalive pings and reports near-zero lag. The promote safety guard (`lag > 5.0 → require force`) allows promotion without force despite significant data loss risk.

**Root Cause**: `get_replication_lag` and `get_replication_status` used `EXTRACT(EPOCH FROM (now() - last_msg_send_time))` from `pg_stat_subscription`. `last_msg_send_time` is updated by keepalive messages sent every few seconds regardless of data changes, substantially understating true replication lag.

**Fix Applied**: Changed both functions to use `GREATEST(last_msg_send_time, last_msg_receipt_time)`. `last_msg_receipt_time` is only updated when data arrives, making it a more accurate lag indicator during active replication. Using `GREATEST` of both ensures the metric reflects the most recent meaningful activity. Added comment explaining the rationale.

**Files Changed**:
- `app/modules/ha/replication.py`

**Similar Bugs Found & Fixed**: Fixed in both `get_replication_lag` and `get_replication_status` in the same pass.

**Related Issues**: ISSUE-114 (lag fix was part of the sequence replication task)

**Spec**: `.kiro/specs/ha-replication-bugfixes/`

---

### ISSUE-121: Multi-worker gunicorn spawns independent heartbeat per worker — race conditions

- **Date**: 2026-04-26
- **Severity**: high
- **Status**: resolved
- **Reporter**: agent (HA audit)
- **Regression of**: N/A

**Symptoms**: With `--workers 2`, the standby receives two heartbeat pings per interval (double the expected load). Two independent auto-promote executions can race: both workers detect the timeout, both call `_execute_auto_promote()`, creating a race condition on `cfg.role` update and writing duplicate audit log entries. The heartbeat response cache `_hb_cache` invalidation after `save_config` only affects the worker that handled the request.

**Root Cause**: Each gunicorn worker independently executes `_start_ha_heartbeat()`, creating separate `HeartbeatService` instances with separate `asyncio.Task` background loops. Module-level state (`_peer_unreachable_since`, `_auto_promote_attempted`, `_hb_cache`) is per-process, not shared across workers.

**Fix Applied**:
1. Added Redis distributed lock (`SET NX EX`) in `_start_ha_heartbeat()` — only the lock-holder starts the heartbeat loop
2. Added lock TTL renewal in `HeartbeatService._ping_loop` after each successful ping cycle
3. Added separate Redis promotion lock in `_execute_auto_promote()` to prevent race conditions
4. Added Redis dirty-flag (`ha:hb_cache_dirty`) in `save_config` for cross-worker cache invalidation
5. Added Redis dirty-flag check in heartbeat endpoint handler — forces cache miss if dirty flag present
6. Fallback: if Redis unavailable, log warning and proceed without lock (single-worker behaviour)

**Files Changed**:
- `app/main.py`
- `app/modules/ha/heartbeat.py`
- `app/modules/ha/service.py`
- `app/modules/ha/router.py`

**Similar Bugs Found & Fixed**: ISSUE-125 (cache invalidation) is fully covered by the Redis dirty-flag mechanism in this fix.

**Related Issues**: ISSUE-125

**Spec**: `.kiro/specs/ha-replication-bugfixes/`

---

### ISSUE-122: Split-brain undetectable and undocumented during full network partition

- **Date**: 2026-04-26
- **Severity**: medium
- **Status**: resolved
- **Reporter**: agent (HA audit)
- **Regression of**: N/A

**Symptoms**: During a full network partition where neither node can reach the other, split-brain detection is inactive because it relies on successful heartbeat communication. If auto-promote is enabled, the standby promotes after the failover timeout, resulting in two independent primaries with diverging data. This limitation was not documented.

**Root Cause**: `detect_split_brain(self.local_role, peer_role)` only executes when `_ping_peer()` returns a successful heartbeat response with a `role` field. During a full partition, pings fail and split-brain detection never runs. This is an inherent limitation of a 2-node active-standby design without a quorum mechanism.

**Fix Applied**: No code changes — documentation-only fix:
1. Added explicit network partition warning block to `docs/HA_REPLICATION_GUIDE.md` under the Unplanned Failover section, explaining the limitation and recovery procedure
2. Added tooltip text on the auto-promote toggle in the HA admin frontend component

**Files Changed**:
- `docs/HA_REPLICATION_GUIDE.md`

**Similar Bugs Found & Fixed**: N/A — inherent 2-node design limitation.

**Related Issues**: N/A

**Spec**: `.kiro/specs/ha-replication-bugfixes/`

---

### ISSUE-123: Standby dev compose missing statement and idle-transaction timeouts

- **Date**: 2026-04-26
- **Severity**: medium
- **Status**: resolved
- **Reporter**: agent (HA audit)
- **Regression of**: N/A

**Symptoms**: A session on the dev standby that hangs inside a transaction (bug, deadlock, forgotten commit) is never killed, masking timeout-related bugs that would surface in production. The production standby (`docker-compose.standby-prod.yml`) and Pi primary (`docker-compose.pi.yml`) both have 30000ms timeouts, but the dev standby does not.

**Root Cause**: `docker-compose.ha-standby.yml` was missing `idle_in_transaction_session_timeout` and `statement_timeout` postgres command args.

**Fix Applied**: Added `-c idle_in_transaction_session_timeout=30000` and `-c statement_timeout=30000` to the postgres command in `docker-compose.ha-standby.yml`, matching the production standby configuration.

**Files Changed**:
- `docker-compose.ha-standby.yml`

**Similar Bugs Found & Fixed**: N/A

**Related Issues**: N/A

**Spec**: `.kiro/specs/ha-replication-bugfixes/`

---

### ISSUE-124: pg_hba.conf unmanaged — replication connections not IP-restricted

- **Date**: 2026-04-26
- **Severity**: medium
- **Status**: resolved
- **Reporter**: agent (HA audit)
- **Regression of**: N/A

**Symptoms**: The PostgreSQL Docker image uses default `pg_hba.conf` rules which allow all authenticated connections from any host. Any host on the VPN/network that knows the replication user credentials can establish a replication connection to the primary, even if it is not the designated standby. The HA guide documented IP-based restrictions but provided no script or mechanism to deploy them.

**Root Cause**: No script, entrypoint, or compose mechanism existed to configure `pg_hba.conf` inside the Docker container with IP-specific replication rules.

**Fix Applied**:
1. Created `scripts/configure_pg_hba.sh` that appends IP-specific `hostssl replication` and `hostssl all` rules for the replicator user to the postgres container's `pg_hba.conf` and reloads the configuration via `pg_reload_conf()`
2. Added reference to the new script in `docs/HA_REPLICATION_GUIDE.md` under the Security section

**Files Changed**:
- `scripts/configure_pg_hba.sh` (new)
- `docs/HA_REPLICATION_GUIDE.md`

**Similar Bugs Found & Fixed**: N/A

**Related Issues**: N/A

**Spec**: `.kiro/specs/ha-replication-bugfixes/`

---

### ISSUE-125: Heartbeat cache invalidation is single-worker only in multi-worker gunicorn

- **Date**: 2026-04-26
- **Severity**: low
- **Status**: resolved
- **Reporter**: agent (HA audit)
- **Regression of**: N/A

**Symptoms**: After `save_config` completes in one gunicorn worker, other workers continue serving stale heartbeat config (role, secret, maintenance mode) from their in-memory `_hb_cache` for up to 10 seconds.

**Root Cause**: `save_config` invalidates the cache by setting `_hb_cache["ts"] = 0` in the current worker's memory. Other workers' caches are unaffected because each process has its own memory space.

**Fix Applied**: Covered by the Redis dirty-flag mechanism in ISSUE-121 (BUG-HA-06 fix). When `save_config` completes, it writes `ha:hb_cache_dirty` to Redis. All workers check this flag before serving cached heartbeat responses. If Redis is unavailable, the existing 10-second TTL-based expiry takes over.

**Files Changed**:
- `app/modules/ha/service.py`
- `app/modules/ha/router.py`

**Similar Bugs Found & Fixed**: N/A — fully covered by ISSUE-121.

**Related Issues**: ISSUE-121

**Spec**: `.kiro/specs/ha-replication-bugfixes/`

---

### ISSUE-126: WebSocket connections bypass standby write-protection middleware

- **Date**: 2026-04-26
- **Severity**: low
- **Status**: resolved
- **Reporter**: agent (HA audit)
- **Regression of**: N/A

**Symptoms**: WebSocket connections on a standby node bypass the `StandbyWriteProtectionMiddleware` entirely. The middleware checks `if scope["type"] != "http"` and passes through unconditionally for non-HTTP scopes. Any future WebSocket handler that writes to the database would silently succeed on a standby, bypassing the protection the middleware was designed to enforce.

**Root Cause**: `StandbyWriteProtectionMiddleware.__call__` only handled `scope["type"] == "http"` and passed all other scope types (including `websocket`) through without any write-protection check.

**Fix Applied**:
1. Extended the middleware to handle `scope["type"] == "websocket"` connections
2. Added WebSocket path allowlist: `/ws/kitchen/` (read-only Redis pub/sub) and `/api/v1/ha/` (HA management)
3. Non-allowlisted WebSocket paths on standby are closed with code 1013 (Try Again Later) and a descriptive reason message

**Files Changed**:
- `app/modules/ha/middleware.py`

**Similar Bugs Found & Fixed**: N/A

**Related Issues**: N/A

**Spec**: `.kiro/specs/ha-replication-bugfixes/`

---

### ISSUE-127: dead_letter table replicated — may cause double-processing after failover

- **Date**: 2026-04-26
- **Severity**: low
- **Status**: resolved
- **Reporter**: agent (HA audit)
- **Regression of**: N/A

**Symptoms**: After failover, the new primary (former standby) inherits all `dead_letter` entries from the old primary. The background task processor may re-attempt these partially-executed operations, causing double side-effects (duplicate emails, duplicate payment attempts, duplicate webhook deliveries).

**Root Cause**: `init_primary` builds the publication table list excluding only `ha_config`. The `dead_letter` table (failed background jobs) is included in the publication and replicated to the standby. After promotion, the new primary's task processor sees these entries and re-attempts them.

**Fix Applied**:
1. Changed the table exclusion filter in `init_primary` from `!= 'ha_config'` to `NOT IN ('ha_config', 'dead_letter_queue')` (actual table name verified from `app/models/dead_letter.py`)
2. Added comment in `filter_tables_for_truncation` explaining why `dead_letter` is excluded from publication but not from truncation

**Files Changed**:
- `app/modules/ha/replication.py`

**Similar Bugs Found & Fixed**: N/A

**Related Issues**: N/A

**Spec**: `.kiro/specs/ha-replication-bugfixes/`

---

### ISSUE-128: Peer role inferred as opposite of local — incorrect in standalone mode

- **Date**: 2026-04-26
- **Severity**: low
- **Status**: resolved
- **Reporter**: agent (HA audit)
- **Regression of**: N/A

**Symptoms**: In standalone mode, `GET /api/v1/ha/cluster-status` shows the peer entry with `role: "primary"` (inferred as opposite of `"standalone"`), which is incorrect. The peer's actual role is available from heartbeat responses but was never stored or used.

**Root Cause**: `get_cluster_status` in `service.py` sets `peer_role = "standby" if cfg.role == "primary" else "primary"`, always producing the opposite of the local role. This is wrong for standalone mode and also wrong when the peer is in an unexpected state. The heartbeat response payload already contains the peer's actual role (`data.get("role")`) but this data was discarded after each ping.

**Fix Applied**:
1. Added `self.peer_role: str = "unknown"` to `HeartbeatService.__init__`
2. Set `self.peer_role = data.get("role", "unknown")` in `_ping_peer()` on successful response
3. Changed `get_cluster_status` to use `_heartbeat_service.peer_role` instead of the inferred opposite role
4. Defaults to `"unknown"` when no heartbeat has been received yet

**Files Changed**:
- `app/modules/ha/heartbeat.py`
- `app/modules/ha/service.py`

**Similar Bugs Found & Fixed**: N/A

**Related Issues**: N/A

**Spec**: `.kiro/specs/ha-replication-bugfixes/`


---

### ISSUE-129: `trigger_resync` orphaned slot — resync always fails on second call

- **Date**: 2026-04-27
- **Severity**: critical
- **Status**: resolved
- **Reporter**: agent (HA post-bugfix review round 2)
- **Regression of**: N/A

**Symptoms**: Calling "Resync" on a standby that previously had a subscription always fails with `ERROR: replication slot "orainvoice_ha_sub" already exists` on the `CREATE SUBSCRIPTION` step. The standby is left with all tables truncated (step 1 succeeded) and no subscription (step 3 failed), making it fully broken with no data and no replication — requiring manual `psql` intervention to recover.

**Root Cause**: `trigger_resync` calls `drop_subscription(db)` which executes `ALTER SUBSCRIPTION ... SET (slot_name = NONE)`, orphaning the replication slot named `orainvoice_ha_sub` on the primary. It then immediately executes `CREATE SUBSCRIPTION ... WITH (copy_data = true)` which fails because the orphaned slot still exists on the primary. The `init_standby` path correctly handles this via `_cleanup_orphaned_slot_on_peer`, but `trigger_resync` was written separately and skips this cleanup step.

**Fix Applied**: Added `await ReplicationManager._cleanup_orphaned_slot_on_peer(primary_conn_str)` between `drop_subscription(db)` and the `CREATE SUBSCRIPTION` SQL in `trigger_resync`. This follows the exact pattern already used by `init_standby` for orphaned slot handling. Added comment: `# Step 3: clean up orphaned slot left on primary by SET (slot_name = NONE)`.

**Files Changed**:
- `app/modules/ha/replication.py`

**Similar Bugs Found & Fixed**: N/A — `init_standby` already had correct orphaned slot cleanup.

**Related Issues**: ISSUE-115 (trigger_resync truncation fix from round 1)

**Spec**: `.kiro/specs/ha-replication-bugfixes-2/`

---

### ISSUE-130: `promote()`/`demote()`/`demote_and_sync()` don't update `_heartbeat_service.local_role`

- **Date**: 2026-04-27
- **Severity**: critical
- **Status**: resolved
- **Reporter**: agent (HA post-bugfix review round 2)
- **Regression of**: N/A

**Symptoms**: Three distinct failure modes depending on which manual role transition is used:

1. **After `promote()`**: `_heartbeat_service.local_role` stays `"standby"`, so `detect_split_brain("standby", peer_role)` never returns `True` even when both nodes are simultaneously primary — true split-brain goes undetected.
2. **After `demote()`**: `_heartbeat_service.local_role` stays `"primary"`, so `detect_split_brain("primary", "primary")` returns `True` on the next heartbeat — a spurious split-brain detection that persists until container restart, blocking all requests with misleading "split-brain detected" errors.
3. **After `demote_and_sync()`**: Same spurious split-brain as `demote()`.

**Root Cause**: The auto-promote path (`_execute_auto_promote`) correctly sets `self.local_role = "primary"` directly on the heartbeat service instance. However, the three manual role transition functions (`promote()`, `demote()`, `demote_and_sync()`) only call `set_node_role()` to update the middleware cache but never update `_heartbeat_service.local_role`. This is a simple omission — the auto-promote code shows the correct pattern.

**Fix Applied**: Added `_heartbeat_service.local_role` update after `set_node_role()` in all three functions:

1. In `promote()`: Added `if _heartbeat_service is not None: _heartbeat_service.local_role = "primary"` after `set_node_role("primary", cfg.peer_endpoint)`
2. In `demote()`: Added `if _heartbeat_service is not None: _heartbeat_service.local_role = "standby"` after `set_node_role("standby", cfg.peer_endpoint)`
3. In `demote_and_sync()`: Added `if _heartbeat_service is not None: _heartbeat_service.local_role = "standby"` after `set_node_role("standby", cfg.peer_endpoint)`

All three follow the exact pattern from `_execute_auto_promote` and include a `None` guard for when the heartbeat service is not running.

**Files Changed**:
- `app/modules/ha/service.py`

**Similar Bugs Found & Fixed**: N/A — the auto-promote path already had the correct pattern.

**Related Issues**: ISSUE-121 (multi-worker heartbeat race conditions from round 1)

**Spec**: `.kiro/specs/ha-replication-bugfixes-2/`

---

### ISSUE-131: `drop_replication_slot` router passes `None` as db → 500 on every call

- **Date**: 2026-04-27
- **Severity**: critical
- **Status**: resolved
- **Reporter**: agent (HA post-bugfix review round 2)
- **Regression of**: N/A

**Symptoms**: Calling `DELETE /api/v1/ha/replication/slots/{slot_name}` always returns 500 Internal Server Error with `AttributeError: 'NoneType' object has no attribute 'execute'`. The endpoint is completely non-functional.

**Root Cause**: The `drop_replication_slot` endpoint function in `app/modules/ha/router.py` has no `db: AsyncSession = Depends(get_db_session)` parameter. It passes `None` to `ReplicationManager.drop_replication_slot(None, slot_name)`, which calls `db.execute()` on `None`. The adjacent `list_replication_slots` endpoint has the `db` dependency correctly — this was a copy-paste omission when the drop endpoint was added.

**Fix Applied**: Added `db: AsyncSession = Depends(get_db_session)` parameter to the `drop_replication_slot` function signature and changed the call from `ReplicationManager.drop_replication_slot(None, slot_name)` to `ReplicationManager.drop_replication_slot(db, slot_name)`. This matches the pattern used by the adjacent `list_replication_slots` endpoint.

**Files Changed**:
- `app/modules/ha/router.py`

**Similar Bugs Found & Fixed**: N/A — all other HA router endpoints have the `db` dependency correctly.

**Related Issues**: N/A

**Spec**: `.kiro/specs/ha-replication-bugfixes-2/`

---

### ISSUE-132: `save_config` restarts heartbeat without Redis lock info

- **Date**: 2026-04-27
- **Severity**: significant
- **Status**: resolved
- **Reporter**: agent (HA post-bugfix review round 2)
- **Regression of**: N/A

**Symptoms**: After changing HA config (peer endpoint, secret, etc.) via the admin UI, the heartbeat service restarts but the Redis heartbeat lock (`ha:heartbeat_lock`) expires within 30 seconds. After expiry, a second gunicorn worker starts a duplicate heartbeat service, reintroducing the multi-worker race condition fixed in ISSUE-121 (BUG-HA-06).

**Root Cause**: `save_config` in `service.py` creates a new `HeartbeatService` instance when config changes require a heartbeat restart. However, it never sets `_redis_lock_key`, `_lock_ttl`, or `_redis_client` on the new instance. The initial startup path (`_start_ha_heartbeat` in `main.py`) correctly wires these attributes, but `save_config` was written before the Redis lock mechanism was added and was never updated.

**Fix Applied**: Added Redis lock wiring after creating the new `HeartbeatService` and before calling `start()` in `save_config`, replicating the exact pattern from `_start_ha_heartbeat` in `main.py`:

```python
try:
    from app.core.redis import redis_pool
    _heartbeat_service._redis_lock_key = "ha:heartbeat_lock"
    _heartbeat_service._lock_ttl = 30
    _heartbeat_service._redis_client = redis_pool
except Exception:
    pass  # Redis unavailable — lock renewal won't work but service still runs
```

**Files Changed**:
- `app/modules/ha/service.py`

**Similar Bugs Found & Fixed**: N/A — the initial startup path in `main.py` already had correct Redis lock wiring.

**Related Issues**: ISSUE-121 (multi-worker heartbeat race conditions — the fix this bug undermines)

**Spec**: `.kiro/specs/ha-replication-bugfixes-2/`

---

### ISSUE-133: `demote()` uses `copy_data=true` on full dataset and doesn't drop publication

- **Date**: 2026-04-27
- **Severity**: significant
- **Status**: resolved
- **Reporter**: agent (HA post-bugfix review round 2)
- **Regression of**: N/A

**Symptoms**: Two issues during manual demotion of a primary to standby:

1. **Duplicate PK violations**: When `demote()` calls `resume_subscription()` and the fallback path (re-create subscription) executes, PostgreSQL attempts a full initial table sync on a node that already has all the data, causing duplicate primary-key violations on every table. The demotion fails and the node is left in an inconsistent state.
2. **Orphaned publication**: `demote()` never calls `drop_publication()`, leaving the former primary with an active publication (`orainvoice_ha_pub`) that retains WAL unnecessarily and is conceptually incorrect for a standby node.

**Root Cause**: Two separate omissions in the demote flow:

1. The `resume_subscription` fallback `CREATE SUBSCRIPTION` SQL has no `WITH (copy_data = false)` clause, defaulting to `copy_data=true`. During demotion, the former primary already has all the data, so `copy_data=true` causes PostgreSQL to attempt a full initial table sync that conflicts with existing rows.
2. `demote()` transitions a primary to standby but never drops the publication. The publication should be removed because a standby node should not hold an active publication.

**Fix Applied**:

1. **`copy_data=false` in fallback path**: Changed the fallback `CREATE SUBSCRIPTION` SQL in `resume_subscription` (in `replication.py`) from `PUBLICATION {name}` to `PUBLICATION {name} WITH (copy_data = false)` to prevent duplicate-key violations when the node already has all the data.

2. **Drop publication in `demote()`**: Added a `drop_publication(db)` call in `demote()` (in `service.py`) before the `resume_subscription` call, wrapped in try/except so a failure to drop the publication doesn't block the demotion:
   ```python
   try:
       await ReplicationManager.drop_publication(db)
   except Exception as exc:
       logger.warning("Could not drop publication during demote: %s", exc)
   ```

**Files Changed**:
- `app/modules/ha/replication.py` (added `WITH (copy_data = false)` to `resume_subscription` fallback)
- `app/modules/ha/service.py` (added `drop_publication` call in `demote()`)

**Similar Bugs Found & Fixed**: N/A — the `resume_subscription` enable path (ALTER SUBSCRIPTION ENABLE) is unchanged and does not need `copy_data` since it re-enables an existing subscription without re-copying.

**Related Issues**: N/A

**Spec**: `.kiro/specs/ha-replication-bugfixes-2/`

---

### ISSUE-134: Dev standby compose missing `max_wal_senders` and `max_replication_slots`

- **Date**: 2026-04-27
- **Severity**: minor
- **Status**: resolved
- **Reporter**: agent (HA post-bugfix review round 2)
- **Regression of**: N/A

**Symptoms**: The dev standby postgres (`docker-compose.ha-standby.yml`) starts without explicit `max_wal_senders` or `max_replication_slots` settings. Replication works by coincidence (PostgreSQL 16 defaults are sufficient for 1 standby) but the configuration is not intentional or auditable. All other compose files (`docker-compose.yml`, `docker-compose.pi.yml`, `docker-compose.standby-prod.yml`) have these settings explicitly declared.

**Root Cause**: `docker-compose.ha-standby.yml` was missing `-c max_wal_senders=10` and `-c max_replication_slots=10` in the postgres command args. This was an oversight when the other compose files were updated in ISSUE-118/ISSUE-119 (round 1 HA bugfixes) — the dev standby compose was missed.

**Fix Applied**: Appended `-c max_wal_senders=10` and `-c max_replication_slots=10` to the postgres command list in `docker-compose.ha-standby.yml`, matching all other compose files. Existing settings (`wal_level=logical`, `idle_in_transaction_session_timeout=30000`, `statement_timeout=30000`, SSL configuration) are unchanged.

**Files Changed**:
- `docker-compose.ha-standby.yml`

**Similar Bugs Found & Fixed**: N/A — all other compose files already have explicit WAL settings from ISSUE-118/ISSUE-119.

**Related Issues**: ISSUE-118 (WAL disk space guard), ISSUE-119 (base compose WAL settings)

**Spec**: `.kiro/specs/ha-replication-bugfixes-2/`


---

### ISSUE-135: Leaked password in `.env.standby-prod` + active `HA_PEER_DB_URL` env fallback in `get_peer_db_url()`

- **Date**: 2026-04-27
- **Severity**: critical
- **Status**: fixed
- **Reporter**: agent (HA GUI config cleanup audit round 3)
- **Regression of**: N/A

**Symptoms**: `.env.standby-prod` contained a hardcoded production password in the `HA_PEER_DB_URL` line (`postgresql://replicator:NoorHarleen1@192.168.1.90:5432/workshoppro`). Additionally, `get_peer_db_url()` in `service.py` fell back to `os.environ.get("HA_PEER_DB_URL")` when DB-stored peer config was empty, silently using the leaked credential instead of returning `None`. The `.env` and `.env.ha-standby` files also had non-empty `HA_PEER_DB_URL` values with dev credentials.

**Root Cause**: The BUG-HA-03 fix added a DB-preferred path for peer DB URL retrieval but left the `os.environ.get("HA_PEER_DB_URL")` fallback as a safety net at `service.py:142`. The `.env*` files were never cleared of their `HA_PEER_DB_URL` values after the GUI migration, leaving a production password in plaintext in `.env.standby-prod` and dev credentials in `.env` and `.env.ha-standby`.

**Fix Applied**:
1. Cleared `HA_PEER_DB_URL` to empty in `.env.standby-prod`, `.env`, and `.env.ha-standby` (set to `HA_PEER_DB_URL=`)
2. Removed the env fallback in `get_peer_db_url()`: changed `return os.environ.get("HA_PEER_DB_URL") or None` to `return None`
3. `.env.pi` and `.env.pi-standby` already had blank `HA_PEER_DB_URL=` — no change needed

**Files Changed**:
- `app/modules/ha/service.py`
- `.env`
- `.env.ha-standby`
- `.env.standby-prod`

**Similar Bugs Found & Fixed**: Same env-fallback pattern existed for `HA_HEARTBEAT_SECRET` (see ISSUE-136).

**Related Issues**: ISSUE-136 (heartbeat secret env fallback — same class of bug)

**Spec**: `.kiro/specs/ha-gui-config-cleanup/`

---

### ISSUE-136: `HA_HEARTBEAT_SECRET` env fallback still active in `_get_heartbeat_secret_from_config()` and heartbeat endpoint; dev secret in all `.env*` files

- **Date**: 2026-04-27
- **Severity**: moderate
- **Status**: fixed
- **Reporter**: agent (HA GUI config cleanup audit round 3)
- **Regression of**: N/A

**Symptoms**: When the DB-stored `heartbeat_secret` was empty or decryption failed, `_get_heartbeat_secret_from_config()` at `service.py:72` fell back to `os.environ.get("HA_HEARTBEAT_SECRET", "")`, silently using the weak dev secret `dev-ha-secret-for-testing` from env files for HMAC signing. The heartbeat endpoint at `router.py:165` had the same env fallback in its cache-miss branch. All four `.env*` files (`.env`, `.env.pi`, `.env.ha-standby`, `.env.standby-prod`) contained `HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing`.

**Root Cause**: The BUG-HA-04 fix introduced `_get_heartbeat_secret_from_config()` as the DB-preferred path but left `os.environ.get("HA_HEARTBEAT_SECRET", "")` as a fallback in both the service function and the heartbeat endpoint cache-miss branch. The `.env*` files were never cleared of their dev secret values after the GUI migration.

**Fix Applied**:
1. Removed env fallback in `_get_heartbeat_secret_from_config()`: changed `return os.environ.get("HA_HEARTBEAT_SECRET", "")` to `return ""`
2. Removed env fallback in heartbeat endpoint cache-miss: changed `secret = os.environ.get("HA_HEARTBEAT_SECRET", "")` to `secret = ""`
3. Cleared `HA_HEARTBEAT_SECRET` to empty in `.env`, `.env.pi`, `.env.ha-standby`, and `.env.standby-prod` (set to `HA_HEARTBEAT_SECRET=`)
4. `.env.pi-standby` already had blank `HA_HEARTBEAT_SECRET=` — no change needed

**Files Changed**:
- `app/modules/ha/service.py`
- `app/modules/ha/router.py`
- `.env`
- `.env.pi`
- `.env.ha-standby`
- `.env.standby-prod`

**Similar Bugs Found & Fixed**: Same env-fallback pattern existed for `HA_PEER_DB_URL` (see ISSUE-135).

**Related Issues**: ISSUE-135 (peer DB URL env fallback — same class of bug)

**Spec**: `.kiro/specs/ha-gui-config-cleanup/`

---

### ISSUE-137: Error messages at `replication/init` and `replication/resync` still reference `HA_PEER_DB_URL` env var

- **Date**: 2026-04-27
- **Severity**: moderate
- **Status**: fixed
- **Reporter**: agent (HA GUI config cleanup audit round 3)
- **Regression of**: N/A

**Symptoms**: When `POST /ha/replication/init` or `POST /ha/replication/resync` detected no peer DB URL on a standby node, the error message said "Peer database connection is not configured. Set peer DB settings in HA configuration or set HA_PEER_DB_URL environment variable." This directed users to use an env var that should no longer be the configuration path after the GUI migration.

**Root Cause**: The error messages at `router.py:449` (replication_init) and `router.py:521` (replication_resync) were written when the env var was the primary configuration path and were never updated after the GUI migration.

**Fix Applied**: Updated both error messages to remove the env var reference:
- Changed `"Peer database connection is not configured. Set peer DB settings in HA configuration or set HA_PEER_DB_URL environment variable."` to `"Peer database connection is not configured. Set peer DB settings in HA configuration."`

**Files Changed**:
- `app/modules/ha/router.py`

**Similar Bugs Found & Fixed**: N/A — these were the only two error messages referencing `HA_PEER_DB_URL`.

**Related Issues**: ISSUE-135 (env fallback removal for the same env var)

**Spec**: `.kiro/specs/ha-gui-config-cleanup/`

---

### ISSUE-138: No GUI fields for `local_lan_ip`/`local_pg_port`; auto-detect returns wrong IP in Docker on Linux

- **Date**: 2026-04-27
- **Severity**: moderate
- **Status**: fixed
- **Reporter**: agent (HA GUI config cleanup audit round 3)
- **Regression of**: N/A

**Symptoms**: The "View Connection Info" modal displayed an auto-detected LAN IP using a UDP socket trick that returned the Docker container's internal IP (e.g., `172.17.0.2`) on Linux production instead of the host's LAN IP (e.g., `192.168.1.90`). The only override was the `HA_LOCAL_LAN_IP` env var, which had no GUI equivalent. Similarly, the PostgreSQL port defaulted to reading `HA_LOCAL_PG_PORT` from the environment with no GUI field. The `HAConfig` model had no `local_lan_ip` or `local_pg_port` columns.

**Root Cause**: `local_lan_ip` and `local_pg_port` were never part of the original HA design — they were added as env-var overrides for Docker-specific issues. The `HAConfig` model, schemas, service, router, and frontend were never extended to support them as GUI-configurable fields.

**Fix Applied**:
1. Added `local_lan_ip` (VARCHAR 255, nullable) and `local_pg_port` (INTEGER, nullable) columns to the `HAConfig` model
2. Created Alembic migration to add both columns to the `ha_config` table
3. Added `local_lan_ip` and `local_pg_port` fields to `HAConfigRequest` and `HAConfigResponse` schemas
4. Updated `save_config()` to persist both fields and `_config_to_response()` to return them
5. Updated `local_db_info()` and `create_replication_user()` endpoints to prioritize DB fields over env vars over auto-detect
6. Added "Local LAN IP" and "Local PostgreSQL Port" form fields to the frontend HA configuration form with helper text

**Files Changed**:
- `app/modules/ha/models.py`
- `app/modules/ha/schemas.py`
- `app/modules/ha/service.py`
- `app/modules/ha/router.py`
- `frontend/src/pages/admin/HAReplication.tsx`
- `alembic/versions/` (new migration)

**Similar Bugs Found & Fixed**: N/A

**Related Issues**: N/A

**Spec**: `.kiro/specs/ha-gui-config-cleanup/`

---

### ISSUE-139: Peer role hardcoded as logical opposite in frontend; `FailoverStatusResponse` missing `peer_role` field

- **Date**: 2026-04-27
- **Severity**: moderate
- **Status**: fixed
- **Reporter**: agent (HA GUI config cleanup audit round 3)
- **Regression of**: N/A

**Symptoms**: The Cluster Status peer card in `HAReplication.tsx` displayed `config.role === 'primary' ? 'Standby' : 'Primary'` as the peer role — a hardcoded logical opposite of the local role. After a promotion or demotion, both nodes could show incorrect peer roles. The actual peer role was already available in `_heartbeat_service.peer_role` (from the BUG-HA-15 fix) but the `/ha/failover-status` endpoint did not include it in its response, so the frontend had no way to display it.

**Root Cause**: The BUG-HA-15 fix stored `peer_role` in `_heartbeat_service.peer_role` and exposed it through `get_cluster_status()`, but the `/ha/failover-status` endpoint (which the frontend polls) was never updated to include a `peer_role` field in `FailoverStatusResponse`. The frontend fell back to a hardcoded logical opposite.

**Fix Applied**:
1. Added `peer_role: str = Field(default="unknown")` to `FailoverStatusResponse` schema
2. Populated `peer_role` from `_heartbeat_service.peer_role` in the `failover_status()` endpoint
3. Added `peer_role?: string` to the `FailoverStatus` TypeScript interface
4. Changed the peer card Badge to use `failoverStatus?.peer_role ?? (config.role === 'primary' ? 'standby' : 'primary')` instead of the hardcoded opposite

**Files Changed**:
- `app/modules/ha/schemas.py`
- `app/modules/ha/router.py`
- `frontend/src/pages/admin/HAReplication.tsx`

**Similar Bugs Found & Fixed**: N/A

**Related Issues**: N/A

**Spec**: `.kiro/specs/ha-gui-config-cleanup/`

---

### ISSUE-140: `stop-replication` on primary has no CONFIRM gate; can accidentally drop publication

- **Date**: 2026-04-27
- **Severity**: moderate
- **Status**: fixed
- **Reporter**: agent (HA GUI config cleanup audit round 3)
- **Regression of**: N/A

**Symptoms**: Clicking "Stop Replication" on a primary node dropped the publication (halting all data flow to the standby) without requiring the user to type CONFIRM. All other destructive HA actions (promote, demote, resync, demote-and-sync) required typing CONFIRM, but `stop-replication` was missing from the list.

**Root Cause**: The `needsConfirmText` check at `HAReplication.tsx:638` was written before `stop-replication` was considered a destructive action. The action was omitted from the list `['promote', 'demote', 'resync', 'demote-and-sync']`.

**Fix Applied**: Added `'stop-replication'` to the `needsConfirmText` list: `['promote', 'demote', 'resync', 'stop-replication', 'demote-and-sync']`. Also added `'stop-replication'` to the `isStandbyInit` condition check so it requires CONFIRM on both primary and standby.

**Files Changed**:
- `frontend/src/pages/admin/HAReplication.tsx`

**Similar Bugs Found & Fixed**: N/A — all other destructive actions already had CONFIRM gates.

**Related Issues**: N/A

**Spec**: `.kiro/specs/ha-gui-config-cleanup/`

---

### ISSUE-141: `_auto_promote_attempted` never cleared on peer recovery; auto-promote permanently disabled after one attempt

- **Date**: 2026-04-27
- **Severity**: minor
- **Status**: fixed
- **Reporter**: agent (HA GUI config cleanup audit round 3)
- **Regression of**: N/A

**Symptoms**: After a failed auto-promote attempt, `_auto_promote_attempted` remained `True` permanently. Even if the peer recovered and later went down again, auto-promote would never trigger — it was permanently disabled until the container was restarted.

**Root Cause**: In `heartbeat.py`'s `_ping_loop`, the peer recovery branch (where `previous_health == "unreachable" and self.peer_health != "unreachable"`) reset `_peer_unreachable_since = None` but did not reset `_auto_promote_attempted`. The single-attempt flag should reset when the peer recovers so auto-promote can trigger again on a future outage. Note: `_auto_promote_failed_permanently` (the two-failure permanent flag) is intentionally NOT reset.

**Fix Applied**: Added `self._auto_promote_attempted = False` in the peer recovery branch of `_ping_loop`, after the existing `self._peer_unreachable_since = None` reset. The `_auto_promote_failed_permanently` flag is intentionally left unchanged.

**Files Changed**:
- `app/modules/ha/heartbeat.py`

**Similar Bugs Found & Fixed**: N/A

**Related Issues**: N/A

**Spec**: `.kiro/specs/ha-gui-config-cleanup/`

---

### ISSUE-142: Dead code `_get_heartbeat_secret()` still present in `service.py`

- **Date**: 2026-04-27
- **Severity**: minor
- **Status**: fixed
- **Reporter**: agent (HA GUI config cleanup audit round 3)
- **Regression of**: N/A

**Symptoms**: The function `_get_heartbeat_secret()` at `service.py:46-59` still existed in the codebase but was never called anywhere. It was the old env-only path that read `HA_HEARTBEAT_SECRET` from the environment, replaced by `_get_heartbeat_secret_from_config()` during the BUG-HA-04 fix. Its presence caused confusion about which function was authoritative for heartbeat secret retrieval.

**Root Cause**: When `_get_heartbeat_secret_from_config()` was introduced as the DB-preferred replacement, the old `_get_heartbeat_secret()` function was left in place as dead code and never cleaned up.

**Fix Applied**: Deleted the entire `_get_heartbeat_secret()` function (lines 46-59) from `service.py`.

**Files Changed**:
- `app/modules/ha/service.py`

**Similar Bugs Found & Fixed**: N/A

**Related Issues**: ISSUE-136 (env fallback removal in the replacement function)

**Spec**: `.kiro/specs/ha-gui-config-cleanup/`

---

### ISSUE-143: Setup guide security notes still mention `.env` files for HA configuration

- **Date**: 2026-04-27
- **Severity**: minor
- **Status**: fixed
- **Reporter**: agent (HA GUI config cleanup audit round 3)
- **Regression of**: N/A

**Symptoms**: The Setup Guide security notes in `HAReplication.tsx` said "protect your `.env` files too", which contradicted the GUI-only configuration model and misled users into thinking env files were required for HA configuration.

**Root Cause**: The setup guide text was written before the GUI-only migration and was never updated to reflect that all HA secrets and credentials are now stored encrypted in the database.

**Fix Applied**: Changed the security note text from `"protect your .env files too"` to `"The heartbeat secret and peer DB credentials are stored encrypted in the database — no .env file entries are required for HA configuration"`.

**Files Changed**:
- `frontend/src/pages/admin/HAReplication.tsx`

**Similar Bugs Found & Fixed**: N/A

**Related Issues**: ISSUE-135, ISSUE-136 (env value cleanup that makes this text change accurate)

**Spec**: `.kiro/specs/ha-gui-config-cleanup/`

---

### ISSUE-144: `get_todays_bookings` references non-existent `bookings.customer_id` column — crashes dashboard widget endpoint

- **Date**: 2026-04-28
- **Severity**: high
- **Status**: fixed
- **Fixed**: 2026-04-28
- **Reporter**: user (prod error ID `a44a5e42-6446-4d13-80c1-d2ee504e07ca`, recurring since at least 2026-04-26)
- **Regression of**: N/A

**Symptoms**:
- `GET /api/v1/dashboard/widgets` logs `asyncpg.exceptions.UndefinedColumnError: column b.customer_id does not exist` on every request.
- The entire PostgreSQL transaction enters **aborted state** — all subsequent widget SAVEPOINT operations fail with `InFailedSQLTransactionError: current transaction is aborted, commands ignored until end of transaction block`.
- All dashboard widgets silently return `{"items": [], "total": 0}` (empty) for every org.
- HTTP status is still 200, so the client sees no error — the dashboard just shows no data.
- The error cascade also triggers ISSUE-145 (see below), producing noisy `error_log` entries and uvicorn `Exception in ASGI application` lines.

**Root Cause**:
`get_todays_bookings` in `app/modules/organisations/dashboard_service.py` (lines 231–263) runs:

```sql
SELECT b.id AS booking_id, b.start_time AS scheduled_time,
       COALESCE(c.display_name, c.first_name || ' ' || c.last_name) AS customer_name,
       b.vehicle_rego
FROM bookings b
LEFT JOIN customers c ON b.customer_id = c.id   -- column does not exist
WHERE b.org_id = :org_id AND b.start_time::date = :today
```

The `bookings` table stores customer info as plain text columns (`customer_name`, `customer_email`, `customer_phone`) — it has **no `customer_id` foreign key**. The JOIN is therefore invalid.

When asyncpg raises `UndefinedColumnError`, PostgreSQL marks the entire outer transaction (not just the SAVEPOINT) as **aborted**. The `_safe_call` wrapper in `get_all_widget_data` attempts `await savepoint.rollback()`, which itself raises `InFailedSQLTransactionError` because no SQL can execute in an aborted transaction. The outer `except Exception` in `_safe_call` catches this second error and returns `_empty_section()` — but the DB session is now permanently poisoned for the lifetime of this request. Every subsequent `_safe_call` also fails immediately when it tries `db.begin_nested()`.

**Confirmed on prod** — `bookings` table column list (from `information_schema.columns`):
```
id, org_id, customer_name, customer_email, customer_phone,
staff_id, service_type, start_time, end_time, status, notes,
confirmation_token, converted_job_id, converted_invoice_id,
created_at, updated_at, service_catalogue_id, service_price,
send_email_confirmation, send_sms_confirmation,
reminder_offset_hours, reminder_scheduled_at,
reminder_cancelled, vehicle_rego, booking_data_json, branch_id
```
No `customer_id` column. First seen in `error_log` at `2026-04-26 03:55:20 UTC`, recurring on every request to this endpoint.

**Fix Required**:
In `get_todays_bookings`, remove the `LEFT JOIN customers` and use `b.customer_name` directly (already a text column on `bookings`). Apply to both the non-branch and branch-scoped query variants:

```sql
SELECT b.id AS booking_id, b.start_time AS scheduled_time,
       COALESCE(b.customer_name, 'Walk-in') AS customer_name,
       b.vehicle_rego
FROM bookings b
WHERE b.org_id = :org_id AND b.start_time::date = :today
ORDER BY b.start_time ASC
```

If the intent was to link bookings back to a Customer record, that requires a `customer_id` FK column and a migration — but the existing text field is sufficient and correct for the widget display.

**Files to Change**:
- `app/modules/organisations/dashboard_service.py` — `get_todays_bookings` function, lines ~231–263 (both query variants)

**Similar Bugs Found**:
- `get_recent_claims` (same file, lines ~370–402) joins `customer_claims LEFT JOIN customers c ON cc.customer_id = c.id` — verify that `customer_claims.customer_id` exists on prod before this triggers the same crash.

**Related Issues**: ISSUE-145 (secondary ASGI double-response crash triggered by this error cascade)

**Spec**: N/A (direct fix — change SQL to use existing text column)

---

### ISSUE-145: Rate limiter `except Exception` handler re-runs the inner app after a response has already completed — causes ASGI double-response crash

- **Date**: 2026-04-28
- **Severity**: high
- **Status**: fixed
- **Fixed**: 2026-04-28
- **Reporter**: user (prod error IDs `a44a5e42-6446-4d13-80c1-d2ee504e07ca`, `b31c2e5c-0f64-4ab9-a24f-042046e9c392`, `a217f7be-f390-40ef-ad1d-f76665ecd04e`, `e68298fe-082d-444b-b108-d083cbcaaef5`, `29a86d7c-af3f-43bd-bac9-7f98a612f492`, `8ac11be3-0c13-4668-b7dc-079d473d5b7a`, `b4b31db0-3955-4000-bec4-75c2a26f3f1c` and earlier — recurring for multiple orgs)
- **Regression of**: N/A

**Symptoms**:
- `error_log` entries: `module=builtins`, `function_name=RuntimeError`, `message=Unexpected ASGI message 'http.response.start' sent, after response already completed.`
- Uvicorn logs: `[ERROR] Exception in ASGI application` with the same RuntimeError.
- App logs immediately before: `Rate limiter unexpected error — allowing request through: /api/v1/dashboard/widgets (error: RuntimeError: Caught handled exception, but response already started.)`
- Triggered on every failed `GET /api/v1/dashboard/widgets` request (i.e., every time ISSUE-144 fires).
- At least 7 occurrences in `error_log` across two orgs as of 2026-04-28.

**Root Cause**:
This is a secondary crash triggered by ISSUE-144, but it is a latent bug in the rate limiter that can be triggered by **any** exception that propagates back through `_apply_rate_limits` after the inner app has already sent a response.

**Full crash chain (for each occurrence):**

1. ISSUE-144 causes `UndefinedColumnError` → PostgreSQL transaction aborted → SQLAlchemy cascades failures through all widgets.
2. An exception propagates upward from the route handler **after** `http.response.start` has been sent (the 200 response headers are already transmitted to the client).
3. Starlette's `_exception_handler.py:56` detects `response_started=True` and raises:
   `RuntimeError: Caught handled exception, but response already started.`
4. This propagates out of `await self.app(scope, receive, send)` at `rate_limit.py:308` (the call inside `_apply_rate_limits`), back to `__call__`.
5. `__call__`'s `except Exception as exc:` block at `rate_limit.py:189` catches it.
6. The handler logs the warning, then calls **`await self.app(scope, receive, send)` again at line 200** — attempting to re-run the entire inner middleware stack and route handler on a connection whose response is already complete.
7. The second run attempts to send `http.response.start` to Uvicorn's `ASGIHTTPCycle`, which checks its `response_complete` flag and raises:
   `RuntimeError: Unexpected ASGI message 'http.response.start' sent, after response already completed.`
8. This second RuntimeError propagates through ExceptionMiddleware, is caught by `general_exception_handler` in `main.py`, logged to `error_log`, and re-raised.
9. Uvicorn's `run_asgi` catches the final unhandled exception and logs `Exception in ASGI application`.

**The bug in isolation** (independent of ISSUE-144):

```python
# rate_limit.py lines 189–200 — CURRENT BUGGY CODE
except Exception as exc:
    logger.exception("Rate limiter unexpected error — allowing request through: %s ...", ...)
    await self.app(scope, receive, send)   # ← calls the inner app a SECOND time
```

`_apply_rate_limits` calls `await self.app(scope, receive, send)` at line 308 as its final step (after all rate checks pass). Any exception that propagates *from* that call — including exceptions from the downstream app — is caught by line 189's `except Exception`. The fallback then calls `self.app()` a second time, which is never correct when the first call already dispatched a response. The "fail open" intent of this block applies to bugs in the **rate-check logic** (before `self.app()` is ever called), not to exceptions from the **inner app** (which propagate back after `self.app()` ran).

**Fix Required**:
Change the `except Exception` fallback to `raise` instead of calling `self.app()` again:

```python
# rate_limit.py lines 189–200 — PROPOSED FIX
except Exception as exc:
    path = request.url.path
    logger.exception(
        "Rate limiter unexpected error — failing open: %s (error: %s: %s)",
        path,
        type(exc).__name__,
        exc,
    )
    raise  # re-raise; never retry self.app() after a response may have started
```

Re-raising is safe: if the inner app completed successfully, there is no exception in flight and this block is never reached. If a real rate-limiter bug fires before `self.app()` (e.g., a logic error in `_check_rate_limit`), the exception propagates to ServerErrorMiddleware which handles it correctly with a 500 response.

**Files to Change**:
- `app/middleware/rate_limit.py` — `__call__` method, lines 189–200

**Similar Bugs Found**:
All other custom ASGI middleware audited for the same pattern (calling `self.app()` inside an `except` block after already calling it in the try): `idempotency.py`, `modules.py`, `security_headers.py`, `ha/middleware.py`, `tenant.py` — none repeat the pattern. Bug is isolated to `rate_limit.py`.

**Related Issues**: ISSUE-144 (primary trigger; fixing ISSUE-144 prevents the cascade that currently exposes this bug, but ISSUE-145 remains a latent risk for any future downstream exception)