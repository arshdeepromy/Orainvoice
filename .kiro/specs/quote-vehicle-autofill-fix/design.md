# Quote Vehicle Autofill Fix — Bugfix Design

## Overview

The QuoteCreate form's local `CustomerSearch` component does not auto-fill vehicle details when a customer with linked vehicles is selected. This feature works correctly in InvoiceCreate because that component passes `include_vehicles: true` to the API, defines a `LinkedVehicle` interface, and calls an `onVehicleAutoSelect` callback. The fix aligns QuoteCreate's `CustomerSearch` with InvoiceCreate's implementation pattern.

## Glossary

- **Bug_Condition (C)**: A customer with linked vehicles is selected in QuoteCreate when no vehicle is currently set — the vehicle field remains empty instead of auto-filling
- **Property (P)**: When a customer with linked vehicles is selected and no vehicle is set, the first linked vehicle's details should populate the vehicle field
- **Preservation**: All existing QuoteCreate behavior (search, create customer, clear, vehicle→customer backfill via VehicleLiveSearch) must remain unchanged
- **CustomerSearch**: The local component defined inside `QuoteCreate.tsx` (line 142) that handles customer search and selection
- **LinkedVehicle**: A vehicle record associated with a customer, returned by the `/customers` API when `include_vehicles: true` is passed
- **onVehicleAutoSelect**: A callback prop that triggers vehicle auto-fill when a customer with linked vehicles is selected

## Bug Details

### Bug Condition

The bug manifests when a user selects a customer that has linked vehicles in the QuoteCreate form. The local `CustomerSearch` component:
1. Does not include `linked_vehicles` on its `Customer` interface
2. Does not pass `include_vehicles: true` to the `/customers` API call
3. Does not accept an `onVehicleAutoSelect` prop
4. Does not call any vehicle auto-fill logic in its select handler

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type CustomerSelectEvent
  OUTPUT: boolean
  
  RETURN input.selectedCustomer.linked_vehicles IS NOT EMPTY
         AND input.selectedCustomer.linked_vehicles.length > 0
         AND input.currentVehicle = null
END FUNCTION
```

### Examples

- User selects "John Smith" who has vehicle "ABC123" (2020 Toyota Corolla) linked → Expected: vehicle field auto-fills with ABC123. Actual: vehicle field remains empty.
- User selects "Jane Doe" who has two vehicles linked → Expected: first vehicle auto-fills. Actual: vehicle field remains empty.
- User selects "Bob Wilson" who has no linked vehicles → Expected: no vehicle change. Actual: no vehicle change (correct, not a bug case).
- User selects "John Smith" when vehicle "XYZ789" is already selected → Expected: existing vehicle preserved. Actual: existing vehicle preserved (correct, guard prevents overwrite).

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Mouse clicks on customer search results must continue to select the customer
- VehicleLiveSearch vehicle→customer backfill must continue to work (selecting a vehicle auto-fills customer)
- Customer search fuzzy matching on first_name, last_name, display_name, and phone must remain
- "+ Add New Customer" modal flow must remain unchanged
- Clearing customer selection must not affect the vehicle field
- Customer dropdown display (name + email) must remain unchanged

**Scope:**
All inputs that do NOT involve selecting a customer with linked vehicles when no vehicle is set should be completely unaffected by this fix. This includes:
- Selecting customers with no linked vehicles
- Selecting customers when a vehicle is already chosen
- Creating new customers via the modal
- Clearing customer selection
- Vehicle search via VehicleLiveSearch
- All other form interactions (items, dates, subject, etc.)

## Hypothesized Root Cause

Based on code analysis, the root cause is confirmed (not hypothesized):

1. **Missing Interface Fields**: The `Customer` interface (line 19) lacks `linked_vehicles?: LinkedVehicle[]` and there is no `LinkedVehicle` interface defined in QuoteCreate.tsx

2. **Missing API Parameter**: The `search` function in CustomerSearch does not pass `include_vehicles: true` to the `/customers` API call, so the backend never returns linked vehicle data

3. **Missing Callback Prop**: The `CustomerSearch` component does not accept an `onVehicleAutoSelect` prop, so there is no mechanism to communicate vehicle selection back to the parent

4. **Missing Select Handler Logic**: The inline `onClick` handler in the dropdown simply calls `onSelect(c)` and sets the query — it does not check for linked vehicles or invoke any auto-fill callback

5. **Missing Rego Filter**: The client-side filter does not match on `linked_vehicles[].rego`, unlike InvoiceCreate which includes rego matching

## Correctness Properties

Property 1: Bug Condition - Vehicle Auto-Fill on Customer Select

_For any_ customer selection event where the selected customer has linked vehicles AND no vehicle is currently set in the form, the fixed CustomerSearch component SHALL invoke the `onVehicleAutoSelect` callback with the first linked vehicle, causing the vehicle state to be set with `{ id, rego, make, model, year, colour }` and `vehicleRego` to be set to the vehicle's rego.

**Validates: Requirements 2.1, 2.2**

Property 2: Preservation - Non-Autofill Interactions Unchanged

_For any_ customer selection event where the selected customer has NO linked vehicles OR a vehicle is already selected, the fixed CustomerSearch component SHALL produce the same behavior as the original — selecting the customer without modifying the vehicle field. All other interactions (search, create, clear, VehicleLiveSearch backfill) SHALL remain identical.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

## Fix Implementation

### Changes Required

All changes are in **`frontend/src/pages/quotes/QuoteCreate.tsx`**.

**1. Add `LinkedVehicle` interface** (after the existing `Vehicle` interface, ~line 35):
```typescript
interface LinkedVehicle {
  id: string
  rego: string
  make: string | null
  model: string | null
  year: number | null
  colour: string | null
}
```

**2. Add `linked_vehicles` to `Customer` interface** (line 19):
```typescript
interface Customer {
  id: string
  first_name: string
  last_name: string
  email: string
  phone: string
  address?: string
  linked_vehicles?: LinkedVehicle[]
}
```

**3. Add props to `CustomerSearch` component** (line 142):
- Add `onVehicleAutoSelect?: (v: LinkedVehicle) => void` prop
- Add `includeVehicles?: boolean` prop (default `true`)

**4. Pass `include_vehicles: true` in API call**:
```typescript
const res = await apiClient.get('/customers', { 
  params: { q: q, ...(includeVehicles ? { include_vehicles: true } : {}) } 
})
```

**5. Add rego matching to client-side filter**:
```typescript
const regoMatch = (c.linked_vehicles || []).some((v: LinkedVehicle) =>
  matchesSequence(v.rego || '', term)
)
return (
  matchesSequence(firstName, term) ||
  matchesSequence(lastName, term) ||
  matchesSequence(displayName, term) ||
  matchesSequence(phone, term) ||
  regoMatch
)
```

**6. Add auto-fill logic to select handler**:
Replace the inline `onClick` with a `handleSelect` function:
```typescript
const handleSelect = (c: Customer) => {
  onSelect(c)
  setQuery(`${c.first_name} ${c.last_name}`)
  setShowDropdown(false)
  
  // Auto-select first linked vehicle if available
  if (onVehicleAutoSelect && c.linked_vehicles && c.linked_vehicles.length > 0) {
    onVehicleAutoSelect(c.linked_vehicles[0])
  }
}
```

**7. Wire `onVehicleAutoSelect` at render site** (~line 1112):
```typescript
<CustomerSearch
  selectedCustomer={customer}
  onSelect={setCustomer}
  onVehicleAutoSelect={(v) => {
    if (!vehicle) {
      setVehicle({ id: v.id, rego: v.rego, make: v.make || '', model: v.model || '', year: v.year, colour: v.colour || '' })
      setVehicleRego(v.rego)
    }
  }}
  error={errors.customer}
/>
```

**8. Guard condition**: The `onVehicleAutoSelect` callback only sets vehicle state if `!vehicle` (no vehicle currently selected), preventing overwrite of an existing selection.

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm the root cause analysis by observing that selecting a customer with linked vehicles does not trigger vehicle auto-fill.

**Test Plan**: Write component tests that render QuoteCreate's CustomerSearch, mock the `/customers` API to return customers with `linked_vehicles`, simulate selecting a customer, and assert that `onVehicleAutoSelect` is NOT called (confirming the bug exists on unfixed code).

**Test Cases**:
1. **Customer with vehicles selected, no current vehicle**: Simulate selecting a customer with linked_vehicles — assert vehicle field remains empty (will fail on unfixed code because callback doesn't exist)
2. **API response without include_vehicles**: Verify the API call does NOT include `include_vehicles: true` param (confirms missing param on unfixed code)
3. **Rego search not matching**: Search by a vehicle rego — assert no results returned (confirms missing rego filter on unfixed code)

**Expected Counterexamples**:
- `onVehicleAutoSelect` prop does not exist on the component, so no vehicle auto-fill occurs
- API response lacks `linked_vehicles` field because `include_vehicles: true` is not sent
- Rego-based search returns no matches because filter only checks name/phone

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := CustomerSearch_fixed.handleSelect(input.customer)
  ASSERT onVehicleAutoSelect WAS CALLED WITH input.customer.linked_vehicles[0]
  ASSERT vehicle.id = input.customer.linked_vehicles[0].id
  ASSERT vehicle.rego = input.customer.linked_vehicles[0].rego
  ASSERT vehicleRego = input.customer.linked_vehicles[0].rego
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT CustomerSearch_original(input) = CustomerSearch_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many customer configurations (with/without vehicles, various name patterns)
- It catches edge cases in the fuzzy matching filter
- It provides strong guarantees that non-buggy inputs behave identically

**Test Plan**: Observe behavior on UNFIXED code for customers without linked vehicles and for selections when a vehicle is already set, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Customer without vehicles preservation**: Verify selecting a customer with no linked_vehicles does not modify vehicle state — same behavior before and after fix
2. **Existing vehicle preservation**: Verify selecting a customer with linked_vehicles when a vehicle is already set does NOT overwrite the vehicle — guard condition works
3. **Search filter preservation**: Verify fuzzy matching on name/phone continues to work identically for all non-rego search terms
4. **Create customer preservation**: Verify "+ Add New Customer" flow remains unchanged
5. **Clear customer preservation**: Verify clearing customer does not affect vehicle state

### Unit Tests

- Test that `CustomerSearch` calls `onVehicleAutoSelect` with first linked vehicle when customer has vehicles and no vehicle is set
- Test that `CustomerSearch` does NOT call `onVehicleAutoSelect` when customer has no linked vehicles
- Test that the guard in the render-site callback prevents overwriting existing vehicle
- Test that `include_vehicles: true` is passed in the API params
- Test that rego matching works in the client-side filter

### Property-Based Tests

- Generate random customer objects (with/without linked_vehicles, varying vehicle counts) and verify auto-fill only triggers when vehicles exist and no vehicle is set
- Generate random search terms and verify the filter produces correct results including rego matching
- Generate random form states (vehicle set/unset) and verify the guard condition correctly prevents/allows auto-fill

### Integration Tests

- Test full QuoteCreate flow: select customer with vehicle → verify vehicle field populates
- Test QuoteCreate flow: select customer with vehicle when vehicle already set → verify no overwrite
- Test QuoteCreate flow: search by rego → verify customer with matching vehicle rego appears in results
- Test that VehicleLiveSearch vehicle→customer backfill still works after the fix
