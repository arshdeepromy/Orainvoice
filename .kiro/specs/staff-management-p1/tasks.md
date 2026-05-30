# Staff Management Phase 1 — Tasks

Each task is independently mergeable, has a `**Verify:**` line per `implementation-completeness-checklist.md` Rule 9, and references back to a requirement.

## Workstream A — Backend schema + module registration

- [ ] **A1. Write Alembic migration `0203_staff_phase1_schema.py`**
  - Adds the 22 new columns to `staff_members` with `ADD COLUMN IF NOT EXISTS`.
  - Adds CHECK constraints for `employment_type` and `tax_code` enums (drop+recreate idempotent).
  - Creates `staff_pay_rates` table with `CREATE TABLE IF NOT EXISTS`, RLS policy, FK to `organisations`/`staff_members`/`users`.
  - Inserts module_registry rows for `staff_management` and `payroll` with `ON CONFLICT (slug) DO NOTHING`.
  - Inserts mirror feature_flags rows.
  - Updates `subscription_plans.enabled_modules` JSONB to include both slugs (idempotent set-union).
  - Provides downgrade that drops columns + table + module rows + flag rows.
  - **Refs:** R2, R3, R11.
  - **Verify:** `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head` runs cleanly. Then in psql: `SELECT slug FROM module_registry WHERE slug IN ('staff_management','payroll')` returns 2 rows; `SELECT key FROM feature_flags WHERE key IN ('staff_management','payroll')` returns 2 rows; `\d+ staff_members` shows the 22 new columns; `\d+ staff_pay_rates` shows the table with RLS.

- [ ] **A2. Write Alembic migration `0204_staff_phase1_indexes.py`**
  - 7 indexes via `CREATE INDEX CONCURRENTLY ... IF NOT EXISTS` inside `op.get_context().autocommit_block()`.
  - Mirrors the canonical 0202 template exactly — use `_run_outside_tx` helper.
  - Downgrade drops the same indexes via `DROP INDEX CONCURRENTLY IF EXISTS`.
  - **Refs:** Performance-and-resilience steering, R6.
  - **Verify:** alembic upgrade head; `SELECT indexname FROM pg_indexes WHERE indexname LIKE 'idx_staff_%'` returns the 7 new indexes; `EXPLAIN SELECT * FROM staff_members WHERE org_id=$1 AND probation_end_date < now()+interval '14 days' AND is_active=true` shows index scan on `idx_staff_probation_end`.

## Workstream B — Backend ORM + schemas + service

- [ ] **B1. Extend `app/modules/staff/models.py`**
  - Add the 22 mapped columns to `StaffMember` matching the migration.
  - Add new `StaffPayRate` model with FKs to `StaffMember` and `User`.
  - Encrypted columns typed as `Mapped[bytes | None]` with `LargeBinary`.
  - **Refs:** R2, R3.
  - **Verify:** `docker compose exec app python -c "from app.modules.staff.models import StaffMember, StaffPayRate; print(StaffMember.__table__.columns.keys()); print(StaffPayRate.__table__.columns.keys())"` lists every new column.

- [ ] **B2. Create `app/modules/staff/security.py` with masking helpers**
  - `mask_ird`, `mask_bank_account`, `is_masked_ird`, `is_masked_bank` per design §3.4.
  - Add Hypothesis property tests in `tests/unit/test_staff_phase1_mask.py`: any input string → mask output never contains more than 3 IRD digits / 4 bank digits.
  - **Refs:** R2.
  - **Verify:** `docker compose exec app pytest tests/unit/test_staff_phase1_mask.py -v` → all green.

- [ ] **B3. Extend `app/modules/staff/schemas.py`**
  - Add `tax_code`, `ird_number`, `student_loan`, `kiwisaver_*`, `bank_account_number`, employment dates/type, std hours, contacts, photos, opt-in flags, `minimum_wage_override` to `StaffMemberCreate` and `StaffMemberUpdate`.
  - Add `StaffPayRateResponse` and `StaffPayRateListResponse`.
  - Add `RosterEmailRequest`, `RosterSmsRequest`, `RosterSendResponse`.
  - Validators reject mask-pattern values on UPDATE so the service-layer mask-detection is the real guard but client gets immediate feedback.
  - Output schema masks IRD + bank via field validators (or a custom serializer).
  - **Refs:** R2, R8, R9.
  - **Verify:** `pytest tests/unit/test_staff_schemas.py -v` (extend existing test file) covers happy + mask round-trip cases.

- [ ] **B4. Extend `StaffService.create_staff` and `update_staff`**
  - Encrypt IRD + bank on save (skip when value is masked or unchanged).
  - Auto-set `probation_end_date` when start_date provided and probation_end empty.
  - Insert initial `staff_pay_rates` row on create (when rate present).
  - On update: if rate changed, insert new pay-rate row + update `last_pay_review_date`.
  - Apply minimum-wage check; raise `MinimumWageBelowThresholdError` (new exception type) when below threshold and `override` flag absent.
  - Mask IRD + bank on outbound serialisation.
  - Always call `await db.refresh(obj)` after `db.flush()`.
  - **Refs:** R2, R3, R4.
  - **Verify:** `pytest tests/unit/test_staff_service_phase1.py -v` covers: create with IRD → bytea persisted → response masked; update with masked IRD → DB ciphertext unchanged; rate change → pay-rate row written; below-min-wage without override → 422.

- [ ] **B5. Add `StaffService.get_pay_rate_history`**
  - Selects `StaffPayRate` rows for staff_id, joins users to resolve email of changer.
  - Returns `(items, total)`.
  - **Verify:** unit test covers ordering DESC + paginated total count.

- [ ] **B6. Add minimum-wage threshold to org settings cache path**
  - Reuse the existing `get_org_settings` Redis-cached read (post quick-win #6) — extend it to surface `minimum_wage_threshold_nzd` with default 23.15.
  - No new endpoint — the existing org-settings PATCH writes through to invalidate the cache.
  - **Refs:** R4.
  - **Verify:** save `minimum_wage_threshold_nzd: 25.00` via existing org-settings UI → service reads new value within 60s.

## Workstream C — Backend API endpoints

- [ ] **C1. Module-gate the existing staff endpoints**
  - Add `_require_staff_management_module(request, db)` helper that calls `ModuleService.is_enabled` and raises 404 `not_enabled` when disabled.
  - Apply to `POST /staff`, `PUT /staff/:id`, `GET /staff/:id`, list endpoint, and all new endpoints below.
  - List endpoint stays accessible (legacy view) when module disabled — only the new fields are stripped from response.
  - **Refs:** R11.5.
  - **Verify:** disable module for a test org; POST `/api/v2/staff` → 404 `not_enabled`. Re-enable → 201.

- [ ] **C2. Add `GET /api/v2/staff/:id/pay-rates`**
  - Returns `{ items: [...], total: N }`.
  - Pagination via existing `?offset=&limit=` pattern.
  - **Refs:** R3.5.
  - **Verify:** `curl /api/v2/staff/<id>/pay-rates` after a rate change → returns the history row at top.

- [ ] **C3. Add `POST /api/v2/staff/:id/email-roster`**
  - Body `{ week_start: 'YYYY-MM-DD' }`.
  - Refuses with 422 reason when staff.email is null OR `weekly_roster_email_enabled=false` OR no shifts in week.
  - Renders new template `app/templates/email/staff_roster.html` (Jinja) with this-week's `schedule_entries`.
  - Calls `send_email(db, message, dlq_task_name='roster_email', dlq_task_args={...})`.
  - Writes `audit_logs` action='roster.emailed'.
  - Returns `{ ok, message_id, reason }`.
  - **Refs:** R8.
  - **Verify:** trigger from API → check email_provider sent log → received in test inbox.

- [ ] **C4. Create `app/integrations/sms_sender.py`**
  - New thin module mirroring `email_sender.py` shape.
  - `async def send_sms(db, *, to_phone, body, dlq_task_name=None) -> SmsSendResult`.
  - Loads active SMS provider (`SmsVerificationProvider WHERE is_active=true ORDER BY priority`), instantiates `ConnexusSmsClient`, calls `send`.
  - On exception with DLQ → `DeadLetterService.store_failed_task`.
  - Returns `SmsSendResult(ok, message_id, provider_key, reason)`.
  - **Refs:** R9 prerequisite.
  - **Verify:** `pytest tests/unit/test_sms_sender.py` covers happy + provider-down DLQ paths.

- [ ] **C5. Add `staff_roster_view_tokens` table + service**
  - New table: `id uuid PK, org_id uuid, staff_id uuid, token text UNIQUE, week_start date, expires_at timestamptz, created_at timestamptz`.
  - RLS + tenant_isolation policy.
  - Add to migration 0203 (don't split — same phase).
  - Index `(token)` UNIQUE for the public lookup.
  - Service `get_or_create_viewer_token(db, staff_id, week_start)` returns the token, reuses existing row when present + not expired.
  - **Refs:** R9.4.
  - **Verify:** call helper twice for same staff+week → same token.

- [ ] **C6. Add `POST /api/v2/staff/:id/sms-roster`**
  - Body `{ week_start }`.
  - Refuses with 422 when `phone IS NULL OR weekly_roster_sms_enabled=false OR no shifts`.
  - Composes 160-char body via helper `compose_roster_sms_body(staff, entries, viewer_url)`.
  - Calls `send_sms(db, to_phone=staff.phone, body=..., dlq_task_name='roster_sms')`.
  - Writes `audit_logs` action='roster.sms_sent'.
  - **Refs:** R9.
  - **Verify:** trigger via curl → check `notification_log` row + `audit_logs` row + receive on test phone.

- [ ] **C7. Add `GET /api/v2/public/staff-roster/:token`**
  - No auth.
  - Validates token + expiry.
  - Returns `{ staff_name, week_start, week_end, entries: [...] }`.
  - Frontend public viewer page renders this read-only.
  - **Refs:** R9.4.
  - **Verify:** open the link in incognito → schedule renders.

- [ ] **C8. Add `POST /api/v2/staff/:id/employment-agreement`**
  - Accepts JSON `{ upload_id }` from the existing `/uploads` POST flow.
  - Validates the upload exists, belongs to the org.
  - Sets `staff_members.employment_agreement_upload_id`.
  - Writes `audit_logs` action='staff.employment_agreement_uploaded'.
  - Returns updated staff (with masked PII).
  - **Refs:** R5.
  - **Verify:** upload via Documents tab → DB column populated → "View" link returns signed URL.

- [ ] **C9. Extend `GET /api/v2/staff` response with `compliance_summary`**
  - Five COUNT(*) FILTER aggregates on the org's staff list (probation_ending_soon, visa_expiring_soon, missing_agreement, pay_review_due, below_minimum_wage).
  - Returns alongside `items` + `total`.
  - **Refs:** R6.
  - **Verify:** check the response shape — `compliance_summary` keys all present and integer-typed.

- [ ] **C10. Extend POST/PUT for minimum-wage gate**
  - When body contains `hourly_rate < threshold`, 422 with `{detail: 'minimum_wage_below_threshold', threshold: 23.15}`.
  - When body also contains `minimum_wage_override: true`, accept + write `audit_logs` action='staff.minimum_wage_override' with the override user_id.
  - **Refs:** R4.
  - **Verify:** unit test covers both paths.

## Workstream D — Scheduled task

- [ ] **D1. Register `weekly_roster_broadcast` in `app/tasks/scheduled.py`**
  - Runs every 30 minutes (existing tick).
  - Body short-circuits unless current local time in org timezone is Friday 16:00–16:29.
  - For each org with `staff_management` module enabled:
    - Iterates active staff with `weekly_roster_email_enabled=true OR weekly_roster_sms_enabled=true`.
    - Each per-staff send wrapped in `db.begin_nested()` SAVEPOINT.
  - Logs per-staff success/failure with org_id + staff_id.
  - Respects existing scheduler Redis SETNX lock.
  - **Refs:** R10.
  - **Verify:** force timezone to "Pacific/Auckland", patch now() to a Friday 16:05, run task once → grep logs for `weekly_roster_broadcast: org=<id> staff=<id> email=ok`.

## Workstream E — Frontend tabbed shell

- [ ] **E1. Create `useTabHash` hook**
  - At `frontend/src/hooks/useTabHash.ts`. Reads/writes `window.location.hash`. Falls back to default tab on mismatch.
  - **Verify:** unit test in `__tests__/useTabHash.test.tsx`.

- [ ] **E2. Refactor `StaffDetail.tsx` into tabbed shell**
  - Module-gated: when disabled, renders `<LegacyStaffDetail />` (the current single-form file moved to `frontend/src/pages/staff/_legacy/StaffDetail.legacy.tsx`).
  - When enabled, renders header + tab strip + `<Suspense>` + lazy tab components.
  - Discard-changes guard wraps tab transitions.
  - **Refs:** R1.
  - **Verify:** Browser test: open `/staff/<id>` → tabs visible → click each tab → URL hash updates → refresh → same tab loads.

- [ ] **E3. Build `OverviewTab.tsx`**
  - Sections: Personal, Employment, Tax & Pay, Schedule (existing WorkSchedule), Clock-in & roster delivery, Skills.
  - Inputs respect `is_masked_ird`/`is_masked_bank` heuristic — when the user clears the field, sends `null` (which the backend skips); when typed fresh, sends raw plaintext.
  - PayRateHistoryPanel collapsible at bottom of Tax & Pay section.
  - Uses `?.` and `?? []` everywhere on API data.
  - All `useEffect` API calls have AbortController cleanup.
  - **Refs:** R2, R3, R4, R6.
  - **Verify:** Browser test — fill staff form, save, reload, fields populate from masked response, type new IRD value, save, DB shows new ciphertext.

- [ ] **E4. Build `RosterTab.tsx`**
  - Embeds existing `ScheduleCalendar` filtered to `staff_id` (extend its props if needed: `focusStaffId?: string`).
  - Toolbar: WeekNavigator, Add shift, Apply template, Email roster, Send roster SMS.
  - Calls `POST /:id/email-roster` and `POST /:id/sms-roster` with the active week.
  - **Refs:** R7, R8, R9.
  - **Verify:** Browser test — click Email roster → toast shows; check email inbox for content.

- [ ] **E5. Build `DocumentsTab.tsx`**
  - Single section "Employment agreement".
  - Drag-drop or file picker → POST to `/uploads` → POST to `/staff/:id/employment-agreement` → refresh.
  - Shows current filename + View + Replace.
  - **Refs:** R5.
  - **Verify:** Browser test — upload PDF → row updated → View opens signed URL.

- [ ] **E6. Build `MinimumWageWarningModal.tsx`**
  - Props: `threshold`, `proposed`, `onCancel`, `onConfirm`.
  - On Confirm → caller re-submits with `minimum_wage_override: true`.
  - **Refs:** R4.
  - **Verify:** unit test in `__tests__/MinimumWageWarningModal.test.tsx`.

- [ ] **E7. Build `PayRateHistoryPanel.tsx`**
  - Fetches `/staff/:id/pay-rates` lazily (only when expanded).
  - Renders read-only list: effective_from, hourly, overtime, change reason, by-email.
  - **Refs:** R3.5.
  - **Verify:** unit test renders mock data.

- [ ] **E8. Build `ComplianceBanner` for StaffList.tsx**
  - Reads `compliance_summary` from list response.
  - Renders 5 clickable counters that toggle URL filter chips.
  - **Refs:** R6.
  - **Verify:** Browser test — counter increments, click filters list, X removes filter.

- [ ] **E9. Public `StaffRosterPublicView.tsx`**
  - Route `/public/staff-roster/:token` (no auth).
  - Fetches `/api/v2/public/staff-roster/:token`, renders read-only week view.
  - 404 / expired token shows clear message.
  - **Refs:** R9.4.
  - **Verify:** Browser test in incognito.

## Workstream F — Tests + verification

- [ ] **F1. E2E script `scripts/test_staff_employment_record_e2e.py`**
  - Login as org_admin → create TEST_E2E_ staff with full payload → verify masked response → fetch detail → update pay rate → verify history → upload agreement → trigger email roster → trigger SMS roster (skip if no phone) → exercise min-wage override → cleanup all in `finally`.
  - Idempotent prefix-cleanup at the start.
  - **Refs:** R13.
  - **Verify:** `python scripts/test_staff_employment_record_e2e.py` exits 0 with "passed: N, failed: 0".

- [ ] **F2. Unit-test files**
  - `tests/unit/test_staff_phase1_mask.py`
  - `tests/unit/test_staff_phase1_minimum_wage.py`
  - `tests/unit/test_staff_pay_rate_history.py`
  - `tests/unit/test_staff_phase1_roster_delivery.py`
  - `tests/unit/test_sms_sender.py`
  - `tests/unit/test_staff_phase1_endpoints.py`
  - **Verify:** `pytest tests/unit/ -k 'phase1 or sms_sender' -v` → all green.

- [ ] **F3. Module + flag rows verified post-migration**
  - Run on dev: `SELECT slug, setup_question FROM module_registry WHERE slug IN ('staff_management','payroll')` → 2 rows.
  - `SELECT key FROM feature_flags WHERE key IN ('staff_management','payroll')` → 2 rows.
  - `SELECT enabled_modules FROM subscription_plans WHERE NOT is_archived` → all rows include both slugs.

## Workstream G — Versioning + docs

- [ ] **G1. Bump versions**
  - `pyproject.toml` 1.13.0 → 1.14.0.
  - `frontend/package.json` same bump.
  - `mobile/package.json` same bump (even though no mobile changes — keeps stack in sync).
  - **Refs:** R14.
  - **Verify:** `git grep '1.13.0'` after the change returns no results except CHANGELOG history entries.

- [ ] **G2. Update `CHANGELOG.md`**
  - Add `## [1.14.0]` section.
  - Bullet list: tabbed staff detail; full employment record (tax code, IRD, KiwiSaver, bank, employment dates, probation, visa); pay rate history; min-wage warning; compliance counters; roster email + SMS delivery; module registration for staff_management + payroll.
  - **Refs:** R14.

- [ ] **G3. Allocate STAFF-001..STAFF-008 placeholders in `docs/ISSUE_TRACKER.md`**
  - One-line entries with the question + "Awaiting decision before Phase X".
  - **Refs:** R14.3.

- [ ] **G4. Update `docs/future/staff-management-system.md`**
  - Mark Phase 1 status `In progress` once work begins; flip to `Shipped — see CHANGELOG 1.14.0` once merged.

## Pre-merge gate (per source plan §12)

Tick before opening the merge PR:

**Code completeness**
- [ ] alembic upgrade head runs cleanly
- [ ] All index migrations use CREATE INDEX CONCURRENTLY
- [ ] Zero `op.create_index(...)` calls
- [ ] All new tables have RLS + tenant_isolation policy
- [ ] Module registry inserts include setup_question + setup_question_description
- [ ] feature_flags rows added alongside
- [ ] Subscription plan enabled_modules updated

**API contract**
- [ ] Every new service-dict field has a matching Pydantic schema field
- [ ] All list endpoints return `{ items: [...], total: N }`
- [ ] No new env vars introduced
- [ ] All emails route through send_email
- [ ] All SMS routes through new `send_sms` (which uses connexus_sms)
- [ ] audit_logs entries written for every state change

**Frontend**
- [ ] Every API call uses `?.` + `?? []` / `?? 0`
- [ ] No `as any`
- [ ] Every useEffect with API call has AbortController cleanup
- [ ] All buttons 44×44 minimum (mobile-app rule, in case any of these screens render on mobile breakpoint)
- [ ] No "Coming soon" placeholders — Leave/Hours/Payslips tabs ARE NOT RENDERED in Phase 1 (they're only added in their respective phases)
- [ ] Empty / loading / error states all implemented

**Testing**
- [ ] E2E script ships with prefix `TEST_E2E_` + cleanup
- [ ] Hypothesis property tests on mask helpers
- [ ] Unit tests for every new service method

**Security**
- [ ] PII bytea encrypted via envelope_encrypt
- [ ] Mask-pattern detection on save
- [ ] No plaintext IRD/bank in API responses
- [ ] Migration `0203` includes `ENABLE ROW LEVEL SECURITY` + `CREATE POLICY tenant_isolation` for `staff_pay_rates` AND `staff_roster_view_tokens`

**Versioning**
- [ ] pyproject.toml + frontend/package.json + mobile/package.json all 1.14.0
- [ ] CHANGELOG.md updated

**Browser test**
- [ ] Tabbed staff detail loads and switches tabs
- [ ] Pay rate edit writes a history row
- [ ] Min-wage modal fires + override audit log written
- [ ] Email roster sends successfully
- [ ] SMS roster sends successfully
- [ ] Employment agreement upload persists
- [ ] Public viewer-token URL renders read-only schedule

The phase is NOT done until every box is ticked. Any item that can't be ticked goes into `gap-analysis.md` with the reason.
