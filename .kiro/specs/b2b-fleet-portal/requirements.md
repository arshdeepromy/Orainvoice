# Requirements Document

## ⚠️ Naming Note (added during execution of task 1.1)

The spec originally proposed creating a new table named `fleet_accounts`. During task 1.1 a name collision was discovered with an existing migration-0002 `fleet_accounts` table. **The new table created by this feature is named `portal_fleet_accounts`**. Glossary entries below that say `fleet_accounts` should be read as `portal_fleet_accounts`. The conceptual term `Fleet_Account` is unchanged.

## Introduction

The B2B Fleet Portal is a separate, password-based business customer portal that gates fleet management functionality behind a new `b2b-fleet-management` module. It is essentially a fleet management product (without GPS tracking, telemetry, or fuel-card integration) bolted onto the existing OraInvoice platform.

The portal lives at a distinct URL (e.g. `/fleet/login` or `fleet.<domain>`), separate from the default org user login page and from the existing token-link customer portal. Business customers (fleet operators) sign in with email + password, manage their fleet of vehicles, invite drivers, configure WOF/COF/service-due reminders, request bookings and quotations, view invoices, and run NZTA-compliant pre-trip checklists.

This builds on existing infrastructure:

- **Customers**: a Fleet Account Admin links to an existing `customers` row (`customer_type = 'business'`).
- **Vehicles**: fleet vehicles use the existing `global_vehicles` + `customer_vehicles` tables.
- **Bookings**: portal service requests create draft rows in the existing booking system.
- **Quotes**: portal quotation requests create draft rows in the existing quote system.
- **Invoices**: portal invoice viewing reuses the existing portal invoice service.
- **Notifications**: SMS and email reminders use the existing notification infrastructure (`email_providers`, Connexus SMS).
- **Portal sessions**: extends the existing `portal_sessions` table (4-hour inactivity, HttpOnly cookies, CSRF).
- **Module gating**: registered as a new `b2b-fleet-management` module in `module_registry`, depending on `vehicles`.
- **Password login foundation**: `docs/future/portal-password-login.md` (`portal_accounts` table, bcrypt, invite/lockout flows).

The feature is scoped to organisations in the `automotive-transport` trade family (workshops, garages, fleet servicing). Out of scope: GPS tracking, real-time telemetry, fuel cards, driver behaviour scoring, route optimisation, and any DOT/regulatory reporting beyond NZTA pre-trip checklists.

## Glossary

- **Fleet_Portal**: The customer-facing web application served at the dedicated fleet URL (`/fleet/...` path or `fleet.<domain>` subdomain), rendered as a standalone surface separate from `OrgLayout` and the existing token-link `PortalPage`.
- **Workshop_Org**: An organisation using OraInvoice (a workshop or garage) that has the `b2b-fleet-management` module enabled and offers the Fleet Portal to its business customers.
- **Workshop_Admin**: A user of a Workshop_Org with `role IN ('owner','admin')` who manages module enablement, fleet portal access for customers, bookings, quotes, and invoices.
- **Fleet_Account**: A row in `fleet_accounts` representing a business customer's portal tenant, linked one-to-one to an existing `customers` row with `customer_type = 'business'`.
- **Fleet_Account_Admin**: The primary Portal_User of a Fleet_Account (the business customer). Manages vehicles, drivers, reminders, bookings, quotations, and checklist templates for the Fleet_Account.
- **Driver_User**: A secondary Portal_User invited by the Fleet_Account_Admin. Has limited access to only the vehicles assigned to that Driver_User.
- **Portal_User**: A row in `portal_accounts` representing login credentials (email, bcrypt password hash, invite/lockout state). Distinguished by `portal_user_role IN ('fleet_admin','driver')` and `fleet_account_id`.
- **Fleet**: The set of `customer_vehicles` rows linked to the Fleet_Account's `customer_id` within a single `org_id`.
- **Driver_Assignment**: A row in `fleet_driver_assignments` linking a Driver_User to one or more `customer_vehicles` rows, controlling which vehicles the Driver_User can see.
- **Module_Gate**: The system that checks `ModuleService.is_enabled(org_id, "b2b-fleet-management")` (with `vehicles` as a dependency) before allowing any Fleet_Portal API endpoint to respond.
- **Trade_Family_Gate**: The check that the Workshop_Org's `tradeFamily` equals `automotive-transport` before exposing the module in the module registry UI or allowing it to be enabled.
- **Reminder_Preference**: A row in `fleet_reminder_preferences` storing per-vehicle WOF/COF/service-due reminder configuration (channels, lead times, recipients).
- **Service_Booking_Request**: A row in `fleet_service_booking_requests` representing a portal-originated booking; on acceptance by the Workshop_Admin, a draft row is created in the existing `bookings` table.
- **Quotation_Request**: A row in `fleet_quotation_requests` representing a portal-originated quote request; on acceptance, a draft row is created in the existing `quotes` table.
- **Checklist_Template**: A row in `fleet_checklist_templates` defining a reusable pre-trip checklist (NZTA default or custom), composed of ordered `fleet_checklist_template_items`.
- **Checklist_Item**: A single check entry within a Checklist_Template (e.g. "Tyre tread depth ≥ 1.5 mm"), with a category, label, optional description, and a flag indicating whether photo evidence is required on failure.
- **Checklist_Submission**: A row in `fleet_checklist_submissions` representing one completed run-through of a Checklist_Template by a Driver_User on a specific vehicle, with per-item pass/fail results in `fleet_checklist_submission_items`.
- **NZTA_Default_Template**: The system-seeded Checklist_Template that contains the New Zealand Transport Agency–compliant pre-trip safety items (tyres, lights, brakes, mirrors, fluids, body/load, signage, indicators, horn, wipers, seatbelts).
- **Fleet_Portal_Session**: A row in the existing `portal_sessions` table whose `portal_account_id` references a `portal_accounts` row with `portal_user_role IN ('fleet_admin','driver')`.

## Requirements

### Requirement 1: Module Registration and Gating

**User Story:** As a Workshop_Admin, I want the Fleet Portal feature to be controlled by a dedicated module that I can enable per organisation, so that only orgs that have purchased or opted into fleet management see and use it.

#### Acceptance Criteria

1. THE Module_Gate SHALL register the `b2b-fleet-management` module in the `module_registry` table with `display_name = 'B2B Fleet Management'`, `category = 'fleet_management'`, `is_core = false`, `dependencies = '["vehicles"]'`, `status = 'available'`, `setup_question = 'Do your business customers need a self-service portal to manage their vehicle fleet?'`, and `setup_question_description = 'Let fleet operators log in to view vehicles, invite drivers, run NZTA pre-trip checklists, book services, request quotes, and manage WOF/COF reminders.'`.
2. WHERE the Workshop_Org's `tradeFamily` is not `automotive-transport`, THE Module_Gate SHALL hide the `b2b-fleet-management` module from the module management UI and the Setup Guide.
3. IF a request is made to enable the `b2b-fleet-management` module for a Workshop_Org whose `tradeFamily` is not `automotive-transport`, THEN THE Module_Gate SHALL reject the request with HTTP 403 and message "B2B Fleet Management is available only for automotive and transport organisations".
4. WHEN the `b2b-fleet-management` module is enabled for a Workshop_Org, THE Module_Gate SHALL auto-enable the `vehicles` module dependency via the existing `DEPENDENCY_GRAPH` mechanism in `app/core/modules.py`.
5. IF a request is made to any Fleet_Portal API endpoint and the `b2b-fleet-management` module is not enabled for the resolved Workshop_Org, THEN THE Module_Gate SHALL return HTTP 403 with message "B2B Fleet Management module is not enabled for this organisation".
6. IF a browser requests the Fleet_Portal login URL (`/fleet/login` or `fleet.<domain>`) for a Workshop_Org that does not have the `b2b-fleet-management` module enabled, THEN THE Fleet_Portal SHALL return HTTP 404 and SHALL NOT reveal whether the org exists.
7. WHEN the `b2b-fleet-management` module is disabled for a Workshop_Org, THE Module_Gate SHALL invalidate all active Fleet_Portal_Sessions for that org by deleting the corresponding `portal_sessions` rows within 60 seconds.
8. WHILE the `b2b-fleet-management` module is disabled for a Workshop_Org, THE Org_Admin_Panel SHALL hide all Fleet Portal navigation items, customer-detail "Fleet Portal Access" sections, and fleet booking/quote queues for that org.
9. THE Module_Gate SHALL allow a Workshop_Admin to enable or disable the `b2b-fleet-management` module via the existing module management admin interface and the Setup Guide.

### Requirement 2: Separate Fleet Portal URL

**User Story:** As a Fleet_Account_Admin, I want to access the Fleet Portal at a dedicated URL that is clearly separate from the workshop's internal staff login, so that the portal feels like its own product and I do not see internal admin UI by accident.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL be served at a dedicated URL distinct from the Workshop_Org's internal login: either the path prefix `/fleet/...` (e.g. `/fleet/login`, `/fleet/dashboard`) or the subdomain `fleet.<domain>` (e.g. `fleet.example.com`), configurable per deployment via env variable `FLEET_PORTAL_HOST`.
2. THE Fleet_Portal SHALL NOT reuse the `OrgLayout` chrome — it SHALL render its own standalone layout (`FleetPortalLayout`) with its own sidebar, header, and theming.
3. THE Fleet_Portal SHALL resolve the Workshop_Org from the URL using one of: subdomain (`<org_slug>.fleet.<domain>`), path parameter (`/fleet/<org_slug>/login`), or a single-tenant configured `FLEET_PORTAL_DEFAULT_ORG_SLUG` env variable when only one org is hosted.
4. IF the Fleet_Portal URL resolves to no Workshop_Org (invalid slug or missing config), THEN THE Fleet_Portal SHALL return HTTP 404 and SHALL NOT redirect to or expose the internal `/login` page.
5. THE Fleet_Portal SHALL NOT accept staff JWTs or staff session cookies — only Fleet_Portal_Sessions backed by `portal_accounts` SHALL grant access.
6. IF a staff user navigates to a Fleet_Portal URL without a valid Fleet_Portal_Session, THEN THE Fleet_Portal SHALL redirect to the Fleet_Portal login page, regardless of any active staff JWT in storage.
7. THE Fleet_Portal frontend bundle SHALL be served from the same Vite build but routed via a top-level `<FleetPortalRouter>` mounted at the `/fleet` path or selected by hostname, separate from the existing org and admin routers.

### Requirement 3: Password-Based Authentication for Portal Users

**User Story:** As a Fleet_Account_Admin or Driver_User, I want to log in with my email and a password I set myself, so that I can return to the portal without depending on a one-time link.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL provide a login page at `/fleet/login` that accepts email and password.
2. WHEN a Portal_User submits valid credentials AND the corresponding Portal_User row has `is_active = true` AND (`locked_until IS NULL` OR `locked_until <= now()`), THE Fleet_Portal SHALL create a Fleet_Portal_Session in the existing `portal_sessions` table and set an HttpOnly, Secure, SameSite=Lax session cookie scoped to the Fleet_Portal host.
3. IF a Portal_User submits invalid credentials, THEN THE Fleet_Portal SHALL return HTTP 401 with the generic message "Invalid email or password" and SHALL increment `failed_login_attempts` on the Portal_User row by 1.
4. IF `failed_login_attempts` reaches 5 within a single `locked_until` window, THEN THE Fleet_Portal SHALL set `locked_until = now() + 30 minutes` and return HTTP 403 with the message "Account temporarily locked. Please try again later.".
5. WHILE `locked_until > now()` for a Portal_User, THE Fleet_Portal SHALL reject login attempts with HTTP 403 and SHALL NOT increment `failed_login_attempts` further.
6. WHEN a Portal_User logs in successfully, THE Fleet_Portal SHALL set `failed_login_attempts = 0`, set `locked_until = NULL`, and update `last_login_at = now()`.
7. THE Fleet_Portal SHALL hash all passwords with bcrypt at cost factor 12 using the existing `passlib` infrastructure and SHALL NOT store, log, or transmit plaintext passwords.
8. THE Fleet_Portal SHALL enforce a minimum password length of 8 characters and SHALL reject passwords that match the Portal_User's email local-part (case-insensitive).
9. THE Fleet_Portal SHALL provide a forgot-password endpoint at `POST /fleet/api/auth/forgot-password` that, for any submitted email, returns HTTP 200 with a generic confirmation message regardless of whether the email matches an existing Portal_User.
10. WHEN a forgot-password request is submitted for an existing Portal_User with `is_active = true`, THE Fleet_Portal SHALL generate a `reset_token = secrets.token_urlsafe(32)`, store it on the Portal_User row with `reset_token_expires_at = now() + 1 hour`, and send an email containing a link to `/fleet/reset-password/{reset_token}`.
11. WHEN a Portal_User submits a new password through a valid reset link, THE Fleet_Portal SHALL update `password_hash`, clear `reset_token` and `reset_token_expires_at`, set `failed_login_attempts = 0` and `locked_until = NULL`, and redirect to the login page.
12. IF a reset token is expired or already used, THEN THE Fleet_Portal SHALL display the message "This password reset link is no longer valid" and offer a "Request a new reset link" action.
13. THE Fleet_Portal SHALL provide a logout endpoint at `POST /fleet/api/auth/logout` that destroys the Fleet_Portal_Session and clears the session cookie.
14. THE Fleet_Portal SHALL rate-limit `POST /fleet/api/auth/login` to 10 requests per minute per source IP and `POST /fleet/api/auth/forgot-password` to 3 requests per minute per email.
15. THE Fleet_Portal SHALL apply CSRF protection (double-submit cookie pattern) to all state-changing endpoints under `/fleet/api/...`.

### Requirement 4: Fleet Portal Access Provisioning by Workshop Admin

**User Story:** As a Workshop_Admin, I want to invite a business customer to the Fleet Portal as the Fleet_Account_Admin from the customer detail page, so that they can set up a password and start managing their fleet.

#### Acceptance Criteria

1. WHERE the `b2b-fleet-management` module is enabled for the Workshop_Org AND the customer's `customer_type = 'business'`, THE Org_Admin_Panel SHALL display a "Fleet Portal Access" section on the customer detail/edit page.
2. WHEN a Workshop_Admin clicks "Invite to Fleet Portal" on a business customer, THE Org_Admin_Panel SHALL call `POST /api/v2/fleet-portal/admin/invite` which (a) creates or reuses a `fleet_accounts` row linked to the customer, (b) creates a Portal_User with `portal_user_role = 'fleet_admin'`, `invite_token = secrets.token_urlsafe(32)`, `invite_sent_at = now()`, and (c) sends an invitation email containing the link `/fleet/accept-invite/{invite_token}`.
3. IF a Workshop_Admin attempts to invite a customer with `customer_type != 'business'`, THEN THE Org_Admin_Panel SHALL return HTTP 400 with message "Fleet Portal is only available for business customers".
4. WHEN a Portal_User clicks an invite link, THE Fleet_Portal SHALL serve the password-creation page at `/fleet/accept-invite/{invite_token}` requiring the user to set a password meeting the rules in Requirement 3.8.
5. WHEN a Portal_User completes the invite acceptance, THE Fleet_Portal SHALL store the bcrypt `password_hash`, set `invite_accepted_at = now()`, clear `invite_token`, and redirect to `/fleet/login`.
6. IF an invite token is expired (older than 7 days based on `invite_sent_at`) OR has already been accepted, THEN THE Fleet_Portal SHALL display "This invitation has expired or has already been used" and SHALL offer a "Request a new invitation" action that notifies the Workshop_Org via the existing in-app notification system.
7. THE Org_Admin_Panel SHALL display the Portal_User status on the customer detail page as one of: "Not Invited", "Invited (pending)", "Active", "Locked", or "Revoked".
8. WHEN a Workshop_Admin clicks "Revoke portal access", THE Org_Admin_Panel SHALL set the Portal_User's `is_active = false` and within 60 seconds invalidate all Fleet_Portal_Sessions associated with that Portal_User.
9. WHEN a Workshop_Admin clicks "Resend invitation" for a pending invite, THE Org_Admin_Panel SHALL generate a fresh `invite_token`, update `invite_sent_at = now()`, and send a new invitation email.
10. WHILE a Portal_User has `is_active = false`, THE Fleet_Portal SHALL reject login attempts with HTTP 403 and message "Your portal access has been revoked. Please contact the workshop.".

### Requirement 5: Driver User Invitation by Fleet Account Admin

**User Story:** As a Fleet_Account_Admin, I want to invite my drivers as Driver_Users and assign them specific vehicles, so that each driver can log in and see only their own vehicles.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL provide a "Drivers" management page at `/fleet/drivers` accessible only to Portal_Users with `portal_user_role = 'fleet_admin'`.
2. WHEN a Fleet_Account_Admin invites a driver by submitting first name, last name, email, and optional phone number, THE Fleet_Portal SHALL create a Portal_User with `portal_user_role = 'driver'`, `fleet_account_id = current_fleet_account.id`, `org_id = current_org_id`, `invite_token`, and `invite_sent_at = now()`, and send an invitation email.
3. THE Fleet_Portal SHALL prevent creating a Driver_User with the same email as an existing active Portal_User in the same `org_id`; in that case it SHALL return HTTP 409 with message "A user with this email already has portal access".
4. WHEN a Driver_User completes invite acceptance, THE Fleet_Portal SHALL set `invite_accepted_at = now()` and redirect to `/fleet/login`.
5. THE Fleet_Portal SHALL allow the Fleet_Account_Admin to assign one or more `customer_vehicles` rows to a Driver_User by creating `fleet_driver_assignments` rows (`portal_account_id`, `customer_vehicle_id`, `assigned_at`, `assigned_by_portal_account_id`).
6. THE Fleet_Portal SHALL allow the Fleet_Account_Admin to remove a driver-vehicle assignment by deleting the corresponding `fleet_driver_assignments` row.
7. THE Fleet_Portal SHALL allow the Fleet_Account_Admin to deactivate a Driver_User (sets `is_active = false`) and within 60 seconds invalidate all Fleet_Portal_Sessions for that Driver_User.
8. WHEN a Driver_User logs in, THE Fleet_Portal SHALL list only the `customer_vehicles` rows present in `fleet_driver_assignments` for that Portal_User; vehicles without an assignment SHALL NOT be visible to the Driver_User.
9. THE Fleet_Portal SHALL display, on the Drivers page for the Fleet_Account_Admin, each Driver_User's name, email, status, last login, number of assigned vehicles, and most recent checklist submission timestamp.

### Requirement 6: Fleet Vehicle Management — Fleet Account Admin

**User Story:** As a Fleet_Account_Admin, I want to view, edit, and add vehicles in my fleet, so that I keep an accurate record of what my drivers operate.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL display a fleet dashboard at `/fleet/vehicles` listing all `customer_vehicles` rows linked to the Fleet_Account's `customer_id` and `org_id`, joined to `global_vehicles`.
2. FOR EACH vehicle, THE Fleet_Portal SHALL display: registration (`rego`), make, model, year, colour, current odometer (`odometer_last_recorded`), WOF expiry (`wof_expiry`), COF expiry (`cof_expiry`), assigned driver(s), and a compliance status badge.
3. WHEN a vehicle's WOF or COF is within 28 days of expiry, THE Fleet_Portal SHALL display an amber "Expiring soon" badge on that vehicle.
4. WHEN a vehicle's WOF or COF expiry date is before the current date, THE Fleet_Portal SHALL display a red "Expired" badge on that vehicle.
5. WHEN a Fleet_Account_Admin clicks "Add vehicle", THE Fleet_Portal SHALL open a form requiring `rego` and SHALL look up the vehicle in `global_vehicles` (CarJam pathway when available) before creating a `customer_vehicles` link to the Fleet_Account's customer.
6. THE Fleet_Portal SHALL allow the Fleet_Account_Admin to edit `customer_vehicles` editable fields (e.g. internal name, fleet number, notes) and the `global_vehicles` mutable fields permitted to customers (colour, odometer, WOF/COF expiry where the workshop allows customer entry).
7. THE Fleet_Portal SHALL allow the Fleet_Account_Admin to remove a vehicle from the fleet by soft-unlinking the `customer_vehicles` row (does not delete the underlying `global_vehicles` row).
8. THE Fleet_Portal SHALL display a fleet summary header showing: total vehicles, vehicles with valid WOF and COF, vehicles expiring within 28 days, vehicles overdue for service, and today's checklist completion count (completed / pending).
9. THE Fleet_Portal SHALL only display vehicles for the authenticated Fleet_Account, enforced both by query filters (`org_id`, `customer_id`) and by Postgres RLS policies on `customer_vehicles`.

### Requirement 7: Vehicle Access for Driver Users

**User Story:** As a Driver_User, I want to see the vehicles assigned to me and update limited vehicle information, so that I can keep my logs current without affecting the rest of the fleet.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL display only the vehicles linked via `fleet_driver_assignments` to the authenticated Driver_User on `/fleet/vehicles`.
2. THE Fleet_Portal SHALL allow a Driver_User to update only the following fields on an assigned vehicle: odometer reading (creates a new `odometer_readings` row), driving hours (creates a new `fleet_driver_hours` row), and `service_due_date` on the corresponding `global_vehicles` / `org_vehicles` row (the existing column — `customer_vehicles` is a link table with no service-due column of its own).
3. THE Fleet_Portal SHALL NOT allow a Driver_User to change `make`, `model`, `year`, `vin`, or `rego` on `global_vehicles`.
4. IF a Driver_User submits a request to change a restricted vehicle field, THEN THE Fleet_Portal SHALL return HTTP 403 with message "Drivers cannot change vehicle make, model, year, VIN, or registration".
5. THE Fleet_Portal SHALL allow a Driver_User to log driving hours by submitting `start_at` (ISO timestamp), `end_at` (ISO timestamp ≥ `start_at`), and optional `notes`, persisted to `fleet_driver_hours` with `portal_account_id`, `customer_vehicle_id`, `org_id`.
6. THE Fleet_Portal SHALL allow a Driver_User to log an odometer reading by submitting an integer kilometres value strictly greater than the most recent recorded value for the vehicle.
7. IF a Driver_User submits an odometer reading less than or equal to the most recent recorded value for the vehicle, THEN THE Fleet_Portal SHALL return HTTP 400 with message "Odometer reading must be greater than the most recent recorded value of {value} km".
8. THE Fleet_Portal SHALL display each assigned vehicle's WOF, COF, and next-service-due status to the Driver_User in the same way as the Fleet_Account_Admin view.

### Requirement 8: NZTA-Compliant Pre-Trip Checklist Templates

**User Story:** As a Fleet_Account_Admin, I want a default NZTA-compliant pre-trip checklist available out of the box and the ability to customise or create new templates, so that drivers complete the right safety checks for the vehicle type they operate.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL seed exactly one NZTA_Default_Template per Fleet_Account at first login of the Fleet_Account_Admin, with `name = 'NZTA Pre-Trip Inspection (Default)'`, `is_default = true`, `is_system_seeded = true`.
2. THE NZTA_Default_Template SHALL contain Checklist_Items grouped into categories Tyres, Lights, Brakes, Mirrors, Windows and Wipers, Fluids, Body and Load, Signage and Indicators, Horn, and Seatbelts, with at least the following items:
   - Tyres: tread depth ≥ 1.5 mm, no visible damage or bulges, correct inflation.
   - Lights: headlights low and high beam, brake lights, indicators front and rear, hazard lights, reversing light, number plate light.
   - Brakes: foot brake responsive, parking brake holds, no warning lights on dash.
   - Mirrors: side mirrors clean and adjusted, rear-view mirror clean and adjusted.
   - Windows and Wipers: windscreen free of cracks obstructing view, wipers and washers functional.
   - Fluids: engine oil level, coolant level, washer fluid level.
   - Body and Load: load secured, doors close and latch, no fluid leaks visible.
   - Signage and Indicators: registration label current, COF/WOF label visible (if applicable), reflective tape and hazard signage where required.
   - Horn: audible.
   - Seatbelts: all seatbelts present and functional.
3. THE Fleet_Portal SHALL allow the Fleet_Account_Admin to clone the NZTA_Default_Template into an editable Checklist_Template.
4. THE Fleet_Portal SHALL allow the Fleet_Account_Admin to create, edit, reorder, and remove Checklist_Items in any non-system Checklist_Template, including: `category`, `label` (≤ 200 chars), optional `description` (≤ 500 chars), `requires_photo_on_fail` (boolean), and `display_order`.
5. THE Fleet_Portal SHALL allow the Fleet_Account_Admin to create multiple Checklist_Templates per Fleet_Account (e.g. "Light Vehicle Daily", "Heavy Vehicle Daily") and to mark exactly zero or one as `is_default = true` per Fleet_Account.
6. THE Fleet_Portal SHALL allow the Fleet_Account_Admin to assign a specific Checklist_Template to a `customer_vehicles` row by setting `customer_vehicles.fleet_checklist_template_id`; if unset, the Fleet_Account's default template (where `is_default = true`) applies.
7. IF the Fleet_Account_Admin attempts to delete a Checklist_Template that is referenced by any non-archived Checklist_Submission, THEN THE Fleet_Portal SHALL prevent deletion and SHALL allow archiving instead (`archived_at = now()`).
8. THE NZTA_Default_Template SHALL NOT be editable, deletable, or archivable; it SHALL only be cloneable.

### Requirement 9: Pre-Trip Checklist Completion by Drivers

**User Story:** As a Driver_User, I want to complete the pre-trip checklist for my assigned vehicle at the start of my shift, including marking items pass or fail and uploading a photo for failed items, so that I record my safety check for compliance.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL allow a Driver_User to start a Checklist_Submission for any vehicle in `fleet_driver_assignments` for that Driver_User.
2. WHEN a Driver_User starts a Checklist_Submission, THE Fleet_Portal SHALL create a `fleet_checklist_submissions` row with `started_at = now()`, `portal_account_id`, `customer_vehicle_id`, `fleet_checklist_template_id`, `org_id`, `status = 'in_progress'`.
3. FOR EACH Checklist_Item in the resolved Checklist_Template, THE Fleet_Portal SHALL require the Driver_User to record one of `result IN ('pass','fail','na')` and an optional `notes` field (≤ 500 chars).
4. WHERE a Checklist_Item has `requires_photo_on_fail = true` AND the recorded `result = 'fail'`, THE Fleet_Portal SHALL require at least one uploaded photo evidence file (image MIME type, ≤ 8 MB) before submission can be completed.
5. IF a Driver_User attempts to complete a Checklist_Submission while any required photo evidence is missing, THEN THE Fleet_Portal SHALL return HTTP 400 with message "Photo evidence is required for failed item: {label}".
6. WHEN a Driver_User completes a Checklist_Submission, THE Fleet_Portal SHALL set `completed_at = now()`, set `status = 'completed'`, compute `failed_item_count` and `passed_item_count`, and lock the submission against further edits.
7. WHEN a Checklist_Submission is completed AND `failed_item_count > 0`, THE Fleet_Portal SHALL emit an in-app notification (`type = 'fleet_checklist_failure'`) to the Fleet_Account_Admin and to all Workshop_Admins of the Workshop_Org.
8. THE Fleet_Portal SHALL display, to a Driver_User, only that Driver_User's own Checklist_Submissions on `/fleet/checklists/history`.
9. THE Fleet_Portal SHALL display, to a Fleet_Account_Admin, all Checklist_Submissions for the Fleet_Account on `/fleet/checklists/history`, with filters by vehicle, driver, date range, and result (any failures vs all passes).
10. THE Fleet_Portal SHALL retain Checklist_Submissions and their items for at least 24 months from `completed_at` for compliance audit, and SHALL NOT permit hard deletion through the portal UI.
11. THE Fleet_Portal SHALL provide a kiosk-friendly checklist completion view at `/fleet/kiosk/checklist` optimised for tablet (large touch targets ≥ 56 px, full-screen layout, no sidebar) so depots can run the checklist on a shared device after the Driver_User authenticates. THIS IS A WEB KIOSK VIEW served at the Fleet_Portal URL — it is distinct from the existing mobile-app `kiosk` role (which is a native Capacitor-based vehicle check-in flow under the staff JWT auth path); the two MUST NOT share session state, and a Workshop_Org operating both will use them for different purposes.
12. THE Fleet_Portal SHALL, when used on a viewport ≤ 480 px wide, render the checklist with single-column layout, sticky pass/fail buttons, and tap-to-capture photo controls suitable for phones.

### Requirement 10: Reminder Configuration for WOF, COF, and Service Due

**User Story:** As a Fleet_Account_Admin, I want to enable WOF, COF, and service-due reminders per vehicle with configurable lead times and channels, so that I and my drivers receive timely notifications before each compliance deadline.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL provide a reminder preferences page at `/fleet/reminders` listing all fleet vehicles with toggles for WOF, COF, and service-due reminders.
2. FOR EACH reminder type per vehicle, THE Fleet_Portal SHALL allow the Fleet_Account_Admin to configure: `enabled` (boolean), `lead_time_days` (one of 7, 14, 30), `channels` (any subset of `['email','sms']`, at least one required when enabled), `recipients` (any subset of `['fleet_admin','assigned_drivers']`, at least one required when enabled). THE supported reminder types are `'wof_expiry_reminder'`, `'cof_expiry_reminder'`, `'service_due_reminder'`, and (optionally per fleet) `'registration_expiry_reminder'` — matching the existing reminder type names registered in `app/modules/notifications/schemas.py`.
3. THE Fleet_Portal SHALL persist these preferences in `fleet_reminder_preferences` with columns `id`, `fleet_account_id`, `customer_vehicle_id`, `org_id`, `reminder_type VARCHAR(40)` (one of the names listed in 10.2), `enabled`, `lead_time_days`, `channels` (jsonb array), `recipients` (jsonb array), `service_interval_km`, `service_interval_months`, `created_at`, `updated_at`.
4. WHEN a WOF reminder is enabled for a vehicle with `lead_time_days = N`, THE existing reminder Celery Beat task SHALL send a reminder via each enabled channel to each enabled recipient on the day `wof_expiry - N days = today`, exactly once per `(customer_vehicle_id, reminder_type, expiry_date)` combination.
5. WHEN a COF reminder is enabled for a vehicle with `lead_time_days = N`, THE reminder task SHALL send a reminder via each enabled channel to each enabled recipient on the day `cof_expiry - N days = today`, exactly once per `(customer_vehicle_id, reminder_type, expiry_date)` combination.
6. WHEN a service-due reminder is enabled for a vehicle, THE reminder task SHALL send a reminder when the vehicle's `service_due_date` (column on `global_vehicles` / `org_vehicles`) minus `lead_time_days` reaches today. WHERE `service_interval_km` and/or `service_interval_months` are configured per vehicle in `fleet_reminder_preferences`, the Workshop_Admin or Fleet_Account_Admin MAY recompute the `service_due_date` from the latest odometer reading and last service date via a service helper.
7. THE Fleet_Portal SHALL allow the Fleet_Account_Admin to send an ad-hoc SMS reminder for a vehicle to assigned drivers via the existing Connexus SMS infrastructure, provided the Workshop_Org has SMS credit and a configured sender.
8. IF the Workshop_Org has no SMS provider configured, THEN THE Fleet_Portal SHALL disable the SMS channel option in the UI and reject SMS reminder submissions with HTTP 400 and message "SMS is not configured for this workshop".
9. THE Fleet_Portal SHALL default all reminders to disabled when a vehicle is first added to the Fleet_Account.
10. IF a reminder send fails (SMTP error, SMS gateway error), THEN THE reminder task SHALL retry up to 3 times with exponential backoff (1 s, 2 s, 4 s) and SHALL record final failures in the existing notification audit log without re-sending the same reminder window.

### Requirement 11: Service Booking Requests

**User Story:** As a Fleet_Account_Admin or Driver_User, I want to request a service booking for a vehicle from the portal, so that the workshop can schedule the work without me phoning in.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL provide a booking request form at `/fleet/bookings/new` requiring: vehicle (selected from the user's accessible vehicles), preferred date (today or future), preferred time slot (`'morning'`, `'afternoon'`, or `'all_day'`), service description (≥ 10 chars), and optional notes.
2. WHEN a Portal_User submits a booking request, THE Fleet_Portal SHALL create a `fleet_service_booking_requests` row with `status = 'pending'`, `requested_by_portal_account_id`, `customer_vehicle_id`, `org_id`, `fleet_account_id`, `preferred_date`, `preferred_slot`, `service_description`, `notes`, and SHALL emit an in-app notification (`type = 'fleet_booking_request'`) to all Workshop_Admins of the Workshop_Org.
3. IF the submitted preferred date is in the past relative to the Workshop_Org's timezone, THEN THE Fleet_Portal SHALL return HTTP 400 with message "Preferred date must be today or later".
4. WHEN a Workshop_Admin accepts a Service_Booking_Request, THE Org_Admin_Panel SHALL create a draft row in the existing `bookings` table linked to the request via `fleet_service_booking_requests.booking_id`, set the request `status = 'accepted'`, and send an email notification to the requesting Portal_User.
5. WHEN a Workshop_Admin declines a Service_Booking_Request, THE Org_Admin_Panel SHALL set the request `status = 'declined'`, store an optional `decline_reason`, and send an email notification to the requesting Portal_User.
6. THE Fleet_Portal SHALL display a list of all Service_Booking_Requests for the Fleet_Account at `/fleet/bookings` showing vehicle rego, preferred date, preferred slot, service description, status (pending, accepted, declined, completed, cancelled), and created date.
7. THE Org_Admin_Panel SHALL display a "Fleet Bookings" queue (gated by `<ModuleGate module="b2b-fleet-management">`) showing all pending requests across all Fleet_Accounts of the Workshop_Org with actions to accept (with date/time refinement) or decline.
8. THE Fleet_Portal SHALL allow the requester to cancel their own pending Service_Booking_Request, setting `status = 'cancelled'` and notifying the Workshop_Org.

### Requirement 12: Quotation Requests

**User Story:** As a Fleet_Account_Admin, I want to request a quotation for a specific service on a specific vehicle, so that I can get pricing before agreeing to the work.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL provide a quotation request form at `/fleet/quotes/request` accessible only to Portal_Users with `portal_user_role = 'fleet_admin'`, requiring: vehicle, service description (≥ 10 chars), and optional notes.
2. WHEN a Fleet_Account_Admin submits a quotation request, THE Fleet_Portal SHALL create a `fleet_quotation_requests` row with `status = 'pending'`, `customer_vehicle_id`, `org_id`, `fleet_account_id`, `requested_by_portal_account_id`, `service_description`, `notes`, and SHALL emit an in-app notification (`type = 'fleet_quote_request'`) to Workshop_Admins.
3. WHEN a Workshop_Admin creates a quote in the existing quotes module and links it to a Quotation_Request (sets `fleet_quotation_requests.quote_id`), THE Fleet_Portal SHALL set the request `status = 'quoted'` and send an email notification to the Fleet_Account_Admin.
4. WHEN a Fleet_Account_Admin views a quoted request, THE Fleet_Portal SHALL display the quote line items, totals, validity, and Accept / Decline actions.
5. WHEN a Fleet_Account_Admin accepts a quote via the portal, THE Fleet_Portal SHALL set the request `status = 'accepted'`, mark the quote accepted via the existing portal quote acceptance service, and emit an in-app notification to the Workshop_Org.
6. WHEN a Fleet_Account_Admin declines a quote via the portal, THE Fleet_Portal SHALL set the request `status = 'declined'`, mark the quote declined via the existing service, and emit an in-app notification to the Workshop_Org.
7. WHEN a quote linked to a Quotation_Request expires (existing quote `valid_until` is in the past), THE Fleet_Portal SHALL display the request as `expired` and SHALL NOT allow acceptance.

### Requirement 13: Invoice Viewing

**User Story:** As a Fleet_Account_Admin, I want to view all invoices issued to my business and download PDFs, so that I can keep records and pay outstanding amounts.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL display a paginated list of invoices at `/fleet/invoices` filtered to the Fleet_Account's `customer_id` and `org_id`, with 20 items per page and offset-based navigation.
2. FOR EACH invoice in the list, THE Fleet_Portal SHALL display: invoice number, date, total (formatted as NZD currency by default unless the org is configured otherwise), balance due, and payment status badge (paid, unpaid, overdue).
3. THE Fleet_Portal SHALL allow filtering by status: all, unpaid, paid, overdue.
4. WHEN a Fleet_Account_Admin clicks an invoice row, THE Fleet_Portal SHALL display the invoice detail showing line items, tax breakdown, payments history (from `payments`), and linked vehicle if any.
5. THE Fleet_Portal SHALL provide a "Download PDF" action that calls the existing `get_portal_invoice_pdf()` service path.
6. THE Fleet_Portal SHALL display invoices issued by the same Workshop_Org only; cross-org invoice viewing SHALL NOT be possible (enforced by `org_id` filter and Postgres RLS).
7. WHERE the authenticated Portal_User is a Driver_User, THE Fleet_Portal SHALL hide the invoice list and detail routes and return HTTP 403 if accessed directly.

### Requirement 14: Driver Activity Visibility for Fleet Account Admin

**User Story:** As a Fleet_Account_Admin, I want to see each driver's activity — kilometres logged, hours logged, checklists completed — so that I have visibility over fleet operations.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL display a driver activity page at `/fleet/drivers/{portal_account_id}/activity` accessible only to Portal_Users with `portal_user_role = 'fleet_admin'` for drivers in the same Fleet_Account.
2. FOR EACH driver, THE Fleet_Portal SHALL display: total odometer kilometres logged in the selected date range, total driving hours, number of checklists completed, and number of checklists with at least one failure.
3. THE Fleet_Portal SHALL provide date range filters (last 7 days, last 30 days, last 90 days, custom range up to 365 days).
4. THE Fleet_Portal SHALL provide a per-vehicle activity breakdown for the selected driver, showing kilometres, hours, and checklist count per `customer_vehicle_id`.
5. THE Fleet_Portal SHALL provide an export action that generates a CSV of the driver's activity for the selected date range, with one row per (date, vehicle) pair.

### Requirement 15: Fleet Dashboard

**User Story:** As a Fleet_Account_Admin, I want a dashboard view summarising fleet status and today's activity, so that I can spot problems quickly.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL display a dashboard at `/fleet/dashboard` as the default landing page after login for Fleet_Account_Admins.
2. THE Fleet_Portal SHALL display, on the dashboard, summary cards showing: total vehicles, vehicles with WOF expiring within 28 days, vehicles with COF expiring within 28 days, vehicles overdue for service, today's checklists pending count, and today's checklists completed count.
3. THE Fleet_Portal SHALL display a "Recent failures" panel listing the last 10 Checklist_Submissions where `failed_item_count > 0`, ordered by `completed_at DESC`, with vehicle rego, driver name, and number of failed items.
4. THE Fleet_Portal SHALL display a "Pending bookings" panel showing the count of pending Service_Booking_Requests with a link to `/fleet/bookings`.
5. THE Fleet_Portal SHALL display a "Pending quotes" panel showing the count of pending Quotation_Requests with a link to `/fleet/quotes`.
6. WHERE the authenticated Portal_User is a Driver_User, THE Fleet_Portal SHALL display a driver-scoped dashboard showing: assigned vehicles, today's checklist status per vehicle (Pending / Completed today), and the next assigned shift if any.

### Requirement 16: Workshop Admin Fleet Management Console

**User Story:** As a Workshop_Admin, I want a console in the existing org admin panel to manage all Fleet_Accounts, bookings, quote requests, and module-level settings for fleet portal, so that I can run the fleet portal product alongside my other workflows.

#### Acceptance Criteria

1. WHERE the `b2b-fleet-management` module is enabled, THE Org_Admin_Panel SHALL display a "Fleet Portal" sidebar item linking to `/fleet-portal-admin/dashboard`.
2. THE Org_Admin_Panel SHALL display a queue at `/fleet-portal-admin/bookings` listing pending Service_Booking_Requests across all Fleet_Accounts with columns Customer Name, Vehicle Rego, Service Description, Preferred Date, Preferred Slot, Status, and Actions.
3. THE Org_Admin_Panel SHALL display a queue at `/fleet-portal-admin/quotes` listing pending Quotation_Requests with columns Customer Name, Vehicle Rego, Service Description, Status, Linked Quote, and Actions.
4. WHEN a Workshop_Admin clicks "Create Quote" on a Quotation_Request, THE Org_Admin_Panel SHALL navigate to QuoteCreate pre-populated with the Fleet_Account's customer and the requested vehicle.
5. THE Org_Admin_Panel SHALL display a count badge on the "Fleet Portal" sidebar item equal to `pending_bookings + pending_quotes` for the Workshop_Org.
6. THE Org_Admin_Panel SHALL display a list at `/fleet-portal-admin/accounts` of all Fleet_Accounts of the Workshop_Org with columns Customer Name, Number of Vehicles, Number of Drivers, Last Login, Portal Status, and Actions (Resend Invite, Revoke Access, View Customer).
7. THE Org_Admin_Panel SHALL display a checklist failures feed at `/fleet-portal-admin/checklist-failures` showing the most recent Checklist_Submissions across all Fleet_Accounts where `failed_item_count > 0`, with filters by Fleet_Account and date range.

### Requirement 17: Multi-Tenant Isolation, RLS, and Authorisation

**User Story:** As a Workshop_Admin, I want strict tenant isolation between Workshop_Orgs and between Fleet_Accounts, so that no portal user can see data belonging to another org or another fleet.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL filter every query by `org_id` derived from the resolved Workshop_Org and by `fleet_account_id` derived from the authenticated Portal_User; SHALL NOT trust any `org_id` or `fleet_account_id` provided by the client in URL or body.
2. THE Fleet_Portal SHALL apply Postgres RLS policies on every new table introduced by this feature (`fleet_accounts`, `fleet_driver_assignments`, `fleet_checklist_templates`, `fleet_checklist_template_items`, `fleet_checklist_submissions`, `fleet_checklist_submission_items`, `fleet_reminder_preferences`, `fleet_service_booking_requests`, `fleet_quotation_requests`, `fleet_driver_hours`) keyed on `org_id`.
3. IF a Portal_User attempts to access a resource (vehicle, checklist, booking, quote, invoice) whose `org_id` differs from the resolved Workshop_Org or whose `fleet_account_id` differs from the authenticated Portal_User's `fleet_account_id`, THEN THE Fleet_Portal SHALL return HTTP 404 (not 403, to avoid leaking existence).
4. IF a Driver_User attempts to access a vehicle that is not present in `fleet_driver_assignments` for that Driver_User, THEN THE Fleet_Portal SHALL return HTTP 404.
5. IF a Driver_User attempts to access an admin-only endpoint (drivers management, checklist template management, reminder preferences, quotation requests, invoices), THEN THE Fleet_Portal SHALL return HTTP 403 with message "This action requires Fleet Account Admin access".
6. THE Fleet_Portal SHALL validate, on every authenticated request, that the Portal_User's `is_active = true`, the Fleet_Account's `is_active = true`, and the Workshop_Org has the `b2b-fleet-management` module enabled; failure of any check SHALL return HTTP 403 and destroy the session.

### Requirement 18: API Response Shape and Conventions

**User Story:** As a frontend developer integrating with the Fleet Portal API, I want consistent response shapes and conventions so that I can consume endpoints safely.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL return list endpoints in the shape `{ "items": [...], "total": N }` and SHALL NOT return bare arrays.
2. THE Fleet_Portal SHALL accept pagination as `offset` (integer, ≥ 0) and `limit` (integer, 1–100, default 20) on every list endpoint and SHALL NOT accept `skip`.
3. THE Fleet_Portal SHALL return error responses in the shape `{ "detail": "<message>" }` consistent with the existing FastAPI convention.
4. THE Fleet_Portal SHALL expose all backend endpoints under the prefix `/fleet/api/...` (or `/api/v2/fleet-portal/...` for admin-side endpoints invoked from the existing Org_Admin_Panel).
5. THE Fleet_Portal SHALL document every new endpoint in the FastAPI OpenAPI schema with tags `fleet-portal` (portal-user-facing) or `fleet-portal-admin` (workshop-admin-facing).

### Requirement 19: Frontend Standards and Mobile Responsiveness

**User Story:** As a Driver_User on a phone or tablet, I want the Fleet Portal to work fluidly on small screens and on shared kiosk tablets, so that I can complete checklists and log activity in the field.

#### Acceptance Criteria

1. THE Fleet_Portal frontend SHALL be built with React 18, TypeScript, Tailwind CSS, and Vite, consistent with the existing repository.
2. THE Fleet_Portal SHALL render correctly on viewports between 320 px and 1920 px wide; primary actions on mobile SHALL have minimum touch targets of 44 × 44 CSS pixels.
3. THE Fleet_Portal kiosk checklist view (`/fleet/kiosk/checklist`) SHALL use minimum 56 × 56 CSS pixels touch targets, full-screen layout with no sidebar, and font sizes ≥ 18 px to support depot tablets.
4. THE Fleet_Portal SHALL apply optional chaining (`?.`) and nullish-coalescing defaults (`?? []`, `?? 0`) on every API consumption per the existing safe-API consumption rules.
5. THE Fleet_Portal SHALL use AbortController in every `useEffect` API call and abort on cleanup.
6. THE Fleet_Portal SHALL support light and dark mode via Tailwind `dark:` variants consistent with the rest of the application.
7. THE Fleet_Portal SHALL respect device safe-area insets (`env(safe-area-inset-*)`, `pb-safe`) on mobile viewports so the layout does not collide with phone notches, dynamic islands, or home indicators (mirrors the existing mobile-app pattern from `.kiro/steering/mobile-app.md`).
8. THE Fleet_Portal SHALL use a single-column layout below 480 px wide for all primary screens (Dashboard, Vehicles, Checklists, Drivers, Bookings, Quotes, Invoices, Reminders, My Security), and SHALL collapse the sidebar into a hamburger menu below 768 px.
9. THE Fleet_Portal SHALL use accessible touch interactions on mobile: tap-to-open dropdowns, swipe-to-dismiss for non-blocking toasts, pull-to-refresh on list pages.
10. THE Fleet_Portal SHALL render the photo upload control (Requirement 9.4) using a native HTML `<input type="file" accept="image/*" capture="environment">` so phones open the rear camera directly without a Capacitor plugin (the portal is web-only per Requirement 20.7).

### Requirement 20: Out of Scope

**User Story:** As a Workshop_Admin, I want the scope of this feature to be explicit so that downstream design and implementation do not creep into adjacent functionality.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL NOT include GPS tracking of vehicles.
2. THE Fleet_Portal SHALL NOT include real-time vehicle telemetry (engine codes, fuel level, ignition state).
3. THE Fleet_Portal SHALL NOT include fuel-card or fuel-purchase integration.
4. THE Fleet_Portal SHALL NOT include driver behaviour scoring (harsh braking, speeding, idling).
5. THE Fleet_Portal SHALL NOT include route optimisation or trip planning.
6. THE Fleet_Portal SHALL NOT include DOT or other regulatory reporting beyond the NZTA pre-trip checklist functionality described in Requirements 8 and 9.
7. THE Fleet_Portal SHALL be available via two surfaces: (a) the responsive web SPA at `fleet.<domain>` or `/fleet/...` for browser-based access, and (b) the existing OraInvoice native mobile app (Capacitor 8, iOS/Android) extended with a fleet portal sign-in option per Requirement 24. Both surfaces hit the same `/fleet/api/...` backend endpoints. A separate native app dedicated only to fleet portal users is OUT OF SCOPE — the existing app is extended, not duplicated. The Capacitor 7 → 8 upgrade is a prerequisite (task 19L) per the dependency audit `docs/DEPENDENCY_AUDIT_2026_05.md`.

### Requirement 21: Security Settings Parity for Portal Users

**User Story:** As a Workshop_Admin (and as a customer-facing operator with ISO 27001 / SOC 2 / PCI-DSS aspirations), I want Portal_Users to have the same configurable security controls (MFA, password policy, lockout policy, session policy, audit log) as my internal organisation users, so that the Fleet_Portal does not become a weaker authentication surface than the staff app.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL apply a per-org `portal_security_policy` that mirrors the existing `OrgSecuritySettings` schema (`mfa_policy`, `password_policy`, `lockout_policy`, `session_policy`) with separate values from the staff policy.
2. THE Workshop_Admin SHALL be able to view and edit `portal_security_policy` at `/fleet-portal-admin/settings` with the same UI affordances as the existing org security settings page.
3. THE Password_Policy for Portal_Users SHALL support: `min_length` (8–128), `require_uppercase`, `require_lowercase`, `require_digit`, `require_special`, `expiry_days` (0–365), `history_count` (0–24, no reuse of last N passwords).
4. THE Fleet_Portal SHALL enforce the configured `password_policy` on Portal_User password creation, password change, and password reset; rejections SHALL return HTTP 400 with a message naming the violated rule(s).
5. THE Fleet_Portal SHALL maintain a per-Portal_User `password_history` table (last `history_count` bcrypt hashes) and SHALL reject any password whose bcrypt-verify matches any entry in the history.
6. THE Fleet_Portal SHALL check candidate passwords against the HIBP "Pwned Passwords" k-anonymity API (cached for 24 hours per SHA-1 5-prefix bucket); IF the password appears in the breach corpus AND `password_policy.require_not_pwned = true`, THEN the change SHALL be rejected with HTTP 400 and message "This password has appeared in a known data breach. Please choose another.".
7. THE Lockout_Policy for Portal_Users SHALL support both `temp_lock_threshold` (3–10 failures → temporary lock for `temp_lock_minutes`) and `permanent_lock_threshold` (5–20 failures → permanent lock until Workshop_Admin manually unlocks).
8. THE Session_Policy for Portal_Users SHALL support: `max_sessions_per_user` (1–10), `idle_timeout_minutes` (15–240), `refresh_token_expire_days` (1–30), and SHALL terminate sessions exceeding `max_sessions_per_user` (oldest first, FIFO).
9. THE Mfa_Policy for Portal_Users SHALL support modes `optional`, `mandatory_admins_only` (Fleet_Account_Admins only), and `mandatory_all` (Fleet_Account_Admins and Driver_Users).
10. THE Fleet_Portal SHALL allow Portal_Users to enrol TOTP MFA at `/fleet/security/mfa/enroll/totp` using the same QR-code / 6-digit-OTP flow as the staff `UserMfaMethod` infrastructure, persisted to a new `portal_account_mfa_methods` table keyed on `portal_account_id`.
11. THE Fleet_Portal SHALL allow Portal_Users to enrol SMS MFA at `/fleet/security/mfa/enroll/sms` using the existing Connexus SMS integration, only if the Workshop_Org has SMS configured; otherwise the option SHALL be hidden.
12. THE Fleet_Portal SHALL generate and display 10 single-use backup codes on first MFA enrolment, persisted as bcrypt hashes in `portal_account_backup_codes`; each code SHALL be consumable exactly once.
13. WHEN MFA is configured for a Portal_User, THE Fleet_Portal SHALL require a successful MFA verification on every login before issuing a Fleet_Portal_Session.
14. WHEN `mfa_policy.mode = 'mandatory_all'` (or `mandatory_admins_only` for an admin) AND a Portal_User logs in without MFA configured, THE Fleet_Portal SHALL force MFA enrolment as a blocking step before access is granted.
15. THE Fleet_Portal SHALL maintain an audit log of every Portal_User authentication event (`portal_auth.login_success`, `portal_auth.login_failed_invalid_password`, `portal_auth.login_failed_account_locked`, `portal_auth.mfa_verified`, `portal_auth.mfa_failed`, `portal_auth.password_changed`, `portal_auth.password_reset`, `portal_auth.session_revoked`, `portal_auth.account_locked`, `portal_auth.account_unlocked`, `portal_auth.mfa_enrolled`, `portal_auth.mfa_disabled`) with timestamp, IP, user-agent, and `portal_account_id`.
16. THE Fleet_Portal SHALL provide a "My Security" page at `/fleet/security` where the Portal_User can: change their password (current password + new password + confirm), enrol or remove MFA methods, view their last 10 login events, and view and revoke their other active sessions.
17. THE Workshop_Admin Console SHALL display, on the Portal_User detail page (`/fleet-portal-admin/accounts/{portal_account_id}`), the Portal_User's status, last_login_at, last_password_change_at, last_mfa_verified_at, current MFA methods, active sessions list (with revoke button), and the last 90 days of audit log entries.
18. THE Workshop_Admin SHALL be able to manually unlock a Portal_User from the detail page (sets `failed_login_attempts = 0`, `locked_until = NULL`, audit-logs `portal_auth.account_unlocked`).
19. THE Workshop_Admin SHALL be able to force a Portal_User to re-enrol MFA from the detail page (deletes all `portal_account_mfa_methods` rows for that account, audit-logs `portal_auth.mfa_disabled`).
20. THE Workshop_Admin SHALL be able to reset a Portal_User's password (admin-initiated) from the detail page following the kiosk-password-reset spec pattern (admin sets a new password, all sessions for that account are invalidated, the Portal_User receives an email with the new password and a "must change on next login" flag).
21. THE Workshop_Admin SHALL be able to "View as Portal User" from the FleetAccountList — clicking the action creates a time-limited (15-minute) impersonation session, audit-logs `portal_auth.impersonation_started` and `portal_auth.impersonation_ended`, displays a banner "Viewing as {portal_user.email} (impersonation, expires at {time})" while active, and prevents any state-changing portal write while in impersonation mode.

### Requirement 22: Frontend Version Refresh & Cache Busting

**User Story:** As a Portal_User who has the Fleet_Portal open in my browser when the Workshop_Org deploys an update, I want my browser to detect the new version and prompt me to reload, so that I do not continue using stale frontend code that mismatches the backend.

#### Acceptance Criteria

1. THE Fleet_Portal backend SHALL expose `GET /fleet/api/version` returning `{ "version": "<semver>", "build_sha": "<git_sha>", "released_at": "<iso8601>" }` derived from `app/__init__.py` `__version__` and a build-time git sha.
2. THE Fleet_Portal SPA SHALL include the build's version in a `<meta name="x-app-version">` tag in `index.html` at build time.
3. THE Fleet_Portal SPA SHALL poll `GET /fleet/api/version` every 60 seconds while focused; WHEN the response `build_sha` differs from the loaded `<meta>` value, THE SPA SHALL display a non-blocking "New version available — reload to update" toast with a "Reload now" action.
4. THE Fleet_Portal SPA SHALL expose a manual "Check for updates" button in the Profile page that calls the same endpoint immediately.
5. THE Fleet_Portal nginx config SHALL serve `index.html` with `Cache-Control: no-store` and serve hashed JS/CSS chunks with `Cache-Control: public, max-age=31536000, immutable`, so that an `index.html` reload always picks up the latest chunk filenames without needing a hard refresh.

### Requirement 23: Security Headers and CSP for the Fleet Portal

**User Story:** As a security reviewer for ISO/SOC2/PCI compliance readiness, I want the Fleet_Portal to ship with strict security headers and a Content-Security-Policy, so that XSS and clickjacking attack surface is minimised.

#### Acceptance Criteria

1. THE Fleet_Portal SHALL serve all responses with the following headers (applied by the existing nginx config or a FastAPI middleware analogous to `PortalCacheRoute`): `Cache-Control: no-store, Pragma: no-cache` on every response under `/fleet/api/...`; `X-Frame-Options: DENY`; `X-Content-Type-Options: nosniff`; `Referrer-Policy: same-origin`; `Strict-Transport-Security: max-age=31536000; includeSubDomains` on the fleet host; `Permissions-Policy: camera=(self), microphone=(), geolocation=()`.
2. THE Fleet_Portal SHALL serve a Content-Security-Policy header that disallows `unsafe-inline` for scripts, allows `'self'` for default-src, and only whitelists the existing CDN origins required by the SPA (matching the staff app's CSP, with `fleet.<domain>` substituted for the staff host where applicable).
3. THE Fleet_Portal SHALL serve cookies with `HttpOnly`, `Secure`, `SameSite=Lax`. Cookie scope depends on deployment mode (read at runtime from `FLEET_PORTAL_HOST`):
   - **Subdomain mode** (`fleet.<domain>`): cookie has `Domain=fleet.<domain>` and `Path=/` so it is scoped to the fleet subdomain only.
   - **Sub-path mode** (`/fleet/...`): cookie has `Path=/fleet` (no `Domain` attribute, defaults to current host) so the staff origin never sees it.
   The cookie SHALL never be sent to the staff origin.

### Requirement 24: Native Mobile App Support for Portal Users

**User Story:** As a Fleet_Account_Admin or Driver_User who already has the OraInvoice mobile app installed (or is asked to install it for fleet portal use), I want to log in with my portal credentials and see screens designed for my role — fleet vehicles, pre-trip checklists, hours, bookings, and so on — without seeing any staff-facing screens or being routed through the staff JWT auth flow, so that the mobile experience is purpose-built for fleet operators rather than a stripped-down staff app.

#### Acceptance Criteria

1. THE Mobile_App SHALL provide a "Sign in to Fleet Portal" option on its login screen, distinct from the existing staff "Sign in" option. The fleet sign-in flow SHALL collect email + password and authenticate against `POST /fleet/api/auth/login` (returning a Fleet_Portal_Session cookie), NOT against the staff `/auth/login` endpoint.
2. THE Mobile_App SHALL persist the active authentication mode (`'staff'` or `'fleet'`) in `Capacitor Preferences` so that returning users land on the correct login form on next launch (no re-prompt).
3. THE Mobile_App SHALL detect a Fleet_Portal_Session and route the user to a **Fleet_Portal_Mobile_Shell** with bottom-tab navigation customised for the Portal_User's role (NOT the staff Dashboard / Invoices / Customers / Jobs / More tabs):
   - **Fleet_Account_Admin tabs:** Dashboard, Vehicles, Drivers, Bookings, More.
   - **Driver_User tabs:** My Vehicles, Checklists, Hours, More.
4. THE Mobile_App SHALL gate every Fleet_Portal_Mobile_Shell screen behind a valid Fleet_Portal_Session — IF a staff JWT is present without a Fleet_Portal_Session, the user SHALL see only staff screens; IF a Fleet_Portal_Session is present without a staff JWT, the user SHALL see only fleet portal screens.
5. THE Mobile_App SHALL apply the same MFA flow as the web portal (Requirement 21) on fleet portal login: when the login response is `mfa_required = true`, the app navigates to `/mobile/fleet/mfa-verify` and submits the 6-digit code or backup code to `POST /fleet/api/auth/mfa/verify`.
6. THE Mobile_App SHALL apply the same first-login enrolment flow when `mfa_setup_required = true`, navigating to a `/mobile/fleet/security/mfa/enroll/totp` screen that displays the QR code + 6-digit confirm input, posting to `POST /fleet/api/auth/mfa/enroll/totp/confirm`.
7. THE Mobile_App SHALL provide the following screens for Driver_Users in `mobile/src/screens/fleet-portal/`:
   - `FleetDashboardScreen` — assigned vehicles count, today's checklist status, next shift if any.
   - `MyVehiclesScreen` — list of assigned vehicles with WOF/COF/service-due badges; tap to open `VehicleDetailScreen` (read fields + log odometer + log driving hours).
   - `ChecklistSubmitScreen` — driver pre-trip flow with item rows, pass/fail buttons, photo capture via Capacitor `Camera.getPhoto({ source: CameraSource.Camera, resultType: CameraResultType.Uri })`, and a "Complete" button that calls `POST /fleet/api/checklists/{id}/complete`.
   - `ChecklistHistoryScreen` — driver's own submission history, scrollable, filter by date.
   - `HoursLogScreen` — list of recent driving-hour entries; "+ Log hours" opens a modal that calls `POST /fleet/api/vehicles/{id}/hours`.
   - `MoreScreen` (driver variant) — Profile, Notifications, My Security (MFA, change password, sessions), About, Logout.
8. THE Mobile_App SHALL provide the following additional screens for Fleet_Account_Admins:
   - `FleetVehiclesScreen` — full fleet list (replaces driver-scoped MyVehiclesScreen for admins).
   - `DriversScreen` — list of drivers, invite button, tap-to-assign-vehicles.
   - `BookingsScreen` — list of service booking requests, "+ New booking" form with vehicle picker.
   - `RemindersScreen` — per-vehicle WOF/COF/service-due toggles with lead-time selector.
   - `MoreScreen` (admin variant) — adds Quotes, Invoices (read-only list + PDF download), Drivers, Reminders to the driver More menu.
9. THE Mobile_App SHALL apply Konsta UI primitives (`Page`, `Block`, `BlockTitle`, `Card`, `List`, `ListItem`, `Button`, `Preloader`, `Chip`, `Toolbar`) consistent with the existing `mobile/src/screens/portal/PortalScreen.tsx` and `mobile/src/components/konsta/KonstaNavbar.tsx` so the fleet portal screens visually match the rest of the mobile app.
10. THE Mobile_App SHALL apply Capacitor 8 native features for the Driver_User flow: `Camera` plugin for photo capture in the checklist; `Push Notifications` plugin for booking-accepted, booking-declined, and quote-quoted alerts; `Network` plugin for offline-state detection; `Preferences` plugin for the auth-mode persistence above. The Capacitor 7 → 8 upgrade is implemented in task 19L and is a prerequisite for any code added under Requirement 24.
11. THE Mobile_App SHALL apply biometric unlock (Face ID / Touch ID / fingerprint via `@capgo/capacitor-native-biometric` v8-compatible) to the fleet portal login flow, mirroring the existing staff biometric pattern. The biometric data SHALL be stored under a separate keychain entry (`fleet-portal-biometric` vs the existing `staff-biometric`) so the two never cross. The plugin swap from the abandoned `capacitor-native-biometric` to `@capgo/capacitor-native-biometric` is in task 19L.1.
12. THE Mobile_App fleet portal screens SHALL apply the same touch-target / safe-area / single-column rules as Requirement 19 (44×44 px minimum, `pb-safe`, single-column below 480 px wide, sticky pass/fail buttons on checklist).
13. THE Mobile_App SHALL include a "Switch to Staff Login" link on the fleet sign-in screen, and a "Switch to Fleet Portal Login" link on the staff sign-in screen, allowing users to flip between the two without uninstalling/reinstalling the app.
14. THE Mobile_App SHALL detect when the active session has been revoked server-side (HTTP 401 on any fleet API call) and clear the local session, navigate to the fleet login screen, and show a non-blocking toast "Your session has expired. Please sign in again.".
15. THE Mobile_App SHALL support push notifications scoped to the Portal_User's `portal_account_id` — backend registers the device token under `portal_account_devices` (a new table created by migration 0191) and the new `app/modules/push_notifications/` module (created by this spec — task 19M.9 — since the existing codebase only has the mobile-side hook) routes notifications based on whether the recipient is a `User` or a `PortalAccount`. **MVP scope:** Android (FCM) only; iOS APNs is a follow-up. **Fallback policy:** when FCM is not configured or the FCM call fails, the push send is a no-op; the in-app notification + email continue to fire as the primary surface so the user is never silently uninformed.
16. THE Mobile_App SHALL expose the same `/fleet/api/version` polling pattern (Requirement 22.3) on launch and every 60 seconds while focused, and prompt the user to reload in-app via Capacitor `App.exitApp()` + `App.openUrl()` re-launch when the app version is older than the server build.
17. THE Mobile_App SHALL gate all fleet portal screens behind the `b2b-fleet-management` module — if the Workshop_Org disables the module mid-session, the next API call returns 403 and the app shows a full-screen "This service is no longer available" message with a Logout button.
18. WHERE the kiosk Driver_User flow is run on a tablet at a depot (not a personal phone), THE Mobile_App SHALL provide a "Kiosk mode" toggle in the More menu that locks the app to `/mobile/fleet/kiosk/checklist` until a 6-digit unlock PIN is entered (mirroring the existing `mobile/src/screens/kiosk/` pattern but rooted at the Driver_User's portal account).
