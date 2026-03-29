# Trade Family Gating — Implementation Audit Report

Date: 2026-03-30

## Summary

When a user changes their business type from automotive to another trade (e.g., plumber), automotive-specific features remain visible on most pages. The sidebar correctly hides the Vehicles link, but individual pages still render vehicle columns, vehicle selectors, and vehicle-specific UI unconditionally.

## Root Cause

The gating was only applied in 3 places (sidebar, CataloguePage, InvoiceList variable declaration) but not in the 10+ other pages that render vehicle-specific UI. The `isAutomotive` variable is declared in InvoiceList but never used to conditionally render anything.

## What Works

| Component | Status | Notes |
|-----------|--------|-------|
| Backend: `PUT /org/settings` with `trade_category_slug` | ✅ Working | Updates `trade_category_id` in DB |
| Backend: `GET /org/settings` returns `trade_family` | ✅ Working | Resolves family from category via JOIN |
| TenantContext: `tradeFamily` state | ✅ Working | Fetches and stores correctly, `refetch()` works |
| Sidebar: Vehicles nav item | ✅ Working | Hidden when `tradeFamily !== 'automotive-transport'` |
| CataloguePage: Parts/Fluids tabs | ✅ Working | Hidden for non-automotive |
| Business Type selector in Settings | ✅ Working | Dropdown loads, saves, refetches context |

## What's Broken

| Page | Issue | Fix Required |
|------|-------|-------------|
| `InvoiceList.tsx` | Declares `isAutomotive` but never uses it — vehicle rego column always shows | Wrap vehicle column in `{isAutomotive && ...}` |
| `InvoiceCreate.tsx` | Imports and renders `VehicleLiveSearch` unconditionally | Conditionally render based on `isAutomotive` |
| `InvoiceDetail.tsx` | Shows vehicle info section unconditionally | Add `isAutomotive` check |
| `QuoteList.tsx` | No `tradeFamily` check — vehicle rego column always shows | Add `useTenant()` + conditional render |
| `QuoteCreate.tsx` | Likely renders vehicle selector unconditionally | Add `isAutomotive` check |
| `QuoteDetail.tsx` | Likely shows vehicle info unconditionally | Add `isAutomotive` check |
| `JobCardList.tsx` | Likely shows vehicle info unconditionally | Add `isAutomotive` check |
| `JobCardCreate.tsx` | Likely renders vehicle selector unconditionally | Add `isAutomotive` check |
| `JobCardDetail.tsx` | Likely shows vehicle info unconditionally | Add `isAutomotive` check |
| `BookingCalendarPage.tsx` | Likely renders vehicle selector in booking form | Add `isAutomotive` check |
| `App.tsx` routes | `/vehicles` and `/vehicles/:id` accessible via direct URL for non-automotive | Add `RequireAutomotive` route guard |
| `VehicleList.tsx` | Page renders for any user who navigates to `/vehicles` | Should redirect non-automotive to dashboard |
| `VehicleProfile.tsx` | Page renders for any user who navigates to `/vehicles/:id` | Should redirect non-automotive to dashboard |

## Fix Plan

### Phase 1: Route Guard (prevents direct URL access)
Add a `RequireAutomotive` wrapper in `App.tsx` that checks `tradeFamily` and redirects non-automotive users to `/dashboard` when they try to access `/vehicles/*`.

### Phase 2: Invoice Pages
- `InvoiceList.tsx`: Use the existing `isAutomotive` variable to conditionally render vehicle rego column and vehicle info in the detail panel
- `InvoiceCreate.tsx`: Wrap `VehicleLiveSearch` and vehicle selection section in `{isAutomotive && ...}`

### Phase 3: Quote Pages
- `QuoteList.tsx`: Add `useTenant()`, compute `isAutomotive`, conditionally render vehicle rego column
- `QuoteCreate.tsx`: Conditionally render vehicle selector
- `QuoteDetail.tsx`: Conditionally render vehicle info section

### Phase 4: Job Card Pages
- `JobCardList.tsx`: Conditionally render vehicle column
- `JobCardCreate.tsx`: Conditionally render vehicle selector
- `JobCardDetail.tsx`: Conditionally render vehicle info

### Phase 5: Booking Pages
- `BookingCalendarPage.tsx` / `BookingForm.tsx`: Conditionally render vehicle selector in booking creation

## Pattern for All Fixes

Every page that shows vehicle-specific UI needs this at the top of the component:

```tsx
const { tradeFamily } = useTenant()
const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
```

Then wrap vehicle-specific JSX:
```tsx
{isAutomotive && <VehicleColumn />}
{isAutomotive && <VehicleLiveSearch ... />}
{isAutomotive && <VehicleInfoSection />}
```

## Testing Checklist

After all fixes:
- [ ] Automotive org: vehicles nav shows, vehicle columns show in invoices/quotes/jobs/bookings
- [ ] Change to plumber: vehicles nav hides, vehicle columns hide everywhere
- [ ] Direct URL `/vehicles` as plumber: redirects to dashboard
- [ ] Refresh page after business type change: vehicle UI stays hidden
- [ ] Change back to automotive: everything reappears
- [ ] Check: InvoiceList, InvoiceCreate, InvoiceDetail
- [ ] Check: QuoteList, QuoteCreate, QuoteDetail
- [ ] Check: JobCardList, JobCardCreate, JobCardDetail
- [ ] Check: BookingCalendarPage
- [ ] Check: CataloguePage (Parts/Fluids tabs)
