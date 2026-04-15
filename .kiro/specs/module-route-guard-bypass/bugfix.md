# Bugfix Requirements Document

## Introduction

Disabling a module in OraInvoice's Module Settings only hides the sidebar navigation link — it does not prevent access to the module's pages via direct URL navigation. For example, if the "vehicles" module is disabled (either by org admin or because it's not in the subscription plan), navigating to `/vehicles` in the browser still loads the full page content. This is a security and access-control gap: disabled modules must be inaccessible at the route level, not just hidden from the sidebar.

The root cause is that `App.tsx` defines all module routes directly under `OrgLayout` without any module enablement checks. A `ModuleRouter` component exists with proper module-gating logic (renders "Feature not available" for disabled modules), but it is not used — `AppRoutes` renders all routes unconditionally. The `useModuleGuard` hook also exists but is only called by ~5 pages.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a module is disabled by the org admin in Module Settings AND a user navigates directly to a route belonging to that module (e.g. `/vehicles`, `/pos`, `/kitchen`, `/jobs`, `/quotes`, `/inventory`, `/schedule`, `/franchise`, `/loyalty`, `/compliance`, `/assets`, `/ecommerce`, `/time-tracking`, `/expenses`, `/projects`, `/staff`, `/bookings`, `/recurring`, `/purchase-orders`, `/progress-claims`, `/variations`, `/retentions`, `/floor-plan`, `/stock-transfers`, `/locations`, `/catalogue`, `/sms`, `/job-cards`) THEN the system renders the full page content as if the module were enabled

1.2 WHEN a module is not included in the org's subscription plan AND a user navigates directly to a route belonging to that module THEN the system renders the full page content as if the module were available

1.3 WHEN a module is disabled AND the `AppRoutes` component in `App.tsx` renders routes THEN the system does not check `ModuleContext.isEnabled()` before rendering the module's page component, because all module routes are defined as unconditional `<Route>` elements under `OrgLayout`

1.4 WHEN a module is disabled AND the existing `ModuleRouter` component correctly gates routes by module enablement THEN the system does not use `ModuleRouter` for the org-level routes in `AppRoutes`, rendering its gating logic ineffective

### Expected Behavior (Correct)

2.1 WHEN a module is disabled by the org admin in Module Settings AND a user navigates directly to any route belonging to that module THEN the system SHALL redirect the user to the dashboard or display a "Module Not Available" page, and SHALL NOT render the module's page content

2.2 WHEN a module is not included in the org's subscription plan AND a user navigates directly to any route belonging to that module THEN the system SHALL redirect the user to the dashboard or display a "Module Not Available" page, and SHALL NOT render the module's page content

2.3 WHEN a module is disabled AND a user navigates to any route belonging to that module THEN the system SHALL enforce the module check at the route level (before the page component renders), using the existing `ModuleContext.isEnabled()` mechanism consistently across ALL module-gated routes

2.4 WHEN the module enablement status is still loading (e.g. initial page load, context not yet initialized) THEN the system SHALL show a loading state and SHALL NOT briefly flash the module page content before redirecting

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a module is enabled AND a user navigates to a route belonging to that module THEN the system SHALL CONTINUE TO render the module's page content normally

3.2 WHEN a user navigates to a core route (dashboard, invoices, customers, settings, reports, notifications, data) THEN the system SHALL CONTINUE TO render the page regardless of module enablement settings, since these are not module-gated

3.3 WHEN a module is disabled THEN the sidebar navigation SHALL CONTINUE TO hide the link for that module (existing OrgLayout filtering behavior must be preserved)

3.4 WHEN a user is a global admin viewing an org THEN the system SHALL CONTINUE TO respect the org's module enablement settings for route access

3.5 WHEN the `ModuleGate` component is used within a page to conditionally render sub-sections THEN the system SHALL CONTINUE TO function as before (route-level guards do not replace in-page gating)

---

## Bug Condition (Formal)

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type RouteNavigation { route: string, moduleSlug: string, isModuleEnabled: boolean }
  OUTPUT: boolean

  // The bug triggers when a user navigates to a module-gated route
  // while that module is disabled (by admin or subscription)
  RETURN X.moduleSlug IS NOT NULL
     AND X.isModuleEnabled = false
     AND X.route MATCHES a path belonging to X.moduleSlug
END FUNCTION
```

```pascal
// Property: Fix Checking — Disabled module routes are blocked
FOR ALL X WHERE isBugCondition(X) DO
  result ← navigateTo'(X.route)
  ASSERT result.renderedPage ≠ modulePageContent(X.moduleSlug)
     AND (result.redirectedTo = "/dashboard" OR result.renderedPage = "Module Not Available")
END FOR
```

```pascal
// Property: Preservation Checking — Enabled module routes still work
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT navigateTo(X.route) = navigateTo'(X.route)
END FOR
```
