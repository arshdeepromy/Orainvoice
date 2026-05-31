# Rego → Customer auto-fill + One-vehicle-one-customer constraint

**Status:** Investigation complete. No code changes yet.
**Date:** 2026-05-30
**Scope:** Confirm the rego→customer auto-fill exists, design the change from N-customers-per-vehicle to 1-customer-per-vehicle within an org.
**Method:** Code investigation only. Production data was not queried.

---

## 0. TL;DR for product decisions

| What was asked for | Where it stands |
|---|---|
| Type rego → auto-fill linked customer details on Invoice & Quote | **Already implemented and live.** Uses `linked_customers` field on the `/vehicles/search` response. |
| One customer can have many vehicles | Allowed (no change). |
| One vehicle can be linked to only one customer at a time within an org | **Not enforced today.** Schema + service code intentionally allow many. Needs a migration + service-layer guard + data cleanup. |

The work to do is **not** "build the rego→customer feature" — that exists. The work is enforcing the new uniqueness rule on the data model, sequenced safely against existing production data.

---

## 1. Does this work for existing data, or only future data?

This is the deciding question. The answer is split:

### 1a. The rego→customer auto-fill UI: **works for existing data unchanged.**

The backend `/vehicles/search` endpoint at [app/modules/vehicles/service.py:1420-1561](../../app/modules/vehicles/service.py#L1420-L1561) reads `customer_vehicles` joined to `customers` regardless of when the link was created. Every existing link participates the moment the feature is exercised — no backfill needed for the lookup.

If today a vehicle has 3 linked customers, the dropdown will show "3 owners" (per [VehicleLiveSearch.tsx:336](../../frontend/src/components/vehicles/VehicleLiveSearch.tsx#L336)) and auto-select `linked_customers[0]`. Behaviour exists; it's just ambiguous until §1b is done.

### 1b. The "one customer per vehicle" constraint: **requires explicit handling of existing data.**

The chosen enforcement mechanism is a **partial unique index** on `customer_vehicles (org_id, org_vehicle_id) WHERE org_vehicle_id IS NOT NULL` (and the mirror for `global_vehicle_id`). Postgres behaviour:

- `CREATE UNIQUE INDEX CONCURRENTLY` **scans every existing row** while it builds the index. If any row violates uniqueness, the entire statement **aborts** with `ERROR: could not create unique index ... Key (org_id, org_vehicle_id)=(...) is duplicated`.
- This is good — it's a safety net — but it also means **you cannot just deploy the migration**. Any existing many-to-many situation in production data will block the migration until resolved.

So the plan **does** cover existing data, but only via an explicit cleanup phase (§4 below). It does not silently rewrite history.

### 1c. The service-layer guards: **work for existing data once cleanup is done.**

The duplicate-link checks in the three creation paths (§3.2) will start refusing conflicts the moment they're deployed. They don't retroactively remove existing duplicates; they just stop new ones forming. That's why §1b cleanup must precede the deploy — otherwise the new checks would interpret already-broken state as "vehicle already owned by someone else" and start refusing legitimate operations on existing customers.

### 1d. Bottom line for the decision

| Concern | Future data | Existing data |
|---|---|---|
| Rego→customer dropdown shows linked customer | ✅ Already works | ✅ Already works |
| Auto-fill picks the right customer when there's only one | ✅ | ✅ |
| Auto-fill picks an unambiguous customer when historically there were two | ✅ once cleanup done | ⚠️ Currently picks `linked_customers[0]` — first-by-DB-order; not deterministic by business meaning |
| New duplicate links blocked | ✅ once guards deployed | ✅ |
| Existing duplicate links cleaned up | n/a | ⚠️ One-off audit + manual or policy-driven merge required |
| Customer-merge flow safe | ✅ once guard added (§3.3) | ✅ once guard added |

The plan is fully production-safe **on the condition that §4 (cleanup) runs before §5 (constraint deploy)**. Skipping §4 = deploy failure; the migration will refuse to install.

---

## 2. Current state of the codebase

### 2.1 The rego→customer auto-fill is already there

#### Frontend
- [frontend/src/components/vehicles/VehicleLiveSearch.tsx](../../frontend/src/components/vehicles/VehicleLiveSearch.tsx) is a shared component used by:
  - [InvoiceCreate.tsx:2134-2156](../../frontend/src/pages/invoices/InvoiceCreate.tsx#L2134-L2156)
  - [QuoteCreate.tsx:1575-1594](../../frontend/src/pages/quotes/QuoteCreate.tsx#L1575-L1594)
- Calls `GET /vehicles/search?q=<rego>` (debounced 300 ms, min 2 chars) at [VehicleLiveSearch.tsx:94-97](../../frontend/src/components/vehicles/VehicleLiveSearch.tsx#L94-L97).
- Exposes `onCustomerAutoSelect` callback ([line 54](../../frontend/src/components/vehicles/VehicleLiveSearch.tsx#L54)) that fires with `linked_customers[0]` when a user picks a vehicle ([lines 148-151](../../frontend/src/components/vehicles/VehicleLiveSearch.tsx#L148-L151)).
- Also re-runs the search after a CarJam onboarding to grab any newly-discovered link ([lines 181-195](../../frontend/src/components/vehicles/VehicleLiveSearch.tsx#L181-L195)).
- Renders an "N owner(s)" badge in the dropdown ([line 336](../../frontend/src/components/vehicles/VehicleLiveSearch.tsx#L336)) plus the first two names ([lines 340-347](../../frontend/src/components/vehicles/VehicleLiveSearch.tsx#L340-L347)).

#### Backend
- Route handler: [app/modules/vehicles/router.py:430-446](../../app/modules/vehicles/router.py#L430-L446).
- Service: [app/modules/vehicles/service.py:1420-1561](../../app/modules/vehicles/service.py#L1420-L1561).
- Searches both `global_vehicles` and `org_vehicles` by rego prefix; for each hit attaches all `linked_customers` for **this org only** (lines 1483, 1543 — `CustomerVehicle.org_id == org_id`). No cross-tenant leak.
- Returns per linked customer: `id, first_name, last_name, email, phone, mobile_phone, display_name, company_name`.

#### Where the auto-fill applies the customer
- **InvoiceCreate** ([line 2141-2155](../../frontend/src/pages/invoices/InvoiceCreate.tsx#L2141-L2155)): fills `id, first_name, last_name, email, phone, mobile_phone, display_name, company_name`. Guard at line 2143: `if (!customer)` — auto-fill only when no customer is currently selected.
- **QuoteCreate** ([line 1583-1593](../../frontend/src/pages/quotes/QuoteCreate.tsx#L1583-L1593)): same pattern, narrower field set (no `mobile_phone/display_name/company_name`). Minor inconsistency worth aligning once you're touching this code.

### 2.2 The data model today permits many-to-many

[app/modules/vehicles/models.py:98-154](../../app/modules/vehicles/models.py#L98-L154) defines `customer_vehicles`:

```
id           PK
org_id       FK organisations
customer_id  FK customers
global_vehicle_id  FK global_vehicles  (nullable)
org_vehicle_id     FK org_vehicles     (nullable)
linked_at, odometer_at_link, fleet_checklist_template_id
```

with exactly one CHECK constraint: `vehicle_link_check` ensuring exactly one of `global_vehicle_id` / `org_vehicle_id` is set.

**There is no unique constraint anywhere on `(org_id, org_vehicle_id)` or `(org_id, global_vehicle_id)`.** Confirmed by scanning all 204 Alembic migrations under `alembic/versions/`.

The schema migration that created this table — [alembic/versions/0003_create_vehicle_tables.py:70-111](../../alembic/versions/2025_01_15_0003-0003_create_vehicle_tables.py#L70-L111) — has no unique index either.

The link-creation service docstring at [app/modules/vehicles/service.py:1120-1122](../../app/modules/vehicles/service.py#L1120-L1122) explicitly documents this:

> "The same global vehicle can be linked to different customers across different organisations (Req 15.1) **and to multiple customers within a single organisation (Req 15.2).**"

(The citation of Req 15.2 is a misattribution — that requirement in [.kiro/specs/vehicle-data-isolation/requirements.md](../../.kiro/specs/vehicle-data-isolation/requirements.md) is about test coverage. The behaviour is still real; the comment is just wrong about the source.)

### 2.3 Sites that create or modify `CustomerVehicle` rows

| Where | Operation | Current guard |
|---|---|---|
| [vehicles/service.py:1108 `link_vehicle_to_customer`](../../app/modules/vehicles/service.py#L1108) | Explicit link endpoint. Creates a `CustomerVehicle` row at line 1203. | **None.** Allows linking a vehicle that's already owned by another customer. |
| [invoices/service.py:951-1009 auto-link on invoice create](../../app/modules/invoices/service.py#L951-L1009) | Auto-creates a link when an invoice includes a vehicle. | Checks for duplicate `(org_id, customer_id, vehicle_id)` only (lines 977-993). Does NOT block linking a vehicle that's already linked to a *different* customer. |
| [kiosk/service.py:189-200](../../app/modules/kiosk/service.py#L189-L200) | Auto-links when a customer checks in at the kiosk. | Logs "already linked — skipping" but only checks `global_vehicle_id`, not `org_vehicle_id`, so the post-promotion path can still duplicate. |
| [customers/service.py:1086 `CustomerVehicle(...)`](../../app/modules/customers/service.py#L1086) | Customer-side link creation. | Same as above. |
| [customers/service.py:1278-1279 customer merge](../../app/modules/customers/service.py#L1278-L1279) | `cv.customer_id = target_customer_id` — blind reassignment when merging two customers. | **None.** If both customers happen to have the same vehicle linked, the merge today silently leaves two links pointing at the target. After the constraint is enforced this becomes a runtime integrity error. |

### 2.4 The only explicit unlink today

[fleet_portal/router.py:2297](../../app/modules/fleet_portal/router.py#L2297) — a fleet-portal-admin-only delete on `CustomerVehicle.id`. **There is no org-user-facing "transfer this vehicle to a new customer" endpoint.** This becomes a usability gap once the new constraint is enforced — see §3.4.

---

## 3. Design of the change

### 3.1 Database layer — the actual enforcement

Two partial unique indexes (because `org_vehicle_id` and `global_vehicle_id` are mutually exclusive by `vehicle_link_check`):

```sql
CREATE UNIQUE INDEX CONCURRENTLY uq_customer_vehicles_org_orgvehicle
  ON customer_vehicles (org_id, org_vehicle_id)
  WHERE org_vehicle_id IS NOT NULL;

CREATE UNIQUE INDEX CONCURRENTLY uq_customer_vehicles_org_globalvehicle
  ON customer_vehicles (org_id, global_vehicle_id)
  WHERE global_vehicle_id IS NOT NULL;
```

These also subsume the FK indexes flagged in [PERFORMANCE_AUDIT.md](../PERFORMANCE_AUDIT.md) finding D-H5 — single migration covers both jobs.

`CONCURRENTLY` is mandatory: this is a live table.

### 3.2 Service layer — prevent re-introduction of duplicates

Widen the duplicate-link checks at the four sites in §2.3 from "same `(customer, vehicle)` pair" to "any link with this `(org, vehicle)`":

- **vehicles/service.py:1108 `link_vehicle_to_customer`** — add `force_reassign: bool = False` parameter. On conflict: return 409 with current owner's name, or detach the prior link if `force_reassign=True`.
- **invoices/service.py:977-993** — widen the existing duplicate-detection select to look up by vehicle alone within the org. On conflict, either reassign (if the invoice is being issued *to* a different customer than the current vehicle owner, that's strong intent) or refuse with a clear error.
- **kiosk/service.py:189** — same widening; kiosk check-in is implicit intent so likely should be "reassign with audit log entry."
- **customers/service.py:1278-1279 (merge)** — before reassigning links, detect the overlap set (vehicles linked to *both* source and target), delete the source-side link for each, and let the rest fall through. Add a counter to the merge-audit payload.

### 3.3 Reassignment / transfer flow — the new capability you need

Without an explicit transfer endpoint, the new constraint would block legitimate "I sold my car to my brother who's also one of our customers" scenarios. Two options:

- **Option A** — add `force_reassign=True` to `link_vehicle_to_customer`. Single endpoint, simplest. Frontend confirms with the user before sending the flag.
- **Option B** — new `POST /vehicles/{id}/reassign {new_customer_id}` endpoint. More explicit; nicer to audit; clearer in API docs.

Recommend **A** unless you anticipate the reassign action needing additional metadata (transfer date, reason, old/new odometer). It's a one-line param change in the service, plus a UI tweak to show a confirm dialog when the rego search reveals the vehicle is owned by someone else.

### 3.4 UI implications

Once enforced, `linked_customers` is always `[]` or `[onlyone]`. Then:

- [VehicleLiveSearch.tsx:336](../../frontend/src/components/vehicles/VehicleLiveSearch.tsx#L336) — "N owner(s)" badge becomes "Linked: <name>" (no plural).
- [VehicleLiveSearch.tsx:148-151](../../frontend/src/components/vehicles/VehicleLiveSearch.tsx#L148-L151) — `linked_customers[0]` is unambiguous; remove the "first owner wins" implication.
- [VehicleLiveSearch.tsx:340-347](../../frontend/src/components/vehicles/VehicleLiveSearch.tsx#L340-L347) — "+N more" dead code; remove.
- The `if (!customer)` guard at [InvoiceCreate.tsx:2143](../../frontend/src/pages/invoices/InvoiceCreate.tsx#L2143) and [QuoteCreate.tsx:1584](../../frontend/src/pages/quotes/QuoteCreate.tsx#L1584): consider a banner if the org user typed Customer Y and the rego search reveals it's linked to Customer X. Options:
  - Silent keep Y (current behaviour, confusing).
  - Silent overwrite with X (data-driven, stomps user input).
  - Banner: "This vehicle is linked to X — switch customer or reassign?" — **recommended**; honest and forces the decision.

### 3.5 Documentation cleanup

Update the docstrings that will lie after this change:
- [vehicles/service.py:1120-1122](../../app/modules/vehicles/service.py#L1120-L1122) — remove "and to multiple customers within a single organisation."
- [vehicles/router.py:373](../../app/modules/vehicles/router.py#L373) — same.

---

## 4. Handling existing production data — the audit & cleanup phase

This is the part that **must** run before §3.1's migration, otherwise the deploy fails.

### 4.1 Audit query — find every conflict

Run this read-only query against the production database (or a recent restore) to enumerate every row of customer_vehicles that violates the new constraint:

```sql
-- All (org_id, vehicle) groups where more than one customer link exists
WITH duplicates AS (
  SELECT
    org_id,
    COALESCE(org_vehicle_id::text, global_vehicle_id::text) AS vehicle_id,
    CASE WHEN org_vehicle_id IS NOT NULL THEN 'org' ELSE 'global' END AS vehicle_kind,
    array_agg(id ORDER BY linked_at DESC) AS link_ids,
    array_agg(customer_id ORDER BY linked_at DESC) AS customer_ids,
    array_agg(linked_at ORDER BY linked_at DESC) AS link_dates,
    count(*) AS link_count
  FROM customer_vehicles
  GROUP BY org_id, COALESCE(org_vehicle_id::text, global_vehicle_id::text),
           CASE WHEN org_vehicle_id IS NOT NULL THEN 'org' ELSE 'global' END
  HAVING count(*) > 1
)
SELECT
  d.org_id,
  d.vehicle_kind,
  d.vehicle_id,
  d.link_count,
  CASE WHEN d.vehicle_kind = 'org'
    THEN (SELECT rego FROM org_vehicles WHERE id = d.vehicle_id::uuid)
    ELSE (SELECT rego FROM global_vehicles WHERE id = d.vehicle_id::uuid)
  END AS rego,
  d.customer_ids,
  d.link_dates,
  d.link_ids
FROM duplicates d
ORDER BY d.org_id, d.link_count DESC;
```

Expected result categories:

- **Category A — same `(org, customer, vehicle)` triple duplicated.** Definitely safe to dedup; keep the oldest by `linked_at` (or oldest by `id` if dates are equal), delete the rest. The duplicate-link bug noted in [vehicle-data-isolation tasks.md line 329](../../.kiro/specs/vehicle-data-isolation/tasks.md) is the cause of most of these.
- **Category B — different customers within the same org for the same vehicle.** Genuine business question: "who owns the car now?" Cannot be auto-resolved. Need a per-org or per-row decision.

### 4.2 Auto-resolution policy for Category A (safe)

```sql
-- Delete dupes that share (org, customer, vehicle). Keeps oldest link.
WITH ranked AS (
  SELECT id,
    ROW_NUMBER() OVER (
      PARTITION BY org_id, customer_id,
                   COALESCE(org_vehicle_id, global_vehicle_id)
      ORDER BY linked_at ASC, id ASC
    ) AS rn
  FROM customer_vehicles
)
DELETE FROM customer_vehicles
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);
```

This handles the duplicate-link bug class. Run in a transaction first with `BEGIN; ... ROLLBACK;` to see counts.

### 4.3 Resolution policy for Category B (needs a decision)

Pick one of these policies before running:

- **Policy 1 — most recent wins.** Keep the link with the highest `linked_at`; delete the older ones. Justification: latest data is usually the current owner.
- **Policy 2 — most-recent-invoice wins.** For each conflict, look up which customer has the most recent invoice referencing the vehicle's rego; keep that customer's link. Most accurate business-wise, more work to compute.
- **Policy 3 — manual triage.** Export Category B to CSV, send to each affected org admin for review, apply their choice. Highest fidelity, most ops effort.

For most workshops the volume in Category B will be small. The realistic mix is: do **Policy 1 (most recent)** as the default, with a one-off email to any org whose count exceeds some threshold (say 5 conflicts), asking them to confirm.

Whichever policy is chosen, write the deletions through a single transaction that also writes audit-log entries for every row deleted — these are real link records and removing them should be auditable.

### 4.4 Pre-flight check before the migration

After §4.2 and §4.3, re-run the audit query in §4.1. **It must return zero rows** before the `CREATE UNIQUE INDEX CONCURRENTLY` migration is applied. If anything remains, fix it; do not proceed.

### 4.5 Rollback safety

The two indexes in §3.1 can be dropped with `DROP INDEX CONCURRENTLY` if anything goes wrong:

```sql
DROP INDEX CONCURRENTLY IF EXISTS uq_customer_vehicles_org_orgvehicle;
DROP INDEX CONCURRENTLY IF EXISTS uq_customer_vehicles_org_globalvehicle;
```

That reverts to the current many-to-many state. The service-layer guards in §3.2 are non-destructive on rollback — they only refuse new bad writes; existing data isn't touched.

The data deletions in §4.2 and §4.3 are **not** reversible from a regular backup if discovered late. Take a full `pg_dump` immediately before §4 runs. (Per [PERFORMANCE_AUDIT.md](../PERFORMANCE_AUDIT.md) Phase 1, off-host nightly backups should be running anyway before this work starts.)

---

## 5. Sequenced rollout

Order is important. Each step is independently reversible up to step 6.

1. **Off-host backup verified.** Per the performance audit, this should already be in place; if not, do it first.
2. **Code changes deployed but inactive.**
   - Add the service-layer guards (§3.2) behind a feature flag `STRICT_VEHICLE_OWNERSHIP` defaulting to `false`. Old behaviour stays in place.
   - Ship the UI changes (§3.4) that prefer single-customer rendering but still tolerate the multi-customer shape.
   - Add `force_reassign` to `link_vehicle_to_customer` (§3.3); the new param defaults to `false` so existing callers are unaffected.
3. **Audit query (§4.1) run in production.** Export results. Verify expectation (Category A small, Category B small).
4. **Resolve Category A** with the dedup SQL (§4.2) inside a transaction. Compare row counts before commit.
5. **Resolve Category B** per chosen policy (§4.3). Audit-log every deletion.
6. **Re-run audit (§4.4).** Expect zero rows. If non-zero, stop.
7. **Take a `pg_dump`.**
8. **Apply migration (§3.1)** — two `CREATE UNIQUE INDEX CONCURRENTLY` statements. Each takes ~seconds to minutes on a 5 M-row table.
9. **Enable the feature flag** `STRICT_VEHICLE_OWNERSHIP=true`. Service guards now block new conflicts; the constraint is the second line of defence.
10. **Soak for 2 weeks.** Watch the error log for any 409s from `link_vehicle_to_customer` — these are real-world owner-change events that need the reassign UI (§3.3 Option A) to be discoverable. Add the confirmation banner from §3.4 if you haven't already.
11. **Final cleanup.** Remove the feature flag; the unique indexes are now load-bearing.

Steps 1–8 do not require downtime. Step 8 acquires only `SHARE UPDATE EXCLUSIVE` because of `CONCURRENTLY`.

---

## 6. Effort estimate

| Phase | Effort | Risk |
|---|---|---|
| Code: service-layer guards behind feature flag | 0.5–1 d | Low |
| Code: `force_reassign` + UI confirmation banner | 0.5 d | Low |
| Code: customer-merge overlap fix | 0.5 d | Low (good test coverage already on this path) |
| Code: UI simplifications in `VehicleLiveSearch` | 0.25 d | Low |
| Data: audit query + Category A auto-resolution | 0.5 d | Low |
| Data: Category B policy + execution | **0.5–3 d, depends on volume + chosen policy** | Medium (manual triage option is the slow part) |
| Migration | 0.25 d | Low |
| Soak | 2 weeks elapsed | n/a |
| **Total dev effort** | **3–6 dev-days** | n/a |

The unknowable is Category B volume; everything else is mechanical.

---

## 7. Open product questions to confirm before starting

1. **Category B policy** — Most recent wins, most-recent-invoice wins, or manual triage per org? Recommend most-recent-wins with an opt-out for high-count orgs.
2. **Conflict UX during normal operation** — when an org user types Customer Y for an invoice but the rego is already owned by Customer X, do we (a) silently keep Y, (b) silently overwrite with X, or (c) prompt for a decision? Recommend (c).
3. **Reassign capability scope** — does the new `force_reassign` flag need to be RBAC-gated (e.g. only org admins, not staff)? Probably yes.
4. **Audit-log retention for the data cleanup** — write a special audit `action="vehicle.link.cleanup_pre_constraint"` for every deletion in §4.2 / §4.3 so the rationale is preserved forever, not just in the deploy log.
5. **Customer-portal implications** — does the customer-facing portal display "your vehicles" anywhere that would surface this change? Out-of-scope for this investigation but worth a quick sweep.

---

## 8. Cross-references

- Schema: [app/modules/vehicles/models.py:98-154](../../app/modules/vehicles/models.py#L98-L154)
- Original migration: [alembic/versions/0003_create_vehicle_tables.py](../../alembic/versions/2025_01_15_0003-0003_create_vehicle_tables.py)
- Backend service: [app/modules/vehicles/service.py:1108-1561](../../app/modules/vehicles/service.py#L1108-L1561)
- Backend route: [app/modules/vehicles/router.py:430-446](../../app/modules/vehicles/router.py#L430-L446)
- Frontend component: [frontend/src/components/vehicles/VehicleLiveSearch.tsx](../../frontend/src/components/vehicles/VehicleLiveSearch.tsx)
- Frontend Invoice call site: [frontend/src/pages/invoices/InvoiceCreate.tsx:2134-2156](../../frontend/src/pages/invoices/InvoiceCreate.tsx#L2134-L2156)
- Frontend Quote call site: [frontend/src/pages/quotes/QuoteCreate.tsx:1575-1594](../../frontend/src/pages/quotes/QuoteCreate.tsx#L1575-L1594)
- Customer-merge path: [app/modules/customers/service.py:1278-1279](../../app/modules/customers/service.py#L1278-L1279)
- Related performance audit findings: [PERFORMANCE_AUDIT.md](../PERFORMANCE_AUDIT.md) D-H5 (FK indexes — same migration can satisfy both).
- Related spec: [.kiro/specs/vehicle-data-isolation/](../../.kiro/specs/vehicle-data-isolation/) — relevant context on lazy-promotion and how `global_vehicle_id` vs `org_vehicle_id` interact.
