# Tasks — Quote Vehicle Autofill Fix

## Task List

- [x] 1. Add LinkedVehicle interface and update Customer interface
  - [x] 1.1 Add `LinkedVehicle` interface after the existing `Vehicle` interface in QuoteCreate.tsx with fields: id, rego, make (string | null), model (string | null), year (number | null), colour (string | null)
  - [x] 1.2 Add `linked_vehicles?: LinkedVehicle[]` field to the existing `Customer` interface in QuoteCreate.tsx
- [x] 2. Update CustomerSearch component props and API call
  - [x] 2.1 Add `onVehicleAutoSelect?: (v: LinkedVehicle) => void` and `includeVehicles?: boolean` (default true) props to the CustomerSearch component's destructured params and type annotation
  - [x] 2.2 Update the `apiClient.get('/customers', ...)` call to include `include_vehicles: true` when `includeVehicles` is true: `params: { q: q, ...(includeVehicles ? { include_vehicles: true } : {}) }`
  - [x] 2.3 Add rego matching to the client-side filter: check `(c.linked_vehicles || []).some((v: LinkedVehicle) => matchesSequence(v.rego || '', term))` and include it in the return condition
- [x] 3. Add vehicle auto-fill logic to customer select handler
  - [x] 3.1 Extract the inline `onClick` handler into a named `handleSelect` function that calls `onSelect(c)`, sets the query, closes the dropdown, and calls `onVehicleAutoSelect(c.linked_vehicles[0])` if the customer has linked vehicles and the callback exists
  - [x] 3.2 Update the dropdown button's `onClick` to call `handleSelect(c)` instead of the inline logic
- [x] 4. Wire onVehicleAutoSelect callback at the CustomerSearch render site
  - [x] 4.1 Pass `onVehicleAutoSelect` prop to `<CustomerSearch>` at ~line 1112 with a callback that sets vehicle state (mapping LinkedVehicle fields to Vehicle fields with `|| ''` fallbacks for nullable strings) and sets vehicleRego, guarded by `if (!vehicle)`
- [x] 5. Verify the fix
  - [x] 5.1 Run TypeScript compilation (`npx tsc --noEmit`) to confirm no type errors in QuoteCreate.tsx
  - [x] 5.2 Manually verify the fix matches InvoiceCreate's pattern by comparing the two CustomerSearch implementations
