---
inclusion: auto
---

# Trade Family Gating — Mandatory for New Features

This steering doc is always loaded. It ensures that every new feature, module, or UI component is properly gated by trade family from the start — preventing the recurring bug where automotive-specific UI leaks into non-automotive organisations.

## When This Applies

This applies when the user asks to implement ANY of the following:
- A new module or feature area
- New fields, columns, or sections on existing pages (invoices, quotes, bookings, job cards, catalogue, inventory)
- New sidebar navigation items
- New routes in App.tsx
- New catalogue forms or product types
- New integrations (e.g., vehicle lookup, parts supplier APIs)

This does NOT apply to:
- Bug fixes on existing code (those should follow the existing gating patterns)
- Backend-only changes with no UI
- Global admin features (admin panel, platform settings)

## Step 1: Ask the User Which Trade This Feature Is For

Before writing any code, ask the user:

> "Which trade or business type is this feature for? Pick one or more, or 'all' if it's universal:"
>
> 1. `automotive-transport` — Automotive & Transport (mechanics, panel beaters, tyre shops)
> 2. `electrical-mechanical` — Electrical & Mechanical (electricians, solar installers)
> 3. `plumbing-gas` — Plumbing & Gas (plumbers, gasfitters, drainlayers)
> 4. `building-construction` — Building & Construction (builders, roofers, painters)
> 5. `landscaping-outdoor` — Landscaping & Outdoor
> 6. `cleaning-facilities` — Cleaning & Facilities
> 7. `it-technology` — IT & Technology
> 8. `creative-professional` — Creative & Professional Services
> 9. `accounting-legal-financial` — Accounting, Legal & Financial
> 10. `health-wellness` — Health & Wellness
> 11. `food-hospitality` — Food & Hospitality
> 12. `retail` — Retail
> 13. `hair-beauty-personal-care` — Hair, Beauty & Personal Care
> 14. `trades-support-hire` — Trades Support & Hire
> 15. `freelancing-contracting` — Freelancing & Contracting
> 16. **All trades** — Universal feature (no gating needed)

Wait for the user's answer before proceeding.

## Step 2: Apply the Correct Gating Pattern

Based on the user's answer, apply gating to ALL new UI elements.

### If the feature is for a SINGLE trade family

Every new frontend component, JSX section, table column, form field, route, and sidebar link must be wrapped:

```tsx
// At the top of the component
const { tradeFamily } = useTenant()
const isTargetTrade = (tradeFamily ?? 'automotive-transport') === 'TARGET_SLUG'

// Wrap all trade-specific JSX
{isTargetTrade && (
  <TradeSpecificSection />
)}

// Gate columns in tables
{isTargetTrade && <th>Trade-Specific Column</th>}
{isTargetTrade && <td>{data.trade_specific_field}</td>}

// Gate fields in payloads
const payload = {
  ...commonFields,
  ...(isTargetTrade ? { trade_specific_field: value } : {}),
}
```

For automotive specifically, use the established pattern:
```tsx
const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
```

The `?? 'automotive-transport'` fallback treats null tradeFamily as automotive for backward compatibility with existing orgs that haven't set their trade yet.

### If the feature is for MULTIPLE trade families

```tsx
const { tradeFamily } = useTenant()
const effectiveFamily = tradeFamily ?? 'automotive-transport'
const isTargetTrade = ['automotive-transport', 'electrical-mechanical', 'plumbing-gas'].includes(effectiveFamily)
```

### If the feature is for ALL trades

No gating needed. But still consider whether specific sub-sections within the feature are trade-specific (e.g., a universal booking form might have an automotive-only vehicle selector section).

## Step 3: Gate These Specific Element Types

Every one of these must be checked:

### Frontend JSX
- Table columns (`<th>` and corresponding `<td>`)
- Form sections and fields
- Sidebar navigation links
- Detail page info sections
- Modal content sections
- Picker/search components (VehicleLiveSearch, parts picker, etc.)
- Action buttons (+ Add Part, + Labour Charge, etc.)

### Routes in App.tsx
- New routes for trade-specific pages need a route guard (like `RequireAutomotive` for `/vehicles`)

### API Payloads
- Trade-specific fields in POST/PUT payloads must be conditionally included
- Use the spread pattern: `...(isTargetTrade ? { field: value } : {})`

### Sidebar (OrgLayout.tsx)
- New nav items must be wrapped in the trade family check

### Catalogue (CataloguePage.tsx)
- New catalogue tabs/forms must be gated by trade family

## Step 4: Checklist Before Considering Code Complete

Before any trade-specific feature is done:

- [ ] Asked the user which trade family this is for
- [ ] Every new JSX section is wrapped in `{isTargetTrade && ...}`
- [ ] Every new table column (th + td) is conditionally rendered
- [ ] Every new form field is conditionally rendered
- [ ] API payloads conditionally include trade-specific fields
- [ ] New routes have a route guard if they're trade-specific pages
- [ ] New sidebar links are gated
- [ ] `colSpan` on empty-state rows accounts for conditional columns
- [ ] `useTenant()` is imported from `@/contexts/TenantContext`
- [ ] Null tradeFamily is handled with `?? 'automotive-transport'` fallback

## Existing Gating Reference

These are the files that already have `isAutomotive` gating — use them as reference for the pattern:

| File | What's gated |
|------|-------------|
| `App.tsx` | `RequireAutomotive` route guard on `/vehicles` routes |
| `OrgLayout.tsx` (sidebar) | Vehicles nav link |
| `CataloguePage.tsx` | Parts and Fluids tabs |
| `InvoiceList.tsx` | Vehicle info in detail panel |
| `InvoiceCreate.tsx` | VehicleLiveSearch, fluid usage, labour picker |
| `InvoiceDetail.tsx` | Vehicle info section |
| `QuoteCreate.tsx` | Vehicle lookup, parts/labour buttons, vehicle payload fields |
| `QuoteDetail.tsx` | Vehicle rego display |
| `JobCardList.tsx` | Rego column (th + td), colSpan |
| `JobCardCreate.tsx` | Vehicle section, vehicle_id in payload |
| `JobCardDetail.tsx` | Vehicle section |
| `BookingForm.tsx` | VehicleLiveSearch, Parts section, fluid section, vehicle_rego/parts/fluid in payload |
| `BookingCalendar.tsx` | Vehicle rego on calendar cards |
| `BookingListPanel.tsx` | Vehicle Rego column (th + td) |
| `JobCreationModal.tsx` | Vehicle Rego display |

## Common Mistakes to Avoid

1. Adding a vehicle/parts/fluid section without `isAutomotive` check
2. Gating with `ModuleGate module="vehicles"` instead of `isAutomotive` — vehicles are a trade feature, not a toggleable module
3. Forgetting to gate the `<td>` when you gate the `<th>` (or vice versa)
4. Forgetting to gate the API payload fields — the UI is hidden but the data still gets sent
5. Forgetting to adjust `colSpan` on empty-state table rows when a column is conditional
6. Not handling null `tradeFamily` — always use `?? 'automotive-transport'` for backward compat
7. Hardcoding trade-specific labels instead of using TerminologyContext
