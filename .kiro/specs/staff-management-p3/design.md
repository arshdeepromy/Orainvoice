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
- `app/modules/kiosk/router.py` extension — staff clock-in routes added under `/kiosk/clock/*` (STAFF-006 settled in favour of shared kiosk surface with a "Staff" tile, mirroring how the customer-facing kiosk already works).
- `app/tasks/scheduled.py` — register `check_late_arrivals` (5 min), `check_missed_clock_outs` (1 hr).
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
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','rejected','cancelled')),
    reason text,
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
        "kiosk_employee_id_rate_limit": 10
    }'::jsonb;
```

All new tables get `ENABLE ROW LEVEL SECURITY` + `tenant_isolation` policy.

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
    Rate-limited via existing rate-limit pattern."""

async def kiosk_clock_action(db, *, org_id, staff_id, action, photo_upload_id):
    """Handles in/out with mandatory photo. Auto-matches scheduled_entry_id."""

async def self_service_clock_action(db, *, org_id, staff_id, action, photo_upload_id, lat, lng, source):
    """Refuses 403 when self_service_clock_enabled=false. Honours geofence + photo policy."""

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
    Returns dict ready for upsert into timesheet_approvals."""

async def approve_week(db, staff_id, week_start, approved_by, toil_choice=None):
    """Upserts timesheet_approvals; locks edits; if org policy is toil → grants TOIL leave."""

async def reopen_week(db, staff_id, week_start):
    """Status='edited_after_approval'; unlocks edits."""

async def lock_check(db, staff_id, when_dt) -> bool:
    """Used by service to refuse PUT/DELETE on entries inside an approved week."""
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

## 5. API endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/kiosk/clock/lookup` | POST | Kiosk employee_id → staff identity |
| `/kiosk/clock/action` | POST | Kiosk in/out with photo |
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
| `/api/v2/shift-swaps/:id/accept` | POST | Accept |
| `/api/v2/shift-swaps/:id/reject` | POST | Reject |
| `/api/v2/shift-cover` | GET, POST | List + open broadcast |
| `/api/v2/shift-cover/:id/accept` | POST | Claim |

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

### 6.2 `HoursTab.tsx`

```tsx
export default function HoursTab({ staff }) {
  const [weekStart, setWeekStart] = useState(startOfWeek(new Date()))
  const { week, summary, refresh } = useStaffHours(staff.id, weekStart)
  const isAdmin = useRole(['org_admin','branch_admin'])
  return (
    <>
      <WeekNavigator weekStart={weekStart} onChange={setWeekStart} />
      <ScheduledVsActualTable week={week} />
      <ClockEntriesList entries={week.entries} onEdit={isAdmin ? editEntry : undefined} />
      {isAdmin && <ApproveWeekBar summary={summary} onApprove={...} onReopen={...} />}
    </>
  )
}
```

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
  await api.post('/api/v2/staff/me/clock-action', { action, photo_upload_id: photoUploadId, lat, lng })
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
→ POST /api/v2/uploads (existing) → {upload_id}
→ POST /kiosk/clock/action {staff_id, action:'in', photo_upload_id}
   - server matches scheduled_entry_id from schedule_entries window
   - inserts time_clock_entries row
   - audit_logs (time_clock.in)
→ "Clocked in at 08:42. Have a great day."
```

### 7.2 Self-service clock-in (mobile)

```
Staff opens mobile /clock
→ ClockScreen renders
→ Currently not clocked in → button "Clock In"
→ Tap → Capacitor camera → photo
→ Geolocation if required
→ POST /api/v2/staff/me/clock-action {action:'in', photo_upload_id, lat, lng}
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

## 10. Verified-against-code addendum

- ✅ Existing kiosk router at `app/modules/kiosk/router.py` follows the no-login pattern; we'll add staff clock routes in the same file/module.
- ✅ Mobile `StackRoutes.tsx` lazy-import pattern — `ClockScreen` follows it.
- ✅ Capacitor camera + geolocation plugin patterns — Mobile uses existing helpers in `mobile/src/native/`.
- ✅ `app/modules/scheduling_v2/models.py::ScheduleEntry` is the lookup target for `scheduled_entry_id`.
- ✅ Redis `SET NX EX` pattern used throughout the codebase (rate-limit, scheduler lock, late-alert dedupe).
- ✅ Existing `audit_logs` writer + `send_sms` from Phase 1 in place.

## 11. Spec completeness self-check

- ✅ Navigation §2.
- ✅ Component tree §6.
- ✅ Workflow trace §7.
- ✅ Modal inventory §8.
- ✅ Toolbar §6.2.
- ✅ List/table §6.2 ScheduledVsActualTable.
- ✅ Error UI: 403 self_service_disabled banner; 422 photo_required toast; geofence-fail toast.
- ✅ Integration points: scheduler lock, audit_logs, send_sms, kiosk router, mobile module gate.
