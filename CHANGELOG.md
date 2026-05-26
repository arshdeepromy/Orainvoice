# Changelog

All notable changes to OraInvoice are documented in this file.

---

## [1.11.0] — 2026-05-26

### Added

- **QR partial-payment flow** — org users now see a small modal between
  the QR Payment button and the existing kiosk waiting popup that lets
  them pick Full (default) or Partial. Choosing Partial reveals an
  amount input pre-populated with `balance_due`; the typed amount is
  validated against the per-currency Stripe minimum ($0.50 NZD) and
  the invoice's outstanding balance, then sent to
  `POST /api/v1/payments/qr-session/existing` as the new optional
  `amount` field. Existing callers that omit `amount` get the
  pre-feature full-balance behaviour byte-for-byte. Implemented across
  `QrPaymentAmountModal`, `InvoiceList`, `InvoiceDetail`,
  `create_qr_session_for_existing_invoice`, and the public payment
  page (web + mobile).
- **`payment_tokens.amount_override` and `payment_tokens.last_pi_amount_cents`
  columns** — the per-token override carries the partial amount through
  to the public payment page and the surcharge recompute; the cached PI
  cents lets the reuse-branch decision skip a synchronous Stripe API
  call without sacrificing accuracy. Both are nullable so existing
  rows remain unaffected. Added in alembic revision `0193`.
- **`is_partial_payment` field on `PaymentPageResponse`** — `GET
  /api/v1/public/pay/{token}` now returns a boolean flag the public
  payment page consumes to display an informational banner ("You are
  paying a partial amount of $X. Please contact the business if you
  intended to pay the full balance.") and switch the payment-summary
  label from "Amount Due" to "Amount Due (Partial)". Defaults to
  `false` so older frontends ignore it cleanly.
- **Partial-payment-aware receipt emails** — when `email_invoice` fires
  after a partial payment is recorded (most recent Payment row exists,
  `balance_due > 0`, status in `partially_paid`/`overdue`), the
  hardcoded fallback subject becomes "Partial payment received for
  invoice {N} — ${X}" and the body is prefixed with "Payment
  received: $X.XX / Remaining balance: $Y.YY". Custom `invoice_send`
  templates pass through unchanged, preserving existing
  template-customisation semantics.
- **Audit log entries `payment.qr_session_created` and
  `payment.qr_session_superseded`** — fire on every new-PI path and
  whenever an old PaymentIntent is cancelled because the requested
  amount changed. Skipped on the reuse-branch path so duplicate audit
  entries are not emitted.
- **`expired` state on `QrPaymentWaitingPopup`** — when the polled
  status returns `expired` (e.g. the session was superseded by a
  newer payment attempt from another tab), the popup transitions to
  a "QR session superseded" state instead of polling forever.

### Changed

- **`create_payment_intent` accepts an `extra_metadata: dict[str, str]
  | None` parameter** — appended to the Stripe payload as
  `metadata[KEY]` form fields before the POST. Backwards-compatible:
  existing callers continue to work unchanged.

### Fixed

- **PI metadata now set at creation time** — `source: "kiosk_qr"`,
  `original_amount`, and `is_partial_payment` are written into
  `metadata` when the PaymentIntent is first created instead of
  waiting for the customer to reach `update-surcharge`. Closes a
  pre-existing detection-bug gap where `is_qr_payment` in the
  webhook handler was always `false` if the customer skipped
  payment-method selection. Applies to both new-invoice
  (`create_qr_payment_session`) and existing-invoice
  (`create_qr_session_for_existing_invoice`) paths.
- **Stale invoice PI fields cleared after the webhook records a
  payment** — `invoice.stripe_payment_intent_id`,
  `invoice.payment_page_url`, and the `stripe_client_secret` entry on
  `invoice.invoice_data_json` are reset on the success path. Without
  this, a second-partial QR click on the same invoice was entering
  the reuse-branch with a non-null PI ID that had already moved to a
  terminal state on Stripe, breaking the next surcharge update.
  Regression-fix discovered during the qr-partial-payment audit; the
  existing webhook handler is otherwise unchanged — partial payments
  record correctly via the existing `metadata.original_amount`
  plumbing.
- **Active payment_tokens deactivated in the webhook on payment
  completion** — closes a re-scan gap on the just-paid URL: the URL
  no longer stays active for its 72-hour TTL, so re-scans between
  payment-completion and the next partial-initiation now return a
  clean HTTP 404 ("Invalid payment link") instead of `is_payable=true`
  with a null `client_secret`.

### Compliance

- The 1.10.5 surcharge gross-up continues to apply to the partial
  amount, so the merchant nets exactly the typed partial. Stripe's
  per-currency minimum charge amounts are sourced from
  `STRIPE_MIN_BY_CURRENCY` so multi-currency invoicing (future work)
  needs only an entry in this dict — no code change.

### Tests

- 21 integration tests in `tests/test_qr_partial_payment_integration.py`
  including the highest-value `test_webhook_duplicate_event_for_partial_pi_idempotent`
  guarding against silent double-debits on Stripe at-least-once
  webhook delivery.
- 5 Hypothesis property tests in
  `tests/properties/test_qr_partial_properties.py` (cents round-trip,
  validation envelope inside/outside, webhook records exactly the
  partial within 1¢ regardless of surcharge configuration).
- 4 partial-receipt email tests in `tests/test_email_invoice_partial.py`.
- Updated frontend Vitest coverage for `QrPaymentAmountModal`,
  `QrPaymentWaitingPopup` (`expired` branch), `InvoiceList`,
  `InvoiceDetail`, the public payment page, and the mobile public
  payment screen.

### Migration

- Alembic revision `0193_payment_tokens_amount_override` — adds two
  nullable columns to `payment_tokens` (`amount_override NUMERIC(12,2)
  NULL` and `last_pi_amount_cents BIGINT NULL`). Idempotent
  (no backfill required), no table rewrite.

---

## [1.10.5] — 2026-05-26

### Fixed

- **Stripe surcharge undercollected on every payment** — the in-app
  Stripe payment page computed the surcharge as ``balance × p + fixed``
  and charged Stripe ``balance + surcharge``. Stripe then deducted its
  fee on the gross (which it computes as ``gross × p + fixed``), so
  the merchant absorbed a small shortfall on every transaction
  approximately equal to ``balance × p²``. For Afterpay (6%) on $240
  the merchant lost $0.88 per transaction; for card (2.9%) on $1000
  it was $0.84. The fix replaces the formula with the gross-up
  ``(balance × p + fixed) / (1 − p)`` so the gross charge fully
  covers Stripe's fee and the merchant nets exactly the invoice
  balance. Implemented in ``app/modules/payments/surcharge.py`` with
  matching client-side instant-display calculations in
  ``frontend/src/pages/public/InvoicePaymentPage.tsx`` and
  ``mobile/src/screens/auth/PublicPaymentScreen.tsx``. The frontend
  now also adopts the backend response's ``surcharge_amount`` as
  authoritative once available, eliminating any tiny float drift on
  the displayed value. Property tests in
  ``tests/properties/test_surcharge_properties.py`` were rewritten
  to assert the new formula and added a 200-example invariant
  verifying the merchant nets ≥ ``balance_due − $0.01`` after
  Stripe's fee on the gross charge for any combination of
  ``(balance, percentage, fixed)``. NZ Commerce Commission's
  May 2026 surcharge rules require surcharges to not exceed actual
  cost of acceptance — the gross-up is exactly cost recovery, no
  markup, so it remains compliant.

---

## [1.10.4] — 2026-05-26

### Fixed

- **Customer profile vehicle "Source" badge mislabelled CarJam as Manual** —
  the `LinkedVehicleResponse.source` field carries storage location
  (`'global'` vs `'org'`), but the customer profile UI rendered it as data
  origin, so every newly-promoted org-scoped vehicle (per the 1.10.3 isolation
  rollout) showed as "Manual" even when its data came from CarJam. Backend
  now also returns an explicit `origin` field (`'carjam'` / `'manual'`)
  derived from `org_vehicles.is_manual_entry` for org rows and always
  `'carjam'` for global rows. The customer profile badge uses the new field
  with a fallback to the old heuristic for backwards compatibility.
- **Invoice odometer edits silently dropped after first issue** — editing
  `vehicle_odometer` on an issued invoice (or duplicate-then-edit) updated
  the invoice row but did not propagate to `org_vehicles.odometer_last_recorded`
  or insert an `odometer_readings` history row. The vehicle profile and
  service-history aggregations stayed stale until a future invoice. The
  resolution gate in `update_invoice` now includes `vehicle_odometer`, and
  a write block mirroring `create_invoice` records the reading via the
  unified `record_odometer_reading` helper (with the manual-entry-only
  fallback to a direct write).
- **Kiosk existing-customer field updates emitted no audit row** — when a
  walk-in check-in updated `first_name` / `last_name` / `phone` / `email`
  on an existing customer (`existing_customer_id` payload branch), the
  edit landed silently with no `customer.updated` audit log entry, so the
  change was invisible on the merge/audit history. The kiosk service now
  captures per-field before/after values and writes a `customer.updated`
  row matching the standard customer update service shape, with
  `entity_type=customer`, `org_id`, `user_id`, and `ip_address`.

---

## [1.10.3] — 2026-05-25

### Fixed

- **Vehicle data isolation** — customer-driven vehicle fields (odometer,
  service-due date, WOF expiry, COF expiry, inspection type) are now
  strictly per-organisation. Previously every org's writes landed on the
  shared `global_vehicles` cache, so workshop A's odometer reading was
  immediately visible to workshop B as soon as B looked up the same rego.
  Customer-driven flows (invoice create/update, kiosk check-in, fleet portal
  odometer/service-due updates, customer-vehicle link creation) now lazily
  promote the rego for the calling org on first touch — copying the row
  into `org_vehicles` and migrating any existing `customer_vehicles` link
  to `org_vehicle_id`. Subsequent customer-driven writes target the per-org
  snapshot. CarJam refresh continues to write the spec cache on
  `global_vehicles`. Read paths fall back to `global_vehicles` until the
  org is promoted, so existing data and existing workflows continue to
  function unchanged.
- **Fleet portal odometer log raised AttributeError on every call** — the
  helper at `app/modules/fleet_portal/services/vehicle_service.py::log_odometer_reading`
  referenced a non-existent `OdometerReading.odometer_km` column. The
  actual column on the model is `reading_km`. Both the `select(func.max(...))`
  aggregation and the `OdometerReading(...)` constructor are now corrected.
  The helper also writes `source="manual"` so the inserted row satisfies
  the `ck_odometer_readings_source` CHECK constraint.
- **Invoice update silently dropped `vehicle_cof_expiry_date`** — the field
  was missing from `UpdateInvoiceRequest` in `app/modules/invoices/schemas.py`,
  and `update_invoice` had no COF write branch. The schema now accepts the
  field, the resolution gate includes it, and the COF write branch mirrors
  the existing WOF branch.
- **`PUT /api/v1/customers/{id}/vehicle-dates` silently dropped `cof_expiry`** —
  the endpoint only handled `service_due_date` and `wof_expiry`. Now also
  handles `cof_expiry`. Writes target `org_vehicles` (after lazy promotion)
  rather than `global_vehicles`.
- **Dashboard expiry-reminders widget queried a non-existent column** — the
  widget joined `org_vehicles ov ON ov.global_vehicle_id = gv.id`, but
  `org_vehicles.global_vehicle_id` is not a column on the model. The widget
  now reads from `org_vehicles` directly for promoted vehicles and from
  `global_vehicles` via `customer_vehicles` for un-promoted links. The
  customer-name lookup now accepts either link type.
- **Invoice display leaked cross-tenant `global_vehicles` Customer_Driven_Fields** —
  `get_invoice` and `view_shared_invoice` (the public portal-token endpoint)
  looked up `GlobalVehicle` by rego first. Inverted to prefer `OrgVehicle`
  scoped to the invoice's `org_id`, falling back to `GlobalVehicle` only
  when the org has no row for that rego.
- **Notification/reminder services dropped reminders for promoted vehicles** —
  three call sites in `notifications/service.py` and
  `reminder_queue_service.py` did inner joins against `global_vehicles`,
  silently excluding every link migrated to `org_vehicle_id`. Replaced with
  two-pass queries covering both link types. Dedup keys standardised on
  `customer_vehicles.id` so they survive the link migration.
- **Data export CSV mislabelled promoted vehicles as `manual`** —
  `data_io/service.py::export_vehicles_csv` hardcoded `"manual"` for every
  `org_vehicles` row, but promoted rows have `is_manual_entry=False` and
  were originally CarJam-sourced. The label is now
  `("manual" if v.is_manual_entry else "carjam")`.

### Security

- **Closed multi-tenant data-leakage defect** — customer-driven vehicle
  fields are now strictly isolated per organisation. One workshop's
  odometer / WOF / COF / service-due / inspection-type writes are no
  longer visible to other workshops via the shared `global_vehicles`
  CarJam cache. RLS policies on `org_vehicles` and `customer_vehicles`
  remain unchanged; the fix is a behavioural redirect that targets the
  org-scoped table on every customer-driven write.
- New audit-log actions: `vehicle.promote` (emitted on first promotion
  of a rego per org, with `trigger_site` carried in `after_value`) and
  `vehicle.manual_refresh` (emitted by the explicit "Refresh from CarJam"
  action). Concurrent promotions for the same `(org_id, rego)` converge
  on a single row via PostgreSQL advisory transaction lock
  (`pg_advisory_xact_lock(hashtext(org_id), hashtext(rego))`); no schema
  change required.

### Notes

- **One-time reminder duplication** — reminder dedup keys were migrated
  from a vehicle-id-based scheme to a link-id-based scheme so dedup
  survives the new vehicle isolation. As a one-time consequence,
  reminders that fall within the lookahead window (≤ 30 days for
  service-due, ≤ 14 days for WOF/COF) and were already sent before this
  release may be sent a second time on the next scheduler run.
  Subsequent runs dedup correctly.

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
