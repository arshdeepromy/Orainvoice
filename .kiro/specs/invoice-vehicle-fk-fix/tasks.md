# Invoice Vehicle FK Fix — Implementation Tasks

## Overview

Fix the `ForeignKeyViolationError` crash when creating invoices with org-scoped vehicles, and the silent metadata update skip in `update_invoice()`. The fix introduces a vehicle-type resolution step that checks `global_vehicles` first, then `org_vehicles`, and routes linking/metadata logic to the correct table.

**Test file**: `tests/test_invoice_vehicle_fk_exploration.py` (exploration), `tests/test_invoice_vehicle_fk_preservation.py` (preservation)
**Run tests**: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python -m pytest tests/test_invoice_vehicle_fk_exploration.py tests/test_invoice_vehicle_fk_preservation.py -x -v`

---

## Tasks

### Exploration & Preservation Tests

- [x] 1. Write bug condition exploration test (BEFORE implementing fix)
  - **Property 1: Bug Condition** - Org Vehicle FK Violation on Invoice Creation
  - **IMPORTANT**: Write this property-based test BEFORE implementing the fix
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists in `create_invoice()` and `update_invoice()`
  - **Scoped PBT Approach**: Scope the property to concrete failing cases — vehicle IDs that exist in `org_vehicles` but NOT in `global_vehicles`
  - **Test file**: `tests/test_invoice_vehicle_fk_exploration.py`
  - Test 1a — Create invoice with org vehicle: Set up an org, customer, and `OrgVehicle` record (no matching `GlobalVehicle`). Call `create_invoice()` with `global_vehicle_id` set to the org vehicle's UUID. Assert the invoice is created successfully (no crash) and the `CustomerVehicle` link uses `org_vehicle_id` (not `global_vehicle_id`). On UNFIXED code this will raise `ForeignKeyViolationError` — confirming the bug (from Bug Condition in design: `isBugCondition(input)` where `input.global_vehicle_id NOT IN global_vehicles.id AND input.global_vehicle_id IN org_vehicles.id`)
  - Test 1b — Create invoice with org vehicle + service due date: Same setup as 1a but also pass `vehicle_service_due_date`. Assert the `OrgVehicle.service_due_date` is updated. On UNFIXED code the `GlobalVehicle` query returns `None` and the update is silently skipped
  - Test 1c — Create invoice with org vehicle + WOF expiry: Same setup but pass `vehicle_wof_expiry_date`. Assert `OrgVehicle.wof_expiry` is updated. On UNFIXED code the update is silently skipped
  - Test 1d — Create invoice with org vehicle + odometer: Same setup but pass `vehicle_odometer`. Assert odometer is recorded on `OrgVehicle.odometer_last_recorded` (not via `record_odometer_reading` which only supports global vehicles). On UNFIXED code this either crashes or silently skips
  - Test 1e — Update invoice with org vehicle + metadata: Create a draft invoice, then call `update_invoice()` with org vehicle ID and `vehicle_service_due_date` / `vehicle_wof_expiry_date`. Assert `OrgVehicle` metadata is updated. On UNFIXED code the `GlobalVehicle` query returns `None` and updates are skipped
  - Test 1f — Duplicate link detection for org vehicles: Create an invoice with an org vehicle (after fix), then create a second invoice with the same org vehicle and customer. Assert no duplicate `CustomerVehicle` link is created. On UNFIXED code the duplicate check queries `global_vehicle_id` column which never matches org vehicle links
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests FAIL (this is correct — it proves the bug exists)
  - Document counterexamples found: `ForeignKeyViolationError` on `customer_vehicles` insert, silent metadata skip for org vehicles
  - Mark task complete when tests are written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Global Vehicle and No-Vehicle Behavior Unchanged
  - **IMPORTANT**: Follow observation-first methodology — observe behavior on UNFIXED code first
  - **Test file**: `tests/test_invoice_vehicle_fk_preservation.py`
  - Observe: `create_invoice()` with a `global_vehicle_id` that exists in `global_vehicles` creates a `CustomerVehicle` with `global_vehicle_id` set — this must remain unchanged
  - Observe: `create_invoice()` with a global vehicle and existing `CustomerVehicle` link skips creating a duplicate — this must remain unchanged
  - Observe: `create_invoice()` with a global vehicle and `vehicle_odometer` calls `record_odometer_reading()` — this must remain unchanged
  - Observe: `create_invoice()` with a global vehicle and `vehicle_service_due_date` updates `GlobalVehicle.service_due_date` — this must remain unchanged
  - Observe: `create_invoice()` with a global vehicle and `vehicle_wof_expiry_date` updates `GlobalVehicle.wof_expiry` — this must remain unchanged
  - Observe: `create_invoice()` with `global_vehicle_id=None` skips auto-link logic entirely — this must remain unchanged
  - Observe: `update_invoice()` with a global vehicle ID updates `GlobalVehicle` metadata — this must remain unchanged
  - Write property-based tests: for all inputs where `global_vehicle_id` exists in `global_vehicles` OR is `None`, the fixed function produces the same result as the original
  - Property-based testing generates many test cases for stronger preservation guarantees across the non-buggy input domain
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: All tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

### Implementation

- [x] 3. Add vehicle-type resolution helper function

  - [x] 3.1 Create `resolve_vehicle_type()` async helper in `app/modules/invoices/service.py`
    - Signature: `async def _resolve_vehicle_type(db: AsyncSession, vehicle_id: uuid.UUID, org_id: uuid.UUID) -> tuple[str, Any] | None`
    - Returns `("global", vehicle_record)` if found in `global_vehicles`, `("org", vehicle_record)` if found in `org_vehicles` (scoped to `org_id`), or `None` if not found in either
    - Query `GlobalVehicle` first (by `id`), then `OrgVehicle` (by `id` AND `org_id`)
    - Place the helper near the top of the file with other private helpers
    - _Requirements: 2.1_

- [x] 4. Fix `create_invoice()` auto-link logic

  - [x] 4.1 Add vehicle-type resolution call in `create_invoice()`
    - Before the auto-link block (~line 679), call `_resolve_vehicle_type(db, global_vehicle_id, org_id)` when `global_vehicle_id` is provided
    - Store result as `vehicle_type, vehicle_record = ...` (or handle `None` for unknown vehicle IDs)
    - _Bug_Condition: isBugCondition(input) where input.global_vehicle_id NOT IN global_vehicles.id AND input.global_vehicle_id IN org_vehicles.id_
    - _Requirements: 2.1_

  - [x] 4.2 Fix `CustomerVehicle` link creation to use correct FK column
    - When `vehicle_type == "global"`: set `global_vehicle_id=global_vehicle_id` (existing behavior)
    - When `vehicle_type == "org"`: set `org_vehicle_id=global_vehicle_id, global_vehicle_id=None`
    - This satisfies the `vehicle_link_check` CHECK constraint on `customer_vehicles`
    - _Bug_Condition: isBugCondition(input) where vehicle is org-scoped_
    - _Expected_Behavior: CustomerVehicle.org_vehicle_id = vehicle_id, CustomerVehicle.global_vehicle_id IS NULL_
    - _Requirements: 2.1, 2.2_

  - [x] 4.3 Fix duplicate-link detection query
    - When `vehicle_type == "global"`: filter on `CustomerVehicle.global_vehicle_id == global_vehicle_id` (existing behavior)
    - When `vehicle_type == "org"`: filter on `CustomerVehicle.org_vehicle_id == global_vehicle_id`
    - This prevents duplicate links for org vehicles (existing query only checks `global_vehicle_id` column)
    - _Requirements: 2.2_

  - [x] 4.4 Fix audit log for org vehicle links
    - When linking an org vehicle, include `org_vehicle_id` (not `global_vehicle_id`) in the `after_value` dict
    - _Requirements: 2.2_

  - [x] 4.5 Fix odometer recording for org vehicles
    - When `vehicle_type == "org"` and `vehicle_odometer` is provided: update `OrgVehicle.odometer_last_recorded` directly instead of calling `record_odometer_reading()` (which only supports global vehicles via `odometer_readings` table FK)
    - When `vehicle_type == "global"`: keep existing `record_odometer_reading()` call unchanged
    - _Preservation: Global vehicle odometer recording unchanged (Req 3.3)_
    - _Requirements: 2.1, 2.2_

  - [x] 4.6 Fix `service_due_date` update in `create_invoice()` for org vehicles
    - When `vehicle_type == "org"` and `vehicle_service_due_date` is provided: update `OrgVehicle.service_due_date` on the already-resolved `vehicle_record`
    - When `vehicle_type == "global"`: keep existing `GlobalVehicle` query and update unchanged
    - _Preservation: Global vehicle service_due_date update unchanged (Req 3.4)_
    - _Requirements: 2.4_

  - [x] 4.7 Fix `wof_expiry` update in `create_invoice()` for org vehicles
    - When `vehicle_type == "org"` and `vehicle_wof_expiry_date` is provided: update `OrgVehicle.wof_expiry` on the already-resolved `vehicle_record`
    - When `vehicle_type == "global"`: keep existing `GlobalVehicle` query and update unchanged
    - _Preservation: Global vehicle WOF expiry update unchanged (Req 3.5)_
    - _Requirements: 2.4_

- [x] 5. Fix `update_invoice()` metadata updates

  - [x] 5.1 Add vehicle-type resolution in `update_invoice()`
    - Before the metadata update block (~line 1979), call `_resolve_vehicle_type(db, global_vehicle_id, org_id)` when `global_vehicle_id` is provided
    - _Requirements: 2.4_

  - [x] 5.2 Fix `service_due_date` update in `update_invoice()` for org vehicles
    - When `vehicle_type == "org"`: update `OrgVehicle.service_due_date` instead of querying `GlobalVehicle`
    - When `vehicle_type == "global"`: keep existing `GlobalVehicle` query and update unchanged
    - _Preservation: Global vehicle metadata update in update_invoice unchanged (Req 3.7)_
    - _Requirements: 2.4_

  - [x] 5.3 Fix `wof_expiry` update in `update_invoice()` for org vehicles
    - When `vehicle_type == "org"`: update `OrgVehicle.wof_expiry` instead of querying `GlobalVehicle`
    - When `vehicle_type == "global"`: keep existing `GlobalVehicle` query and update unchanged
    - _Preservation: Global vehicle WOF update in update_invoice unchanged (Req 3.7)_
    - _Requirements: 2.4_

### Verify Fix

- [x] 6. Verify exploration and preservation tests pass after fix

  - [x] 6.1 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Org Vehicle Linking Uses Correct FK Column
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - The tests from task 1 encode the expected behavior — when they pass, the fix is confirmed
    - Run: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python -m pytest tests/test_invoice_vehicle_fk_exploration.py -x -v`
    - **EXPECTED OUTCOME**: All tests PASS (confirms bug is fixed for all bug condition cases)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 6.2 Verify preservation tests still pass
    - **Property 2: Preservation** - Global Vehicle and No-Vehicle Behavior Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python -m pytest tests/test_invoice_vehicle_fk_preservation.py -x -v`
    - **EXPECTED OUTCOME**: All tests PASS (confirms no regressions)
    - Confirm: global vehicle auto-link unchanged (Req 3.1)
    - Confirm: duplicate link prevention for global vehicles unchanged (Req 3.2)
    - Confirm: global vehicle odometer recording unchanged (Req 3.3)
    - Confirm: global vehicle service_due_date update unchanged (Req 3.4)
    - Confirm: global vehicle WOF expiry update unchanged (Req 3.5)
    - Confirm: no-vehicle invoice creation unchanged (Req 3.6)
    - Confirm: update_invoice global vehicle metadata unchanged (Req 3.7)

- [x] 7. Checkpoint — Ensure all tests pass
  - Run both test files together: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python -m pytest tests/test_invoice_vehicle_fk_exploration.py tests/test_invoice_vehicle_fk_preservation.py -x -v`
  - Verify all exploration tests PASS (bug is fixed)
  - Verify all preservation tests PASS (no regressions)
  - Run existing invoice test suite to check for broader regressions: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python -m pytest tests/test_invoices.py tests/test_invoice_lifecycle.py -x -v`
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

### Files Changed Summary

| File | Changes |
|------|---------|
| `app/modules/invoices/service.py` | Add `_resolve_vehicle_type()` helper; fix `create_invoice()` auto-link, duplicate check, audit log, odometer, service_due_date, wof_expiry; fix `update_invoice()` service_due_date, wof_expiry |
| `tests/test_invoice_vehicle_fk_exploration.py` | Bug condition exploration tests (6 test cases) |
| `tests/test_invoice_vehicle_fk_preservation.py` | Preservation property tests (7 test cases) |

### Risk Assessment

| Change | Risk | Mitigation |
|--------|------|------------|
| Vehicle-type resolution helper | Low | Pure query function, no side effects; returns `None` for unknown IDs |
| CustomerVehicle FK column routing | Low | Directly addresses the CHECK constraint; both columns already exist on the model |
| Duplicate-link detection fix | Low | Adds an OR branch to the existing query; global vehicle path unchanged |
| Odometer recording for org vehicles | Low | Updates `OrgVehicle.odometer_last_recorded` directly; skips `record_odometer_reading()` which has FK to `global_vehicles` |
| Metadata update routing | Low | Adds conditional branch; global vehicle path unchanged |
| `update_invoice()` metadata fix | Low | Same pattern as `create_invoice()` fix; isolated to metadata block |

### Implementation Order

1. **Exploration tests** (Task 1) — confirm bug exists on unfixed code (tests FAIL)
2. **Preservation tests** (Task 2) — capture baseline behavior on unfixed code (tests PASS)
3. **Resolution helper** (Task 3) — add `_resolve_vehicle_type()` function
4. **Fix create_invoice()** (Task 4) — auto-link, duplicate check, audit, odometer, metadata
5. **Fix update_invoice()** (Task 5) — metadata updates for org vehicles
6. **Verify fix** (Task 6) — exploration tests PASS, preservation tests still PASS
7. **Checkpoint** (Task 7) — full test suite green
