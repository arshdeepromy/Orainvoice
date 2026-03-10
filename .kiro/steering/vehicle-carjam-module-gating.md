---
inclusion: auto
---

# Vehicle & CarJam Module Gating Rules

OraInvoice is a multi-industry invoicing platform. Vehicle-related features (global vehicle database, CarJam lookups, vehicle search, odometer tracking, vehicle info on invoices/PDFs) are part of the **CarJam module** — an optional module for automotive/mechanic shop organisations. These features MUST NOT appear or execute for organisations that don't have the module enabled.

## Module Architecture

The platform uses two gating systems that work together:

1. **Module system** (`org_modules` table + `ModuleService` in `app/core/modules.py`): Controls which feature modules are enabled per organisation. Checked via `ModuleService.is_enabled(org_id, "vehicles")`.
2. **Feature flags** (`feature_flags` table + `evaluate_flag()` in `app/core/feature_flags.py`): Fine-grained control within modules. Targeting by org, trade_category, country, plan_tier, or percentage rollout.

The `vehicles` module slug is the gating key for ALL vehicle/CarJam functionality.

## Module Slug: `vehicles`

- **Registry**: Must exist in `module_registry` table (slug: `vehicles`, category: `automotive`, is_core: false)
- **Dependencies**: None (standalone optional module)
- **Frontend gating**: `useModules().isEnabled('vehicles')` or `<ModuleGate module="vehicles">` wrapper
- **Backend gating**: `ModuleService(db).is_enabled(org_id, "vehicles")` check before any vehicle operation

## What Belongs to the Vehicles Module

Everything touching the global vehicle database, CarJam API, vehicle search, vehicle-customer linking, and vehicle display on invoices is gated behind `vehicles`:

### Backend (gated by module check)
- `app/modules/vehicles/` — entire module (search, lookup, CRUD, odometer)
- `app/modules/invoices/service.py` — vehicle fields on invoice creation (`vehicle_rego`, `vehicle_make`, `vehicle_model`, `vehicle_year`, `vehicle_odometer`, `global_vehicle_id`)
- `app/modules/invoices/service.py` — auto-linking customer↔vehicle on invoice save
- `app/modules/invoices/service.py` — odometer recording on invoice save
- `app/modules/customers/service.py` — `linked_vehicles` in customer search results
- `app/templates/pdf/invoice.html` — vehicle info bar section
- `app/templates/pdf/invoice_share.html` — vehicle info bar section
- Any CarJam/ABCD API integration endpoints

### Frontend (gated by ModuleGate or isEnabled check)
- `frontend/src/components/vehicles/VehicleLiveSearch.tsx` — vehicle search component
- `frontend/src/pages/invoices/InvoiceCreate.tsx` — vehicle selection section, odometer input
- `frontend/src/pages/invoices/InvoiceList.tsx` — vehicle info card in invoice detail
- `frontend/src/pages/invoices/InvoiceDetail.tsx` — vehicle display section
- `frontend/src/layouts/OrgLayout.tsx` — Vehicles nav item (already gated with `module: 'vehicles'`)
- Any vehicle profile, vehicle list, or fleet management pages

## Gating Rules for New Code

### Rule 1: Backend endpoints in `app/modules/vehicles/` MUST check module enablement

Every vehicle router endpoint must verify the module is enabled for the requesting org before proceeding:

```python
from app.core.modules import ModuleService

module_svc = ModuleService(db)
if not await module_svc.is_enabled(str(org_id), "vehicles"):
    raise HTTPException(status_code=403, detail="Vehicles module is not enabled for this organisation")
```

### Rule 2: Invoice creation MUST skip vehicle fields when module is disabled

In `app/modules/invoices/service.py`, the `create_invoice()` function must:
- Accept vehicle params but ignore them if vehicles module is disabled
- NOT store vehicle_rego, vehicle_make, vehicle_model, vehicle_year, vehicle_odometer on the invoice record
- NOT create CustomerVehicle links
- NOT record odometer readings
- NOT look up GlobalVehicle data

### Rule 3: Invoice PDF templates MUST conditionally render vehicle sections

In `app/templates/pdf/invoice.html` and `invoice_share.html`:
- The vehicle info bar (rego, make/model, odometer, WOF) must only render when vehicle data exists on the invoice
- Use Jinja2 conditional: `{% if vehicle and vehicle.rego %}`
- When vehicles module is disabled, no vehicle data will be on the invoice, so the section naturally hides

### Rule 4: Frontend components MUST use ModuleGate or isEnabled

Wrap vehicle UI sections with the existing `<ModuleGate>` component:

```tsx
import { ModuleGate } from '@/components/common/ModuleGate'

// In InvoiceCreate — wrap the vehicle search section
<ModuleGate module="vehicles">
  <VehicleLiveSearch ... />
</ModuleGate>

// Or use the hook directly
const { isEnabled } = useModules()
if (isEnabled('vehicles')) {
  // show vehicle UI
}
```

### Rule 5: Customer search MUST NOT return linked_vehicles when module is disabled

In `app/modules/customers/service.py`, the `search_customers()` function should only query and return `linked_vehicles` when the vehicles module is enabled for the org. When disabled, omit the field or return an empty array.

### Rule 6: API responses MUST NOT leak vehicle data when module is disabled

Invoice API responses (`get_invoice`, `list_invoices`) should strip vehicle fields from the response when the vehicles module is disabled for the requesting org. This prevents frontend from accidentally displaying stale vehicle data.

### Rule 7: New vehicle-related features MUST be added under the vehicles module gate

When adding any new feature that touches:
- Vehicle registration/rego lookup
- CarJam or ABCD API calls
- Global vehicle database queries
- Vehicle-customer linking
- Odometer tracking
- WOF/registration expiry
- Vehicle info display on any document (invoice, quote, job card, PDF)

...it MUST be gated behind the `vehicles` module check on both backend and frontend.

## What is NOT Gated (Available to All Orgs)

These core features work for every organisation regardless of module settings:
- Invoicing (create, edit, issue, void, payments, credit notes)
- Customer management (create, edit, search, profiles)
- PDF generation (without vehicle sections)
- Email/SMS notifications
- Reports (non-vehicle reports)
- Settings, branding, billing
- All other enabled modules (quotes, jobs, projects, etc.)

## Testing Checklist for Vehicle-Related Changes

When modifying any code that touches vehicle functionality:

1. ✅ Verify the feature works correctly when `vehicles` module IS enabled
2. ✅ Verify the feature is completely hidden/skipped when `vehicles` module is NOT enabled
3. ✅ Verify invoice creation works without vehicle fields when module is disabled
4. ✅ Verify invoice PDFs render cleanly without vehicle section when module is disabled
5. ✅ Verify no vehicle-related API calls are made from frontend when module is disabled
6. ✅ Verify customer search doesn't include vehicle data when module is disabled

## Key Files Reference

| Purpose | File |
|---------|------|
| Module service | `app/core/modules.py` |
| Module models | `app/modules/module_management/models.py` |
| Module context (frontend) | `frontend/src/contexts/ModuleContext.tsx` |
| ModuleGate component | `frontend/src/components/common/ModuleGate.tsx` |
| Vehicle models | `app/modules/vehicles/models.py` |
| Vehicle service | `app/modules/vehicles/service.py` |
| Vehicle router | `app/modules/vehicles/router.py` |
| Invoice service | `app/modules/invoices/service.py` |
| Invoice PDF template | `app/templates/pdf/invoice.html` |
| Invoice share template | `app/templates/pdf/invoice_share.html` |
| Invoice create (frontend) | `frontend/src/pages/invoices/InvoiceCreate.tsx` |
| Invoice list (frontend) | `frontend/src/pages/invoices/InvoiceList.tsx` |
| Vehicle search component | `frontend/src/components/vehicles/VehicleLiveSearch.tsx` |
| OrgLayout nav | `frontend/src/layouts/OrgLayout.tsx` |
| Feature flags | `app/core/feature_flags.py` |
