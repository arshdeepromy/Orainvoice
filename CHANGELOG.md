# Changelog

All notable changes to OraInvoice are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [1.2.0] - 2026-04-28

### Added
- Public landing page at `/` for unauthenticated visitors — hero section, 8 feature categories (26 features), pricing card ($60/month Mech Pro Plan), testimonials, CTA, responsive from 320px to 1920px
- Public privacy policy page at `/privacy` — full NZ Privacy Act 2020 compliant default policy covering all 13 IPPs, with admin-editable custom content via Markdown
- Public supported trades page at `/trades` — Automotive & Transport, General Invoicing (available), Plumbing & Gas, Electrical & Mechanical (coming soon)
- Demo request flow: `POST /api/v1/public/demo-request` with honeypot bot filtering, Redis rate limiting (5/hr/IP), SMTP email failover
- Privacy policy admin editor: new "Privacy Policy" tab in Global Admin Settings with Markdown editor, preview, and reset to default
- Privacy policy API: `GET /api/v1/public/privacy-policy` (public) and `PUT /api/v1/admin/privacy-policy` (global_admin)
- Dark mode logo support: new `dark_logo_url` field in platform branding — upload via admin branding page, automatically used on dark/coloured backgrounds (landing page header, admin sidebar preview), regular logo used on light backgrounds
- Migration 0164: add `dark_logo_url` column to `platform_branding`
- Shared public page components: LandingHeader (sticky nav, mobile hamburger), LandingFooter (4-column responsive), DemoRequestModal (form with honeypot)
- Landing page module: `app/modules/landing/` with router, schemas, public + admin endpoints
- Plumbing service types: trade-family-gated service type management
- Job card attachments: file upload/download for job cards
- Job card invoice appendix: HTML snapshot of job card appended to invoice PDF
- 44 backend tests for landing page (unit, integration, RBAC, validation)
- 4 property-based tests (Hypothesis, 100 examples each): demo form validation, rate limiting, honeypot rejection, privacy policy round-trip

### Fixed
- ISSUE-144: `get_todays_bookings` referenced non-existent `bookings.customer_id` column — crashed entire dashboard widgets endpoint. Fixed to use `b.customer_name` directly.
- ISSUE-145: Rate limiter `except Exception` handler called `self.app()` a second time after response already sent — caused ASGI double-response crash. Fixed to `raise` instead of retrying.
- Public pages unable to scroll due to global `overflow: hidden` on html/body/#root — added `public-page` CSS class override applied by each public page on mount
- Landing page logo too small (h-8 → h-12)
- Mech Pro Plan price corrected from $99 to $60 NZD/month excluding GST

## [1.1.1] - 2026-04-28

### Fixed
- Invoice vehicle FK fix: `create_invoice()` no longer crashes with `ForeignKeyViolationError` when creating invoices with org-scoped vehicles. Added `_resolve_vehicle_type()` helper that checks `global_vehicles` first, then `org_vehicles`, and routes linking/metadata logic to the correct table.
- Invoice vehicle FK fix: `update_invoice()` now correctly updates `org_vehicles` metadata (service_due_date, wof_expiry) instead of silently skipping when the vehicle is org-scoped.
- Invoice vehicle FK fix: duplicate-link detection now works for org vehicles (queries `org_vehicle_id` column instead of only `global_vehicle_id`).
- Invoice vehicle FK fix: odometer recording for org vehicles updates `OrgVehicle.odometer_last_recorded` directly (bypasses `record_odometer_reading()` which only supports global vehicles).
- Items catalogue GST badge: table now correctly shows "Incl." / "Excl." / "Exempt" instead of showing "Incl." for all non-exempt items. Added missing `gst_inclusive` field to the frontend `Item` interface.

## [1.1.0] - 2026-04-26

### Added
- Setup guide: question-driven module onboarding replacing wizard step 5
  - Backend: migration 0158 (setup_question columns + seed data), schemas, router with 6 correctness properties
  - Frontend: WelcomeScreen, QuestionCard, SummaryScreen, SetupGuide page
  - 26 property-based tests, 10 unit tests, 18 integration tests
  - Steering doc for future module developers
  - Settings re-run button + user menu link
- Mobile dashboard: Zoho-style redesign with quick actions, receivables summary, aging chart, recent transactions tabs, income/expense chart, top expenses
- Mobile customer list: avatar initials with colored backgrounds, Active/Unpaid/All filter tabs, receivables/credits per customer, FAB button
- Mobile customer profile: quick action circles (Call/Mail/Message/More), financial summary, billing/shipping addresses, primary contact, More bottom sheet, Edit button
- Mobile customer edit screen: type toggle, salutation, name fields, payment terms, sends only changed fields
- Setup wizard auto-redirect for new org admins on first login
- Migration 0159: backfill wizard_completed=true for existing orgs (safe prod deploy)
- Expenses page: list-first layout with "+ Expense" modal containing all three tabs
- Setup Guide link in top-right user menu for org admins
- Versioning steering doc and CHANGELOG

### Changed
- Setup wizard: removed Country/Trade steps (captured during signup, no longer needed)
- Setup wizard: structured address fields (unit, street, city, state, postcode) matching Settings page
- Setup wizard ReadyStep fetches real org data from backend instead of local state
- Expense modal widened to max-w-3xl for proper form display
- NZ IRD validation: accepts 8-9 digits with auto-dash formatting as user types
- Watch-build.sh: disabled aggressive stale asset cleanup that was deleting lazy-loaded chunks

### Fixed
- ISSUE-113: v2 double-prefix bug in 16 files (setup wizard + inventory pages)
- Setup wizard country defaults crash from double-encoded JSONB tax rates
- CataloguePage corrupted import statement
- Setup wizard step key mismatch (step_X_complete vs step_X in progress response)
- JSONB merge syntax error (::jsonb cast vs CAST() for asyncpg compatibility)
- Expense form: hidden Customer Name, Projects, Billable fields (features not yet complete)

## [1.0.0] - 2026-04-08

### Notes
- Initial production release
- 132 database tables, 112 issues tracked and resolved
- Full invoicing, quoting, job management, inventory, POS, scheduling, staff, bookings
- Multi-org, multi-branch, role-based access, trade-family gating
- Stripe billing, Xero accounting integration, SMS via Connexus
- Mobile app (Capacitor) with offline support
- HA replication between Pi primary and local standby
