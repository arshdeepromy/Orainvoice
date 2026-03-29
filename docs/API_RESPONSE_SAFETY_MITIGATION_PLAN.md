# API Response Safety — Mitigation Plan

**Date**: 2026-03-29
**Related**: `docs/API_RESPONSE_SAFETY_AUDIT.md`
**Scope**: Fix ~60 files with unsafe API response access, add automated regression tests, prevent future occurrences

---

## 1. Constraints

- No performance degradation — fixes must be zero-cost at runtime (no extra API calls, no middleware, no wrappers that add latency)
- No security regressions — fixes must not expose internal error details, leak stack traces, or weaken input validation
- No backend changes — all fixes are frontend-only (the backend response contracts are correct; the frontend is not handling them defensively)
- Automated testing — every fix must be covered by a test that fails before the fix and passes after

---

## 2. Mitigation Strategy

The fix for every file is the same mechanical pattern — add null guards. There are exactly 3 transforms:

**Transform A** — Array access on response property:
```typescript
// Before (crashes if property is undefined)
setItems(res.data.items)

// After (falls back to empty array)
setItems(res.data?.items ?? [])
```

**Transform B** — Array method on response property:
```typescript
// Before
res.data.rules.map(fn)

// After
(res.data?.rules ?? []).map(fn)
```

**Transform C** — Number formatting on potentially undefined value:
```typescript
// Before
value.toLocaleString()

// After
(value ?? 0).toLocaleString()
```

**Transform D** — Type assertion with proper null guards:
```typescript
// Before (bypasses type safety)
const data = res.data as any
setRecords(data.usage || [])

// After (type-safe and null-safe)  
setRecords(res.data?.usage ?? [])
```

These transforms are:
- Zero runtime cost (optional chaining and nullish coalescing are native JS operators, not function calls)
- No security impact (they only add fallback values for missing data, never expose internals)
- No behaviour change when data is present (the `??` operator only activates on null/undefined)

---

## 3. Affected Workflows and Features

Grouped by user-facing feature area so you can prioritize by business impact.

### Priority 1 — Core Revenue Workflows (crash = lost revenue)
| Feature | Files | Risk | User Impact |
|---------|-------|------|-------------|
| Invoice creation | `AddToStockModal.tsx` (parts/fluids picker) | HIGH | Invoice line item picker crashes if catalogue API returns unexpected shape |
| Invoice detail | `InvoiceDetail.tsx` | MEDIUM | Odometer display crashes if vehicle_odometer is null |
| Reports (all 10 tabs) | `RevenueSummary`, `GstReturnSummary`, `OutstandingInvoices`, `InvoiceStatus`, `FleetReport`, `TopServices`, `CarjamUsage`, `StorageUsage`, `CustomerStatement`, `ReportBuilder` | MEDIUM | Any report tab crashes if backend returns empty/null data |
| Billing/subscription | `Billing.tsx` | MEDIUM | Storage addon page crashes if storage_used_gb is undefined |

### Priority 2 — Daily Operations (crash = workflow blocked)
| Feature | Files | Risk | User Impact |
|---------|-------|------|-------------|
| Inventory management | `StockLevels`, `StockAdjustment`, `StockMovements`, `ReorderAlerts`, `ProductList`, `ProductDetail`, `PricingRules`, `CategoryTree`, `SupplierList`, `StockUpdateLog`, `UsageHistory` | MEDIUM | Any inventory page crashes if stock_items/products/suppliers array is missing |
| Job management | `JobsPage`, `JobList`, `JobBoard`, `JobDetail`, `JobTimer` | MEDIUM | Job list or detail crashes if job_cards/jobs/entries is undefined |
| Notifications | `OverdueRules`, `Reminders`, `NotificationPreferences`, `NotificationLog` | HIGH/MEDIUM | Overdue rules page crashes on .map(); others crash on missing arrays |
| Vehicle profile | `VehicleProfile.tsx` | LOW | Odometer history line 274 is actually safe — `odometerHistory` is built with `.filter((s) => s.odometer != null)` so `entry.odometer` is guaranteed non-null |
| Floor plan | `FloorPlan.tsx` | HIGH | Crashes on .length access if floor_plans is undefined |

### Priority 3 — Admin & Settings (crash = admin blocked)
| Feature | Files | Risk | User Impact |
|---------|-------|------|-------------|
| Error log | `ErrorLog.tsx` | HIGH | Critical error filter crashes if errors array is undefined |
| Admin dashboard | `GlobalAdminDashboard.tsx`, `AnalyticsDashboard.tsx` | MEDIUM | KPI cards crash if MRR/org counts are undefined |
| Admin reports | `Reports.tsx`, `Settings.tsx` | MEDIUM | Vehicle DB stats crash on toLocaleString |
| MFA settings | `MfaSettings.tsx` | MEDIUM | Methods list crashes if bare array assumption fails |
| Recurring invoices | `RecurringInvoices.tsx`, `RecurringList.tsx` | MEDIUM | Schedule list crashes if schedules is undefined |

### Priority 4 — Secondary Features (crash = feature unavailable)
| Feature | Files | Risk | User Impact |
|---------|-------|------|-------------|
| Customer portal | `PortalPage`, `InvoiceHistory`, `VehicleHistory`, `LoyaltyBalance` | MEDIUM | Portal pages crash if response shape differs |
| SMS chat | `SmsChat.tsx`, `SmsUsageSummary.tsx` | MEDIUM | SMS pages crash on missing data |
| Ecommerce | `WooCommerceSetup`, `SkuMappings`, `ApiKeys` | MEDIUM | Ecommerce config crashes if arrays missing |
| Construction | `ProgressClaimForm`, `ProgressClaimList` | LOW | Values are locally computed via `calculateProgressClaimFields()` with `Number(x) \|\| 0` inputs — actually safe, no fix needed |
| POS | `TipPrompt`, `SyncStatus`, `ProductGrid`, `OrderPanel` | MEDIUM | Tip analytics and product display crash on undefined |
| Franchise | `FranchiseDashboard`, `LocationDetail`, `StockTransfers` | MEDIUM | Location data crashes if response shape differs |
| Loyalty | `LoyaltyConfig.tsx` | MEDIUM | Analytics display crashes on toLocaleString |
| Time tracking | `TimeSheet.tsx` | LOW | Project aggregation `.toFixed()` calls are on locally computed values (`(duration_minutes ?? 0) / 60`), always numbers — actually safe |
| Projects | `ProjectList.tsx` | MEDIUM | Project list crashes if projects array missing |
| Purchase orders | `PODetail.tsx`, `POList.tsx` | MEDIUM | PO detail crashes if response shape differs |
| Currency settings | `CurrencySettings.tsx` | MEDIUM | Rate history tooltip crashes on toFixed |

---

## 4. Implementation Phases

### Phase 1: HIGH-risk files (6 files, ~30 min)
Fix the files that will crash immediately on any backend hiccup:
1. `pages/notifications/OverdueRules.tsx` — `(res.data?.rules ?? []).map(...)`
2. `components/inventory/AddToStockModal.tsx` — 3 fixes: products.map, parts.filter, stock_items.map
3. `pages/admin/ErrorLog.tsx` — `(res.data?.errors ?? []).filter(...)`
4. `pages/floor-plan/FloorPlan.tsx` — null guard on floor_plans before .length and [0] access

### Phase 2: Core revenue files (15 files, ~1 hour)
Fix invoice, report, and billing pages that affect revenue workflows.

### Phase 3: Daily operations files (22 files, ~1.5 hours)
Fix inventory, jobs, notifications, and vehicle pages.

### Phase 4: Admin and secondary features (25 files, ~2 hours)
Fix remaining admin, portal, ecommerce, POS, construction, franchise, loyalty, and time tracking pages.

Total estimated effort: ~5 hours of mechanical transforms.

---

## 5. Automated Test Plan

Every fix needs a test that verifies the component doesn't crash when the API returns null/undefined for the property in question. The tests use the existing infrastructure: vitest + @testing-library/react + vi.mock for API mocking.

### Test Strategy: "Null Response Resilience Tests"

For each affected file, write one test that mocks the API to return a response with the critical property missing (null or undefined), renders the component, and asserts it doesn't throw. This is a crash-or-no-crash test — it doesn't validate UI content, just that the page renders without error.

### Test File Structure

One test file per feature area, placed alongside existing test directories:

```
frontend/src/pages/notifications/__tests__/null-response-resilience.test.tsx
frontend/src/pages/inventory/__tests__/null-response-resilience.test.tsx
frontend/src/pages/admin/__tests__/null-response-resilience.test.tsx
frontend/src/pages/reports/__tests__/null-response-resilience.test.tsx
frontend/src/pages/invoices/__tests__/null-response-resilience.test.tsx
frontend/src/pages/vehicles/__tests__/null-response-resilience.test.tsx
frontend/src/pages/jobs/__tests__/null-response-resilience.test.tsx
frontend/src/pages/settings/__tests__/null-response-resilience.test.tsx
frontend/src/pages/floor-plan/__tests__/null-response-resilience.test.tsx
frontend/src/pages/portal/__tests__/null-response-resilience.test.tsx
frontend/src/pages/sms/__tests__/null-response-resilience.test.tsx
frontend/src/pages/pos/__tests__/null-response-resilience.test.tsx
frontend/src/pages/ecommerce/__tests__/null-response-resilience.test.tsx
frontend/src/components/inventory/__tests__/null-response-resilience.test.tsx
```

### Test Pattern (template for every component)

```typescript
import { render } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import apiClient from '../../../api/client'
import ComponentUnderTest from '../ComponentUnderTest'

describe('ComponentUnderTest — null response resilience', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('does not crash when API returns empty object', () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: {} })
    expect(() => render(<ComponentUnderTest />)).not.toThrow()
  })

  it('does not crash when API returns null for array property', () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { items: null } })
    expect(() => render(<ComponentUnderTest />)).not.toThrow()
  })

  it('does not crash when API returns undefined for nested property', () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { nested: undefined } })
    expect(() => render(<ComponentUnderTest />)).not.toThrow()
  })
})
```

### Test Scenarios Per Category

**Category 1 & 2 (HIGH risk — array methods on response):**
- Mock API to return `{ data: {} }` (property missing entirely)
- Mock API to return `{ data: { property: null } }`
- Mock API to return `{ data: { property: undefined } }`
- Assert: component renders without throwing

**Category 3 (MEDIUM risk — set state from response property):**
- Mock API to return `{ data: {} }` (property missing)
- Assert: component renders, shows empty/loading state, no crash

**Category 4 (MEDIUM risk — setData(res.data) without validation):**
- Mock API to return `{ data: null }`
- Mock API to return `{ data: {} }` (missing expected nested properties)
- Assert: component renders without throwing

**Category 5 (MEDIUM risk — toLocaleString/toFixed on undefined):**
- Mock API to return data with the numeric field set to `null` or `undefined`
- Assert: component renders, shows fallback value (0, "—", etc.)

**Category 6 (MEDIUM risk — type assertions with fallback):**
- Mock API to return `{ data: {} }` (property missing)
- Mock API to return `{ data: { property: null } }`
- Assert: component renders without throwing, shows empty/loading state

### Running the Tests

```bash
# Run all null-response resilience tests
cd frontend && npx vitest run --reporter=verbose "null-response-resilience"

# Run for a specific feature area
cd frontend && npx vitest run --reporter=verbose "pages/inventory/__tests__/null-response-resilience"

# Run as part of the full test suite (already included by vitest glob)
cd frontend && npm test
```

### Test Count Estimate

| Feature Area | Components | Tests per Component | Total Tests |
|-------------|-----------|-------------------|-------------|
| Notifications | 4 | 3 | 12 |
| Inventory | 12 | 3 | 36 |
| Admin | 5 | 3 | 15 |
| Reports | 10 | 3 | 30 |
| Invoices | 3 | 3 | 9 |
| Vehicles | 2 | 3 | 6 |
| Jobs | 5 | 3 | 15 |
| Settings | 6 | 3 | 18 |
| Floor Plan | 2 | 3 | 6 |
| Portal | 4 | 3 | 12 |
| SMS | 2 | 3 | 6 |
| POS | 4 | 3 | 12 |
| Ecommerce | 3 | 3 | 9 |
| Components | 1 | 3 | 3 |
| **Total** | **63** | | **~189** |

Each test is a simple render-and-don't-crash check — the full suite should run in under 30 seconds.

---

## 6. Regression Prevention

### Automated (already in place)
- The steering doc `.kiro/steering/frontend-backend-contract-alignment.md` (inclusion: auto) reminds the agent to add null guards on every new API call
- The null-response resilience tests catch regressions if a future change removes a guard

### CI Integration
Add to the CI pipeline (or pre-commit hook):
```bash
cd frontend && npx vitest run "null-response-resilience" --reporter=verbose
```
This runs only the resilience tests (~30s) and fails the build if any component crashes on null responses.

### Static Analysis (optional future enhancement)
Consider adding an ESLint rule or TypeScript strict null checks to catch `res.data.property` without optional chaining at lint time. This would prevent the pattern from being introduced in new code. Not required for the immediate fix but worth evaluating after the manual fixes are complete.

---

## 7. Security Considerations

The fixes in this plan have zero security impact:

- No new API calls are added (no extra network traffic, no new attack surface)
- No error details are exposed to the user (fallback values are empty arrays, zeros, or "—" placeholders)
- No input validation is weakened (the fixes only add output guards, not input bypasses)
- No authentication or authorization logic is changed
- No sensitive data is logged or displayed differently
- The `??` and `?.` operators are native JavaScript — no third-party dependencies added

The only risk is that a null guard could mask a genuine backend bug by silently showing empty data instead of crashing. This is acceptable because:
1. The crash itself is worse than showing empty data (user loses their entire page context)
2. Backend errors are already logged server-side in the audit log
3. The frontend already shows error states in catch blocks — the null guards only protect against unexpected response shapes within successful (200) responses

---

## 8. Performance Considerations

- Optional chaining (`?.`) compiles to a simple null check — zero overhead
- Nullish coalescing (`??`) compiles to a ternary — zero overhead
- No additional API calls, no additional renders, no additional state updates
- No wrapper components, HOCs, or middleware added
- The resilience tests add ~30s to the test suite but don't affect runtime performance
- Bundle size impact: effectively zero (the compiled JS is a few bytes larger per guard)

---

## 9. Execution Order

1. Write the resilience tests first (they should all FAIL before fixes — this confirms the tests are valid)
2. Apply Phase 1 fixes (6 HIGH-risk files)
3. Run Phase 1 tests — should now PASS
4. Apply Phase 2 fixes (15 core revenue files)
5. Run Phase 2 tests — should now PASS
6. Apply Phase 3 fixes (20 daily operations files)
7. Run Phase 3 tests — should now PASS
8. Apply Phase 4 fixes (25 secondary feature files — note: `ProgressClaimForm`, `ProgressClaimList`, `TimeSheet` aggregation, and `VehicleProfile` odometer history are false positives and don't need fixes)
9. Run full resilience test suite — all ~189 tests should PASS
10. Run full frontend test suite (`npm test`) — no regressions in existing tests
