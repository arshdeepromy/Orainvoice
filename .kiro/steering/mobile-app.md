---
inclusion: always
---

# Mobile App — Steering Guide

## Purpose and Scope

The OraInvoice Mobile App is a **companion app for organisation users only** — field staff, tradespeople, business owners, and org-level managers. It is NOT an admin panel. The following are explicitly out of scope for mobile:

**Never include in mobile:**
- Global admin screens (platform management, billing admin, HA replication, global user management)
- Org admin–only destructive operations (data export/import, advanced integrations management, org deletion)
- Full settings panels with deep configuration — mobile settings are a read-only profile view plus notification and biometric toggles

**In scope for mobile:**
- Invoicing, quoting, customer management
- Job cards, job board, time tracking, expenses, bookings
- Inventory lookup (read-only stock checks in the field)
- Compliance document upload (camera-based)
- Accounting/Banking/Tax — **view-only** for business owners monitoring financials remotely (module-gated)
- Reports — **read-only** summary views
- Notifications, push alerts
- POS (hospitality/retail, module-gated)

## Tech Stack

- **Framework:** React 19 + TypeScript + Vite + Tailwind CSS
- **Native bridge:** Capacitor 7 (camera, biometrics, push notifications, network, preferences, share)
- **State:** React Context (AuthContext, ModuleContext, BranchContext, ThemeContext, OfflineContext, BiometricContext)
- **API client:** Axios at `baseURL: '/api/v1'`; v2 endpoints use absolute paths `/api/v2/...`
- **Routing:** React Router DOM v7 (score-based matching — static paths beat dynamic)
- **Testing:** Vitest + React Testing Library + fast-check property tests

## API Conventions

### Always prefer v2 endpoints where they exist

The backend re-registers many v1 routers under `/api/v2/` for future compatibility. New code in the mobile app should use v2 endpoints where available. Key v2-only endpoints:

| Feature | Endpoint |
|---------|----------|
| Time entries | `/api/v2/time-entries` |
| Expenses | `/api/v2/expenses` |
| Staff | `/api/v2/staff` |
| Schedule | `/api/v2/schedule` |
| Purchase orders | `/api/v2/purchase-orders` |
| Recurring invoices | `/api/v2/recurring` |
| Compliance docs | `/api/v2/compliance-docs` |
| Franchise | `/api/v2/franchise` |
| Modules | `/api/v2/modules` |

### Pagination parameters

The backend uses `offset` (not `skip`) and `limit`:

```typescript
// CORRECT — matches backend FastAPI Query params
params = { offset: (page - 1) * pageSize, limit: pageSize }

// WRONG — 'skip' is silently ignored by the backend
params = { skip: (page - 1) * pageSize, limit: pageSize }
```

### Safe API consumption (mandatory)

All API responses must be consumed safely. No exceptions:

```typescript
const items = res.data?.items ?? []
const total = res.data?.total ?? 0
```

Use typed generics on all API calls — never `as any`.

Use AbortController in every `useEffect` with an API call:

```typescript
useEffect(() => {
  const controller = new AbortController()
  fetchData(controller.signal)
  return () => controller.abort()
}, [])
```

## Navigation Architecture

- Five bottom tabs: Dashboard, Invoices, Customers, Jobs, More
- All tabs except Jobs are always visible (no module gate on tabs)
- Jobs tab is gated by `jobs` module
- More menu is a 3-column grid of module-gated feature buttons
- Module gate wildcard: `moduleSlug: '*'` means always visible (no module check)

### Role-based visibility

- `owner` and `admin` roles can access Settings in the More menu
- `kiosk` role shows the Kiosk screen instead of standard tabs
- `global_admin` should never see org-level settings in mobile

## Touch Targets and Mobile Design

- Minimum 44×44 CSS pixels for all interactive elements (Apple HIG + WCAG 2.5.8)
- Use `min-h-[44px]` on buttons, list items, toggle rows
- Safe area insets must be respected (`pb-safe`, `env(safe-area-inset-*)`)
- Font sizes: minimum 12px for secondary text, 14px+ for primary text
- Dark mode: all components must use `dark:` Tailwind variants
- Viewport range: 320px (iPhone SE) to 430px (iPhone Pro Max)

## Component Conventions

### Screen structure

Every screen follows this pattern:

```tsx
export default function SomeListScreen() {
  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col">
        {/* Header with title + action button */}
        <div className="flex items-center justify-between px-4 pt-4 pb-1">
          <h1 className="text-xl font-semibold">Title</h1>
          <MobileButton variant="primary" size="sm">New</MobileButton>
        </div>
        {/* List */}
        <MobileList ... />
      </div>
    </PullRefresh>
  )
}
```

### Module-gated screens

Wrap the screen content (not the route) in `ModuleGate`:

```tsx
export default function AccountingScreen() {
  return (
    <ModuleGate moduleSlug="accounting">
      {/* content */}
    </ModuleGate>
  )
}
```

### Loading and error states

Use `MobileSpinner` for initial loads. Show error banner with retry for fetch failures. Never leave a blank screen on error.

## Capacitor Native Features

All Capacitor plugin calls must be wrapped in try/catch and guarded by platform detection:

```typescript
const isNative = !!(window as any).Capacitor?.isNativePlatform?.()
if (isNative) {
  // safe to call Capacitor plugins
}
```

Camera, push notifications, and biometrics use platform-specific flows and must not be called in web browser context without guards.

## Adding New Screens

1. Create the screen file in `mobile/src/screens/<feature>/`
2. Add lazy import in `StackRoutes.tsx`
3. Add route in the `<Routes>` block
4. Add menu item in `MoreMenuScreen.tsx` (if accessing from More tab) with correct `moduleSlug`, `tradeFamily`, and `roles`
5. Write a unit test covering the happy path and empty state
6. Verify the API endpoint exists in the backend (`app/main.py`) and the response shape matches `@shared/types/`

## Common Mistakes to Avoid

| Mistake | Correct approach |
|---------|-----------------|
| Using `skip` as pagination param | Use `offset` |
| Calling Capacitor plugins outside native check | Guard with `isNativePlatform()` |
| Hardcoding currency as `$` | Use `Intl.NumberFormat` with org locale |
| Admin-only operations in mobile | Gate with `roles` on ModuleGate |
| `as any` on API responses | Use typed generics + optional chaining |
| Forgetting AbortController cleanup | Always return `() => controller.abort()` from useEffect |
| Adding global_admin to mobile role gates | Mobile is for org users only |
