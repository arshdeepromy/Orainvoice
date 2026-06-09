# Design — Staff Timesheets

## Overview

The Staff Timesheets module is an integration and computation layer that aggregates data from `time_clock_entries`, `schedule_entries`, `leave_requests`, and `pay_periods` into a single `Timesheet` row per staff per pay period. It introduces a match-to-roster policy engine, branch-scoped query enforcement, clock immutability at the PostgreSQL level, and `timesheet.approve` / `payrun.lock` permission grants composable with existing roles. The module does NOT duplicate existing entities — it reads them and produces computed aggregation records.

### Architecture Diagram

```mermaid
flowchart TB
    subgraph Frontend ["Frontend (frontend-v2/)"]
        Tab1["Tab 1: Clocked In\nReal-time view"]
        Tab2["Tab 2: Timesheets\nPeriod review & approval"]
        Settings["Timesheet Settings\nClock/match/approval config"]
    end

    subgraph API ["API Layer (app/modules/timesheets/)"]
        Router["router.py\nFastAPI endpoints"]
        Service["service.py\nBusiness logic"]
        Aggregator["aggregation.py\nCompute rostered/actual/adjusted"]
        MatchEngine["match_engine.py\nMatch-to-roster policy"]
        BranchScope["branch_scope.py\nFastAPI dependency"]
    end

    subgraph ExistingModules ["Existing Modules (read-only)"]
        TimeClock["time_clock_entries\n(clock in/out records)"]
        Schedule["schedule_entries\n(roster/shifts)"]
        PayPeriods["pay_periods\n(period boundaries)"]
        Staff["staff_members\n(rates, hours, branch)"]
        Branches["branches\n(timezone, geofence)"]
        Leave["leave_requests\n(approved leave)"]
    end

    subgraph NewTables ["New Tables"]
        Timesheets["timesheets\n(aggregation row)"]
        TSSettings["timesheet_settings\n(clock/match config)"]
    end

    subgraph AlteredTables ["Altered Existing Tables"]
        TCE_Alter["time_clock_entries\n+ clock_out_branch_id\n+ immutability trigger"]
        TSA_Alter["timesheet_approvals\n+ timesheet_id FK"]
    end

    Tab1 --> Router
    Tab2 --> Router
    Settings --> Router

    Router --> BranchScope
    BranchScope --> Service
    Service --> Aggregator
    Service --> MatchEngine
    Aggregator --> TimeClock
    Aggregator --> Schedule
    Aggregator --> PayPeriods
    Aggregator --> Staff
    MatchEngine --> Schedule
    MatchEngine --> TimeClock
    MatchEngine --> TSSettings

    Service --> Timesheets
    Service --> TSSettings
    Service --> TCE_Alter
    Service --> TSA_Alter

    BranchScope --> Branches
```

### Key Invariants

1. **Timesheet is a computed view that caches results** — `rostered_minutes` and `actual_minutes` are recomputed on demand (or on status transition) from the underlying entries. They are stored for query performance but are not the source of truth for the raw data.
2. **Clock data is immutable** — DB-level BEFORE UPDATE/DELETE trigger on `clock_in_at`/`clock_out_at` prevents mutation. Superuser can temporarily disable trigger for emergency data recovery. Corrections go through `adjusted_minutes`.
3. **Branch scoping is a security boundary** — enforced at the dependency layer, not just UI filtering.
4. **One timesheet per staff per period** — UNIQUE constraint prevents duplicates. Re-aggregation updates the existing row.
5. **Approval is auditable** — every status transition writes an `audit_log` row AND a `timesheet_approvals` row for the approval-event ledger.

## Data Model

### New Tables

#### `timesheets`

```sql
CREATE TABLE timesheets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,
    staff_id        UUID NOT NULL REFERENCES staff_members(id),
    pay_period_id   UUID NOT NULL REFERENCES pay_periods(id),
    branch_id       UUID REFERENCES branches(id),  -- nullable for multi-branch or unassigned staff
    rostered_minutes    INTEGER NOT NULL DEFAULT 0,
    actual_minutes      INTEGER NOT NULL DEFAULT 0,
    adjusted_minutes    INTEGER,  -- nullable; when set = source of truth
    ordinary_minutes    INTEGER NOT NULL DEFAULT 0,
    overtime_minutes    INTEGER NOT NULL DEFAULT 0,
    public_holiday_minutes INTEGER NOT NULL DEFAULT 0,
    exception_flags     JSONB NOT NULL DEFAULT '[]'::jsonb,
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open','pending_approval','approved','locked')),
    approved_by     UUID REFERENCES users(id),
    approved_at     TIMESTAMPTZ,
    locked_at       TIMESTAMPTZ,
    locked_by       UUID REFERENCES users(id),
    payslip_id      UUID REFERENCES payslips(id),  -- populated when locked→payslip
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_timesheets_staff_period UNIQUE (staff_id, pay_period_id)
);

CREATE INDEX ix_timesheets_org_period ON timesheets(org_id, pay_period_id);
CREATE INDEX ix_timesheets_branch ON timesheets(branch_id) WHERE branch_id IS NOT NULL;
CREATE INDEX ix_timesheets_status ON timesheets(org_id, status);
```

#### `timesheet_settings`

```sql
CREATE TABLE timesheet_settings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,
    branch_id       UUID REFERENCES branches(id),  -- nullable = org-wide default
    clock_rounding_minutes      INTEGER NOT NULL DEFAULT 1
                    CHECK (clock_rounding_minutes IN (1, 5, 10, 15, 30)),
    clock_rounding_direction    TEXT NOT NULL DEFAULT 'nearest'
                    CHECK (clock_rounding_direction IN ('nearest','up','down')),
    early_grace_minutes         INTEGER NOT NULL DEFAULT 0,
    late_grace_minutes          INTEGER NOT NULL DEFAULT 0,
    match_policy    TEXT NOT NULL DEFAULT 'pay_actual'
                    CHECK (match_policy IN ('pay_actual','round_to_roster','actual_rounded')),
    auto_approve_threshold_minutes INTEGER NOT NULL DEFAULT 0,
    require_approval_before_lock   BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_timesheet_settings_org_branch UNIQUE (org_id, branch_id)
);
```

The UNIQUE constraint on `(org_id, branch_id)` uses PostgreSQL's handling of NULL — `(org_id, NULL)` is unique from `(org_id, branch_uuid)`, so one org-wide default plus per-branch overrides is naturally enforced.

### ALTER TABLE Additions to Existing Tables

#### `time_clock_entries` — add `branch_id` + `clock_out_branch_id` + `clock_in_ip`

```sql
-- branch_id does NOT exist today (only clock_in_lat/clock_in_lng geofence coords).
-- This is a NEW column, not a constraint on an existing one.
ALTER TABLE time_clock_entries
    ADD COLUMN IF NOT EXISTS branch_id UUID REFERENCES branches(id);

ALTER TABLE time_clock_entries
    ADD COLUMN clock_out_branch_id UUID REFERENCES branches(id);

-- clock_in_ip is a new audit field (IP at clock-in time)
ALTER TABLE time_clock_entries
    ADD COLUMN clock_in_ip TEXT;

-- Forward-only NOT NULL enforcement on branch_id for new rows:
ALTER TABLE time_clock_entries
    ADD CONSTRAINT ck_tce_branch_id_new_rows
    CHECK (created_at <= '2026-07-01T00:00:00Z'::timestamptz OR branch_id IS NOT NULL);
```

The date in the CHECK constraint is the migration execution date (set at migration write time). This ensures old NULL rows are valid but new inserts must provide `branch_id`.

**Code-truth note (verified against actual schema):** `time_clock_entries` currently has `clock_in_lat`/`clock_in_lng` (geofence coordinates) but NO `branch_id`, NO `clock_out_branch_id`, and NO `clock_in_ip` column. All three are brand-new columns added by this migration. The `source` column (not `clock_in_source`) stores `kiosk`/`self_service_mobile`/`self_service_web`/`admin_manual`.

#### `time_clock_entries` — immutability policy

```sql
-- TRIGGER-ONLY enforcement (REVOKE is not viable — see Q9 Investigation below).
-- The app connects as the `postgres` superuser role, which is also used by Alembic
-- migrations. A REVOKE on `postgres` would block both the app AND migrations.
-- Instead, the trigger fires for ALL roles including `postgres`, effectively making
-- the columns immutable at the application level.
CREATE OR REPLACE FUNCTION tce_immutability_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND (
        (OLD.clock_in_at IS NOT NULL AND OLD.clock_in_at IS DISTINCT FROM NEW.clock_in_at) OR
        (OLD.clock_out_at IS NOT NULL AND OLD.clock_out_at IS DISTINCT FROM NEW.clock_out_at)
    ) THEN
        RAISE EXCEPTION 'Mutation of immutable clock columns on entry % is prohibited', OLD.id
            USING ERRCODE = 'restrict_violation';
        RETURN OLD;  -- never reached, but required for function signature
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Deletion of time_clock_entry % is prohibited', OLD.id
            USING ERRCODE = 'restrict_violation';
        RETURN NULL;  -- never reached
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_tce_immutability
    BEFORE UPDATE OR DELETE ON time_clock_entries
    FOR EACH ROW EXECUTE FUNCTION tce_immutability_guard();
```

**Override mechanism (superuser-only, for emergency data recovery):**
```sql
-- Temporarily disable the trigger (requires superuser, which `postgres` is):
ALTER TABLE time_clock_entries DISABLE TRIGGER trg_tce_immutability;
-- ... perform emergency fix ...
ALTER TABLE time_clock_entries ENABLE TRIGGER trg_tce_immutability;
```

This matches the "superuser-only override mechanism" requirement. The DISABLE/ENABLE must be logged in the audit trail manually by the DBA.

#### `timesheet_approvals` — add `timesheet_id` FK

```sql
ALTER TABLE timesheet_approvals
    ADD COLUMN timesheet_id UUID REFERENCES timesheets(id);

CREATE INDEX ix_timesheet_approvals_timesheet ON timesheet_approvals(timesheet_id)
    WHERE timesheet_id IS NOT NULL;
```

Existing rows remain with `timesheet_id = NULL`. New approval events populate it.

#### Kiosk credential — branch scoping via existing `users.branch_ids`

Per Q10 investigation findings: kiosk auth uses model (a) — a plain `users` row with `role='kiosk'`. The user's `branch_ids` JSONB column (already present on all users) is used for branch scoping.

**No new table needed for v1.** Instead:

1. When creating/inviting a kiosk user, require exactly one `branch_id` in the request body.
2. Store it in `users.branch_ids = [branch_id]` (existing JSONB column).
3. On kiosk clock-in, derive `TimeClockEntry.branch_id` from the JWT's `branch_ids[0]`.
4. The existing `BranchContextMiddleware` already reads `branch_ids` from JWT claims — kiosk users will be naturally scoped.

```sql
-- No schema change needed. Kiosk users already have branch_ids on the users table.
-- Enforcement is at the application layer:
--   - Kiosk invite endpoint validates exactly 1 branch_id provided
--   - Clock-in service reads branch_ids[0] from JWT claims
--   - BranchContextMiddleware already handles the scoping
```

If multi-device-per-branch or device-level revocation is needed later, a `kiosk_credentials` table can be added in a future phase.

## Timesheet Lifecycle — Creation Triggers

Timesheet rows are created **lazily** (not eagerly on period open). This avoids blank rows for casual staff who don't work every period.

### Trigger 1: First TimeClockEntry in Period

When a `TimeClockEntry` is inserted for a staff member and the `clock_in_at` falls within an open `PayPeriod`, the service checks for an existing `Timesheet` row. If none exists, it creates one with `status = 'open'` and runs the initial aggregation.

### Trigger 2: Approved LeaveRequest Overlap

When a `LeaveRequest` transitions to `approved` and its date range overlaps a `PayPeriod`, the service ensures a `Timesheet` row exists for that staff/period combination. Leave hours contribute to the aggregation.

### Trigger 3: ScheduleEntry Presence

When a `ScheduleEntry` is created/updated for a staff member within a `PayPeriod`, the service ensures a `Timesheet` row exists. This handles the case where a staff member is rostered but hasn't clocked in yet.

### Scheduled Sweep: `materialise_missing_timesheets(pay_period_id)`

A scheduled task runs N hours before pay-run cutoff (configurable, default 24h). It:

1. Queries all `staff_members` with: (a) `ScheduleEntry` in the period, OR (b) approved `LeaveRequest` overlapping the period.
2. For each staff member who matches (a) or (b) but lacks a `Timesheet` row, creates one and runs aggregation.
3. For staff with NO clock activity, NO leave, AND NO scheduled shifts — logs a `"no_activity"` exception alert (does NOT create a blank row).

```python
async def materialise_missing_timesheets(
    db: AsyncSession,
    pay_period_id: UUID,
    org_id: UUID,
) -> MaterialisationResult:
    """Sweep to create missing timesheets before pay-run cutoff.
    
    Returns:
        MaterialisationResult with:
        - created_count: timesheets materialised
        - no_activity_staff: list of staff_ids with nothing to attach
    """
```

### "no_activity" Exception Handling

Staff flagged as "no_activity" by the sweep are:
- NOT given a blank Timesheet row (avoids noise in the approval queue).
- Logged as an alert/exception for the org_admin to review (e.g., casual staff who didn't work, staff on unpaid leave without a LeaveRequest, or data-entry gaps).
- Visible in a "Missing Timesheets" section on the pay-run dashboard.

## Aggregation Service

### Module: `app/modules/timesheets/aggregation.py`

The aggregation service computes `rostered_minutes`, `actual_minutes`, and hour-band breakdowns for a timesheet.

```python
async def compute_timesheet(
    db: AsyncSession,
    *,
    staff_id: UUID,
    pay_period: PayPeriod,
    settings: TimesheetSettings,
    branch_tz: str = "Pacific/Auckland",
) -> TimesheetComputation:
    """Compute aggregated hours for one staff member in one pay period.

    Returns a TimesheetComputation dataclass with:
    - rostered_minutes: sum of scheduled shift durations
    - actual_minutes: sum of worked_minutes from approved clock entries
    - ordinary_minutes: actual (or matched) minutes minus overtime/PH
    - overtime_minutes: minutes exceeding daily/weekly threshold (Phase C)
    - public_holiday_minutes: minutes on public holidays (Phase C)
    - exception_flags: list of anomaly dicts
    - matched_entries: list of (clock_entry_id, schedule_entry_id, matched_minutes)
    """
```

#### Computation Steps

1. **Fetch roster**: Query `schedule_entries` WHERE `staff_id` AND `start_time` within period AND `status = 'scheduled'` AND `entry_type NOT IN ('break', 'leave')`. Sum `(end_time - start_time)` → `rostered_minutes`.

2. **Fetch clock entries**: Query `time_clock_entries` WHERE `staff_id` AND `clock_in_at` within period AND `worked_minutes IS NOT NULL`. Sum `worked_minutes` → `actual_minutes`.

3. **Run match engine**: For each clock entry, attempt to match against schedule entries per the configured `match_policy`. Produce per-entry `matched_minutes` (may differ from raw `worked_minutes` depending on policy).

4. **Classify hour bands**: For Phase A, all matched minutes default to `ordinary_minutes`. Phase C adds overtime/PH classification.

5. **Detect exceptions**: Compare roster vs clock entries to find mismatches:
   - Shift with no clock entry → `{"type": "missed_shift", "detail": "No clock-in for scheduled shift", "schedule_entry_id": "..."}`
   - Clock entry with no matching shift → `{"type": "unmatched_clock", "detail": "Clock entry does not match any scheduled shift", "clock_entry_id": "..."}`
   - Missing clock-out → `{"type": "missing_clock_out", "detail": "Staff still clocked in", "clock_entry_id": "..."}`
   - Excessive variance → `{"type": "high_variance", "detail": "Actual exceeds rostered by >60 min"}`

6. **Return computation**: Package all results into `TimesheetComputation` for the service layer to persist.

### Recomputation Triggers

The aggregation is run:
- When a timesheet is first created (lazily: on first TCE in the period, on approved LeaveRequest overlap, or on ScheduleEntry presence).
- When the scheduled sweep (`materialise_missing_timesheets`) runs before pay-run cutoff.
- When explicitly triggered by the user ("Refresh" button on Tab 2).
- When transitioning status from `open` → `pending_approval` (ensures latest data).
- NOT automatically on every clock event (too expensive for large orgs).

## Match-to-Roster Engine

### Module: `app/modules/timesheets/match_engine.py`

```python
class MatchResult:
    clock_entry_id: UUID
    schedule_entry_id: UUID | None  # None if unmatched
    raw_minutes: int                # from time_clock_entry.worked_minutes
    matched_minutes: int            # after policy application
    match_type: Literal["exact", "grace", "rounded", "unmatched"]


def match_clock_to_roster(
    clock_entry: TimeClockEntry,
    schedule_entries: list[ScheduleEntry],
    settings: TimesheetSettings,
) -> MatchResult:
    """Match a single clock entry against available schedule entries."""
```

#### Algorithm

```
1. For each schedule_entry in the period for this staff_id:
   a. Compute overlap between clock_entry time range and schedule_entry time range.
   b. If clock_in_at is within [schedule.start_time - early_grace, schedule.start_time + late_grace]:
      → candidate match.

2. Select the best candidate (highest overlap).

3. Apply match_policy:
   - pay_actual: matched_minutes = clock_entry.worked_minutes
   - round_to_roster: matched_minutes = schedule_entry duration (if matched), else actual
   - actual_rounded: 
       rounded_in = round(clock_in_at, rounding_minutes, direction)
       rounded_out = round(clock_out_at, rounding_minutes, direction)
       matched_minutes = (rounded_out - rounded_in) - break_minutes

4. Return MatchResult with the determination.
```

#### Rounding Implementation

```python
def round_time(
    t: datetime,
    interval_minutes: int,
    direction: Literal["nearest", "up", "down"],
) -> datetime:
    """Round a timestamp to the nearest interval boundary.
    
    - 'nearest': standard rounding (>= half rounds up)
    - 'up': always round to the next boundary (employer-favourable for clock-in)
    - 'down': always round to the previous boundary (employer-favourable for clock-out)
    """
```

## Branch Scoping Dependency

### Module: `app/modules/timesheets/branch_scope.py`

```python
from fastapi import Depends, Request
from uuid import UUID


class BranchScopedTimesheets:
    """FastAPI dependency that enforces branch-level data isolation.
    
    For branch_admin and users with `timesheet.approve` permission (who are
    not org_admin): filters queries to branch_id ∈ request.state.branch_ids.
    
    For org_admin and global_admin: no filter applied.
    """

    def __init__(self, request: Request):
        self.role = getattr(request.state, "role", None)
        self.branch_ids: list[UUID] = []
        self.should_filter = False

        if self.role in ("branch_admin",):
            raw_ids = getattr(request.state, "branch_ids", None) or []
            self.branch_ids = [UUID(str(bid)) for bid in raw_ids]
            self.should_filter = True
        elif self.role not in ("org_admin", "global_admin"):
            # Non-admin roles with timesheet.approve permission are branch-scoped
            if has_permission(request, "timesheet.approve"):
                raw_ids = getattr(request.state, "branch_ids", None) or []
                self.branch_ids = [UUID(str(bid)) for bid in raw_ids]
                self.should_filter = True

    def apply_filter(self, query, branch_id_column):
        """Apply branch filtering to a SQLAlchemy query.
        
        Returns the query unchanged for org_admin/global_admin.
        Adds WHERE branch_id IN (...) for branch_admin/timesheet.approve holders.
        """
        if not self.should_filter:
            return query
        return query.where(branch_id_column.in_(self.branch_ids))

    def can_access_branch(self, branch_id: UUID | None) -> bool:
        """Check if the current user can access a specific branch's data."""
        if not self.should_filter:
            return True
        if branch_id is None:
            return False  # NULL branch_id not visible to branch-scoped users
        return branch_id in self.branch_ids
```

Usage in router:

```python
@router.get("/timesheets")
async def list_timesheets(
    pay_period_id: UUID,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
):
    query = select(Timesheet).where(
        Timesheet.org_id == org_id,
        Timesheet.pay_period_id == pay_period_id,
    )
    query = scope.apply_filter(query, Timesheet.branch_id)
    ...
```

## API Endpoints (Phase A)

### Module Registration

```python
# app/middleware/modules.py — addition
MODULE_ENDPOINT_MAP["/api/v2/timesheets"] = "timesheets"
MODULE_ENDPOINT_MAP["/api/v2/clocked-in"] = "timesheets"
MODULE_ENDPOINT_MAP["/api/v2/timesheet-settings"] = "timesheets"

# app/core/modules.py — addition
DEPENDENCY_GRAPH["timesheets"] = ["staff", "scheduling"]
```

### Endpoints

| Method | Path | Permission / Role | Description |
|--------|------|---------|-------------|
| GET | `/api/v2/clocked-in` | org_admin, branch_admin, `timesheet.approve` | List currently clocked-in staff |
| POST | `/api/v2/clocked-in/{entry_id}/clock-out` | org_admin, `timesheet.approve` | Manual clock-out |
| GET | `/api/v2/timesheets` | org_admin, branch_admin, `timesheet.approve` | List timesheets for a period |
| GET | `/api/v2/timesheets/{id}` | org_admin, branch_admin, `timesheet.approve` | Get timesheet detail + entries |
| POST | `/api/v2/timesheets/{id}/recompute` | org_admin, `timesheet.approve` | Trigger re-aggregation |
| PUT | `/api/v2/timesheets/{id}/adjust` | org_admin, `timesheet.approve` | Set adjusted_minutes + notes |
| POST | `/api/v2/timesheets/{id}/submit` | org_admin, `timesheet.approve` | Transition open → pending_approval |
| POST | `/api/v2/timesheets/{id}/approve` | org_admin, `timesheet.approve` | Transition pending → approved |
| POST | `/api/v2/timesheets/{id}/reject` | org_admin, `timesheet.approve` | Transition pending/approved → open |
| POST | `/api/v2/timesheets/{id}/lock` | org_admin, `payrun.lock` | Transition approved → locked |
| POST | `/api/v2/timesheets/bulk-approve` | org_admin, `timesheet.approve` | Approve all clean timesheets |
| POST | `/api/v2/timesheets/bulk-lock` | org_admin, `payrun.lock` | Lock all approved timesheets |
| POST | `/api/v2/timesheets/match-all` | org_admin, `timesheet.approve` | Run match engine on period |
| GET | `/api/v2/timesheet-settings` | org_admin (rw), `timesheet.approve` (ro) | Get settings (org + branch) |
| PUT | `/api/v2/timesheet-settings` | org_admin | Update settings |
| GET | `/api/v2/timesheet-settings/branches/{branch_id}` | org_admin (rw), `timesheet.approve` (ro) | Get branch override |
| PUT | `/api/v2/timesheet-settings/branches/{branch_id}` | org_admin | Set branch override |

### Request/Response Schemas

```python
# Timesheet list response
class TimesheetListResponse(BaseModel):
    items: list[TimesheetSummary]
    total: int
    period_summary: PeriodSummary


class TimesheetSummary(BaseModel):
    id: UUID
    staff_id: UUID
    staff_name: str
    branch_name: str | None
    status: str
    rostered_hours: Decimal  # minutes / 60, rounded 2dp
    actual_hours: Decimal
    adjusted_hours: Decimal | None
    variance_hours: Decimal  # actual - rostered
    exception_count: int
    approved_by_name: str | None
    approved_at: datetime | None


class PeriodSummary(BaseModel):
    total_staff: int
    approved_count: int
    pending_count: int
    locked_count: int
    total_ordinary_hours: Decimal
    total_overtime_hours: Decimal
    total_public_holiday_hours: Decimal


# Clocked-in list response
class ClockedInEntry(BaseModel):
    id: UUID
    staff_id: UUID
    staff_name: str
    position: str | None
    clock_in_at: datetime
    elapsed_minutes: int
    on_break: bool
    break_started_at: datetime | None
    clock_in_branch_name: str
    clock_out_branch_name: str | None  # non-null only if cross-branch
    source: str  # kiosk, self_service_mobile, etc.


class ClockedInResponse(BaseModel):
    items: list[ClockedInEntry]
    total: int
```

## Frontend Pages/Tabs (Phase A)

### Location: `frontend-v2/src/pages/staff-timesheets/`

#### Tab 1: Clocked In (`ClockedInTab.tsx`)

- Real-time list of currently clocked-in staff.
- Auto-refresh every 30 seconds (polling with `useInterval`).
- Branch filter via `BranchContext` selector.
- Each row: avatar, name, position, clock-in time, elapsed (auto-updating via `useEffect` interval), break badge, branch labels, source icon.
- Action: "Clock Out" button (confirmation modal with optional notes).
- Header: count badge "5 staff clocked in".

#### Tab 2: Timesheets (`TimesheetsTab.tsx`)

- Pay-period selector (dropdown of recent periods, default = current open).
- Summary cards: total staff, approved, pending, locked, total hours by band.
- Filterable/sortable table with columns: Staff, Status, Rostered, Actual, Adjusted, Variance, Exceptions, Actions.
- Row expansion: per-day breakdown showing individual clock entries matched to schedule entries.
- Actions per row: Adjust, Submit, Approve, Reject, Lock (based on status + role).
- Bulk actions toolbar: "Approve All Clean", "Lock All Approved", "Match All", "Refresh".
- Exception flag icons with tooltip detail.

#### Settings Page (`TimesheetSettings.tsx`)

- Org-wide defaults section.
- Branch overrides section (expandable per branch).
- Form fields: clock rounding (select), rounding direction (radio), early/late grace (number inputs), match policy (select), auto-approve threshold (number), require approval before lock (toggle).
- Save button per section.

### Routing

```typescript
// In staff section routes
{ path: "timesheets", element: <TimesheetsPage /> }
{ path: "timesheets/settings", element: <TimesheetSettingsPage /> }
```

The `TimesheetsPage` component contains the tab switcher (Clocked In / Timesheets).

## Module Registration

### DEPENDENCY_GRAPH Entry

```python
# app/core/modules.py
DEPENDENCY_GRAPH["timesheets"] = ["staff", "scheduling"]
```

The `timesheets` module requires both `staff` (for staff_members data) and `scheduling` (for schedule_entries roster data). It does NOT depend on `payroll` — the payslip linkage is optional and one-directional (timesheet → payslip FK).

### MODULE_ENDPOINT_MAP Entry

```python
# app/middleware/modules.py
MODULE_ENDPOINT_MAP["/api/v2/timesheets"] = "timesheets"
MODULE_ENDPOINT_MAP["/api/v2/clocked-in"] = "timesheets"
MODULE_ENDPOINT_MAP["/api/v2/timesheet-settings"] = "timesheets"
```

### RBAC Additions

```python
# app/modules/auth/rbac.py

# NO new role is added. Instead, add permissions to the available permission set:
# These compose with existing roles via the custom_role_permissions mechanism.

TIMESHEET_PERMISSIONS = {
    "timesheet.approve",   # approve/reject timesheets
    "payrun.lock",         # lock period + issue payslips
}

# Add to AVAILABLE_PERMISSIONS (used by custom_role_permissions)
AVAILABLE_PERMISSIONS = AVAILABLE_PERMISSIONS | TIMESHEET_PERMISSIONS

# org_admin inherits both via org.* wildcard (no change needed).
# branch_admin can be granted timesheet.approve via custom_role_permissions.
# Any role can be granted timesheet.approve — branch scoping still applies.

# Permission check helper (used in endpoints):
def has_permission(request: Request, permission: str) -> bool:
    """Check if current user has a specific permission.
    
    Checks: role-based wildcard (org_admin → org.*) OR
    explicit grant in custom_role_permissions for this user/role.
    """
    ...

# Endpoint-level access: use has_permission(request, 'timesheet.approve')
# instead of checking role names directly.
```

## Migration Plan

### Migration: `0XXX_staff_timesheets_schema`

A single Alembic migration that:

1. Creates `timesheets` table with all columns, constraints, and indexes.
2. Creates `timesheet_settings` table.
3. Adds `clock_out_branch_id` column to `time_clock_entries`.
4. Adds forward-only CHECK constraint on `time_clock_entries.branch_id`.
5. Adds `timesheet_id` column to `timesheet_approvals`.
6. Applies immutability trigger on `time_clock_entries` (trigger-only, no REVOKE).

### Migration Notes

- **Idempotent**: Uses `IF NOT EXISTS` for table/index creation.
- **Non-destructive**: No DROP, no RENAME, no data modification.
- **Backward compatible**: All new columns are nullable or have defaults. Existing functionality continues to work without the timesheets module enabled.
- **Trigger is last**: The immutability trigger is applied as the final step so that if the migration needs to be rolled back, it's the first thing undone.
- **No REVOKE**: The single-role architecture (`postgres` for both app and migrations) makes REVOKE non-viable. The trigger is the primary enforcement mechanism.
- **No kiosk_credentials table**: Kiosk branch scoping uses the existing `users.branch_ids` column (per Q10 findings).
- **CHECK constraint date**: The `ck_tce_branch_id_new_rows` CHECK uses the migration execution timestamp. This is injected at migration write time as a literal.

### Rollback Strategy

```python
def downgrade():
    # 1. Remove immutability trigger
    op.execute("DROP TRIGGER IF EXISTS trg_tce_immutability ON time_clock_entries")
    op.execute("DROP FUNCTION IF EXISTS tce_immutability_guard()")
    
    # 2. Drop new tables
    op.drop_table("timesheet_settings")
    op.drop_table("timesheets")  # CASCADE drops the FK from timesheet_approvals
    
    # 3. Remove added columns
    op.drop_column("time_clock_entries", "clock_out_branch_id")
    op.drop_column("timesheet_approvals", "timesheet_id")
    
    # 4. Remove CHECK constraint
    op.drop_constraint("ck_tce_branch_id_new_rows", "time_clock_entries")
```

## Phase B Architecture Notes (Outline)

### Pay Cycle Groups

```
pay_cycles
├── id, org_id, name, frequency (weekly/fortnightly/monthly)
├── anchor_date (first period starts here)
└── pay_date_offset_days (days after period end → pay date)

pay_cycle_assignments
├── id, pay_cycle_id
├── target_type (all/branch/employment_type/staff)
└── target_id (nullable for 'all')
```

`PayPeriod` gains `pay_cycle_id` FK. UNIQUE changes to `(org_id, pay_cycle_id, start_date)`. A scheduled task auto-generates periods per cycle.

### Locked State → Payslip

When a timesheet transitions to `locked`:
1. Hour bands are frozen.
2. `payslip_id` is populated when draft generation runs.
3. A locked timesheet with a finalised payslip is fully sealed.

### Corrections After Lock

A new `timesheet_adjustments` table:
```
timesheet_adjustments
├── id, org_id
├── original_timesheet_id (FK)
├── correction_period_id (FK → pay_periods, the NEXT open period)
├── adjustment_minutes (positive or negative)
├── reason, created_by, created_at
```

The adjustment is included in the correction period's payslip as a separate line item.

## Phase C Architecture Notes (Outline)

### Overtime Auto-Detect

Settings extend `timesheet_settings`:
- `daily_overtime_threshold_minutes` (default 480 = 8 hours)
- `weekly_overtime_threshold_minutes` (default 2400 = 40 hours)
- `overtime_rate_multiplier` (default 1.5)

The aggregation service classifies minutes exceeding thresholds into `overtime_minutes`.

### Leave Rules Engine

```python
class LeaveRuleSet(Protocol):
    """Versioned leave rules provider."""
    
    def accrue(self, staff: StaffMember, period: PayPeriod) -> Decimal: ...
    def value_leave_taken(self, staff: StaffMember, request: LeaveRequest) -> Decimal: ...
    def otherwise_working_day(self, staff: StaffMember, date: date) -> bool: ...
    def public_holiday(self, branch: Branch, date: date) -> bool: ...
    def termination_payout(self, staff: StaffMember) -> Decimal: ...


def resolve_ruleset(org_id: UUID, effective_date: date) -> LeaveRuleSet:
    """Return the applicable rule set for the org at the given date."""
```

Implementations:
- `HolidaysAct2003RuleSet` — current active implementation.
- `EmploymentLeaveAct2026RuleSet` — stubbed for future legislation.

## Phase D — Out of Scope

Phase D (PAYE calc engine, IRD payday filing, bank-file export) is explicitly NOT specced. These are separate modules that consume the Timesheet and Payslip data produced by Phases A–C.

## Resolved Design Decisions (Q5–Q8)

### Q5. Timesheet Auto-Creation Trigger — RESOLVED: Lazy + Safety Net

**Decision:** Hybrid of B (lazy) with a scheduled sweep safety net.

- Timesheet rows are created LAZILY: on first clock-in for that staff in the period, OR when an approved LeaveRequest's dates overlap the period, OR when a ScheduleEntry exists for that staff in the period.
- A scheduled sweep (`materialise_missing_timesheets`) runs before pay-run cutoff to catch any gaps.
- Staff with NO clock activity, NO leave, and NO scheduled shifts are flagged as "no_activity" EXCEPTION (alert only — no blank row created).

See "Timesheet Lifecycle — Creation Triggers" section above for full implementation detail.

### Q6. Approver Role — RESOLVED: Permission Grant (NOT a standalone role)

**Decision:** Option B — permission grant composable with existing roles.

- There is NO new `approver` RBAC role.
- `timesheet.approve` is a permission grant attachable to any existing role via `custom_role_permissions`.
- `timesheet.approve` (approve hours) is SEPARATE from `payrun.lock` (lock period + issue payslips). A user can hold one without the other.
- Branch scoping still applies: a branch_admin with `timesheet.approve` can only approve timesheets for their branch(es).
- The `org_admin` role inherits both permissions via wildcard.

### Q7. Multi-Branch Staff Timesheet Splitting — RESOLVED: One Per Staff Per Period

**Decision:** Option A confirmed — one timesheet per staff per period.

Required by NZ employment law (one employment relationship → one Payslip per period). Per-branch attribution is preserved inside the timesheet via `clock_in_branch_id`/`clock_out_branch_id` but the unit of approval and pay is the single aggregated row. Overtime/leave/public-holiday thresholds are computed per-person per-period, never per-branch.

### Q8. Settings Access for Approvers — RESOLVED: Read-Only

**Decision:** Users with `timesheet.approve` permission get READ-ONLY access to calculation-affecting settings.

- They CAN see: clock rounding, grace window, match-to-roster policy, overtime thresholds, break rules.
- They CANNOT write/modify any settings.
- They CANNOT see financial/PII settings (pay rates, bank/IRD config).
- Write access remains exclusive to `org_admin`.

## Q9 Investigation: DB Role for Immutability REVOKE

### Findings

- The app connects as PostgreSQL user `postgres` (from `.env.example`: `POSTGRES_USER=postgres`, `DATABASE_URL=postgresql+asyncpg://postgres:...@postgres:5432/workshoppro`).
- Alembic migrations ALSO run as `postgres` (same connection string — the entrypoint runs `alembic upgrade head` using the same app container).
- The runtime app role and the migration role are THE SAME (`postgres`).
- The existing RLS pattern does NOT use REVOKE/GRANT — it uses `current_setting('app.current_org_id')` session variables with `CREATE POLICY ... USING (org_id = current_setting(...))`. The app sets this via `set_config()` per-session in `get_db_session`.

### Implication

A REVOKE on the `postgres` role would block BOTH the app AND migrations. This is not viable with the current single-role architecture.

### Recommendation (ADOPTED)

Use a BEFORE UPDATE/DELETE trigger (`tce_immutability_guard()`) as the PRIMARY enforcement mechanism instead of REVOKE. The trigger fires for ALL roles including `postgres`, effectively making the columns immutable at the application level.

For emergency data recovery, a DBA can temporarily:
```sql
ALTER TABLE time_clock_entries DISABLE TRIGGER trg_tce_immutability;
-- ... fix data ...
ALTER TABLE time_clock_entries ENABLE TRIGGER trg_tce_immutability;
```
This requires superuser (which `postgres` is), matching the "superuser-only override mechanism" requirement.

The design's immutability section has been updated to TRIGGER-ONLY (REVOKE removed).

## Q10 Investigation: Kiosk Auth Model

### Findings

- Kiosk auth is model (a): a plain `users` row with `role='kiosk'`.
- Kiosk users are created via `POST /api/v1/org/users/invite` with `password` provided (bypasses email invitation — immediate creation).
- Kiosk users get a 30-day JWT token on login (vs 15min for normal users).
- The JWT carries `branch_ids` (a JSONB column on the `users` table, always present for all roles).
- `branch_ids` is already used by `BranchContextMiddleware` to scope branch_admin users.
- Existing kiosk users likely have `branch_ids = []` (empty — they're not currently branch-scoped).
- The kiosk rate-limiter uses `user_id` from the JWT (key: `rl:kiosk:{user_id}`).
- There is NO existing kiosk-specific table or device management.
- Multiple kiosks per branch would require multiple user accounts (one per device).

### Recommendation (ADOPTED)

Use model (a) — add branch to the kiosk user's `branch_ids` array. One kiosk user = one branch. For v1 this is sufficient (most workshops have 1 kiosk per branch).

Implementation:
1. When creating/inviting a kiosk user, require exactly one `branch_id` in the request body.
2. Store it in `users.branch_ids = [branch_id]` (existing JSONB column).
3. On kiosk clock-in, derive `TimeClockEntry.branch_id` from the JWT's `branch_ids[0]`.
4. The existing `BranchContextMiddleware` already reads `branch_ids` from JWT claims — kiosk users will be naturally scoped.
5. No new table needed for v1. If multi-device-per-branch or device-level revocation is needed later, `kiosk_credentials` table can be added in a future phase.

The design's kiosk section has been updated to remove the proposed `kiosk_credentials` table.

## Assumption Validation

### Q5: "no_activity" Exception Interpretation

The user's answer states: "flags 'no activity' staff as an EXCEPTION rather than creating a blank row."

**Confirmed interpretation:** The sweep does NOT create a Timesheet row for no-activity staff. It only logs/alerts them as a "no_activity" exception. This is correct — if the sweep WERE to create a row with the exception flag, that would contradict "rather than creating a blank row."

**Validation:** Sound. The sweep creates rows only for staff who have roster/leave activity but are missing a Timesheet row (data-entry gap catch). Staff with genuinely no activity get no row.

### Q6: Permission Composability with Branch Scoping

The user says: "`timesheet.approve` composes with branch scoping."

**Confirmed interpretation:** A `branch_admin` who has `timesheet.approve` granted can approve timesheets ONLY for their branch(es). The permission check happens at the endpoint layer, branch scoping is a separate query filter applied by `BranchScopedTimesheets` dependency.

**Validation:** Sound. The existing `custom_role_permissions` mechanism is evaluated at the endpoint (permission check), while branch scoping is a parallel concern applied at the query layer. They compose naturally — a user needs BOTH the permission AND branch access to perform the action.

### Q7: One Timesheet Per Staff Per Period

No assumptions to validate — straightforward, matches existing `UNIQUE(staff_id, pay_period_id)` constraint.

### Q8: No Financial/PII Leak into Settings Endpoint

The user says: "NO access to financial/PII settings (pay rates, bank/IRD config)."

**Confirmed interpretation:** Pay rates are on `StaffPayRate` (a separate endpoint `GET /api/v2/staff/:id/pay-rates`), not on `timesheet_settings`. The `timesheet_settings` table only contains: clock_rounding_minutes, clock_rounding_direction, early_grace_minutes, late_grace_minutes, match_policy, auto_approve_threshold_minutes, require_approval_before_lock.

**Validation:** Sound. There is no pay-rate data leaking into the timesheet settings endpoint. The GET `/api/v2/timesheet-settings` endpoint returns only calculation-affecting fields — no financial or PII data.
