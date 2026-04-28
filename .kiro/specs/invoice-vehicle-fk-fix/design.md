# Invoice Vehicle FK Fix — Bugfix Design

## Overview

The `create_invoice()` function in `app/modules/invoices/service.py` crashes with a `ForeignKeyViolationError` when creating an invoice for a customer with a manually-entered org-scoped vehicle. The frontend sends the vehicle ID as `global_vehicle_id` regardless of whether the vehicle is a global (CarJam) or org-scoped (manual) vehicle. The auto-link logic blindly inserts this ID into the `global_vehicle_id` column of `customer_vehicles`, which violates the FK constraint when the ID belongs to an `org_vehicles` record.

The fix introduces a vehicle-type resolution step: before linking or updating metadata, the code checks `global_vehicles` first, then `org_vehicles`, and uses the correct column/table accordingly. The same pattern applies to `update_invoice()` where vehicle metadata updates (service due date, WOF expiry) only query `global_vehicles`.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — when the provided `global_vehicle_id` value actually belongs to an `org_vehicles` record (not present in `global_vehicles`)
- **Property (P)**: The desired behavior — the system resolves the vehicle type and uses `org_vehicle_id` on `customer_vehicles`, and updates `org_vehicles` for metadata
- **Preservation**: Existing global-vehicle linking, odometer recording, and metadata updates must remain unchanged
- **`global_vehicles`**: CarJam API lookup results — shared across all organisations, keyed by rego
- **`org_vehicles`**: Manually-entered vehicle records scoped to a single organisation
- **`customer_vehicles`**: Link table connecting customers to vehicles; has a CHECK constraint requiring exactly one of `global_vehicle_id` or `org_vehicle_id` to be set
- **`create_invoice()`**: Function in `app/modules/invoices/service.py` (~line 380) that creates invoices and auto-links customer-vehicle relationships
- **`update_invoice()`**: Function in `app/modules/invoices/service.py` (~line 1800) that updates draft invoices and syncs vehicle metadata

## Bug Details

### Bug Condition

The bug manifests when a user creates (or updates) an invoice with a vehicle ID that exists in `org_vehicles` but NOT in `global_vehicles`. The frontend always sends this ID as `global_vehicle_id`. The `create_invoice()` function then:
1. Inserts a `CustomerVehicle` row with `global_vehicle_id` set to the org vehicle's UUID
2. PostgreSQL rejects this because `global_vehicle_id` has a FK to `global_vehicles.id` and no matching row exists
3. The transaction fails with `ForeignKeyViolationError`, returning a 503 to the user

In `update_invoice()`, the metadata update logic queries `GlobalVehicle` by the provided ID. When the ID belongs to an org vehicle, the query returns `None` and the metadata update is silently skipped.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type InvoiceCreateInput or InvoiceUpdateInput
  OUTPUT: boolean
  
  RETURN input.global_vehicle_id IS NOT NULL
         AND input.global_vehicle_id NOT IN global_vehicles.id
         AND input.global_vehicle_id IN org_vehicles.id
END FUNCTION
```

### Examples

- **Create invoice with org vehicle → crash**: User creates an invoice for customer "John" with vehicle ID `abc-123` (exists in `org_vehicles`, not in `global_vehicles`). Expected: invoice created, customer linked via `org_vehicle_id`. Actual: `ForeignKeyViolationError`, 503 response.
- **Create invoice with org vehicle → duplicate link check fails**: Even if the link check were to pass, the existing query checks `CustomerVehicle.global_vehicle_id == vehicle_id`, which would never match an org vehicle link (where `org_vehicle_id` is set instead), potentially creating duplicate links.
- **Update invoice with org vehicle + service due date → silently skipped**: User updates a draft invoice with org vehicle ID `abc-123` and sets `vehicle_service_due_date` to `2025-06-01`. Expected: `org_vehicles.service_due_date` updated. Actual: `GlobalVehicle` query returns `None`, update skipped.
- **Update invoice with org vehicle + WOF expiry → silently skipped**: Same pattern as above for `vehicle_wof_expiry_date`.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Creating an invoice with a vehicle ID that exists in `global_vehicles` must continue to auto-link using `global_vehicle_id` in `customer_vehicles`
- Duplicate link detection for global vehicles must continue to work (skip if link already exists)
- Odometer recording via `record_odometer_reading()` must continue to work for global vehicles
- Service due date and WOF expiry updates on `global_vehicles` must continue to work when the vehicle is global
- Creating an invoice without any vehicle ID must continue to skip auto-link logic entirely
- `update_invoice()` with a global vehicle ID must continue to update `global_vehicles` metadata

**Scope:**
All inputs where `global_vehicle_id` is `None` OR where `global_vehicle_id` exists in `global_vehicles` should be completely unaffected by this fix. This includes:
- Invoices created without a vehicle
- Invoices created with a CarJam-sourced global vehicle
- Invoice updates with global vehicle metadata changes
- All non-vehicle-related invoice operations (line items, totals, notes, status transitions)

## Hypothesized Root Cause

Based on the code analysis, the root causes are:

1. **Hardcoded FK column in auto-link logic** (lines 679–716 of `service.py`): The `create_invoice()` function always sets `global_vehicle_id` on the `CustomerVehicle` record without checking whether the ID actually belongs to `global_vehicles` or `org_vehicles`. The customer service's `link_vehicle_to_customer()` function already handles both cases correctly — the invoice service does not.

2. **Hardcoded duplicate-link check**: The existing link query filters on `CustomerVehicle.global_vehicle_id == global_vehicle_id`. For org vehicles, the link would be stored under `org_vehicle_id`, so this check would never find an existing org-vehicle link, potentially creating duplicates even after the FK fix.

3. **Hardcoded GlobalVehicle query in metadata updates** (lines 1979–2000 of `service.py`): Both `create_invoice()` and `update_invoice()` query only `GlobalVehicle` when updating `service_due_date` and `wof_expiry`. For org vehicles, these queries return `None` and the update is silently skipped.

4. **Odometer recording only supports global vehicles**: The `record_odometer_reading()` function and the `odometer_readings` table both reference `global_vehicle_id` only. For org vehicles, odometer recording should be skipped gracefully (org vehicles have their own `odometer_last_recorded` column but no history table).

## Correctness Properties

Property 1: Bug Condition - Org Vehicle Linking Uses Correct FK Column

_For any_ invoice creation input where the provided vehicle ID exists in `org_vehicles` but NOT in `global_vehicles` (isBugCondition returns true), the fixed `create_invoice()` function SHALL create the `CustomerVehicle` link with `org_vehicle_id` set to the vehicle ID and `global_vehicle_id` set to NULL, and the invoice SHALL be created successfully without a `ForeignKeyViolationError`.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Bug Condition - Org Vehicle Metadata Updates

_For any_ invoice create or update input where the provided vehicle ID exists in `org_vehicles` but NOT in `global_vehicles` and a `vehicle_service_due_date` or `vehicle_wof_expiry_date` is provided, the fixed function SHALL update the corresponding fields on the `org_vehicles` record instead of silently skipping the update.

**Validates: Requirements 2.4**

Property 3: Preservation - Global Vehicle Linking Unchanged

_For any_ invoice creation input where the provided vehicle ID exists in `global_vehicles` (isBugCondition returns false), the fixed `create_invoice()` function SHALL produce the same `CustomerVehicle` link (with `global_vehicle_id` set) and the same metadata updates as the original function, preserving all existing global vehicle behavior.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.7**

Property 4: Preservation - No Vehicle Skips Linking

_For any_ invoice creation input where `global_vehicle_id` is NULL, the fixed function SHALL skip the auto-link logic entirely, producing the same result as the original function.

**Validates: Requirements 3.6**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `app/modules/invoices/service.py`

**Function**: `create_invoice()` — auto-link logic (~lines 679–716)

**Specific Changes**:

1. **Add vehicle-type resolution helper**: Before the auto-link block, query `global_vehicles` for the provided ID. If not found, query `org_vehicles` (scoped to `org_id`). Store the result as `is_global_vehicle: bool` and the resolved vehicle record.

2. **Fix CustomerVehicle link creation**: Use `global_vehicle_id=vehicle_id` when the vehicle is global, or `org_vehicle_id=vehicle_id` when it's an org vehicle. This satisfies the CHECK constraint.

3. **Fix duplicate-link detection**: When checking for an existing link, query by `global_vehicle_id` for global vehicles or `org_vehicle_id` for org vehicles.

4. **Fix audit log**: Include `org_vehicle_id` in the audit log `after_value` when linking an org vehicle.

5. **Skip odometer recording for org vehicles**: The `record_odometer_reading()` function and `odometer_readings` table only support global vehicles. For org vehicles, update `org_vehicles.odometer_last_recorded` directly instead.

6. **Fix service_due_date update**: When the vehicle is an org vehicle, query and update `OrgVehicle` instead of `GlobalVehicle`.

7. **Fix wof_expiry update**: Same as above — query and update `OrgVehicle` for org vehicles.

**Function**: `update_invoice()` — metadata update logic (~lines 1979–2000)

**Specific Changes**:

8. **Add vehicle-type resolution**: Same pattern as `create_invoice()` — resolve whether the vehicle ID is global or org before updating metadata.

9. **Fix service_due_date update in update_invoice()**: Query `OrgVehicle` when the vehicle is org-scoped.

10. **Fix wof_expiry update in update_invoice()**: Query `OrgVehicle` when the vehicle is org-scoped.

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that call `create_invoice()` with a vehicle ID that exists only in `org_vehicles` and assert the operation succeeds. Run these tests on the UNFIXED code to observe the `ForeignKeyViolationError`.

**Test Cases**:
1. **Create invoice with org vehicle**: Call `create_invoice()` with a vehicle ID from `org_vehicles` — expect `ForeignKeyViolationError` on unfixed code
2. **Create invoice with org vehicle + service due date**: Same as above but with `vehicle_service_due_date` set — expect the metadata update to be silently skipped on unfixed code
3. **Update invoice with org vehicle + WOF expiry**: Call `update_invoice()` with an org vehicle ID and `vehicle_wof_expiry_date` — expect the WOF update to be skipped on unfixed code
4. **Create invoice with org vehicle + odometer**: Call `create_invoice()` with an org vehicle ID and `vehicle_odometer` — expect either crash or silent skip on unfixed code

**Expected Counterexamples**:
- `ForeignKeyViolationError` when inserting `CustomerVehicle` with org vehicle ID in `global_vehicle_id` column
- Possible causes: hardcoded `global_vehicle_id` column in auto-link logic, no vehicle-type resolution

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := create_invoice_fixed(input)
  ASSERT no_crash(result)
  ASSERT result.status_code = 201
  link := get_customer_vehicle_link(input.customer_id, input.global_vehicle_id)
  ASSERT link.org_vehicle_id = input.global_vehicle_id
  ASSERT link.global_vehicle_id IS NULL
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT create_invoice_original(input) = create_invoice_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for global vehicle inputs and no-vehicle inputs, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Global vehicle link preservation**: Verify creating an invoice with a global vehicle ID still creates a `CustomerVehicle` with `global_vehicle_id` set
2. **Global vehicle metadata preservation**: Verify service_due_date and wof_expiry updates still apply to `global_vehicles` for global vehicle IDs
3. **No vehicle preservation**: Verify creating an invoice without a vehicle ID still skips auto-link logic
4. **Duplicate link prevention preservation**: Verify that an existing global vehicle link is not duplicated

### Unit Tests

- Test vehicle-type resolution: given a global vehicle ID, returns `is_global=True`; given an org vehicle ID, returns `is_global=False`; given a nonexistent ID, returns `None`
- Test `CustomerVehicle` creation with org vehicle ID uses `org_vehicle_id` column
- Test `CustomerVehicle` creation with global vehicle ID uses `global_vehicle_id` column
- Test duplicate-link detection works for both global and org vehicle links
- Test metadata updates route to `OrgVehicle` for org vehicles and `GlobalVehicle` for global vehicles
- Test odometer recording is skipped for org vehicles (updates `org_vehicles.odometer_last_recorded` directly)

### Property-Based Tests

- Generate random vehicle IDs (some global, some org) and verify the correct FK column is always used on `CustomerVehicle`
- Generate random combinations of vehicle type × metadata fields and verify the correct table is updated
- Generate invoice inputs with no vehicle ID and verify auto-link is always skipped

### Integration Tests

- Full `create_invoice()` flow with an org vehicle: verify invoice created, customer linked via `org_vehicle_id`, metadata updated on `org_vehicles`
- Full `create_invoice()` flow with a global vehicle: verify existing behavior unchanged
- Full `update_invoice()` flow with an org vehicle and metadata: verify `org_vehicles` record updated
- Full `update_invoice()` flow with a global vehicle and metadata: verify `global_vehicles` record updated
