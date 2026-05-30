# Staff Management Phase 1 — Tasks

Each task is independently mergeable, has a `**Verify:**` line per `implementation-completeness-checklist.md` Rule 9, and references back to a requirement.

## Workstream A — Backend schema + module registration

- [ ] **A1. Write Alembic migration `0203_staff_phase1_schema.py`**
  - Adds **23 new columns** to `staff_members` with `ADD COLUMN IF NOT EXISTS` (the previous 22 plus `residency_type` per G2).
  - Adds CHECK constraints for `employment_type`, `tax_code`, and `residency_type` enums (each drop+recreate idempotent). `residency_type` enum: `'citizen' | 'permanent_resident' | 'work_visa' | 'student_visa' | 'other'`, default `'citizen'`.
  - Creates `staff_pay_rates` table with `CREATE TABLE IF NOT EXISTS`, RLS policy, FK to `organisations`/`staff_members`/`users`.
  - Creates `staff_roster_view_tokens` table per design §3.1.1 with `CREATE TABLE IF NOT EXISTS`, RLS policy, **and `ON DELETE CASCADE` on both `org_id` and `staff_id` FKs (G8)**. Includes the `UNIQUE (staff_id, week_start)` constraint for the get-or-create-token upsert pattern.
  - Inserts module_registry rows for `staff_management` and `payroll` with `ON CONFLICT (slug) DO NOTHING`.
  - Inserts mirror feature_flags rows.
  - Updates `subscription_plans.enabled_modules` JSONB to include both slugs (idempotent set-union).
  - Provides downgrade that drops both new tables + columns + constraints + module rows + flag rows.
  - **Refs:** R2 (incl. residency_type), R3, R11, G2, G8.
  - **Verify:** `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head` runs cleanly. Then in psql: `SELECT slug FROM module_registry WHERE slug IN ('staff_management','payroll')` returns 2 rows; `SELECT key FROM feature_flags WHERE key IN ('staff_management','payroll')` returns 2 rows; `\d+ staff_members` shows the **23 new columns** (incl. `residency_type`); `\d+ staff_pay_rates` shows the table with RLS; `\d+ staff_roster_view_tokens` shows the table with RLS and ON DELETE CASCADE on both FKs (visible in `\d+` output as `Foreign-key constraints: ... ON DELETE CASCADE`); `SELECT constraint_name FROM information_schema.check_constraints WHERE constraint_name LIKE 'ck_staff_residency_type'` returns 1 row.

- [ ] **A2. Write Alembic migration `0204_staff_phase1_indexes.py`**
  - **10 indexes** via `CREATE INDEX CONCURRENTLY ... IF NOT EXISTS` inside `op.get_context().autocommit_block()`. The 7 from design §3.2 plus:
    - `idx_staff_missing_employee_id` partial: `ON staff_members (org_id) WHERE is_active=true AND employee_id IS NULL` — supports the G1 compliance counter.
    - `idx_staff_missing_start_date` partial: `ON staff_members (org_id) WHERE is_active=true AND employment_start_date IS NULL` — supports the G3 counter.
    - `idx_staff_roster_view_tokens_token` UNIQUE: `ON staff_roster_view_tokens (token)` — public viewer lookup is on token only; needs to be O(1).
  - Mirrors the canonical 0202 template exactly — use `_run_outside_tx` helper.
  - Downgrade drops the same indexes via `DROP INDEX CONCURRENTLY IF EXISTS`.
  - **Refs:** Performance-and-resilience steering, R6, G1, G3, G8.
  - **Verify:** alembic upgrade head; `SELECT indexname FROM pg_indexes WHERE indexname LIKE 'idx_staff_%'` returns 10 indexes; `EXPLAIN SELECT count(*) FROM staff_members WHERE org_id=$1 AND is_active=true AND employee_id IS NULL` shows index scan on `idx_staff_missing_employee_id`; same shape for start_date.

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
  - **Extend the `SETTINGS_JSONB_KEYS` allow-list at `app/modules/organisations/service.py:198`** to include `minimum_wage_threshold_nzd`. This is mandatory: `update_org_settings` iterates this set and silently drops any kwarg not in it, so without this step the Settings PATCH UI would never persist the threshold.
  - Reuse the existing `get_org_settings` Redis-cached read (post quick-win #6) — once the key is in `SETTINGS_JSONB_KEYS`, it surfaces automatically on every read.
  - Default value when missing from JSONB: `23.15`. Surface this default at the call-sites that read the value (compliance counter SQL in C9, save-time check in C10) — there's no need to backfill `23.15` into existing org rows.
  - No new endpoint — the existing org-settings PATCH writes through to invalidate the cache (already wired in `update_org_settings` per ISSUE-165).
  - **Refs:** R4.
  - **Verify:** save `minimum_wage_threshold_nzd: 25.00` via existing org-settings UI → service reads new value within the cache TTL (<60s); cache key is invalidated immediately on PATCH so the read sees 25.00 within milliseconds in practice.

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
  - New table per design §3.1.1: `id uuid PK, org_id uuid REFERENCES organisations(id) ON DELETE CASCADE, staff_id uuid REFERENCES staff_members(id) ON DELETE CASCADE (G8), token text UNIQUE, week_start date, expires_at timestamptz, created_at timestamptz`. Unique on `(staff_id, week_start)` for upsert.
  - RLS + tenant_isolation policy.
  - Add to migration 0203 (don't split — same phase). The unique index on `token` is in 0204 (CONCURRENTLY pack, A2).
  - Service `get_or_create_viewer_token(db, staff_id, week_start)` returns the token, reuses existing row when present + not expired.
  - **Refs:** R9.4, G8.
  - **Verify:** call helper twice for same staff+week → same token; hard-delete the staff via `DELETE /staff/:id/permanent` → query `staff_roster_view_tokens WHERE staff_id=:id` returns 0 rows (cascade verified).

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
  - Validates token + expiry. Distinguishes three failure modes:
    - Token doesn't exist → HTTP 404 `{ "detail": "token_not_found" }`.
    - Token exists but `expires_at <= now()` AND was deliberately revoked by deactivation flow (G4) → HTTP 410 Gone `{ "detail": "token_expired_staff_deactivated" }`.
    - Token exists but expired by natural 30-day TTL → HTTP 410 Gone `{ "detail": "token_expired" }`.
  - Returns `{ staff_name, week_start, week_end, entries: [...] }` on success.
  - **Per-IP rate limit of 30 req/min applied (G5).** Implementation: `app/middleware/rate_limit.py` does NOT have a "policy map" data structure today — it uses hardcoded path-prefix conditionals inside `_apply_rate_limits` (e.g., the HA-heartbeat block at lines 252-265). Add a NEW conditional block following the same pattern: `_PUBLIC_STAFF_ROSTER_PATH_PREFIX = "/api/v2/public/staff-roster/"` constant + `if path.startswith(_PUBLIC_STAFF_ROSTER_PATH_PREFIX): ...` block keyed `rl:public_staff_roster:ip:{client_ip}` at 30/min, returning 429 with `Retry-After` header on breach.
  - Frontend public viewer page renders this read-only and shows the right error UI per design §9.
  - **Refs:** R9.4, R9.8, G5.
  - **Verify:** open the link in incognito → schedule renders. Hammer with `for i in $(seq 1 35); do curl -s -o /dev/null -w '%{http_code}\n' /api/v2/public/staff-roster/<token>; done` → first ~30 return 200, then 429 with `Retry-After` header. Deactivate the staff → next request returns 410 with body `{ "detail": "token_expired_staff_deactivated" }`.

- [ ] **C8. Add `POST /api/v2/staff/:id/employment-agreement`**
  - Accepts JSON `{ upload_id }` from the existing `/uploads` POST flow.
  - Validates the upload exists, belongs to the org.
  - Sets `staff_members.employment_agreement_upload_id`.
  - Writes `audit_logs` action='staff.employment_agreement_uploaded'.
  - Returns updated staff (with masked PII).
  - **Refs:** R5.
  - **Verify:** upload via Documents tab → DB column populated → "View" link returns signed URL.

- [ ] **C9. Extend `GET /api/v2/staff` response with `compliance_summary`**
  - **Seven** COUNT(*) FILTER aggregates on the org's staff list. The existing `StaffMemberListResponse` schema returns `{ staff: [...], total, page, page_size }` (verified at `app/modules/staff/schemas.py:92`); Phase 1 adds a NEW top-level `compliance_summary` field — it does NOT rename `staff` to `items`. Both keys must coexist (one for the row data, one for the counter object).
    - `probation_ending_soon` — `probation_end_date BETWEEN now() AND now() + interval '14 days' AND is_active=true`.
    - `visa_expiring_soon` — `visa_expiry_date BETWEEN now() AND now() + interval '60 days' AND is_active=true AND residency_type IN ('work_visa','student_visa','other')` (G2: filtered to visa-holders only).
    - `missing_agreement` — `employment_agreement_upload_id IS NULL AND is_active=true`.
    - `pay_review_due` — `(last_pay_review_date IS NULL OR last_pay_review_date < now() - interval '12 months') AND is_active=true`.
    - `below_minimum_wage` — `hourly_rate IS NOT NULL AND hourly_rate < <org.minimum_wage_threshold_nzd> AND is_active=true`.
    - **`missing_employee_id`** (G1) — `employee_id IS NULL AND is_active=true`. Uses partial index `idx_staff_missing_employee_id`.
    - **`missing_start_date`** (G3) — `employment_start_date IS NULL AND is_active=true`. Uses partial index `idx_staff_missing_start_date`.
  - Single round-trip query — all aggregates computed in one SELECT using FILTER clauses.
  - **Refs:** R6, G1, G2, G3.
  - **Verify:** `curl /api/v2/staff` → `compliance_summary` contains all 7 integer keys. `EXPLAIN` the count query → planner uses the partial indexes from A2.

- [ ] **C10. Extend POST/PUT for minimum-wage gate**
  - When body contains `hourly_rate < threshold`, 422 with `{detail: 'minimum_wage_below_threshold', threshold: 23.15}`.
  - When body also contains `minimum_wage_override: true`, accept + write `audit_logs` action='staff.minimum_wage_override' with the override user_id.
  - **Refs:** R4.
  - **Verify:** unit test covers both paths.

- [ ] **C11. Extend deactivation + termination flows to revoke roster tokens (G4)**
  - Modify `StaffService.deactivate_staff` (existing `DELETE /api/v2/staff/:id` handler) and the new termination flow (when `employment_end_date` is set via `PUT /staff/:id`) to run the token-revocation SQL per design §5.5 inside the same DB transaction:
    ```python
    result = await db.execute(
        update(StaffRosterViewToken)
        .where(
            StaffRosterViewToken.staff_id == staff_id,
            StaffRosterViewToken.org_id == org_id,
            StaffRosterViewToken.expires_at > func.now(),
        )
        .values(expires_at=func.now())
        .returning(StaffRosterViewToken.id)
    )
    revoked = result.rowcount or 0
    if revoked > 0:
        await write_audit_log(
            session=db, org_id=org_id, user_id=current_user.id,
            action='roster.tokens_revoked',
            entity_type='staff_member', entity_id=staff_id,
            after_value={'tokens_revoked_count': revoked},
        )
    ```
  - Reactivation (`POST /staff/:id/activate`) does NOT un-revoke tokens — staff must receive a fresh roster send to get a new viewer link.
  - **Refs:** R9.7, G4.
  - **Verify:** Create a staff, send roster SMS (token created), curl the public viewer URL → 200. Deactivate the staff → curl the same URL → 410 with `{ "detail": "token_expired_staff_deactivated" }`. Query `audit_log` for the latest row → action='roster.tokens_revoked', after_value `{"tokens_revoked_count": 1}`. Reactivate → curl still returns 410 (token stays revoked).

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
  - Sections: Personal, Employment, Tax & Pay, Schedule (existing WorkSchedule), Clock-in & roster delivery, Skills (per design §6.2).
  - **Employment section** includes the new `residency_type` select with options `citizen | permanent_resident | work_visa | student_visa | other` (default `citizen`). The `visa_expiry_date` date input is **conditionally rendered (G2)** — `{['work_visa', 'student_visa', 'other'].includes(staff.residency_type) && <input ...>}`. Switching back to citizen/resident hides the field; the value is preserved (not nulled).
  - **Inline amber warnings above the Employment section (G1, G3):**
    - When `staff.employee_id === null` → `<InlineWarning>` "This staff has no employee code. Kiosk clock-in (Phase 3) won't work until you set one. Tip: use the format `EMP-001` or `JD-2024`." with a quick-set input that PUTs `{employee_id}` and refreshes.
    - When `staff.employment_start_date === null` → `<InlineWarning>` "Employment start date is required for Phase 2 leave accrual. Please set it before Phase 2 ships." with a date picker that PUTs `{employment_start_date}` and refreshes.
    - Both banners disappear immediately on successful save.
  - Inputs respect `is_masked_ird`/`is_masked_bank` heuristic — when the user clears the field, sends `null` (which the backend skips); when typed fresh, sends raw plaintext.
  - PayRateHistoryPanel collapsible at bottom of Tax & Pay section.
  - Uses `?.` and `?? []` everywhere on API data.
  - All `useEffect` API calls have AbortController cleanup.
  - **Refs:** R2 (incl. residency_type), R3, R4, R6, G1, G2, G3.
  - **Verify:** Browser test —
    - Create a new staff with `residency_type='citizen'` → visa_expiry_date input is hidden.
    - Change to `residency_type='work_visa'` → visa_expiry_date input appears; set a date; save → DB row reflects it.
    - Change back to `'citizen'` → input hides; reload → value still in DB but not rendered.
    - Create a staff with `employee_id=null` → amber inline banner shows; type a code and click "Save" → banner disappears.
    - Create a staff with `employment_start_date=null` → amber inline banner shows; set the date → banner disappears.

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
  - Renders **7** clickable counters (G1 + G3 add two new ones) that toggle URL filter chips per design §6.5:
    - probation_ending_soon → `?filter=probation_ending`
    - visa_expiring_soon → `?filter=visa_expiring`
    - pay_review_due → `?filter=pay_review_due`
    - below_minimum_wage → `?filter=below_minimum_wage` (also renders 🔴 row dot)
    - missing_agreement → `?filter=missing_agreement`
    - missing_employee_id (G1) → `?filter=missing_employee_id` (also renders 🟠 row dot)
    - missing_start_date (G3) → `?filter=missing_start_date` (also renders 🟠 row dot)
  - Row dots stack as a chip cluster; hover tooltip names the missing field(s).
  - **Persistent banner for G3:** When `compliance_summary.missing_start_date > 0`, render an additional **non-dismissible** banner above the counter row:
    > "Phase 2 leave accrual will skip these staff until you backfill `employment_start_date`. Set start dates now to avoid disruption when Phase 2 ships."
    The banner stays visible until the count drops to zero (no "X to dismiss" — admins must actually fix the data).
  - **Refs:** R6, G1, G3.
  - **Verify:** Browser test —
    - Counter increments when a new staff is added without employee_id; click counter → filter chip appears; list shows only staff missing employee_id.
    - X on the chip removes the filter; list returns to default.
    - Persistent banner appears when `missing_start_date > 0`; cannot be dismissed; vanishes only after backfilling.
    - Hover row dot on a staff missing both employee_id and start_date → tooltip "Missing: employee code, employment start date".

- [ ] **E9. Public `StaffRosterPublicView.tsx`**
  - Route `/public/staff-roster/:token` (no auth).
  - Fetches `/api/v2/public/staff-roster/:token`, renders read-only week view.
  - 404 / expired token shows clear message.
  - **Refs:** R9.4.
  - **Verify:** Browser test in incognito.

## Workstream F — Tests + verification

- [ ] **F1. E2E script `scripts/test_staff_employment_record_e2e.py`**
  - Login as org_admin → create TEST_E2E_ staff with full payload (incl. `residency_type`, `employee_id`, `employment_start_date`) → verify masked response → fetch detail → update pay rate → verify history → upload agreement → trigger email roster → trigger SMS roster (skip if no phone) → exercise min-wage override → cleanup all in `finally`.
  - Idempotent prefix-cleanup at the start.
  - **G1 path:** create a staff WITHOUT `employee_id` → GET `/api/v2/staff` → assert `compliance_summary.missing_employee_id >= 1` → patch `employee_id='TEST_E2E_EMP-001'` → re-fetch → assert counter back down.
  - **G2 path:** create a staff with `residency_type='work_visa', visa_expiry_date='2026-12-31'` → GET → assert visa_expiry_date present in masked response. Change to `'citizen'` → re-save → assert `visa_expiry_date` still in DB but `compliance_summary.visa_expiring_soon` does NOT include this staff (because residency is now citizen).
  - **G3 path:** create a staff WITHOUT `employment_start_date` → GET → assert `compliance_summary.missing_start_date >= 1` → patch the date → assert counter back down.
  - **G4 path:** create staff, send SMS roster (provider mocked or real test phone) → token created in `staff_roster_view_tokens` → curl `/api/v2/public/staff-roster/:token` returns 200. Deactivate the staff via `DELETE /staff/:id` → curl same URL → returns 410 with body `{ "detail": "token_expired_staff_deactivated" }`. Query `audit_log` for the latest row → action=`roster.tokens_revoked`, after_value contains `tokens_revoked_count: 1`.
  - **G5 path:** hammer the public viewer URL 35 times in 10 seconds (sequential curls) → first 30 return 200 (or 410 if previously revoked), then 429 with `Retry-After` header. Wait 60 s → request succeeds again.
  - **G7 path:** create a staff with `first_name='Aroha Tāmaki'` (Māori macrons) → trigger SMS roster → inspect the audit_log row → assert `metadata.encoding == 'ucs2'` and `metadata.segments >= 1`.
  - **G8 path:** create staff, send SMS roster (token created) → hard-delete the staff via `DELETE /staff/:id/permanent` → query `staff_roster_view_tokens WHERE staff_id=:id` returns 0 rows (cascade verified).
  - **Refs:** R13, G1, G2, G3, G4, G5, G7, G8.
  - **Verify:** `python scripts/test_staff_employment_record_e2e.py` exits 0 with "passed: N, failed: 0".

- [ ] **F2. Unit-test files**
  - `tests/unit/test_staff_phase1_mask.py`
  - `tests/unit/test_staff_phase1_minimum_wage.py`
  - `tests/unit/test_staff_pay_rate_history.py`
  - `tests/unit/test_staff_phase1_roster_delivery.py` — extended to cover G7 (Māori macrons → UCS-2, multi-part segment count logged in audit).
  - `tests/unit/test_staff_phase1_token_lifecycle.py` (new — G4) — `get_or_create_viewer_token` idempotent; deactivation revokes; reactivation does not un-revoke; cascade-delete on hard-delete staff.
  - `tests/unit/test_staff_phase1_compliance_counters.py` (new — G1, G2, G3) — every counter query returns the expected value for fixtures: staff missing employee_id, staff missing start_date, staff with `residency_type='citizen'` excluded from visa-expiry count, staff with `residency_type='work_visa'` included.
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

**G1–G8 closure ticks (added during spec review)**
- [ ] G1: "Missing employee code" counter renders on Staff List, filters work, amber row dot shown.
- [ ] G2: residency_type select renders in Employment section; visa_expiry_date conditionally hidden for `citizen`/`permanent_resident`; visa-expiry compliance counter excludes citizens.
- [ ] G3: "Missing employment start date" counter + persistent non-dismissible banner above Staff List; inline OverviewTab warning fires when start_date is null.
- [ ] G4: SMS roster token created → public viewer 200; deactivate staff → public viewer 410 with `token_expired_staff_deactivated`; `roster.tokens_revoked` audit row written.
- [ ] G5: Public viewer endpoint enforces 30 req/min/IP — 31st request in a minute returns 429 with Retry-After header.
- [ ] G6: Mobile screens unchanged in Phase 1; mobile staff list/detail loads without crash when org has staff_management enabled (verified post-merge).
- [ ] G7: SMS sent for staff with Māori macron in name → multi-part UCS-2 SMS delivered; audit row captures segments + encoding.
- [ ] G8: Hard-delete a staff via `DELETE /staff/:id/permanent` → `staff_roster_view_tokens` rows for that staff are cascade-deleted (0 rows post-delete).

The phase is NOT done until every box is ticked. Any item that can't be ticked goes into `gap-analysis.md` with the reason.
