# COF (Certificate of Fitness) Support — Gap Analysis

## Problem Statement

In New Zealand, vehicles are subject to either a **WOF (Warrant of Fitness)** or a **COF (Certificate of Fitness)** depending on their type:

- **WOF** — light passenger vehicles (cars, vans, motorcycles under 3,500 kg)
- **COF** — heavy vehicles (trucks, buses, taxis, rental vehicles over 3,500 kg, vehicles used for hire/reward)

The CarJam API returns **separate fields** for each:

| CarJam Field | Description |
|---|---|
| `subject_to_wof` | Y/N — whether vehicle requires WOF |
| `expiry_date_of_last_successful_wof` | WOF expiry timestamp |
| `subject_to_cof` | Y/N — whether vehicle requires COF |
| `expiry_date_of_last_successful_cof` | COF expiry timestamp |

**Current state:** Our system only maps `expiry_date_of_last_successful_wof` → `wof_expiry`. The COF fields are completely ignored. Vehicles subject to COF (not WOF) will have **no inspection expiry stored** — the data is silently discarded.

---

## Scope of Changes Required

### Layer 1: CarJam Integration (1 file)

| File | Change |
|---|---|
| `app/integrations/carjam.py` | Add `cof_expiry` field to `CarjamVehicleData` dataclass |
| `app/integrations/carjam.py` | Add `subject_to_cof` and `subject_to_wof` fields to `CarjamVehicleData` |
| `app/integrations/carjam.py` | In `_parse_vehicle_response()`: map `expiry_date_of_last_successful_cof` → `cof_expiry` |
| `app/integrations/carjam.py` | In `_parse_vehicle_response()`: map `subject_to_wof` and `subject_to_cof` flags |

**Effort: Small** — 4 lines added to the dataclass, 3 lines in the parser.

---

### Layer 2: Database Models + Migration (3 files)

| File | Change |
|---|---|
| `app/modules/admin/models.py` (GlobalVehicle) | Add `cof_expiry: Mapped[date \| None]` column |
| `app/modules/admin/models.py` (GlobalVehicle) | Add `inspection_type: Mapped[str \| None]` column (values: "wof", "cof", null) |
| `app/modules/vehicles/models.py` (OrgVehicle) | Add `cof_expiry: Mapped[date \| None]` column |
| `app/modules/vehicles/models.py` (OrgVehicle) | Add `inspection_type: Mapped[str \| None]` column |
| New migration file | `ALTER TABLE global_vehicles ADD COLUMN cof_expiry DATE, ADD COLUMN inspection_type VARCHAR(3)` |
| New migration file | `ALTER TABLE org_vehicles ADD COLUMN cof_expiry DATE, ADD COLUMN inspection_type VARCHAR(3)` |

**Effort: Small** — 1 new migration, 4 column additions across 2 models.

---

### Layer 3: Backend Schemas (4 files)

| File | Change |
|---|---|
| `app/modules/vehicles/schemas.py` | Add `cof_expiry` to `GlobalVehicleResponse`, `ManualVehicleCreate`, `VehicleSearchResult`, `VehicleDetailResponse` |
| `app/modules/kiosk/schemas.py` | Add `cof_expiry` to `KioskVehicleLookupResponse` |
| `app/modules/invoices/schemas.py` | Add `vehicle_cof_expiry_date` to `InvoiceCreateRequest` |
| `app/modules/portal/schemas.py` | Add `cof_expiry` to `PortalVehicleItem` |

**Effort: Small** — adding one field to ~6 schemas.

---

### Layer 4: Backend Services (5 files)

| File | Function | Change |
|---|---|---|
| `app/modules/vehicles/service.py` | `_carjam_data_to_global_vehicle()` | Store `cof_expiry` and `inspection_type` from CarJam data |
| `app/modules/vehicles/service.py` | `_update_global_vehicle_from_carjam()` | Update `cof_expiry` and `inspection_type` on refresh |
| `app/modules/vehicles/service.py` | `get_vehicle_detail()` | Include `cof_expiry` in response dict |
| `app/modules/vehicles/service.py` | `search_vehicles()` | Include `cof_expiry` in search results |
| `app/modules/vehicles/service.py` | `create_manual_vehicle()` | Accept and store `cof_expiry` |
| `app/modules/vehicles/service.py` | `update_vehicle()` | Accept and update `cof_expiry` |
| `app/modules/kiosk/service.py` | `lookup_vehicle_for_kiosk()` | Include `cof_expiry` in response |
| `app/modules/invoices/service.py` | `create_invoice()` / `update_invoice()` | Handle `vehicle_cof_expiry_date` same as `vehicle_wof_expiry_date` |
| `app/modules/portal/service.py` | `get_customer_vehicles()` | Include `cof_expiry` in portal response |
| `app/modules/notifications/service.py` | WOF reminder logic | Add COF expiry reminder alongside WOF |

**Effort: Medium** — mostly adding a parallel field next to every `wof_expiry` reference.

---

### Layer 5: Backend API / Router (2 files)

| File | Change |
|---|---|
| `app/modules/vehicles/router.py` | Accept `cof_expiry` in manual vehicle creation endpoint |
| `app/modules/invoices/router.py` | Pass `vehicle_cof_expiry_date` through to service |

**Effort: Small** — 2 files, minimal changes.

---

### Layer 6: Frontend Types (4 files)

| File | Change |
|---|---|
| `frontend/src/pages/kiosk/types.ts` | Add `cof_expiry: string \| null` to `VehicleLookupResult` |
| `frontend/src/components/vehicles/VehicleLiveSearch.tsx` | Add `cof_expiry` to `Vehicle` and `SearchResult` interfaces |
| `frontend/src/pages/vehicles/VehicleList.tsx` | Add `cof_expiry_date` to vehicle list item type |
| `frontend/src/pages/invoices/InvoiceCreate.tsx` | Add `cof_expiry` to vehicle state type |

**Effort: Small** — adding one field to ~4 interfaces.

---

### Layer 7: Frontend Display Components (10 files)

| File | Current WOF Display | COF Change Needed |
|---|---|---|
| `frontend/src/pages/kiosk/KioskVehicleSummary.tsx` | Shows "WOF Expiry" row | Show "WOF/COF Expiry" dynamically based on `inspection_type` |
| `frontend/src/pages/vehicles/VehicleProfile.tsx` | `ExpiryBadge` for WOF | Add COF badge or make label dynamic |
| `frontend/src/pages/vehicles/VehicleList.tsx` | "WOF" column header with indicator | Show "WOF/COF" or separate COF column |
| `frontend/src/pages/invoices/InvoiceCreate.tsx` | "WOF Expiry" input field | Show "COF Expiry" when vehicle is COF-subject |
| `frontend/src/pages/invoices/InvoiceDetail.tsx` | "WOF Expiry" label in vehicle card | Dynamic label based on inspection type |
| `frontend/src/pages/invoices/InvoiceList.tsx` | "WOF Expiry" in vehicle details | Dynamic label |
| `frontend/src/pages/portal/VehicleHistory.tsx` | WOF expiry badge | Dynamic WOF/COF badge |
| `frontend/src/pages/customers/CustomerProfile.tsx` | "WOF Expiry" reminder config section | Add COF reminder config |
| `frontend/src/pages/customers/CustomerList.tsx` | WOF reminder toggle | Add COF reminder toggle |
| `frontend/src/pages/data/JsonBulkImport.tsx` | "WOF Expiry" column in preview | Add COF column |

**Effort: Medium** — each file needs a conditional label change (WOF vs COF) and potentially a second field.

---

### Layer 8: Notifications (3 files)

| File | Change |
|---|---|
| `app/modules/notifications/schemas.py` | Add `cof_expiry_reminder` template type, subject line, default content |
| `app/modules/notifications/service.py` | Add COF expiry to the reminder processing loop (currently only processes WOF + Registration) |
| `app/modules/notifications/reminder_queue_service.py` | Add COF expiry field to reminder queue processing |

**Effort: Small-Medium** — the WOF reminder logic is already a loop over `(expiry_type, expiry_field, template_type)` tuples, so adding COF is one more tuple entry.

---

### Layer 9: Dashboard (1 file)

| File | Change |
|---|---|
| `app/modules/organisations/dashboard_service.py` | Include COF expiry in "upcoming expirations" widget alongside WOF |

**Effort: Small** — the query already checks `gv.wof_expiry`, add `OR gv.cof_expiry` condition.

---

## Design Decision: Single Column vs Dual Column

**Option A: Rename `wof_expiry` → `inspection_expiry` (breaking change)**
- Pros: Single column, simpler queries
- Cons: Massive migration, breaks all existing code, loses semantic clarity

**Option B: Add `cof_expiry` alongside `wof_expiry` (recommended)**
- Pros: Non-breaking, backward compatible, clear semantics
- Cons: Two columns, need to check both in queries
- Logic: Use `inspection_type` field to determine which to display; fallback to whichever is non-null

**Option C: Store in `wof_expiry` regardless of type, add `inspection_type` flag**
- Pros: No schema changes to display logic
- Cons: Semantically incorrect column name, confusing for future developers

**Recommendation: Option B** — add `cof_expiry` + `inspection_type` columns. Display logic checks `inspection_type` to determine label ("WOF Expiry" vs "COF Expiry"). Queries for "upcoming inspections" check both columns.

---

## Display Logic

```typescript
// Frontend helper
function getInspectionLabel(vehicle: { inspection_type?: string | null }): string {
  if (vehicle.inspection_type === 'cof') return 'COF Expiry'
  return 'WOF Expiry' // default for wof or unknown
}

function getInspectionExpiry(vehicle: { wof_expiry?: string | null; cof_expiry?: string | null; inspection_type?: string | null }): string | null {
  if (vehicle.inspection_type === 'cof') return vehicle.cof_expiry
  return vehicle.wof_expiry
}
```

---

## Effort Estimate

| Layer | Files | Effort |
|---|---|---|
| CarJam integration | 1 | Small (30 min) |
| Database + migration | 3 | Small (30 min) |
| Backend schemas | 4 | Small (30 min) |
| Backend services | 5 | Medium (2 hrs) |
| Backend API/router | 2 | Small (15 min) |
| Frontend types | 4 | Small (15 min) |
| Frontend display | 10 | Medium (3 hrs) |
| Notifications | 3 | Small-Medium (1 hr) |
| Dashboard | 1 | Small (15 min) |
| **Total** | **~33 files** | **~8 hours** |

---

## Files Requiring Changes (Complete List)

### Backend
1. `app/integrations/carjam.py`
2. `app/modules/admin/models.py`
3. `app/modules/vehicles/models.py`
4. `app/modules/vehicles/schemas.py`
5. `app/modules/vehicles/service.py`
6. `app/modules/vehicles/router.py`
7. `app/modules/kiosk/schemas.py`
8. `app/modules/kiosk/service.py`
9. `app/modules/invoices/schemas.py`
10. `app/modules/invoices/service.py`
11. `app/modules/invoices/router.py`
12. `app/modules/portal/schemas.py`
13. `app/modules/portal/service.py`
14. `app/modules/notifications/schemas.py`
15. `app/modules/notifications/service.py`
16. `app/modules/notifications/reminder_queue_service.py`
17. `app/modules/organisations/dashboard_service.py`
18. `alembic/versions/XXXX_add_cof_expiry_columns.py` (new)

### Frontend
19. `frontend/src/pages/kiosk/types.ts`
20. `frontend/src/pages/kiosk/KioskVehicleSummary.tsx`
21. `frontend/src/components/vehicles/VehicleLiveSearch.tsx`
22. `frontend/src/pages/vehicles/VehicleProfile.tsx`
23. `frontend/src/pages/vehicles/VehicleList.tsx`
24. `frontend/src/pages/invoices/InvoiceCreate.tsx`
25. `frontend/src/pages/invoices/InvoiceDetail.tsx`
26. `frontend/src/pages/invoices/InvoiceList.tsx`
27. `frontend/src/pages/portal/VehicleHistory.tsx`
28. `frontend/src/pages/customers/CustomerProfile.tsx`
29. `frontend/src/pages/customers/CustomerList.tsx`
30. `frontend/src/pages/data/JsonBulkImport.tsx`

---

## Risk Assessment

- **Low risk**: All changes are additive (new columns, new fields). No existing data is modified.
- **Backward compatible**: Existing WOF-only vehicles continue to work unchanged.
- **Data migration**: No data migration needed — new columns start as NULL for existing records. CarJam re-pulls will populate them.
- **COF vehicles already in system**: Any COF vehicles already looked up via CarJam will have `wof_expiry = NULL` (since they're not subject to WOF). After the change, a re-pull from CarJam will populate `cof_expiry` and `inspection_type`.
