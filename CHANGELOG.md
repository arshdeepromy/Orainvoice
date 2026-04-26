# Changelog

All notable changes to OraInvoice are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

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
