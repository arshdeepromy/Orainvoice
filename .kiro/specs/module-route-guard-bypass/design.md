# Module Route Guard Bypass — Bugfix Design

## Overview

Disabling a module in OraInvoice only hides the sidebar link — it does not block direct URL access to the module's pages. The root cause is that `App.tsx` defines all module routes as unconditional `<Route>` elements under `OrgLayout`, bypassing the existing `ModuleContext.isEnabled()` mechanism. A `ModuleRouter` component with proper gating exists but is unused for org-level routes.

The fix introduces a `ModuleRoute` wrapper component that checks module enablement at the route level. All module-gated routes in `App.tsx` will be wrapped with `ModuleRoute`, which renders `FeatureNotAvailable` for disabled modules and shows a loading spinner while module state is initializing. Core routes (dashboard, invoices, customers, settings, reports, notifications, data) remain unguarded.

## Glossary

- **Bug_Condition (C)**: A user navigates directly to a route belonging to a disabled module (disabled by admin or not in subscription plan)
- **Property (P)**: Disabled module routes render `FeatureNotAvailable` page instead of module content; enabled module routes render normally
- **Preservation**: All existing behavior for enabled modules, core routes, sidebar filtering, in-page `ModuleGate` usage, and global admin "view as org" mode must remain unchanged
- **`ModuleContext`**: React context in `frontend/src/contexts/ModuleContext.tsx` that fetches module enablement from `/api/v2/modules` and exposes `isEnabled(slug)`, `isLoading`, and `enabledModules`
- **`ModuleRoute`**: New wrapper component (to be created) that checks `isEnabled(moduleSlug)` before rendering children, showing `FeatureNotAvailable` when disabled and a loading spinner while initializing
- **`ModuleRouter`**: Existing component in `frontend/src/router/ModuleRouter.tsx` with `MODULE_ROUTES` mapping — currently unused by `AppRoutes` but contains the canonical route-to-module-slug mapping
- **`FeatureNotAvailable`**: Existing page in `frontend/src/pages/common/FeatureNotAvailable.tsx` that shows a friendly "Feature not available" message with a link back to dashboard
- **`useModuleGuard`**: Existing hook in `frontend/src/hooks/useModuleGuard.ts` that redirects to dashboard with a toast when a module is disabled — used by ~5 pages but not at the route level

## Bug Details

### Bug Condition

The bug manifests when a user navigates directly (via URL bar, bookmark, or shared link) to any route belonging to a module that is disabled for their organisation. The `AppRoutes` component in `App.tsx` renders all module routes as unconditional `<Route>` elements — there is no `isEnabled()` check before the page component mounts.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type RouteNavigation { route: string, moduleSlug: string | null, isModuleEnabled: boolean }
  OUTPUT: boolean

  RETURN input.moduleSlug IS NOT NULL
     AND input.isModuleEnabled = false
     AND input.route MATCHES a path belonging to input.moduleSlug
END FUNCTION
```

### Examples

- User navigates to `/vehicles` when the `vehicles` module is disabled → **Current**: full VehicleList page renders. **Expected**: FeatureNotAvailable page renders.
- User navigates to `/pos` when the `pos` module is not in the subscription plan → **Current**: full POSScreen renders. **Expected**: FeatureNotAvailable page renders.
- User navigates to `/franchise` when the `franchise` module is disabled → **Current**: full FranchiseDashboard renders. **Expected**: FeatureNotAvailable page renders.
- User navigates to `/kitchen` when `kitchen_display` module is disabled → **Current**: full KitchenDisplay renders. **Expected**: FeatureNotAvailable page renders.
- User navigates to `/dashboard` (core route, no module gate) → **Current & Expected**: Dashboard renders normally regardless of module settings.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- All enabled module routes must continue to render their page content normally
- Core routes (dashboard, invoices, customers, settings, reports, notifications, data) must render regardless of module enablement settings
- Sidebar navigation must continue to hide links for disabled modules (existing `OrgLayout` filtering)
- Global admin "view as org" mode must continue to respect the org's module enablement settings
- In-page `ModuleGate` components must continue to conditionally render sub-sections as before
- The `useModuleGuard` hook must continue to function for pages that use it (route-level guard is additive, not a replacement)
- The existing `RequireAutomotive` wrapper for vehicles must continue to work alongside the new module guard

**Scope:**
All inputs that do NOT involve navigating to a disabled module's route should be completely unaffected by this fix. This includes:
- Navigation to any core route
- Navigation to any enabled module route
- Mouse clicks on sidebar links (already filtered)
- All non-navigation interactions (form submissions, API calls, etc.)

## Hypothesized Root Cause

Based on the code analysis, the root cause is clear and confirmed:

1. **Unconditional Route Rendering in `AppRoutes`**: `App.tsx` defines every module route as a direct `<Route>` element under `OrgLayout` without any module enablement check. The `<Route path="/vehicles" element={<SafePage><VehicleList /></SafePage>} />` pattern is used for all ~40 module routes — none consult `ModuleContext.isEnabled()`.

2. **`ModuleRouter` Not Integrated**: A fully functional `ModuleRouter` component exists in `frontend/src/router/ModuleRouter.tsx` with a complete `MODULE_ROUTES` mapping (module slug → route configs) and proper gating logic (renders `FeatureNotAvailable` for disabled modules). However, `AppRoutes` does not use `ModuleRouter` — it renders all routes directly.

3. **`useModuleGuard` Inconsistently Applied**: The `useModuleGuard` hook exists and works correctly (redirects to dashboard with toast), but only ~5 pages call it. The remaining ~35 module pages have no guard at all.

4. **Sidebar-Only Filtering Creates False Security**: `OrgLayout` correctly filters `navItems` by `isEnabled(item.module)`, hiding sidebar links for disabled modules. This creates the appearance of access control, but direct URL navigation bypasses the sidebar entirely.

## Correctness Properties

Property 1: Bug Condition — Disabled Module Routes Are Blocked

_For any_ route navigation where the target route belongs to a module (moduleSlug is not null) AND that module is disabled (isEnabled(moduleSlug) returns false), the `ModuleRoute` wrapper SHALL render the `FeatureNotAvailable` page and SHALL NOT render the module's page component.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation — Enabled Module Routes Render Normally

_For any_ route navigation where the target route belongs to a module AND that module is enabled (isEnabled(moduleSlug) returns true), the `ModuleRoute` wrapper SHALL render the module's page component exactly as before, preserving all existing functionality.

**Validates: Requirements 3.1**

Property 3: Preservation — Core Routes Are Unaffected

_For any_ route navigation to a core route (dashboard, invoices, customers, settings, reports, notifications, data), the route SHALL render its page component regardless of any module enablement settings, with no `ModuleRoute` wrapper applied.

**Validates: Requirements 3.2**

## Fix Implementation

### Changes Required

**File**: `frontend/src/components/common/ModuleRoute.tsx` (NEW)

**Component**: `ModuleRoute`

**Specific Changes**:
1. **Create `ModuleRoute` wrapper component**: A new component that accepts a `moduleSlug` prop, reads `isEnabled` and `isLoading` from `useModules()`, and conditionally renders children or `FeatureNotAvailable`.
   - When `isLoading` is true (modules not yet fetched): render a loading spinner (reuse `Spinner` component) to prevent content flash
   - When `isLoading` is false AND `isEnabled(moduleSlug)` is true: render `children` (the module page)
   - When `isLoading` is false AND `isEnabled(moduleSlug)` is false: render `FeatureNotAvailable`
   - Must handle the edge case where `ModuleContext` returns `isEnabled: () => true` when used outside `ModuleProvider` (the safe default in `useModules`)

2. **Handle initialization timing**: The `ModuleContext` sets `isLoading: false` and `modules: []` initially for global admins (who skip the fetch). For global admins not in "view as org" mode, `isEnabled()` returns `true` by default (empty `enabledModules` means the fallback in `useModules` returns `() => true`). The `ModuleRoute` component must account for this — when modules array is empty and not loading, it should allow rendering (same as current behavior where global admins see everything).

**File**: `frontend/src/App.tsx` (MODIFY)

**Function**: `AppRoutes`

**Specific Changes**:
3. **Import `ModuleRoute`**: Add import for the new component.

4. **Wrap module-gated routes with `ModuleRoute`**: For each route that belongs to a module, wrap the `element` prop's content with `<ModuleRoute moduleSlug="...">`. The module slug mapping comes from `OrgLayout`'s `navItems` (which already has `module` properties) and `ModuleRouter`'s `MODULE_ROUTES`. The complete mapping:
   - `vehicles` → `/vehicles`, `/vehicles/:id`
   - `quotes` → `/quotes`, `/quotes/new`, `/quotes/:id/edit`, `/quotes/:id`
   - `jobs` → `/job-cards`, `/job-cards/new`, `/job-cards/:id`, `/jobs`, `/jobs/board`, `/jobs/:id`
   - `bookings` → `/bookings`
   - `inventory` → `/inventory`
   - `staff` → `/staff`, `/staff/:id`
   - `projects` → `/projects`, `/projects/:id`
   - `expenses` → `/expenses`
   - `time_tracking` → `/time-tracking`
   - `pos` → `/pos`
   - `scheduling` → `/schedule`
   - `recurring_invoices` → `/recurring`
   - `purchase_orders` → `/purchase-orders`, `/purchase-orders/:id`
   - `progress_claims` → `/progress-claims`
   - `variations` → `/variations`
   - `retentions` → `/retentions`
   - `tables` → `/floor-plan`
   - `kitchen_display` → `/kitchen`
   - `franchise` → `/franchise`, `/locations`, `/locations/:id`, `/stock-transfers`
   - `assets` → `/assets`, `/assets/:id`
   - `compliance_docs` → `/compliance`
   - `loyalty` → `/loyalty`
   - `ecommerce` → `/ecommerce`
   - `catalogue` → `/catalogue`
   - `customer_claims` → `/claims`, `/claims/new`, `/claims/reports`, `/claims/:id`
   - `accounting` → `/accounting`, `/accounting/journal-entries`, `/accounting/journal-entries/:id`, `/accounting/periods`, `/reports/profit-loss`, `/reports/balance-sheet`, `/reports/aged-receivables`, `/tax/gst-periods`, `/tax/gst-periods/:id`, `/tax/wallets`, `/tax/position`, `/banking/accounts`, `/banking/transactions`, `/banking/reconciliation`
   - `branch_management` → `/branch-transfers`, `/staff-schedule`

5. **Do NOT wrap core routes**: The following routes must remain unwrapped: `/dashboard`, `/customers/*`, `/invoices/*`, `/reports` (the main reports page), `/settings`, `/notifications`, `/data`, `/items`, `/setup`, `/onboarding`, and the catch-all.

6. **Preserve `RequireAutomotive` wrapper**: The `/vehicles` routes already have a `RequireAutomotive` wrapper. The `ModuleRoute` wrapper should be applied inside `RequireAutomotive` (or alongside it), so both trade-family gating and module gating apply.

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm that navigating to disabled module routes renders the full page content.

**Test Plan**: Write React Testing Library tests that render `AppRoutes` with a mocked `ModuleContext` where specific modules are disabled, then navigate to those module routes and assert the page content renders (demonstrating the bug). Run these tests on the UNFIXED code to observe failures.

**Test Cases**:
1. **Disabled Vehicles Route**: Navigate to `/vehicles` with `vehicles` module disabled — assert VehicleList content renders (will pass on unfixed code, demonstrating the bug)
2. **Disabled POS Route**: Navigate to `/pos` with `pos` module disabled — assert POSScreen content renders (will pass on unfixed code)
3. **Disabled Franchise Route**: Navigate to `/franchise` with `franchise` module disabled — assert FranchiseDashboard content renders (will pass on unfixed code)
4. **Disabled Kitchen Route**: Navigate to `/kitchen` with `kitchen_display` module disabled — assert KitchenDisplay content renders (will pass on unfixed code)

**Expected Counterexamples**:
- All module page components render their full content even when the module is disabled
- No redirect or "Feature not available" message appears
- Root cause confirmed: `AppRoutes` has no `isEnabled()` checks on any route

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed `ModuleRoute` wrapper blocks access and shows `FeatureNotAvailable`.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := renderRoute_fixed(input.route, { moduleSlug: input.moduleSlug, isEnabled: false })
  ASSERT result.contains("Feature not available")
  ASSERT NOT result.contains(modulePageContent(input.moduleSlug))
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed code produces the same result as the original code.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT renderRoute_original(input.route) = renderRoute_fixed(input.route)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many combinations of module enablement states and route paths automatically
- It catches edge cases like partially-enabled module sets that manual tests might miss
- It provides strong guarantees that enabled module routes and core routes are unchanged

**Test Plan**: Observe behavior on UNFIXED code first for enabled module routes and core routes, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Enabled Module Preservation**: For each module slug, enable the module and navigate to its routes — verify the page component renders normally
2. **Core Route Preservation**: Navigate to each core route with various module enablement states — verify the page always renders
3. **Sidebar Filtering Preservation**: Render `OrgLayout` with disabled modules — verify sidebar links are still hidden
4. **Loading State**: Render `ModuleRoute` with `isLoading: true` — verify a loading spinner is shown, not the page content or FeatureNotAvailable

### Unit Tests

- Test `ModuleRoute` component renders children when module is enabled
- Test `ModuleRoute` component renders `FeatureNotAvailable` when module is disabled
- Test `ModuleRoute` component renders loading spinner when `isLoading` is true
- Test `ModuleRoute` component handles edge case where modules array is empty (global admin default)
- Test that core routes in `AppRoutes` do not have `ModuleRoute` wrappers

### Property-Based Tests

- Generate random subsets of enabled/disabled modules and verify all disabled module routes show `FeatureNotAvailable` while all enabled module routes render normally
- Generate random module enablement states and verify core routes always render regardless
- Generate random navigation sequences mixing core and module routes with varying enablement states

### Integration Tests

- Test full navigation flow: user logs in → navigates to disabled module route → sees FeatureNotAvailable → clicks "Back to Dashboard" → arrives at dashboard
- Test that enabling a module (via settings) then navigating to its route renders the page
- Test global admin "view as org" mode with disabled modules
- Test that `RequireAutomotive` + `ModuleRoute` compose correctly for vehicle routes
