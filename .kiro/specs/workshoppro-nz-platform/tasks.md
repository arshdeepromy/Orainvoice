# Implementation Plan: WorkshopPro NZ Platform

## Overview

This plan implements the WorkshopPro NZ multi-tenant SaaS platform using FastAPI (Python) backend, React + Tailwind CSS frontend, PostgreSQL with RLS, Redis, Celery, and integrations with Stripe, Carjam, Brevo/SendGrid, Twilio, Xero, and MYOB. Tasks are ordered so that foundational infrastructure is built first, then core modules, then advanced features, and finally frontend pages.

## Tasks

- [x] 1. Project scaffolding and configuration
  - [x] 1.1 Initialise FastAPI backend project structure
    - Create the `app/` directory tree as defined in the design: `main.py`, `config.py`, `middleware/`, `modules/`, `integrations/`, `tasks/`, `core/`, `templates/`
    - Set up `pyproject.toml` with dependencies: fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, redis, celery, pydantic, python-jose, passlib, weasyprint, httpx, hypothesis
    - Create `config.py` loading all settings from environment variables (database URL, Redis URL, Stripe keys, JWT secret, etc.)
    - _Requirements: 82.1_

  - [x] 1.2 Initialise React frontend project structure
    - Create the `src/` directory tree as defined in the design: `api/`, `hooks/`, `contexts/`, `layouts/`, `pages/`, `components/`, `utils/`
    - Set up Vite + React + TypeScript + Tailwind CSS
    - Configure `api/client.ts` with Axios instance, JWT interceptor, and automatic token refresh
    - _Requirements: 55.5_

  - [x] 1.3 Set up Docker Compose for local development
    - Create `docker-compose.yml` with services: FastAPI app, PostgreSQL, Redis, Celery worker, Celery Beat
    - Create `.env.example` with all required environment variables
    - _Requirements: 82.1, 82.3_

  - [x] 1.4 Set up core middleware stack
    - Implement `middleware/auth.py` — JWT validation, org_id extraction from token
    - Implement `middleware/tenant.py` — set `app.current_org_id` on each DB session for RLS
    - Implement `middleware/rate_limit.py` — Redis sliding window rate limiter (100 req/min per user, 1000/min per org, 10/min per IP on auth endpoints)
    - Implement `middleware/security_headers.py` — CSP, HSTS, X-Frame-Options, X-Content-Type-Options, CSRF protection
    - _Requirements: 1.6, 52.3, 52.4, 71.1, 71.2, 71.3, 71.4_

  - [x] 1.5 Set up core utilities
    - Implement `core/database.py` — SQLAlchemy async engine, session factory, RLS session setup
    - Implement `core/redis.py` — Redis connection pool
    - Implement `core/encryption.py` — envelope encryption for secrets (integration credentials, webhook secrets, MFA secrets)
    - Implement `core/audit.py` — append-only audit log helper
    - Implement `core/errors.py` — error logging service with severity, category, and sanitisation
    - _Requirements: 48.5, 51.1, 51.2, 49.1, 49.2_

- [x] 2. Database schema and migrations
  - [x] 2.1 Set up Alembic migration framework
    - Initialise Alembic with async SQLAlchemy support
    - Configure migration environment for PostgreSQL
    - _Requirements: 82.2_

  - [x] 2.2 Create global tables migration
    - Create `subscription_plans`, `organisations`, `global_vehicles`, `integration_configs`, `platform_settings` tables as defined in the design
    - Create indexes on `global_vehicles(rego)`
    - _Requirements: 40.1, 14.4, 48.1, 50.1_

  - [x] 2.3 Create tenant-scoped tables migration (users, sessions, branches, customers)
    - Create `users`, `sessions`, `branches`, `customers`, `fleet_accounts` tables with RLS policies enabled
    - Create indexes: `users(org_id)`, `users(email)`, `customers(org_id)`, full-text search GIN index on customers
    - _Requirements: 5.1, 11.5, 11.6, 66.1_

  - [x] 2.4 Create vehicle tables migration
    - Create `org_vehicles`, `customer_vehicles` tables with RLS and the `vehicle_link_check` constraint
    - _Requirements: 14.7, 15.1, 15.2_

  - [x] 2.5 Create catalogue and inventory tables migration
    - Create `service_catalogue`, `parts_catalogue`, `suppliers`, `part_suppliers`, `labour_rates` tables with RLS
    - _Requirements: 27.1, 28.1, 28.3, 63.1, 63.2_

  - [x] 2.6 Create invoice, line items, payments, credit notes tables migration
    - Create `invoices`, `line_items`, `credit_notes`, `payments` tables with RLS and all indexes as defined in the design
    - Create `invoice_sequences`, `quote_sequences`, `credit_note_sequences` tables for gap-free numbering
    - _Requirements: 17.1, 18.1, 19.1, 20.1, 23.1, 24.1, 25.1, 26.1_

  - [x] 2.7 Create quotes, job cards, time entries, recurring schedules, bookings tables migration
    - Create `quotes`, `quote_line_items`, `job_cards`, `job_card_items`, `time_entries`, `recurring_schedules`, `bookings` tables with RLS
    - _Requirements: 58.1, 59.1, 60.1, 64.1, 65.1_

  - [x] 2.8 Create notification, audit, error log, webhook, accounting, discount, stock tables migration
    - Create `notification_templates`, `notification_log`, `overdue_reminder_rules`, `notification_preferences` tables with RLS
    - Create `audit_log` (append-only, REVOKE UPDATE/DELETE), `error_log`, `webhooks`, `webhook_deliveries` tables
    - Create `accounting_integrations`, `accounting_sync_log`, `discount_rules`, `stock_movements` tables with RLS
    - _Requirements: 34.3, 35.1, 38.1, 49.2, 51.3, 70.1, 68.1, 67.1, 62.1_

  - [x] 2.9 Create RLS policies for all tenant-scoped tables
    - Write a migration that creates `tenant_isolation` RLS policies on every tenant-scoped table using `current_setting('app.current_org_id')::uuid`
    - Revoke UPDATE and DELETE on `audit_log` from the application database role
    - _Requirements: 54.1, 54.2, 51.3_

- [x] 3. Checkpoint — Verify database setup
  - Ensure all migrations run cleanly, RLS policies are active, and the audit_log is append-only. Ask the user if questions arise.

- [x] 4. Authentication, Security & Identity module
  - [x] 4.1 Implement email/password login endpoint
    - Create `modules/auth/router.py` with `POST /api/v1/auth/login`
    - Implement password verification with passlib (bcrypt), JWT pair issuance (15-min access, 7-day refresh), and "Remember this device" (30-day refresh)
    - Record successful login in audit log (timestamp, IP, device, browser) and failed login (timestamp, IP, reason)
    - _Requirements: 1.1, 1.2, 1.7, 1.8_

  - [x] 4.2 Implement refresh token rotation with reuse detection
    - Create `POST /api/v1/auth/token/refresh` endpoint
    - Implement refresh token rotation using `family_id` — on reuse, invalidate entire family and send email alert
    - _Requirements: 1.5_

  - [x] 4.3 Implement Google OAuth login
    - Create `integrations/google_oauth.py` client
    - Create `POST /api/v1/auth/login/google` endpoint — authenticate via Google OAuth 2.0, create or link account by email
    - _Requirements: 1.3_

  - [x] 4.4 Implement Passkey (WebAuthn) authentication
    - Create `POST /api/v1/auth/login/passkey` endpoint using py_webauthn library
    - Passkey login satisfies MFA requirement (no additional MFA prompt)
    - _Requirements: 1.4, 2.9_

  - [x] 4.5 Implement MFA enrolment and verification
    - Create `POST /api/v1/auth/mfa/enrol` — support TOTP (QR code), SMS OTP (Twilio), email OTP
    - Create `POST /api/v1/auth/mfa/verify` — verify 6-digit code for any method
    - Create `POST /api/v1/auth/mfa/backup-codes` — generate 10 single-use hashed backup codes
    - Support multiple simultaneous MFA methods with fallback chain
    - Enforce MFA on every login for Global_Admin accounts
    - Redirect users without MFA to setup screen when org MFA is mandatory
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

  - [x] 4.6 Implement account lockout and brute force protection
    - 5 consecutive failures → 15-minute lock; 10 failures → permanent lock + email
    - Implement HaveIBeenPwned password check via `integrations/hibp.py` (k-anonymity)
    - Implement anomalous login detection (new country, new device, unusual time) with email alert and "This wasn't me" link
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 4.7 Implement session management
    - Create `GET /api/v1/auth/sessions` — list active sessions with device, IP, last activity
    - Create `DELETE /api/v1/auth/sessions/{id}` — terminate a session
    - Enforce configurable max concurrent sessions per user (default 5), revoke oldest when exceeded
    - _Requirements: 3.6, 3.7, 3.8_

  - [x] 4.8 Implement password recovery
    - Create `POST /api/v1/auth/password/reset-request` — send reset link (1-hour expiry), uniform response for existing/non-existing emails
    - Create `POST /api/v1/auth/password/reset` — complete reset, invalidate all sessions
    - Support recovery via MFA backup codes
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 4.9 Implement RBAC middleware and role enforcement
    - Enforce three roles (Global_Admin, Org_Admin, Salesperson) on every API request
    - Verify role + org membership before processing
    - Salesperson denied org settings/billing/user management; Org_Admin denied global admin; Global_Admin denied org customer/invoice data
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 4.10 Implement IP allowlisting
    - Create IP allowlist check in auth middleware, configurable per org
    - Validate current session IP is in allowlist before saving (prevent self-lockout)
    - Return clear error and log blocked attempts
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 4.11 Implement email verification for new accounts
    - Create invitation email with secure signup link (48-hour expiry)
    - Mark email as verified on link click, allow password setup
    - Allow Org_Admin to resend expired invitations
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 4.12 Write property tests for auth module
    - **Property 7: Authentication Events Are Fully Logged** — verify all auth events produce complete audit entries
    - **Property 8: Refresh Token Rotation Detects Reuse** — verify reused tokens invalidate the family
    - **Property 9: Account Lockout After Failed Attempts** — verify 5→lock 15min, 10→permanent lock
    - **Property 10: Session Limit Enforcement** — verify active sessions ≤ configured max
    - **Property 11: Password Reset Response Uniformity** — verify identical responses for existing/non-existing emails
    - **Property 12: RBAC Enforcement** — verify role determines endpoint access
    - **Property 13: IP Allowlist Enforcement** — verify non-allowlisted IPs are rejected
    - **Validates: Requirements 1.5, 1.7, 1.8, 3.1, 3.2, 3.6, 4.4, 5.2, 5.3, 5.4, 5.5, 6.1, 6.3**


- [x] 5. Checkpoint — Verify auth module
  - Ensure all auth endpoints work correctly, JWT issuance/refresh/rotation, MFA flows, RBAC enforcement, and session management. Ask the user if questions arise.

- [x] 6. Organisation Management module
  - [x] 6.1 Implement organisation provisioning
    - Create `POST /api/v1/admin/organisations` — Global_Admin provisions new org, creates record, assigns plan, generates Org_Admin invitation email
    - _Requirements: 8.1_

  - [x] 6.2 Implement onboarding wizard API
    - Create `POST /api/v1/org/onboarding` — save each wizard step (org name, logo, brand colours, GST number, GST %, invoice prefix, starting number, payment terms, first service type)
    - Allow any step to be skipped; workspace usable immediately regardless of completion
    - _Requirements: 8.2, 8.3, 8.4, 8.5_

  - [x] 6.3 Implement organisation settings CRUD
    - Create `GET /PUT /api/v1/org/settings` — configure name, logo (PNG/SVG), colours, address, phone, email, invoice header/footer, email signature
    - GST number validation (IRD format), GST %, GST-inclusive/exclusive toggle
    - Invoice prefix, starting number, default due days, default notes, payment terms, custom T&C (rich text)
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [x] 6.4 Implement branch management
    - Create `GET /POST /api/v1/org/branches` — multiple branches per org, each with address and phone
    - Allow users to be assigned to one or more branches
    - _Requirements: 9.7, 9.8_

  - [x] 6.5 Implement user management
    - Create `GET /POST /PUT /DELETE /api/v1/org/users` — invite users (48-hour link), assign roles, deactivate (invalidate sessions)
    - Configure MFA policy (optional/mandatory), enforce user seat limits per plan
    - Display upgrade message when seat limit reached
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 6.6 Implement public signup flow
    - Create public signup endpoint — create org, start 14-day trial, collect card via Stripe SetupIntent, trigger onboarding wizard
    - _Requirements: 8.6_

  - [x] 6.7 Write unit tests for organisation module
    - Test onboarding wizard step saving and skipping
    - Test GST number validation (IRD format)
    - Test seat limit enforcement
    - _Requirements: 8.2, 8.4, 9.3, 10.4_

- [x] 7. Customer Management module
  - [x] 7.1 Implement customer CRUD and search
    - Create `GET /POST /PUT /api/v1/customers` — live search by name, phone, email with dropdown results
    - Inline "Create new customer" from search dropdown (first name, last name, email, phone, optional address)
    - Store customer records scoped to org (never shared across orgs)
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [x] 7.2 Implement customer profile and history
    - Create `GET /api/v1/customers/{id}` — return linked vehicles, full invoice history, total spend, outstanding balance
    - Create `POST /api/v1/customers/{id}/notify` — send one-off email or SMS from profile
    - Allow tagging vehicles to customers
    - _Requirements: 12.1, 12.2, 12.3_

  - [x] 7.3 Implement customer record merging
    - Create `POST /api/v1/customers/{id}/merge` — combine invoice history, vehicles, contact details with confirmation preview
    - _Requirements: 12.4_

  - [x] 7.4 Implement Privacy Act 2020 compliance
    - Create `DELETE /api/v1/customers/{id}` — anonymise linked invoices (replace name with "Anonymised Customer", clear contact details), preserve financial records
    - Create `GET /api/v1/customers/{id}/export` — export all customer data as JSON
    - Ensure PII never written to application logs or error reports
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

  - [x] 7.5 Implement fleet account management
    - Create fleet account CRUD — group multiple vehicles under commercial customer, primary contact, billing address
    - Support fleet-specific pricing overrides on catalogue items
    - _Requirements: 66.1, 66.2_

  - [x] 7.6 Implement customer loyalty and discount programs
    - Create `discount_rules` CRUD — rules based on visit count, spend threshold, or customer tags
    - Auto-apply qualifying discounts to new invoices with visible label
    - Allow manual assignment/removal of discount eligibility
    - _Requirements: 67.1, 67.2, 67.3_

  - [x] 7.7 Write property test for customer anonymisation
    - **Property 14: Customer Anonymisation Preserves Financial Records** — verify deletion anonymises customer but preserves invoice amounts, line items, and payment history
    - **Validates: Requirements 13.2**

- [x] 8. Vehicle Management & Carjam Integration module
  - [x] 8.1 Implement Carjam API client
    - Create `integrations/carjam.py` — HTTP client with Redis rate limiting (global rate limit configurable by Global_Admin)
    - _Requirements: 16.2_

  - [x] 8.2 Implement vehicle lookup (cache-first)
    - Create `GET /api/v1/vehicles/lookup/{rego}` — check Global_Vehicle_DB first; if miss, call Carjam API, store result, increment org counter
    - Store all Carjam fields: rego, make, model, year, colour, body type, fuel type, engine size, seats, WOF expiry, rego expiry, odometer, last pulled timestamp
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [x] 8.3 Implement vehicle refresh and manual entry
    - Create `POST /api/v1/vehicles/{id}/refresh` — force Carjam re-fetch, update Global_Vehicle_DB, charge org
    - Create `POST /api/v1/vehicles/manual` — manual entry stored in org_vehicles (not Global_Vehicle_DB), marked as "manually entered"
    - If Carjam returns no result, present manual entry form
    - _Requirements: 14.5, 14.6, 14.7_

  - [x] 8.4 Implement vehicle linking and profile
    - Create `POST /api/v1/vehicles/{id}/link` — link vehicle to customer (same global vehicle can link to different customers across orgs)
    - Create `GET /api/v1/vehicles/{id}` — vehicle profile with Carjam data, linked customers, odometer history, service history, WOF/rego expiry indicators (green >60d, amber 30-60d, red <30d)
    - _Requirements: 15.1, 15.2, 15.3, 15.4_

  - [x] 8.5 Implement Carjam usage monitoring
    - Create admin endpoint for real-time Carjam usage table per org (total lookups, included, overage, charge)
    - Display org Carjam usage on billing dashboard
    - _Requirements: 16.1, 16.4_

  - [x] 8.6 Write property test for vehicle lookup caching
    - **Property 15: Vehicle Lookup Cache-First with Accurate Counter** — verify cache hit → no API call + no counter increment; cache miss → API call + counter increment by 1
    - **Validates: Requirements 14.1, 14.2, 14.3**

- [x] 9. Checkpoint — Verify org, customer, and vehicle modules
  - Ensure organisation provisioning, onboarding, customer CRUD/search/merge/anonymisation, vehicle lookup/caching, and Carjam integration all work correctly. Ask the user if questions arise.


- [ ] 10. Invoice Management module
  - [x] 10.1 Implement invoice creation endpoint
    - Create `POST /api/v1/invoices` — single-screen flow: customer selection, vehicle selection (auto-populate from Vehicle_Module), line items, totals
    - Auto-calculate subtotal (ex-GST), GST amount, GST-inclusive total as line items are added
    - Support saving as Draft (no invoice number, fully editable) or issuing (assigns sequential number with org prefix, locks structural edits)
    - _Requirements: 17.1, 17.3, 17.4, 17.5, 17.6_

  - [x] 10.2 Implement invoice line items
    - Support three types: Service (catalogue selection with pre-filled price), Part (description, part number, quantity, unit price), Labour (description, hours, hourly rate from configured rates)
    - Support warranty notes per line item, GST-exempt toggle per line, discounts per line (percentage/fixed), invoice-level discounts
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7_

  - [x] 10.3 Implement invoice status lifecycle
    - Enforce status state machine: Draft → Issued → {Partially Paid, Overdue} → Paid; any non-Voided → Voided
    - Draft: free editing, no number; Issued: sequential number, locked structural edits (notes still editable)
    - Overdue: auto-update at midnight when due date passes with outstanding balance
    - Voided: retain number, require reason (audit log), exclude from revenue reporting
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7_

  - [x] 10.4 Implement gap-free invoice numbering
    - Use `SELECT ... FOR UPDATE` on `invoice_sequences` within a transaction for contiguous numbering
    - Prevent any modification to assigned invoice numbers via API
    - Record all state changes in tamper-evident audit log with before/after values
    - _Requirements: 23.1, 23.2, 23.3_

  - [x] 10.5 Implement credit notes
    - Create `POST /api/v1/invoices/{id}/credit-note` — separate document linked to original invoice with own reference number (CN-prefix)
    - Display what is being credited and reason; update net balance on original invoice; adjust revenue reporting
    - Prompt for Stripe refund when credit note issued against Stripe-paid invoice
    - _Requirements: 20.1, 20.2, 20.3, 20.4_

  - [x] 10.6 Implement invoice search and filtering
    - Create `GET /api/v1/invoices` — search by invoice number, rego, customer name/phone/email, date range
    - Instant results as user types; stackable filters; display number, customer, rego, total, status, issue date
    - _Requirements: 21.1, 21.2, 21.3, 21.4_

  - [x] 10.7 Implement invoice duplication
    - Create `POST /api/v1/invoices/{id}/duplicate` — new Draft pre-filled with same customer, vehicle, line items; no number until issued
    - _Requirements: 22.1, 22.2_

  - [x] 10.8 Implement NZ tax invoice compliance
    - Ensure every issued invoice includes: "Tax Invoice" label, supplier name + GST number, invoice date, description of goods/services, total including GST, GST amount
    - For invoices >$1,000 NZD (incl. GST): include buyer name and address
    - Clearly distinguish taxable vs GST-exempt line items on PDF
    - _Requirements: 80.1, 80.2, 80.3_

  - [x] 10.9 Implement recurring invoices
    - Create recurring schedule CRUD — linked to customer, configurable frequency (weekly/fortnightly/monthly/quarterly/annually)
    - Auto-generate Draft or Issued invoice when due; allow view/edit/pause/cancel; notify Org_Admin on generation
    - _Requirements: 60.1, 60.2, 60.3, 60.4_

  - [x] 10.10 Implement multi-currency support
    - Default NZD; when enabled by Org_Admin, allow currency selection per invoice
    - Display currency symbol and code on PDF; report revenue in NZD with exchange rate at creation time
    - _Requirements: 79.1, 79.2, 79.3, 79.4_

  - [x] 10.11 Write property tests for invoice module
    - **Property 2: Invoice Number Contiguity** — verify issued numbers form gap-free sequence per org
    - **Property 3: Invoice Number Immutability** — verify issued numbers cannot be modified
    - **Property 4: GST Calculation Correctness** — verify subtotal, GST, total math for arbitrary line item mixes
    - **Property 5: Invoice Balance Consistency** — verify amount_paid + credit_note_total + balance_due = total always
    - **Property 21: NZ Tax Invoice Compliance** — verify all required fields present, $1,000 threshold for buyer details
    - **Property 22: Invoice Status State Machine** — verify only valid transitions succeed
    - **Validates: Requirements 17.5, 18.6, 18.7, 19.1-19.7, 20.3, 23.1, 23.2, 24.1-24.3, 80.1, 80.2**

- [ ] 11. Payment Processing module
  - [x] 11.1 Implement cash payment recording
    - Create `POST /api/v1/payments/cash` — capture amount, timestamp, recording user
    - Update invoice status to Paid (full balance cleared) or Partially Paid (partial amount) with remaining balance display
    - _Requirements: 24.1, 24.2, 24.3_

  - [x] 11.2 Implement Stripe Connect setup
    - Create `POST /api/v1/billing/stripe/connect` and `GET /api/v1/billing/stripe/connect/callback` — Stripe Connect OAuth flow for org-level payment setup
    - Never handle raw card data (Stripe.js hosted fields only)
    - _Requirements: 25.1, 25.2_

  - [x] 11.3 Implement Stripe payment link generation
    - Create `POST /api/v1/payments/stripe/create-link` — generate secure payment link, send via email or SMS
    - Support partial Stripe payments for deposit scenarios
    - _Requirements: 25.3, 25.5_

  - [x] 11.4 Implement Stripe webhook receiver
    - Create `POST /api/v1/payments/stripe/webhook` — verify Stripe signature, update invoice status in real time, auto-email payment receipt
    - _Requirements: 25.4_

  - [x] 11.5 Implement payment history and refunds
    - Create `GET /api/v1/payments/invoice/{id}/history` — full payment history per invoice (date, amount, method, recording user)
    - Create `POST /api/v1/payments/refund` — Stripe refund via API or manual cash refund with note; update invoice balance
    - Include all payment/refund events in audit log
    - _Requirements: 26.1, 26.2, 26.3, 26.4_

  - [x] 11.6 Write unit tests for payment module
    - Test cash payment status transitions (Partially Paid, Paid)
    - Test Stripe webhook signature verification
    - Test refund balance calculations
    - _Requirements: 24.1, 24.2, 24.3, 25.4, 26.2_

- [ ] 12. Service & Parts Catalogue module
  - [x] 12.1 Implement service catalogue CRUD
    - Create `GET /POST /PUT /api/v1/catalogue/services` — service name, description, default price (ex-GST), GST toggle, category (warrant/service/repair/diagnostic), active/inactive toggle
    - Inactive services hidden from invoice creation but retained for historical display
    - Catalogue prices overridable per invoice line item
    - _Requirements: 27.1, 27.2, 27.3_

  - [x] 12.2 Implement parts catalogue and labour rates
    - Create `GET /POST /api/v1/catalogue/parts` — pre-load parts with name, part number, default price, supplier
    - Allow ad-hoc parts per invoice without pre-loading
    - Create `GET /POST /api/v1/catalogue/labour-rates` — configure named labour rates with hourly rate
    - _Requirements: 28.1, 28.2, 28.3_

  - [x] 12.3 Write unit tests for catalogue module
    - Test inactive service hiding from invoice creation
    - Test price override per line item
    - _Requirements: 27.2, 27.3_

- [x] 13. Checkpoint — Verify invoice, payment, and catalogue modules
  - Ensure invoice creation/lifecycle/numbering, payment recording (cash + Stripe), credit notes, search/filter, catalogue CRUD, and GST calculations all work correctly. Ask the user if questions arise.


- [ ] 14. Storage & Document Management module
  - [x] 14.1 Implement storage quota calculation and enforcement
    - Calculate storage from compressed invoice JSON, customer records, and vehicle records per org (exclude logos/branding)
    - Display amber banner at 80%, red alert at 90% (with usage details + purchase button), block invoice creation at 100% (full-page interstitial)
    - Allow all other functionality (viewing, searching, payments) at 100%
    - _Requirements: 29.1, 29.2, 29.3, 29.4, 29.5_

  - [x] 14.2 Implement storage add-on purchasing
    - Create `POST /api/v1/billing/storage/purchase` — purchase in Global_Admin-configured increments, confirmation dialog with exact charge, immediate Stripe charge, instant quota increase, confirmation email
    - Add storage add-on as line item on next monthly invoice
    - _Requirements: 30.1, 30.2, 30.3, 30.4_

  - [x] 14.3 Implement bulk invoice export and archive
    - Create bulk export endpoint — filter by date range, export as ZIP of PDFs or single CSV
    - Bulk deletion with confirmation (number of invoices, space recovered); deleted invoices irrecoverable
    - _Requirements: 31.1, 31.2, 31.3_

  - [x] 14.4 Implement PDF generation (on-demand)
    - Store invoices as compressed JSON in PostgreSQL; generate PDFs on-the-fly with WeasyPrint from Jinja2 templates
    - Never write PDFs to permanent storage
    - Include on PDF: invoice number, dates, customer/vehicle details, line items with GST, totals, payment status, org branding, payment terms, T&C
    - Create `GET /api/v1/invoices/{id}/pdf` and `POST /api/v1/invoices/{id}/email` endpoints
    - _Requirements: 32.1, 32.2, 32.3, 32.4_

  - [x] 14.5 Write property test for storage quota enforcement
    - **Property 16: Storage Quota Enforcement at 100%** — verify invoice creation blocked at/above quota, other operations continue normally
    - **Validates: Requirements 29.4, 29.5**

- [ ] 15. Notifications module (Email & SMS)
  - [x] 15.1 Implement email sending infrastructure
    - Create `integrations/brevo.py` — Brevo/SendGrid/custom SMTP client
    - Create admin endpoint `PUT /api/v1/admin/integrations/smtp` — configure platform-wide email relay with API key, domain, from name, reply-to
    - Create "Test Email" button that sends real email to Global_Admin
    - Org emails use global infrastructure but display org sender name and reply-to
    - _Requirements: 33.1, 33.2, 33.3_

  - [x] 15.2 Implement email template customisation
    - Create `GET /PUT /api/v1/notifications/templates` — visual block editor content (JSONB body_blocks), template variables ({{customer_first_name}}, {{invoice_number}}, etc.), preview mode
    - Provide all 16 customisable email templates per org as defined in requirements
    - _Requirements: 34.1, 34.2, 34.3_

  - [x] 15.3 Implement email delivery tracking
    - Log every sent email: recipient, template, timestamp, delivery status (queued/sent/delivered/bounced/opened), subject
    - Create `GET /api/v1/notifications/log` — Org_Admin email log view
    - Flag bounced email addresses on customer record with warning visible to Salespeople
    - _Requirements: 35.1, 35.2, 35.3_

  - [x] 15.4 Implement SMS sending via Twilio
    - Create `integrations/twilio_sms.py` — Twilio client
    - Create admin endpoint for Twilio config (account SID, auth token, sender number) with "Test SMS" button
    - Per-org SMS enable/disable, sender name config, SMS template editor with variable system
    - Provide 4 SMS templates per org; warn if template exceeds 160 chars; log SMS with same detail as email
    - _Requirements: 36.1, 36.2, 36.3, 36.4, 36.5, 36.6_

  - [x] 15.5 Implement notification queuing and retry
    - Create `tasks/notifications.py` — Celery tasks for async email/SMS dispatch
    - Retry up to 3 times with exponential backoff; after 3 failures, mark as failed and log in Global Admin error log
    - _Requirements: 37.1, 37.2, 37.3_

  - [x] 15.6 Implement automated overdue payment reminders
    - Create overdue reminder rules CRUD — up to 3 rules per org (days after due, email/SMS/both)
    - Celery Beat triggers reminders; skip voided/paid invoices; disabled by default, automatic once enabled
    - _Requirements: 38.1, 38.2, 38.3, 38.4_

  - [x] 15.7 Implement WOF and registration expiry reminders
    - Enable/disable per org (disabled by default); configurable days in advance (default 30)
    - Send to customer linked to vehicle with rego, expiry type, date, workshop contact
    - Send via configured channel (email/SMS/both)
    - _Requirements: 39.1, 39.2, 39.3, 39.4_

  - [x] 15.8 Implement configurable notification preferences
    - Create `GET /PUT /api/v1/notifications/settings` — all notification types individually toggleable (disabled by default)
    - Group by category (Invoicing, Payments, Vehicle Reminders, System Alerts)
    - Independent channel config (email/SMS/both) per notification type
    - _Requirements: 83.1, 83.2, 83.3, 83.4_

  - [x] 15.9 Write property test for notification retry
    - **Property 19: Notification Retry Bounded at Three** — verify max 4 total attempts (1 initial + 3 retries), then permanently failed
    - **Validates: Requirements 37.2, 37.3**

- [ ] 16. Subscription & Billing module
  - [x] 16.1 Implement subscription plan management
    - Create `GET /POST /PUT /api/v1/admin/plans` — plan name, monthly price (NZD), user seats, storage quota, Carjam lookups, enabled modules
    - Public/private plans; edit/archive without affecting existing subscribers; configure storage tier pricing
    - _Requirements: 40.1, 40.2, 40.3, 40.4_

  - [x] 16.2 Implement free trial and signup
    - 14-day free trial on all public plans; collect card via Stripe SetupIntent (no charge until trial ends)
    - Trial countdown on Org_Admin dashboard; reminder email at 3 days remaining; auto-charge at trial end
    - _Requirements: 41.1, 41.2, 41.3, 41.4, 41.5_

  - [x] 16.3 Implement monthly billing lifecycle
    - Create `integrations/stripe_billing.py` — Stripe Subscriptions with metered billing for Carjam overages and storage add-ons
    - Bill monthly on signup anniversary; include base plan + storage add-ons + Carjam overage
    - Send Stripe invoice PDF by email; make past invoices viewable from Billing page
    - Payment failure retry: immediately, 3 days, 7 days with dunning emails
    - After final retry (14 days): 7-day grace period (view only, no create/pay); after grace: suspend (90-day data retention, warning emails at 30d and 7d)
    - _Requirements: 42.1, 42.2, 42.3, 42.4, 42.5, 42.6_

  - [x] 16.4 Implement plan upgrade and downgrade
    - Create `POST /api/v1/billing/upgrade` and `POST /api/v1/billing/downgrade`
    - Upgrade: immediate with prorated charges; Downgrade: applied at next billing period
    - Downgrade validation: warn if over new plan's storage or user limit
    - _Requirements: 43.1, 43.2, 43.3, 43.4_

  - [x] 16.5 Implement Org_Admin billing dashboard
    - Create `GET /api/v1/billing` — current plan, next billing date, estimated next invoice breakdown, storage usage bar, Carjam usage, past invoices, update payment method
    - Plain language, no accounting jargon
    - _Requirements: 44.1, 44.2_

  - [x] 16.6 Implement Carjam overage billing
    - When org exceeds plan's included Carjam lookups, auto-add overage charge to next monthly Stripe invoice
    - _Requirements: 16.3_

  - [x] 16.7 Write property tests for subscription module
    - **Property 17: Subscription Billing Lifecycle State Machine** — verify trial → active → grace_period → suspended → deleted transitions
    - **Property 18: Plan Downgrade Validation** — verify over-limit downgrades are rejected with specific messages
    - **Validates: Requirements 42.4, 42.5, 42.6, 43.4**

- [x] 17. Checkpoint — Verify storage, notifications, and subscription modules
  - Ensure storage quota enforcement, PDF generation, email/SMS sending, notification retry, overdue reminders, subscription billing lifecycle, and plan changes all work correctly. Ask the user if questions arise.


- [ ] 18. Quote & Job Card Management module
  - [x] 18.1 Implement quote CRUD
    - Create `GET /POST /PUT /api/v1/quotes` — same customer, vehicle, line item structure as invoices
    - Support statuses: Draft, Sent, Accepted, Declined, Expired
    - Configurable validity periods (7/14/30 days) with auto-expiry
    - Assign quote numbers with configurable prefix (e.g. "QT-") separate from invoice numbering
    - _Requirements: 58.1, 58.2, 58.4, 58.6_

  - [x] 18.2 Implement quote sending and conversion
    - Create `POST /api/v1/quotes/{id}/send` — email branded PDF quote to customer
    - Create `POST /api/v1/quotes/{id}/convert` — one-click conversion to Draft invoice pre-filled with all quote details
    - _Requirements: 58.3, 58.5_

  - [x] 18.3 Implement job card CRUD
    - Create `GET /POST /PUT /api/v1/job-cards` — linked to customer and vehicle, list work to be performed
    - Support statuses: Open, In Progress, Completed, Invoiced
    - Display active job cards on Salesperson dashboard as work queue
    - _Requirements: 59.1, 59.2, 59.5_

  - [x] 18.4 Implement job card conversion to invoice
    - Create `POST /api/v1/job-cards/{id}/convert` — one-click conversion to Draft invoice pre-filled with job card line items
    - Support combining multiple job cards into a single invoice
    - _Requirements: 59.3, 59.4_

  - [x] 18.5 Write unit tests for quote and job card modules
    - Test quote auto-expiry logic
    - Test quote-to-invoice conversion preserves all details
    - Test job card status transitions
    - _Requirements: 58.2, 58.4, 58.5, 59.2, 59.3_

- [ ] 19. Booking & Time Tracking module
  - [x] 19.1 Implement booking/appointment CRUD
    - Create `GET /POST /PUT /DELETE /api/v1/bookings` — calendar view data (day/week/month), linked to customer + optional vehicle, date/time/duration/service type
    - Optional confirmation email/SMS on creation; configurable appointment reminders
    - _Requirements: 64.1, 64.2, 64.3, 64.4_

  - [x] 19.2 Implement booking conversion
    - Create `POST /api/v1/bookings/{id}/convert` — one-click creation of Job Card or Draft invoice pre-filled with appointment details
    - _Requirements: 64.5_

  - [x] 19.3 Implement employee time tracking
    - Create `POST /api/v1/job-cards/{id}/timer/start` and `POST /api/v1/job-cards/{id}/timer/stop`
    - Calculate total time, allow adding as Labour line item with configured hourly rate
    - Provide Org_Admin report: total hours per employee in date range
    - _Requirements: 65.1, 65.2, 65.3_

  - [x] 19.4 Write unit tests for booking and time tracking
    - Test calendar data generation for day/week/month views
    - Test time calculation and Labour line item creation
    - _Requirements: 64.1, 65.2_

- [ ] 20. Inventory & Supplier Management module
  - [x] 20.1 Implement inventory stock tracking
    - Create `GET /PUT /api/v1/inventory/stock` — track stock quantities with current level, min threshold, reorder quantity
    - Auto-decrement stock when part added to invoice
    - Reorder alert on dashboard when below threshold; optional email notification
    - Stock report: current levels, parts below threshold, movement history
    - Manual stock adjustment with reason in audit log
    - _Requirements: 62.1, 62.2, 62.3, 62.4, 62.5_

  - [x] 20.2 Implement supplier management
    - Create `GET /POST /api/v1/inventory/suppliers` — supplier name, contact, email, phone, address, account number
    - Link parts to suppliers with supplier-specific part numbers and costs
    - Create `POST /api/v1/inventory/purchase-orders` — generate purchase order PDF for supplier
    - _Requirements: 63.1, 63.2, 63.3_

  - [x] 20.3 Write property test for inventory stock consistency
    - **Property 23: Inventory Stock Consistency** — verify stock_after = stock_before − quantity, and reorder alert generated when below threshold
    - **Validates: Requirements 62.2, 62.3**

- [x] 21. Checkpoint — Verify quotes, job cards, bookings, time tracking, and inventory
  - Ensure quote lifecycle, job card workflow, booking calendar, time tracking, inventory stock tracking, and supplier management all work correctly. Ask the user if questions arise.


- [ ] 22. Reporting & Analytics module
  - [x] 22.1 Implement org-level reports
    - Create `GET /api/v1/reports/revenue` — revenue summary
    - Create `GET /api/v1/reports/invoices/status` — invoice status report
    - Create `GET /api/v1/reports/outstanding` — outstanding invoices with one-click reminder button
    - Create `GET /api/v1/reports/top-services` — top services by revenue
    - Create `GET /api/v1/reports/gst-return` — GST return summary (total sales, GST collected, net GST, standard-rated vs zero-rated, formatted for IRD filing)
    - Create `GET /api/v1/reports/customer-statement/{id}` — printable/emailable PDF statement for a customer
    - Create `GET /api/v1/reports/carjam-usage` and `GET /api/v1/reports/storage` — usage reports
    - Create `GET /api/v1/reports/fleet/{id}` — fleet account report (total spend, vehicles serviced, outstanding balance)
    - All reports filterable by date range (day/week/month/quarter/year/custom), exportable as PDF or CSV
    - _Requirements: 45.1, 45.2, 45.3, 45.4, 45.5, 45.6, 45.7, 66.4_

  - [x] 22.2 Implement global admin reports
    - Create `GET /api/v1/admin/reports/mrr` — platform MRR with plan breakdown and month-over-month trend
    - Create `GET /api/v1/admin/reports/organisations` — table of all orgs (plan, signup date, trial status, billing status, storage, Carjam usage, last login)
    - Create `GET /api/v1/admin/reports/carjam-cost` — Carjam cost vs revenue
    - Create `GET /api/v1/admin/reports/churn` — churn report (cancelled/suspended orgs with plan type and duration)
    - Global Vehicle Database stats: total records, cache hit rate, total lookups
    - _Requirements: 46.1, 46.2, 46.3, 46.4, 46.5_

  - [x] 22.3 Write unit tests for reporting module
    - Test GST return calculation with mixed taxable/exempt items
    - Test customer statement generation
    - Test MRR calculation
    - _Requirements: 45.6, 45.7, 46.2_

- [ ] 23. Global Admin Console & Error Logging module
  - [x] 23.1 Implement organisation management in admin console
    - Create `GET /POST /PUT /DELETE /api/v1/admin/organisations` — sortable/searchable table, provision, suspend, reinstate, delete (multi-step confirmation), move between plans
    - Require reason for suspend/delete (audit log), optional email to Org_Admin
    - _Requirements: 47.1, 47.2, 47.3_

  - [x] 23.2 Implement integration configuration
    - Create `GET /PUT /api/v1/admin/integrations/{name}` — separate config pages for Carjam, Global Stripe, SMTP/Email, Twilio
    - Create `POST /api/v1/admin/integrations/{name}/test` — connection test button per integration
    - Carjam config: API key, endpoint URL, per-lookup cost, global rate limit
    - Global Stripe config: platform account, webhook endpoint, signing secret
    - All credentials encrypted (envelope encryption), never logged, never returned in API responses
    - _Requirements: 48.1, 48.2, 48.3, 48.4, 48.5_

  - [x] 23.3 Implement comprehensive error logging
    - Capture every exception, integration failure, background job failure across the platform
    - Store: unique ID, timestamp, severity (Info/Warning/Error/Critical), module, function, stack trace, org_id, user_id, HTTP details (sanitised), plain English message, auto-categorisation
    - Categories: Payment, Integration, Storage, Authentication, Data, Background Job, Application
    - Dashboard: real-time counts (1h/24h/7d by severity/category), live feed colour-coded, search/filter
    - Critical error → push notification to logged-in Global_Admins + email alert
    - Error detail view: formatted stack trace, context, request/response, status (Open/Investigating/Resolved) with notes
    - Retain 12 months, auto-archive, export CSV/JSON
    - _Requirements: 49.1, 49.2, 49.3, 49.4, 49.5, 49.6, 49.7_

  - [x] 23.4 Implement platform settings
    - Create `GET /PUT /api/v1/admin/settings` — subscription plans, storage pricing, Global Vehicle DB management (view, search, force-refresh, delete stale), platform T&C with version history, announcement banner
    - Prompt users to re-accept T&C on update; announcement banner visible to all org users
    - _Requirements: 50.1, 50.2, 50.3_

  - [x] 23.5 Implement audit log viewing
    - Create endpoints for Org_Admins to view their org's audit log and Global_Admins to view platform-wide logs
    - Each entry: who, what, before/after values, timestamp, IP, device
    - _Requirements: 51.1, 51.2, 51.4_

  - [x] 23.6 Write property test for audit log immutability
    - **Property 6: Audit Log Append-Only Immutability** — verify UPDATE/DELETE on audit_log are rejected by the application database role
    - **Validates: Requirements 51.1, 51.3**

- [ ] 24. Customer Portal module
  - [x] 24.1 Implement customer portal API
    - Create `GET /api/v1/portal/{token}` — secure access via unique link (no account creation)
    - Create `GET /api/v1/portal/{token}/invoices` — customer's invoice history, outstanding balances, payment history
    - Create `GET /api/v1/portal/{token}/vehicles` — vehicle service history with dates and services
    - Create `POST /api/v1/portal/{token}/pay/{invoice_id}` — pay outstanding invoice via Stripe
    - Reflect organisation branding (logo, colours)
    - _Requirements: 61.1, 61.2, 61.3, 61.4, 61.5_

  - [x] 24.2 Write unit tests for customer portal
    - Test secure token access and expiry
    - Test portal payment flow
    - _Requirements: 61.1, 61.3_

- [ ] 25. Data Import/Export & Webhooks module
  - [x] 25.1 Implement data import
    - Create `POST /api/v1/data/import/customers` and `POST /api/v1/data/import/vehicles` — CSV import with field mapping
    - Validate data, display preview with errors before committing
    - Skip invalid rows, continue processing, provide downloadable error report
    - _Requirements: 69.1, 69.2, 69.3, 69.5_

  - [x] 25.2 Implement data export
    - Create `GET /api/v1/data/export/customers`, `GET /api/v1/data/export/vehicles`, `GET /api/v1/data/export/invoices` — CSV export
    - _Requirements: 69.4_

  - [x] 25.3 Implement outbound webhooks
    - Create `GET /POST /PUT /DELETE /api/v1/webhooks` — configure webhook URLs for events: invoice created/paid/overdue, payment received, customer created, vehicle added
    - Send HTTP POST with JSON payload (event type, timestamp, data), signed with shared secret
    - Retry up to 3 times with exponential backoff on failure; log failures
    - _Requirements: 70.1, 70.2, 70.3, 70.4_

  - [x] 25.4 Implement accounting software integration (Xero & MYOB)
    - Create `integrations/xero.py` and `integrations/myob.py` — OAuth connection from org settings
    - Auto-sync invoices, payments, and credit notes to connected accounting software
    - Log sync failures, display warning to Org_Admin, allow manual retry
    - _Requirements: 68.1, 68.2, 68.3, 68.4, 68.5, 68.6_

  - [x] 25.5 Write unit tests for import/export and webhooks
    - Test CSV import validation and error report generation
    - Test webhook payload signing
    - Test Xero/MYOB sync payload construction
    - _Requirements: 69.3, 69.5, 70.3, 68.3_

- [x] 26. Checkpoint — Verify reporting, admin console, portal, import/export, and webhooks
  - Ensure all reports generate correctly, admin console functions work, customer portal is accessible, data import/export handles edge cases, webhooks deliver, and accounting sync works. Ask the user if questions arise.


- [ ] 27. Frontend — Core Layout, Auth & Dashboard pages
  - [x] 27.1 Implement reusable UI component library
    - Create `components/ui/` — Button, Input, Select, Modal, Toast, AlertBanner, Badge, Spinner, Tabs, Dropdown, DataTable, Pagination
    - All components use Tailwind CSS, support keyboard navigation, include ARIA labels/roles
    - Maintain 4.5:1 contrast ratio for normal text, 3:1 for large text (WCAG 2.1 AA)
    - Never rely solely on colour to convey information
    - _Requirements: 55.5, 56.2, 57.1, 57.2, 57.3, 57.4_

  - [x] 27.2 Implement layouts
    - Create `layouts/OrgLayout.tsx` — org-facing layout with sidebar, header, org branding (logo, colours)
    - Create `layouts/AdminLayout.tsx` — global admin layout with separate navigation
    - Create `layouts/PortalLayout.tsx` — customer portal layout (branded, minimal)
    - Responsive: two-column on desktop, single-column on mobile with large touch targets
    - _Requirements: 55.1, 55.2, 55.3, 55.4_

  - [x] 27.3 Implement auth context and pages
    - Create `contexts/AuthContext.tsx` — JWT state, user role, org context
    - Create `pages/auth/` — Login page (email/password, Google OAuth, Passkey), MFA verification page, Password reset request/complete pages, Passkey setup page
    - _Requirements: 1.1, 1.3, 1.4, 2.1, 4.1_

  - [x] 27.4 Implement tenant context and branding
    - Create `contexts/TenantContext.tsx` — org branding, settings loaded on login
    - Apply org primary/secondary colours, logo throughout the org layout
    - _Requirements: 9.1, 9.2_

  - [x] 27.5 Implement role-specific dashboards
    - Create `pages/dashboard/` — Salesperson dashboard (today's appointments, active job cards, recent invoices, overdue invoices, quick-action new invoice button)
    - Org_Admin dashboard (revenue summary, outstanding total, overdue count, storage usage, activity feed, system alerts)
    - Global_Admin dashboard (platform MRR, active orgs, error count by severity, integration health, billing issues)
    - _Requirements: 73.1, 73.2, 73.3_

  - [x] 27.6 Implement global search bar
    - Create `components/search/GlobalSearchBar.tsx` — accessible from any screen (Ctrl/Cmd+K)
    - Search across customers, vehicles (by rego), invoices simultaneously
    - Results grouped by type, most relevant first, within 500ms
    - _Requirements: 72.1, 72.2, 72.3_

  - [x] 27.7 Implement keyboard shortcuts
    - Create `hooks/useKeyboardShortcuts.ts` — Ctrl/Cmd+N (new invoice), Ctrl/Cmd+K (search), Ctrl/Cmd+S (save draft), module navigation
    - Keyboard shortcut reference via Ctrl/Cmd+/; no conflicts with browser shortcuts
    - _Requirements: 74.1, 74.2, 74.3_

  - [x] 27.8 Write unit tests for UI components
    - Test keyboard navigation on interactive elements
    - Test ARIA labels and roles
    - Test responsive layout breakpoints
    - _Requirements: 57.1, 57.2, 55.1_

- [ ] 28. Frontend — Onboarding & Organisation Settings pages
  - [x] 28.1 Implement onboarding wizard
    - Create `pages/onboarding/` — step-by-step wizard: org name/contact, logo upload, brand colours, GST number, GST %, invoice prefix/start number, payment terms, first service type
    - Visible progress indicator, one screen per step, any step skippable
    - _Requirements: 8.2, 8.3, 8.4, 8.5_

  - [x] 28.2 Implement organisation settings pages
    - Create `pages/settings/` — branding settings, GST settings, invoice settings, payment terms, T&C editor (rich text with headings, bold, bullets, links)
    - Branch management page, user management page (invite, role assignment, deactivate, MFA policy)
    - _Requirements: 9.1-9.8, 10.1-10.5_

  - [x] 28.3 Implement billing settings page
    - Create `pages/settings/Billing.tsx` — current plan, next billing date, estimated next invoice, storage usage bar, Carjam usage, past invoices, update payment method, upgrade/downgrade buttons, storage add-on purchase
    - Trial countdown display; plain language
    - _Requirements: 44.1, 44.2, 41.3_

- [ ] 29. Frontend — Invoice, Quote, Job Card pages
  - [x] 29.1 Implement invoice creation page
    - Create `pages/invoices/InvoiceCreate.tsx` — single-screen form: customer search/create inline, vehicle rego lookup (auto-populate), line item editor (service/part/labour), totals auto-calculated
    - Two-column on desktop, single-column with large touch targets on mobile
    - Save as Draft or Issue buttons; inline validation with specific error messages
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 56.5_

  - [x] 29.2 Implement invoice list and search page
    - Create `pages/invoices/InvoiceList.tsx` — search by number/rego/customer/date, instant results, stackable filters, scannable list (number, customer, rego, total, status, date)
    - Batch actions: mark as paid, send reminders, export PDF ZIP, export CSV
    - _Requirements: 21.1-21.4, 78.1_

  - [x] 29.3 Implement invoice detail page
    - Create `pages/invoices/InvoiceDetail.tsx` — full invoice view with status badge, payment history, credit notes, duplicate button, void button, email button, print button, PDF download
    - Print-optimised CSS (clean branded layout without nav/sidebar)
    - _Requirements: 22.1, 26.1, 75.1, 75.2, 75.3_

  - [x] 29.4 Implement quote pages
    - Create `pages/quotes/` — quote list, create (same structure as invoice), detail, send, convert to invoice
    - _Requirements: 58.1-58.6_

  - [x] 29.5 Implement job card pages
    - Create `pages/job-cards/` — job card list, create, detail with status transitions, convert to invoice, timer start/stop
    - _Requirements: 59.1-59.5, 65.1, 65.2_

  - [x] 29.6 Implement recurring invoice management page
    - Create recurring schedule list, create/edit form, pause/cancel controls
    - _Requirements: 60.1-60.4_

- [ ] 30. Frontend — Customer, Vehicle, Catalogue pages
  - [x] 30.1 Implement customer pages
    - Create `pages/customers/` — customer list with search, customer profile (linked vehicles, invoice history, total spend, outstanding balance), send email/SMS from profile, merge UI with confirmation preview
    - Fleet account management, discount rule management
    - _Requirements: 11.1-11.6, 12.1-12.4, 66.1-66.3, 67.1-67.3_

  - [x] 30.2 Implement vehicle pages
    - Create `pages/vehicles/` — vehicle list, vehicle profile (Carjam data, linked customers, odometer history, service history, WOF/rego expiry indicators with green/amber/red)
    - Refresh button, manual entry form
    - _Requirements: 14.1-14.7, 15.1-15.4_

  - [x] 30.3 Implement catalogue pages
    - Create `pages/catalogue/` — service catalogue list/create/edit, parts catalogue list/create/edit, labour rates list/create/edit
    - _Requirements: 27.1-27.3, 28.1-28.3_

  - [x] 30.4 Implement inventory pages
    - Create `pages/inventory/` — stock levels dashboard, reorder alerts, stock adjustment form, supplier list/create, purchase order generation
    - _Requirements: 62.1-62.5, 63.1-63.3_

  - [x] 30.5 Implement booking calendar page
    - Create `pages/bookings/` — calendar view (day/week/month), appointment create/edit, convert to job card or invoice
    - _Requirements: 64.1-64.5_


- [ ] 31. Frontend — Settings, Billing, Notifications pages
  - [x] 31.1 Implement notification settings pages
    - Create `pages/notifications/` — notification preferences (individually toggleable, grouped by category), template editor (visual block editor with drag-and-drop, template variables, preview), email/SMS log viewer
    - Overdue reminder rules configuration (up to 3 rules), WOF/rego reminder settings
    - _Requirements: 34.1-34.3, 35.1-35.3, 36.3-36.6, 38.1-38.4, 39.1-39.4, 83.1-83.4_

  - [x] 31.2 Implement report pages
    - Create `pages/reports/` — revenue summary, invoice status, outstanding invoices (with one-click reminder), top services, GST return summary, customer statement, Carjam usage, storage usage, fleet report
    - Charts: simple, readable, mobile-friendly; date range filters; PDF/CSV export buttons
    - _Requirements: 45.1-45.7, 66.4_

  - [x] 31.3 Implement Privacy Act compliance UI
    - Customer profile: "Process deletion request" button (anonymise), "Export customer data" button (JSON)
    - Confirmation dialogs explaining what will happen
    - _Requirements: 13.1-13.4_

  - [x] 31.4 Implement data import/export pages
    - Create import pages: CSV upload, field mapping UI, validation preview, error report download
    - Create export pages: customer/vehicle/invoice CSV export buttons
    - Batch import progress indicator and results summary
    - _Requirements: 69.1-69.5, 78.2, 78.3_

  - [x] 31.5 Implement accounting integration settings
    - Create Xero and MYOB connection pages — OAuth connect button, sync status, manual retry for failed syncs
    - _Requirements: 68.1-68.6_

  - [x] 31.6 Implement webhook configuration page
    - Create webhook list, create/edit form (event type, URL), delivery log viewer
    - _Requirements: 70.1-70.4_

- [ ] 32. Frontend — Admin Console pages
  - [x] 32.1 Implement admin organisation management page
    - Create `pages/admin/Organisations.tsx` — sortable/searchable table, provision/suspend/reinstate/delete orgs, move between plans
    - Reason required for suspend/delete
    - _Requirements: 47.1-47.3_

  - [x] 32.2 Implement admin integration configuration pages
    - Create `pages/admin/Integrations.tsx` — Carjam, Stripe, SMTP, Twilio config pages with test buttons
    - _Requirements: 48.1-48.5_

  - [x] 32.3 Implement admin error log dashboard
    - Create `pages/admin/ErrorLog.tsx` — real-time error counts (1h/24h/7d), live feed colour-coded by severity, search/filter, error detail view with stack trace, status management (Open/Investigating/Resolved), notes
    - Critical error push notifications
    - _Requirements: 49.1-49.7_

  - [x] 32.4 Implement admin platform settings page
    - Create `pages/admin/Settings.tsx` — plan management, storage pricing, Global Vehicle DB management, platform T&C editor with version history, announcement banner
    - _Requirements: 50.1-50.3_

  - [x] 32.5 Implement admin reports pages
    - Create `pages/admin/Reports.tsx` — MRR, organisation overview, Carjam cost vs revenue, vehicle DB stats, churn report
    - _Requirements: 46.1-46.5_

  - [x] 32.6 Implement admin audit log viewer
    - Create `pages/admin/AuditLog.tsx` — platform-wide audit log with search/filter
    - _Requirements: 51.4_

- [ ] 33. Frontend — Customer Portal & PWA/Offline
  - [x] 33.1 Implement customer portal pages
    - Create `pages/portal/` — secure access via token link, invoice history, outstanding balances, payment history, vehicle service history, Stripe payment flow
    - Org branding (logo, colours), minimal layout
    - _Requirements: 61.1-61.5_

  - [x] 33.2 Implement PWA support
    - Create `manifest.json` — valid PWA manifest for mobile/desktop installation
    - Create `service-worker.ts` — cache critical assets for fast repeat loading
    - "Install App" prompt on supported devices
    - _Requirements: 76.1, 76.2, 76.3_

  - [x] 33.3 Implement offline capability
    - Create `contexts/OfflineContext.tsx` and `hooks/useOffline.ts` — offline detection, local cache (IndexedDB)
    - Offline: view previously loaded invoices/customers/vehicles, start creating new invoice saved locally
    - Online restore: auto-sync locally saved data, notify user; conflict resolution (present both versions, user chooses)
    - _Requirements: 77.1, 77.2, 77.3, 77.4_

  - [x] 33.4 Implement print-friendly views
    - Add print-optimised CSS for invoice detail, customer statements, all reports
    - "Print" button triggers browser print dialog; clean branded layout without nav/sidebar
    - _Requirements: 75.1, 75.2, 75.3_

  - [x] 33.5 Write unit tests for offline sync
    - Test local cache read/write
    - Test sync conflict detection and resolution
    - _Requirements: 77.3, 77.4_

- [ ] 34. Checkpoint — Verify all frontend pages
  - Ensure all frontend pages render correctly, responsive layouts work on desktop/tablet/mobile, keyboard navigation works, ARIA labels are present, and offline capability functions. Ask the user if questions arise.


- [ ] 35. Background Jobs & Scheduled Tasks (Celery)
  - [x] 35.1 Implement Celery configuration and task queues
    - Configure Celery with Redis broker and 5 queues: notifications, pdf_generation, reports, integrations, scheduled_jobs
    - Configure Celery Beat for periodic tasks
    - _Requirements: 82.3_

  - [x] 35.2 Implement scheduled jobs
    - Create `tasks/scheduled.py`:
      - Every minute: check for overdue invoices (update status to Overdue at midnight on due date)
      - Every 5 minutes: process overdue reminder queue
      - Daily at 2am NZST: WOF/registration expiry reminder check
      - Every minute: retry failed notifications (exponential backoff)
      - Daily at 3am NZST: archive error logs older than 12 months
    - _Requirements: 19.6, 38.2, 39.3, 37.2, 49.7_

  - [x] 35.3 Implement recurring invoice generation task
    - Celery Beat checks recurring schedules and generates Draft or Issued invoices when due
    - Notify Org_Admin on generation
    - _Requirements: 60.2, 60.4_

  - [x] 35.4 Implement report generation tasks
    - Create `tasks/reports.py` — async report generation for large datasets
    - _Requirements: 82.3_

  - [x] 35.5 Implement accounting sync tasks
    - Create `tasks/integrations.py` — Xero/MYOB sync for invoices, payments, credit notes
    - _Requirements: 68.3, 68.4, 68.5_

- [ ] 36. Tenant Data Isolation — Property Tests & Hardening
  - [x] 36.1 Write property test for tenant data isolation
    - **Property 1: Tenant Data Isolation** — for any two orgs A and B, API requests as org A never return records with org_id = B, regardless of query params, filters, or path manipulation
    - **Validates: Requirements 5.6, 54.1, 54.2, 54.3, 54.4**

  - [x] 36.2 Write property test for API rate limiting
    - **Property 20: API Rate Limit Enforcement** — verify over-limit requests get HTTP 429 with Retry-After header; auth endpoints enforce stricter limit (10/min per IP)
    - **Validates: Requirements 71.1, 71.2, 71.3, 71.4**

- [ ] 37. Integration tests
  - [x] 37.1 Write Stripe integration tests
    - Test Stripe Connect OAuth flow
    - Test payment link generation and webhook processing
    - Test refund processing
    - Test subscription billing with metered usage
    - _Requirements: 25.1-25.5, 42.1-42.6_

  - [x] 37.2 Write Carjam integration tests
    - Test cache-first lookup flow
    - Test Carjam API failure fallback to manual entry
    - Test rate limiting enforcement
    - _Requirements: 14.1-14.7, 16.2_

  - [x] 37.3 Write Xero/MYOB integration tests
    - Test OAuth connection flow
    - Test invoice/payment/credit note sync
    - Test sync failure handling and retry
    - _Requirements: 68.1-68.6_

  - [x] 37.4 Write notification delivery integration tests
    - Test email sending via Brevo/SendGrid
    - Test SMS sending via Twilio
    - Test delivery status tracking and bounce handling
    - _Requirements: 33.1-33.3, 36.1-36.6, 37.1-37.3_

- [ ] 38. Accessibility, performance & security hardening
  - [x] 38.1 Implement data encryption at rest
    - Configure PostgreSQL AES-256 encryption at rest
    - Enforce TLS 1.3 for all data in transit
    - Verify all security headers (CSP, X-Frame-Options, X-Content-Type-Options, HSTS) on all responses
    - _Requirements: 52.1, 52.2, 52.3_

  - [x] 38.2 Implement data residency and backup configuration
    - Document NZ/AU data centre requirements for deployment
    - Configure 30-day backup retention with point-in-time recovery
    - Encrypted backups in geographically separate location
    - _Requirements: 53.1, 53.2, 53.3, 53.4_

  - [x] 38.3 Implement performance optimisations
    - Configure Redis caching for vehicle lookups, service catalogues, session data
    - Configure database connection pooling
    - Verify page render within 2 seconds, API response within 200ms for standard CRUD
    - Verify support for 500 concurrent users
    - _Requirements: 81.1, 81.2, 81.3, 81.4, 81.5_

  - [x] 38.4 Accessibility audit and fixes
    - Verify keyboard navigation on all interactive elements with visible focus indicators
    - Verify ARIA labels and roles on all UI components
    - Verify 4.5:1 contrast ratio for normal text, 3:1 for large text
    - Verify no information conveyed solely by colour
    - Verify browser zoom to 200% without content loss
    - _Requirements: 57.1, 57.2, 57.3, 57.4, 57.5_

  - [x] 38.5 Implement progressive disclosure and UX polish
    - Verify all screens use plain language with no technical jargon
    - Verify immediate visual feedback for all actions (loading states, success, error highlights)
    - Verify progressive disclosure (relevant options first, advanced on demand)
    - Verify inline form validation with specific error messages next to fields
    - _Requirements: 56.1, 56.2, 56.3, 56.4, 56.5_

  - [x] 38.6 Write security-focused tests
    - Test CSRF protection on all state-changing endpoints
    - Test that PII is never written to logs or error reports
    - Test that integration credentials are never returned in API responses
    - Test that RLS violations return 404 (not 403)
    - _Requirements: 52.4, 13.4, 48.5, 54.3_

- [ ] 39. Final checkpoint — Ensure all tests pass
  - Ensure all unit tests, property tests, and integration tests pass. Verify all 83 requirements are covered by implementation. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at logical boundaries
- Property tests validate the 23 universal correctness properties from the design document
- Unit tests validate specific examples, edge cases, and integration points
- The backend uses Python (FastAPI) and the frontend uses TypeScript (React + Tailwind CSS)
- All property-based tests use the Hypothesis library for Python






