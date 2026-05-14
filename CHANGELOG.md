# Changelog

All notable changes to OraInvoice are documented in this file.

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
