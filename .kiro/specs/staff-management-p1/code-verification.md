# Code Verification Report — Phase 1 (Re-verified 2026-05-31, post G1-G8 amendments)

This document records every assumption made in the Phase 1 spec docs (`requirements.md`, `design.md`, `tasks.md`) and the result of cross-checking each one against the live codebase **at workspace head 0202**. Anything ⚠️ or ❌ is a real gap that must be fixed before code lands.

> Re-verification was triggered after the user added G1–G8 amendments (residency_type, missing-employee_id counter, missing-start_date counter, token revocation on deactivation, rate-limit on public viewer, Māori macron SMS encoding, FK cascade on hard-delete). All G amendments are in `tasks.md`; the design and requirements docs may still need parity sweeps in §4 below.

---

## 1. Backend infrastructure — ALL ✅ verified

| Assumption | Status | Verified at |
|---|---|---|
| `app/core/encryption.py::envelope_encrypt(str|bytes) -> bytes` | ✅ | `app/core/encryption.py:66`. `envelope_decrypt_str` at line 105. |
| `app/integrations/email_sender.py::send_email(db, message, *, dlq_task_name=None, dlq_task_args=None)` | ✅ | `app/integrations/email_sender.py:1763`. Existing call sites in `auth/service.py`, `invoices/service.py`, `quotes/service.py` confirm the kwarg shape. |
| `EmailMessage` dataclass | ✅ | `app/integrations/email_sender.py:118`. |
| `app/modules/scheduling_v2/models.py::ScheduleEntry.entry_type` includes `'leave'` | ✅ | `app/modules/scheduling_v2/models.py:21` — `ENTRY_TYPES = ["job", "booking", "break", "other", "leave"]`. |
| `app/modules/admin/models.py::PublicHoliday` exists (Phase 2 dep, but staff_phase1 tab references it) | ✅ | `app/modules/admin/models.py:467`. Not used in Phase 1 directly. |
| `app/core/modules.py::ModuleService.is_enabled(org_id, slug)` | ✅ | `app/core/modules.py:304`. |
| `app/modules/module_management/models.py::ModuleRegistry` exists | ✅ | Confirmed via grep. |
| `feature_flags` table — primary key column is `key`, has `default_enabled`, `scope` | ✅ | `app/modules/feature_flags/models.py:21`. |
| `subscription_plans.enabled_modules` is JSONB list | ✅ | `app/modules/admin/models.py:62` — `Mapped[dict] = mapped_column(JSONB, ...)`. **The `subscription_plans` table has NO `slug` column** — only `name`, `is_archived`, `is_public`. The migration's `WHERE name ILIKE '%default%' OR name ILIKE '%starter%' OR is_archived = false` heuristic is the only available approach until STAFF-001 settles. |
| `app/modules/uploads/router.py` exists with `/receipts` and `/attachments` endpoints | ✅ | `app/modules/uploads/router.py:69, 81`. **Uploads router is mounted at `/api/v2/uploads` per `app/main.py:504`.** |
| WeasyPrint `await asyncio.to_thread(...)` (Phase 4 dep) | ✅ | `app/modules/invoices/service.py:4446`. Not used in Phase 1. |
| Existing scheduler Redis SETNX lock `scheduler:loop_lock` | ✅ | `app/tasks/scheduled.py:891` — `_SCHED_LOCK_KEY = "scheduler:loop_lock"`. |
| `connexus_sms.py::ConnexusSmsClient.send(message)` | ✅ | `app/integrations/connexus_sms.py:765`. |
| `SmsVerificationProvider` model with `provider_key='connexus'`, `is_active`, `priority` | ✅ | Verified via grep on `connexus_sms.py:325, 388, 418` reads it. |
| `app/integrations/sms_sender.py` does NOT exist today | ✅ confirmed missing | Phase 1 task **C4 creates this new file**. |
| `app/core/audit.py::write_audit_log(session, *, action, entity_type, ...)` | ✅ | `app/core/audit.py:35`. **Table is `audit_log` (singular)** — confirmed at `app/modules/admin/models.py:318`. The spec uses `audit_logs` colloquially; implementation MUST call `write_audit_log` (which encapsulates the singular table name). |
| `app/modules/portal/service.py` token pattern uses `secrets.token_urlsafe(32)` | ✅ | `app/modules/portal/service.py:298`. Phase 1's `staff_roster_view_tokens` reuses it. |
| `app/tasks/scheduled.py::_DAILY_TASKS` registry list | ✅ | `app/tasks/scheduled.py:872` — Phase 1 D1 appends to this list. |

---

## 2. Existing staff module — ALL ✅ verified

| Assumption | Status | Verified at |
|---|---|---|
| `staff_members` columns today: id, org_id, user_id, name, first_name, last_name, email, phone, employee_id, position, reporting_to, shift_start, shift_end, role_type, hourly_rate, overtime_rate, is_active, availability_schedule, skills, created_at, updated_at | ✅ | `app/modules/staff/models.py:30-77`. Phase 1's `0203` migration adds 22 (now 23 with `residency_type`) new columns idempotently. |
| `staff_members.employee_id` is already nullable | ✅ | `Mapped[str | None]` at line 47. Phase 1's G1 amber warning hooks into this without schema change. |
| `staff_location_assignments` table exists for staff↔branch many-to-many | ✅ | `app/modules/staff/models.py:85`. Phase 2's branch-admin scoping references it. |
| `StaffMember.reporting_to` self-FK (manager) | ✅ | `app/modules/staff/models.py:48`. |
| Staff router prefix `/api/v2/staff` | ✅ | `app/main.py:512`. |
| Scheduling v2 router prefix `/api/v2/schedule` (NOT `/api/v2/scheduling`) | ⚠️ **DRIFT** | `app/main.py:516` confirms prefix is `/api/v2/schedule`. The `mobile-app.md` steering doc lists `/api/v2/schedule`, which is correct. Spec must use `/api/v2/schedule?staff_id=...&start=...&end=...`, NOT `/api/v2/scheduling/entries?...` as written in design §6.3 and tasks E4. |
| Scheduling v2 list endpoint accepts `staff_id`, `start`, `end` query params | ✅ | `app/modules/scheduling_v2/router.py:50` — `start`, `end`, `staff_id`, `location_id` are the params; response shape is `{ entries: [...], total: N }` — note it's `entries` (plural), not `items`. |
| Existing `GET /api/v2/staff` list response shape is `{ staff: [...], total, page, page_size }` | ✅ | `app/modules/staff/schemas.py:92-95`. **NOT `{ items: [...], total: N }`** — the spec's R1 / R6 should use the existing key `staff`, OR introduce `items` as a new optional field for the new compliance-summary response. |
| `_get_org_id(request)` helper reads `request.state.org_id` | ✅ | `app/modules/staff/router.py:44`. |
| Staff service `get_staff`, `update_staff`, `_check_duplicates` exist | ✅ | `app/modules/staff/service.py:120, 131, 91`. Phase 1 task B4 extends these. |

---

## 3. Frontend — ALL ✅ verified

| Assumption | Status | Verified at |
|---|---|---|
| `/staff/:id` route registered in `App.tsx` with `<ModuleRoute moduleSlug="staff">` guard | ✅ | `frontend/src/App.tsx:575`. **Module slug is `'staff'`, NOT `'staff_management'`.** This is important: the existing `ModuleRoute` checks the EXISTING `staff` module slug. Phase 1 introduces a NEW `staff_management` module slug. The two co-exist: the legacy `staff` module enables CRUD, and the new `staff_management` module enables the new tabbed UI / payslip dependency chain. The spec's R11 + design §2 pattern (legacy single-form when `staff_management` disabled, tabbed shell when enabled) is correct in concept but needs to make explicit that `staff` ≠ `staff_management` — see §4 below. |
| `StaffDetail` is lazy-loaded in App.tsx | ✅ | `frontend/src/App.tsx:166`. |
| `StaffDetailRoute` wraps it with `useParams<{ id: string }>` | ✅ | `frontend/src/App.tsx:314`. |
| `ScheduleCalendar` is `export default` and is a self-contained calendar component | ✅ | `frontend/src/pages/schedule/ScheduleCalendar.tsx:369`. **It does NOT accept any props today** — `export default function ScheduleCalendar()` with empty parameter list. Phase 1 task E4's "filtered to staff_id" via `focusStaffId` prop requires extending its signature. The component already has internal `selectedStaffId` state used in MobileDayView, so the refactor is plumbing the prop into that state, not a redesign. |
| `ModuleContext` exposes `useModules()` returning `{ isEnabled, enabledModules, ... }` | ✅ | `frontend/src/contexts/ModuleContext.tsx:33`. **The hook is `useModules()`, NOT `useModuleEnabled()`.** Spec design §6.1 says `useModuleEnabled('staff_management')` — that's a wrapper that doesn't exist; implementation must call `const { isEnabled } = useModules(); isEnabled('staff_management')`. |
| `apiClient` calls use `{ baseURL: '/api/v2' }` override pattern | ✅ | Existing `StaffDetail.tsx:114` uses this pattern. |
| Staff list endpoint response key is `data?.staff` (not `data?.items`) | ✅ | `frontend/src/pages/staff/StaffList.tsx` consumes `(res.data as any)?.staff ?? []`. Phase 1's compliance counter response addition must preserve the `staff` key. |

---

## 4. CRITICAL DRIFTS — must fix before implementation

These are real bugs the implementation will hit if we don't correct the spec text first.

### 4.1 ⚠️ Module slug confusion: `staff` vs `staff_management`

**The codebase already has a module called `staff`.** Existing `<ModuleRoute moduleSlug="staff">` in `App.tsx:575` gates all `/staff/*` routes today. Phase 1 introduces a SECOND module called `staff_management`.

Required clarification in design §2:
- The existing `staff` module continues to be the route-level gate (must be enabled to even see `/staff/*` routes).
- The new `staff_management` module gates only the *upgraded tabbed UI*; when `staff_management` is disabled but `staff` is enabled, the page renders the existing single-form `LegacyStaffDetail` view (the file moved to `_legacy/StaffDetail.legacy.tsx` per task E2).
- The new module dependency on Payroll is `payroll` → `["staff_management"]`. Payroll does NOT depend on the legacy `staff` module.

This isn't a contradiction with the existing setup — both modules can exist together — but the design doc must spell out which one is the route gate and which one is the feature gate. **Action: amend `design.md` §2** to add a row clarifying the relationship. Spec implementation isn't blocked, but the OverviewTab module-gate check must use `useModules().isEnabled('staff_management')` (not `'staff'`).

### 4.2 ⚠️ Wrong API path for scheduling-v2 in design §6.3 and tasks E4

Design says: `GET /api/v2/scheduling/entries?staff_id=:id&from=:weekStart&to=:weekEnd`

Reality (`app/main.py:516`): `GET /api/v2/schedule?staff_id=:id&start=:weekStart&end=:weekEnd`

**Action:** correct design §6.3 and task E4 to use `/api/v2/schedule` (not `/scheduling/entries`) and query params `start`/`end` (not `from`/`to`). Response shape is `{ entries: [...], total: N }`, not `{ items, total }` — frontend must consume `res.data?.entries ?? []`.

### 4.3 ⚠️ List endpoint response shape mismatch in R1 / R6

The `GET /api/v2/staff` list endpoint already returns `{ staff: [...], total, page, page_size }` per `app/modules/staff/schemas.py:92-95::StaffMemberListResponse`. Phase 1's R6 / C9 / E8 talk about `compliance_summary` being added "alongside `items` + `total`" — but `items` doesn't exist on this endpoint.

**Action:** in tasks C9 and E8, change `items + total` references to "the existing `staff` key + total". The `compliance_summary` field is a new top-level key on the response — fine, just don't claim it sits next to `items`.

### 4.4 ⚠️ `useModuleEnabled` hook does not exist

Spec design §6.1 + several places use `useModuleEnabled('staff_management')`. The actual API is `useModules().isEnabled('staff_management')`.

**Action:** fix design §6.1 example code to use the real hook signature. Mechanical rename.

### 4.5 ⚠️ Ord_settings JSONB allow-list — `minimum_wage_threshold_nzd` requires explicit registration

`organisations.settings` JSONB writes are gated by a closed allow-list `SETTINGS_JSONB_KEYS` at `app/modules/organisations/service.py:198`. Currently includes 36 settings keys. **Adding a new key like `minimum_wage_threshold_nzd` requires extending this set** AND `update_org_settings` will then echo it back.

**Action in B6 (already implicit but make it explicit):** the task must include "add `minimum_wage_threshold_nzd` to `SETTINGS_JSONB_KEYS` in `app/modules/organisations/service.py`". Without this, the Settings PATCH UI silently drops the value.

### 4.6 ⚠️ Rate-limit middleware doesn't have a clean "policy map" extension point

Spec task C7 says "add a new rule keyed `public_staff_roster` to the existing rate-limit middleware policy map at `app/middleware/rate_limit.py`". The actual middleware uses **hardcoded path-prefix conditionals** in `_apply_rate_limits` (e.g., `if path == _HA_HEARTBEAT_PATH:`, `if path.startswith(_PAYMENT_PAGE_PREFIX):`). There is no `policy_map` data structure.

**Action in C7:** rephrase to "add a new conditional block to `_apply_rate_limits` mirroring the existing HA-heartbeat block" — with a constant `_PUBLIC_STAFF_ROSTER_PATH_PREFIX = "/api/v2/public/staff-roster/"` and per-IP key `rl:public_staff_roster:ip:{ip}` at 30/min. The implementation pattern is in lines 252-265 of `rate_limit.py` (the HA heartbeat block).

### 4.7 ⚠️ Audit `audit_log` (singular) vs `audit_logs` (plural)

Specs use `audit_logs` colloquially. Real table is `audit_log` (`app/modules/admin/models.py:318`). The `write_audit_log` helper at `app/core/audit.py:35` encapsulates the table name, so as long as implementation calls the helper (which the design does — see §3.2 frontend trace and tasks C3/C6/C8/C10/C11), this is a documentation-only drift. **Action:** the spec already corrects this in R12 — confirmed clean.

### 4.8 ⚠️ Pre-merge gate checklist refers to `audit_logs` (plural) — minor

Pre-merge gate: "audit_logs entries written for every state change". Same colloquial use. Not a code drift, just inconsistent prose. Optionally rename to `audit_log` for accuracy. Not blocking.

---

## 5. G1–G8 amendments — verify against code

The user's G1–G8 expansions in `tasks.md` are all internally consistent and have no further code drift beyond what §4 captures. Specifically:

- **G1 (missing employee_id counter)** — Verified: `staff_members.employee_id` is nullable today, so the counter `WHERE employee_id IS NULL AND is_active=true` is well-defined.
- **G2 (residency_type + visa filter)** — Verified: `residency_type` is a NEW column added in 0203. The compliance counter `WHERE visa_expiry_date BETWEEN ... AND residency_type IN (...)` works once the column exists. **Action:** ensure the migration adds the column before any backfill runs that touch `residency_type`.
- **G3 (missing employment_start_date counter + persistent banner)** — Verified: same pattern as G1, no new code needed.
- **G4 (token revocation on deactivation)** — Verified: existing `DELETE /api/v2/staff/:id` handler in `router.py:223` calls `staff.is_active = False` and flushes. Task C11 must hook revocation into this flow within the same DB transaction. The helper `update().where(...).values(expires_at=func.now()).returning(...)` works on async SQLAlchemy.
- **G5 (rate-limit public viewer)** — Verified: see §4.6 above for the implementation site correction.
- **G6 (mobile unchanged)** — No-op verification; no code drift.
- **G7 (Māori macron SMS encoding)** — Spec says SMS metadata captures `encoding: 'ucs2'` and `segments`. The existing `ConnexusSmsClient.send(SmsMessage)` returns `SmsSendResult` (verified at `connexus_sms.py:765`); the `audit_log.metadata` field will need to receive these from the SmsSendResult. **Action:** confirm `SmsSendResult` exposes encoding + segment count, OR have the new `app/integrations/sms_sender.py` (task C4) compute it from the body before dispatching. Likely the latter — the helper `compose_roster_sms_body()` should classify GSM-7 vs UCS-2 (any char outside the GSM-7 alphabet → UCS-2; macrons are not in GSM-7). Pure-Python heuristic, ~10 lines.
- **G8 (cascade delete tokens on hard-delete staff)** — Verified: task A1 already states `ON DELETE CASCADE on both org_id and staff_id FKs`. Existing `DELETE /api/v2/staff/:id/permanent` endpoint at `router.py:239` already does `await db.delete(staff)` — Postgres CASCADE handles the rest.

---

## 6. Subscription plan migration heuristic — STAFF-001 still open

`subscription_plans` table has NO `slug` column — only `name`, `is_archived`, `is_public`. Spec uses `name ILIKE '%default%' OR name ILIKE '%starter%' OR is_archived = false` heuristic. **STAFF-001 must settle which plans get auto-included before merge.**

Three options:
- (a) all non-archived plans (default in the spec)
- (b) only public plans
- (c) explicit list via plan IDs (most surgical)

Recommend (a) for now — matches existing module-registration pattern in alembic 0068, 0135, 0137, 0141 (other module backfills did the same).

---

## 7. Compliance summary query — single round-trip claim

Tasks C9 says "all aggregates computed in one SELECT using FILTER clauses". Verified: PostgreSQL supports `COUNT(*) FILTER (WHERE ...)` natively, single-table query against `staff_members` plus a single `LEFT JOIN organisations o ON o.id = sm.org_id` to get `o.settings->>'minimum_wage_threshold_nzd'`. The query plan with the partial indexes from 0204 will be O(log N) per FILTER. Confirmed feasible.

---

## 8. Open verification gaps remaining at merge time

These need explicit decisions before code lands:

1. **STAFF-001:** which subscription plans auto-include `staff_management`/`payroll`. Recommend "all non-archived non-public-trial plans" — settle by reading `app/modules/admin/models.py:62-65` for the actual plan inventory on Pi PROD.
2. **STAFF-006:** kiosk routing for Phase 3 (not Phase 1; mention only because Phase 1 sets `self_service_clock_enabled` flag default).
3. **STAFF-009 (new during this verification):** scheduling-v2 endpoint path drift in §4.2 — implementation correctness blocker if not corrected before E4 begins.

---

## 9. Implementation readiness verdict

**Phase 1 spec is implementable** with the seven targeted text corrections in §4 applied:

| # | File | Correction |
|---|---|---|
| 4.1 | `design.md §2` | Clarify `staff` (route gate) vs `staff_management` (feature gate) co-existence. |
| 4.2 | `design.md §6.3` + `tasks.md E4` | `/api/v2/schedule?staff_id=...&start=...&end=...`; consume `data?.entries ?? []`. |
| 4.3 | `tasks.md C9, E8` + `design.md §11` | Use existing `staff` key on the list response, not `items`. |
| 4.4 | `design.md §6.1` | `useModules().isEnabled('staff_management')`, not `useModuleEnabled(...)`. |
| 4.5 | `tasks.md B6` | Add explicit step "extend `SETTINGS_JSONB_KEYS` with `minimum_wage_threshold_nzd`". |
| 4.6 | `tasks.md C7` | Rate-limit added as a new conditional block in `_apply_rate_limits`, not a "policy map entry". |
| 4.7 | (none — already correct) | `write_audit_log` is the helper; `audit_log` is the singular table. |

These are mechanical text edits totalling ~30 lines of spec change. None of them require redesign. Once applied, the spec produces a working implementation on first run with no broken flows.

**No critical blockers.** The G1–G8 amendments are sound. The only meaningful new finding from this re-verification is the `/api/v2/scheduling/entries` → `/api/v2/schedule` path drift (§4.2), which would have caused a silent 404 in the Roster tab the moment E4 was tested in the browser.
