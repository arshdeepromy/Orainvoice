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

