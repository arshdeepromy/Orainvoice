# Staff Management Phase 3 — Design

## 1. Architecture overview

Phase 3 adds the operational layer. New module `app/modules/time_clock/` for clock-in/out + breaks + approvals + overtime + swaps + cover. Reuses Phase 1's `sms_sender.py` and existing kiosk router pattern.

Backend touches:
- `alembic/versions/0207_time_clock_schema.py`
- `alembic/versions/0208_time_clock_indexes.py`
- `app/modules/time_clock/{models,schemas,service,router}.py`
- `app/modules/time_clock/breaks.py` — break logic.
- `app/modules/time_clock/approvals.py` — week approval + locking.
- `app/modules/time_clock/swaps.py`, `cover.py`, `overtime.py`.
- `app/modules/kiosk/router.py` extension — staff clock-in routes added at `/api/v1/kiosk/clock/lookup` and `/api/v1/kiosk/clock/action`, both gated by the same `dependencies=[require_role("kiosk"), Depends(_check_kiosk_rate_limit)]` pattern as the existing `POST /api/v1/kiosk/check-in` endpoint (verified at `app/modules/kiosk/router.py:108`). STAFF-006 settled — shared kiosk surface with a "Staff" tile, mirroring the customer-facing kiosk app.
- `app/modules/uploads/router.py` extension — adds a third upload endpoint `POST /api/v2/uploads/clock-photos` calling `_store(content, filename, org_id, "clock_photos", db)`. Files land at `/app/uploads/clock_photos/<org_id>/<uuid>.{jpg,png}`. Returns `{ file_key, file_name, file_size }` (same shape as existing `/receipts` and `/attachments`).
- `app/tasks/scheduled.py` — register `check_late_arrivals` (300s, name `check_late_arrivals`) and `check_missed_clock_outs` (3600s, name `check_missed_clock_outs`). **Both task names must be added to the `WRITE_TASKS` set at `scheduled.py:849`** so they are skipped on standby HA nodes (preventing duplicate SMS sends).
- `app/main.py` — include the time_clock router.

Frontend touches:
- `frontend/src/pages/staff/tabs/HoursTab.tsx`
- `frontend/src/pages/kiosk/KioskClockScreen.tsx` (new section in existing kiosk app)
- `frontend/src/pages/staff/me/SelfServiceClockScreen.tsx`
- `frontend/src/pages/swaps/ShiftSwapPage.tsx` + cover.
- `frontend/src/pages/settings/people/ClockInPolicyPage.tsx`
- `frontend/src/pages/staff/components/OvertimeRequestModal.tsx`
- `mobile/src/screens/clock/ClockScreen.tsx`

## 2. Navigation & Access

- **Hours tab** added to Staff Detail tab strip (between Roster and Leave).
- **Settings → People → Clock-in Policy** — new sub-route.
- **Sidebar items:** "Open shifts" (cover), "Shift swaps" — visible when module enabled, scoped by role.
- **Mobile route:** `/clock` in mobile app, lazy-loaded.
- **Web staff self-service:** `/staff/me/clock` route, gated by `self_service_clock_enabled` flag.
- **Kiosk:** existing welcome screen at `/kiosk` gets a new "Staff Clock-in" tile alongside the existing customer-facing tiles.

## 3. Data Model

### 3.1 Migration `0207_time_clock_schema.py`

> Note: per the code-verification report (`staff-management-p1/code-verification.md` §"Open verification gaps"), this migration also adds geofence columns to `branches` because the table currently has no `lat`/`lng` columns. Without this addition the self-service geofence policy in R4 has no anchor.

```sql
ALTER TABLE branches
    ADD COLUMN IF NOT EXISTS lat numeric(9,6),
    ADD COLUMN IF NOT EXISTS lng numeric(9,6),
    ADD COLUMN IF NOT EXISTS geofence_radius_metres int NOT NULL DEFAULT 200;
```

Then the new tables:

```sql
CREATE TABLE IF NOT EXISTS time_clock_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    staff_id uuid NOT NULL REFERENCES staff_members(id),
    clock_in_at timestamptz NOT NULL,
    clock_out_at timestamptz,
    source text NOT NULL CHECK (source IN ('kiosk','self_service_mobile','self_service_web','admin_manual')),
    clock_in_photo_url text,
    clock_out_photo_url text,
    clock_in_lat numeric(9,6),
    clock_in_lng numeric(9,6),
    clock_out_lat numeric(9,6),
    clock_out_lng numeric(9,6),
    scheduled_entry_id uuid REFERENCES schedule_entries(id),
    break_minutes int NOT NULL DEFAULT 0,
    notes text,
    created_by uuid REFERENCES users(id),
    worked_minutes int,
    flags jsonb NOT NULL DEFAULT '{}'::jsonb,  -- G10: holds flagged_for_review + review_reason. Named 'flags' (NOT 'metadata') because SQLAlchemy DeclarativeBase reserves the 'metadata' attribute name on the class — declaring a column called 'metadata' raises InvalidRequestError at startup.
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source <> 'kiosk' OR clock_in_photo_url IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS break_records (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    time_clock_entry_id uuid NOT NULL REFERENCES time_clock_entries(id) ON DELETE CASCADE,
    break_type text NOT NULL CHECK (break_type IN ('rest_paid','meal_unpaid')),
    start_at timestamptz NOT NULL,
    end_at timestamptz,
    minutes int,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS timesheet_approvals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    staff_id uuid NOT NULL REFERENCES staff_members(id),
    week_start date NOT NULL,
    week_end date NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','edited_after_approval')),
    total_worked_minutes int,
    total_scheduled_minutes int,
    total_overtime_minutes int NOT NULL DEFAULT 0,
    total_break_minutes int NOT NULL DEFAULT 0,
    ordinary_minutes int NOT NULL DEFAULT 0,
    public_holiday_minutes int NOT NULL DEFAULT 0,
    toil_choice text CHECK (toil_choice IN ('pay_cash','toil')),
    approved_by uuid REFERENCES users(id),
    approved_at timestamptz,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (staff_id, week_start)
);

CREATE TABLE IF NOT EXISTS overtime_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    staff_id uuid NOT NULL REFERENCES staff_members(id),
    schedule_entry_id uuid REFERENCES schedule_entries(id),
    proposed_extra_minutes int NOT NULL,
    reason text,
    requested_by uuid NOT NULL REFERENCES users(id),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    decided_by uuid REFERENCES users(id),
    decided_at timestamptz,
    decision_notes text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shift_swap_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    requester_staff_id uuid NOT NULL REFERENCES staff_members(id),
    target_staff_id uuid REFERENCES staff_members(id),
    schedule_entry_id uuid NOT NULL REFERENCES schedule_entries(id),
    -- G8 — 'awaiting_manager' is the new state when manager approval is required.
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','awaiting_manager','accepted','rejected','cancelled')),
    reason text,
    decided_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz
);

CREATE TABLE IF NOT EXISTS shift_cover_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    schedule_entry_id uuid NOT NULL REFERENCES schedule_entries(id),
    requester_staff_id uuid NOT NULL REFERENCES staff_members(id),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','accepted','cancelled','expired')),
    accepted_by uuid REFERENCES staff_members(id),
    broadcast_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    accepted_at timestamptz
);

ALTER TABLE organisations
    ADD COLUMN IF NOT EXISTS clock_in_policy jsonb NOT NULL DEFAULT '{
        "default_channel": "kiosk_only",
        "self_service_require_photo": true,
        "self_service_require_geofence": false,
        "branch_radius_metres": 200,
        "allow_late_clock_out_edits": true,
        "kiosk_employee_id_rate_limit": 10,
        "shift_swap_requires_manager_approval": false
    }'::jsonb;

-- G1 — overtime policy lives in a separate JSONB column so it's not
-- tangled with clock-in concerns. The overtime_handling enum from
-- Phase 2 (organisations.overtime_handling text column) stays where it
-- is — typed at the column level, not nested.
ALTER TABLE organisations
    ADD COLUMN IF NOT EXISTS overtime_policy jsonb NOT NULL DEFAULT '{
        "weekly_threshold_minutes": 2400,
        "daily_threshold_minutes": 480,
        "require_pre_approval": false
    }'::jsonb;
```

All new tables get `ENABLE ROW LEVEL SECURITY` + `tenant_isolation` policy.

**Geofence radius — per-branch vs org default (G17):** the migration above sets `clock_in_policy.branch_radius_metres = 200` as the org-level default applied when new branches are created. The per-branch `branches.geofence_radius_metres` column (added at the top of this migration) is the authoritative value at clock-in time. The migration backfills existing branches' `geofence_radius_metres` from the org-level default once at upgrade; subsequent changes to either value are independent. Spec R6.4 documents this.

**Photo retention (G15):** Phase 3 ships NO scheduled deletion job for clock-in/out photos. Per `Non-Goals`, the default policy is 6-year retention matching Holidays Act s81. Photos persist in `uploads` even when their `time_clock_entries` row is hard-deleted by admin manual flow; the future cleanup task is a Phase 6+ concern. No DDL implication here — `time_clock_entries.clock_in_photo_url` / `clock_out_photo_url` are nullable text columns, not FKs.

### 3.2 Indexes (`0208_time_clock_indexes.py`) — CONCURRENTLY pack

- `idx_time_clock_org_staff_date ON time_clock_entries (org_id, staff_id, clock_in_at DESC)`
- `idx_time_clock_open ON time_clock_entries (staff_id) WHERE clock_out_at IS NULL`
- `idx_time_clock_org_open ON time_clock_entries (org_id, clock_in_at) WHERE clock_out_at IS NULL`
- `idx_break_records_entry ON break_records (time_clock_entry_id)`
- `idx_timesheet_approvals_org_status ON timesheet_approvals (org_id, status, week_start DESC)`
- `idx_timesheet_approvals_staff ON timesheet_approvals (staff_id, week_start DESC)`
- `idx_overtime_requests_org_status ON overtime_requests (org_id, status, created_at DESC)`
- `idx_shift_swaps_status ON shift_swap_requests (org_id, status, created_at DESC)`
- `idx_shift_cover_status ON shift_cover_requests (org_id, status, broadcast_at DESC)`

## 4. Service layer

### 4.1 Clock-in service `app/modules/time_clock/service.py`

```python
async def lookup_for_kiosk(db, org_id, employee_id):
    """Returns (staff_id, first_name, on_file_photo_url, currently_clocked_in) or raises 422 not_found.
    Two-layer rate limit (P3-N9): dependency-level `_check_kiosk_rate_limit` (30/min/kiosk-user)
    runs before service body; inline G12 check (10/min/(org_id, sha256(employee_id)),
    distinct 429 body) runs at top of service. See R3.3 for the body shapes."""

async def kiosk_clock_action(db, *, org_id, staff_id, action, photo_file_key):
    """Handles in/out with mandatory photo. Auto-matches scheduled_entry_id.
    (P3-N1: parameter renamed from `photo_upload_id` to match the canonical
    `_store(...)` return key `file_key`.)"""

async def self_service_clock_action(db, *, org_id, staff_id, action, photo_file_key, lat, lng, source):
    """Refuses 403 when self_service_clock_enabled=false. Honours geofence + photo policy.
    (P3-N1: same rename.)"""

async def admin_manual_entry(db, *, org_id, staff_id, clock_in_at, clock_out_at, ...):
    """Manual edit, audit-logged."""

async def start_break(db, time_clock_entry_id, break_type):
    """Insert break_records row."""

async def end_break(db, time_clock_entry_id):
    """Set end_at, compute minutes, update parent entry's break_minutes if meal_unpaid."""
```

### 4.2 Approvals service `app/modules/time_clock/approvals.py`

```python
async def compute_week_totals(db, staff_id, week_start):
    """Aggregates time_clock_entries + break_records + schedule_entries × public_holidays.
    Returns dict ready for upsert into timesheet_approvals.

    G1 — splits total_worked_minutes into ordinary + overtime using the org's
    overtime_policy:

        org = await load_organisation(db, org_id)
        pol = org.overtime_policy  # jsonb
        weekly_threshold = pol['weekly_threshold_minutes']  # default 2400
        daily_threshold  = pol['daily_threshold_minutes']   # default 480

        # 1) Per-day overtime contribution.
        daily_ot = 0
        for day in week_days(week_start):
            day_minutes = sum_worked_minutes_for_day(staff_id, day) - day_break_minutes(staff_id, day)
            if day_minutes > daily_threshold:
                daily_ot += day_minutes - daily_threshold

        # 2) Weekly-threshold contribution, not double-counted.
        week_worked = total_worked_minutes  # sum across the week, breaks deducted
        weekly_ot_candidate = max(0, week_worked - weekly_threshold)
        weekly_ot = max(0, weekly_ot_candidate - daily_ot)

        total_overtime_minutes = daily_ot + weekly_ot
        public_holiday_minutes = compute_public_holiday_worked_minutes(...)
        ordinary_minutes = (week_worked
                            - total_overtime_minutes
                            - public_holiday_minutes)

        # G1.5 — unapproved-overtime warning.
        if pol['require_pre_approval'] and total_overtime_minutes > 0:
            approved_request_minutes = sum_approved_overtime_requests(staff_id, week_start)
            unapproved = max(0, total_overtime_minutes - approved_request_minutes)
            if unapproved > 0:
                notes_append(f'unapproved_overtime: {unapproved}min — no overtime_request was approved')
    """

async def approve_week(db, staff_id, week_start, approved_by, toil_choice=None):
    """Upserts timesheet_approvals; locks edits; if org policy is toil → grants TOIL leave.

    NOTE: only locks time_clock_entries (G7). The existing time_tracking_v2
    billable-timer table is not touched by this flow.
    """

async def reopen_week(db, staff_id, week_start):
    """Status='edited_after_approval'; unlocks edits."""

async def lock_check(db, staff_id, when_dt) -> bool:
    """Used by service to refuse PUT/DELETE on entries inside an approved week.
    Scope: time_clock_entries only (per G7)."""
```

### 4.3 Late-arrival + missed-clock-out tasks

```python
async def check_late_arrivals():
    """Every 5 min. For each org with module enabled.
    Selects schedule_entries WHERE start_time BETWEEN now()-15min AND now()
        AND NOT EXISTS open clock entry.
    Per-shift dedupe via Redis SET key 'late:{shift_id}' EX 8h."""

async def check_missed_clock_outs():
    """Every hour. SELECT FROM time_clock_entries WHERE clock_out_at IS NULL AND clock_in_at < now()-12h."""
```

### 4.4 Self-service refusal flow

The `/api/v2/staff/me/clock-action` endpoint:

```python
async def clock_action(request, payload, db):
    user = request.state.user_id
    staff = await load_staff_for_user(db, user)
    if not staff or not staff.self_service_clock_enabled:
        raise HTTPException(403, {"detail": "self_service_disabled"})
    # ... policy checks (photo, geofence) ... insert/update entry
```

### 4.5 `StaffService.create_staff` extension for `default_channel` (G9)

This is a Phase 3 patch to Phase 1's `app/modules/staff/service.py` (cross-phase change — see R6b):

```python
async def create_staff(self, org_id, payload):
    # If caller didn't explicitly set self_service_clock_enabled,
    # read the org's clock_in_policy.default_channel and apply.
    if payload.self_service_clock_enabled is None:
        org = await self.db.get(Organisation, org_id)
        default_channel = (org.clock_in_policy or {}).get('default_channel', 'kiosk_only')
        payload.self_service_clock_enabled = (default_channel == 'kiosk_and_self_service')
    # ... existing create_staff body ...
```

The Pydantic schema `StaffMemberCreate` makes `self_service_clock_enabled` an `Optional[bool] = None` (not `False`) so the service can distinguish "caller didn't specify" from "caller explicitly said false".

### 4.6 Roster-change SMS hook (G2)

Implemented as a hook fired from `app/modules/scheduling_v2/service.py` write paths (`update_entry`, `reschedule` — note real method is named `reschedule` not `reschedule_entry`, verified at `service.py:215` — plus shift-swap acceptance and cover acceptance in the time_clock module):

`compose_change_sms_body(entry_before, entry_after, change_type, staff)` produces one of these 160-char-budget templates (length-classified GSM-7 vs UCS-2 — Māori macrons force UCS-2, halving the per-segment limit, see Phase 1 G7):

| change_type | Template (≈ within GSM-7 160 chars when names are < 30 chars) |
|---|---|
| `staff_reassigned` (to outgoing staff) | `Your shift on {weekday} {dd_mmm} {hhmm}–{hhmm} has been reassigned. Open the app for details.` |
| `staff_reassigned` (to incoming staff) | `You're now on the {weekday} {dd_mmm} {hhmm}–{hhmm} shift. Open the app for details.` |
| `time_changed` | `Your shift on {weekday} {dd_mmm} changed: now {new_start}–{new_end} (was {old_start}–{old_end}).` |

```python
async def _emit_roster_change_sms(db, *, entry_before, entry_after, change_type):
    """Fire-and-forget SMS notifications for in-window roster changes."""
    if entry_after.start_time > now() + timedelta(hours=48):
        return  # too far out — Friday auto-broadcast handles it
    # P3-N10: skip cancelled entries — a cancelled-then-edited entry is
    # effectively dead and SMS-ing the staff would be misleading.
    if entry_after.status == 'cancelled':
        await write_audit_log(action='roster.change_sms_skipped',
                              entity_type='schedule_entry', entity_id=entry_after.id,
                              after_value={'reason': 'cancelled_entry'})
        return
    redis_key = f'roster_change:{entry_after.id}'
    if not await redis.set(redis_key, '1', nx=True, ex=3600):
        return  # already sent in last hour
    affected_staff_ids = []
    if change_type == 'staff_reassigned':
        if entry_before.staff_id:
            affected_staff_ids.append(entry_before.staff_id)
        if entry_after.staff_id:
            affected_staff_ids.append(entry_after.staff_id)
    elif change_type in ('time_changed',):
        affected_staff_ids.append(entry_after.staff_id)
    for staff_id in affected_staff_ids:
        staff = await db.get(StaffMember, staff_id)
        if not staff.weekly_roster_sms_enabled:
            await write_audit_log(action='roster.change_sms_skipped',
                                  after_value={'staff_id': str(staff_id), 'reason': 'opt_out'})
            continue
        if not staff.phone:
            await write_audit_log(action='roster.change_sms_skipped',
                                  after_value={'staff_id': str(staff_id), 'reason': 'no_phone'})
            continue
        body = compose_change_sms_body(entry_before, entry_after, change_type, staff)
        await send_sms(db, to_phone=staff.phone, body=body, dlq_task_name='roster_change_sms')
        await write_audit_log(action='roster.change_sms_sent',
                              entity_type='schedule_entry', entity_id=entry_after.id,
                              after_value={'staff_id': str(staff_id), 'change_type': change_type})
```

### 4.7 Running-late handler (G3)

Helpers (also used by other paths in §4):

```python
async def find_in_window_shift(db, staff_id, *, window) -> ScheduleEntry | None:
    """Return the staff's schedule_entries row whose start_time falls within
    `window` (a 2-tuple of timezone-aware datetimes). Picks the closest to
    now() if multiple. Returns None if none found."""
    from sqlalchemy import select, func, extract
    from app.modules.scheduling_v2.models import ScheduleEntry
    from_dt, to_dt = window
    stmt = (
        select(ScheduleEntry)
        .where(
            ScheduleEntry.staff_id == staff_id,
            ScheduleEntry.start_time.between(from_dt, to_dt),
            ScheduleEntry.entry_type.in_(['job', 'booking', 'other']),
            # P3-N7: positive set rather than `!= 'cancelled'` so future state
            # additions explicitly opt-in. Verified at scheduling_v2/models.py:21
            # ENTRY_STATUSES = ['scheduled', 'completed', 'cancelled'].
            ScheduleEntry.status.in_(['scheduled', 'completed']),
        )
        .order_by(func.abs(extract('epoch', ScheduleEntry.start_time - func.now())))
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def resolve_manager(db, staff: StaffMember) -> User | None:
    """Walk staff.reporting_to chain, return the first manager with a
    user_id. Falls back to first org_admin if no chain leads to a user.

    Cross-phase X7 — when no chain manager has a user_id, the running-late
    SMS goes to the org_admin fallback. The org admin should see this
    state ahead of time on the Overview tab so they can fix the chain
    before a real running-late event surprises them.
    """
    from app.modules.staff.models import StaffMember
    from app.modules.auth.models import User
    seen: set[uuid.UUID] = set()
    cursor = staff
    while cursor.reporting_to and cursor.reporting_to not in seen:
        seen.add(cursor.id)
        manager_staff = await db.get(StaffMember, cursor.reporting_to)
        if not manager_staff:
            break
        if manager_staff.user_id:
            return await db.get(User, manager_staff.user_id)
        cursor = manager_staff
    stmt = select(User).where(User.org_id == staff.org_id, User.role == 'org_admin').limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()
```

`POST /api/v2/staff/me/running-late`:

```python
async def report_running_late(request, payload, db):
    staff = await load_staff_for_user(db, request.state.user_id)
    # Find the in-window scheduled shift
    shift = await find_in_window_shift(db, staff.id,
        window=(now() - timedelta(minutes=60), now() + timedelta(minutes=120)))
    if not shift:
        raise HTTPException(422, {'detail': 'no_upcoming_shift'})
    # Per-shift rate limit — max 3 reports
    report_count_key = f'running_late_reports:{shift.id}'
    count = await redis.incr(report_count_key)
    if count == 1:
        await redis.expire(report_count_key, 14400)  # 4h TTL
    if count > 3:
        raise HTTPException(429, {'detail': 'too_many_late_reports'})
    # Send manager SMS
    manager = await resolve_manager(db, staff)
    if manager and manager.phone:
        body = (f"Heads up: {staff.first_name} expects to be {payload.minutes_late} min late "
                f"for {shift_label(shift)}." +
                (f" Reason: {payload.reason}" if payload.reason else ""))
        await send_sms(db, to_phone=manager.phone, body=body, dlq_task_name='running_late_sms')
    # Snooze the automated late-arrival check for this shift
    snooze_ttl = (payload.minutes_late + 30) * 60
    await redis.set(f'late:{shift.id}', '1', ex=snooze_ttl)
    await write_audit_log(action='staff.reported_late', entity_type='schedule_entry',
                          entity_id=shift.id,
                          after_value={'minutes_late': payload.minutes_late,
                                       'reason': payload.reason})
    return {'ok': True, 'snoozed_until': now() + timedelta(seconds=snooze_ttl)}
```

### 4.8 Shift-swap manager-approval workflow (G8) + notification matrix (G13)

```python
async def target_accepts_swap(db, swap_id, target_staff_id):
    swap = await db.get(ShiftSwapRequest, swap_id)  # FOR UPDATE
    if swap.target_staff_id != target_staff_id or swap.status != 'pending':
        raise HTTPException(409, {'detail': 'invalid_state'})
    org = await db.get(Organisation, swap.org_id)
    requires_manager = (org.clock_in_policy or {}).get('shift_swap_requires_manager_approval', False)
    if requires_manager:
        swap.status = 'awaiting_manager'
        swap.decided_at = now()
        await _notify_swap(db, swap, event='target_accepted_pending_manager')
    else:
        swap.status = 'accepted'
        swap.decided_by = target_staff_id  # auto-approve attributes to target
        swap.decided_at = now()
        # Re-check eligibility at flip time
        entry = await db.get(ScheduleEntry, swap.schedule_entry_id)
        if not await _is_target_still_eligible(db, swap.target_staff_id, entry):
            raise HTTPException(409, {'detail': 'scheduling_conflict_at_accept'})
        entry.staff_id = swap.target_staff_id
        await _notify_swap(db, swap, event='auto_approved')

async def manager_decides_swap(db, swap_id, manager_user_id, approve: bool):
    swap = await db.get(ShiftSwapRequest, swap_id)  # FOR UPDATE
    if swap.status != 'awaiting_manager':
        raise HTTPException(409, {'detail': 'not_awaiting_manager'})
    swap.decided_by = manager_user_id
    swap.decided_at = now()
    if approve:
        swap.status = 'accepted'
        entry = await db.get(ScheduleEntry, swap.schedule_entry_id)
        if not await _is_target_still_eligible(db, swap.target_staff_id, entry):
            raise HTTPException(409, {'detail': 'scheduling_conflict_at_manager_approval'})
        entry.staff_id = swap.target_staff_id
        await _notify_swap(db, swap, event='manager_approved')
    else:
        swap.status = 'rejected'
        await _notify_swap(db, swap, event='manager_rejected')
```

`_notify_swap` implements R12.5's notification matrix — sends SMS to each party listed, writes `shift_swap.sms_sent` or `shift_swap.sms_skipped` audit per recipient.

### 4.9 Buddy-punch photo review (G10)

The Hours-tab approval data hook (`useStaffHours` on the frontend, `GET /api/v2/staff/:id/clock?week=...` on the backend) returns per-clock-entry photo URLs alongside the existing fields. The backend serializer applies RBAC: photos visible to roles `org_admin`, `branch_admin`, `location_manager`; lower roles see `null`. A "Flag for follow-up" action writes:

```python
await db.execute(
    update(TimeClockEntry)
    .where(TimeClockEntry.id == entry_id, TimeClockEntry.org_id == org_id)
    .values(flags=func.jsonb_set(
        coalesce(TimeClockEntry.flags, text("'{}'::jsonb")),
        '{flagged_for_review}',
        text("'true'::jsonb"),
    ))
)
await write_audit_log(action='time_clock.flagged_for_review',
                      entity_type='time_clock_entry', entity_id=entry_id,
                      after_value={'flagged_by': user_id, 'reason': reason})
```

The schema needs a `flags jsonb DEFAULT '{}'::jsonb` column on `time_clock_entries` — add to migration 0207. **Column is named `flags`, not `metadata`** — see §3.1 inline comment.

## 5. API endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/kiosk/clock/lookup` | POST | Kiosk employee_id → staff identity (require_role kiosk) |
| `/api/v1/kiosk/clock/action` | POST | Kiosk in/out with photo (require_role kiosk) |
| `/api/v2/uploads/clock-photos` | POST | Upload kiosk/self-service photo, returns `{ file_key, file_name, file_size }` |
| `/api/v2/staff/me/clock-action` | POST | Self-service in/out |
| `/api/v2/staff/:id/clock/break-start` | POST | Begin break |
| `/api/v2/staff/:id/clock/break-end` | POST | End break |
| `/api/v2/staff/:id/clock/manual` | POST/PATCH/DELETE | Admin manual entry |
| `/api/v2/staff/:id/clock` | GET | List entries for week (Hours tab) |
| `/api/v2/staff/:id/timesheets/:week_start/approve` | POST | Approve week |
| `/api/v2/staff/:id/timesheets/:week_start/reopen` | POST | Reopen |
| `/api/v2/staff/:id/timesheets` | GET | List week summaries |
| `/api/v2/overtime-requests` | GET, POST | List + submit |
| `/api/v2/overtime-requests/:id/approve` | POST | Approve |
| `/api/v2/overtime-requests/:id/reject` | POST | Reject |
| `/api/v2/shift-swaps` | GET, POST | List + request |
| `/api/v2/shift-swaps/:id/accept` | POST | Target accepts (auto-approve or → awaiting_manager) |
| `/api/v2/shift-swaps/:id/reject` | POST | Target rejects |
| `/api/v2/shift-swaps/:id/manager-approve` | POST | Manager approves (only from awaiting_manager state) — G8 |
| `/api/v2/shift-swaps/:id/manager-reject` | POST | Manager rejects from awaiting_manager — G8 |
| `/api/v2/shift-swaps/:id/cancel` | POST | Requester cancels own pending request |
| `/api/v2/shift-cover` | GET, POST | List + open broadcast |
| `/api/v2/shift-cover/:id/accept` | POST | Claim (G6 eligibility re-checked at this moment; 409 on conflict) |
| `/api/v2/staff/:id/clock-entries/:entry_id/flag` | POST | Flag a clock-entry for follow-up review — G10. Path uses `clock-entries/:id/...` to avoid collision with `/clock/break-start`, `/clock/break-end`, `/clock/manual` named-action routes. |
| `/api/v2/staff/me/running-late` | POST | Staff-initiated "I'm running late" upward message — G3 |

All list responses use `{ items, total }`. Pagination via `offset` + `limit`.

## 6. Frontend Component Tree

### 6.1 `KioskClockScreen.tsx`

Sequence:
1. Welcome screen with "Staff Clock In" tile.
2. Tap tile → `EmployeeIdEntryScreen` (numeric/alphanumeric on-screen keyboard).
3. Submit → `POST /kiosk/clock/lookup` → on match render `IdentityConfirmScreen` showing on-file photo + first_name + "Take a photo to clock in".
4. Camera-capture screen (browser `getUserMedia` because the kiosk runs as a web app on a tablet).
5. POST `/kiosk/clock/action` → confirmation screen with side-by-side photos and worked-minutes display.

Each screen 44×44 minimum touch targets per `mobile-app.md`.

### 6.2 `HoursTab.tsx` (G10 — photos surfaced)

```tsx
import { useAuth } from '@/contexts/AuthContext'

export default function HoursTab({ staff }) {
  const { user } = useAuth()
  const [weekStart, setWeekStart] = useState(startOfWeek(new Date()))
  const { week, summary, refresh } = useStaffHours(staff.id, weekStart)
  const isAdmin = ['org_admin', 'branch_admin', 'location_manager'].includes(user?.role || '')
  const flaggedCount = (week?.entries ?? []).filter(e => e?.flags?.flagged_for_review).length

  return (
    <>
      <WeekNavigator weekStart={weekStart} onChange={setWeekStart} />
      <ScheduledVsActualTable week={week} />
      {flaggedCount > 0 && (
        <FlaggedReviewBanner count={flaggedCount} />
      )}
      <ClockEntriesList
        entries={week?.entries ?? []}
        onEdit={isAdmin ? editEntry : undefined}
        onFlagForReview={isAdmin ? flagForReview : undefined}
        // G10 — show photo thumbnails when role permits
        showPhotos={isAdmin}
        onFile={staff.on_file_photo_url}
      />
      {isAdmin && (
        <ApproveWeekBar
          summary={summary}
          flaggedCount={flaggedCount}
          onApprove={(args) => onApprove({ ...args, acknowledgeFlagged: flaggedCount > 0 })}
          onReopen={onReopen}
        />
      )}
    </>
  )
}
```

> Note: column is `flags` (NOT `metadata`) per §3.1. Frontend type `ClockEntry.flags?: { flagged_for_review?: boolean; review_reason?: string; flagged_by?: string }`.

`ClockEntriesList` row layout (when `showPhotos=true`):

```
┌─────────────────────────────────────────────────────────────────────┐
│ Mon 9 Jun                                                  🚩       │
│ ⏰ 08:42 → 17:08    Worked 7h 56m   Break 30m   Variance +14m       │
│ 📸 [clock-in thumb] [clock-out thumb]   [Compare with on-file ▸]    │
│                                       [Flag for follow-up]           │
└─────────────────────────────────────────────────────────────────────┘
```

Clicking "Compare with on-file ▸" opens a side-by-side modal:
```
┌──────────────────┬──────────────────┬──────────────────┐
│  On-file photo   │  Clock-in photo  │  Clock-out photo │
│   [128×128]      │   [128×128]      │   [128×128]      │
└──────────────────┴──────────────────┴──────────────────┘
[Looks correct] [Flag mismatch — investigate]
```

Per-entry "Flag for follow-up" writes `flags.flagged_for_review=true` via `POST /api/v2/staff/:id/clock-entries/:entry_id/flag` (audit `time_clock.flagged_for_review`). The flag persists across approvals and surfaces in the weekly approval modal's "Flagged entries" section.

When `flaggedCount > 0`, the `ApproveWeekModal` shows an acknowledgement step: *"3 entries are flagged for review. Approve anyway? You can also re-open the week later."* — admin must explicitly tick the box before the Approve button enables.

### 6.3 `SelfServiceClockScreen.tsx` (web)

Same UX as mobile but uses `getUserMedia`. Module-gated by `self_service_clock_enabled` (server returns 403 → frontend shows "Use the kiosk").

### 6.4 Mobile `ClockScreen.tsx`

```tsx
export default function ClockScreen() {
  return (
    <ModuleGate moduleSlug="staff_management">
      <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
        <CurrentStatusCard {...status} />
        <BigClockButton onPress={handleClockAction} disabled={!staff?.self_service_clock_enabled} />
        {!staff?.self_service_clock_enabled && (
          <SelfServiceDisabledBanner />
        )}
      </PullRefresh>
    </ModuleGate>
  )
}

async function handleClockAction() {
  const isNative = !!(window as any).Capacitor?.isNativePlatform?.()
  let photoUploadId: string | null = null
  if (org.clock_in_policy.self_service_require_photo) {
    if (isNative) photoUploadId = await captureNativePhoto()
    else photoUploadId = await captureWebPhoto()
  }
  let lat = null, lng = null
  if (org.clock_in_policy.self_service_require_geofence && isNative) {
    ({ lat, lng } = await getCurrentPosition())
  }
  await api.post('/api/v2/staff/me/clock-action', { action, photo_file_key: photoFileKey, lat, lng })
}
```

### 6.5 `ClockInPolicyPage.tsx` (Settings)

Form: default_channel select, self_service_require_photo toggle, geofence toggle + radius numeric, allow_late_edits toggle, rate_limit numeric. PATCH writes back.

### 6.6 Shift Swap + Cover Pages

- `/shift-swaps` — staff sees own swap requests; admins see all.
- `/shift-cover` — open shifts list; staff can claim.

## 7. User Workflow Traces

### 7.1 Kiosk clock-in

```
Staff taps "Staff Clock In" on kiosk welcome
→ Enters EMP-001
→ POST /kiosk/clock/lookup → {staff_id, first_name, on_file_photo, currently_clocked_in: false}
→ "Hi Jane. Take a photo to clock in." Camera capture.
→ POST /api/v2/uploads/clock-photos (P3-N12: dedicated endpoint, NOT `/uploads`) → {file_key}
→ POST /kiosk/clock/action {staff_id, action:'in', photo_file_key}
   - server matches scheduled_entry_id from schedule_entries window
   - inserts time_clock_entries row
   - audit_log (time_clock.in)
→ "Clocked in at 08:42. Have a great day."
```

### 7.2 Self-service clock-in (mobile)

```
Staff opens mobile /clock
→ ClockScreen renders
→ Currently not clocked in → button "Clock In"
→ Tap → Capacitor camera → photo
→ Geolocation if required
→ POST /api/v2/staff/me/clock-action {action:'in', photo_file_key, lat, lng}
   - server checks self_service_clock_enabled
   - geofence check
   - inserts row source='self_service_mobile'
→ Toast "Clocked in" + status updates
```

### 7.3 Approve week

```
Admin opens /staff/<id>#hours week=2026-06-08
→ HoursTab shows scheduled vs actual
→ Click "Approve hours"
→ Modal with totals breakdown + (if policy=employee_chooses) toil_choice radio
→ POST /api/v2/staff/:id/timesheets/2026-06-08/approve
   - compute_week_totals → upsert
   - if toil → write leave_ledger TOIL accrual
   - lock subsequent edits
→ Hours tab now read-only with green "Approved" banner
```

### 7.4 Late-arrival alert

```
schedule_entries: Jane Mon 09:00–17:00
→ at 09:16 the 5-min task fires
→ no open time_clock_entries for Jane
→ Redis SET 'late:{shift_id}' NX → succeeds
→ send_sms to Jane's manager: "Late: Jane hasn't clocked in for 09:00 shift"
→ subsequent ticks see Redis key, skip
```

### 7.5 Cover broadcast

```
Bob can't make Sat shift
→ POST /api/v2/shift-cover {schedule_entry_id} → status='open' broadcast_at=now expires_at=now+8h
→ Server fan-out: SMS to all active staff with skill overlap (or all staff)
→ Alice opens /shift-cover, taps "Claim" on Sat shift
→ POST /api/v2/shift-cover/:id/accept
   - status='accepted' accepted_by=Alice
   - schedule_entries.staff_id updated to Alice
   - SMS to Bob: "Alice has claimed your Sat shift"
```

## 8. Modal Inventory

| Element | Trigger | Contains |
|---|---|---|
| ApproveWeekModal | Approve button | Totals breakdown, TOIL choice (if policy), notes |
| OvertimeRequestModal | "Request OT" | shift, extra minutes, reason |
| ManualEntryModal | Admin "Add manual entry" | Staff, in_at, out_at, breaks |
| ShiftSwapModal | "Swap this shift" | Target staff select, reason |
| CoverShiftModal | "Open for cover" | Optional skill filter, expiry |

## 9. Performance

- Open-clock-in lookup uses partial index (1 row at most per staff).
- Late-arrival task scans only rows where `start_time` is in the last 15 min — small window.
- Missed-clock-out task uses partial index `idx_time_clock_open`.
- Approve-week calc reads a week's worth of entries for one staff — typically <50 rows.

### 9.1 SLOs (G4)

| API | Target | Notes |
|---|---|---|
| `POST /api/v2/staff/me/clock-action` (mobile + web self-service) | **<200ms p99** | Photo upload is async — frontend POSTs to `/api/v2/uploads/clock-photos` first, gets `file_key`, then passes it to clock-action as `photo_file_key` (P3-N1 + P3-N12 unification). Clock-action request only does DB writes + scheduled-entry match + Redis ops. |
| `POST /kiosk/clock/action` (kiosk) | **<300ms p99** | Slightly larger budget because kiosk operator-attended UX is tolerant; photo upload is still pre-POSTed. |
| `POST /kiosk/clock/lookup` | **<150ms p99** | Single indexed `employee_id` query + Redis rate-limit check. |
| `GET /api/v2/staff/:id/clock?week=...` (Hours tab load) | **<400ms p99** | Joins clock entries + breaks + scheduled entries for one week; index-backed. |
| `POST /api/v2/staff/:id/timesheets/:week_start/approve` | **<2s p99** | Compute totals across the week + write timesheet_approvals + TOIL ledger write (if applicable). Acceptable budget. |
| Scheduled `check_late_arrivals` (5-min) | run in <30s | Scans only the 15-min start_time window. Per-shift Redis dedupe key per design §4.3. |
| Scheduled `check_missed_clock_outs` (1-hr) | run in <60s | Partial index `idx_time_clock_open`. |

All clock-action paths follow performance-and-resilience steering rules: no synchronous I/O on the request thread; photo upload + sms send are background-queued; DB ops are single-flush + refresh per project-overview.

## 10. Verified-against-code addendum

- ✅ Existing kiosk router at `app/modules/kiosk/router.py` follows the no-login pattern; we'll add staff clock routes in the same file/module.
- ✅ Mobile `StackRoutes.tsx` lazy-import pattern — `ClockScreen` follows it.
- ✅ Capacitor camera + geolocation plugin patterns — Mobile uses existing helpers in `mobile/src/native/`.
- ✅ `app/modules/scheduling_v2/models.py::ScheduleEntry` is the lookup target for `scheduled_entry_id`.
- ✅ Redis `SET NX EX` pattern used throughout the codebase (rate-limit, scheduler lock, late-alert dedupe).
- ✅ Existing `audit_log` (singular — table is `audit_log` per `app/modules/admin/models.py:318`) writer + `send_sms` from Phase 1 in place. (P3-N2: spec previously referred to `audit_logs` plural in a few places; corrected.)

## 11. Spec completeness self-check

- ✅ Navigation §2.
- ✅ Component tree §6 (incl. G10 photo review surface).
- ✅ Workflow trace §7.
- ✅ Modal inventory §8.
- ✅ Toolbar §6.2.
- ✅ List/table §6.2 ScheduledVsActualTable + ClockEntriesList with photos.
- ✅ Error UI: 403 self_service_disabled banner; 422 photo_required toast; geofence-fail toast; 409 scheduling_conflict_at_claim; 422 no_upcoming_shift (running-late); 429 too_many_late_reports; 429 kiosk_lookup_rate_limited.
- ✅ Integration points: scheduler lock, audit_log, send_sms, kiosk router, mobile module gate.
- ✅ SLOs (G4) at §9.1.

## 12. Gap-analysis closure addendum

- ✅ **G1** — `overtime_policy` JSONB on organisations (§3.1); R6a + R10 thresholds; `compute_week_totals` splits ordinary vs overtime using thresholds (§4.2).
- ✅ **G2** — R14a + §4.6 roster-change SMS hook with Redis dedupe.
- ✅ **G3** — R14b + §4.7 `/staff/me/running-late` endpoint + mobile/web button.
- ✅ **G4** — §9.1 SLO table.
- ✅ **G6** — R13 eligibility filter spec; §4.8 re-checks at claim time; replaced stale `clock_pin_hash` reference.
- ✅ **G7** — `time_entries` locking explicitly dropped from approval flow (R9.3 + §4.2 docstring).
- ✅ **G8** — `shift_swap_requires_manager_approval` org setting; `awaiting_manager` state in schema; §4.8 workflow.
- ✅ **G9** — §4.5 cross-phase `create_staff` extension reads `default_channel`.
- ✅ **G10** — `flags` JSONB column on time_clock_entries (P3-N3: named `flags` not `metadata` — SQLAlchemy DeclarativeBase reservation); §4.9 flag flow; §6.2 photo thumbnails + side-by-side modal + flagged-acknowledgement on approve.
- ✅ **G12** — R3.3 concrete Redis key + SHA-256 hashing + 429 response.
- ✅ **G13** — R12.5 notification matrix; §4.8 `_notify_swap` helper.
- ✅ **G15** — Photo retention policy 6 years in Non-Goals; no orphan-cleanup job in Phase 3.
- ✅ **G16** — Test coverage covered in tasks E1 (see tasks.md).
- ✅ **G17** — Per-branch vs org-default geofence radius resolution documented in §3.1 + R6.4.
