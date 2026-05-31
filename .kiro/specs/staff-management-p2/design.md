# Staff Management Phase 2 — Design

## 1. Architecture overview

Phase 2 adds the leave engine. New module `app/modules/leave/` holds the bulk of new code; ledger and accrual jobs are the heaviest pieces.

Backend touches:
- `alembic/versions/0205_leave_schema.py` — DDL for `leave_types`, `leave_balances`, `leave_requests`, `leave_ledger`; backfill statutory types per org; ADP snapshot column on staff_members; `organisations.overtime_handling` typed column (P2-N5: not a JSONB key). Plus the FV-leave permission backfill into `user_permission_overrides`.
- `alembic/versions/0206_leave_indexes.py` — CREATE INDEX CONCURRENTLY pack.
- `app/modules/leave/models.py`
- `app/modules/leave/schemas.py`
- `app/modules/leave/service.py`
- `app/modules/leave/router.py` (registered at `/api/v2/leave` and `/api/v2/staff/:id/leave/*`)
- `app/modules/leave/accrual.py` — accrual engine.
- `app/modules/leave/public_holidays.py` — OWD detection + s40A extension.
- `app/tasks/scheduled.py` — register `accrue_leave`, `process_public_holidays`, `update_adp_snapshots`.
- `app/main.py` — include leave router.

Frontend touches:
- `frontend/src/pages/staff/tabs/LeaveTab.tsx` (new)
- `frontend/src/pages/leave/ApprovalQueue.tsx` (new)
- `frontend/src/pages/settings/people/LeaveTypesPage.tsx` (new sub-route)
- `frontend/src/pages/leave/components/RequestLeaveModal.tsx`
- `frontend/src/pages/leave/components/AdjustBalanceModal.tsx`
- `frontend/src/pages/leave/components/LedgerTable.tsx`
- `frontend/src/api/leave.ts` (typed client)

## 2. Navigation & Access

- **Sidebar item:** "Leave" under "People" section, visible when `staff_management` module enabled. Links to `/leave/approvals` (admin) or `/leave` (staff self-service).
- **Tab on Staff Detail:** "Leave" appears between "Roster" and "Documents" when module enabled.
- **Settings sub-route:** Settings → People → Leave Types.
- **Routes added in App.tsx:** `/leave/approvals`, `/leave`, `/settings/people/leave-types`. All lazy-loaded.
- **Guards:** `RequireOrgAdmin` for the approvals queue and settings; staff self-service routes use existing `RequireAuth`.

## 3. Data Model

### 3.1 Migration `0205_leave_schema.py`

```python
revision = "0205"
down_revision = "0204"  # phase 1 indexes
```

Tables (RLS + tenant_isolation policy on all):

```sql
CREATE TABLE IF NOT EXISTS leave_types (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    code text NOT NULL,
    name text NOT NULL,
    is_paid boolean NOT NULL DEFAULT true,
    accrual_method text NOT NULL,
    accrual_amount numeric(8,2),
    accrual_unit text NOT NULL DEFAULT 'hours',
    carry_over_max numeric(8,2),
    is_statutory boolean NOT NULL DEFAULT false,
    requires_doctor_note boolean NOT NULL DEFAULT false,
    confidential_visibility boolean NOT NULL DEFAULT false,
    active boolean NOT NULL DEFAULT true,
    display_order int NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, code),
    CHECK (accrual_method IN ('anniversary','fixed_annual','per_period','unaccrued','event_based')),
    CHECK (accrual_unit IN ('hours','days'))
);

CREATE TABLE IF NOT EXISTS leave_balances (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    staff_id uuid NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE,
    leave_type_id uuid NOT NULL REFERENCES leave_types(id) ON DELETE RESTRICT,
    accrued_hours numeric(8,2) NOT NULL DEFAULT 0,
    used_hours numeric(8,2) NOT NULL DEFAULT 0,
    pending_hours numeric(8,2) NOT NULL DEFAULT 0,
    anniversary_date date,
    last_accrual_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (staff_id, leave_type_id)
);

CREATE TABLE IF NOT EXISTS leave_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    staff_id uuid NOT NULL REFERENCES staff_members(id),
    leave_type_id uuid NOT NULL REFERENCES leave_types(id),
    start_date date NOT NULL,
    end_date date NOT NULL,
    hours_requested numeric(6,2) NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    reason text,
    relationship_to_subject text,                  -- required when leave_type.code='bereavement': 'close_family' | 'other'
    partial_day_start_time time,                   -- populated when hours_requested < standard_daily_hours AND start_date = end_date
    attachment_upload_id uuid,
    requested_by uuid NOT NULL REFERENCES users(id),
    decided_by uuid REFERENCES users(id),
    decided_at timestamptz,
    decision_notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status IN ('pending','approved','rejected','cancelled')),
    CHECK (relationship_to_subject IS NULL OR relationship_to_subject IN ('close_family','other'))
);
-- Application-level guard (cannot do via DB CHECK because the bereavement
-- code lives on leave_types, not leave_requests):
--   if leave_type.code = 'bereavement' then relationship_to_subject IS NOT NULL.
-- Enforced in leave_service.submit_request.

CREATE TABLE IF NOT EXISTS leave_ledger (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    staff_id uuid NOT NULL,
    leave_type_id uuid NOT NULL,
    delta_hours numeric(8,2) NOT NULL,
    reason text NOT NULL,
    request_id uuid REFERENCES leave_requests(id),
    occurred_at date NOT NULL,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (reason IN (
        'accrual','request_approved','request_cancelled_after_approval',
        'manual_adjustment','opening_balance','termination_payout',
        'public_holiday_extension','public_holiday_worked','pay_run_payout',
        'toil_accrual'  -- cross-phase X3: pre-included so P3's TOIL write doesn't require an enum amendment
    ))
);

ALTER TABLE staff_members
    ADD COLUMN IF NOT EXISTS average_daily_pay_snapshot numeric(10,2);
```

`organisations.overtime_handling` is added as a typed column on `organisations` (P2-N5: settled here as a typed column rather than a JSONB key — Phase 4's `_org_setting('overtime_handling', ...)` helper will read this column directly):

```sql
ALTER TABLE organisations
    ADD COLUMN IF NOT EXISTS overtime_handling text NOT NULL DEFAULT 'pay_cash';
ALTER TABLE organisations DROP CONSTRAINT IF EXISTS ck_org_overtime_handling;
ALTER TABLE organisations ADD CONSTRAINT ck_org_overtime_handling
    CHECK (overtime_handling IN ('pay_cash','toil','employee_chooses'));
```

### 3.2 Statutory backfill

The migration's data block:

```python
op.execute("""
    INSERT INTO leave_types (
        id, org_id, code, name, is_paid, accrual_method, accrual_amount, accrual_unit,
        carry_over_max, is_statutory, requires_doctor_note, confidential_visibility,
        active, display_order
    )
    SELECT gen_random_uuid(), o.id, t.code, t.name, t.is_paid, t.accrual_method, t.accrual_amount,
           t.accrual_unit, t.carry_over_max, true, t.requires_doctor_note,
           t.confidential_visibility, true, t.display_order
    FROM organisations o
    CROSS JOIN (VALUES
        ('annual', 'Annual leave', true, 'anniversary', NULL, 'hours', NULL, false, false, 1),
        ('sick', 'Sick leave', true, 'per_period', 80.0, 'hours', 160.0, true, false, 2),
        ('bereavement', 'Bereavement leave', true, 'event_based', NULL, 'days', NULL, false, false, 3),
        ('family_violence', 'Family violence leave', true, 'per_period', 80.0, 'hours', 80.0, false, true, 4),
        ('public_holiday_alt', 'Alternative holiday', true, 'event_based', NULL, 'days', NULL, false, false, 5),
        ('unpaid', 'Unpaid leave', false, 'unaccrued', NULL, 'hours', NULL, false, false, 6),
        -- cross-phase X2: toil pre-seeded universally so P3's overtime-toil write
        -- doesn't FK-violate. is_statutory=false because TOIL is a contractual choice,
        -- but ship it for every org because every org might enable it later.
        ('toil', 'Time off in lieu', true, 'event_based', NULL, 'hours', NULL, false, false, 7)
    ) AS t(code, name, is_paid, accrual_method, accrual_amount, accrual_unit, carry_over_max,
           requires_doctor_note, confidential_visibility, display_order)
    ON CONFLICT (org_id, code) DO NOTHING;
""")

# Seed leave_balances for every existing active staff × every active leave_type
# in this org (cross-phase X2: previously filtered by is_statutory=true, but toil
# is is_statutory=false yet still needs a balance row per staff so P3's
# overtime-toil write can find the (staff_id, leave_type_id) pair).
op.execute("""
    INSERT INTO leave_balances (
        id, org_id, staff_id, leave_type_id, accrued_hours, used_hours, pending_hours,
        anniversary_date
    )
    SELECT gen_random_uuid(), s.org_id, s.id, lt.id, 0, 0, 0, s.employment_start_date
    FROM staff_members s
    JOIN leave_types lt ON lt.org_id = s.org_id AND lt.active = true
    WHERE s.is_active = true
    ON CONFLICT (staff_id, leave_type_id) DO NOTHING;
""")
```

### 3.3 Indexes (`0206_leave_indexes.py`)

CONCURRENTLY pack:
- `idx_leave_balances_staff_type ON leave_balances (staff_id, leave_type_id)` — uniqueness already covers this; add covering index for the dashboard query.
- `idx_leave_balances_org ON leave_balances (org_id)`.
- `idx_leave_requests_org_status ON leave_requests (org_id, status, created_at DESC)` — approval queue.
- `idx_leave_requests_staff ON leave_requests (staff_id, start_date DESC)`.
- `idx_leave_ledger_staff_type_occurred ON leave_ledger (staff_id, leave_type_id, occurred_at DESC)`.
- `idx_leave_ledger_org ON leave_ledger (org_id)`.
- `idx_leave_ledger_request ON leave_ledger (request_id) WHERE request_id IS NOT NULL`.
- `idx_leave_types_org_active ON leave_types (org_id, display_order) WHERE active = true`.

## 4. Service layer

### 4.1 Accrual engine `app/modules/leave/accrual.py`

```python
async def accrue_for_staff(db, staff: StaffMember, today: date) -> list[LeaveLedger]:
    """Process all accrual types for one staff. Returns ledger rows written."""
    written = []
    balances = await load_balances_with_types(db, staff.id)
    for bal, lt in balances:
        if not lt.active:
            continue
        if lt.accrual_method == 'anniversary':
            row = await _process_anniversary(db, staff, bal, lt, today)
            if row: written.append(row)
        elif lt.accrual_method == 'per_period' and lt.code == 'sick':
            row = await _process_sick_yearly(db, staff, bal, lt, today)
            if row: written.append(row)
        elif lt.accrual_method == 'per_period' and lt.code == 'family_violence':
            row = await _process_family_violence_yearly(db, staff, bal, lt, today)
            if row: written.append(row)
    return written
```

Idempotency: each `_process_*` does `SELECT 1 FROM leave_ledger WHERE staff_id=? AND leave_type_id=? AND reason='accrual' AND occurred_at=?` first; skips if row exists.

Casual filter: `staff.employment_type == 'casual'` skips the annual-leave anniversary path entirely; sick + family_violence still apply pro-rata.

#### 4.1.1 Days-to-hours conversion (G9)

When `leave_type.accrual_unit == 'days'` (used only by custom org-defined types — the 6 statutory ones all use `'hours'`), the engine converts `accrual_amount` to balance hours using the staff's standard working day:

```python
def days_to_hours(accrual_amount_days: Decimal, staff: StaffMember) -> Decimal:
    """Convert a days-based accrual amount into balance hours.

    Working day = staff.standard_hours_per_week / 5, rounded to 2dp.
    Fallback when standard_hours_per_week is NULL: 8h/day (industry default).
    """
    if staff.standard_hours_per_week:
        std_day = Decimal(staff.standard_hours_per_week) / Decimal(5)
        return (Decimal(accrual_amount_days) * std_day).quantize(Decimal("0.01"))
    return Decimal(accrual_amount_days) * Decimal(8)
```

Apply at every grant site in `_process_anniversary`, `_process_sick_yearly`, `_process_family_violence_yearly`, and the `adjust_balance` admin path.

#### 4.1.2 Leap-year anniversary edge (STAFF-010)

For staff with `employment_start_date = Feb 29 of a leap year`, anniversaries in non-leap years fall on **Feb 28** (the last day of February). Helper:

```python
from calendar import isleap

def anniversary_in_year(start_date: date, year: int) -> date:
    if start_date.month == 2 and start_date.day == 29 and not isleap(year):
        return date(year, 2, 28)
    return start_date.replace(year=year)
```

Use everywhere the anniversary date is computed.

### 4.2 Public holiday engine `app/modules/leave/public_holidays.py`

> **Cache TTL note (P2-N9).** Two distinct caches operate here, each with its own TTL:
> - **Public-holiday list cache** (org × upcoming-window of `public_holidays` rows): **1 hour TTL**, keyed `org:public_holidays:{org_id}:{from_date}:{to_date}`. This is the steering-compliance bullet's reference; rebuilds quickly when admins manually re-sync from Nager.Date.
> - **Per-staff OWD computation cache** (the `staff:owd:{staff_id}:{holiday_date}` Redis key below): **24 hour TTL**. The OWD answer for a given staff × holiday date is stable for the holiday's lifetime, so the longer TTL is safe and reduces compute on repeated runs.

```python
async def is_otherwise_working_day(db, staff_id, holiday_date) -> bool:
    """4-week pattern from time_clock_entries (Phase 3) → fallback to availability_schedule."""
    cached = await redis.get(f"staff:owd:{staff_id}:{holiday_date}")
    if cached is not None:
        return cached == b'1'
    # Phase 2 fallback: only availability_schedule
    weekday_key = WEEKDAY_KEYS[holiday_date.weekday()]
    staff = await db.get(StaffMember, staff_id)
    schedule = staff.availability_schedule or {}
    is_owd = weekday_key in schedule and bool(schedule[weekday_key].get('start'))
    await redis.setex(f"staff:owd:{staff_id}:{holiday_date}", 86400, b'1' if is_owd else b'0')
    return is_owd

async def process_holiday_for_org(db, org_id, holiday_date):
    """For each active staff: detect OWD, flag schedule entries, grant alt-day if worked."""
    staff_list = await db.execute(...)  # active staff in org
    for staff in staff_list:
        if not await is_otherwise_working_day(db, staff.id, holiday_date):
            continue
        # if scheduled to work that day → grant alt-day, mark schedule entry
        entries = await schedule_v2_service.entries_on_date(db, staff.id, holiday_date)
        if any(e.entry_type in ('job','booking','other') for e in entries):
            await _grant_alt_day(db, staff, holiday_date)
            await _mark_entries_time_and_a_half(db, entries)

async def s40a_extension(db, request: LeaveRequest):
    """When approving annual leave, extend by one paid day per public holiday on OWD."""
    if request.leave_type.code != 'annual' or request.status != 'approved':
        return
    holidays = await load_public_holidays_in_range(db, request.start_date, request.end_date)
    extended_days = 0
    cursor = request.end_date
    for hol in holidays:
        if not await is_otherwise_working_day(db, request.staff_id, hol.holiday_date):
            continue
        # already inside leave window → extend after end_date by one working day
        cursor = next_working_day(cursor)
        await create_schedule_entry(db, staff_id=request.staff_id,
                                    start_time=datetime_combine(cursor, ...),
                                    end_time=...,
                                    entry_type='leave',
                                    notes=f's40A extension for {hol.name}')
        await write_ledger(db, request.staff_id, request.leave_type_id,
                           delta=+staff.standard_hours_per_week / 5,
                           reason='public_holiday_extension', request_id=request.id,
                           occurred_at=cursor)
        extended_days += 1
    return extended_days
```

### 4.3 Request workflow

`leave_service.submit_request`:
1. Load staff + leave_type + balance.
2. Compute `available = accrued - used - pending`.
3. **Bereavement gate (G1 / R4.7):** if `lt.code == 'bereavement'`:
   - Require `relationship_to_subject IN ('close_family','other')`. Raise `ValidationError('relationship_required')` if NULL or invalid.
   - Compute per-event cap:
     ```python
     std_day = (staff.standard_hours_per_week or 40) / 5      # hours per working day
     cap = (3 if relationship == 'close_family' else 1) * std_day
     ```
   - If `hours_requested > cap`, raise `BereavementCapExceededError(cap)` (returned as HTTP 422 with `{ reason: 'bereavement_cap_exceeded', cap_hours }`).
   - Skip the balance check at step 4 (bereavement is event_based, balance is always 0).
4. If `lt.accrual_method` not in `('event_based','unaccrued')` and `hours_requested > available` → raise `InsufficientLeaveError`.
5. **TOIL Phase 2 guard (G6):** if `lt.code == 'toil'`, additionally require `available >= hours_requested` even though accrual_method is event_based (prevents negative TOIL balance before Phase 3 actually accrues hours). Return HTTP 422 `{ reason: 'insufficient_toil_balance', available }` if not.
6. **Partial-day capture:** if `start_date == end_date` AND `hours_requested < (staff.standard_hours_per_week or 40) / 5`, the caller may supply `partial_day_start_time`. If omitted, default to `staff.shift_start` (the `availability_schedule` weekday entry's start time) at approval time.
7. Insert `leave_request` row (status='pending') with `relationship_to_subject`, `partial_day_start_time` if applicable.
8. Increment `pending_hours` on balance (skipped for `event_based`/`unaccrued`).
9. Audit `leave_request.submitted` with redacted PII (no free-text reason in audit row for `confidential_visibility=true` types).
10. Return.

`leave_service.approve_request`:
1. Load request (FOR UPDATE).
2. Validate state == pending.
3. **Permission check for confidential leave (G2 / R4.6 / R4.9):** if `leave_type.confidential_visibility == true`:
   - Verify the current user (the approver) has the `leave.fv_view` permission via `user_permission_overrides` (P2-N1: dot-separated form aligned with the rest of the spec). Otherwise return HTTP 403 `{ reason: 'fv_leave_no_approval_permission' }`.
4. Set status=approved, decided_by, decided_at.
5. Decrement `pending_hours`, increment `used_hours` on balance.
6. Insert leave_ledger row `reason='request_approved'` `delta_hours=-hours_requested` `request_id`.
7. Iterate working days in `[start_date, end_date]`, create `schedule_entries` row with `entry_type='leave'` per day. For partial-day requests, the single schedule_entries row uses `partial_day_start_time` as start and `partial_day_start_time + hours_requested` as end (otherwise full-day from `shift_start` to `shift_end`).
8. Run `s40a_extension` if leave_type.code == 'annual'.
9. Send approval email + SMS (async). For confidential types, email body redacts the leave type name → "Your approved leave request" (full details visible only on login).
10. Audit `leave_request.approved` (redacted for confidential types per §4.3.1).

`reject_request`, `cancel_request` — symmetric. Both honour the same R4.6 permission check.

### 4.3.1 Confidential-leave audit redaction shapes (P2-N6)

When the leave_type has `confidential_visibility=true` (i.e., `family_violence`), the `write_audit_log(...)` call sites in `app/modules/leave/service.py` MUST construct an explicit, redacted `after_value` dict — the full leave_request payload would leak the `reason`, `decision_notes`, `relationship_to_subject`, and `attachment_upload_id` fields, defeating the confidentiality model.

Per-event after_value shapes:

- `leave_request.submitted` → `{ leave_request_id, staff_id, leave_type_code: 'family_violence', date_range: '<start>..<end>', hours_requested }` — NO `reason`, NO `relationship_to_subject`, NO `attachment_upload_id`.
- `leave_request.approved` → `{ leave_request_id, staff_id, leave_type_code: 'family_violence', decided_at }` — NO `decision_notes`.
- `leave_request.rejected` → `{ leave_request_id, staff_id, leave_type_code: 'family_violence', decided_at }` — NO `decision_notes`.
- `leave_request.cancelled` → `{ leave_request_id, staff_id, leave_type_code: 'family_violence' }` — same redaction.

For non-confidential types, the service writes the full payload — existing behaviour, no change.

Implementation hint: a small helper `_redact_for_confidential(leave_type, full_payload) -> dict` in `app/modules/leave/service.py` keeps the redaction rule in one place and the lint test (tasks B3 verify) parses it.

### 4.4 Confidential-leave visibility filter (G2)

Implemented as a reusable query helper applied to every endpoint that returns `leave_requests` rows. **Important:** this uses the existing synchronous `app/modules/auth/rbac.py::has_permission(role, permission_key, overrides=...)` helper — the spec does NOT introduce a new async DB-querying helper. The user's permission overrides are already loaded by `RBACMiddleware` into `request.state.permission_overrides` (60s Redis cache at `app/middleware/rbac.py:_load_permission_overrides_cached`), so the filter just consumes that list.

```python
from sqlalchemy import or_, select
from sqlalchemy.sql import Select
from fastapi import Request

from app.modules.auth.rbac import has_permission
from app.modules.leave.models import LeaveRequest, LeaveType
from app.modules.leave.visibility import FV_LEAVE_VIEW_PERMISSION
from app.modules.staff.models import StaffMember


def _apply_confidential_filter(query: Select, request: Request, user_id: UUID, user_role: str) -> Select:
    """Restrict confidential-leave-type rows to:
       (a) the staff member who is the SUBJECT of the request (i.e., LeaveRequest.staff_id
           resolves to a StaffMember whose user_id == current user_id), OR
       (b) users holding the leave.fv_view permission via user_permission_overrides.

    Non-confidential leave types pass through unchanged.

    Synchronous — reads from request.state.permission_overrides (already cached
    by RBACMiddleware on the way in).

    P2-N12 — subject access is keyed by `staff_id` not `requested_by`. A manager
    submitting on behalf of a staff member who can't access the system would set
    `requested_by = manager.user_id` while `staff_id = subject.staff_id`. The
    earlier draft used `requested_by == user_id` which would have HIDDEN the
    request from the subject (the staff member whose privacy this whole feature
    protects) and SHOWN it to the proxy submitter. Fixed by joining on `staff_id`.
    """
    overrides = getattr(request.state, "permission_overrides", []) or []
    has_fv_view = has_permission(user_role, FV_LEAVE_VIEW_PERMISSION, overrides=overrides)
    if has_fv_view:
        return query  # no restriction

    # Resolve the current user's staff_id (NULL when the user is not linked to a
    # staff record — e.g., global_admin or non-staff org users).
    current_staff_id_subq = (
        select(StaffMember.id)
        .where(StaffMember.user_id == user_id)
        .limit(1)
        .scalar_subquery()
    )

    # Filter: exclude requests whose leave_type has confidential_visibility=true
    # UNLESS the current user is the subject (staff_id matches their staff record).
    confidential_type_ids = (
        select(LeaveType.id).where(
            LeaveType.org_id == request.state.org_id,
            LeaveType.confidential_visibility == True,
        )
    )
    return query.where(
        or_(
            LeaveRequest.leave_type_id.notin_(confidential_type_ids),
            LeaveRequest.staff_id == current_staff_id_subq,
        )
    )
```

Apply at:
- `GET /api/v2/leave/requests` (approval queue) — every list query.
- `GET /api/v2/staff/:id/leave/requests` — when `:id != current_staff_id` (own requests always visible to self via the subject branch).
- `GET /api/v2/staff/:id/leave/ledger` — same filter on the underlying `leave_requests` join when surfacing request-linked ledger rows.

Cache implication: `request.state.permission_overrides` is already populated by `RBACMiddleware` from the existing 60s Redis cache. No additional DB query per filter call. Revocation effective within 60s — acceptable per R4.9.

Permission key constant lives in `app/modules/leave/visibility.py`:

```python
# Dot-separated to match the existing rbac convention.
# Granting this permission requires writing a user_permission_overrides row
# explicitly per user — no role wildcard auto-grants it (verified against
# ROLE_PERMISSIONS in rbac.py: no role currently has `leave.*`).
FV_LEAVE_VIEW_PERMISSION = 'leave.fv_view'
```

## 5. API endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v2/leave/types` | GET, POST | List + create leave types |
| `/api/v2/leave/types/:id` | PATCH, DELETE | Update + delete (delete blocked for statutory) |
| `/api/v2/staff/:id/leave/balances` | GET | All balances for one staff |
| `/api/v2/staff/:id/leave/ledger` | GET | History. **(P2-N10)** When `leave_type_id` filters to a per-event leave type (e.g., bereavement), each item additionally surfaces `request_relationship_to_subject` via JOIN to `leave_requests.relationship_to_subject` when `request_id IS NOT NULL`. NULL for other leave types. |
| `/api/v2/staff/:id/leave/requests` | GET, POST | List own + submit |
| `/api/v2/staff/:id/leave/balances/:type_id/adjust` | POST | Manual adjustment (admin) |
| `/api/v2/leave/requests` | GET | Org-wide approval queue |
| `/api/v2/leave/requests/:id/approve` | POST | Approve |
| `/api/v2/leave/requests/:id/reject` | POST | Reject |
| `/api/v2/leave/requests/:id/cancel` | POST | Cancel |

All list responses use `{ items, total }`.

## 6. Frontend Component Tree

### 6.1 `LeaveTab.tsx` (Staff Detail)

```tsx
export default function LeaveTab({ staff }) {
  const { balances, ledger, refresh } = useStaffLeave(staff.id)
  if (staff.employment_type === 'casual') {
    return <CasualLeaveBanner staff={staff} ledger={ledger} />
  }
  return (
    <>
      <BalanceCardsRow balances={balances} />
      <Toolbar>
        <button onClick={() => openRequestLeaveModal({ staff })}>Request leave</button>
        {isAdmin && <button onClick={() => openAdjustBalanceModal({ staff })}>Adjust balance</button>}
      </Toolbar>
      <LedgerTable rows={ledger} />
    </>
  )
}
```

### 6.2 Approval Queue `/leave/approvals`

- Filter chips: All / Pending / Approved / Rejected / Cancelled.
- Each row: avatar + name, leave type, start–end + hours, reason, attached doctor's note (View link), available-balance preview (`64h available → 56h after this`).
- Inline Approve / Reject buttons.
- Reject opens modal asking for `decision_notes`.

### 6.3 Settings → People → Leave Types

Table: Order, Name, Code, Method, Amount, Carry-over, Statutory badge, Actions (Edit / Deactivate / Delete-disabled).
"Add custom leave type" button → modal.

### 6.4 RequestLeaveModal

Fields:
- `leave_type` select
- `start_date`, `end_date`
- `hours_requested` (auto-computed from start/end × std hours, editable)
- `reason` text
- `relationship_to_subject` select — **only renders when `leave_type.code == 'bereavement'`**. Options: "Close family (spouse, child, parent, sibling, grandparent, grandchild, in-law)" → `close_family`; "Other person" → `other`. Required.
- `partial_day_start_time` time input — **only renders when `start_date == end_date` AND `hours_requested < std_daily_hours`**. Defaults to staff's `shift_start`.
- `attachment` (drag-drop) — only shown when `leave_type.requires_doctor_note == true`.

Validation:
- Bereavement cap preview: when leave_type=bereavement and relationship is selected, show banner "Maximum: {cap}h ({3 or 1} working days × {std_day}h)".
- Balance preview: shows `available → available - hours_requested` for accruing types.
- Refuses submit if insufficient (R4.4 / R4.7 / R4.5 violations).
- Confidential leave types: the modal renders a one-line banner "This leave type is confidential — only you and your designated approver will see this request."

### 6.5 AdjustBalanceModal (admin only)

Fields: leave_type select, delta hours (signed), reason (text), occurred_at (date).
Posts to `/balances/:type_id/adjust`; writes ledger row reason='manual_adjustment'.

## 7. User Workflow Traces

### 7.1 Submit + approve annual leave

```
Staff opens Leave tab → clicks Request leave
→ Modal: Annual leave, 12-19 June, 40h, reason="Family trip"
→ POST /staff/:id/leave/requests → 201 (pending)
→ Balance card now shows pending=40
Admin opens /leave/approvals
→ Sees the request → Approve
→ POST /leave/requests/:id/approve
   - balance: pending=0, used=40
   - ledger row written
   - schedule_entries rows written (Mon, Tue, ... ).
   - s40A extension: if a public holiday on Wed AND OWD → adds extra leave day after end + ledger row.
→ Email + SMS to staff.
→ Toast on admin "Approved. Balance now 24h."
```

### 7.2 Casual employee leave tab

```
Open Leave tab for casual staff
→ Banner: "8% holiday pay-as-you-go on each pay run"
→ Sick leave card (still applies)
→ Annual leave card hidden
→ Ledger filterable
```

### 7.3 Annual accrual fires on anniversary

```
Daily task accrue_leave runs at 00:30 UTC
→ For each staff:
   - SAVEPOINT
   - if anniversary today:
     - SELECT 1 FROM leave_ledger WHERE staff_id=:s AND reason='accrual' AND occurred_at=today → none
     - INSERT ledger row delta=+std_hours×4, reason='accrual'
     - UPDATE balance accrued_hours += that
     - if accrued - used > carry_over_max: write compensating ledger row
→ Logs counter "accrued_today=N orgs=M"
```

## 8. Modal/Panel Inventory

| Element | Trigger | Contains | Closes |
|---|---|---|---|
| RequestLeaveModal | "Request leave" | Type, dates, hours, reason, attachment | X / Cancel / Submit |
| AdjustBalanceModal | Admin "Adjust balance" | Type, delta, reason, occurred_at | X / Cancel / Save |
| RejectModal | Admin Reject button | decision_notes textarea | X / Cancel / Reject |
| LeaveTypeEditModal | Settings table edit | Name, accrual rate, carry_over | X / Cancel / Save |
| ConfirmStatutoryEditModal | Edit statutory rate | "Confirm change above legal floor" | Cancel / Confirm |

## 9. Error UI

- 422 `insufficient_balance`: red inline below hours_requested with available figure.
- 422 `relationship_required` (bereavement without relationship): red inline below the relationship select.
- 422 `bereavement_cap_exceeded`: red inline below hours_requested with the cap figure and the relationship-tier explanation.
- 422 `insufficient_toil_balance` (Phase 2 only): yellow banner "TOIL accrual starts in Phase 3 — no hours available yet. Contact your manager if this is urgent."
- 422 `requires_doctor_note_warning`: yellow banner on approver UI (not blocking).
- 403 `fv_leave_no_approval_permission` (confidential leave): toast "You don't have permission to approve family-violence-leave requests. Contact your org owner."
- 403 statutory delete: toast.
- 404 module disabled: graceful — Leave tab simply doesn't render.

## 9.1 Settings → People → Permissions → Family-Violence Leave Visibility (R4.9)

**Routing model.** The `frontend/src/pages/settings/Settings.tsx` shell uses tab-based navigation via the `?tab=...` query param (verified at `Settings.tsx:74-130`), NOT URL sub-routes. Phase 2 adds a new `NAV_ITEMS` entry `{ id: 'people-permissions', label: 'People Permissions', icon: '👥', adminOnly: true, module: 'staff_management' }` plus a matching `'people-permissions': PermissionsPage` entry in `SECTION_COMPONENTS`. The deep-link path is `/settings?tab=people-permissions` (NOT `/settings/people/permissions`).

The page lists all org users with on/off checkbox for the `leave.fv_view` permission (note: dot-separated, matches existing rbac.py convention — see design §4.4 for rationale). Sourced from existing `user_permission_overrides` table. Read pattern uses the existing `permission_key` column (NOT `permission`) and `is_granted=true` to mean "explicitly granted".

UI:
- Table: User, Role, Has FV-leave-view permission (checkbox), Last reviewed.
- Top banner during the first 30 days after Phase 2 migration: "We've granted family-violence-leave visibility to all current org admins. Please review and revoke from anyone who shouldn't see these confidential requests."
- Toggling a checkbox calls `create_or_update_permission_override` (existing helper at `app/modules/auth/permission_overrides.py`) which handles the SELECT-then-INSERT-or-UPDATE idempotency and writes the audit row automatically. Revoke calls `delete_permission_override`.

Backend:
- `GET /api/v2/permissions/fv-leave-view` — returns `{ items: [{ user_id, email, name, role, has_permission, granted_at }], total }`. JOIN against `user_permission_overrides upo ON upo.user_id = u.id AND upo.permission_key = 'leave.fv_view' AND upo.is_granted = true`.
- `POST /api/v2/permissions/fv-leave-view/{user_id}/grant` — calls `create_or_update_permission_override(session, user_id=..., permission_key='leave.fv_view', is_granted=true, granted_by=current_user.id, org_id=current_user.org_id)`. The helper writes the audit row.
- `POST /api/v2/permissions/fv-leave-view/{user_id}/revoke` — calls `delete_permission_override(session, user_id=..., permission_key='leave.fv_view', deleted_by=current_user.id, org_id=current_user.org_id)`.
- All three are org_admin-only (existing RBAC).

## 10. Performance

- Accrual job per-staff query is O(1) per staff after the indexes; the job processes ~9 staff per org × ~7 orgs = ~63 ops/day.
- Public-holiday job runs once daily, processes 11 NZ public holidays × ~9 staff × ~7 orgs = ~700 OWD checks. With Redis cache, second run is near-zero.
- Approval queue paginates by 50.

## 11. Testing

- `tests/unit/test_leave_accrual.py` — anniversary, casual skip, sick 6-month gate, idempotency.
- `tests/unit/test_leave_request_workflow.py` — submit / approve / reject / cancel transitions.
- `tests/unit/test_public_holiday_engine.py` — OWD detection, alt-day grant, s40A extension.
- `tests/property/test_leave_balance_invariants.py` — Hypothesis: any sequence of accrual+approve+cancel keeps `accrued >= used` and `accrued - used >= 0`.
- `scripts/test_staff_leave_e2e.py` per R16.

## 12. Verified-against-code addendum

- ✅ `app/modules/scheduling_v2/models.py::ScheduleEntry.entry_type` already includes `'leave'` — no migration needed for entry_type.
- ✅ `app/modules/admin/models.py::PublicHoliday` exists with `holiday_date`, `name`, `country_code`.
- ✅ `app/modules/admin/service.py::sync_public_holidays` (Nager.Date) already feeds the table.
- ✅ `app/integrations/email_sender.py::send_email` handles DLQ.
- ✅ Phase 1 introduced `app/integrations/sms_sender.py` — Phase 2 reuses it for leave-decision SMS.
- ✅ Existing `audit_log` (singular — verified at `app/modules/admin/models.py:318`; the model class is `AuditLog`) is the right table. (P2-N2: spec previously referred to `audit_logs` plural in a few places; corrected.)
- ⚠️ The latest migration before Phase 2 will be 0203 + 0204 (Phase 1). Phase 2 lands as 0205, 0206.
- ⚠️ `staff_members.availability_schedule` is `JSONB` keyed by `monday`/`tuesday`/...`sunday`. The OWD fallback uses these keys; Phase 3 swaps to time_clock_entries data when available.

## 13. Spec completeness self-check

- ✅ Navigation §2 / §6 (incl. new Permissions sub-route §9.1).
- ✅ Component tree §6.
- ✅ User workflow §7.
- ✅ Modal inventory §8.
- ✅ Toolbar/list §6.
- ✅ Error UI §9 (incl. new 422/403 codes for bereavement + FV permission).
- ✅ Integration points §11 (existing send_email, sms_sender, scheduler lock, audit_log, user_permission_overrides).
- ✅ Bereavement per-event cap §4.3 step 3 (G1 closed).
- ✅ Family-violence visibility mechanism §4.4 + §9.1 (G2 closed).
- ✅ Sick + family-violence 6-month gate §4.1 (G3 closed via R6 rename).
- ✅ Days-to-hours conversion §4.1.1 (G9 closed).
- ✅ Leap-year anniversary helper §4.1.2 (STAFF-010 closed).
