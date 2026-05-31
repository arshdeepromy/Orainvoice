# Staff Management — Phase 1: Tab Restructure + Employee Record + Roster Delivery

## Overview

Phase 1 of the Staff & Contractor Management System. Converts the single-form `StaffDetail.tsx` into a tabbed layout, expands the staff record with the employment fields every later phase depends on, ships pay-rate change history, surfaces compliance warnings (minimum wage, missing employment agreement, expiring visa, probation end), and adds Roster delivery via email and SMS.

This phase delivers visible UX immediately and unblocks every later phase. No leave engine, no clock-in/out, no payslips — those land in Phases 2–4.

**Source:** `docs/future/staff-management-system.md` §6 Phase 1, §7A categories A and C.

**Trade-family scope:** Universal across all 16 trade families. No `isAutomotive` / `isTargetTrade` gating. Module gate via `staff_management` is the only conditional rendering.

**Status:** Draft, awaiting implementation.

## Steering compliance

- All API list responses wrap arrays in objects per `project-overview.md`. New endpoints introduced by Phase 1 use `{ items: [...], total: N }`. The pre-existing `GET /api/v2/staff` list endpoint already returns `{ staff: [...], total, page, page_size }` — Phase 1 does NOT rename `staff` to `items`; the new `compliance_summary` field is added as a parallel top-level key.
- All `db.flush()` followed by `await db.refresh(obj)` before Pydantic serialization.
- Every migration uses `IF NOT EXISTS` for `CREATE TABLE` and `ALTER TABLE ADD COLUMN`.
- All index migrations use `CREATE INDEX CONCURRENTLY ... IF NOT EXISTS` inside `op.get_context().autocommit_block()` per `database-migration-checklist.md` (canonical template `alembic/versions/2026_05_30_2300-0202_add_perf_indexes.py`). Zero `op.create_index(...)` calls.
- All new tables get `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` + a `tenant_isolation` policy at creation (per migration `0008`).
- PII columns (IRD number, bank account number) stored as `BYTEA` envelope-encrypted via `app/core/encryption.py::envelope_encrypt`; never plaintext `TEXT`.
- PII returned masked (`***123` for IRD, `**-****-****56-00` for bank acct) — full plaintext only inside the future payslip-rendering path.
- Mask-pattern detection on save: when the form re-submits a masked value, skip that field (never overwrite a real value with the mask string).
- New module `staff_management` registered in `module_registry` with `setup_question` + `setup_question_description` per `setup-guide-for-new-modules.md`.
- Mirror `feature_flags` row inserted alongside (Rule 8 of `implementation-completeness-checklist.md`).
- Default subscription plan's `enabled_modules` JSONB updated to include `staff_management`.
- All emails route through unified `app/integrations/email_sender.py::send_email`.
- All SMS routes through a new thin wrapper `app/integrations/sms_sender.py::send_sms` (introduced in Phase 1, mirrors `email_sender.py`'s shape), which loads the active `SmsVerificationProvider` row and dispatches via the existing `connexus_sms` provider stack. (P1-N9 fix: previously this bullet implied the wrapper already existed — it doesn't, this phase ships it.)
- Frontend: every API call uses `?.` + `?? []` / `?? 0`; every `useEffect` with API call uses `AbortController`; no `as any`.
- E2E test script ships with the PR: `scripts/test_staff_employment_record_e2e.py`.

## Requirements

### R1. Tabbed Staff Detail Page

**User story:** As an org admin, I want the Staff Detail screen organised into tabs so I can navigate between Personal/Employment data, Roster, and (in later phases) Leave/Hours/Payslips, instead of scrolling through one long form.

**Acceptance criteria (EARS):**

1. WHEN a user navigates to `/staff/:staffId` THE SYSTEM SHALL render a tabbed layout with the following tabs in order: **Overview**, **Roster**, **Documents**.
2. WHEN the `staff_management` module is disabled for the org THE SYSTEM SHALL render only the legacy single-form view (no tabs) so the feature is module-gated.
3. WHEN a user clicks the **Overview** tab THE SYSTEM SHALL render the existing personal info, employment details, and work-schedule editor PLUS the new fields defined in R2.
4. WHEN a user clicks the **Roster** tab THE SYSTEM SHALL embed the existing `ScheduleCalendar` component filtered to the current staff member only, with action buttons "Add shift", "Apply template", "Email this week's roster", "Send roster SMS".
5. WHEN a user clicks the **Documents** tab THE SYSTEM SHALL render the upload slot for the signed employment agreement (R5) and any other compliance documents.
6. WHEN a user navigates between tabs with unsaved changes on Overview THE SYSTEM SHALL prompt "Discard unsaved changes?" before switching.
7. THE SYSTEM SHALL persist the active tab in the URL hash (`#overview`, `#roster`, `#documents`) so the browser back button and refresh land on the same tab.

### R2. Expanded Employment Record

**User story:** As an org admin, I need to capture the employment fields every NZ payslip and leave engine requires, so Phase 2 (leave) and Phase 4 (payslips) can be built on real data.

**Acceptance criteria:**

1. THE SYSTEM SHALL add the following columns to `staff_members`, all nullable except where noted, all idempotent (`ADD COLUMN IF NOT EXISTS`):
   - `employment_start_date` (date)
   - `employment_end_date` (date) — nullable; set when staff is terminated
   - `employment_type` (text, default `'permanent'`) — values `permanent | casual | fixed_term`; CHECK constraint enforces enum
   - `standard_hours_per_week` (numeric(5,2))
   - `tax_code` (text) — values `M | ME | S | SH | ST | SB | CAE | NSW | ND` per IRD; CHECK enforces enum
   - `ird_number_encrypted` (bytea)
   - `student_loan` (boolean, default false)
   - `kiwisaver_enrolled` (boolean, default false)
   - `kiwisaver_employee_rate` (numeric(4,2)) — values 3, 4, 6, 8, 10
   - `kiwisaver_employer_rate` (numeric(4,2), default 3.00)
   - `bank_account_number_encrypted` (bytea)
   - `probation_end_date` (date) — auto-set to `start_date + 90 days` on creation, editable
   - `residency_type` (text, NOT NULL, default `'citizen'`) — values `citizen | permanent_resident | work_visa | student_visa | other`; drives whether `visa_expiry_date` is rendered + counted in compliance reports. CHECK enforces enum.
   - `visa_expiry_date` (date) — only rendered + counted when `residency_type IN ('work_visa', 'student_visa', 'other')`. Nullable in all cases.
   - `self_service_clock_enabled` (boolean, NOT NULL, default false)
   - `on_file_photo_url` (text)
   - `emergency_contact_name` (text)
   - `emergency_contact_phone` (text)
   - `weekly_roster_email_enabled` (boolean, NOT NULL, default true)
   - `weekly_roster_sms_enabled` (boolean, NOT NULL, default false)
2. WHEN the API receives a POST/PUT to `/api/v2/staff` or `/api/v2/staff/:id` containing `ird_number` THE SYSTEM SHALL call `envelope_encrypt(value)` and store the resulting bytes in `ird_number_encrypted`.
3. WHEN the API returns a staff record THE SYSTEM SHALL mask `ird_number` as `***NNN` (last 3 digits) and `bank_account_number` as `**-****-****NN-NN` (last 4 digits across the 16-digit NZ pattern).
4. WHEN a save payload contains `ird_number` matching the mask pattern (`re.match(r'^\*+\d{3}$', value)`) THE SYSTEM SHALL skip that field on update (never overwrite the real ciphertext with the mask).
5. THE SYSTEM SHALL refuse a POST/PUT with `tax_code` not in the enum with HTTP 422.
6. WHEN a staff is created without `probation_end_date` THE SYSTEM SHALL set it to `employment_start_date + 90 days` if `employment_start_date` is present, else NULL.

### R3. Pay Rate History (audit + anniversary review)

**User story:** As an org admin, I need an audit trail of every pay-rate change so I can answer "when did Jane last get a raise?" and surface anniversary review reminders.

**Acceptance criteria:**

1. THE SYSTEM SHALL create a new table `staff_pay_rates` with columns: `id` (uuid PK), `org_id` (uuid, FK organisations, NOT NULL), `staff_id` (uuid, FK staff_members, NOT NULL), `hourly_rate` (numeric(10,2), nullable), `overtime_rate` (numeric(10,2), nullable), `effective_from` (date, NOT NULL), `changed_by` (uuid, FK users, nullable), `change_reason` (text, nullable), `created_at` (timestamptz, default now()).
2. THE SYSTEM SHALL enable RLS on `staff_pay_rates` with a `tenant_isolation` policy `USING (org_id = current_setting('app.current_org_id', true)::uuid)`.
3. WHEN a staff is created with `hourly_rate` and/or `overtime_rate` set THE SYSTEM SHALL insert one `staff_pay_rates` row with `effective_from = now()::date` and `change_reason = 'initial_rate'`.
4. WHEN a PUT updates `hourly_rate` or `overtime_rate` to a different value THE SYSTEM SHALL insert a new `staff_pay_rates` row capturing the new values, the current user as `changed_by`, and `change_reason = 'rate_change'` (or whatever the user typed).
5. THE SYSTEM SHALL expose `GET /api/v2/staff/:id/pay-rates` returning `{ items: [...], total: N }` ordered by `effective_from DESC`. Frontend UI surfaces this on the Overview tab as a collapsible "Pay rate history" panel.

### R4. Minimum Wage Warning

**User story:** As an org admin, I want a clear warning when I save a staff with an hourly rate below the NZ minimum wage so I don't accidentally underpay.

**Acceptance criteria:**

1. THE SYSTEM SHALL add a new org-level setting `minimum_wage_threshold_nzd` (numeric, default 23.15) to the existing `org_settings` JSONB or `organisations` settings store.
2. WHEN the user types a hourly rate below the threshold on Overview tab THE SYSTEM SHALL show a red badge "Below NZ minimum wage ($23.15/hr)" inline.
3. WHEN the user clicks Save THE SYSTEM SHALL show a confirm modal "This rate is below the NZ minimum wage. Continue anyway?" — Save proceeds only after the user confirms, and a row is written to `audit_log` with `action='staff.minimum_wage_override'` and the user_id of who confirmed.
4. THE SYSTEM SHALL show a red badge on the Staff List view for any active staff with `hourly_rate < minimum_wage_threshold_nzd`.

### R5. Employment Agreement Upload Slot

**User story:** As an org admin, I want a single place to attach each staff's signed employment agreement, because keeping a signed copy is mandatory under ERA s64.

**Acceptance criteria:**

1. THE SYSTEM SHALL add an `employment_agreement_upload_id` column (uuid, FK to `uploads.id`) to `staff_members`.
2. THE SYSTEM SHALL render an upload slot on the Documents tab (or Overview tab — TBD in design) that accepts PDF/JPG/PNG up to 10 MB.
3. WHEN the user uploads a file THE SYSTEM SHALL POST to existing uploads endpoint, capture the returned `upload_id`, and PUT the staff record with `employment_agreement_upload_id`.
4. THE SYSTEM SHALL render a "View" link that opens a signed/decrypted URL.
5. THE SYSTEM SHALL show a counter on the Staff List header: "N staff without signed employment agreement on file" — gentle nag, not a save block.
6. WHEN a staff record is deleted permanently THE SYSTEM SHALL soft-detach the upload via existing uploads orphan-cleanup behaviour (no special handling here).

### R6. Probation, Visa Expiry, Anniversary Calendars

**User story:** As an org admin, I want to know when probation ends, when a visa is about to expire, and when a pay-review anniversary is coming up.

**Acceptance criteria:**

1. WHEN viewing the Staff List THE SYSTEM SHALL render a banner at the top showing **seven** counters (P1-N13: enumerated here in one place to keep `compliance_summary` shape unambiguous):
   - "N staff have probation ending in next 14 days" — `probation_end_date BETWEEN now() AND now() + interval '14 days' AND is_active=true`. Response key: `probation_ending_soon`.
   - "N staff have visa expiring in next 60 days" — `visa_expiry_date BETWEEN now() AND now() + interval '60 days' AND is_active=true AND residency_type IN ('work_visa','student_visa','other')`. Citizens and permanent residents are excluded from the count. Response key: `visa_expiring_soon`.
   - "N staff are due a pay review this month" — `last_pay_review_date IS NULL OR last_pay_review_date < (now() - interval '12 months')` AND `is_active=true`. Response key: `pay_review_due`.
   - **"N staff are below NZ minimum wage" (cross-ref R4.4)** — `hourly_rate IS NOT NULL AND hourly_rate < <org.minimum_wage_threshold_nzd> AND is_active=true`. Response key: `below_minimum_wage`.
   - **"N staff are missing an employment agreement" (cross-ref R5.5)** — `employment_agreement_upload_id IS NULL AND is_active=true`. Response key: `missing_agreement`.
   - **"N staff are missing an employee code" (G1)** — `employee_id IS NULL AND is_active=true`. Tooltip on the counter: *"Staff without an employee code cannot clock in or out at the kiosk in Phase 3. Set one now."* Response key: `missing_employee_id`.
   - **"N staff are missing an employment start date" (G3)** — `employment_start_date IS NULL AND is_active=true`. Tooltip: *"Phase 2 leave accrual requires every active staff to have an employment start date. Backfill before Phase 2 ships."* Response key: `missing_start_date`.
2. WHEN the counter is non-zero THE SYSTEM SHALL render a clickable badge that filters the staff list to that subset. Each filter is independent and persists in the URL query string.
3. THE SYSTEM SHALL add a `last_pay_review_date` column (date, nullable) to `staff_members`. Populated whenever a pay-rate change is saved with `change_reason = 'rate_change'`.
4. THE SYSTEM SHALL show a red dot indicator on each staff row that is missing `employee_id` OR `employment_start_date` (both indicators visible if both are missing). Hovering the dot shows a tooltip listing which fields are missing.

### R7. Roster Tab — Per-Staff Calendar

**User story:** As an org admin, I want to see one staff member's roster filtered down on the Roster tab so I don't have to scan the full org grid.

**Acceptance criteria:**

1. WHEN a user opens the Roster tab THE SYSTEM SHALL fetch `GET /api/v2/schedule?staff_id=:id&start=:weekStartIso&end=:weekEndIso` (verified path per `app/main.py:516`; query keys are `start` / `end`, not `from` / `to`). Response shape is `{ entries: [...], total: N }` — frontend consumes `res.data?.entries ?? []`.
2. THE SYSTEM SHALL render a week view (Mon–Sun) with this-week/prev/next buttons.
3. WHEN the user clicks "Add shift" THE SYSTEM SHALL open a drawer to create a new `schedule_entries` row for this staff with `entry_type='other'`, default times from `staff.shift_start`/`shift_end`.
4. WHEN the user clicks "Apply template" THE SYSTEM SHALL open a picker of `shift_templates` and create entries based on the chosen template.
5. WHEN the user clicks "Email this week's roster" THE SYSTEM SHALL trigger R8.
6. WHEN the user clicks "Send roster SMS" THE SYSTEM SHALL trigger R9.

### R8. Email Roster to Staff

**User story:** As an org admin, I want to email a staff member their week's roster with a single click.

**Acceptance criteria:**

1. THE SYSTEM SHALL add `POST /api/v2/staff/:id/email-roster` accepting body `{ week_start: 'YYYY-MM-DD' }` and returning `{ ok: true, message_id: '...' }` or `{ ok: false, reason: '...' }`.
2. THE SYSTEM SHALL refuse with HTTP 422 if `staff.email` is null or `weekly_roster_email_enabled` is false (with explicit `reason`).
3. WHEN the endpoint is called THE SYSTEM SHALL load all `schedule_entries` for that staff in the week, render a Jinja HTML template with the staff's locale/timezone, and call `send_email(db, EmailMessage(...), dlq_task_name='roster_email')`.
4. THE SYSTEM SHALL write an `audit_log` row with `action='roster.emailed'`.
5. THE SYSTEM SHALL only send the email if at least one schedule entry exists in the week — otherwise return HTTP 422 `reason='no_shifts_in_week'`.

### R9. SMS Roster to Staff

**User story:** As an org admin, I want to send an SMS summary with a tokenised link to the full schedule, because hourly staff don't read work email.

**Acceptance criteria:**

1. THE SYSTEM SHALL add `POST /api/v2/staff/:id/sms-roster` accepting body `{ week_start: 'YYYY-MM-DD' }` and returning `{ ok: true, message_id: '...' }` or `{ ok: false, reason: '...' }`.
2. THE SYSTEM SHALL refuse with HTTP 422 if `staff.phone` is null/blank or `weekly_roster_sms_enabled` is false.
3. THE SYSTEM SHALL compose a body using the template `"Kia ora {first_name}, your {week_label} roster: {N} shifts, {first_shift_summary}. Full schedule: {tokenised_link}"`.
   - **GSM-7 vs UCS-2 (G7):** the template above uses pure ASCII so it fits a single 160-character GSM-7 segment. However, a staff member's `first_name` may contain Māori macrons (`ā ē ī ō ū`) or other non-GSM-7 characters, which downgrades the entire SMS to UCS-2 (70 chars per segment).
   - THE SYSTEM SHALL detect non-GSM-7 characters in the composed body and:
     - If the body fits within UCS-2's 70-char limit → send as a single UCS-2 message.
     - If the body exceeds 70 chars in UCS-2 mode → send as a concatenated multi-part SMS (the `connexus_sms` provider already supports this; the spec just acknowledges the cost implication).
   - THE SYSTEM SHALL **never transliterate** Māori macrons to ASCII vowels — that's culturally inappropriate. Accept the multi-part billing.
   - THE SYSTEM SHALL log the segment count + encoding in the audit row's `after_value` JSONB (e.g. `{ "segments": 2, "encoding": "ucs2", "phone_number_masked": "*****1234" }`) for ops visibility. (P1-N12: `audit_log` has no `metadata` column — `after_value` is the right field.)
4. THE SYSTEM SHALL generate a tokenised viewer link (similar pattern to `app/modules/portal/service.py` portal tokens) that expires 30 days after issue and renders a read-only HTML schedule. No login required.
5. THE SYSTEM SHALL route the SMS through the existing `connexus_sms` provider via the configured fallback chain.
6. THE SYSTEM SHALL write an `audit_log` row with `action='roster.sms_sent'`.
7. **Token lifecycle (G4):** WHEN a staff member is deactivated (R12 `staff.deactivated`) OR terminated (R12 `staff.terminated`) THE SYSTEM SHALL immediately expire all of that staff's `staff_roster_view_tokens` rows by setting `expires_at = now()`. Any subsequent GET to a previously-valid token returns HTTP 410 Gone with body `{ "detail": "token_expired_staff_deactivated" }`. Audit row `roster.tokens_revoked` is written with `{ staff_id, tokens_revoked_count }` in `after_value`.
8. **Rate limit on public viewer (G5):** the unauthenticated `GET /api/v2/public/staff-roster/:token` endpoint SHALL be subject to a per-IP rate limit of **30 requests per minute**, configured by adding a new conditional block to `_apply_rate_limits` in `app/middleware/rate_limit.py` mirroring the existing HA-heartbeat pattern (lines 252-265). On 429, the standard `Retry-After` header is returned. (P1-N10: middleware has no "policy file" — uses hardcoded path-prefix conditionals.)

### R10. Auto Friday-Afternoon Roster Broadcast (Scheduled Task)

**User story:** As an org admin, I want every staff with `weekly_roster_email_enabled` (or sms equivalent) to automatically receive next-week's roster on Friday afternoons.

**Acceptance criteria:**

1. THE SYSTEM SHALL add a new entry `weekly_roster_broadcast` to `app/tasks/scheduled.py`, running daily at 16:00 in the org's local timezone but only firing on Fridays.
2. WHEN the task runs THE SYSTEM SHALL iterate over all active orgs that have `staff_management` module enabled, then for each staff with `weekly_roster_email_enabled=true` send the email per R8 logic, and for each with `weekly_roster_sms_enabled=true` send the SMS per R9 logic.
3. THE SYSTEM SHALL wrap each per-staff send in a `db.begin_nested()` SAVEPOINT so one staff's failure does not poison the batch (per `performance-and-resilience.md`).
4. THE SYSTEM SHALL respect the existing scheduler Redis SETNX lock (single-worker execution per ISSUE-164).
5. THE SYSTEM SHALL log per-staff success/failure with `org_id` and `staff_id` so admins can grep for failures.

### R11. Module Registration + Setup Question

**User story:** As a new org going through the setup wizard, I should see "Do you employ staff or contractors that you need to roster and pay?" and have Staff Management auto-enabled if I answer yes.

**Acceptance criteria:**

1. THE SYSTEM SHALL insert into `module_registry` (idempotent, `ON CONFLICT (slug) DO NOTHING`) one row with `slug='staff_management'`, `display_name='Staff Management'`, `category='operations'`, `is_core=false`, `dependencies='[]'`, `incompatibilities='[]'`, `status='available'`, `setup_question='Do you employ staff or contractors that you need to roster and pay?'`, `setup_question_description='Manage employee records, rosters, leave balances, clock-in/out, and weekly hours approval — built to NZ employment law.'`.
2. THE SYSTEM SHALL also insert `payroll` row with `dependencies='["staff_management"]'`, `setup_question='Would you like to generate payslips for your staff inside this app?'`. (Payroll itself ships in Phase 4 — Phase 1 only registers the module shell so the setup wizard works once Phase 4 lands.)
3. THE SYSTEM SHALL update **all unarchived subscription plans** (P1-N2: STAFF-001 resolved — modules ship enabled in every plan; per-org disablement is the gate) to include both `staff_management` and `payroll` in `enabled_modules` (idempotent JSONB merge: `WHERE is_archived = false`).
4. THE SYSTEM SHALL insert mirror rows into `feature_flags` for both keys with `default_value=true` (P1-N14: matches the policy from migration `0171_fix_feature_flag_defaults.py` — module gate is the real lever; flag is a passive mirror for the admin GUI), `category='operations'`, `access_level='all_users'`, `dependencies='[]'::jsonb`, `is_active=true`, `display_name` populated (NOT NULL column). Idempotent on `key`. (P1-N1: `feature_flags` has no `scope` or `default_enabled` column — real names are `default_value`, plus `display_name` is required.)
5. THE SYSTEM SHALL gate every staff-management UI surface (tabbed view, scheduled task, new endpoints) behind `ModuleService.is_enabled(org_id, 'staff_management')`. When disabled, the new sub-feature endpoints return HTTP **404** `{"detail": "not_enabled", "module": "staff_management"}` and the frontend swaps to the legacy single-form view. (P1-N4: 404 not 403 here is deliberate — the broader `staff` module path-prefix gate already returns 403 via middleware; this finer-grained `staff_management` gate uses 404 to hide the new sub-endpoints without re-asserting access denial. Users never see a 404 in the UI because the frontend pre-checks the flag and renders `LegacyStaffDetail` instead.)

### R12. Audit Logging

THE SYSTEM SHALL call `app/core/audit.py::write_audit_log(session, action=..., entity_type=...)` (which writes to the `audit_log` table) for every state change in this phase. Action names per the existing audit taxonomy:

- `staff.created`
- `staff.updated`
- `staff.deactivated`
- `staff.terminated` (when `employment_end_date` is set)
- `staff.minimum_wage_override`
- `staff.pay_rate_changed`
- `staff.employment_agreement_uploaded`
- `roster.emailed`
- `roster.sms_sent`
- `roster.tokens_revoked` (G4 — written by the deactivation/termination flow with `{ staff_id, tokens_revoked_count }` in `after_value`)

### R13. End-to-End Test Script

**Acceptance criteria:**

1. THE SYSTEM SHALL ship `scripts/test_staff_employment_record_e2e.py` per `feature-testing-workflow.md`.
2. The script SHALL: log in as an org_admin, create staff with `TEST_E2E_` prefix, set tax code + IRD + KiwiSaver + bank account + employment_start, verify masked response, fetch detail, update pay rate (verify history row), upload signed agreement, send roster email, send roster SMS, exercise minimum-wage warning override path, clean up in `finally` block.
3. The script SHALL exit non-zero if any assertion fails.

### R14. Versioning + Issue IDs

**Acceptance criteria:**

1. THE SYSTEM SHALL bump `pyproject.toml`, `frontend/package.json`, `mobile/package.json` from 1.13.0 → 1.14.0 in sync.
2. THE SYSTEM SHALL add a `CHANGELOG.md` entry under `## [1.14.0]` listing the Phase 1 deliverables.
3. THE SYSTEM SHALL allocate `STAFF-001` through `STAFF-008` placeholder IDs in `docs/ISSUE_TRACKER.md` per the open-questions list in §13 of the source plan.
4. Any bug discovered during implementation SHALL get a `ISSUE-NNN` entry per `issue-tracking-workflow.md`. Phase 1 begins with the next free ID after 168.

## Non-Goals (Phase 1)

- Leave types, leave balances, leave accrual — Phase 2.
- Public-holiday engine (s40A, OWD detection) — Phase 2.
- Casual 8% holiday-pay-as-you-go — Phase 2 storage, Phase 4 calc.
- Clock-in / clock-out / kiosk flow / photo capture — Phase 3.
- Hours approval / scheduled-vs-actual variance — Phase 3.
- Payslips — Phase 4.
- Bank-file export, IRD export, dashboard widgets — Phase 5.
- The "Documents" tab UI is implemented as a single upload slot for the employment agreement only. Multi-document categories are out of scope.
- **Mobile-app changes (G6).** Phase 1 ships **no changes** to `mobile/src/`. The mobile staff list + detail screens continue to render their current fieldset; the new Phase 1 fields (tax_code, IRD, KiwiSaver, bank, residency_type, etc.) are visible on web only. The mobile API client will still parse responses correctly because all new fields are nullable. A future Phase 1.5 follow-up will add mobile rendering for the new fields and the compliance counters. Verified post-merge: load `/mobile` staff list and detail with a Phase 1-enabled org → no crash, existing fields still show.
- **Phase 2 prerequisite for existing staff (G3).** Phase 1 leaves `employment_start_date` NULL for all currently-existing staff records. **Org admins MUST backfill this column before Phase 2 ships** — the leave-accrual engine in Phase 2 will skip any staff with a NULL start date (no annual-leave accrual, no sick-leave 6-month gate, no anniversary). The Phase 1 compliance banner counter "N staff are missing an employment start date" surfaces this gap. We deliberately do NOT auto-populate with a default value (e.g. "today") because that would silently grant fictitious tenure and skew leave entitlements. Phase 2's release notes will reiterate the backfill requirement.

## Open Questions Carried Forward

- **STAFF-001:** Default subscription plan inclusion (yes per R11.3, but is "default" the right slug to target — confirm in design).
- **STAFF-006:** Kiosk routing (in-scope only at Phase 3, but the `self_service_clock_enabled` flag added in Phase 1 is the policy hinge).

## Verification Gates

Before merging, all checkboxes in `docs/future/staff-management-system.md` §12 (Pre-merge gate checklist) must be ticked. The `gap-analysis.md` in this spec folder will be generated post-implementation listing any unmet criteria with reasons.
