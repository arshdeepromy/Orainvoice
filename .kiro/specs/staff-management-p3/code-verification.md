# Code Verification Report — Phase 3 (2026-05-31, post G1–G17 amendments)

This document records every assumption made in the Phase 3 spec docs (`requirements.md`, `design.md`, `tasks.md`) and the result of cross-checking each one against the live codebase **at workspace head 0202**. Anything ⚠️ or ❌ is a real gap that must be fixed before code lands.

> Verification scope: re-read all three P3 spec files plus the user's amendments (G1 overtime policy, G2 roster-change SMS, G3 running-late, G4 SLOs, G6 cover eligibility, G7 time_entries lock scope, G8 manager-approval swap, G9 default_channel propagation, G10 photo review, G12 kiosk lookup rate-limit, G13 SMS matrix, G15 photo retention, G16 edited_after_approval test, G17 per-branch geofence).

---

## 1. Backend infrastructure — verified clean ✅

| Assumption | Status | Verified at |
|---|---|---|
| `app/modules/scheduling_v2/models.py::ScheduleEntry` is the lookup target for `scheduled_entry_id` | ✅ | Verified earlier in P1/P2; `entry_type IN ('job','booking','break','other','leave')`. |
| `app/modules/scheduling_v2/service.py::SchedulingService.update_entry(org_id, entry_id, payload)` exists | ✅ | `app/modules/scheduling_v2/service.py:159`. |
| `app/modules/scheduling_v2/service.py::SchedulingService.reschedule(...)` exists | ⚠️ | Real method is `reschedule(...)` (NOT `reschedule_entry(...)` as the spec says in design §4.6 and tasks B7a). Method located at `app/modules/scheduling_v2/service.py:215`. **Spec rename required.** |
| `_DAILY_TASKS: list[tuple]` registry in `app/tasks/scheduled.py:872` (entries are `(fn, interval_seconds, name)`) | ✅ | New tasks `check_late_arrivals` (300s) and `check_missed_clock_outs` (3600s) appended. |
| `WRITE_TASKS: set[str]` at `scheduled.py:849` — names of tasks that mutate data, skipped on standby | ✅ | New SMS-emitting tasks should be added to `WRITE_TASKS` per the established convention. **Tasks lists doesn't currently call this out** — see §2.7 below. |
| Existing scheduler Redis SETNX lock `scheduler:loop_lock` (60s TTL, 30s renewal) | ✅ | Tasks C3 honors this. |
| `staff_members.availability_schedule` JSONB keyed by `monday`/`tuesday`/...`sunday` | ✅ | Phase 1 ships this. |
| `app/integrations/sms_sender.py::send_sms(db, *, to_phone, body, dlq_task_name=None)` (Phase 1) | ✅ planned | New file in Phase 1 task C4; reused everywhere here. |
| `app/core/audit.py::write_audit_log(session, *, action, entity_type, ...)` | ✅ | Confirmed. Real table is `audit_log` (singular), helper encapsulates name. Spec design §11 already correct. |
| Capacitor camera + geolocation plugins, `isNativePlatform()` guard | ✅ | Established mobile pattern. |
| Redis `SET NX EX` pattern for locks/dedupe | ✅ | Used everywhere in the codebase. |
| `app/modules/uploads/router.py` mounted at `/api/v2/uploads` (verified P1 §1) | ✅ | `POST /receipts` and `POST /attachments` are the actual endpoints. **Note for the kiosk flow:** spec assumes `photo_upload_id` is returned by a generic `/uploads` POST — actual endpoint paths are `/api/v2/uploads/receipts` or `/api/v2/uploads/attachments`. Service-level wiring needs to pick one — see §2.4 below. |
| `staff_members.on_file_photo_url` (Phase 1) | ✅ | Phase 1 R2 column added in 0203. |
| `staff_members.weekly_roster_sms_enabled` opt-in (Phase 1) | ✅ | Phase 1 R2 column. Roster-change SMS (G2) honors this flag correctly. |
| `staff_members.self_service_clock_enabled` (Phase 1) | ✅ | Phase 1 R2 column. Default-channel propagation (G9) reads it. |
| `staff_members.employee_id` (existing, nullable) | ✅ | Existing column. Cover-eligibility filter checks `employee_id IS NOT NULL OR user_id IS NOT NULL`. |
| `branches` table has no `lat`/`lng`/`geofence_radius_metres` columns today | ✅ | Spec migration A1 adds them; verified in P1 verification report §4 — same finding. |

---

## 2. Critical drifts — must fix before implementation

### 2.1 ❌ Kiosk routes are NOT public — JWT with `kiosk` role required

**Spec says** (§steering compliance, R3, design §1, §4.1, §6.1, §7.1): kiosk clock routes register at `/kiosk/clock/*` (or `/api/v1/kiosk/clock/*`) with the explicit phrase "no auth required" and "no login required".

**Reality** at `app/modules/kiosk/router.py:108-112, 159-163, 204-208`: every existing kiosk endpoint (`POST /check-in`, `POST /vehicle-lookup`, `GET /customer-lookup`) declares `dependencies=[require_role("kiosk"), Depends(_check_kiosk_rate_limit)]`. Auth middleware does NOT bypass `/api/v1/kiosk/*` either — `app/middleware/auth.py::PUBLIC_PATHS` and `PUBLIC_PREFIXES` (lines 43, 117) only include `/health`, `/api/v1/version`, `/api/v1/portal/`, `/api/v1/public/`. Kiosk paths require a JWT with `role: kiosk`.

The customer-facing kiosk flow at `frontend/src/pages/kiosk/KioskPage.tsx` works because the kiosk tablet is logged in once (with a `role: kiosk` JWT, 30-day refresh per `tests/properties/test_kiosk_properties.py:1572`) and then any walk-in customer uses that pre-existing session. There is no "unauthenticated public kiosk" surface.

**Impact if shipped as-is:**
- The new `/kiosk/clock/lookup` and `/kiosk/clock/action` routes would either:
  - (a) Fail with 401 because they bypass `require_role("kiosk")` but the auth middleware still requires a JWT (kiosk routes aren't in PUBLIC_PATHS).
  - (b) Or, if hooked into the existing kiosk router, REQUIRE the kiosk JWT — which contradicts "no auth required" but actually matches how kiosk works today.
- The "kiosk operator/queue can challenge mismatches in person" model (R3.9) implicitly assumes a kiosk operator is present and the device is already kiosk-logged-in. That's actually correct in practice; the spec language is wrong.

**Fix:**
- Update steering-compliance and R3 to say: "Kiosk clock routes mount at `/api/v1/kiosk/clock/*` and use the SAME `dependencies=[require_role('kiosk')]` pattern as the existing customer-facing kiosk endpoints. The kiosk tablet is logged-in once (the existing 30-day kiosk JWT model) and any walk-in staff uses that device's session — no per-staff JWT involved."
- Drop "no auth required" / "no login required" from R3 user story and acceptance criteria. Replace with: "No staff-specific login required at the device — the kiosk tablet's role-`kiosk` JWT serves the surface."
- Path: it's `/api/v1/kiosk/clock/lookup` and `/api/v1/kiosk/clock/action`, NOT `/kiosk/clock/*`. The router prefix is `/api/v1/kiosk` per `app/main.py`.

### 2.2 ❌ Path drift: `/kiosk/clock/*` should be `/api/v1/kiosk/clock/*`

**Spec says** in 6 places (R3.1, design §1, §5, §7.1, etc.): the routes are `/kiosk/clock/lookup` and `/kiosk/clock/action`.

**Reality**: kiosk router is mounted at prefix `/api/v1/kiosk` (verified at `app/main.py:364`). Every existing kiosk endpoint is `/api/v1/kiosk/check-in`, `/api/v1/kiosk/vehicle-lookup`, `/api/v1/kiosk/customer-lookup`.

**Impact:**
- Frontend kiosk app already references `/api/v1/kiosk/check-in` (verified at `mobile/src/screens/kiosk/KioskScreen.tsx:160`). Any new `/kiosk/clock/*` paths in the spec would 404.
- The mobile app and frontend kiosk pages would have no working endpoint to call.

**Fix:** Replace every `/kiosk/clock/*` reference with `/api/v1/kiosk/clock/*`. Six occurrences across requirements.md, design.md, tasks.md.

### 2.3 ⚠️ `/api/v1` (kiosk) vs `/api/v2` (everything else in P3) inconsistency

P3 mounts most new endpoints at `/api/v2/...` (per `mobile-app.md` steering: "All new endpoints land at `/api/v2/...`"). But kiosk lives at `/api/v1/kiosk/...`. So:

| Endpoint | Final path |
|---|---|
| Kiosk lookup | `/api/v1/kiosk/clock/lookup` |
| Kiosk action | `/api/v1/kiosk/clock/action` |
| Self-service action | `/api/v2/staff/me/clock-action` |
| Hours tab list | `/api/v2/staff/:id/clock` |
| Approve week | `/api/v2/staff/:id/timesheets/:week_start/approve` |
| Shift swaps | `/api/v2/shift-swaps/...` |
| Running-late | `/api/v2/staff/me/running-late` |

This isn't a bug — it's actually the right call (kiosk module is v1 because it pre-dates the v2 convention, and re-mounting it at v2 would break the existing customer-facing kiosk app). But the spec should explicitly call this out so future readers don't think the inconsistency is a mistake.

**Fix:** Add a note to design §5: "Kiosk endpoints retain the `/api/v1` prefix to coexist with the existing customer-facing kiosk module. All other new P3 endpoints use `/api/v2`."

### 2.4 ⚠️ `photo_upload_id` source endpoint ambiguous

**Spec says** in R3.5 and design §7.1: the kiosk app calls `POST /api/v2/uploads` first, gets `photo_upload_id`, then passes it to the clock-action. The "uploads" endpoint is referred to generically.

**Reality** at `app/modules/uploads/router.py`: only two POST endpoints exist — `POST /api/v2/uploads/receipts` and `POST /api/v2/uploads/attachments`. There is no plain `POST /api/v2/uploads`. They both return `{file_key, file_name, file_size}` — note the field is `file_key`, not `upload_id` (the term "upload_id" never appears in the upload module). The "ID" used to reference the file later is `file_key`, which encodes path category + org + UUID + extension.

**Impact:**
- Spec's `photo_upload_id` parameter doesn't match the response field. Need to be consistent: either rename to `photo_file_key` (matches actual return), OR make the kiosk module accept `file_key` and call it `photo_upload_id` internally for clarity (but be sure the schema documents the mapping).
- Picking `attachments` vs `receipts` matters: `attachments` is for invoices, `receipts` for expenses. Neither category is right for clock-in photos. **Spec needs to add a third upload category** like `staff_clock_photos` (or call it `staff_attachments`) to keep storage organized + match the existing `category/org_id/file_id` path structure.

**Fix:**
- Add a new upload endpoint `POST /api/v2/uploads/clock-photos` that mirrors `_store(content, filename, org_id, "clock_photos", db)` — adds the third category to the existing `_store` helper.
- Rename `photo_upload_id` to `photo_file_key` throughout the spec to match the existing returned field name.
- Document the path: `clock_photos/<org_id>/<uuid>.{jpg,png}`.

### 2.5 ❌ Dependency drift: `organisations.overtime_handling` was moved to JSONB by P2 verification — P3 R6a.2 still treats it as a typed column

**Spec R6a.2 says**: "re-use the existing `organisations.overtime_handling` column added in Phase 2 R10.2 (`pay_cash | toil | employee_chooses`) — Phase 3 does NOT duplicate this; it lives separately as a typed column, not inside `overtime_policy` JSONB."

**Reality**: Phase 2's `code-verification.md` §2.5 flagged this as "🟠 should fix — `overtime_handling` should live in `organisations.settings` JSONB, not a real column" — and the recommended fix was applied to P2 (move into `SETTINGS_JSONB_KEYS`). However, the P2 spec text still describes it as a typed column. The actual implementation outcome is ambiguous depending on whether the user accepts the P2 should-fix or not.

**Impact:**
- P3's `compute_week_totals` reads `org.overtime_handling` — if P2 ships with it as a JSONB key, the read becomes `org.settings.get('overtime_handling', 'pay_cash')`.
- The validation logic for `overtime_handling IN ('pay_cash','toil','employee_chooses')` moves from a DB CHECK constraint to application-level validation.

**Fix:** Pick one and lock it in:
- **Option A (recommended, consistent with P2 verification recommendation):** `overtime_handling` lives in `organisations.settings` JSONB. P3 code reads it as `org.settings.get('overtime_handling', 'pay_cash')`. Both P2 and P3 specs need updating to reflect this. P2 task A1 should add `'overtime_handling'` to `SETTINGS_JSONB_KEYS` (per P2 verification §2.5).
- **Option B (override P2 verification):** Keep `overtime_handling` as a typed column; P3 R6a.2 stays as written. P2 verification §2.5 is downgraded from 🟠 to "decided otherwise".

Recommend Option A. Either way, P3 R6a.2 needs to be in sync with whichever P2 ships.

### 2.6 ⚠️ `WRITE_TASKS` set membership not declared for new tasks

**Spec C1 + C2** register `check_late_arrivals` (5-min) and `check_missed_clock_outs` (1-hr).

**Reality** at `app/tasks/scheduled.py:849-870`: the `WRITE_TASKS: set[str]` declares which task names cause writes (and so are skipped on standby HA nodes). Both new tasks SEND SMS (a write to provider + audit log), so both should be in `WRITE_TASKS`. **The spec doesn't declare this.**

**Impact:** If a new task isn't in `WRITE_TASKS`, it would run on the standby node, doubling SMS sends for any setup with HA replication. The tracker `ISSUE-164` (single-worker scheduler) is already deployed; this is the next layer down.

**Fix:** Tasks C1 and C2 must add a sub-bullet:
> Register the task name in `WRITE_TASKS` set (line 849 of `scheduled.py`) so it's skipped on standby HA nodes.

### 2.7 ⚠️ `metadata` column on `time_clock_entries` — naming collision with reserved word

**Spec design §3.1** adds a `metadata jsonb NOT NULL DEFAULT '{}'::jsonb` column to `time_clock_entries`.

**Reality**: `metadata` is a SQLAlchemy reserved attribute name on the `Base.metadata` class-level (the SchemaItem registry). When you declare a column called `metadata` on a SQLAlchemy `DeclarativeBase` subclass, you get an `InvalidRequestError: Attribute name 'metadata' is reserved when using the Declarative API`. Tested with SQLAlchemy 2.0+.

**Impact:** ORM model definition would fail at startup. Mypy/Pyright would also flag the conflict.

**Fix:** Rename the column to `entry_metadata` or `flags` (the latter is shorter and matches the actual semantic — flagged_for_review is a flag). Update the model + migration + jsonb_set call sites + frontend types. The `audit_log` table already uses a similar pattern with `before_value` / `after_value` instead of `metadata`.

Suggested name: `flags jsonb NOT NULL DEFAULT '{}'::jsonb`. Sub-keys: `flags.flagged_for_review`, `flags.review_reason`, `flags.flagged_by`. SQL pattern stays identical (`jsonb_set(coalesce(flags, '{}'::jsonb), '{flagged_for_review}', 'true'::jsonb)`).

### 2.8 ⚠️ `time_tracking_v2.update_entry` already blocks edits when `is_invoiced=true`

**Spec G7** says "the existing time_tracking_v2 module is a separate concern" and that `is_invoiced UPDATE on a time_entries row inside an approved week still succeeds".

**Reality** at `app/modules/time_tracking_v2/service.py:172-184`: `update_entry` raises `ValueError("Cannot update an invoiced time entry")` when `entry.is_invoiced is True`. So it's not "still succeeds" — there's already an existing lock on invoiced entries. The G7 test in tasks E1 should be:

> "Approve a week → mark a `time_entries` row as invoiced (`is_invoiced=true`) via the existing `add_to_invoice` flow → attempt PUT on that row → expect 400/422 because of the EXISTING `is_invoiced` lock, NOT because of the timesheet-approval lock. Approve a week → attempt PUT on a *non-invoiced* `time_entries` row inside that window → succeeds. The G7 test asserts the timesheet approval flow does NOT add a new lock."

**Fix:** Update the G7 verification text in tasks E1 to clarify: the existing `is_invoiced` lock from `time_tracking_v2` is the only thing that blocks edits to billable timer rows; Phase 3 does not add a second lock.

### 2.9 ⚠️ `GET /api/v2/staff/:id/clock` — the path collides with `/api/v2/staff/:id/clock/break-start`

**Spec design §5** lists:
- `GET /api/v2/staff/:id/clock` — list entries for the week
- `POST /api/v2/staff/:id/clock/break-start` — begin break
- `POST /api/v2/staff/:id/clock/break-end` — end break
- `POST /api/v2/staff/:id/clock/manual` — admin manual entry
- `POST /api/v2/staff/:id/clock/:entry_id/flag` — flag for review

**Reality**: FastAPI path matching is order-dependent within the router but it does correctly distinguish `/clock` from `/clock/break-start`. However the `:entry_id` segment in `/clock/:entry_id/flag` will accidentally match `break-start` and `break-end` strings as if they were UUIDs unless the path is structured as `/clock/entry/:entry_id/flag` or `/clock/:entry_id/flag` is moved before the named-action routes in registration order.

**Fix:** Restructure the `:entry_id`-keyed routes:
- `/api/v2/staff/:id/clock-entries/:entry_id/flag` (uses a different parent segment to disambiguate)
- OR keep `/clock/:entry_id/flag` but register specific named routes (`break-start`, `break-end`, `manual`) FIRST so FastAPI matches them before the catch-all `:entry_id`.

Both approaches work; first one is clearer and avoids router-order foot-guns. Update spec §5 + tasks B7.

### 2.10 ⚠️ `compute_change_sms_body(...)` called but not defined

**Spec design §4.6** invokes `compose_change_sms_body(entry_before, entry_after, change_type, staff)` — note the actual call uses `compose_` but the docstring earlier says `compute_`. Either way, the function is referenced but its implementation isn't sketched in the spec.

**Fix:** Either inline a stub showing the SMS body composition (160-char SMS templates) or explicitly mark it as TBD in implementation. The text matters because:
- `staff_id` change → "Your shift on Sat 5 Jun 10–4 has been reassigned." (to outgoing) and "You're now on the Sat 5 Jun 10–4 shift." (to incoming).
- `start_time`/`end_time` change → "Your shift on Sat 5 Jun changed: now 12–4 (was 10–4)."

These need character-count verification (some local-time formats blow past 160 chars, forcing UCS-2 encoding which doubles SMS cost). Spec G7 (Māori macrons) from Phase 1 already flagged this for SMS encoding considerations.

**Fix:** Add to design §4.6 a small helper-spec block with the three template strings + their length classification (`gsm-7` vs `ucs-2`).

### 2.11 ⚠️ `find_in_window_shift(db, staff.id, window=...)` not defined

**Spec design §4.7** calls `find_in_window_shift(db, staff.id, window=(now() - 60min, now() + 120min))` — function not specified.

**Fix:** Add design block:
```python
async def find_in_window_shift(db, staff_id, *, window):
    """Return the single schedule_entries row for this staff whose
    start_time falls within `window`. Picks the closest to now() if
    multiple. Returns None if none found.
    """
    from_dt, to_dt = window
    stmt = (select(ScheduleEntry)
            .where(ScheduleEntry.staff_id == staff_id,
                   ScheduleEntry.start_time.between(from_dt, to_dt),
                   ScheduleEntry.entry_type.in_(['job','booking','other']),
                   ScheduleEntry.status != 'cancelled')
            .order_by(func.abs(extract('epoch', ScheduleEntry.start_time - now()))))
    return (await db.execute(stmt.limit(1))).scalar_one_or_none()
```

### 2.12 ⚠️ Photo RBAC — `useRole(['org_admin','branch_admin','location_manager'])` hook signature

**Spec design §6.2** uses `const isAdmin = useRole(['org_admin','branch_admin','location_manager'])` — a frontend hook.

**Reality**: there's no `useRole` hook in the codebase today. Frontend role checks today use `user?.role === 'org_admin'` from `useAuth()` directly (verified at `frontend/src/pages/settings/Settings.tsx:78` and many others).

**Fix:** Either create a new `useRole` helper (`frontend/src/hooks/useRole.ts`) that wraps `useAuth()` and accepts a list, OR change the design example to use the existing pattern:

```tsx
const { user } = useAuth()
const isAdmin = ['org_admin', 'branch_admin', 'location_manager'].includes(user?.role || '')
```

Recommendation: create the `useRole` helper (small, reusable). Add to tasks D2 explicitly so it's not skipped.

### 2.13 ⚠️ Manager-resolution helper `resolve_manager(db, staff)` not defined

**Spec design §4.7** uses `manager = await resolve_manager(db, staff)` and §R14b mentions "the staff's manager (`reporting_to` chain, or org owner if none)".

**Reality**: `staff_members.reporting_to` is a self-FK to another staff member. The "org owner" is the user with `role='org_admin'`. Resolving "manager" needs:
1. Walk `staff.reporting_to` → look up the target staff record → if their `user_id` is set, use that user.
2. If no chain or chain ends without a `user_id`, fall back to `users WHERE org_id=:org_id AND role='org_admin' LIMIT 1`.

**Fix:** Add the `resolve_manager` helper sketch to design §4.7:
```python
async def resolve_manager(db, staff: StaffMember) -> User | None:
    """Walk reporting_to chain, return the first manager with a user_id.
    Falls back to org_admin if no chain leads to a user."""
    seen = set()
    cursor = staff
    while cursor.reporting_to and cursor.reporting_to not in seen:
        seen.add(cursor.id)
        manager_staff = await db.get(StaffMember, cursor.reporting_to)
        if not manager_staff:
            break
        if manager_staff.user_id:
            return await db.get(User, manager_staff.user_id)
        cursor = manager_staff
    # Fallback to first org_admin
    stmt = select(User).where(User.org_id == staff.org_id, User.role == 'org_admin').limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()
```

### 2.14 ⚠️ Missing User import in design code blocks

Design code blocks reference `User`, `Organisation`, `StaffMember`, `ScheduleEntry`, `ShiftSwapRequest`, `TimeClockEntry`, `LeaveLedger` etc. without explicit import statements. Acceptable for design pseudocode but tasks B1/B6/B7 need to spell out the actual imports needed.

**Fix:** Tasks B1 explicitly lists the imports; tasks B6 + B7 reference `from app.modules.staff.models import StaffMember`, `from app.modules.scheduling_v2.models import ScheduleEntry`, etc. Trivial cleanup.

### 2.15 ⚠️ `now()` in `db.execute` clauses — Postgres vs Python timezone

**Spec design §4.6 and §4.7** mix Python `now()` (`datetime.now(timezone.utc)`) with Postgres `func.now()`. The dedupe Redis key uses Python `now()`. The `late:{shift.id}` snooze TTL uses Python `timedelta` math. The `find_in_window_shift` query uses Postgres `now()` via `func.now()`.

**Impact:** If the app server clock and Postgres server clock are within milliseconds (which they should be on the same machine), no issue. On HA configs where the standby is a different machine the clocks could drift by seconds. Spec doesn't address this.

**Fix:** Lock down the convention: "All time comparisons in P3 service code use Python `datetime.now(timezone.utc)` consistently. SQL queries that compare server-time use `func.now()` AT TIME ZONE 'UTC' explicitly. Redis TTLs are computed in Python." Trivial doc clarification in design §4 prelude.

---

## 3. G1–G17 amendments — verified consistent (with the §2 fixes applied)

| Gap | Status | Notes |
|---|---|---|
| **G1** Overtime policy JSONB + threshold-aware compute_week_totals | ✅ | §2.5 alignment with P2 needed; otherwise sound. |
| **G2** Roster-change SMS hook | ✅ | §2.10 (`compose_change_sms_body` definition) + §2.6 (WRITE_TASKS membership) trivially fixable. The `reschedule` method name (§2.0 entry above) needs correction in tasks B7a too. |
| **G3** Running-late endpoint | ✅ | §2.11 (`find_in_window_shift`) + §2.13 (`resolve_manager`) helpers need definitions. Otherwise sound. |
| **G4** SLO table | ✅ | Fine — these are aspirational targets that will be measured post-deploy. |
| **G6** Cover broadcast eligibility filter | ✅ | Filter is pure SQL; nothing else to verify. |
| **G7** time_entries lock scope | ⚠️ | §2.8 — the verification text needs nuance because `is_invoiced` is already a lock. |
| **G8** Manager-approval shift swap | ✅ | State machine is sound; design §4.8 covers eligibility re-check at flip. |
| **G9** default_channel propagation | ✅ | Cross-phase patch to P1 service is well-specified. The `Optional[bool] = None` schema change is correct. |
| **G10** Photo review with RBAC | ✅ | §2.12 (useRole hook) + §2.7 (rename `metadata` to `flags`) are the only blockers. |
| **G12** Kiosk lookup rate-limit | ✅ | SHA-256 hashing + `INCR + EXPIRE 60` pattern is sound. The kiosk routes still need to live behind `require_role("kiosk")` per §2.1, so the rate limit is on top of the existing kiosk-rate-limit (30/min/user). |
| **G13** SMS notification matrix | ✅ | Matrix is concrete, all 7 events covered. |
| **G15** Photo retention 6 years | ✅ | No code change needed; Non-Goals documented. |
| **G16** edited_after_approval test | ✅ | Test is in tasks E1; flow already specified in design §4.2. |
| **G17** Per-branch geofence radius | ✅ | Override semantics clear; backfill sound. |

---

## 4. Summary verdict

**Phase 3 spec is NOT yet implementation-ready.** Two critical drifts (§2.1 kiosk auth model; §2.2 path prefix) would cause the kiosk flow to either 401 or 404 depending on which is hit first. Three more drifts (§2.4 photo upload endpoint, §2.5 overtime_handling source, §2.7 SQLAlchemy `metadata` reserved name) would cause runtime crashes. The remaining items are stylistic/clarity fixes.

### Mandatory fixes before code lands

| Priority | Fix |
|---|---|
| 🔴 Must fix | **§2.1** — Kiosk routes use `require_role("kiosk")`; spec text "no auth required" is wrong. |
| 🔴 Must fix | **§2.2** — Path prefix is `/api/v1/kiosk/clock/*`, not `/kiosk/clock/*`. |
| 🔴 Must fix | **§2.4** — Add `POST /api/v2/uploads/clock-photos`; rename `photo_upload_id` → `photo_file_key`. |
| 🔴 Must fix | **§2.5** — Lock down `overtime_handling` storage location (recommend JSONB per P2 verification §2.5). |
| 🔴 Must fix | **§2.7** — Rename `metadata` column to `flags` (SQLAlchemy reserves `metadata` on Base). |
| 🟠 Should fix | **§2.0/G2** — `reschedule` method name (NOT `reschedule_entry`). |
| 🟠 Should fix | **§2.6** — Add `WRITE_TASKS` set membership for the two new scheduled tasks. |
| 🟠 Should fix | **§2.9** — Restructure `/clock/:entry_id/flag` route to avoid catch-all collision with `/clock/break-start`. |
| 🟠 Should fix | **§2.10** — Define `compose_change_sms_body` SMS templates + length classification. |
| 🟠 Should fix | **§2.11** — Define `find_in_window_shift` helper. |
| 🟠 Should fix | **§2.12** — Define `useRole` hook OR change design to use `useAuth()` directly. |
| 🟠 Should fix | **§2.13** — Define `resolve_manager` helper. |
| 🟡 Doc cleanup | **§2.3** — Add note explaining `/api/v1` (kiosk) vs `/api/v2` (rest) coexistence. |
| 🟡 Doc cleanup | **§2.8** — Clarify G7 test against existing `is_invoiced` lock. |
| 🟡 Doc cleanup | **§2.14** — Spell out imports in tasks B1/B6/B7. |
| 🟡 Doc cleanup | **§2.15** — Lock down `now()` convention (Python vs Postgres). |

Estimated edit time for the five 🔴 must-fix items: ~45 minutes. The seven 🟠 items add another 30 minutes. Total: ~75 minutes to make P3 implementation-ready.

The core architectural decisions (kiosk-default clock-in flow, mandatory photo, opt-in self-service, break recording, weekly approval with locking, overtime split, TOIL accrual, shift swap with optional manager approval, cover broadcast with eligibility filter, late-arrival/missed-clock-out SMS, running-late upward message, roster-change SMS within 48h, RBAC-gated photo review with flag-for-review acknowledgement at approve) are all sound and verified. None require redesign.
