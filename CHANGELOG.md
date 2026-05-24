# Changelog

All notable changes to OraInvoice are documented in this file.

---

## [1.10.2] — 2026-05-25

### Added

- **Send Payment Link from invoice list** — new `Send` dropdown entry on the
  invoice list/detail panel that emails the customer the on-domain payment
  page URL (the same token-based page used by QR Payment, backed by a
  Stripe PaymentIntent — not a Stripe-hosted Checkout Session). Visible
  only when Stripe is connected and the invoice is in
  `issued`/`partially_paid`/`overdue` with a balance due. Reuses the org's
  active `invoice_issued` notification template (with a Pay Now button by
  default; user-customised templates honoured automatically) and the
  existing email provider chain. New endpoint:
  `POST /api/v1/payments/invoice/{id}/send-payment-link`.
- **Edit issued invoices (limited correction edit)** — the Edit button now
  appears on `issued`/`partially_paid`/`overdue` invoices. Only safe
  metadata can change: notes, due date, branch, vehicle metadata, payment
  terms, T&Cs. Line items, totals, customer, currency, and discount stay
  locked to keep GST/Xero/payments consistent. Voided/paid/refunded stay
  uneditable — use a credit note. Backend silently drops any non-editable
  fields and writes an audit log entry.

### Fixed

- **Vehicle details missing on invoice when only rego was supplied** — when
  converting a job card to an invoice (or any flow where only
  `vehicle_rego` reaches the backend, e.g. mobile minimal create or
  kiosk-registered customer picked in the new-invoice form), the invoice
  now backfills make/model/year/odometer from the org's `OrgVehicle` (or
  `GlobalVehicle` as fallback) keyed by rego. The existing
  `_resolve_vehicle_type` and `vehicle_display` snapshot then pick up
  inspection_type/WOF/COF/service-due automatically, matching the New
  Invoice form's display rules.
- **Fleet portal admin/reminders/accounts pages returned 500** —
  `/api/v2/fleet-portal/admin/accounts?limit=200` and
  `/fleet/api/reminders?limit=200` failed Pydantic validation because the
  shared `PaginatedResponse.limit` was capped at `le=100`. Lifted to
  `le=200` to match the admin views' actual page size.
- **Payment History columns visually joined on invoice list panel** — the
  Amount and Method cells touched on narrow widths. Both columns are now
  left-aligned with consistent right-padding so the values stay clearly
  separated.

---

## [1.10.0] — 2026-05-22

### Added — B2B Fleet Portal

A separate, password-based portal at `/fleet/*` (or `fleet.<domain>`)
for business customers (fleet operators) to manage their vehicle
fleets, drivers, NZTA pre-trip checklists, WOF/COF reminders,
service-booking and quote requests, and view invoices read-only. Gated
by the new `b2b-fleet-management` module (depends on `vehicles`,
restricted to the `automotive-transport` trade family).

- **Database**: migration `0191_b2b_fleet_portal.py` (head `0191`).
  16 new tables — `portal_accounts`, 5 portal-security tables, 9
  fleet-domain tables, plus `portal_account_devices`. Adds
  `customer_vehicles.fleet_checklist_template_id` and
  `portal_sessions.portal_account_id` discriminator. RLS policies on
  every new table; org + fleet account scoping via two parallel
  `set_config()` GUCs.
- **Backend module** at `app/modules/fleet_portal/`:
  - 16 SQLAlchemy ORM models, 56 Pydantic schemas
  - 13 portal API endpoints (`/fleet/api/*`) — auth, vehicles, hours,
    odometer, dashboard, version
  - 4 admin endpoints (`/api/v2/fleet-portal/admin/*`) — invite,
    revoke, resend-invite, list fleet accounts
  - URL resolver supporting subdomain, path, and single-tenant fallback
  - Module-disable cascade tears down active portal sessions
  - Security headers extended to `/fleet/api/*` (Cache-Control: no-store,
    Permissions-Policy with camera enabled, microphone/geolocation off)
- **Frontend SPA** at `frontend/src/fleet-portal/`:
  - Standalone provider tree mounted at `/fleet/*` — never shares
    chrome with `OrgLayout`
  - Login, forgot-password, dashboard, vehicle list pages
  - Fleet portal axios client with cookie auth + double-submit CSRF
  - Type-safe endpoint wrappers with `?? []` / `?? 0` consumption
- **Property tests**: 138 tests covering Properties 1–10, 12, 13, 16,
  17, 18, 22, 23, 24, 25, 26, 27, 30, 31, 33; auth state machine
  (lockout, password rules, bcrypt), URL resolution, CSRF,
  per-role field allowlist, odometer monotonicity, expiry badge,
  reminder predicate, NZTA seed, photo evidence at completion,
  booking and quote state machines, pagination shape.
- **Module registry**: `b2b-fleet-management` registered with
  `display_name = 'B2B Fleet Management'`, `dependencies = ['vehicles']`,
  setup question for the Setup Guide.
- **App version bumped** to 1.10.0; `/fleet/api/version` endpoint
  exposes version + build sha for the frontend version-refresh hook.

### Notes

The full mobile-app fleet portal flow (Capacitor 8 upgrade, native
auth screens, push notifications) and the workshop-admin SPA pages
under `frontend/src/fleet-portal-admin/` continue in subsequent
releases. The backend, property tests, and standalone fleet portal
SPA shell shipped in this release are complete and operational.

---

## [1.9.0] — 2026-05-15

### Added

- Invoice settings enable/disable toggles (email signature, default notes, payment terms, T&C)
- Email signature append on invoice and quote emails
- Default notes pre-fill on new invoices
- Payment terms and T&C sections in invoice web preview
- Toggle-aware PDF rendering for payment terms and T&C
- Rich text T&C field in invoice form (HTML preserved)

---

## [1.8.0] — 2026-05-08

### Added

- **Service Package Builder** — bundled service items that combine labour with inventory components (parts, fluids, tyres). Includes live cost calculation, profit tracking, invoice integration with automatic inventory deduction, and property-based test coverage.
  - Database: `is_package` and `package_components` JSONB columns on `items_catalogue`
  - Backend: package CRUD, cost resolution from live stock prices, component search endpoints, duplication support
  - Frontend: PackageBuilder component with inventory type selectors, fluid cascading dropdowns, cost summary (admin-only), package preview with stock warnings
  - Invoice integration: automatic inventory deduction on issue, fluid usage recording, snapshot cost fallback for unavailable components
  - Access control: cost/profit data restricted to admin roles
  - Module gating: requires both `vehicles` and `inventory` modules enabled
  - 18 property-based tests (Hypothesis) covering cost calculation, persistence, role gating, and inventory deduction correctness
  - Integration tests covering full lifecycle, invoice deduction, quote safety, and access control

---

## [1.7.0] — 2026-05-01

### Added

- Kiosk vehicle check-in multi-step flow (rego → vehicle summary → customer details)
- COF (Certificate of Fitness) expiry support alongside WOF

---

## [1.6.0] — 2026-04-15

### Added

- Xero accounting integration with webhooks and auto-sync
- Branch management and stock transfers

---

## [1.5.0] — 2026-04-01

### Added

- HA replication between Pi primary and local standby nodes
- Claims and scheduling modules

---

## [1.4.0] — 2026-03-15

### Added

- Initial production deployment
- Multi-tenant invoicing, quoting, customer management
- Role-based access control with JWT + Firebase auth
- Stripe billing integration
