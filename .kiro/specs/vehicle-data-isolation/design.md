# Design Document — Vehicle Data Isolation

## Pre-Design Verification

Before writing the design, two facts about the existing schema were verified by inspecting the codebase, because the design depends on them.

**1. Does `org_vehicles` have a UNIQUE constraint on `(org_id, rego)`?**

No. The original `org_vehicles` table was created in `alembic/versions/2025_01_15_0003-0003_create_vehicle_tables.py`. Its constraints are:

- `PRIMARY KEY (id)`
- `FOREIGN KEY (org_id) -> organisations.id` (constraint `fk_org_vehicles_org_id`)
- Row-Level Security enabled

Migration `0105_add_extended_fields_to_org_vehicles` adds spec columns but no constraints or indexes. There is **no** `UniqueConstraint("org_id", "rego")`, no `idx_org_vehicles_rego` index, and no functional unique index on the table. A `grepSearch` for `idx_org_vehicles|create_index.*org_vehicles` returned no matches.

**Consequence**: we cannot use `INSERT ... ON CONFLICT (org_id, rego) DO NOTHING` to serialise concurrent promotions. Per Requirement 8 (no schema changes), we must not add such a constraint in this feature. This design uses `pg_advisory_xact_lock(hashtext(org_id::text || ':' || rego))` to serialise concurrent promotion attempts for the same `(org_id, rego)` pair within a single transaction. Advisory locks are a built-in PostgreSQL feature, require no schema change, are released automatically at transaction end, and are scoped per-database — they do not block other tenants.

**2. Does the codebase already use `pg_advisory_xact_lock` anywhere?**

No. A `grepSearch` for `pg_advisory_xact_lock|pg_advisory_lock` returned zero matches. This will be the first use. The lock is invoked via raw SQL through `db.execute(text("SELECT pg_advisory_xact_lock(:k1, :k2)"), {...})`. Two-key form is used to keep collision risk low.

**3. Does `customer_vehicles.vehicle_link_check` already enforce the either-or invariant?**

Yes, confirmed in `app/modules/vehicles/models.py`:

```
CheckConstraint(
    "(global_vehicle_id IS NOT NULL AND org_vehicle_id IS NULL) OR "
    "(global_vehicle_id IS NULL AND org_vehicle_id IS NOT NULL)",
    name="vehicle_link_check",
)
```

The promotion path swaps `global_vehicle_id` and `org_vehicle_id` atomically within the same transaction; the constraint never sees an intermediate violating state because both columns are updated in one `UPDATE`.

---

## Overview

`global_vehicles` is a cross-organisation cache populated by CarJam. It currently doubles as the storage for customer-driven operational state — odometer reading, service-due date, WOF expiry, COF expiry, inspection type. Any organisation that records a service against a rego pollutes the cross-tenant cache, so the next organisation looking up the same rego sees the previous workshop's data. This is a tenant-isolation defect.

This feature redirects every customer-driven write away from `global_vehicles` and into the organisation's own `org_vehicles` row. The redirection is implemented as **lazy promotion**: the first customer-driven write or link operation on a given `global_vehicles`-backed rego promotes that rego for that organisation by copying the row into `org_vehicles` (preserving the data the org currently sees via Read_Fallback). All subsequent customer-driven writes within that organisation target the `org_vehicles` row. CarJam refresh continues to write the spec cache on `global_vehicles`.

The feature is **backend-only**, **schema-stable**, and **API-stable**. Every existing API endpoint, request body, response shape, frontend payload, and rendered PDF remains byte-identical. The only observable change is that customer-driven fields stay private to the writing organisation.

The implementation centralises promotion in a single helper, `promote_vehicle()`, which is invoked from every promotion trigger site enumerated in Requirement 3. Concurrency is handled via PostgreSQL advisory locks; idempotency is preserved by re-checking inside the lock and returning the existing row if another transaction won the race.

This design does NOT propose schema changes, data migration, frontend changes, mobile-app changes, or replacement of any existing helper. It augments minimally per `no-shortcut-implementations.md`.

---

## Architecture

### Three Tables, Two Roles

```
+-------------------+        +-------------------+        +---------------------+
|  global_vehicles  |        |    org_vehicles    |        |  customer_vehicles  |
|  (CarJam cache)   |        |  (per-org snapshot)|        |  (link table)       |
+-------------------+        +-------------------+        +---------------------+
| id (PK)           |        | id (PK)            |        | id (PK)             |
| rego              |<-------+ org_id            |<-------+ org_id              |
| make/model/year   | copy   | rego (no UQ)      |        | customer_id         |
| vin/chassis/...   | on     | make/model/year   |        | global_vehicle_id ?+--+
| wof_expiry        | promote| vin/chassis/...   |        | org_vehicle_id    ?+-+|
| cof_expiry        |        | wof_expiry        |        | (either-or check)   ||
| odometer_last_... |        | cof_expiry        |        +---------------------+|
| service_due_date  |        | odometer_last_... |                                |
| ...               |        | service_due_date  |                                |
+-------------------+        | is_manual_entry=F |                                |
        ^                    +-------------------+                                |
        |                              ^                                          |
        | CarJam refresh               | Customer-driven writes after promotion   |
        | + admin bulk import          | (invoice, kiosk, fleet portal, etc.)     |
        | (UNCHANGED)                  |                                          |
        +-(read fallback when no org_vehicles row)-------------------------------+
```

### Data Flow

**First write to a rego inside Org A** (rego previously only existed as a `global_vehicles` row):

1. Customer-driven flow (e.g. invoice create) computes a Customer_Driven_Field value.
2. Flow calls `promote_vehicle(db, org_id=A, global_vehicle_id=<gv.id>, source_record=<gv>)`.
3. `promote_vehicle` takes `pg_advisory_xact_lock(hashtext(...))`, re-checks, finds nothing, copies the `global_vehicles` row into `org_vehicles`, sets `is_manual_entry=false`, writes audit log, returns the new `OrgVehicle`.
4. Flow applies the customer-driven write to the returned `OrgVehicle` (NOT to `global_vehicles`).
5. If the flow also touches an existing `customer_vehicles` link or creates a new one, it points the link at `org_vehicle_id` and clears `global_vehicle_id` via `migrate_link_to_org_vehicle()`.
6. Transaction commits atomically.

**Subsequent write to the same rego inside Org A**:

1. Customer-driven flow looks up the resolved vehicle. `_resolve_vehicle_type` already returns `("org", ov)` because the link was migrated on the previous write.
2. Flow writes directly to the `OrgVehicle`. `promote_vehicle` is not called (the steady-state path is unchanged from today's "manual-entry org_vehicles" path).

**Read of the rego inside Org B (still on `global_vehicle_id`)**:

1. `_resolve_vehicle_type` returns `("global", gv)`.
2. Read endpoints serialise from `gv` exactly as today (Read_Fallback). Nothing changes.

**Pre-existing promoted Org C reads its own snapshot**:

1. `_resolve_vehicle_type` returns `("org", ov)`.
2. Read endpoints serialise from `ov`. Same code path.

### Transaction and RLS Boundary

All promotion work runs inside the existing FastAPI request transaction (`get_db_session` opens `session.begin()`). RLS context is already set per-request via `branch_context`. The `org_vehicles` `INSERT` runs under the org's RLS policy, which already permits inserts where `org_id = current_org_id`. No bypass is required and no `SET ROLE` change is needed. Per `implementation-completeness-checklist.md` Rule 5, RLS bypass is explicitly NOT used.

---

## Data Model

No tables are created, dropped, or renamed. No columns are added, dropped, or renamed. No constraints are added, dropped, or renamed. No indexes are added or dropped.

### Field Mapping (informational only — already in the schema)

| Field | global_vehicles | org_vehicles | Owned by | Written by (after this feature) |
|---|---|---|---|---|
| `rego` | yes | yes | shared | CarJam refresh, admin import, promotion copy |
| **CarJam_Owned_Spec_Fields** | | | | |
| `make`, `model`, `year` | yes | yes (mig 0003) | CarJam | CarJam refresh + Manual_Refresh copy at promotion |
| `colour`, `body_type`, `fuel_type`, `engine_size`, `num_seats` | yes | yes (mig 0003) | CarJam | same |
| `vin`, `chassis`, `engine_no`, `transmission` | yes | yes (mig 0105) | CarJam | same |
| `country_of_origin`, `number_of_owners`, `vehicle_type` | yes | yes (mig 0105) | CarJam | same |
| `power_kw`, `tare_weight`, `gross_vehicle_mass` | yes | yes (mig 0105) | CarJam | same |
| `date_first_registered_nz`, `plate_type`, `submodel`, `second_colour` | yes | yes (mig 0105) | CarJam | same |
| `registration_expiry` | yes | yes (mig 0105) | CarJam | same |
| **Customer_Driven_Fields** | | | | |
| `odometer_last_recorded` | yes | yes (mig 0105) | servicing org | **`org_vehicles` only** post-feature |
| `service_due_date` | yes | yes (mig 0105) | servicing org | **`org_vehicles` only** post-feature |
| `wof_expiry` | yes | yes (mig 0105) | servicing org | **`org_vehicles` only** post-feature |
| `cof_expiry` | yes | yes (mig 0181) | servicing org | **`org_vehicles` only** post-feature |
| `inspection_type` | yes | yes (mig 0181) | servicing org | **`org_vehicles` only** post-feature |
| **Org-only metadata** | | | | |
| `is_manual_entry` | n/a | yes | Org_Vehicles only | set to `false` on promotion, `true` on manual add |

`global_vehicles.odometer_last_recorded`, `service_due_date`, `wof_expiry`, `cof_expiry`, `inspection_type` are NOT removed and their existing values are preserved (Req 1.6, Req 10.1). They become **read-only from customer-driven flows** and are written only by:

- `app/modules/vehicles/service.py::refresh_vehicle` (CarJam refresh — fresh CarJam data)
- `app/modules/data_io/service.py` admin bulk import
- `app/modules/vehicles/service.py::lookup_vehicle` initial CarJam fetch when first caching the rego
- `app/modules/vehicles/service.py::update_odometer_reading` for correcting historical readings (this updates `global_vehicles.odometer_last_recorded` to the recomputed max — see "Read Paths" below)

**Carve-out — `update_odometer_reading` writes to `global_vehicles.odometer_last_recorded`**: this is an explicit, documented exception to Req 1.1's prohibition on customer-driven writes to `global_vehicles`. The function corrects an existing `odometer_readings` history row (e.g. user typed `123,000` instead of `12,300`); after correction it recomputes the max across all history rows for that `global_vehicle_id` and writes that max back. The history is keyed on `global_vehicle_id` (Req 11.1), so the recomputed max is logically a property of the global cache, not a per-org operational value. Moving this write to `org_vehicles` would mean: (a) the corrected max would only apply to the calling org's snapshot; (b) any other org with a `customer_vehicles` link still pointing at the same `global_vehicle_id` would continue seeing the pre-correction max via Read_Fallback. Both behaviours are worse than the carve-out. The carve-out is acceptable because `update_odometer_reading` is a low-traffic correction flow (used to fix data-entry errors), not a hot customer-driven write path. Tests must explicitly cover the carve-out so it is not accidentally moved during future refactors.

### `customer_vehicles` Link Table

The either-or `vehicle_link_check` constraint is preserved. After promotion, the link's `global_vehicle_id` is cleared and `org_vehicle_id` is set within the same `UPDATE`, so the constraint never sees an invalid intermediate state.

### `odometer_readings` Table

Untouched. `global_vehicle_id` remains NOT NULL. All historical and new history rows continue to reference `global_vehicles` (Req 11). The `odometer_last_recorded` cache that we update on the OrgVehicle is a separate field; reading rows still come from this table.

---

## New Helper Functions

Two new module-level helpers in `app/modules/vehicles/service.py`:

### `promote_vehicle()`

```python
async def promote_vehicle(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    global_vehicle_id: uuid.UUID,
    source_record: GlobalVehicle | None = None,
    user_id: uuid.UUID | None = None,
    trigger_site: str,
    ip_address: str | None = None,
) -> OrgVehicle:
    """Idempotently ensure an org_vehicles row exists for (org_id, rego).

    Steps:
      1. If source_record is None, SELECT FROM global_vehicles WHERE id=:gvid.
         (Caller must already have FK-validated the global_vehicle_id.)
      2. Acquire pg_advisory_xact_lock keyed by hashtext(org_id || ':' || rego).
         The lock is released automatically at transaction end.
      3. SELECT FROM org_vehicles WHERE org_id=:org AND rego=:rego (still inside the
         lock — guarantees serialised re-check).
      4. If found: return it. (Idempotent path; subsequent calls in the same or
         later transactions short-circuit.)
      5. If not found:
         a. INSERT a new org_vehicles row, copying every CarJam_Owned_Spec_Field
            and every Customer_Driven_Field from source_record. is_manual_entry=False.
         b. Flush.
         c. write_audit_log(action="vehicle.promote", entity_type="org_vehicle",
                            entity_id=new.id,
                            after_value={"rego": rego, "global_vehicle_id": str(gvid),
                                         "trigger_site": trigger_site}).
         d. Return the new OrgVehicle.

    Module gating: if the `vehicles` module is NOT enabled for org_id, raise
    PermissionError. Callers that already strip vehicle fields when the module
    is disabled (create_invoice, bookings) MUST NOT reach this function for
    such orgs; this guard is defence-in-depth.
    """
```

**Performance**: 1 `SELECT` (the existence check), and on first promotion 1 `INSERT` (org_vehicles) + 1 `INSERT` (audit log). Steady state is a single `SELECT`, which mirrors the existing `_resolve_vehicle_type` lookup that callers already perform.

**Concurrency**: the advisory lock serialises the SELECT-then-INSERT against itself for the same `(org_id, rego)`. Other rego/org pairs are not blocked. Two simultaneous transactions promoting the same rego converge: the second one finds the row inserted by the first and returns it (Req 13.1, Req 13.2).

### `migrate_link_to_org_vehicle()`

```python
async def migrate_link_to_org_vehicle(
    db: AsyncSession,
    *,
    customer_vehicle_id: uuid.UUID,
    org_vehicle_id: uuid.UUID,
) -> None:
    """Atomically swap a customer_vehicles row from global_vehicle_id to
    org_vehicle_id. Single UPDATE; both columns set in the same statement so
    vehicle_link_check is never violated.
    """
    await db.execute(
        update(CustomerVehicle)
        .where(CustomerVehicle.id == customer_vehicle_id)
        .values(global_vehicle_id=None, org_vehicle_id=org_vehicle_id)
    )
    await db.flush()
```

**Multi-link migration semantics**: a single `(org_id, customer_id)` pair can have multiple `customer_vehicles` rows pointing at the same `global_vehicle_id` (e.g. two invoices each created their own link before the spec was deployed; or a manual link plus a kiosk auto-link). Callers that need to migrate every such link should iterate and call `migrate_link_to_org_vehicle` per row, OR run a single bulk UPDATE:

```python
await db.execute(
    update(CustomerVehicle)
    .where(
        CustomerVehicle.org_id == org_id,
        CustomerVehicle.global_vehicle_id == gv.id,
    )
    .values(global_vehicle_id=None, org_vehicle_id=ov.id)
)
```

The bulk UPDATE is preferred because it migrates all duplicate links atomically and avoids the per-row round-trip cost. If no `customer_vehicles` row currently points at `gv.id` for this `(org_id, customer_id)`, the UPDATE is a no-op (0 rows affected) — promotion still succeeds and subsequent flows happily use the existing `customer_vehicles` row that was just created via `org_vehicle_id`. Callers in `create_invoice`/`update_invoice`/etc. should use the bulk pattern; the single-row signature above is provided for when a specific `customer_vehicle_id` is already in scope (e.g. the fleet portal's `edit_vehicle` already has the `cv` object loaded).

### Refactored Signatures

`record_odometer_reading()` already accepts an optional `org_id`. After this feature it gains stricter behaviour, not a new parameter:

- If `org_id` is provided AND the recording flow is customer-driven (`source` in `{invoice, kiosk, manual}`): promote the vehicle for `org_id` if needed, then bump `org_vehicles.odometer_last_recorded` for that org. **Stop** updating `global_vehicles.odometer_last_recorded`.
- If `org_id` is None OR `source == "carjam"`: keep the existing CarJam behaviour (update `global_vehicles.odometer_last_recorded` from the cached value, since this is a CarJam-driven update of the spec cache).

`link_vehicle_to_customer()`: behaviour change only — it calls `promote_vehicle` and then constructs the `CustomerVehicle` with `org_vehicle_id` set and `global_vehicle_id=None`. Signature unchanged.

`update_odometer_reading()`: this corrects historical readings. It currently recomputes the max from `odometer_readings` and writes that into `global_vehicles.odometer_last_recorded`. It is NOT a customer-driven write of new state; it is a correction of the cache. To keep the cache consistent with what CarJam saw, **the existing behaviour is preserved**: it continues to update `global_vehicles.odometer_last_recorded`. The org's snapshot remains whatever was last bumped through promotion. This is acceptable per Req 4.4 (Manual_Refresh model — local snapshot may diverge from cache until refreshed).

---

## Code Changes per File

Each change site is precise. Lines are approximate (indices may shift by ±5 during work).

### `app/modules/vehicles/service.py`

- **Add** `promote_vehicle()` and `migrate_link_to_org_vehicle()` as module-level async functions near the existing `link_vehicle_to_customer`.
- **Modify** `record_odometer_reading()` (~L161): when `org_id is not None` and `source != "carjam"`, after inserting the history row, call `promote_vehicle` and bump the resulting `OrgVehicle.odometer_last_recorded` instead of `GlobalVehicle.odometer_last_recorded`. The history row itself still points at `global_vehicle_id`.
- **Modify** `link_vehicle_to_customer()` (~L696): call `promote_vehicle(...)` first, then create the `CustomerVehicle` with `org_vehicle_id=ov.id, global_vehicle_id=None`. Audit-log entry text unchanged.
- **Add** `manual_refresh_vehicle()` (new helper) for the explicit Manual_Refresh action (Req 5). Signature: `(db, *, org_id, rego, user_id, ip_address) -> OrgVehicle`. It refreshes `global_vehicles` via existing `refresh_vehicle()` if the cache is stale, then copies CarJam_Owned_Spec_Fields into the existing `org_vehicles` row (must already exist — promotion does not happen here). Customer_Driven_Fields are NOT touched. Emits audit log `action="vehicle.manual_refresh"`.
- **Verify** (per `implementation-completeness-checklist.md` Rule 9): unit test exercises `promote_vehicle` for a fresh rego and an already-promoted rego; the second invocation must hit the SELECT-and-return path, not insert.

### `app/modules/invoices/service.py`

- **Modify** `create_invoice()` link block (~L938-944): when the resolved type is `("global", gv)` and a `customer_vehicles` link is being created, call `promote_vehicle(...)`, then construct the `CustomerVehicle` with `org_vehicle_id=ov.id, global_vehicle_id=None`. The existing `if vehicle_type == "org"` branch is taken in either case after promotion.
- **Modify** `create_invoice()` field-write block (~L982-1051): the existing code already handles `vehicle_type == "org"` correctly. The change is to **promote first** when `vehicle_type == "global"` and a Customer_Driven_Field would otherwise be written, then re-resolve to org. Concretely: replace each `gv.<field> = value` write with a promotion + `ov.<field> = value` write. Remove the four `gv.wof_expiry/cof_expiry/service_due_date = ...` and the equivalent global-vehicle odometer-write paths.
- **Modify** `update_invoice()` (~L2474-2520): same rule — when the resolved vehicle is global and any of the four fields would change, promote first, then write to the org snapshot. Migrate the link if it exists (`migrate_link_to_org_vehicle`).
- **No change** to `_resolve_vehicle_type`. It already returns `("global", gv) | ("org", ov)` — exactly what the new code consumes.
- **No change** to the `vehicle_display` snapshot in `invoice_data_json`. Already-issued invoices retain their snapshot. New invoices snapshot from the org vehicle after promotion (the snapshot field set is identical).
- **Verify**: integration test creating a fresh invoice for a `global_vehicles` rego asserts (a) `org_vehicles` row created, (b) `customer_vehicles` link migrated, (c) `global_vehicles.odometer_last_recorded` unchanged, (d) `org_vehicles.odometer_last_recorded` updated.

### `app/modules/kiosk/service.py`

- **Modify** `v2_check_in` `_ensure_vehicle_linked` block: it currently calls `link_vehicle_to_customer(global_vehicle_id=...)`. Because `link_vehicle_to_customer` now promotes internally, no caller-side change is needed beyond verifying the call still passes `org_id`.
- **Modify** the OdometerReading insert block (~L510 in current file): keep the `OdometerReading.global_vehicle_id` insert as-is. After insert, also call `promote_vehicle` (idempotent if already promoted by the link step) and bump `ov.odometer_last_recorded`. **Do not** bump `gv.odometer_last_recorded`.
- **Verify**: integration test for kiosk check-in of a fresh rego asserts the same four invariants as the invoice path.

### `app/modules/fleet_portal/services/vehicle_service.py`

- **Modify** the `_record_odometer` style helper: replace the `gv.odometer_last_recorded = ...` write with a `promote_vehicle()` + `ov.odometer_last_recorded = ...` write. The OdometerReading history insert stays keyed by `global_vehicle_id`.
- **Modify** the `_FLEET_ALLOWED_FIELDS` and `_DRIVER_ALLOWED_FIELDS` update paths: when the link's resolved type is `("global", gv)` and any allowed field maps to a Customer_Driven_Field, promote first, then write to the `OrgVehicle`.
- **Verify**: integration test for fleet portal record-odometer and service-due update asserts `global_vehicles` unchanged for the test rego, `org_vehicles` updated, link migrated.

### `app/modules/fleet_portal/router.py`

- **Modify** the admin link-creation handler at ~L2032 (`cv = CustomerVehicle(...)`): if the supplied `vehicle_id` resolves to a `GlobalVehicle`, call `promote_vehicle()` first and create the `CustomerVehicle` via `org_vehicle_id`. If it already resolves to an `OrgVehicle`, behaviour is unchanged.
- **Verify**: integration test exercising the admin endpoint with a global-vehicle ID asserts promotion happened.

### `app/modules/bookings/service.py`

- **Modify** the two link-creation sites at ~L391 and ~L416 (`cv = CustomerVehicle(...)` for global vs org). For the global branch, call `promote_vehicle()` and create the link with `org_vehicle_id`.
- **Verify**: integration test creating a booking that links a fresh global-vehicle rego.

### `app/modules/customers/service.py`

- **Modify** the link-creation site at ~L994 (`cv = CustomerVehicle(...)`). Same pattern: if the supplied `vehicle_id` is a `GlobalVehicle`, promote first.
- **Modify** `update_customer_vehicle_dates` (~L1976-1985, endpoint `PUT /api/v1/customers/{customer_id}/vehicle-dates`): currently writes `gv.service_due_date` and `gv.wof_expiry` directly to `global_vehicles`. After this change: when the resolved vehicle is `("global", gv)`, promote first via `promote_vehicle(..., trigger_site="customers.update_vehicle_dates")` and write `service_due_date`, `wof_expiry`, and `cof_expiry` to the returned `OrgVehicle`. Migrate the link via `migrate_link_to_org_vehicle()` if it still points at `global_vehicle_id`. Add the missing `cof_expiry` branch to close the pre-existing parity gap with `create_invoice`.
- **Modify** `search_customers_by_query` (~L248-272, the `if include_vehicles:` block): replace the single `outerjoin(GlobalVehicle)` with a double outerjoin to both `GlobalVehicle` and `OrgVehicle`, and switch the loop body to the `v = gv if gv else ov` fallback pattern. Without this fix, post-promotion the customer's vehicle list disappears for any vehicle whose link has been migrated.
- **Modify** any other reads of `cv.global_vehicle.<field>` in this module to apply the same fallback pattern (see Read-Fallback Pattern Enumeration above).
- **Verify**: integration test for customer-vehicle link creation; integration test for `PUT /vehicle-dates` asserting all three date fields land on `org_vehicles` post-promotion; unit test asserting customer-search returns both promoted and un-promoted vehicles in `linked_vehicles`.

### `app/modules/organisations/dashboard_service.py`

- **Modify** `list_expiring_reminders` (~L632-643): the current raw SQL joins `org_vehicles ov ON ov.global_vehicle_id = gv.id` against a non-existent column on `org_vehicles` (this is a pre-existing bug — verified against `app/modules/vehicles/models.py`). Replace with a query that pulls upcoming-expiry rows from `org_vehicles` directly (filtered on `org_id`) plus a UNION query that pulls upcoming-expiry rows from `global_vehicles` for any `customer_vehicles` row in the org whose `org_vehicle_id IS NULL`. The customer-name lookup must also accept either `cv.org_vehicle_id` or `cv.global_vehicle_id` matching the dashboard row's vehicle id.
- **Verify**: unit test pre-creates one promoted `org_vehicles` row and one un-promoted `global_vehicles`-backed link with overlapping expiry windows; assert both appear in the widget output with correct customer names; an `EXPLAIN` shows no `org_vehicles.global_vehicle_id` reference in the new SQL.

### `app/modules/vehicles/router.py`

- **Modify** `vehicle_refresh` (~L220, `POST /api/v1/vehicles/{id}/refresh`): after the existing `refresh_vehicle(...)` call, look up the calling org's `org_vehicles` row for the same rego; if present, call `manual_refresh_vehicle()` so the freshly-pulled CarJam_Owned_Spec_Fields are mirrored into the per-org snapshot. Customer_Driven_Fields are not touched.
- **Modify** `bulk_refresh_vehicles` (~L496) the same way for each vehicle in the bulk request, with best-effort error handling per item.
- The global-admin endpoint at `app/modules/admin/router.py::refresh_vehicle` is **intentionally not modified** — it operates only on the cross-tenant cache. Add a one-line comment documenting this.
- **Verify**: integration test calls `POST /vehicles/{id}/refresh` against a promoted vehicle, mutates the underlying `global_vehicles` CarJam fields via stub, asserts the `org_vehicles` row's CarJam-owned spec fields now match the stub and its Customer_Driven_Fields are byte-identical to before.

### `app/modules/invoices/schemas.py`

- **Add** `vehicle_cof_expiry_date: date | None = Field(default=None, description="COF expiry date — saved to the vehicle record")` to `InvoiceUpdateRequest` (sibling of `vehicle_wof_expiry_date` at ~L417). This is a coordinated fix with the missing COF branch in `update_invoice` — without the schema field, the value never enters the `updates` dict, so any service-layer branch is unreachable. The field is already in `_LIMITED_EDIT_FIELDS` at L2227 so issued/partially_paid/overdue edits flow through naturally.
- **Verify**: a `PUT /api/v1/invoices/{id}` request body with only `vehicle_cof_expiry_date` set passes validation (no 422); the value reaches the service layer.

### `app/modules/invoices/public_router.py`

- **Modify** the rego-keyed vehicle lookup at ~L107-123: invert the order to try `OrgVehicle` (filtered by `invoice.org_id` and `func.upper(rego)`) first, fall back to `GlobalVehicle` only when no per-org row exists. Without this, the public invoice page (anonymous customer view via portal token) serves cross-tenant `global_vehicles` Customer_Driven_Fields that have been written by other workshops.
- The schema of the returned `vehicle` dict is identical in both branches (both `OrgVehicle` and `GlobalVehicle` expose the same `rego/make/model/year/wof_expiry/cof_expiry/odometer_last_recorded` attributes per migrations 0003+0105+0181) — no Pydantic schema change, no frontend change.
- **Verify**: integration test loads the public invoice for an Org A invoice and asserts the page returns Org A's `wof_expiry` even when Org B has separately written a different value to the shared `global_vehicles` row.

### `app/modules/notifications/service.py`

- **Modify** `process_wof_rego_reminders` (~L1465-1485): replace the INNER join `CustomerVehicle.global_vehicle_id == GlobalVehicle.id` with a two-pass query. First pass filters `customer_vehicles` rows where `global_vehicle_id IS NOT NULL` and joins `GlobalVehicle` on the expiry field; second pass filters where `org_vehicle_id IS NOT NULL` and joins `OrgVehicle` on the same field. Both passes return the same row shape (`cv, vehicle, customer`) so the downstream send/dedup loop is unchanged except for the dedup-key stabilisation below.
- **Modify** `process_customer_reminders` (~L2066-2110) the same way — same inner-join → two-pass pattern.
- **Stabilise the dedup subject key**: change the existing pattern `f"{template_type}_{org_id}_{gv.id}_{expiry_date_str}"` to `f"{template_type}_{org_id}_{cv.id}_{expiry_date_str}"`. The link id (`cv.id`) is stable across promotion; the resolved vehicle id (`gv.id` vs `ov.id`) changes when a link is migrated, which would otherwise re-fire reminders that have already been sent.
- **Verify**: unit tests assert reminders fire for both promoted and un-promoted links, and that promoting a vehicle between two reminder runs does not cause a duplicate send.

### `app/modules/notifications/reminder_queue_service.py`

- **Modify** `_process_customer_reminders` (~L192-201): same inner-join → two-pass conversion as `notifications/service.py`. Apply the same dedup-key stabilisation if this service emits dedup-keyed entries.
- **Verify**: integration test exercises the reminder queue against an org with a mix of promoted and un-promoted linked vehicles; both classes generate reminder entries.

### `app/modules/data_io/service.py`

- **Modify** `export_vehicles_csv` (~L683-760): the function pre-loads **all** `OrgVehicle` rows for the org via `select(OrgVehicle).where(OrgVehicle.org_id == org_id)` (~L699), then runs a **separate** `select(GlobalVehicle).join(CustomerVehicle, ...)` query (~L705) for global-linked vehicles. Promoted vehicles **already appear** in the output via the org_vehicles loop — the actual bug is the hardcoded `lookup_type="manual"` literal at L749 which mislabels promoted-from-CarJam rows. Fix: replace the literal with `("manual" if v.is_manual_entry else "carjam")`. No structural join change is needed
- The bulk-import path in the same module is unchanged — it writes to `global_vehicles` (Req 4.2)
- **Verify**: regression test asserts a CSV export with one manual-entry org row and one promoted org row labels them `"manual"` and `"carjam"` respectively, and both regos appear in the output exactly once.

### Other modules — verified untouched

The following modules read vehicle data but do not write Customer_Driven_Fields, and require **no changes**:

- `app/modules/quotes/service.py` — uses `_resolve_vehicle_type` for display only.
- `app/modules/job_cards/service.py` — uses `vehicle_display` snapshot from invoice.
- `app/modules/recurring/service.py` — passes through invoice creation, which is already covered.
- `app/modules/invoices/email.py` and PDF rendering — read from `vehicle_display` snapshot.
- `app/modules/vehicles/service.py::lookup_vehicle` — writes the **CarJam cache** on `global_vehicles`, which is allowed and explicitly preserved (Req 4.1).
- `app/modules/data_io/service.py` admin **bulk import** path — writes to `global_vehicles` (Req 4.2). Unchanged. **Note**: the `export_vehicles_csv` function in the same module **does** require modification (see Task 11.4) because it inner-joins on `global_vehicle_id` and would silently drop promoted vehicles from the CSV export.

---

## Read Paths

Every read path is **unchanged** in behaviour. Each is documented here so reviewers can confirm the design preserves Req 9.

### `_resolve_vehicle_type(db, vehicle_id, org_id)`

Returns `("org", OrgVehicle)` if the ID matches an `org_vehicles` row scoped to `org_id`, else `("global", GlobalVehicle)` if it matches a `global_vehicles` row, else `None`. This already serves Read_Fallback per Req 6 — no change.

### Rego-backfill in `create_invoice()` (added by `invoice-vehicle-info-display`)

```
1. Look up OrgVehicle by (org_id, rego) — preferred snapshot.
2. Fall back to GlobalVehicle by rego — Read_Fallback.
3. Backfill make/model/year if the request did not supply them.
```

This is **the correct read order** and stays as-is. Promoted orgs see their snapshot; unpromoted orgs see the global cache. This is exactly Req 6.

### `email_invoice` and PDF rendering

These flows source vehicle fields from `invoice_data_json["vehicle_display"]`, which was captured at invoice-write time. They never re-read from `global_vehicles` or `org_vehicles`. No change.

### Fleet portal vehicle-list / vehicle-detail / fleet-summary

These flows already join through `customer_vehicles` and resolve the linked vehicle row. After this feature, links migrated by promotion resolve through `org_vehicle_id` (returning the snapshot), and unmigrated links resolve through `global_vehicle_id` (returning the global cache). The resolution pattern is `_resolve_vehicle_type`-equivalent. No change to the resolver logic.

### `vehicle_display` snapshot

The snapshot already captures the fields the invoice rendered. Promoted orgs snapshot from the org vehicle; unpromoted orgs snapshot from the global vehicle. The snapshot dict has the same keys in both cases. No frontend change.

### Read-Fallback Pattern Enumeration (post-promotion correctness)

Once a `customer_vehicles` link is migrated to `org_vehicle_id`, any read code that uses `cv.global_vehicle.<field>` without falling through to `cv.org_vehicle.<field>` will silently render NULL. The canonical pattern, already used correctly by `app/modules/fleet_portal/services/vehicle_service.py`, is:

```python
v = cv.global_vehicle if cv.global_vehicle is not None else cv.org_vehicle
if v is None:
    continue  # or render an "unlinked" placeholder
# read v.rego, v.make, etc.
```

Files that implement this pattern correctly today and need no change:

- `app/modules/fleet_portal/services/vehicle_service.py::list_vehicles_for_session`, `get_vehicle`, `log_odometer_reading`
- `app/modules/invoices/service.py::create_invoice` and `update_invoice` (via `_resolve_vehicle_type`)
- `app/modules/quotes/service.py` (via `_resolve_vehicle_type`)
- `app/modules/vehicles/service.py::lookup_vehicle` (cascading lookup already considers both tables)
- `app/modules/kiosk/service.py::lookup_vehicle_for_kiosk` (cascading lookup considers `org_vehicles` first)

Files that are **currently broken under promotion** and must be fixed in this PR (see tasks 11.1 – 11.7):

- `app/modules/customers/service.py::search_customers_by_query` (the `if include_vehicles:` block) — currently `outerjoin(GlobalVehicle)` only, drops promoted vehicles
- `app/modules/customers/service.py::get_customer_detail` and any other customer endpoint that returns `linked_vehicles` — same single-source bug
- `app/modules/organisations/dashboard_service.py::list_expiring_reminders` — raw SQL joins `org_vehicles` on a non-existent column and reads expiry fields only from `gv`
- `app/modules/invoices/service.py::get_invoice_detail` (~L1697-1782) — looks up `GlobalVehicle` by rego first, falls back to `OrgVehicle` only when `gv is None`. Because `gv` almost always exists, the org-vehicle fallback never fires; every invoice page leaks whichever org last wrote to `global_vehicles`. Fix: invert the order to prefer `OrgVehicle` (org_id-scoped) over `GlobalVehicle`. Same pattern in `app/modules/invoices/public_router.py` (~L107-123) and the `additional_vehicles` enrichment block at `service.py:1755-1782`
- `app/modules/notifications/service.py::process_wof_rego_reminders` (~L1465-1485) — `select(...).join(GlobalVehicle, CustomerVehicle.global_vehicle_id == GlobalVehicle.id)` is an INNER join that drops every promoted link. Post-deploy, no WOF/COF/Rego expiry reminders fire for any promoted vehicle. Fix: two-pass query covering both link types
- `app/modules/notifications/service.py::process_customer_reminders` (~L2066-2110) — same inner-join pattern, same fix
- `app/modules/notifications/reminder_queue_service.py::_process_customer_reminders` (~L192-201) — same inner-join pattern, same fix. **Dedup-key change required**: the existing dedup subject keyed on `gv.id` would re-fire after promotion (since the resolved vehicle's id changes from `gv.id` to `ov.id`). Standardise on `cv.id` (the link id) which is stable across promotion
- `app/modules/data_io/service.py::export_vehicles_csv` (~L683-760) — pre-existing two-query approach already covers both link types, but the `lookup_type` column is hardcoded to `"manual"` for every org_vehicles row. Promoted rows have `is_manual_entry=False` and were originally CarJam-sourced, so they're mislabelled. Fix: replace the `"manual"` literal at L749 with `("manual" if v.is_manual_entry else "carjam")`
- **Link-existence checks at every link-creation site** — four code paths (`kiosk/service.py::_ensure_vehicle_linked`, `bookings/service.py` auto-link, `invoices/service.py::create_invoice` link block, `fleet_portal/router.py::admin_link`) check whether a `customer_vehicles` row already exists by matching only `global_vehicle_id`. After promotion migrates a link to `org_vehicle_id`, every subsequent touch of the same vehicle creates a duplicate `customer_vehicles` row. Fix: widen each existence check so that a link is considered to exist if any `customer_vehicles` row in the org and customer scope points at either the matching `global_vehicles.id` OR the matching `org_vehicles.id` (joined on rego). See Task 11.7 for per-site fixes

Files that **read from `global_vehicles` only and that is correct** (no fallback needed):

- `app/modules/admin/router.py::refresh_vehicle` — global-admin route, intentionally cache-only
- `app/modules/vehicles/service.py::refresh_vehicle` — writes to the cross-tenant cache only
- `app/modules/data_io/service.py` admin bulk import — writes to the cross-tenant cache only

The PR description must include a grep-driven sweep showing zero remaining `cv.global_vehicle.<field>` reads outside the categories above (Task 11.4).

### Link-Existence Check Pattern (Req 3.4 — duplicate-link prevention)

Every code path that creates a `customer_vehicles` row must first check whether such a link already exists for the same `(org_id, customer_id, vehicle)`. Today, four sites do this check by matching only `CustomerVehicle.global_vehicle_id == :vehicle_id`:

- `app/modules/kiosk/service.py::_ensure_vehicle_linked` (idempotency guard)
- `app/modules/bookings/service.py` auto-link block
- `app/modules/invoices/service.py::create_invoice` link-existence query (the `else` branch when `vehicle_type == "global"`)
- `app/modules/fleet_portal/router.py::admin_link` `existing_link_q` builder

After promotion migrates a link from `global_vehicle_id` to `org_vehicle_id`, the existence check returns "no row found" because it only inspects `global_vehicle_id`. The flow then creates a **second** `customer_vehicles` row pointing at `org_vehicle_id`. Result: duplicate links per `(org_id, customer_id, vehicle)`. Symptoms surface in the customer profile (same vehicle listed twice) and in fleet portal admin (409-conflict bypass).

The canonical fix is to widen the check so a link is considered to exist if any `customer_vehicles` row in the `(org_id, customer_id)` scope points at either:

1. The matching `global_vehicles.id` for the rego, **or**
2. The matching `org_vehicles.id` for the rego (within the same `org_id`)

Implementation pattern:

```python
# Resolve the rego once from whichever source we have
target_rego = source_record.rego  # gv.rego or ov.rego depending on caller

# Find any link that points at either side of the same rego
existing = (
    select(CustomerVehicle)
    .outerjoin(GlobalVehicle, CustomerVehicle.global_vehicle_id == GlobalVehicle.id)
    .outerjoin(OrgVehicle, CustomerVehicle.org_vehicle_id == OrgVehicle.id)
    .where(
        CustomerVehicle.org_id == org_id,
        CustomerVehicle.customer_id == customer_id,
        or_(
            func.upper(GlobalVehicle.rego) == target_rego.upper(),
            and_(
                func.upper(OrgVehicle.rego) == target_rego.upper(),
                OrgVehicle.org_id == org_id,
            ),
        ),
    )
    .limit(1)
)
```

After Task 11.7 the four sites use this widened pattern. The `_ensure_vehicle_linked` helper becomes idempotent across promotion; bookings, invoices, and fleet-portal-admin link creation refuse to add duplicates and (where applicable) return their existing 409 responses.

---

## Concurrency and Idempotency Strategy

### The Race

Two simultaneous customer-driven flows in the same org both look up the same `global_vehicles` rego that has no `org_vehicles` row. Each calls `promote_vehicle(org_id=A, global_vehicle_id=G)`. Without coordination, both insert; the second insert succeeds because there is no UNIQUE on `(org_id, rego)`. Result: two `org_vehicles` rows for the same `(A, rego)` — a violation of Req 13.1.

### Why Not Add a Unique Constraint

Per Requirement 8 (no schema changes), this design must not add a constraint. Adding one would also require a backfill migration to deduplicate any pre-existing offending rows in production (the existing manual-entry flow has historically allowed `(org_id, rego)` duplicates because no constraint forbade them). Both effects are out of scope.

### Why Not `ON CONFLICT`

`ON CONFLICT (org_id, rego) DO NOTHING` requires an existing UNIQUE constraint or partial unique index to be the conflict target. Without one, this raises `there is no unique or exclusion constraint matching the ON CONFLICT specification`.

### The Chosen Approach: PostgreSQL Advisory Locks

Inside `promote_vehicle`, before the existence check:

```python
key = hashlib_or_pg_hashtext(org_id, rego)  # see implementation note below
await db.execute(
    text("SELECT pg_advisory_xact_lock(:k1, :k2)"),
    {"k1": int_key_high, "k2": int_key_low},
)
```

`pg_advisory_xact_lock(int4, int4)` takes two 32-bit integer keys and holds the lock for the duration of the current transaction. The lock is released automatically on COMMIT or ROLLBACK. Two transactions calling with the same key serialise; transactions calling with different keys do not block each other.

**Key derivation**: high32 = `hashtext(org_id::text)`, low32 = `hashtext(rego)`. Using `hashtext` (PostgreSQL's stable hash function) is computed inside the same SQL statement that takes the lock:

```python
await db.execute(
    text(
        "SELECT pg_advisory_xact_lock("
        "  hashtext(:org_id_str)::int, "
        "  hashtext(:rego)::int"
        ")"
    ),
    {"org_id_str": str(org_id), "rego": rego},
)
```

`hashtext` returns `int4` directly, so no Python-side hashing is needed.

**Collision risk**: a 64-bit key space split as two `int4` slots. Collisions between unrelated `(org, rego)` pairs are vanishingly unlikely and harmless — at worst they cause one extra serialisation point. The only correctness invariant is "same key → serialised", which `hashtext` satisfies.

### Convergence

Inside the lock:

1. SELECT `org_vehicles WHERE org_id=:org AND rego=:rego`. If found, return it. (The losing transaction in a race lands here — Req 13.2 satisfied.)
2. If not found, INSERT and return the new row.

The losing transaction never inserts a duplicate. The winning transaction's insert is visible to the loser because the loser's SELECT runs after the winner's COMMIT (advisory locks block until the lock-holder's transaction ends).

### Idempotency

`promote_vehicle` is idempotent by construction: if the row exists, return it. The function can be called twice in the same flow (once for promotion, once for safety-net) without producing different state.

`migrate_link_to_org_vehicle` is idempotent: setting `org_vehicle_id=:ov AND global_vehicle_id=NULL` is a write that can repeat without changing the resulting row. The same payload produces the same end-state (Req 13.3).

---

## Audit Logging

Two new audit actions, plus continued use of one existing action.

| Action | When emitted | `entity_type` | `entity_id` | `after_value` |
|---|---|---|---|---|
| `vehicle.promote` | Inside `promote_vehicle` immediately after a new row is inserted | `org_vehicle` | new `OrgVehicle.id` | `{"rego": rego, "global_vehicle_id": str(gvid), "trigger_site": <name>}` |
| `vehicle.manual_refresh` | Inside `manual_refresh_vehicle` after copying CarJam fields | `org_vehicle` | existing `OrgVehicle.id` | `{"rego": rego, "global_vehicle_id": str(gvid)}` |
| `vehicle.link_customer` | Inside `link_vehicle_to_customer` (existing) | `customer_vehicle` | link id | `{"vehicle_id": str(gv_or_ov), "customer_id": ..., "rego": ...}` (existing payload) |

`trigger_site` values: `vehicles.link`, `invoices.create`, `invoices.update`, `kiosk.v2_check_in`, `fleet_portal.record_odometer`, `fleet_portal.update_field`, `fleet_portal.admin_link`, `fleet_portal.carjam_import`, `bookings.link`, `customers.link`, `vehicles.record_odometer_reading`. The string is fixed at the call site (caller passes it), giving operators a clear forensic trail (Req 14).

`org_id` and `user_id` are passed to `write_audit_log` as **top-level keyword arguments** that map to dedicated columns on the `audit_log` table (matching the existing `write_audit_log` signature in `app/core/audit.py:35`). They are **NOT** embedded inside the `after_value` JSON payload. Req 14.3 is satisfied by the `audit_log.org_id` and `audit_log.user_id` columns being populated, not by JSON keys. Implementers must not move them into `after_value` — doing so would silently break the existing audit-log query/filter tooling that joins on those columns.

---

## Backwards Compatibility

| Surface | Guarantee | Mechanism |
|---|---|---|
| Existing invoices | Render byte-identical | `vehicle_display` snapshot was captured at write-time and is read as-is |
| Existing quotes | Render byte-identical | quote vehicle fields likewise sourced from snapshot or invoice |
| Existing job cards | Render byte-identical | source from invoice snapshot |
| Existing customer_vehicles links pointing at `global_vehicle_id` | Continue to resolve and render | Read_Fallback via `_resolve_vehicle_type` returns `("global", gv)` until promotion |
| Existing `global_vehicles` rows | Values preserved exactly | No write touches them from this feature; only the spec-cache writers (`refresh_vehicle`, admin import, `lookup_vehicle`) write |
| Existing `org_vehicles` manual-entry rows | Continue to work | Promotion path is keyed by `(org_id, rego)`; if a manual-entry row already exists for the same rego, **promotion finds it and reuses it** (idempotent path). The matching rule keys on `rego` (not `global_vehicle_id`) precisely because a pre-existing manual-entry row may have been created before the rego was CarJam-imported |
| Existing odometer history | Untouched | All rows continue to point at `global_vehicle_id` |
| Existing fleet portal data | Untouched | Read paths unchanged; first write per portal endpoint promotes |
| Existing API contracts | Stable | No request/response shape change anywhere |
| Existing PDFs | Stable | Source from `vehicle_display` snapshot |

**Critical edge case**: an org that already has a manual-entry `org_vehicles` row for `rego=ABC123` and **separately** has a `customer_vehicles` link pointing at `global_vehicles.id` for the same `rego=ABC123`. This can occur today because there is no UNIQUE constraint and because `link_vehicle_to_customer` does not check for an existing manual-entry row. After this feature, the first customer-driven write through that link will:

1. Resolve the link as `("global", gv)`.
2. Call `promote_vehicle(org_id=A, global_vehicle_id=G)`.
3. Inside `promote_vehicle`, the SELECT-by-rego finds the **pre-existing manual-entry row** and returns it.
4. **CarJam-owned spec-field backfill**: a manual-entry row may have NULL values for fields the org never typed in (`vin`, `make`, `model`, `year`, `colour`, `body_type`, `fuel_type`, `engine_size`, `num_seats`, `chassis`, `engine_no`, `transmission`, `country_of_origin`, `number_of_owners`, `vehicle_type`, `power_kw`, `tare_weight`, `gross_vehicle_mass`, `date_first_registered_nz`, `plate_type`, `submodel`, `second_colour`, `registration_expiry`). Because we now have a richer `global_vehicles` source row for the same rego, `promote_vehicle` **fills any NULL CarJam-owned spec field on the existing manual-entry row from the matching field on `global_vehicles`** before returning. Customer_Driven_Fields (`odometer_last_recorded`, `service_due_date`, `wof_expiry`, `cof_expiry`, `inspection_type`) and `is_manual_entry` itself are **never** overwritten — the manual-entry row keeps its `is_manual_entry=true` flag. The audit log entry includes `"merged_manual_entry": true` in `after_value` so operators can distinguish reuse-with-backfill from a fresh insert.
5. The flow writes its Customer_Driven_Field to that row.
6. `migrate_link_to_org_vehicle` points the link at the manual-entry row.

This is the correct behaviour: the org is "merged" into a single row per rego, and no duplicate is created. This is precisely why `promote_vehicle` keys its existence check on `(org_id, rego)` rather than on `(org_id, global_vehicle_id)`.

---

## Module Gating

Per `vehicle-carjam-module-gating.md`:

- The `vehicles` module gate is preserved at every existing gate site.
- `create_invoice`, `update_invoice`, and `bookings.create` already strip vehicle fields when `ModuleService(db).is_enabled(str(org_id), "vehicles") == False`. Those paths never reach `promote_vehicle` for module-disabled orgs.
- `promote_vehicle` itself **defends in depth**: it raises `PermissionError` if the `vehicles` module is not enabled for the calling org. This is a guard against future call sites that forget the gate. The check uses the existing `ModuleService(db).is_enabled(str(org_id), "vehicles")` helper.
- The fleet portal's promotion sites are reached only when an org has the `vehicles` module enabled (the portal itself is gated on `b2b_fleet_portal`, which presupposes `vehicles`).

This means promotion is impossible for an org that has `vehicles` disabled. Such orgs continue to see no vehicle UI, no vehicle fields on invoices, and no `org_vehicles` rows.

---

## Frontend Impact

**ZERO**.

Verified per `frontend-backend-contract-alignment.md` Rule 8: this feature changes no API request body, no API response shape, no Pydantic schema, no TypeScript type, no frontend component prop, no displayed field, and no PDF layout. The frontend codebase does not need to be touched for this feature.

`safe-api-consumption.md` patterns (`?.`, `?? []`, `?? 0`) continue to apply at every existing API consumption site. Nothing is added or removed.

The following frontend pages are explicitly verified as **unaffected** (by name, so reviewers can sanity-check):

- `frontend/src/pages/invoices/InvoiceCreate.tsx`, `InvoiceDetail.tsx`, `InvoiceList.tsx`
- `frontend/src/pages/quotes/QuoteCreate.tsx`, `QuoteDetail.tsx`
- `frontend/src/pages/customers/CustomerDetail.tsx`, `CustomerList.tsx`
- `frontend/src/pages/vehicles/VehicleProfile.tsx`, `VehicleList.tsx`
- `frontend/src/pages/kiosk/KioskCheckIn.tsx`
- `frontend/src/pages/jobs/JobCard*.tsx`
- `frontend/src/pages/bookings/BookingCreate.tsx`
- All B2B fleet portal pages under `frontend/src/pages/fleet-portal/`

Navigation: no new routes, no menu items, no module gates added. The "Refresh from CarJam" action specified in Requirement 5 surfaces through the **existing** vehicle profile refresh button — its handler points at `manual_refresh_vehicle` for promoted vehicles and at the existing `refresh_vehicle` for unpromoted vehicles. No new frontend code path is created; the same button calls the same backend endpoint, which routes server-side based on whether the org is promoted.

---

## Mobile App Impact

**ZERO**.

Same reasoning as Frontend Impact. Mobile screens read invoice and vehicle data via the same v1/v2 endpoints whose response shapes are unchanged. The mobile vehicle-profile screen and invoice screens display the same fields they do today. No mobile screen, route, ModuleGate, or pull-refresh pattern requires modification.

---

## B2B Fleet Portal Impact

Read paths: **unchanged**. The fleet portal's vehicle-list, vehicle-detail, and fleet-summary endpoints already source vehicle fields through `_resolve_vehicle_type`-equivalent logic, which returns `("org", ov)` once promotion has happened and `("global", gv)` until then. Both branches return the same JSON shape.

Write paths: redirected through promotion. Each portal write endpoint is enumerated:

| Portal endpoint | Today | After feature |
|---|---|---|
| Record odometer (`POST /api/v2/fleet-portal/vehicles/{id}/odometer`) | Inserts `OdometerReading`, bumps `gv.odometer_last_recorded` | Inserts `OdometerReading` (unchanged), promotes if needed, bumps `ov.odometer_last_recorded` |
| Update service-due (`PATCH /api/v2/fleet-portal/vehicles/{id}` with `service_due_date`) | Writes to `gv` or `ov` depending on link resolution | Always promotes if needed, writes to `ov` |
| Update WOF/COF expiry (same endpoint) | Same as above | Same — always promotes, writes to `ov` |
| Admin link creation (`POST /api/v2/fleet-portal/admin/customer-vehicles`) | Creates link with `global_vehicle_id` | Promotes, creates link with `org_vehicle_id` |
| CarJam import from portal | Calls `lookup_vehicle` (writes `global_vehicles`), then creates link with `global_vehicle_id` | Calls `lookup_vehicle` (unchanged), promotes, creates link with `org_vehicle_id` |
| Manual vehicle add (no CarJam) | Creates `org_vehicles` row directly with `is_manual_entry=true`, links via `org_vehicle_id` | **Unchanged** — manual-entry path bypasses promotion (the row is born org-scoped) |

Pre-trip checklist template overrides on `customer_vehicles.fleet_checklist_template_id` (added by migration 0191) are unaffected — the column lives on the link row and survives the migration from `global_vehicle_id` to `org_vehicle_id`.

---

## Performance and Resilience

Per `performance-and-resilience.md`:

### DB Round-Trip Accounting

| Path | Round-trips today | Round-trips after feature | Delta |
|---|---|---|---|
| Invoice create with vehicle (steady state, already promoted) | `_resolve_vehicle_type` (1 SELECT) + writes (existing) | `_resolve_vehicle_type` (1 SELECT) + writes (existing) | **0** |
| Invoice create with vehicle (first write, triggering promotion) | `_resolve_vehicle_type` (1 SELECT) + writes to `gv` | `_resolve_vehicle_type` (1 SELECT) + advisory lock (1 stmt) + existence check (1 SELECT) + INSERT `org_vehicles` (1 INSERT) + INSERT audit log (1 INSERT) + UPDATE link (1 UPDATE) + writes to `ov` | **+5 round-trips, one-time per (org, rego)** |
| Invoice update with vehicle changes (steady state) | as today | as today | **0** |
| Kiosk check-in (steady state) | as today | as today | **0** |
| Fleet portal odometer record (steady state) | 1 INSERT (history) + 1 UPDATE (gv) | 1 INSERT (history) + 1 UPDATE (ov) | **0** |
| Fleet portal odometer record (first write) | 1 INSERT (history) + 1 UPDATE (gv) | + advisory lock + SELECT + INSERT ov + INSERT audit + UPDATE link + UPDATE ov | **+5 one-time** |

The one-time cost is paid once per `(org_id, rego)` pair across the entire lifetime of the platform. For a typical workshop adding a new vehicle, this is a single-digit-millisecond addition during the first invoice creation for that vehicle. There is no recurring cost.

### Connection Pool

The advisory lock takes the same DB connection that holds the open transaction; it does not require a second connection or a second pool checkout. Promotion adds **no** pool pressure beyond the one extra `SELECT` and `INSERT` it issues.

### Index Coverage

`promote_vehicle` does `SELECT FROM org_vehicles WHERE org_id=:o AND rego=:r`. The `org_vehicles` table has no compound index on `(org_id, rego)` today. For organisations with many manual vehicles, a sequential scan inside the advisory lock could be expensive. **Mitigation**: the lock is held only for the duration of the SELECT and INSERT, which run on per-org RLS-scoped data; in practice each org has at most a few thousand `org_vehicles` rows, well within sub-millisecond seq-scan budget. **If** real-world performance shows a regression, a follow-up migration adds `CREATE INDEX CONCURRENTLY ix_org_vehicles_org_rego ON org_vehicles (org_id, rego)`. This index is **not** added in this feature (Req 8.2 — no new columns or constraints; an index is technically allowed but is deferred to keep the rollout strictly behavioural).

### Resilience

- The advisory lock is auto-released on transaction end (commit or rollback). A FastAPI request that crashes mid-promotion releases the lock cleanly.
- A timeout in the SELECT or INSERT propagates as a 5xx with no partial state, satisfying Req 2.6.
- Concurrent promotions for **different** regos within the same org do not block each other — the advisory key includes the rego.

---

## Frontend-Backend Contract Alignment

Per `frontend-backend-contract-alignment.md` Rule 8: API contract changes require coordinated frontend+backend release. **This feature has no API contract change**, so Rule 8 is trivially satisfied.

Verified for each affected endpoint:

| Endpoint | Method | Request body | Response shape | Contract change? |
|---|---|---|---|---|
| `POST /api/v1/invoices` | POST | unchanged | unchanged (`{id, ...}`) | **No** |
| `PUT /api/v1/invoices/{id}` | PUT | unchanged | unchanged | **No** |
| `POST /api/v1/kiosk/check-in` | POST | unchanged | unchanged | **No** |
| `POST /api/v1/customers/{id}/vehicles` | POST | unchanged | unchanged | **No** |
| `POST /api/v1/bookings` | POST | unchanged | unchanged | **No** |
| `POST /api/v2/fleet-portal/admin/customer-vehicles` | POST | unchanged | unchanged | **No** |
| `POST /api/v2/fleet-portal/vehicles/{id}/odometer` | POST | unchanged | unchanged | **No** |
| `PATCH /api/v2/fleet-portal/vehicles/{id}` | PATCH | unchanged | unchanged | **No** |
| `POST /api/v1/vehicles/{id}/refresh` | POST | unchanged | unchanged | **No** |

No Pydantic schema is added, removed, renamed, or reshaped.

---

## Database Migration

Per `database-migration-checklist.md`:

**No migration is required for this feature.**

Reasoning, item by item:

- No new tables — Req 8.1.
- No new columns — Req 8.2.
- No removed or renamed columns — Req 8.3.
- No new constraints (no UNIQUE on `(org_id, rego)`; concurrency uses advisory locks) — Req 8.5.
- No new indexes (the `(org_id, rego)` index is deferred to a follow-up if measurement shows regression).
- No data migration / backfill — Req 8.4.
- No `vehicle_link_check` change — Req 8.5.
- No `odometer_readings` FK or CHECK change — Req 8.6.

**The `alembic upgrade head` rule from `database-migration-checklist.md` does not apply** because no Alembic revision is created. The deployment artefact is application code only. Existing migrations remain at revision 0182 (or wherever the head is at deploy time).

If a later observation shows the `(org_id, rego)` SELECT-under-lock benefits from an index, the follow-up migration will be:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_org_vehicles_org_rego
  ON org_vehicles (org_id, rego);
```

This is **not** part of this feature.

---

## Trade-Family Gating

Per `trade-family-gating-for-new-features.md`: **N/A**. This is a universal backend behavioural fix; it applies to every trade family that has the `vehicles` module enabled (automotive, fleet management, agriculture-with-machinery, etc.). It introduces no new feature gated by trade family. The `vehicles` module gate (above) is the only relevant gate.

---

## Integration Credentials Architecture

Per `integration-credentials-architecture.md`: **N/A** for this feature directly. Promotion does not call any external integration. CarJam refresh continues to use the existing GUI-configured CarJam credentials via `_load_carjam_client`. No env-var dependency is introduced.

---

## Security Hardening

Per `security-hardening-checklist.md`:

- **RLS preservation**: `org_vehicles.org_id` is set to the current org at INSERT time. The existing RLS policy on `org_vehicles` permits inserts where `org_id = current_org_id`. Promotion runs under the same `branch_context` as the triggering request, so RLS is enforced normally. No bypass, no `SET ROLE`, no service-role pattern.
- **No credential leakage**: audit-log `after_value` contains only `rego`, `global_vehicle_id`, and `trigger_site` — no PII, no API key, no encrypted blob.
- **Multi-org isolation**: `promote_vehicle` selects `org_vehicles` filtered by `org_id`. The advisory lock key includes `org_id`, so two different orgs promoting the same rego concurrently do **not** serialise — they're independent operations on independent data.
- **Idempotency under concurrent writes**: covered by the advisory-lock + re-SELECT pattern. Verified by Req 13 acceptance criteria and the concurrency test in the plan.
- **No new auth surface**: promotion is invoked from already-authenticated handlers. No new route, no new permission, no new role.
- **OWASP A1 (Broken Access Control)**: tested in the e2e script — Org A cannot read or write Org B's `org_vehicles`.
- **OWASP A2 (Cryptographic Failures)**: not applicable; no new crypto surface.
- **OWASP A3 (Injection)**: the advisory-lock SQL uses parameter binding (`hashtext(:org_id_str)`), not string interpolation. No raw SQL in the promotion path.
- **OWASP A4 (Insecure Design)**: addressed by the lazy-promotion architecture itself — the previous design (writing to `global_vehicles`) was the insecure design.

---

## Test Strategy

Per `feature-testing-workflow.md` and `implementation-completeness-checklist.md`:

### Unit Tests

`tests/test_vehicle_data_isolation.py` (new):

- `test_promote_vehicle_creates_org_row_when_missing` — verify a fresh promotion inserts an `org_vehicles` row with copied fields and `is_manual_entry=False`.
- `test_promote_vehicle_idempotent_when_org_row_exists` — call promotion twice; assert single row, no extra audit log.
- `test_promote_vehicle_finds_pre_existing_manual_entry_by_rego` — pre-create a manual-entry row, then promote; assert the existing row is reused.
- `test_promote_vehicle_emits_audit_log_with_trigger_site` — assert `vehicle.promote` row exists with the correct `trigger_site` payload.
- `test_promote_vehicle_raises_when_module_disabled` — disable `vehicles` module for the org, attempt promotion, expect `PermissionError`.
- `test_migrate_link_to_org_vehicle_swaps_columns_atomically` — assert a single UPDATE swaps both columns, `vehicle_link_check` never violated (verified by an attempted manual update sequence in a savepoint).
- `test_record_odometer_does_not_touch_global_vehicles` — record an odometer reading; assert `global_vehicles.odometer_last_recorded` is unchanged.

### Integration Tests (one per Promotion_Trigger_Site, per Req 15.2)

`tests/integration/test_vehicle_promotion_trigger_sites.py` (new):

- `test_invoice_create_promotes_first_time` (covers `invoices/service.py::create_invoice`)
- `test_invoice_update_promotes_when_customer_driven_field_changes`
- `test_kiosk_v2_check_in_promotes_first_time`
- `test_fleet_portal_record_odometer_promotes_first_time`
- `test_fleet_portal_service_due_update_promotes_first_time`
- `test_fleet_portal_admin_link_creation_promotes_first_time`
- `test_fleet_portal_carjam_import_promotes_first_time`
- `test_bookings_link_creation_promotes_first_time`
- `test_customers_link_creation_promotes_first_time`
- `test_vehicles_link_to_customer_promotes_first_time`

Each test asserts: (a) `org_vehicles` row created for the calling org, (b) `customer_vehicles` link migrated to `org_vehicle_id` (where applicable), (c) `global_vehicles` Customer_Driven_Fields unchanged, (d) `org_vehicles` Customer_Driven_Fields hold the new value, (e) one `vehicle.promote` audit-log row.

### Read Fallback Test (Req 15.3)

`test_read_fallback_returns_global_when_not_promoted` — create a `global_vehicles` row, link a customer to it via `global_vehicle_id`, then call every read endpoint (vehicle profile, invoice display, fleet portal vehicle detail) and assert the global cache values are returned. No `org_vehicles` row is created.

### Concurrency Test (Req 15.4)

`test_concurrent_promotions_produce_single_org_row` — using `asyncio.gather`, kick off two `promote_vehicle` calls for the same `(org, rego)` in two transactions. After both complete, assert exactly one `org_vehicles` row exists for that pair.

### Backwards-Compatibility Test (Req 15.5)

`test_legacy_global_link_still_resolves_through_every_read_endpoint` — pre-create a `customer_vehicles` row pointing at `global_vehicle_id` (no `org_vehicles` row). Iterate over every documented read endpoint and assert each one returns valid vehicle data with the global-cache values.

### End-to-End Test

`scripts/test_vehicle_data_isolation_e2e.py` (new). Per `feature-testing-workflow.md`:

- Logs into two test organisations created with the `TEST_E2E_` prefix on names, regos, and customers.
- Creates a `global_vehicles` row via Org A's CarJam import (or stub).
- **OWASP A1 check**: as Org A, attempts to read Org B's `org_vehicles` directly — expects 404/403, asserts RLS denial.
- **OWASP A2 check**: scans response payloads for credential leakage (audit-log entries, error messages); asserts no `api_key`, `secret`, or `password` substring leaks.
- **OWASP A3 check**: posts a SQL-injection-shaped rego (`'; DROP TABLE org_vehicles; --`) and asserts the parameter binding rejects it as an invalid rego.
- **OWASP A4 check**: as Org A, creates an invoice that writes a Customer_Driven_Field; then logs in as Org B, reads the same rego; asserts Org B sees the original `global_vehicles` value, not Org A's write.
- Promotes the rego in Org B by creating an invoice in Org B; asserts both orgs now have independent `org_vehicles` rows with independent values.
- **Cleanup**: deletes all rows whose names begin with `TEST_E2E_` (orgs, customers, invoices, vehicles, links, audit-log entries) on success or failure.
- Exits non-zero on any assertion failure, with a clear stdout summary.

The script is invoked manually as part of pre-deploy verification per `feature-testing-workflow.md`. It is **not** part of `pytest -q` because it requires a live FastAPI server.

### Verify-Per-Task

Per `implementation-completeness-checklist.md` Rule 9, the `tasks.md` (next phase) will include an explicit `Verify:` line under each task describing the exact assertion that proves the task is done. This design pre-commits to that structure.

---

## Rollout and Rollback Plan

### Rollout

- **Single backend release.** No DB migration, no frontend release, no mobile release.
- The deployment artefact is the new `app/modules/...` code. Standard Pi-prod deploy flow:
  ```
  git push -> sync to Pi -> docker compose up -d --build --force-recreate app
  ```
- The docker entrypoint runs `alembic upgrade head`, but no new revision exists, so it is a no-op.
- Promotion is lazy: at deploy time, **no** `org_vehicles` rows are created. Each org's first customer-driven write per rego promotes that one rego.
- Existing data is untouched; existing links resolve through Read_Fallback.

### Rollback

- Revert the application commit.
- Existing `org_vehicles` rows that were promoted under the new code remain. They are still valid — they have all the fields the old code expects (`make`, `model`, `year`, etc.). Reads through the old code will resolve them via `_resolve_vehicle_type` returning `("org", ov)` and serialise them normally.
- Existing `customer_vehicles` rows that were migrated to `org_vehicle_id` remain pointing at `org_vehicles`. The old code already supports this branch (see existing `if vehicle_type == "org"` branches in `invoices/service.py`).
- New customer-driven writes under the reverted code will once again write to `global_vehicles` — i.e., the bug returns. This is acceptable as a rollback semantic; the data created during the new-code window is preserved and operational.
- **No data loss, no schema rollback, no manual cleanup.**

---

## CHANGELOG Entry

Per `versioning-and-changelog.md`: this is a **PATCH** bump (`1.10.x → 1.10.(x+1)`), because:

- No API contract change (no MINOR bump trigger).
- No breaking change (no MAJOR bump trigger).
- Behavioural fix in the backend that improves tenant isolation.

Drafted entry for `CHANGELOG.md` under the new PATCH section:

```markdown
## [1.10.y] - YYYY-MM-DD

### Fixed
- **Vehicle data isolation**: customer-driven vehicle state (odometer, service-due
  date, WOF expiry, COF expiry, inspection type) now persists privately per
  organisation. Previously, these fields were written to the shared
  `global_vehicles` cache, leaking one workshop's state into another workshop's
  view of the same registration. The shared `global_vehicles` table now holds
  only CarJam-sourced spec data and the per-org snapshot lives in
  `org_vehicles`. Promotion is lazy: no migration is required; the first
  customer-driven write per registration per organisation creates the org
  snapshot from the current global cache. Reads from organisations that have
  not yet been promoted continue to fall back to the global cache, so existing
  invoices, links, and PDFs are unaffected.
- New audit-log actions: `vehicle.promote`, `vehicle.manual_refresh`.
- Concurrent promotions for the same `(org, rego)` are serialised via
  PostgreSQL advisory locks; no schema change.

### Security
- Closes a multi-tenant data-leakage defect on the vehicles module.
```

---

## Verification Per Task (Forward Reference to `tasks.md`)

Each task in the upcoming `tasks.md` will carry a `Verify:` line per `implementation-completeness-checklist.md` Rule 9. Examples (the design pre-commits to these):

| Task | Verify |
|---|---|
| Add `promote_vehicle` helper | `pytest -q tests/test_vehicle_data_isolation.py::test_promote_vehicle_creates_org_row_when_missing` passes |
| Modify `create_invoice` link block | `pytest -q tests/integration/test_vehicle_promotion_trigger_sites.py::test_invoice_create_promotes_first_time` passes; `global_vehicles.wof_expiry` unchanged in DB after the test |
| Modify `record_odometer_reading` | `pytest -q tests/test_vehicle_data_isolation.py::test_record_odometer_does_not_touch_global_vehicles` passes |
| Add `manual_refresh_vehicle` | New unit test asserts `org_vehicles` spec fields updated, customer-driven fields untouched, audit log row written with `action='vehicle.manual_refresh'` |
| End-to-end OWASP smoke | `python scripts/test_vehicle_data_isolation_e2e.py` exits 0; manual review of stdout shows all four OWASP checks PASSED; no `TEST_E2E_*` rows remain in the DB after run |

---

## Spec-Completeness Self-Check

Per `spec-completeness-checklist.md`:

- Component breakdown: present (Architecture, Code Changes per File).
- Navigation TO and AWAY: N/A — no new screens. Existing navigation unchanged.
- User-workflow trace: present (Data Flow under Architecture).
- Error / edge UI: N/A — no new UI. Backend errors propagate through existing 5xx pathways (Req 2.6).
- Integration with existing pages: present (Frontend Impact + B2B Fleet Portal Impact tables).
- RLS bypass considerations: present (Architecture → Transaction and RLS Boundary; Security Hardening).
- Request-path tracing through middleware: present (Data Flow steps 1–6 above; the request runs under the existing `branch_context` middleware).
- Schema changes: explicitly **none** (Database Migration section).
- Versioning: PATCH (CHANGELOG Entry section).
- Frontend code paths affected vs not: explicitly enumerated (Frontend Impact section).
- Backend code paths affected vs not: explicitly enumerated (Code Changes per File section).
- Test strategy: present (Test Strategy section), with file paths, OWASP checks, and the `TEST_E2E_` cleanup pattern.
