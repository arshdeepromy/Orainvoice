# Trade Family Gating Fix — Bugfix Design

## Overview

Non-automotive organisations see vehicle-specific UI (columns, selectors, info sections, routes) across 10+ frontend pages despite the backend, TenantContext, sidebar, and CataloguePage all gating correctly. The fix adds `isAutomotive` checks to every page that renders vehicle-specific UI, plus a `RequireAutomotive` route guard in `App.tsx` to block direct URL access to `/vehicles` routes. No backend changes are needed.

## Glossary

- **Bug_Condition (C)**: The organisation's `tradeFamily` is NOT `'automotive-transport'` (and is not null), yet vehicle-specific UI is rendered
- **Property (P)**: Vehicle-specific UI elements are hidden when `tradeFamily` is non-automotive; shown when automotive or null
- **Preservation**: All existing automotive-org behaviour, mouse interactions, non-vehicle UI, and null-tradeFamily backward compatibility must remain unchanged
- **`tradeFamily`**: String from `useTenant()` context — e.g. `'automotive-transport'`, `'plumbing'`, or `null`
- **`isAutomotive`**: Derived boolean: `(tradeFamily ?? 'automotive-transport') === 'automotive-transport'` — null treated as automotive for backward compatibility
- **`RequireAutomotive`**: New route guard component that redirects non-automotive users away from `/vehicles` routes
- **`ModuleGate`**: Existing component that gates UI on feature module flags (separate from trade family gating)

## Bug Details

### Fault Condition

The bug manifests when a non-automotive organisation views any page that renders vehicle-specific UI. The page components either lack a `tradeFamily` check entirely, or (in InvoiceList's case) declare `isAutomotive` but never use it to conditionally render vehicle elements.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type { tradeFamily: string | null, page: PageIdentifier }
  OUTPUT: boolean

  LET isAutomotive = (input.tradeFamily ?? 'automotive-transport') === 'automotive-transport'

  RETURN NOT isAutomotive
         AND input.page IN [
           'InvoiceList', 'InvoiceCreate', 'InvoiceDetail',
           'QuoteList', 'QuoteCreate', 'QuoteDetail',
           'JobCardList', 'JobCardCreate', 'JobCardDetail',
           'BookingForm',
           'VehicleRoutes'
         ]
         AND vehicleUIIsRendered(input.page)
END FUNCTION
```

### Examples

- A plumber views Invoice List → vehicle registration column is visible (should be hidden)
- A plumber creates a new invoice → VehicleLiveSearch vehicle selector is rendered (should be hidden)
- A plumber views quote detail → vehicle rego/make/model section is shown (should be hidden)
- A plumber navigates to `/vehicles` via URL → VehicleList page renders (should redirect to `/dashboard`)
- An automotive org views Invoice List → vehicle registration column is visible (correct, unchanged)
- An org with `tradeFamily: null` views Invoice List → vehicle column is visible (correct, backward compat)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Automotive organisations see all vehicle UI on every page exactly as before
- Organisations with `tradeFamily: null` see all vehicle UI (backward compatibility)
- Mouse clicks, form submissions, and all non-vehicle interactions work identically
- Sidebar vehicle nav item continues to hide/show correctly (already working)
- CataloguePage Parts/Fluids tabs continue to hide/show correctly (already working)
- Non-vehicle columns, form fields, and page sections render identically regardless of trade family
- Backend API responses are unchanged — no backend modifications

**Scope:**
All inputs that do NOT involve vehicle-specific UI rendering should be completely unaffected by this fix. This includes:
- Customer search, line item management, totals calculations
- Invoice/quote/job-card CRUD operations and status transitions
- Payment recording, PDF generation, email sending
- All non-vehicle form fields (dates, notes, terms, etc.)
- Timer functionality on job cards
- Booking scheduling, reminders, and confirmations

## Hypothesized Root Cause

Based on the audit, the root causes are straightforward omissions:

1. **InvoiceList.tsx**: `isAutomotive` is computed from `useTenant()` but never used in JSX — the vehicle info section inside the invoice detail card is wrapped in `{isAutomotive && ...}` but the vehicle registration column in the list sidebar is not gated (the list view doesn't show a vehicle column, but the detail panel's vehicle section needs the existing `isAutomotive` guard verified)

2. **InvoiceCreate.tsx**: Uses `vehiclesEnabled` from `useModules()` to gate the `VehicleLiveSearch` via `<ModuleGate module="vehicles">`, but does NOT check `tradeFamily`. The `ModuleGate` checks the feature module flag, not the trade family. A non-automotive org with the vehicles module enabled still sees vehicle UI.

3. **InvoiceDetail.tsx**: Uses `<ModuleGate module="vehicles">` to wrap the vehicle section, but does NOT check `tradeFamily`. Same issue as InvoiceCreate.

4. **QuoteList.tsx**: No `useTenant()` import, no `tradeFamily` check, no vehicle column to hide (the table doesn't have a vehicle column). However, the quote list rows don't show vehicle info either — the issue is in QuoteDetail.

5. **QuoteCreate.tsx**: Uses `isEnabled('vehicles')` to gate the vehicle lookup section, but does NOT check `tradeFamily`.

6. **QuoteDetail.tsx**: Renders `quote.vehicle_rego` unconditionally in the info grid with no trade family check.

7. **JobCardList.tsx**: Renders a "Rego" column unconditionally in the table header and body.

8. **JobCardCreate.tsx**: Renders `<VehicleRegoLookup>` section unconditionally with no trade family or module check.

9. **JobCardDetail.tsx**: Renders a "Vehicle" section unconditionally showing `jobCard.vehicle_rego`.

10. **BookingForm.tsx**: Uses `<ModuleGate module="vehicles">` for `VehicleLiveSearch`, but does NOT check `tradeFamily`. The fluid usage section is already gated on `vehiclesEnabled && selectedVehicle`.

11. **App.tsx**: `/vehicles` and `/vehicles/:id` routes have no trade family guard — any authenticated user can navigate directly to these URLs.

## Correctness Properties

Property 1: Fault Condition — Vehicle UI Hidden for Non-Automotive Organisations

_For any_ page visit where `tradeFamily` is a non-automotive value (e.g. `'plumbing'`, `'electrical'`) and the page is one of the 10 affected pages, the fixed components SHALL NOT render vehicle-specific UI elements (vehicle columns, vehicle selectors, vehicle info sections). For `/vehicles` routes, the user SHALL be redirected to `/dashboard`.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11**

Property 2: Preservation — Vehicle UI Shown for Automotive and Null-TradeFamily Organisations

_For any_ page visit where `tradeFamily` is `'automotive-transport'` OR `null`, the fixed components SHALL render vehicle-specific UI elements exactly as the original (unfixed) code does, preserving all existing automotive functionality including vehicle columns, selectors, info sections, and route access.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:


**File**: `frontend/src/App.tsx`
**Function**: `AppRoutes`
**Change**: Add a `RequireAutomotive` route guard component (modeled on `RequireGlobalAdmin`) that reads `tradeFamily` from `useTenant()`, computes `isAutomotive`, and redirects to `/dashboard` if not automotive. Wrap the `/vehicles` and `/vehicles/:id` routes with this guard.

```
FUNCTION RequireAutomotive()
  LET { tradeFamily } = useTenant()
  LET isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
  IF NOT isAutomotive THEN RETURN <Navigate to="/dashboard" replace />
  RETURN <Outlet />
END FUNCTION
```

---

**File**: `frontend/src/pages/invoices/InvoiceList.tsx`
**Function**: `InvoiceList`
**Change**: The `isAutomotive` variable already exists and is correctly computed. The invoice detail panel's vehicle info section is already wrapped in `{isAutomotive && ...}`. Verify this is complete — the list sidebar doesn't have a vehicle column, so the existing gating on the detail panel vehicle section is the fix. No additional changes needed if the existing `{isAutomotive && ...}` wrapping is confirmed correct.

---

**File**: `frontend/src/pages/invoices/InvoiceCreate.tsx`
**Function**: `InvoiceCreate`
**Change**: Add `tradeFamily` from `useTenant()` (settings is already destructured from it), compute `isAutomotive`. The existing `<ModuleGate module="vehicles">` wrapping the vehicle search section must be augmented with an `isAutomotive` check. Wrap the vehicle section in `{isAutomotive && <ModuleGate module="vehicles">...</ModuleGate>}`. Also gate the fluid usage section and labour picker button similarly.

---

**File**: `frontend/src/pages/invoices/InvoiceDetail.tsx`
**Function**: `InvoiceDetail`
**Change**: Add `const { tradeFamily } = useTenant()` and compute `isAutomotive`. The existing `<ModuleGate module="vehicles">` wrapping the vehicle section must be augmented: `{isAutomotive && <ModuleGate module="vehicles">...</ModuleGate>}`.

---

**File**: `frontend/src/pages/quotes/QuoteList.tsx`
**Function**: `QuoteList`
**Change**: The table does not currently have a vehicle column — the columns are Date, Quote Number, Customer Name, Status, Expires In, Amount, Actions. No vehicle-specific UI to hide. However, if the audit identified this file, verify there's no vehicle rendering. If none exists, no change needed.

---

**File**: `frontend/src/pages/quotes/QuoteCreate.tsx`
**Function**: `QuoteCreate`
**Change**: Add `const { tradeFamily } = useTenant()` and compute `isAutomotive`. The existing `{isEnabled('vehicles') && ...}` wrapping the vehicle lookup section must be augmented: `{isAutomotive && isEnabled('vehicles') && ...}`. Also gate the `vehicle_rego`, `vehicle_make`, `vehicle_model` fields in `buildPayload()` with `isAutomotive`.

---

**File**: `frontend/src/pages/quotes/QuoteDetail.tsx`
**Function**: `QuoteDetail`
**Change**: Add `const { tradeFamily } = useTenant()` and compute `isAutomotive`. Wrap the `{quote.vehicle_rego && ...}` vehicle info block in `{isAutomotive && quote.vehicle_rego && ...}`.

---

**File**: `frontend/src/pages/job-cards/JobCardList.tsx`
**Function**: `JobCardList`
**Change**: Add `const { tradeFamily } = useTenant()` and compute `isAutomotive`. Conditionally render the "Rego" `<th>` column header and the corresponding `<td>` cell: `{isAutomotive && <th>Rego</th>}` and `{isAutomotive && <td>{rego}</td>}`. Adjust `colSpan` on the empty-state row accordingly.

---

**File**: `frontend/src/pages/job-cards/JobCardCreate.tsx`
**Function**: `JobCardCreate`
**Change**: Add `const { tradeFamily } = useTenant()` and compute `isAutomotive`. Wrap the entire Vehicle section (`<section aria-labelledby="section-vehicle">...</section>`) in `{isAutomotive && ...}`. Also gate the `vehicle_id` field in the save payload.

---

**File**: `frontend/src/pages/job-cards/JobCardDetail.tsx`
**Function**: `JobCardDetail`
**Change**: Add `const { tradeFamily } = useTenant()` and compute `isAutomotive`. Wrap the Vehicle `<section>` (the one showing `jobCard.vehicle_rego`) in `{isAutomotive && ...}`.

---

**File**: `frontend/src/pages/bookings/BookingForm.tsx`
**Function**: `BookingForm`
**Change**: Add `const { tradeFamily } = useTenant()` and compute `isAutomotive`. The existing `<ModuleGate module="vehicles">` wrapping `VehicleLiveSearch` must be augmented: `{isAutomotive && <ModuleGate module="vehicles">...</ModuleGate>}`. The fluid usage section is already gated on `vehiclesEnabled && selectedVehicle` — add `isAutomotive` to that condition as well.

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Fault Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis.

**Test Plan**: Render each affected component with a mocked `TenantContext` providing `tradeFamily: 'plumbing'` and assert that vehicle-specific UI elements are present (proving the bug exists on unfixed code).

**Test Cases**:
1. **InvoiceCreate Vehicle Selector**: Render with `tradeFamily: 'plumbing'` — VehicleLiveSearch is visible (will fail on unfixed code to prove bug)
2. **QuoteDetail Vehicle Info**: Render with `tradeFamily: 'plumbing'` and a quote with `vehicle_rego` — vehicle section is visible (proves bug)
3. **JobCardList Rego Column**: Render with `tradeFamily: 'plumbing'` — "Rego" column header is present (proves bug)
4. **App.tsx Vehicle Route**: Navigate to `/vehicles` with `tradeFamily: 'plumbing'` — VehicleList renders instead of redirecting (proves bug)

**Expected Counterexamples**:
- Vehicle UI elements render for non-automotive orgs because no `tradeFamily` check exists
- Root cause confirmed: missing conditional rendering, not a data issue

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed components hide vehicle UI.

**Pseudocode:**
```
FOR ALL tradeFamily WHERE tradeFamily NOT IN ['automotive-transport', null] DO
  FOR ALL page IN affectedPages DO
    result := renderPage_fixed(page, tradeFamily)
    ASSERT vehicleUIElements(result) = EMPTY
  END FOR
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed components render identically to the original.

**Pseudocode:**
```
FOR ALL tradeFamily WHERE tradeFamily IN ['automotive-transport', null] DO
  FOR ALL page IN affectedPages DO
    ASSERT renderPage_original(page, tradeFamily) = renderPage_fixed(page, tradeFamily)
  END FOR
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It can generate many `tradeFamily` values to verify the automotive/null path is unchanged
- It catches edge cases like empty string, undefined, or unexpected trade family values
- It provides strong guarantees that the conditional logic correctly partitions automotive vs non-automotive

**Test Plan**: Observe behavior on UNFIXED code first for automotive orgs, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Automotive Invoice Create**: Verify VehicleLiveSearch renders for `tradeFamily: 'automotive-transport'` — continues after fix
2. **Null TradeFamily Backward Compat**: Verify all vehicle UI renders for `tradeFamily: null` — continues after fix
3. **Automotive Vehicle Routes**: Verify `/vehicles` renders VehicleList for automotive orgs — continues after fix
4. **Non-Vehicle UI Unchanged**: Verify customer search, line items, totals, and all non-vehicle form fields render identically regardless of tradeFamily

### Unit Tests

- Test `RequireAutomotive` route guard: redirects for non-automotive, renders `<Outlet>` for automotive and null
- Test each page component with `tradeFamily: 'plumbing'` — vehicle UI absent
- Test each page component with `tradeFamily: 'automotive-transport'` — vehicle UI present
- Test each page component with `tradeFamily: null` — vehicle UI present (backward compat)
- Test edge case: `tradeFamily: ''` (empty string) — should hide vehicle UI

### Property-Based Tests

- Generate random non-automotive `tradeFamily` strings and verify vehicle UI is hidden across all affected pages
- Generate random automotive/null `tradeFamily` values and verify vehicle UI is shown, matching original behavior
- Test `isAutomotive` derivation: for any string that is not `'automotive-transport'` and is not null, `isAutomotive` is false

### Integration Tests

- Full flow: change business type from automotive to plumber in Settings, then navigate to each affected page and verify vehicle UI is hidden
- Full flow: change business type back to automotive, verify vehicle UI reappears
- Direct URL navigation to `/vehicles` as non-automotive org, verify redirect to `/dashboard`
- Verify sidebar, CataloguePage, and all fixed pages are consistent in their gating behavior
