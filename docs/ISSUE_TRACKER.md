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
