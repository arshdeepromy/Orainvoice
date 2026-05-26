# Implementation Plan: Vehicle Data Isolation

## Overview

This plan implements the per-organisation vehicle isolation fix as a backend-only behavioural change. No tables, columns, indexes, or migrations are introduced. The order is: build the three new helpers in `app/modules/vehicles/service.py` (with unit tests under the same parent); then redirect each enumerated promotion trigger site one file at a time (with its integration test); then fix the read-fallback consumers — including the rego-keyed invoice display reads, the inner-join reminder services, the data-export inner join, and the link-existence checks at every link-creation site — and rewire the CarJam-refresh routes so promoted orgs keep seeing fresh data (Tasks 11–12); then layer in the cross-cutting tests (read-fallback, concurrency, backwards-compatibility); then the OWASP end-to-end script; then the version bump and CHANGELOG entry; and finally a `git push` of all changes to the working branch on origin (no production deployment is performed by these tasks). Seven pre-existing bugs uncovered during audit (fleet portal odometer field-name mismatch; missing `cof_expiry` schema field + branch in `update_invoice`; missing `cof_expiry` branch in `update_customer_vehicle_dates`; dashboard expiry-widget querying a non-existent column; invoice display reading `global_vehicles` first instead of org-scoped `org_vehicles`; notification/reminder services using inner joins that drop promoted links; data-export CSV inner join that drops promoted links) are fixed inside Tasks 6.1, 4.3, 10.1, 11.3, 11.5, 11.6, and 11.4 respectively. In addition, Task 11.7 widens the `customer_vehicles` link-existence checks at every link-creation site to prevent duplicate links being silently created on the second touch of a promoted vehicle. Each task carries an explicit `Verify:` line per `implementation-completeness-checklist.md` Rule 9.

The implementation language is **Python** (existing FastAPI service layer) — no language selection is needed, the design uses concrete Python signatures throughout.

## Tasks

### Implementation Note — Local Variable Rebinding After Promotion

Many tasks below call `promote_vehicle()` and then perform follow-up writes (field assignment, link creation, link-existence checks). After `promote_vehicle()` returns the new `OrgVehicle`, every local variable that referenced the pre-promotion `GlobalVehicle` must be rebound, **before** any subsequent write or check, to point at the new `OrgVehicle`. The canonical pattern is:

```python
ov = await promote_vehicle(db, org_id=..., global_vehicle_id=gv.id, source_record=gv, ...)
# Rebind so subsequent code sees the post-promotion identity
vehicle_record = ov
vehicle_type = "org"
effective_vehicle_id = ov.id   # if any later code referenced the original gv id
```

Failure to rebind silently regresses isolation — subsequent `vehicle_record.<field> = value` writes still target the `GlobalVehicle` because `vehicle_record` was never reassigned. The integration tests for each trigger site assert post-write that `global_vehicles.<field>` is byte-identical to its pre-call value, so the regression would be caught — but reviewers should still verify the rebind is present in every promotion-and-write block.

- [x] 1. Add the three new vehicle service helpers
  - [x] 1.1 Implement `promote_vehicle()` in `app/modules/vehicles/service.py`
    - Add as a module-level async function near the existing `link_vehicle_to_customer`
    - Take the advisory lock first: `SELECT pg_advisory_xact_lock(hashtext(:org_id_str)::int, hashtext(:rego)::int)`. **Critical bind-param note**: pass `org_id_str=str(org_id)` (a Python `str`), NOT a raw `uuid.UUID` object. asyncpg silently sends a UUID-typed parameter, but PostgreSQL has no `hashtext(uuid)` overload and the call would raise `function hashtext(uuid) does not exist`. The same applies to `rego` which must already be a string at the call site
    - Then `SELECT FROM org_vehicles WHERE org_id=:org AND rego=:rego` (re-check inside the lock); return existing row if found
    - Otherwise INSERT a new `org_vehicles` row copying every CarJam_Owned_Spec_Field and every Customer_Driven_Field from the source `global_vehicles` row, with `is_manual_entry=False`
    - `await db.flush()` then `await db.refresh(new_ov)` before returning
    - Defence-in-depth module gate: `if not await ModuleService(db).is_enabled(str(org_id), "vehicles"): raise PermissionError(...)`. **`is_enabled` is async — the call must be awaited**. The function is at `app/core/modules.py:206` and accepts `(org_id_str: str, module_slug: str)`
    - Emit `write_audit_log(action="vehicle.promote", entity_type="org_vehicle", entity_id=new.id, org_id=org_id, user_id=user_id, after_value={"rego": rego, "global_vehicle_id": str(gvid), "trigger_site": trigger_site})`. The `org_id` and `user_id` go on the audit-log row as **top-level columns** (matching the `write_audit_log` signature in `app/core/audit.py:35`), NOT inside the `after_value` JSON payload
    - Signature exactly per design "New Helper Functions" → `promote_vehicle()`
    - _Requirements: 2.1, 2.5, 8.5, 12.4, 13.1, 13.2, 14.1, 14.3_
    - _Design: New Helper Functions → `promote_vehicle()`; Concurrency and Idempotency Strategy; Module Gating_
    - **Verify**: `pytest -q tests/test_vehicle_data_isolation.py::test_promote_vehicle_creates_org_row_when_missing` passes; the inserted `org_vehicles` row has `is_manual_entry=False` and every CarJam-owned + customer-driven field copied from `global_vehicles`. **Additional bind-param regression**: a separate test calls `promote_vehicle` and asserts no `function hashtext(uuid) does not exist` is raised — proving `org_id_str=str(org_id)` was used.

  - [x] 1.2 Implement `migrate_link_to_org_vehicle()` in `app/modules/vehicles/service.py`
    - Single `UPDATE customer_vehicles SET global_vehicle_id=NULL, org_vehicle_id=:ov WHERE id=:cv_id` so `vehicle_link_check` is never violated mid-statement
    - `await db.flush()` after the update
    - _Requirements: 2.3, 2.4, 8.5_
    - _Design: New Helper Functions → `migrate_link_to_org_vehicle()`_
    - **Verify**: `pytest -q tests/test_vehicle_data_isolation.py::test_migrate_link_to_org_vehicle_swaps_columns_atomically` passes; an attempted savepoint that splits the update into two separate writes triggers a `vehicle_link_check` constraint violation, proving the single-UPDATE atomicity is required.

  - [x] 1.3 Implement `manual_refresh_vehicle()` in `app/modules/vehicles/service.py`
    - Signature: `(db, *, org_id, rego, user_id, ip_address) -> OrgVehicle`
    - Load the existing `org_vehicles` row for `(org_id, rego)`; raise `LookupError` if it does not exist (this helper does not promote — it only refreshes already-promoted rows)
    - **Always trigger a CarJam refetch when `manual_refresh_vehicle` is called**, then update the `global_vehicles` row from the response. Rationale: the user explicitly clicked "Refresh from CarJam"; honouring that with a stale-cache short-circuit defeats the user's intent and complicates the design (no TTL constant exists in the spec or a shared config). This is simpler than the original Req 5.2 wording and matches user expectation. If CarJam returns a not-found or rate-limit error, propagate it as the existing 404 / 429 from `refresh_vehicle()` — do NOT silently fall back to the stale `global_vehicles` row. Note: this overrides the TTL conditional language in Req 5.2; Req 5.2's intent (refresh-on-stale) is preserved as a stronger always-refresh
    - Copy CarJam_Owned_Spec_Fields from the refreshed `global_vehicles` row into the existing `org_vehicles` row; do NOT touch `org_vehicles` Customer_Driven_Fields
    - Emit `write_audit_log(action="vehicle.manual_refresh", entity_type="org_vehicle", entity_id=ov.id, org_id=org_id, user_id=user_id, after_value={"rego": rego, "global_vehicle_id": str(gv.id)})`. As in Task 1.1, `org_id` and `user_id` are top-level columns on the audit row, not embedded in `after_value`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 14.2, 14.3_
    - _Design: New Helper Functions → `manual_refresh_vehicle()` (Code Changes per File → `app/modules/vehicles/service.py`)_
    - **Verify**: a new unit test asserts (a) CarJam-owned fields on the `OrgVehicle` were updated to match `global_vehicles`, (b) the four Customer_Driven_Fields on the `OrgVehicle` are byte-identical before vs after, (c) one `vehicle.manual_refresh` audit-log row exists with `org_id` and `user_id` populated as top-level columns. **Additional always-refresh test**: stub the CarJam client to record calls; invoke `manual_refresh_vehicle` and assert the CarJam client was called regardless of `global_vehicles.last_pulled_at` freshness.

  - [x] 1.4 Write unit tests for the three helpers in `tests/test_vehicle_data_isolation.py`
    - `test_promote_vehicle_creates_org_row_when_missing` — fresh promotion inserts row with copied fields, `is_manual_entry=False`
    - `test_promote_vehicle_idempotent_when_org_row_exists` — second invocation returns the same row, no extra audit log entry, no second INSERT
    - `test_promote_vehicle_finds_pre_existing_manual_entry_by_rego` — pre-create a manual-entry row, then promote with a `global_vehicles` source for the same rego; assert the existing manual-entry row is reused (not duplicated) per the "Critical edge case" in the design's Backwards Compatibility section
    - `test_promote_vehicle_emits_audit_log_with_trigger_site` — assert one row in `audit_log` with `action='vehicle.promote'` and `after_value['trigger_site']` equal to the value the caller passed
    - `test_promote_vehicle_raises_when_module_disabled` — disable `vehicles` module for the org; assert `PermissionError` is raised and no `org_vehicles` row is created
    - `test_migrate_link_to_org_vehicle_swaps_columns_atomically` — assert single UPDATE swaps both columns
    - `test_record_odometer_does_not_touch_global_vehicles` — capture `global_vehicles.odometer_last_recorded` before/after; assert unchanged
    - `test_update_odometer_reading_writes_to_global_vehicles_by_design` — locks in the documented carve-out from `design.md`. Pre-create a `global_vehicles` row and an `odometer_readings` row pointing at it; promote the vehicle for an org; record a second reading via `record_odometer_reading` (so the org's `org_vehicles.odometer_last_recorded` is set); call `update_odometer_reading` to correct the **first** historical reading; assert (a) `global_vehicles.odometer_last_recorded` is recomputed and **does** update (this is the carve-out), (b) the org's `org_vehicles.odometer_last_recorded` is **byte-identical** to its pre-call value (correction does not bleed into the org snapshot). The test docstring must cite `design.md` "Carve-out — `update_odometer_reading` writes to `global_vehicles.odometer_last_recorded`" so a future maintainer reviewing failures understands this is intentional, not a regression
    - _Requirements: 2.5, 13.1, 13.2, 13.3, 14.1, 14.3, 15.1_
    - _Design: Test Strategy → Unit Tests; Carve-out — `update_odometer_reading` writes to `global_vehicles.odometer_last_recorded`_
    - **Verify**: `pytest -q tests/test_vehicle_data_isolation.py` exits 0 with eight tests passed.

- [x] 2. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Redirect promotion trigger sites in `app/modules/vehicles/service.py`
  - [x] 3.1 Modify `record_odometer_reading()` to write the odometer cache to `org_vehicles`
    - When `org_id is not None` and `source != "carjam"`: after the history insert, call `promote_vehicle(db, org_id=..., global_vehicle_id=gv.id, source_record=gv, user_id=..., trigger_site="vehicles.record_odometer_reading", ip_address=...)` and bump `ov.odometer_last_recorded` instead of `gv.odometer_last_recorded`
    - When `org_id is None` or `source == "carjam"`: keep existing behaviour (CarJam-driven cache update on `global_vehicles`)
    - The history row itself still references `global_vehicle_id` (Req 11)
    - _Requirements: 1.1, 3.7, 11.1, 11.2, 11.3_
    - _Design: Code Changes per File → `app/modules/vehicles/service.py`; New Helper Functions → Refactored Signatures → `record_odometer_reading()`_
    - **Verify**: `pytest -q tests/test_vehicle_data_isolation.py::test_record_odometer_does_not_touch_global_vehicles` passes; `pytest -q tests/integration/test_vehicle_promotion_trigger_sites.py::test_vehicles_record_odometer_promotes_first_time` passes.

  - [x] 3.2 Modify `link_vehicle_to_customer()` to promote before linking
    - When the supplied `vehicle_id` resolves to a `GlobalVehicle`: call `promote_vehicle(...)` first with `trigger_site="vehicles.link"`, then construct the `CustomerVehicle` with `org_vehicle_id=ov.id, global_vehicle_id=None`
    - When it already resolves to an `OrgVehicle`: existing behaviour (no promotion needed)
    - Existing `vehicle.link_customer` audit-log payload unchanged
    - _Requirements: 2.3, 3.1, 14.1_
    - _Design: Code Changes per File → `app/modules/vehicles/service.py` (link_vehicle_to_customer)_
    - **Verify**: `pytest -q tests/integration/test_vehicle_promotion_trigger_sites.py::test_vehicles_link_to_customer_promotes_first_time` passes; the new `customer_vehicles` row has `org_vehicle_id` set and `global_vehicle_id` NULL.

  - [x] 3.3 Add integration tests for the vehicles-service trigger sites
    - `tests/integration/test_vehicle_promotion_trigger_sites.py::test_vehicles_link_to_customer_promotes_first_time`
    - `tests/integration/test_vehicle_promotion_trigger_sites.py::test_vehicles_record_odometer_promotes_first_time`
    - Each asserts: `org_vehicles` row created for the calling org; `customer_vehicles` link migrated to `org_vehicle_id` (where applicable); `global_vehicles` Customer_Driven_Fields unchanged; `org_vehicles` Customer_Driven_Fields hold the new value; one `vehicle.promote` audit-log row with the matching `trigger_site` string
    - _Requirements: 15.2_
    - _Design: Test Strategy → Integration Tests_
    - **Verify**: both tests pass and assert all five invariants from the design's Test Strategy section.

- [x] 4. Redirect promotion trigger sites in `app/modules/invoices/service.py`
  - [x] 4.0 Modify `_resolve_vehicle_type` (~L399-432) to prefer `OrgVehicle` by rego when the org is promoted
    - Currently the resolver does `select(GlobalVehicle).where(GlobalVehicle.id == vehicle_id)` first, then falls back to `OrgVehicle.id == vehicle_id`. After promotion, the caller still passes the **original `global_vehicles.id`** (the request payload's `global_vehicle_id`), so the resolver returns `("global", gv)` even though the org has been promoted — undoing isolation on every subsequent invoice for the same vehicle
    - Extension: when the resolver finds `("global", gv)`, perform a follow-up query `select(OrgVehicle).where(OrgVehicle.org_id == org_id, func.upper(OrgVehicle.rego) == func.upper(gv.rego)).limit(1)`. If a matching org row exists, return `("org", ov)` instead — the org has been promoted for this rego, and the org snapshot is the source of truth. If no org row exists, return `("global", gv)` as today
    - This change makes second-invoice writes hit the `("org", ov)` branch automatically without requiring callers to thread an `effective_vehicle_id` after promotion. Tasks 4.1, 4.2, 4.3 still need their local-variable rebinding for the **first** call that promotes; this task ensures **subsequent** calls don't need any rebinding because `_resolve_vehicle_type` returns the right type
    - _Requirements: 6.1, 6.2, 6.4, 9.6, 12.3_
    - _Design: Read Paths → `_resolve_vehicle_type`_
    - **Verify**: unit test `test_resolve_vehicle_type_returns_org_when_promoted` — pre-create a `global_vehicles` row, an `org_vehicles` row for the same rego scoped to org A; call `_resolve_vehicle_type(db, gv.id, org_a.id)`; assert the result is `("org", ov)` with `ov.id != gv.id`. Calling for org B (no promotion) returns `("global", gv)`.

  - [x] 4.1 Modify `create_invoice()` link-creation block (~L938-944)
    - When `_resolve_vehicle_type` returns `("global", gv)` and a `customer_vehicles` link is being created: call `promote_vehicle(..., trigger_site="invoices.create")`, then construct the `CustomerVehicle` with `org_vehicle_id=ov.id, global_vehicle_id=None`
    - **Local-variable rebinding** (per "Local Variable Rebinding After Promotion" note above): immediately after `promote_vehicle()` returns, set `vehicle_record = ov` and `vehicle_type = "org"`. Also bind `effective_vehicle_id = ov.id` and **use `effective_vehicle_id` (not the original `global_vehicle_id` parameter) in any link-existence query at L920-936 and any subsequent field write at L982+**. The original parameter `global_vehicle_id` is now logically a "vehicle identity prior to promotion" — leaving downstream queries pointing at the original gv id would silently break the link-existence check (Task 11.7) and the field writes (Task 4.2)
    - The downstream `if vehicle_type == "org"` branch then handles both pre-existing-org and just-promoted cases identically
    - _Requirements: 2.3, 3.2_
    - _Design: Code Changes per File → `app/modules/invoices/service.py` (create_invoice link block); Implementation Note — Local Variable Rebinding_
    - **Verify**: a new invoice for a `global_vehicles`-only rego now creates an `org_vehicles` row and links via `org_vehicle_id`; assertion lives in the integration test added in 4.4. **Additional rebind regression assertion**: the test asserts that after `create_invoice` returns, `global_vehicles.{wof_expiry, cof_expiry, service_due_date, odometer_last_recorded}` are byte-identical to pre-call values — proving no follow-up write accidentally hit the still-around `gv` reference.

  - [x] 4.2 Modify `create_invoice()` field-write block (~L982-1051)
    - For the **odometer field specifically**: keep using the unified `record_odometer_reading()` call (the function modified in Task 3.1 already handles promote + history insert + `org_vehicles.odometer_last_recorded` bump in one call). Do NOT replace this with a `promote_vehicle()` + direct `ov.odometer_last_recorded = value` pattern — that would skip the `odometer_readings` history insert and silently break odometer history growth. Concretely: keep the existing `await record_odometer_reading(db, global_vehicle_id=effective_global_vehicle_id, reading_km=vehicle_odometer, source="invoice", ...)` call shape (the helper still keys on `global_vehicle_id` per Req 11.1)
    - For the **other four Customer_Driven_Fields** (`service_due_date`, `wof_expiry`, `cof_expiry`, `inspection_type`): replace each `gv.<field> = value` write with: `promote_vehicle(..., trigger_site="invoices.create")` (idempotent — returns the existing `org_vehicles` row if 4.1 already promoted) then `ov.<field> = value`
    - If a `customer_vehicles` link still points at `global_vehicle_id` after promotion, call `migrate_link_to_org_vehicle(...)` within the same transaction. This case applies when the link was created earlier in the same transaction by a code path other than 4.1, or when the link pre-dates the call
    - Remove the four global-vehicle Customer_Driven_Field write paths (the existing `gv.wof_expiry = ...`, `gv.cof_expiry = ...`, `gv.service_due_date = ...`, and the inspection_type branch). Note: the global odometer write does NOT need explicit removal — `record_odometer_reading()` after Task 3.1 stops bumping `gv.odometer_last_recorded` from invoice-driven flows (`org_id != None` and `source != "carjam"`)
    - The `vehicle_display` snapshot in `invoice_data_json` now sources from the `OrgVehicle` after promotion; the snapshot field set is identical to today, so no Pydantic schema change
    - **Local-variable rebinding** (per the shared note above): if Task 4.1 already promoted in this same `create_invoice` call, `vehicle_record` is already `ov`; calling `promote_vehicle()` again here returns the same `ov` (idempotent) and the rebind is a no-op. The pattern still must be applied defensively — code paths that enter 4.2 from a different entry (e.g. `vehicle_type == "global"` discovered later in the function) must rebind before writing
    - _Requirements: 1.2, 1.5, 2.2, 2.4, 3.2, 9.1, 9.4, 9.5, 11.1_
    - _Design: Code Changes per File → `app/modules/invoices/service.py` (create_invoice field-write block); Implementation Note — Local Variable Rebinding_
    - **Verify**: integration test asserts `global_vehicles.{wof_expiry, cof_expiry, service_due_date, odometer_last_recorded}` are byte-identical before vs after the invoice create; the same fields on the new `org_vehicles` row hold the invoice payload's values. **Additional history-preservation assertion**: the test asserts that creating an invoice with a `vehicle_odometer` value inserts exactly one `odometer_readings` row with `source="invoice"`, proving the history flow is intact.

  - [x] 4.3 Modify `update_invoice()` (~L2474-2520)
    - When the resolved vehicle is `("global", gv)` and any Customer_Driven_Field would change: call `promote_vehicle(..., trigger_site="invoices.update")` then write to the `OrgVehicle`
    - Migrate the `customer_vehicles` link via `migrate_link_to_org_vehicle(...)` if it still points at `global_vehicle_id`
    - When the resolved vehicle is already `("org", ov)`: existing behaviour
    - **Local-variable rebinding** (per "Local Variable Rebinding After Promotion" note above): immediately after `promote_vehicle()` returns, set `vehicle_record = ov` and `vehicle_type = "org"`. The existing `if vehicle_type == "org": vehicle_record.<field> = value` branch will then take effect for the just-promoted vehicle. Without the rebind, the code would fall through to the `else` branch and re-read `gv` and write to it — silently regressing isolation
    - **Pre-existing-bug fix in the same patch — schema gap**: `update_invoice` currently has no branch for `vehicle_cof_expiry_date` because the field is missing from the request schema entirely. Two coordinated changes are required:
      1. **Add to schema** — add `vehicle_cof_expiry_date: date | None = Field(default=None, ...)` to `UpdateInvoiceRequest` in `app/modules/invoices/schemas.py` (sibling of `vehicle_wof_expiry_date` at ~L417). Without this, the field never enters the `updates` dict, so any service-layer branch is unreachable. `_LIMITED_EDIT_FIELDS` at ~L2227 already includes `vehicle_cof_expiry_date`, so once the schema accepts it, limited-edit (issued/partially_paid/overdue) flows through naturally
      2. **Add to resolution check** — extend the gate at ~L2474 from `if global_vehicle_id and (vehicle_service_due_date or vehicle_wof_expiry_date):` to `if global_vehicle_id and (vehicle_service_due_date or vehicle_wof_expiry_date or vehicle_cof_expiry_date):`. Without this widening, an edit that changes only COF would skip `_resolve_vehicle_type`, leave `vehicle_type=None`, and silently drop the COF write
      3. **Add the COF write branch** — mirror the existing WOF branch (org-vehicle direct write vs global-vehicle resolution) for COF, following the spec's promote-then-write rule for the global branch
    - _Requirements: 1.2, 1.5, 2.2, 2.4, 3.3, 9.6_
    - _Design: Code Changes per File → `app/modules/invoices/service.py` (update_invoice); Implementation Note — Local Variable Rebinding_
    - **Verify**: integration test asserts `update_invoice` triggers promotion when a Customer_Driven_Field changes on a `global_vehicles`-backed invoice, and does NOT promote when only non-vehicle fields change. **Additional COF parity test** in `tests/integration/test_vehicle_promotion_trigger_sites.py::test_invoice_update_writes_cof_expiry_to_org_vehicle`: send `PUT /api/v1/invoices/{id}` with only `vehicle_cof_expiry_date` set; assert (a) the request is accepted by the schema (no 422), (b) the new COF lands on `org_vehicles.cof_expiry`, (c) `global_vehicles.cof_expiry` is byte-identical to its pre-edit value, (d) promotion fired (audit row with `trigger_site='invoices.update'`).

  - [x] 4.4 Add integration tests for the invoice-service trigger sites
    - `tests/integration/test_vehicle_promotion_trigger_sites.py::test_invoice_create_promotes_first_time`
    - `tests/integration/test_vehicle_promotion_trigger_sites.py::test_invoice_update_promotes_when_customer_driven_field_changes`
    - Both assert the five invariants from the design's Test Strategy → Integration Tests
    - _Requirements: 15.2_
    - _Design: Test Strategy → Integration Tests_
    - **Verify**: both tests pass; in particular, `global_vehicles.odometer_last_recorded` is unchanged after the first invoice writes a new odometer value, while `org_vehicles.odometer_last_recorded` for the calling org reflects the new value.

- [x] 5. Redirect promotion trigger site in `app/modules/kiosk/service.py`
  - [x] 5.1 Modify `kiosk_check_in_v2` odometer-insert path (~L500-510, function defined at L389)
    - Keep the `OdometerReading.global_vehicle_id` insert as-is (Req 11) — it already correctly uses `reading_km` and `source="kiosk"` (verified at `kiosk/service.py:503-510`); no field-name fix is needed here unlike the fleet-portal path
    - After the history insert, call `promote_vehicle(..., trigger_site="kiosk.v2_check_in")` (idempotent if the link step already promoted), then bump `ov.odometer_last_recorded`
    - Do NOT bump `gv.odometer_last_recorded`
    - The `_ensure_vehicle_linked` call site needs no change: `link_vehicle_to_customer` now promotes internally per task 3.2
    - _Requirements: 1.3, 3.4, 11.1, 11.2_
    - _Design: Code Changes per File → `app/modules/kiosk/service.py`_
    - **Verify**: `pytest -q tests/integration/test_vehicle_promotion_trigger_sites.py::test_kiosk_v2_check_in_promotes_first_time` passes; `global_vehicles.odometer_last_recorded` unchanged; `org_vehicles.odometer_last_recorded` updated.

  - [x] 5.2 Add integration test `test_kiosk_v2_check_in_promotes_first_time`
    - In `tests/integration/test_vehicle_promotion_trigger_sites.py`
    - Asserts the five invariants from the design's Test Strategy
    - _Requirements: 15.2_
    - _Design: Test Strategy → Integration Tests_
    - **Verify**: the test passes and shows the kiosk path produces a single `vehicle.promote` audit row with `trigger_site='kiosk.v2_check_in'`.

- [x] 6. Redirect promotion trigger sites in `app/modules/fleet_portal/services/vehicle_service.py`
  - [x] 6.1 Modify the `log_odometer_reading` helper to write to `org_vehicles`
    - Replace `gv.odometer_last_recorded = ...` with: `promote_vehicle(..., trigger_site="fleet_portal.record_odometer")` then `ov.odometer_last_recorded = ...`
    - The history insert into `odometer_readings` continues to key on `global_vehicle_id`
    - **Pre-existing-bug fix in the same patch**: the current code references a non-existent `OdometerReading.odometer_km` column (the actual column on the model is `reading_km`, see `app/modules/vehicles/models.py:171`). Both the `select(func.max(OdometerReading.odometer_km))` aggregation and the `OdometerReading(..., odometer_km=value_km, ...)` constructor are broken — they raise at runtime as soon as a fleet user logs an odometer. Replace every `odometer_km` reference with `reading_km` (matching the model and matching the kiosk path which already uses the correct field name). Also set `source="manual"` on the inserted history row (the `ck_odometer_readings_source` CHECK constraint allows only `carjam/manual/invoice/kiosk`; `manual` is the closest match for a driver/fleet-admin manual entry, and avoids requiring a migration to extend the CHECK)
    - _Requirements: 1.4, 3.5, 7.1, 11.1, 11.2_
    - _Design: Code Changes per File → `app/modules/fleet_portal/services/vehicle_service.py`; B2B Fleet Portal Impact (record-odometer row)_
    - **Verify**: `pytest -q tests/integration/test_vehicle_promotion_trigger_sites.py::test_fleet_portal_record_odometer_promotes_first_time` passes. **Additional regression test** `tests/integration/test_vehicle_promotion_trigger_sites.py::test_fleet_portal_record_odometer_does_not_raise_attribute_error`: log an odometer reading via the fleet portal helper and assert (a) no `AttributeError` / `TypeError` is raised, (b) the inserted `odometer_readings` row has `reading_km` equal to the value passed in, (c) the row's `source` column equals `"manual"` and satisfies the `ck_odometer_readings_source` CHECK constraint.

  - [x] 6.2 Modify the field-update path — note: the actual write happens in `app/modules/fleet_portal/router.py::edit_vehicle`, not in the service layer
    - **Where the write actually happens**: the per-role allowlist (`_FLEET_ADMIN_ALLOWED_FIELDS`, `_DRIVER_ALLOWED_FIELDS` in `fleet_portal/services/vehicle_service.py:39-66`) is consumed by `update_vehicle_fields()` (service.py L307-323) which **only filters keys** — it does NOT write to the DB. The write happens in `app/modules/fleet_portal/router.py::edit_vehicle` at L2103-2118 via `target = cv.global_vehicle if cv.global_vehicle is not None else cv.org_vehicle; for key, value in payload.items(): setattr(target, key, value)`. **Task 6.2 modifies the router file, not the service file**
    - When the resolved `target` is a `GlobalVehicle` and any allowed field maps to a Customer_Driven_Field (`odometer_last_recorded`, `service_due_date`, `wof_expiry`, `cof_expiry`, `inspection_type`): call `promote_vehicle(..., trigger_site="fleet_portal.update_field")` first, then **rebind `target = ov`** before the `setattr` loop runs
    - Migrate the `customer_vehicles` link via `migrate_link_to_org_vehicle(...)` if it still points at `global_vehicle_id`
    - **Local-variable rebinding** (per the shared note above): `target` MUST be rebound to the new `OrgVehicle` before the `setattr` loop. Without the rebind, the `setattr` writes still target `cv.global_vehicle` because `cv` was loaded earlier in the function and the relationship attribute still points at the gv. This is the most dangerous rebind site in the spec — fleet portal is the path most likely to log a meaningful field change in production
    - The frozenset name in the service file is **`_FLEET_ADMIN_ALLOWED_FIELDS`** (not `_FLEET_ALLOWED_FIELDS`); no rename needed, just use the correct existing name when reading the allowlist
    - _Requirements: 1.4, 3.5, 7.1, 7.4_
    - _Design: Code Changes per File → `app/modules/fleet_portal/router.py` (edit_vehicle); B2B Fleet Portal Impact (PATCH endpoint rows); Implementation Note — Local Variable Rebinding_
    - **Verify**: `pytest -q tests/integration/test_vehicle_promotion_trigger_sites.py::test_fleet_portal_service_due_update_promotes_first_time` passes. **Additional rebind regression**: the test asserts that after a fleet PATCH that sets `wof_expiry`, the `setattr` write hit `org_vehicles` (not `global_vehicles`) — i.e. `global_vehicles.wof_expiry` is byte-identical to pre-call.

  - [x] 6.3 Add integration tests for the fleet-portal-service trigger sites
    - `test_fleet_portal_record_odometer_promotes_first_time`
    - `test_fleet_portal_service_due_update_promotes_first_time`
    - Both assert the five invariants from the design's Test Strategy
    - _Requirements: 15.2_
    - _Design: Test Strategy → Integration Tests_
    - **Verify**: both tests pass; assert the `trigger_site` in the audit log is `fleet_portal.record_odometer` and `fleet_portal.update_field` respectively.

- [x] 7. Redirect promotion trigger sites in `app/modules/fleet_portal/router.py`
  - [x] 7.1 Modify the admin link-creation handler (~L2032)
    - When the supplied `vehicle_id` resolves to a `GlobalVehicle`: call `promote_vehicle(..., trigger_site="fleet_portal.admin_link")` first, then create the `CustomerVehicle` with `org_vehicle_id=ov.id, global_vehicle_id=None`
    - When the supplied `vehicle_id` already resolves to an `OrgVehicle`: existing behaviour
    - Also covers the CarJam-import path: after the existing `lookup_vehicle()` call writes the `global_vehicles` row, promote and link via `org_vehicle_id` (audit-log `trigger_site="fleet_portal.carjam_import"` for that variant)
    - **Local-variable rebinding** (per the shared note above): the function already loads both `gv` and `ov` (~L2014-2022) before deciding which path to take. After `promote_vehicle()` returns the new `OrgVehicle`, **set `gv = None` and `ov = <returned>` before the link-existence query (Task 11.7) and the `CustomerVehicle(...)` constructor**. Otherwise the existence query at L2018 still filters on `cv.global_vehicle_id == gv.id` (the original gv id) and the construct at L2034 still passes `global_vehicle_id=gv.id`, undoing the promotion atomically with the create. This is the same rebind discipline as Task 4.1
    - _Requirements: 2.3, 3.6, 7.2_
    - _Design: Code Changes per File → `app/modules/fleet_portal/router.py`; B2B Fleet Portal Impact (admin link + CarJam import rows); Implementation Note — Local Variable Rebinding_
    - **Verify**: integration tests `test_fleet_portal_admin_link_creation_promotes_first_time` and `test_fleet_portal_carjam_import_promotes_first_time` both pass. **Additional rebind regression**: each test asserts the resulting `customer_vehicles` row has `org_vehicle_id` set and `global_vehicle_id` NULL — proving the rebind happened before the CustomerVehicle constructor ran.

  - [x] 7.2 Add integration tests for the fleet-portal-router trigger sites
    - `test_fleet_portal_admin_link_creation_promotes_first_time`
    - `test_fleet_portal_carjam_import_promotes_first_time`
    - Each asserts the five invariants from the design's Test Strategy and verifies the correct `trigger_site` string in the audit log
    - _Requirements: 15.2_
    - _Design: Test Strategy → Integration Tests_
    - **Verify**: both tests pass.

- [x] 8. Redirect promotion trigger sites in `app/modules/bookings/service.py`
  - [x] 8.1 Modify the two link-creation sites (~L391 and ~L416)
    - For the `("global", gv)` branch at each site: call `promote_vehicle(..., trigger_site="bookings.link")` and create the link with `org_vehicle_id=ov.id, global_vehicle_id=None`
    - The `("org", ov)` branch is unchanged
    - _Requirements: 2.3, 3.6_
    - _Design: Code Changes per File → `app/modules/bookings/service.py`_
    - **Verify**: `pytest -q tests/integration/test_vehicle_promotion_trigger_sites.py::test_bookings_link_creation_promotes_first_time` passes; both link-creation sites are exercised by the test.

  - [x] 8.2 Add integration test `test_bookings_link_creation_promotes_first_time`
    - In `tests/integration/test_vehicle_promotion_trigger_sites.py`
    - Asserts the five invariants from the design's Test Strategy
    - _Requirements: 15.2_
    - _Design: Test Strategy → Integration Tests_
    - **Verify**: the test passes.

- [x] 9. Redirect promotion trigger site in `app/modules/customers/service.py`
  - [x] 9.1 Modify the link-creation site (~L994)
    - When the supplied `vehicle_id` resolves to a `GlobalVehicle`: call `promote_vehicle(..., trigger_site="customers.link")` first and create the link with `org_vehicle_id=ov.id, global_vehicle_id=None`
    - When the supplied `vehicle_id` already resolves to an `OrgVehicle`: existing behaviour
    - **Pre-flight controller-guard check**: read `app/modules/customers/router.py` to confirm whether the controller layer (or a higher-level handler) prevents the same caller from invoking link-creation twice for the same `(org_id, customer_id, rego)`. The service-layer site at L994 does not currently perform an existence check before constructing the `CustomerVehicle` — it relies on the caller. If no controller guard exists, add one: a small `select(CustomerVehicle).where(...).limit(1)` before constructing, returning HTTP 409 if a link already exists. Do NOT bypass this verification — silently allowing duplicate links is not acceptable behaviour and is the same defect that Task 11.7 fixes elsewhere
    - _Requirements: 2.3, 3.6_
    - _Design: Code Changes per File → `app/modules/customers/service.py`_
    - **Verify**: `pytest -q tests/integration/test_vehicle_promotion_trigger_sites.py::test_customers_link_creation_promotes_first_time` passes. **Additional duplicate-prevention assertion**: a second invocation of the customer-vehicle-link endpoint for the same `(customer_id, rego)` returns HTTP 409 (or, if the existing controller already raises a different conflict status, document it in the test). Note in PR description: "Verified that customer-link site has duplicate-prevention either via controller guard at `customers/router.py:<line>` or added in this PR".

  - [x] 9.2 Add integration test `test_customers_link_creation_promotes_first_time`
    - In `tests/integration/test_vehicle_promotion_trigger_sites.py`
    - Asserts the five invariants from the design's Test Strategy
    - _Requirements: 15.2_
    - _Design: Test Strategy → Integration Tests_
    - **Verify**: the test passes.

- [x] 10. Redirect promotion trigger site in `app/modules/customers/service.py::update_vehicle_expiry_dates`
  - [x] 10.1 Modify `update_vehicle_expiry_dates()` (~L1913-1996, gv writes at L1977 and L1984) to promote-then-write
    - This endpoint is exposed via `app/modules/customers/router.py::update_vehicle_dates_endpoint` (L1165) at `PUT /api/v1/customers/{customer_id}/vehicle-dates`. The service layer currently writes `gv.service_due_date` and `gv.wof_expiry` directly to `global_vehicles` for every linked vehicle in the payload — exactly the cross-tenant leak this spec closes
    - When the linked vehicle resolves to `("global", gv)`: call `promote_vehicle(..., trigger_site="customers.update_vehicle_dates")` then write `service_due_date`, `wof_expiry`, **and** `cof_expiry` to the returned `OrgVehicle`
    - Migrate the `customer_vehicles` link via `migrate_link_to_org_vehicle(...)` if it still points at `global_vehicle_id`
    - When the linked vehicle already resolves to `("org", ov)`: write directly to `ov` without promotion
    - **Pre-existing-bug fix in the same patch**: this endpoint is also missing a `cof_expiry` branch (today only handles `service_due_date` and `wof_expiry`). Add the missing `cof_expiry` branch and update the request schema (the body shape consumed by `update_vehicle_dates_endpoint` — verify the relevant Pydantic model in `customers/schemas.py` or wherever `update_vehicle_expiry_dates`'s `vehicle_updates` list dicts are typed) so the request accepts an optional `cof_expiry` ISO date string. The existing call signature already accepts `vehicle_updates: list[dict]` per `customers/service.py:1919`, so the schema-level addition is light. Confirm the corresponding frontend page (`CustomerDetail.tsx` reminders panel or wherever the dates are edited) is unaffected — the request body strictly adds an optional field, so existing clients continue to work
    - The endpoint's return shape adds the same `cof_expiry` key that `service_due_date` and `wof_expiry` already use. Backend response shape extension only — frontend ignores unknown keys per `safe-api-consumption.md`
    - _Requirements: 1.2, 1.5, 2.2, 2.4, 3.6, 9.4, 9.5, 14.1_
    - _Design: Code Changes per File → `app/modules/customers/service.py` (extend `update_vehicle_expiry_dates`)_
    - **Verify**: `pytest -q tests/integration/test_vehicle_promotion_trigger_sites.py::test_customers_update_vehicle_dates_promotes_first_time` passes; `global_vehicles.{service_due_date, wof_expiry, cof_expiry}` are byte-identical before vs after the call; `org_vehicles.{service_due_date, wof_expiry, cof_expiry}` for the calling org hold the new values; `customer_vehicles.org_vehicle_id` is set and `global_vehicle_id` is NULL; one `vehicle.promote` audit row with `trigger_site='customers.update_vehicle_dates'`

  - [x] 10.2 Add integration test `test_customers_update_vehicle_dates_promotes_first_time`
    - In `tests/integration/test_vehicle_promotion_trigger_sites.py`
    - Includes a sub-assertion that posting `cof_expiry` lands on `org_vehicles.cof_expiry` and not on `global_vehicles.cof_expiry` — the missing-COF-branch fix
    - _Requirements: 15.2_
    - _Design: Test Strategy → Integration Tests_
    - **Verify**: the test passes; the additional COF assertion holds.

- [x] 11. Fix Read_Fallback consumers that only render `global_vehicles`
  - Once a `customer_vehicles` link is migrated to `org_vehicle_id`, any read code that joins or accesses `cv.global_vehicle` without falling through to `cv.org_vehicle` will silently render NULL (attribute reads) or drop the row entirely (inner joins). The seven sub-tasks below cover all known broken sites and add a final sweep + a link-existence-check widening across every link-creation site so duplicate links are not introduced after promotion. Use either the `v = gv if gv else ov` fallback pattern (already used correctly in `app/modules/fleet_portal/services/vehicle_service.py`) or a two-pass query covering both link types. Rego-keyed lookups (Task 11.5) must invert their order to prefer `OrgVehicle` over `GlobalVehicle` to close the cross-tenant leak.

  - [x] 11.1 Fix customer-search vehicle list (`app/modules/customers/service.py::search_customers`, ~L240-280; function defined at L101)
    - Current code at the `if include_vehicles:` block: `select(CustomerVehicle, GlobalVehicle).outerjoin(GlobalVehicle, CustomerVehicle.global_vehicle_id == GlobalVehicle.id)` then `if gv: linked_vehicles.append(...)` — drops promoted links entirely
    - Replace with a double outerjoin: `.outerjoin(GlobalVehicle, ...).outerjoin(OrgVehicle, CustomerVehicle.org_vehicle_id == OrgVehicle.id)`. Loop body becomes `v = gv if gv is not None else ov; if v is not None: linked_vehicles.append({...from v...})`
    - The serialised dict's keys (`id`, `rego`, `make`, `model`, `year`, `colour`, `odometer`, `service_due_date`, `wof_expiry`, `cof_expiry`, `inspection_type`) all read identically from both `OrgVehicle` and `GlobalVehicle` because the schema parity established by migration 0105+0181 means every consumed attribute exists on both
    - Set `id` to `str(v.id)` regardless of source; if downstream consumers need to know which type, add `"source": "org" if gv is None else "global"` (low risk — frontend ignores unknown keys)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 9.6, 10.2, 15.5_
    - _Design: Read Paths (extended); Backwards Compatibility table_
    - **Verify**: `pytest -q tests/test_vehicle_data_isolation.py::test_customer_search_returns_promoted_vehicles` passes — pre-create one promoted (`org_vehicle_id`-only) link and one unmigrated (`global_vehicle_id`-only) link for the same customer, search the customer, assert both vehicles render with their respective rego/make/model.

  - [x] 11.2 Fix any other `cv.global_vehicle.*` access points in `app/modules/customers/service.py` and `app/modules/customers/router.py`
    - grep for `cv\.global_vehicle\b` and `\.global_vehicle\.` within the customers module; for every read (not write) site, apply the fallback pattern from 11.1
    - The customer detail endpoint also returns `linked_vehicles` — the same single-source bug applies
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 15.5_
    - _Design: Read Paths (extended)_
    - **Verify**: a grep at the end of this task shows zero remaining `cv.global_vehicle.<field>` reads that are not guarded by `if cv.global_vehicle is not None: ... else: <ov fallback>`.

  - [x] 11.3 Fix dashboard expiry-reminders widget (`app/modules/organisations/dashboard_service.py::get_expiry_reminders`, function defined at L610; offending join at L637, customer-name lookup at L652)
    - Two pre-existing problems plus one spec-driven problem:
      - **Pre-existing bug**: the raw SQL at L637 joins `org_vehicles ov ON ov.global_vehicle_id = gv.id`, but `org_vehicles.global_vehicle_id` is **not** a column on the model (`app/modules/vehicles/models.py:33`). This widget would error on any real call. Either it has never been exercised in prod, or the schema was once aligned and a later migration dropped the column. Pre-existing.
      - **Pre-existing bug**: the customer-name lookup at L652 `WHERE cv.global_vehicle_id = :vid` returns "Unlinked" any time the link points at `org_vehicle_id` instead.
      - **Spec-driven**: post-deploy, every promoted vehicle's customer-driven dates (`wof_expiry`, `cof_expiry`, `service_due_date`) live on `org_vehicles`, not `global_vehicles`. The widget must read from `org_vehicles` first.
    - Replace the widget query with one that pulls `org_vehicles` rows directly for the calling org (no join through `global_vehicles`), reading `wof_expiry`, `cof_expiry`, `inspection_type`, `service_due_date` from `ov`. For un-promoted regos that exist only as `global_vehicles`-backed links, add a UNION (or a second query) that pulls `gv.{wof_expiry, cof_expiry, inspection_type, service_due_date}` for every `customer_vehicles` row whose `org_id = :org_id` AND `org_vehicle_id IS NULL`
    - Customer-name join: change to `WHERE (cv.org_vehicle_id = :vid OR cv.global_vehicle_id = :vid) AND cv.org_id = :org_id LIMIT 1`
    - _Requirements: 6.1, 6.2, 6.5, 9.7, 10.2, 15.5_
    - _Design: Read Paths (extended)_
    - **Verify**: `pytest -q tests/test_vehicle_data_isolation.py::test_dashboard_expiry_widget_reads_from_org_vehicles_post_promotion` passes. Set up: org with one promoted `org_vehicles` row whose `wof_expiry` is 14 days away, plus one un-promoted `global_vehicles`-backed link whose `wof_expiry` is 21 days away. Assert the widget returns both vehicles with correct customer names. Run an `EXPLAIN` and confirm no `org_vehicles.global_vehicle_id` reference appears in the new SQL.

  - [x] 11.4 Sweep the rest of the codebase for `cv.global_vehicle` reads AND `global_vehicle_id` joins
    - Run `grepSearch` for **two** patterns across `app/**/*.py`:
      - `\.global_vehicle\b` — catches attribute-style reads like `cv.global_vehicle.wof_expiry`
      - `\.global_vehicle_id\s*==` — catches join clauses like `.join(GlobalVehicle, CustomerVehicle.global_vehicle_id == GlobalVehicle.id)` which silently drop promoted links because they are inner joins
    - For every match, confirm one of: (a) the path goes through `_resolve_vehicle_type` (which handles fallback), (b) the path explicitly checks both `cv.global_vehicle_id` and `cv.org_vehicle_id` branches (the `portal/service.py` pattern at L600-628 is the canonical example), (c) the path is genuinely global-only (e.g. `refresh_vehicle` writing to `global_vehicles`, the global-admin route, or `lookup_vehicle` writing the CarJam cache)
    - The widened sweep is required because the inner-join pattern in notification/reminder services (Task 11.6) is invisible to the attribute-style grep alone
    - **Known target — must be fixed in this task** (`app/modules/data_io/service.py::export_vehicles_csv` at L683-760): the function pre-loads **all** `OrgVehicle` rows for the org via `select(OrgVehicle).where(OrgVehicle.org_id == org_id)` at L699-702, then runs a **separate** `select(GlobalVehicle).join(CustomerVehicle, CustomerVehicle.global_vehicle_id == GlobalVehicle.id)` at L705-710. Promoted vehicles **do** appear in the CSV — they're already in the org_vehicles loop at L744-751. The actual bug is **mislabelling**: every row from `org_vehicles` is written with `lookup_type="manual"` at L749, but a promoted row has `is_manual_entry=False` and was originally CarJam-sourced. Fix: replace the hardcoded `"manual"` literal at L749 with `("manual" if v.is_manual_entry else "carjam")`. No structural join change is required — the existing two-query approach already covers both link types correctly. Drop the earlier "two-pass UNION ALL" prescription; it's unnecessary scaffolding given the existing pre-load
    - Document any remaining read sites not in (a)/(b)/(c) and either fix them or list them in design.md as known carve-outs
    - _Requirements: 6.5, 9.6, 15.5_
    - _Design: Read Paths (extended)_
    - **Verify**: an annotated diff of all `cv.global_vehicle` and `.global_vehicle_id ==` consumer sites is attached to the PR description; no read site falls outside categories (a)-(c). **Additional regression test** `tests/test_vehicle_data_isolation.py::test_data_io_export_vehicles_labels_promoted_as_carjam`: pre-create one un-promoted (manual-entry) and one promoted (`is_manual_entry=False`) `org_vehicles` row; run `export_vehicles_csv`; assert the manual-entry row's `lookup_type` column reads `"manual"` and the promoted row's reads `"carjam"`. Both regos appear in the CSV exactly once.

  - [x] 11.5 Fix invoice display reads to prefer `OrgVehicle` over `GlobalVehicle` (rego-keyed lookups)
    - Two flows currently look up vehicle display fields by rego. Each has a slightly different fix:
    - **Fix `app/modules/invoices/service.py::get_invoice_detail` (~L1697-1741)**: the function tries `GlobalVehicle.rego` first and falls back to `OrgVehicle.rego` only when `gv is None`. Because `gv` almost always exists for a CarJam-pulled rego, the org-vehicle fallback never fires, so every org reads cross-tenant `gv` data. Fix: invert the order. Try `OrgVehicle.org_id == invoice.org_id AND func.upper(OrgVehicle.rego) == invoice.vehicle_rego.upper()` first. If found, build the `result["vehicle"]` dict from `ov`. Only if the org has no row for this rego, fall back to `GlobalVehicle.rego == ...` (Read_Fallback, Req 6). Last resort: invoice's flat fields (unchanged)
    - **Fix `app/modules/invoices/public_router.py` (~L107-123)**: this endpoint **does not currently have an `OrgVehicle` branch at all** — it consults only `GlobalVehicle`. The fix is to **add** the `OrgVehicle` branch (org_id-scoped via `invoice.org_id`), positioned before the `GlobalVehicle` lookup. This is a structural addition, not a reorder of two existing branches. The `vehicle` dict's keys are identical between both sources per migrations 0003+0105+0181, so no schema change. Without this fix, the public invoice page (anonymous customer view via portal token) serves cross-tenant `global_vehicles` Customer_Driven_Fields written by other workshops
    - The `additional_vehicles` enrichment block at `service.py:1755-1782` has the same single-source bug as `get_invoice_detail` — invert it the same way (look up `OrgVehicle` first by `(invoice.org_id, av_rego)`, fall back to `GlobalVehicle` by rego)
    - The schema of the returned `vehicle` dict is **identical** in both branches (both `OrgVehicle` and `GlobalVehicle` expose the same `rego/make/model/year/wof_expiry/cof_expiry/odometer_last_recorded/service_due_date` attributes per migrations 0003+0105+0181) — no Pydantic schema change, no frontend change
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 9.6, 10.2, 15.5_
    - _Design: Read Paths (extended) — invoice display section_
    - **Verify**: integration test `tests/integration/test_vehicle_promotion_trigger_sites.py::test_invoice_detail_serves_org_snapshot_after_promotion` — Org A creates an invoice writing `wof_expiry='2027-01-15'`; verify Org A's invoice detail returns `wof_expiry='2027-01-15'`; verify Org B (linked to the same rego via an unmigrated `global_vehicle_id` link) still sees the original `global_vehicles.wof_expiry` value, not Org A's write. Public-router test mirrors this by calling the portal-token endpoint as Org B and asserting the same isolation property.

  - [x] 11.6 Fix notification and reminder services that **inner-join** `customer_vehicles` to `global_vehicles`
    - Three call sites currently do an INNER JOIN that silently excludes every `customer_vehicles` row whose link has been migrated to `org_vehicle_id`. Post-deploy, no WOF/COF/Rego/service-due reminders fire for any rego that has been touched by a customer-driven write since the deploy — every promoted link drops out of the join
    - **`app/modules/notifications/service.py::process_wof_rego_reminders` (~L1465-1485)**: the loop iterates `("WOF", "wof_expiry", ...), ("COF", "cof_expiry", ...), ("Registration", "registration_expiry", ...)` and joins `CustomerVehicle.global_vehicle_id == GlobalVehicle.id` matching `target_date`. Replace with: a UNION-style two-pass query, or two parallel queries — one for `cv.global_vehicle_id IS NOT NULL` joining `GlobalVehicle`, one for `cv.org_vehicle_id IS NOT NULL` joining `OrgVehicle` (filtered by the same `expiry_field == target_date`). Merge the result rows; the per-row processing block (subject dedup, channel send, audit log) reads `gv` or `ov` interchangeably since both have the same field set
    - **`app/modules/notifications/service.py::process_customer_reminders` (~L2066-2110)**: same pattern — replace the single inner join with two-pass query covering both link types. The expiry-field-name lookup (`expiry_field = "service_due_date" | "wof_expiry" | "cof_expiry"`) is unchanged
    - **`app/modules/notifications/reminder_queue_service.py::_process_customer_reminders` (~L192-201)**: same pattern, same fix
    - For **Registration expiry** specifically: this maps to `registration_expiry`, which is a **CarJam_Owned_Spec_Field** (it's CarJam's record of the rego renewal). After promotion, the `org_vehicles` row holds a copy. CarJam refresh updates the `global_vehicles` source row, and `manual_refresh_vehicle` (Task 12.1) propagates it into `org_vehicles`. The two-pass query reads from whichever row is linked — both are valid sources for the `=== target_date` filter
    - **Idempotency on the dedup key — and one-time migration risk**: the existing dedup subject is `f"{template_type}_{org_id}_{gv.id}_{expiry_date_str}"` keyed by **`gv.id`**. After promotion, the link points at `ov.id`; the dedup key must use a value that survives the link migration. Standardise on `cv.id` (the link id) in the dedup key — it is stable across promotion and unique per (customer, vehicle, org). Document in code that the dedup key changed from `gv.id`/`ov.id` to `cv.id` to survive promotion
    - **One-time migration consequence (must be documented in CHANGELOG)**: any reminder that was already sent in the days before deploy has a `notification_log` row keyed on the **old** `gv.id` format. The new `cv.id`-keyed lookup will not find it, so the **next scheduler run after deploy** will re-send those reminders that fall within the lookahead window (≤ 30 days for service-due, ≤ 14 days for WOF/COF). This is a one-cycle, customer-visible duplication. Two acceptable approaches:
      - **Option A (accept the duplicate cycle)**: ship as-is; add a CHANGELOG entry under "Notes" warning that customers may receive a duplicate reminder for one cycle following the deploy. Low engineering cost, mild user impact for ≤ 30 days
      - **Option B (back-compat dual-key read)**: in the new dedup-existence check, fall back to checking the **old** `gv.id`-keyed format when the new `cv.id`-keyed query finds nothing. Add a TTL on this fallback (e.g. only honour rows older than the deploy date for 60 days, then drop the fallback in a follow-up release). Higher engineering cost but zero duplicate sends
    - **Default to Option A** unless the user explicitly chooses Option B; Option A is consistent with the spec's "minimal code change" principle (NFR-1). The CHANGELOG note is added in Task 17.3 alongside the standard Fixed/Security entries
    - _Requirements: 6.1, 6.2, 6.5, 9.6, 10.2, 15.5_
    - _Design: Read Paths (extended) — reminder services_
    - **Verify**: three new tests in `tests/test_vehicle_data_isolation.py`:
      - `test_wof_expiry_reminder_fires_for_promoted_vehicle` — promote a vehicle, set `org_vehicles.wof_expiry = today + 14`, call `process_wof_rego_reminders`, assert exactly one reminder log row created
      - `test_customer_reminder_fires_for_promoted_vehicle` — same scenario for `process_customer_reminders` and `_process_customer_reminders`
      - `test_reminder_dedup_survives_promotion` — set `gv.wof_expiry = today + 14`, fire the un-promoted-side reminder (creates dedup row with `cv.id`), promote the vehicle, fire the same reminder again, assert no second reminder is sent (dedup key matches via `cv.id`)

  - [x] 11.7 Widen `customer_vehicles` link-existence checks at every link-creation site (Req 3.4 fallout)
    - Today, four code paths check whether a customer-vehicle link already exists by matching only `CustomerVehicle.global_vehicle_id == vehicle_id`. After promotion migrates the link to `org_vehicle_id`, this check returns "no row found" even though the link exists, and the calling flow happily creates a **second** `customer_vehicles` row pointing at `org_vehicle_id`. Result: duplicate links per `(org_id, customer_id, vehicle)` after the second touch of any promoted vehicle
    - Note: Task 4.0 extends `_resolve_vehicle_type` to return `("org", ov)` for promoted vehicles. That helps the **resolver-based** call sites (invoices/create_invoice's L920-936 link-existence check operates on the resolved `vehicle_type`/`vehicle_record`, so after Task 4.0 it correctly compares against `ov.id`). The other three sites (`kiosk/_ensure_vehicle_linked`, `bookings/auto-link`, `fleet_portal/router::admin_link`) do NOT use `_resolve_vehicle_type` — they have direct `gv.id`-or-passed-`vehicle_id`-based checks, so they still need the rego-keyed widening
    - The widening pattern: resolve the target rego once (from either `GlobalVehicle.rego` or `OrgVehicle.rego` matching the supplied id), then look for any link `WHERE org_id = :org AND customer_id = :cust AND ((global_vehicle_id IN (SELECT id FROM global_vehicles WHERE rego = :rego)) OR (org_vehicle_id IN (SELECT id FROM org_vehicles WHERE rego = :rego AND org_id = :org)))`. A simpler equivalent: load the resolved rego up front, then run two existence queries (one keyed on the matching `global_vehicle.id`, one on the matching `org_vehicle.id`), and treat either match as "link exists"
    - **Fix `app/modules/kiosk/service.py::_ensure_vehicle_linked` (~L131-137)**: the function is called per check-in; with one pre-existing promoted link, every kiosk check-in creates a duplicate. Load the source's rego and query for any link matching either link-id pointing at that rego
    - **Fix `app/modules/bookings/service.py` (~L386-405)**: the auto-link block inside booking creation has the same bug — when the booking customer is already linked to the promoted vehicle, a second link is created on every booking
    - **Fix `app/modules/invoices/service.py::create_invoice` (~L920-936)**: relies on Task 4.0's resolver extension. After 4.0, `vehicle_type == "org"` for promoted vehicles, so the existing `if vehicle_type == "org"` branch's check `WHERE org_vehicle_id == :vehicle_record.id` works correctly. **Verify** that the existence check at L924-927 uses `vehicle_record.id` (the resolved id) rather than the original `global_vehicle_id` parameter — if the current code references the parameter directly, change it to `vehicle_record.id`
    - **Fix `app/modules/fleet_portal/router.py::admin_link` (~L2014-2022)**: the `existing_link_q` builder filters on `cv.global_vehicle_id == gv.id` when `gv is not None` and `cv.org_vehicle_id == ov.id` when `ov is not None`. After Task 7.1 promotes the vehicle, `gv` may still be present in this code (the helper resolved it before deciding to promote) — the existence check needs to also accept a match on the newly-created `ov.id`. Concretely: after `promote_vehicle()` returns the `OrgVehicle`, replace the `gv.id`-based existence check with an `ov.id`-based one
    - **General principle**: every link-creation site must check existence via the post-promotion identity, not the pre-promotion identity. Failing to do so will create silent duplicate `customer_vehicles` rows that the user sees as the same vehicle appearing twice in their customer profile
    - _Requirements: 3.4, 9.6, 13.3_
    - _Design: Read Paths (extended); Backwards Compatibility table (existing-link case)_
    - **Verify**: four new integration tests in `tests/integration/test_vehicle_promotion_trigger_sites.py`:
      - `test_kiosk_repeated_check_in_after_promotion_does_not_duplicate_link` — promote a vehicle by issuing one invoice, then run kiosk check-in for the same (customer, vehicle); assert exactly one `customer_vehicles` row exists for the pair
      - `test_booking_repeated_creation_after_promotion_does_not_duplicate_link` — same scenario for bookings
      - `test_invoice_repeated_creation_after_promotion_does_not_duplicate_link` — same scenario for invoices (verifies Task 4.0's resolver extension is sufficient for this path)
      - `test_fleet_portal_admin_link_after_promotion_returns_409` — admin attempts to add an already-promoted vehicle to a fleet account; assert HTTP 409 (rather than creating a second link). Also assert the response detail message references the rego, matching today's behaviour

- [x] 12. Rewire the existing CarJam-refresh routes to update `org_vehicles` after refreshing `global_vehicles`
  - Today, `POST /api/v1/vehicles/{id}/refresh`, `POST /api/v1/vehicles/bulk-refresh`, and `POST /api/v1/admin/vehicle-db/{rego}/refresh` all call `refresh_vehicle()` which only updates `global_vehicles`. Post-deploy, an org user clicking "Refresh from CarJam" on a promoted vehicle will see no change because the read path prefers `org_vehicles`. This is a UX regression we must close in the same PR.

  - [x] 12.1 Modify `app/modules/vehicles/router.py::vehicle_refresh` (function defined at L199) to also update `org_vehicles`
    - After the existing `refresh_vehicle(...)` call returns, look up the resolved vehicle for the caller's org via `_resolve_vehicle_type` (or the equivalent rego-keyed `org_vehicles` lookup)
    - If an `org_vehicles` row exists for `(org_id, rego)`: call `manual_refresh_vehicle(db, org_id=..., rego=..., user_id=..., ip_address=...)` so the CarJam_Owned_Spec_Fields are copied from the freshly-refreshed `global_vehicles` row into the existing `org_vehicles` row (Customer_Driven_Fields are explicitly **not** touched per Task 1.3)
    - If no `org_vehicles` row exists yet for that org: skip silently — the user will see the `global_vehicles` refresh on their next read via Read_Fallback. **Note**: `manual_refresh_vehicle` raises `LookupError` when the `org_vehicles` row is missing; the existence check happens **before** the call, so `LookupError` cannot fire from the `/refresh` route in practice. The check-then-call ordering is part of the contract — do not invert it
    - The audit log gets one `vehicle.refresh` (existing) + one `vehicle.manual_refresh` row
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 14.2_
    - _Design: New Helper Functions → `manual_refresh_vehicle()`; Frontend Impact ("Refresh from CarJam" surface unchanged)_
    - **Verify**: integration test `tests/integration/test_vehicle_promotion_trigger_sites.py::test_vehicle_refresh_route_updates_org_vehicles_when_promoted` — set up a promoted org_vehicle, mutate the underlying `global_vehicles` CarJam fields via stub, call the refresh endpoint, assert the `org_vehicles` row's CarJam fields now match the stubbed values and its Customer_Driven_Fields are byte-identical to before. **Additional test** `test_vehicle_refresh_route_skips_manual_refresh_when_unpromoted` — call the endpoint for an org that has no `org_vehicles` row; assert no `LookupError` is raised, no `vehicle.manual_refresh` audit row is written, and only the standard `vehicle.refresh` audit row exists.

  - [x] 12.2 Modify `app/modules/vehicles/router.py::bulk_refresh_vehicles` (~L496) likewise
    - For each `vehicle_id` in the bulk request, after the existing per-vehicle `refresh_vehicle(...)` call, perform the same per-org `manual_refresh_vehicle` follow-up
    - Aggregate per-vehicle errors as today; the `manual_refresh_vehicle` step is best-effort (a failure is logged but does not abort the whole bulk run)
    - _Requirements: 5.1, 5.2, 14.2_
    - _Design: New Helper Functions → `manual_refresh_vehicle()`_
    - **Verify**: bulk integration test asserts every promoted org_vehicles row in the request set is refreshed; un-promoted ones are skipped without error.

  - [x] 12.3 Decision: leave `app/modules/admin/router.py::refresh_vehicle` (global admin route) as-is
    - The global-admin endpoint operates on the cross-tenant `global_vehicles` cache only — it has no `org_id` context and intentionally does not own any per-org snapshot
    - Document this decision inline in the route handler with a one-line comment: "Global-admin refresh updates only the global cache; per-org snapshots refresh via /api/v1/vehicles/{id}/refresh which their org users invoke"
    - _Requirements: 5.1 (out of scope — global admin)_
    - _Design: Code Changes per File → "Other modules — verified untouched" entry for `app/modules/admin/router.py`_
    - **Verify**: the comment is present; no behavioural change.

- [x] 13. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Cross-cutting tests: read-fallback, concurrency, backwards-compatibility
  - [x] 14.1 Add `test_read_fallback_returns_global_when_not_promoted` in `tests/test_vehicle_data_isolation.py`
    - Create a `global_vehicles` row, link a customer to it via `global_vehicle_id`, do not write any Customer_Driven_Field
    - Call every documented read endpoint (vehicle profile, invoice display dict, fleet portal vehicle detail) and assert each returns the global cache values
    - Assert no `org_vehicles` row exists for the calling org
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 10.2, 15.3_
    - _Design: Test Strategy → Read Fallback Test (Req 15.3); Read Paths_
    - **Verify**: the test passes; no assertion in it touches an `org_vehicles` row.

  - [x] 14.2 Add `test_concurrent_promotions_produce_single_org_row` in `tests/test_vehicle_data_isolation.py`
    - Use `asyncio.gather` to fire two `promote_vehicle(...)` calls for the same `(org_id, rego)` in two concurrent transactions
    - After both complete, assert exactly one `org_vehicles` row exists for that pair
    - Assert exactly one `vehicle.promote` audit-log row exists for that pair (only the winning transaction inserted)
    - _Requirements: 13.1, 13.2, 15.4_
    - _Design: Concurrency and Idempotency Strategy; Test Strategy → Concurrency Test (Req 15.4)_
    - **Verify**: the test passes deterministically across at least 10 consecutive runs; both transactions converge on the same row id.

  - [x] 14.3 Add `test_legacy_global_link_still_resolves_through_every_read_endpoint` in `tests/test_vehicle_data_isolation.py`
    - Pre-create a `customer_vehicles` row pointing at `global_vehicle_id` with no `org_vehicles` row
    - Iterate over every documented read endpoint (vehicle profile, invoice list/detail, kiosk lookup, fleet portal vehicle list/detail/summary, customer profile vehicles) and assert each returns valid vehicle data with the global-cache values
    - _Requirements: 6.5, 9.6, 10.2, 15.5_
    - _Design: Test Strategy → Backwards-Compatibility Test (Req 15.5); Backwards Compatibility table_
    - **Verify**: the test passes for every read endpoint enumerated in the design's Read Paths section.

- [x] 15. End-to-end OWASP smoke script
  - [x] 15.1 Create `scripts/test_vehicle_data_isolation_e2e.py`
    - Set up two test organisations with the `TEST_E2E_` prefix on names, regos, customers
    - Create a `global_vehicles` row via Org A's CarJam import (or stub)
    - **OWASP A1 (Broken Access Control)**: as Org A, attempt to read Org B's `org_vehicles` directly; expect 404/403, assert RLS denial
    - **OWASP A2 (Cryptographic Failures)**: scan every response payload (audit-log entries, error messages) for `api_key`, `secret`, `password` substrings; assert none leak
    - **OWASP A3 (Injection)**: post a SQL-injection-shaped rego (`'; DROP TABLE org_vehicles; --`) and assert the parameter binding rejects it as an invalid rego, and `org_vehicles` still exists afterwards
    - **OWASP A4 (Insecure Design)**: as Org A, create an invoice that writes a Customer_Driven_Field; then log in as Org B, read the same rego; assert Org B sees the original `global_vehicles` value (Read_Fallback), not Org A's write
    - Promote the rego in Org B by creating an invoice in Org B; assert both orgs now have independent `org_vehicles` rows with independent values
    - **Cleanup**: delete every row whose name starts with `TEST_E2E_` (orgs, customers, invoices, vehicles, links, audit-log entries) on both success and failure paths
    - Exit non-zero on any assertion failure with a clear stdout summary
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 15.1_
    - _Design: Test Strategy → End-to-End Test; Security Hardening (OWASP A1–A4)_
    - **Verify**: `python scripts/test_vehicle_data_isolation_e2e.py` exits 0; stdout shows all four OWASP checks PASSED; running `SELECT count(*) FROM <each table> WHERE name LIKE 'TEST_E2E_%'` returns 0 in every relevant table after the run.

- [x] 16. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 17. Version bump and CHANGELOG entry
  - [x] 17.1 Bump `pyproject.toml` version `1.10.2` → `1.10.3`
    - Update the `version` field in `pyproject.toml` (PATCH bump per `versioning-and-changelog.md` — behavioural fix, no API contract change, no breaking change)
    - _Requirements: (release discipline — `.kiro/steering/versioning-and-changelog.md`)_
    - _Design: Rollout and Rollback Plan; CHANGELOG Entry_
    - **Verify**: `grep '^version = ' pyproject.toml` shows `version = "1.10.3"`.

  - [x] 17.2 Bump `frontend/package.json` version `1.10.2` → `1.10.3`
    - Update the `version` field in `frontend/package.json` so backend and web frontend versions stay aligned (per `versioning-and-changelog.md` Rules: "All three version files must match"); no functional frontend change ships in this PR
    - _Requirements: (release discipline — `.kiro/steering/versioning-and-changelog.md`)_
    - _Design: Frontend Impact (zero); CHANGELOG Entry_
    - **Verify**: `grep '"version"' frontend/package.json` shows `"version": "1.10.3"`.

  - [x] 17.3 Add `[1.10.3]` entry to `CHANGELOG.md`
    - Prepend the block from `design.md` → "CHANGELOG Entry" at the top of `CHANGELOG.md`, replacing `YYYY-MM-DD` with the deploy date
    - The block lists Fixed (vehicle data isolation, audit-log actions, advisory-lock concurrency note) and Security (multi-tenant data-leakage defect closed)
    - **Add a `### Notes` subsection** to the same `[1.10.3]` block warning operators that the reminder dedup-key change (Task 11.6) may cause customers to receive a duplicate WOF / COF / service-due / registration reminder for one cycle following the deploy. Suggested wording: "Reminder dedup keys were migrated from a vehicle-id-based scheme to a link-id-based scheme so dedup survives the new vehicle isolation. As a one-time consequence, reminders that fall within the lookahead window (≤ 30 days for service-due, ≤ 14 days for WOF/COF) and were already sent before this release may be sent a second time on the next scheduler run. Subsequent runs dedup correctly." Skip this paragraph if Option B (back-compat dual-key read) was selected in Task 11.6
    - _Requirements: (release discipline — `.kiro/steering/versioning-and-changelog.md`); 14.1, 14.2_
    - _Design: CHANGELOG Entry_
    - **Verify**: `head -30 CHANGELOG.md` shows the new `## [1.10.3]` section above the existing `## [1.10.2]` section, with both `Fixed` and `Security` subsections present, and the `Notes` subsection if Option A was selected.

- [x] 18. Commit and push to origin (no production deploy)
  - [x] 18.1 Stage only the files this spec touches
    - Stage exclusively: `app/modules/vehicles/service.py`, `app/modules/vehicles/router.py`, `app/modules/invoices/service.py`, `app/modules/invoices/schemas.py`, `app/modules/invoices/public_router.py`, `app/modules/kiosk/service.py`, `app/modules/fleet_portal/services/vehicle_service.py`, `app/modules/fleet_portal/router.py`, `app/modules/bookings/service.py`, `app/modules/customers/service.py`, `app/modules/customers/router.py`, `app/modules/customers/schemas.py`, `app/modules/organisations/dashboard_service.py`, `app/modules/notifications/service.py`, `app/modules/notifications/reminder_queue_service.py`, `app/modules/data_io/service.py`, `app/modules/admin/router.py` (one-line comment only), `tests/test_vehicle_data_isolation.py`, `tests/integration/test_vehicle_promotion_trigger_sites.py`, `scripts/test_vehicle_data_isolation_e2e.py`, `pyproject.toml`, `frontend/package.json`, `CHANGELOG.md`, and the three spec docs `.kiro/specs/vehicle-data-isolation/{requirements,design,tasks}.md`
    - Do **not** use `git add .` — explicit per-file staging avoids picking up unrelated working-tree changes (env files, IDE settings, untracked artefacts)
    - Run `git status` after staging and confirm the staged set matches the list above
    - _Requirements: (release discipline — `.kiro/steering/versioning-and-changelog.md`)_
    - **Verify**: `git diff --cached --name-only` output is a strict subset of the enumerated list; no `.env*`, `.kiro/settings/`, or other unrelated files appear.

  - [x] 18.2 Commit with a descriptive message and push to the current branch on origin
    - Commit message: `fix(vehicles): isolate customer-driven vehicle data per organisation` followed by a body summarising the four pre-existing bug fixes absorbed and the new audit-log actions
    - Push to the **current branch** on `origin` with `git push -u origin HEAD` (so the branch is created on remote if it does not exist, and tracking is set up)
    - Do **not** push to `main`/`master` directly unless the user explicitly confirms — if the current branch is `main`, stop and ask the user to confirm or specify a feature branch name
    - Do **not** trigger any deployment, rebuild, or container restart on any environment from this task. Production deployment is out of scope for this spec
    - _Requirements: (release discipline — `.kiro/steering/versioning-and-changelog.md`)_
    - **Verify**: `git log -1 --pretty=format:'%H %s'` shows the new commit at HEAD; `git status` reports a clean working tree; `git rev-parse --abbrev-ref --symbolic-full-name @{u}` shows the upstream tracking branch on `origin`.

## Notes

- All tasks are required; no task is marked optional.
- No database migration ships with this feature (Req 8). The deployment artefact is application code only.
- The `ix_org_vehicles_org_rego` index referenced in the design's Performance section is **deferred** to a follow-up if real-world measurement shows a regression — it is intentionally not part of this plan.
- `mobile/package.json` (currently 1.9.5) is left untouched; the pre-existing drift is out of scope for this spec and will be reconciled in a separate release.
- Each task references the exact requirement clauses it satisfies and the design section it implements, so reviewers can audit traceability without cross-referencing other documents.
- Per `implementation-completeness-checklist.md` Rule 9, every task carries an explicit `Verify:` line stating the command, assertion, or check that proves the task is done.
- **Production deployment is explicitly out of scope** for these tasks. The plan ends at `git push` (Task 18). The user will perform the staged-rollout deploy (local standby → Pi standby → Pi prod) separately, following the standard runbook (DB backup, volume backup, tar+SSH sync, `docker compose up -d --build --force-recreate app`, frontend rebuild dance).

### Pre-deploy operational checks (run these manually before deploying — not coding tasks)

These were briefly considered as tasks but are operational steps the user runs against live environments. They are listed here so they are not forgotten when the deploy is scheduled.

1. **Duplicate `(org_id, rego)` scan in `org_vehicles`** — the new helpers assume `(org_id, rego)` is unique. Pre-existing duplicates would cause `promote_vehicle()` to silently pick whichever row sorts first inside the advisory lock and split downstream writes across both rows. Run on every target environment before applying the new code:
   ```sql
   SELECT org_id, rego, count(*) AS dupes
   FROM org_vehicles
   GROUP BY 1, 2
   HAVING count(*) > 1
   ORDER BY dupes DESC, org_id, rego;
   ```
   If the query returns zero rows on every environment: proceed. If duplicates exist: stop. Resolve them manually (consolidate Customer_Driven_Fields into the canonical row, repoint any `customer_vehicles` and `odometer_readings` references, then `DELETE` the redundant row) before deploying.
2. **DB and volume backup before Pi prod** — standard pre-deploy backup steps (`pg_dump -F c`, tar of uploads + compliance volumes) per the project deployment runbook.
3. **Run the OWASP e2e script (Task 15) against each environment after deploy** — confirms the isolation property holds under live RLS and module-gating configuration.

### Pre-existing bugs absorbed into this PR

Seven pre-existing defects were uncovered while auditing the trigger sites and the read paths. All seven are fixed in the same change because the spec already touches the affected functions or queries — splitting them into separate PRs would mean editing the same lines twice.

1. **Fleet portal odometer log uses non-existent column name** (Task 6.1 addendum). `app/modules/fleet_portal/services/vehicle_service.py::log_odometer_reading` references `OdometerReading.odometer_km` for both the `func.max` aggregation and the constructor kwarg; the actual column on the model is `reading_km`. The function would TypeError on first invocation. Fixed in the same patch that switches its target table from `global_vehicles` to `org_vehicles`.
2. **`update_invoice` lacks `vehicle_cof_expiry_date` schema field AND branch** (Task 4.3 addendum). `create_invoice` writes WOF, COF and service-due, but `update_invoice` only handles WOF and service-due. Two coordinated gaps: (a) `InvoiceUpdateRequest` schema has no `vehicle_cof_expiry_date` field, so the value never enters `updates`; (b) the resolution-check at L2474 doesn't include COF as a trigger; (c) there's no COF branch in the service layer. All three are fixed together. Editing an issued invoice's COF expiry is currently a silent no-op.
3. **`update_customer_vehicle_dates` silently drops `cof_expiry`** (Task 10.1 addendum). The endpoint `PUT /api/v1/customers/{customer_id}/vehicle-dates` only handles `service_due_date` and `wof_expiry`. Same parity gap as #2 in a different code path. Fixed in the same patch that switches its writes from `global_vehicles` to `org_vehicles`.
4. **Dashboard expiry-reminders widget queries a non-existent column** (Task 11.3 addendum). `app/modules/organisations/dashboard_service.py::list_expiring_reminders` joins `org_vehicles ov ON ov.global_vehicle_id = gv.id`, but `org_vehicles.global_vehicle_id` is not a column on the model. The widget would error on any non-empty result set. Either it was never exercised in production (1-org early-prod state) or schema evolution since first authoring left the SQL stranded. Fixed by replacing the query with one that reads from `org_vehicles` directly and falls back to `global_vehicles` only for un-promoted links.
5. **Invoice display reads `global_vehicles` first, leaking cross-tenant Customer_Driven_Fields** (Task 11.5 addendum). `app/modules/invoices/service.py::get_invoice_detail` and `app/modules/invoices/public_router.py` both look up `GlobalVehicle` by rego first and only fall back to `OrgVehicle` if `gv is None`. Because `gv` almost always exists for a CarJam-pulled rego, the `OrgVehicle` fallback never fires, so every org reads whichever org last wrote to `global_vehicles`. This **is** the bug the rest of the spec is closing — it just happens on the read side. Fixed by inverting the lookup order to prefer `OrgVehicle` (org_id-scoped) over `GlobalVehicle`.
6. **Notification/reminder services use inner joins that drop promoted links** (Task 11.6 addendum). Three call sites in `notifications/service.py` and `notifications/reminder_queue_service.py` do `select(...).join(GlobalVehicle, CustomerVehicle.global_vehicle_id == GlobalVehicle.id)`. After promotion, `cv.global_vehicle_id IS NULL`, so the inner join silently drops the row. Post-deploy, no WOF/COF/Rego/service-due reminders fire for any promoted vehicle. Fixed by replacing each inner join with a two-pass query covering both link types, plus standardising the dedup-subject key on `cv.id` (stable across promotion) instead of `gv.id`/`ov.id`.
7. **Data export CSV mislabels promoted vehicles as "manual"** (Task 11.4 addendum). `app/modules/data_io/service.py::export_vehicles_csv` already pre-loads all `OrgVehicle` rows for the org and runs a separate query for global-linked vehicles, so promoted rows are not dropped — they just get the wrong `lookup_type` label. The function hardcodes `"manual"` at L749 for every org_vehicles row, but promoted rows have `is_manual_entry=False` and were originally CarJam-sourced. Fix: replace the literal with `("manual" if v.is_manual_entry else "carjam")`. No structural join change required.

### Operational observations (no separate task)

These are deployment- and test-fixture-level details surfaced during the audit; they don't warrant their own tasks but reviewers should keep them in mind.

- **Module-gate cache (defence-in-depth)**: `promote_vehicle` calls `ModuleService(db).is_enabled(str(org_id), "vehicles")` on every promotion. In a single request handler that triggers multiple promotions (e.g. an invoice with several line-item odometer updates) this can run repeatedly. Consider caching the result on `request.state` for the lifetime of the request when implementing Task 1.1; it is not load-bearing for correctness, only an O(N→1) optimisation.
- **Concurrency-test fixture must use two real connections**: Task 14.2's `test_concurrent_promotions_produce_single_org_row` will give a false-positive pass if both `promote_vehicle` calls share a single `AsyncSession` — Postgres advisory transaction locks held by the same backend pid don't contend. The test fixture must explicitly open two distinct `AsyncSession` objects, each from `async_sessionmaker` bound to the test engine, and drive them with `asyncio.gather`. A reviewer should sanity-check the fixture writes two sessions, not one.

