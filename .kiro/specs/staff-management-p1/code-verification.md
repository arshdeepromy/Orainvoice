# Code Verification Report — All Phases

This document records every assumption made in the Phase 1–5 spec docs and the result of cross-checking it against the live codebase. Anything marked ⚠️ or ❌ requires the spec to be amended (or a clarifying decision made) before implementation begins.

Verification date: 2026-05-31. Latest alembic head at verification time: `0202`.

## Backend infrastructure

| Assumption | Status | Notes |
|---|---|---|
| `app/core/encryption.py::envelope_encrypt(str|bytes) -> bytes` exists | ✅ | Verified — function at line 66; `envelope_decrypt_str` at line 105. |
| `app/integrations/email_sender.py::send_email(db, message, *, dlq_task_name=None, dlq_task_args=None)` | ✅ | Verified at line 1763. The `dlq_task_name` + `dlq_task_args` kwargs land in the function signature post-quick-win-#10. |
| `EmailMessage` is the value-object passed in | ✅ | Verified — dataclass at line 118 of `email_sender.py`; multiple call sites in `auth/service.py`, `invoices/service.py`, `quotes/service.py`. |
| `app/modules/scheduling_v2/models.py::ScheduleEntry.entry_type` already includes `'leave'` | ✅ | Verified — `ENTRY_TYPES = ["job", "booking", "break", "other", "leave"]` at line 21. |
| `app/modules/admin/models.py::PublicHoliday` exists with `holiday_date`, `name`, `country_code` | ✅ | Verified — class at line 467, table `public_holidays`. |
| `app/modules/admin/service.py::sync_public_holidays` (Nager.Date) | ✅ | Verified at line 4839. |
| `app/core/modules.py::ModuleService.is_enabled(org_id, slug)` | ✅ | Verified at line 304. |
| `module_registry` table has `setup_question` + `setup_question_description` columns | ✅ | Verified via migrations + `frontend/src/pages/setup-guide` references. |
| `feature_flags` table — primary key column is `key` (not `slug`); has `default_enabled`, `scope` columns | ✅ | Verified via `app/modules/feature_flags/models.py`. |
| `subscription_plans.enabled_modules` is JSONB list | ✅ | Verified at `app/modules/admin/models.py:58`. |
| `app/modules/uploads/` infrastructure handles file storage | ✅ | Verified — Phase 1 reuses; Phase 4 stores PDFs there. |
| `app/modules/portal/service.py` token pattern uses `secrets.token_urlsafe(32)` + expires_at | ✅ | Verified — same pattern reused for Phase 1's `staff_roster_view_tokens`. |
| WeasyPrint `await asyncio.to_thread(lambda: HTML(string=html).write_pdf())` | ✅ | Verified in `app/modules/invoices/service.py:4446` (post-quick-win-#2). |
| Existing scheduler Redis SETNX lock on `scheduler:loop_lock` (per ISSUE-164) | ✅ | Verified — Phase 1's roster broadcast + Phases 2-4 leave/clock/payslip jobs all run inside this lock. |
| `connexus_sms.py::ConnexusSmsClient.send(SmsMessage)` exists | ✅ | Verified at `app/integrations/connexus_sms.py:765`. |
| `SmsVerificationProvider` model with `provider_key='connexus'`, `is_active`, `priority` for fallback | ✅ | Verified — `app/modules/sms_providers/` references and `app/integrations/connexus_sms.py:325`. |
| `app/integrations/sms_sender.py` exists today | ❌ | **Does not exist.** Phase 1 must create it as a new file (mirroring `email_sender.py` shape). The send_sms helper, DLQ wiring, and provider fallback live there. Phases 2–4 reuse it. **Spec amendment:** Phase 1 task C4 already calls this out — verified consistent. |
| `app/core/audit.py::write_audit_log(session, *, action, entity_type, ...)` | ✅ | Verified at line 35. **CORRECTION:** The actual SQL table is `audit_log` (SINGULAR), not `audit_logs`. The spec docs use `audit_logs` colloquially — implementation must use the singular table name and the `write_audit_log` helper, never raw inserts to a non-existent `audit_logs` table. |

## Schema / table references

| Assumption | Status | Notes |
|---|---|---|
| `staff_members` columns: `id, org_id, user_id, name, first_name, last_name, email, phone, employee_id, position, reporting_to, shift_start, shift_end, role_type, hourly_rate, overtime_rate, is_active, availability_schedule, skills` | ✅ | Verified — `app/modules/staff/models.py`. Phase 1 adds 22 new columns idempotently. |
| `staff_members.branch_id` does NOT exist | ✅ | Confirmed absent. **CORRECTION for Phase 3:** branch-admin scoping must use `staff_location_assignments` (the existing many-to-many between `staff_members` and `branches`/`locations`), NOT a direct `staff_members.branch_id`. Spec language "scoped via `staff.branch_id`" should read "scoped via `staff_location_assignments`". |
| `branches` table has `id, org_id, name, address, phone, email, logo_url, operating_hours, timezone, is_hq, notification_preferences, is_default, is_active, created_at, updated_at` | ⚠️ | **Geofence gap:** branches table does NOT have `lat`, `lng`, or `radius_metres` columns. **Phase 3 amendment required:** the geofence feature in R4 either (a) adds these columns to `branches` in Phase 3's migration, or (b) reads them from `org_settings.clock_in_policy.branch_geofences[branch_id]`. Recommendation: add columns to `branches` (`lat numeric(9,6)`, `lng numeric(9,6)`, `geofence_radius_metres int default 200`) — cleaner than nesting in JSONB. Logged as STAFF-009 (new). |
| `audit_log` table (singular) is `app/modules/admin/models.py::AuditLog`, columns `id, org_id, user_id, action, entity_type, entity_id, before_value, after_value, ip_address, device_info, created_at` | ✅ | Verified. **All spec references to `audit_logs` should be read as `audit_log` (singular).** Implementation will use the existing `write_audit_log` helper, which abstracts the table name. |
| `time_entries` table (existing billable timer module `time_tracking_v2`) is keyed on `user_id` not `staff_id` | ✅ | Verified per source plan §1.5. Phase 3 distinguishes `time_clock_entries` (new, keyed on `staff_id`, attendance) from `time_entries` (existing, keyed on `user_id`, billable). The two never overwrite each other. |

## Mobile / frontend infrastructure

| Assumption | Status | Notes |
|---|---|---|
| Mobile `StackRoutes.tsx` lazy-import + ModuleGate pattern | ✅ | Verified pattern exists; Phase 3's `ClockScreen` follows it. |
| `Capacitor.isNativePlatform()` guard pattern | ✅ | Used throughout `mobile/src/`. |
| `useDashboardWidgets.ts` normalisation hook | ✅ | Verified — Phase 5 adds two new entries. |
| `dashboard_service.py::get_public_holidays` SAVEPOINT-per-widget pattern | ✅ | Verified — Phase 5 mirrors. |
| Existing `setup_guide/SetupGuide.tsx` reads `module_registry.setup_question` automatically | ✅ | Verified — Phase 1's module_registry insert just works. |

## Migration sequence

| Assumption | Status | Notes |
|---|---|---|
| Latest alembic head pre-Phase-1 = `0202` | ✅ | Verified via `ls alembic/versions/`. |
| Phase 1 lands as `0203` (schema), `0204` (indexes) | ✅ | Confirmed sequence. |
| Phase 2 lands as `0205, 0206` | ✅ | |
| Phase 3 lands as `0207, 0208` | ✅ | |
| Phase 4 lands as `0209, 0210` | ✅ | |
| Phase 5 introduces no new tables | ✅ | Reports + bank-file are read-only. |
| All index migrations use `CREATE INDEX CONCURRENTLY ... IF NOT EXISTS` inside `op.get_context().autocommit_block()` | ✅ | Per `database-migration-checklist.md` (extended this conversation). Canonical template = `2026_05_30_2300-0202_add_perf_indexes.py`. |

## Subscription plan migration

| Assumption | Status | Notes |
|---|---|---|
| Default subscription plan slug exists | ⚠️ | `subscription_plans` table does NOT have a `slug` column — it has `name`, `is_archived`, `is_public`. Phase 1 migration uses `name ILIKE '%default%' OR name ILIKE '%starter%'` heuristic. **STAFF-001 settles before merge** which exact plans should auto-include `staff_management` + `payroll`. Possible answers: (a) all non-archived plans, (b) only the public ones, (c) only the smallest plan. Default value used in spec is "all non-archived" — explicitly noted as a heuristic, not a contract. |

## Open verification gaps (pre-implementation)

These are still TODO before code lands:

1. **STAFF-001:** Subscription plan target — settle the `name ILIKE` heuristic vs an explicit list.
2. **STAFF-003:** Confirm Nager.Date NZ public-holiday `holiday_date` matches Holidays Act observed dates (Monday-isation). Affects Phase 2's OWD engine.
3. **STAFF-006:** Confirm shared `/kiosk` surface vs dedicated `/staff-kiosk`. The design picked shared.
4. **STAFF-009 (new):** Add lat/lng + geofence-radius to `branches` for Phase 3 self-service geofencing. Migration is one extra `ALTER TABLE ADD COLUMN IF NOT EXISTS`.
5. **Audit log naming:** Spec docs use `audit_logs` (plural) colloquially — actual table is `audit_log` (singular). Implementation must use `from app.core.audit import write_audit_log` rather than raw inserts. Re-read of all spec mentions of "audit_logs row" should be understood to mean "call `write_audit_log` with the listed action".

## Spec amendment note

A targeted edit pass should run before Phase 1 code lands:

- Replace any literal `INSERT INTO audit_logs` snippets with calls to `write_audit_log(session, action='...', entity_type='staff'|'leave_request'|...)`. The list of action names in each phase's R12/R14/R15/R16 stays as-is — those are the action strings.
- Phase 3 geofence design should add the `branches.lat/lng/geofence_radius_metres` migration columns to `0207` instead of nesting them in `org_settings.clock_in_policy.branch_geofences`.
- Phase 3 branch-admin scoping should reference `staff_location_assignments`, not `staff.branch_id`.

These three corrections are mechanical — no design rethink required.
