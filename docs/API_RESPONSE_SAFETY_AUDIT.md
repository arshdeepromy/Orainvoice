# API Response Safety Audit

**Date**: 2026-03-29
**Scope**: All frontend `.tsx` files in `frontend/src/pages/` and `frontend/src/components/`
**Pattern**: Unsafe access to API response data without null/undefined guards

This audit identifies files that access API response properties (`.map()`, `.filter()`, `.length`, `.toLocaleString()`, `.toFixed()`) without verifying the data exists first. These are the same class of bug that caused ISSUE-006, 012, 013, 017, 018, and 020.

---

## Category 1: Unsafe `.map()` / `.filter()` on Response Arrays (HIGH RISK — will crash if backend returns null/undefined)

These call array methods directly on `res.data.property` without checking if the property exists.

| File | Line | Unsafe Code | Risk |
|------|------|-------------|------|
| `pages/notifications/OverdueRules.tsx` | 98 | `res.data.rules.map(backendToUiRule)` | Crashes if `rules` is undefined |
| `components/inventory/AddToStockModal.tsx` | 209 | `res.data.products.map(...)` | Crashes if `products` is undefined |
| `components/inventory/AddToStockModal.tsx` | 236 | `res.data.parts.filter(...)` | Crashes if `parts` is undefined |
| `components/inventory/AddToStockModal.tsx` | 971 | `res.data.stock_items.map(...)` | Crashes if `stock_items` is undefined |
| `pages/admin/ErrorLog.tsx` | 408 | `res.data.errors.filter(...)` | Crashes if `errors` is undefined |

**Fix**: Add `?? []` fallback: `(res.data.rules ?? []).map(...)` or `(res.data?.products ?? []).map(...)`

---

## Category 2: Unsafe `.length` / Array Index Access (HIGH RISK — will crash on undefined)

| File | Line | Unsafe Code | Risk |
|------|------|-------------|------|
| `pages/floor-plan/FloorPlan.tsx` | 147 | `res.data.floor_plans.length` then `[0].id` | Crashes if `floor_plans` is undefined |

**Fix**: `const plans = res.data?.floor_plans ?? []; setFloorPlans(plans); if (!selectedPlanId && plans.length > 0) ...`

---

## Category 3: Direct `set*(res.data.property)` Without Null Guard (MEDIUM RISK — will set state to undefined, causing downstream crashes)

These assign a nested response property directly to state. If the backend response shape changes or the property is missing, state becomes `undefined` and any subsequent `.map()`, `.length`, or render access will crash.

| File | Line | Code | Property at risk |
|------|------|------|------------------|
| `pages/vehicles/VehicleList.tsx` | 118 | `setVehicles(res.data.items)` | `items` |
| `pages/settings/Billing.tsx` | 799 | `setPlans(res.data.plans)` | `plans` |
| `pages/recurring/RecurringList.tsx` | 93 | `setSchedules(res.data.schedules)` | `schedules` |
| `pages/projects/ProjectList.tsx` | 50 | `setProjects(res.data.projects)` | `projects` |
| `pages/notifications/Reminders.tsx` | 157 | `setManualReminders(res.data.manual_reminders)` | `manual_reminders` |
| `pages/notifications/Reminders.tsx` | 158 | `setRules(res.data.automated_reminders)` | `automated_reminders` |
| `pages/notifications/OverdueRules.tsx` | 97 | `setEnabled(res.data.reminders_enabled)` | `reminders_enabled` |
| `pages/notifications/NotificationPreferences.tsx` | 43 | `setCategories(res.data.categories)` | `categories` |
| `pages/notifications/NotificationLog.tsx` | 60 | `setEntries(res.data.entries)` | `entries` |
| `pages/jobs/JobTimer.tsx` | 115 | `setEntries(res.data.entries)` | `entries` |
| `pages/jobs/JobsPage.tsx` | 121 | `setJobs(res.data.job_cards)` | `job_cards` |
| `pages/jobs/JobList.tsx` | 79 | `setJobs(res.data.jobs)` | `jobs` |
| `pages/jobs/JobBoard.tsx` | 80 | `setJobs(res.data.jobs)` | `jobs` |
| `pages/items/ItemsPage.tsx` | 76 | `setItems(res.data.items)` | `items` |
| `pages/invoices/RecurringInvoices.tsx` | 460 | `setSchedules(res.data.schedules)` | `schedules` |
| `pages/inventory/SupplierList.tsx` | 64 | `setSuppliers(res.data.suppliers)` | `suppliers` |
| `pages/inventory/StockMovements.tsx` | 107 | `setMovements(res.data.movements)` | `movements` |
| `pages/inventory/StockMovements.tsx` | 119 | `setProducts(res.data.products)` | `products` |
| `pages/inventory/StockLevels.tsx` | 65 | `setStockItems(res.data.stock_items)` | `stock_items` |
| `pages/inventory/StockAdjustment.tsx` | 105 | `setParts(res.data.stock_levels)` | `stock_levels` |
| `pages/inventory/StockAdjustment.tsx` | 118 | `setFluids(res.data.fluid_stock_levels)` | `fluid_stock_levels` |
| `pages/inventory/ReorderAlerts.tsx` | 36 | `setAlerts(res.data.stock_items)` | `stock_items` |
| `pages/inventory/ProductList.tsx` | 88 | `setProducts(res.data.products)` | `products` |
| `pages/inventory/ProductList.tsx` | 107 | `setCategories(res.data.categories)` | `categories` |
| `pages/inventory/ProductList.tsx` | 114 | `setSuppliers(res.data.suppliers)` | `suppliers` |
| `pages/inventory/ProductDetail.tsx` | 172 | `setMovements(res.data.movements)` | `movements` |
| `pages/inventory/ProductDetail.tsx` | 182 | `setPricingRules(res.data.rules)` | `rules` |
| `pages/inventory/PricingRules.tsx` | 104 | `setProducts(res.data.products)` | `products` |
| `pages/inventory/CategoryTree.tsx` | 53 | `setTree(res.data.tree)` | `tree` |
| `pages/floor-plan/ReservationList.tsx` | 108 | `setReservations(res.data.reservations)` | `reservations` |
| `pages/floor-plan/ReservationList.tsx` | 121 | `setTables(res.data.tables)` | `tables` |
| `pages/floor-plan/FloorPlan.tsx` | 146 | `setFloorPlans(res.data.floor_plans)` | `floor_plans` |
| `pages/ecommerce/WooCommerceSetup.tsx` | 46 | `setSyncLogs(res.data.logs)` | `logs` |
| `pages/ecommerce/SkuMappings.tsx` | 38 | `setMappings(res.data.mappings)` | `mappings` |
| `pages/ecommerce/ApiKeys.tsx` | 31 | `setCredentials(res.data.credentials)` | `credentials` |
| `pages/customers/CustomerProfile.tsx` | 365 | `setMergePreview(res.data.preview)` | `preview` |
| `pages/customers/FleetAccounts.tsx` | 67 | `setAccounts(res.data.fleet_accounts)` | `fleet_accounts` |

**Fix**: Add `?? []` for arrays or `?? {}` for objects: `setVehicles(res.data?.items ?? [])`

---

## Category 4: Direct `setData(res.data)` Without Shape Validation (MEDIUM RISK — downstream renders crash if shape differs)

These assign the entire `res.data` to state and then render nested properties without guards. If the backend returns a different shape (e.g., error object, wrapped response), the render will crash.

| File | Pattern |
|------|---------|
| `pages/sms/SmsUsageSummary.tsx` | `setData(res.data)` — renders `data.sent_count`, `data.monthly_breakdown` etc. |
| `pages/floor-plan/FloorPlan.tsx` | `setState(res.data)` — renders floor plan state directly |
| `pages/settings/PrinterSettings.tsx` | `setPrinters(res.data)` — assumes bare array |
| `pages/settings/MfaSettings.tsx` | `setMethods(res.data)` — assumes bare array of MFA methods |
| `pages/settings/AccountingIntegrations.tsx` | `setData(res.data)` — renders nested accounting config |
| `pages/reports/TopServices.tsx` | `setData(res.data)` — renders `data.services.map(...)` |
| `pages/reports/StorageUsage.tsx` | `setData(res.data)` — renders `data.used_gb`, `data.quota_gb` |
| `pages/reports/RevenueSummary.tsx` | `setData(res.data)` — renders `data.monthly_breakdown.map(...)` |
| `pages/reports/OutstandingInvoices.tsx` | `setData(res.data)` — renders `data.invoices.map(...)` |
| `pages/reports/InvoiceStatus.tsx` | `setData(res.data)` — renders `data.by_status.map(...)` |
| `pages/reports/GstReturnSummary.tsx` | `setData(res.data)` — renders `data.gst_collected`, `data.gst_paid` |
| `pages/reports/FleetReport.tsx` | `setData(res.data)` — renders `data.vehicles.map(...)` |
| `pages/reports/CustomerStatement.tsx` | `setData(res.data)` — renders `data.invoices.map(...)` |
| `pages/reports/CarjamUsage.tsx` | `setData(res.data)` — renders `data.total_lookups`, `data.monthly` |
| `pages/reports/ReportBuilder.tsx` | `setData(res.data)` — renders dynamic report data |
| `pages/reports/ScheduledReports.tsx` | `setSchedules(res.data)` — assumes bare array |
| `pages/time-tracking/TimeSheet.tsx` | `setTimesheet(res.data)` — renders `data.entries`, `data.totals` |
| `pages/settings/CurrencySettings.tsx` | `setConfig(res.data)` — renders provider config |
| `pages/settings/Billing.tsx` | `setStatus(res.data)` — renders `status.storage_used_gb` etc. |

**Fix**: Validate shape before assignment or add guards in render: `data?.services?.map(...) ?? []`

---

## Category 5: Unsafe `.toLocaleString()` / `.toFixed()` on Potentially Undefined Values (MEDIUM RISK)

These call number formatting methods on values that could be undefined if the API response is incomplete.

| File | Line | Unsafe Code |
|------|------|-------------|
| `pages/admin/AnalyticsDashboard.tsx` | 107 | `data.total_orgs.toLocaleString()` — `data` null-checked but properties could be undefined |
| `pages/admin/Reports.tsx` | 422 | `data.total_records.toLocaleString()` — `data` null-checked but properties could be undefined |
| `pages/admin/Settings.tsx` | 208 | `stats.total_records.toLocaleString()` — `stats` null-checked but properties could be undefined |
| `pages/portal/LoyaltyBalance.tsx` | 68 | `data.total_points.toLocaleString()` — `data` null-checked but properties could be undefined |
| `pages/loyalty/LoyaltyConfig.tsx` | 250 | `analytics.total_points_issued.toLocaleString()` — guard checks `total_active_members` but not this field |
| `pages/loyalty/LoyaltyConfig.tsx` | 254 | `analytics.total_points_redeemed.toLocaleString()` — same partial guard issue |
| `pages/settings/FeatureFlagSettings.tsx` | 246 | `m.adoption_percent.toFixed(1)` — inside `.map()`, no per-field guard |
| `pages/settings/FeatureFlagSettings.tsx` | 254 | `m.error_rate.toFixed(2)` — inside `.map()`, no per-field guard |
| `pages/jobs/JobDetail.tsx` | 356-374 | Multiple `financials.*.toFixed(2)` calls |
| `pages/pos/TipPrompt.tsx` | 447-590 | Multiple `*.toFixed(2)` on tip amounts |

**Already protected (removed from this list after review):**
- `pages/vehicles/VehicleProfile.tsx` line 274 — `odometerHistory` is built with `.filter((s) => s.odometer != null)` so `entry.odometer` is guaranteed non-null
- `pages/invoices/InvoiceDetail.tsx` line 622 — guarded by `invoice.vehicle_odometer != null && invoice.vehicle_odometer > 0 &&`
- `pages/dashboard/GlobalAdminDashboard.tsx` line 193 — guarded by `data.platform_mrr != null &&`
- `pages/settings/Billing.tsx` line 719 — guarded by conditional that checks `status.storage_used_gb > newTotalQuota` (short-circuits on undefined)
- `pages/time-tracking/TimeSheet.tsx` lines 459-462 — values are locally computed from `(duration_minutes ?? 0) / 60`, always numbers
- `pages/construction/ProgressClaimForm.tsx` and `ProgressClaimList.tsx` — values from `calculateProgressClaimFields()` which takes `Number(x) || 0` inputs, always returns numbers

**Fix**: Use null-safe formatting: `(value ?? 0).toLocaleString()` or `(value ?? 0).toFixed(2)`

---

## Category 6: Type Assertion with Fallback (LOW RISK — won't crash but bypasses type safety)

These use `as any` type assertions with `|| []` fallbacks. They won't crash at runtime because `|| []` handles undefined/null, but they bypass TypeScript's compile-time safety which means future refactors won't catch type mismatches.

| File | Line | Code | Risk |
|------|------|------|------|
| `pages/inventory/StockUpdateLog.tsx` | 47 | `(res.data as any).movements \|\| []` | Won't crash but bypasses type safety |
| `pages/inventory/UsageHistory.tsx` | 37 | `(res.data as any).usage \|\| []` | Won't crash but bypasses type safety |

**Fix**: Replace with typed optional chaining: `res.data?.movements ?? []` with proper response type generic on the API call

---

## Summary

| Category | Count | Severity |
|----------|-------|----------|
| Unsafe `.map()` / `.filter()` on response arrays | 5 files | HIGH |
| Unsafe `.length` / array index access | 1 file | HIGH |
| Direct `set*(res.data.property)` without null guard | 37+ files | MEDIUM |
| Direct `setData(res.data)` without shape validation | 19 files | MEDIUM |
| Unsafe `.toLocaleString()` / `.toFixed()` | 10 files (6 removed as already protected) | MEDIUM |
| Type assertion with fallback | 2 files | LOW (won't crash, type safety concern only) |

**Total files with at least one unsafe pattern**: ~57+

The 6 HIGH-risk files (Category 1 and 2) will crash immediately if the backend returns an unexpected shape. The MEDIUM-risk files will crash on render if state is set to undefined.

## Recommended Approach

1. Fix the 6 HIGH-risk files first — these are guaranteed crashes on any backend hiccup
2. Add `?? []` fallbacks to all Category 3 state assignments
3. Add null guards in render paths for Category 4 and 5
4. Replace type assertions in Category 6 with proper null-safe patterns
5. Consider a shared `safeArray(data)` utility that returns `[]` if input is not an array
