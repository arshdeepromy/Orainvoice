# Design Document: Booking-to-Job Workflow

## Overview

This feature implements the complete booking → job → invoice workflow. It adds a Booking List Panel below the existing calendar, a Job Creation Modal for converting bookings to job cards with staff assignment, a dedicated Jobs Page with live timers, and a "Confirm Job Done" flow that auto-creates a draft invoice and hands off to the existing invoice module.

The design builds on existing modules:
- **Bookings module** (`app/modules/bookings/`): calendar, CRUD, `convert_booking_to_job_card` service
- **Job Cards module** (`app/modules/job_cards/`): models for `job_cards`, `job_card_items`, `time_entries`; create/list/update/convert endpoints
- **Invoices module** (`app/modules/invoices/`): full CRUD, PDF generation, `convert_job_card_to_invoice` service
- **Staff module** (`app/modules/staff/`): staff member listing with active status
- **Auth/RBAC** (`app/modules/auth/rbac.py`): `require_role()` dependency for endpoint protection

Key design decisions:
1. Timer tracking is server-authoritative — `started_at`/`stopped_at` are set server-side to avoid client clock drift.
2. The existing `convert_booking_to_job_card` service is extended (not replaced) to accept an `assigned_to` parameter.
3. Role-based restrictions are enforced both backend (403 responses) and frontend (conditional UI).
4. The `time_entries` table already exists with the needed schema; no new tables are required.

## Architecture

```mermaid
flowchart TD
    subgraph Frontend ["Frontend (React + TypeScript)"]
        BC[BookingCalendar]
        BLP[BookingListPanel]
        JCM[JobCreationModal]
        JP[JobsPage]
        JT[JobTimer]
    end

    subgraph Backend ["Backend (FastAPI)"]
        BR[Bookings Router]
        JCR[Job Cards Router]
        IR[Invoices Router]
        BS[Bookings Service]
        JCS[Job Cards Service]
        IS[Invoices Service]
    end

    subgraph DB ["PostgreSQL (RLS)"]
        BT[(bookings)]
        JCT[(job_cards)]
        TET[(time_entries)]
        IT[(invoices)]
    end

    BC --> BLP
    BLP -->|Cancel| BR
    BLP -->|Create Job| JCM
    JCM -->|POST /bookings/{id}/convert| BR
    BR --> BS
    BS --> JCS
    JP --> JT
    JT -->|POST /job-cards/{id}/timer/start| JCR
    JT -->|POST /job-cards/{id}/timer/stop| JCR
    JP -->|POST /job-cards/{id}/complete| JCR
    JCR --> JCS
    JCS -->|auto-create invoice| IS

    BS --> BT
    JCS --> JCT
    JCS --> TET
    IS --> IT
```

### Request Flow: Booking → Job → Invoice

1. User views BookingCalendar → BookingListPanel fetches bookings for selected date range via `GET /api/v1/bookings?start_date=...&end_date=...`
2. User clicks "Create Job" → JobCreationModal opens, pre-filled from booking data
3. User selects assignee (self for non-admin, any staff for admin) → submits → `POST /api/v1/bookings/{id}/convert?target=job_card` with `assigned_to` in body
4. Job appears on JobsPage → user starts timer → `POST /api/v1/job-cards/{id}/timer/start`
5. User stops timer → `POST /api/v1/job-cards/{id}/timer/stop`
6. User clicks "Confirm Job Done" → `POST /api/v1/job-cards/{id}/complete` which stops any active timer, sets status to "completed", calls `convert_job_card_to_invoice`, sets status to "invoiced", returns invoice ID
7. Frontend navigates to `/invoices/{id}` for the existing Invoice_Flow

## Components and Interfaces

### Backend Components

#### 1. Extended Booking Conversion (`app/modules/bookings/service.py`)

The existing `convert_booking_to_job_card()` function gains an optional `assigned_to` parameter:

```python
async def convert_booking_to_job_card(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    booking_id: uuid.UUID,
    assigned_to: uuid.UUID | None = None,  # NEW
    ip_address: str | None = None,
) -> dict:
```

The `assigned_to` value is passed through to `create_job_card()`, which also gains the parameter.

#### 2. Timer Service (`app/modules/job_cards/service.py`)

New functions added to the existing service:

```python
async def start_timer(
    db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID,
    job_card_id: uuid.UUID, role: str,
) -> dict:
    """Create a TimeEntry with started_at=now(). Returns TimeEntry dict.
    Raises ValueError if timer already active. Raises PermissionError if
    non-admin user is not the assignee."""

async def stop_timer(
    db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID,
    job_card_id: uuid.UUID, role: str,
) -> dict:
    """Set stopped_at=now() and calculate duration_minutes on active TimeEntry.
    Raises ValueError if no active timer. Raises PermissionError if
    non-admin user is not the assignee."""

async def get_timer_entries(
    db: AsyncSession, *, org_id: uuid.UUID, job_card_id: uuid.UUID,
) -> dict:
    """Return all TimeEntry records for a job card plus active flag."""

async def complete_job(
    db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID,
    job_card_id: uuid.UUID, role: str, ip_address: str | None = None,
) -> dict:
    """Stop active timer if any, set status='completed', convert to invoice,
    set status='invoiced'. Returns {job_card_id, invoice_id}."""

async def assign_job(
    db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID,
    job_card_id: uuid.UUID, role: str,
    new_assignee_id: uuid.UUID, takeover_note: str | None = None,
) -> dict:
    """Assign or reassign a job card. Non-admin can only assign to self.
    If takeover_note provided, appends note with previous assignee and timestamp."""
```

#### 3. Timer Endpoints (`app/modules/job_cards/router.py`)

New endpoints added to the existing router:

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/job-cards/{id}/timer/start` | `org_admin`, `salesperson` | Start timer |
| `POST` | `/api/v1/job-cards/{id}/timer/stop` | `org_admin`, `salesperson` | Stop timer |
| `GET` | `/api/v1/job-cards/{id}/timer` | `org_admin`, `salesperson` | Get all time entries |
| `POST` | `/api/v1/job-cards/{id}/complete` | `org_admin`, `salesperson` | Confirm done + create invoice |
| `PUT` | `/api/v1/job-cards/{id}/assign` | `org_admin`, `salesperson` | Assign/reassign job |

#### 4. Updated Booking Convert Endpoint

The existing `POST /api/v1/bookings/{id}/convert?target=job_card` endpoint accepts an optional JSON body:

```python
class BookingConvertBody(BaseModel):
    assigned_to: uuid.UUID | None = None
```

### Frontend Components

#### 1. BookingListPanel (`frontend/src/pages/bookings/BookingListPanel.tsx`)

Rendered below BookingCalendar. Receives the current date range and view from the calendar.

Props:
```typescript
interface BookingListPanelProps {
  startDate: Date;
  endDate: Date;
  view: 'day' | 'week' | 'month';
  refreshKey: number;
  onRefresh: () => void;
}
```

Displays a table with columns: Customer, Service, Date/Time, Vehicle Rego, Status, Actions.
- "Cancel" button: visible when status ∈ {pending, scheduled, confirmed} and `converted_job_id` is null
- "Create Job" button: visible when status ∈ {pending, scheduled, confirmed} and `converted_job_id` is null
- "View Job" link: visible when `converted_job_id` is not null

#### 2. JobCreationModal (`frontend/src/pages/bookings/JobCreationModal.tsx`)

Props:
```typescript
interface JobCreationModalProps {
  booking: BookingSearchResult;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (jobCardId: string) => void;
}
```

Pre-fills: customer name, vehicle rego, service type, notes from booking.
- If user role is `org_admin`: shows StaffPicker dropdown with all active staff, defaulting to current user.
- If user role is non-admin: shows current user name as read-only assignee.

Submits via `POST /api/v1/bookings/{booking.id}/convert?target=job_card` with `{ assigned_to }` body.

#### 3. JobsPage (`frontend/src/pages/jobs/JobsPage.tsx`)

New page at route `/jobs`. Fetches `GET /api/v1/job-cards?status=open,in_progress` (extended query param).

Displays job cards in a list/card layout with:
- Customer name, service description, vehicle rego, assigned staff name
- Status badge (open / in_progress)
- JobTimer component
- "Confirm Job Done" button (visible when status is `in_progress`)
- Filter toggle: Active only / All jobs

Sorting: `in_progress` first, then `open`, each group by `created_at` descending.

#### 4. JobTimer (`frontend/src/pages/jobs/JobTimer.tsx`)

Props:
```typescript
interface JobTimerProps {
  jobCardId: string;
  assignedTo: string | null;
  assignedToName: string | null;
  status: 'open' | 'in_progress' | 'completed' | 'invoiced';
  onStatusChange: () => void;
}
```

Behaviour:
- Fetches `GET /api/v1/job-cards/{id}/timer` on mount to get existing entries and active state.
- If active timer exists: shows live elapsed counter (using `setInterval` with 1s tick, calculating from `started_at` server timestamp) + "Stop Timer" button.
- If no active timer and job is open/in_progress: shows "Start Timer" button (subject to role checks).
- Displays total accumulated time across all entries.
- Role-based visibility:
  - Admin: always shows Start/Stop buttons
  - Non-admin assigned to job: shows Start/Stop buttons
  - Non-admin not assigned: shows message "This job is assigned to [name]" + "Take Over Job" button
  - Non-admin, unassigned job: shows "Assign to Me" button

#### 5. StaffPicker (`frontend/src/components/StaffPicker.tsx`)

Reusable dropdown that fetches `GET /api/v1/staff?is_active=true` and renders a select.

```typescript
interface StaffPickerProps {
  value: string | null;
  onChange: (staffId: string) => void;
  disabled?: boolean;
}
```

#### 6. TakeOverDialog (`frontend/src/pages/jobs/TakeOverDialog.tsx`)

Modal with a required textarea for the takeover note. Calls `PUT /api/v1/job-cards/{id}/assign` with `{ new_assignee_id, takeover_note }`.

## Data Models

### Existing Tables (No Schema Changes Required)

The `job_cards`, `job_card_items`, and `time_entries` tables already have the required columns. The key fields used by this feature:

**job_cards:**
- `id`, `org_id`, `customer_id`, `vehicle_rego`, `status` (open/in_progress/completed/invoiced)
- `description`, `notes`, `assigned_to` (FK → users.id), `created_by`, `created_at`, `updated_at`

**time_entries:**
- `id`, `org_id`, `user_id`, `job_card_id`, `invoice_id`
- `started_at`, `stopped_at`, `duration_minutes`, `hourly_rate`, `notes`, `created_at`

**bookings:**
- `converted_job_id` — set when booking is converted to a job card

### Schema Enhancement: `assigned_to` on `job_cards`

The `assigned_to` column already exists as `ForeignKey("users.id")`. However, the `create_job_card` service function does not currently accept or set it. The enhancement is purely at the service layer — passing `assigned_to` through to the `JobCard` constructor.

### Query Patterns

1. **Active jobs for org**: `SELECT * FROM job_cards WHERE org_id = :org_id AND status IN ('open', 'in_progress') ORDER BY CASE WHEN status = 'in_progress' THEN 0 ELSE 1 END, created_at DESC`
2. **Active timer for job**: `SELECT * FROM time_entries WHERE job_card_id = :id AND stopped_at IS NULL LIMIT 1`
3. **All timers for job**: `SELECT * FROM time_entries WHERE job_card_id = :id ORDER BY started_at`
4. **Total time for job**: `SELECT COALESCE(SUM(duration_minutes), 0) FROM time_entries WHERE job_card_id = :id AND stopped_at IS NOT NULL`


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Booking date range filtering

*For any* set of bookings and any date range [start, end], the bookings returned by the list endpoint (or displayed in the BookingListPanel) should include exactly those bookings whose `start_time` falls within [start, end], and no others.

**Validates: Requirements 1.3**

### Property 2: Booking list sort order

*For any* list of bookings returned for a date range, for every consecutive pair (booking[i], booking[i+1]), `booking[i].start_time <= booking[i+1].start_time`.

**Validates: Requirements 1.4**

### Property 3: Cancel button visibility

*For any* booking, the "Cancel" button is visible if and only if `status ∈ {pending, scheduled, confirmed}` AND `converted_job_id` is null. In all other cases (status is cancelled/completed/no_show, or converted_job_id is set), the button is hidden.

**Validates: Requirements 2.1, 2.5**

### Property 4: Cancellation status transition

*For any* booking with status ∈ {pending, scheduled, confirmed}, after a successful cancellation request, the booking's status is "cancelled".

**Validates: Requirements 2.3**

### Property 5: Create Job button visibility

*For any* booking, the "Create Job" button is visible if and only if `status ∈ {pending, scheduled, confirmed}` AND `converted_job_id` is null. When `converted_job_id` is not null, a link to the existing job card is shown instead.

**Validates: Requirements 3.1, 3.9**

### Property 6: Job creation pre-populates from booking

*For any* booking converted to a job card, the resulting job card's `description` contains the booking's `service_type`, and the job card's `notes` contains the booking's `notes`, and the job card's `vehicle_rego` matches the booking's `vehicle_rego`.

**Validates: Requirements 3.2**

### Property 7: Conversion creates job with correct assignee

*For any* booking conversion request with an `assigned_to` value, the resulting job card has `status = "open"` and `assigned_to` equal to the requested value, and the booking's `converted_job_id` is set to the new job card's ID.

**Validates: Requirements 3.6**

### Property 8: Role-based timer access control

*For any* user and any job card, the timer start/stop operation succeeds if and only if the user's role is "org_admin" OR the job card's `assigned_to` equals the user's `user_id`. Otherwise, the backend returns 403 Forbidden.

**Validates: Requirements 4.2, 4.3, 8.1, 8.3, 8.9**

### Property 9: Start timer creates TimeEntry

*For any* job card with no active timer (no TimeEntry where `stopped_at IS NULL`), calling start-timer creates a new TimeEntry with `started_at` set to a server timestamp and `stopped_at = NULL`, and updates the job card's status to "in_progress".

**Validates: Requirements 4.6, 7.1**

### Property 10: Stop timer sets stopped_at and duration

*For any* job card with an active timer, calling stop-timer sets `stopped_at` to a server timestamp and `duration_minutes` equals `ceil((stopped_at - started_at).total_seconds() / 60)`. After stopping, no TimeEntry for that job card has `stopped_at IS NULL`.

**Validates: Requirements 4.9, 7.2**

### Property 11: Elapsed time calculation

*For any* TimeEntry with `started_at` and a reference time `now`, the elapsed display value equals `now - started_at` in hours:minutes:seconds format. This is a pure function of two timestamps.

**Validates: Requirements 4.7**

### Property 12: Accumulated time is sum of durations

*For any* job card with N completed time entries (where `stopped_at IS NOT NULL`), the total accumulated time equals `SUM(duration_minutes)` across all N entries.

**Validates: Requirements 4.10, 4.11**

### Property 13: Double start returns 409

*For any* job card that already has an active TimeEntry (`stopped_at IS NULL`), a start-timer request returns HTTP 409 Conflict and does not create a new TimeEntry.

**Validates: Requirements 7.3**

### Property 14: Stop with no active timer returns 404

*For any* job card that has no active TimeEntry (all entries have `stopped_at IS NOT NULL`, or no entries exist), a stop-timer request returns HTTP 404 Not Found.

**Validates: Requirements 7.4**

### Property 15: GET timer returns entries with active flag

*For any* job card, `GET /job-cards/{id}/timer` returns all TimeEntry records for that job card, and the `is_active` flag is `true` if and only if exactly one TimeEntry has `stopped_at IS NULL`.

**Validates: Requirements 7.5**

### Property 16: Active jobs filtering

*For any* set of job cards in an organisation, the active jobs list contains exactly those with `status ∈ {open, in_progress}` and excludes all with `status ∈ {completed, invoiced}`.

**Validates: Requirements 5.1, 5.4**

### Property 17: Jobs page sort order

*For any* list of active job cards, all `in_progress` jobs appear before all `open` jobs, and within each group, jobs are sorted by `created_at` descending.

**Validates: Requirements 5.3**

### Property 18: Complete job flow

*For any* job card with status "in_progress", calling complete-job: (a) stops any active timer, (b) sets status to "completed", (c) creates a draft invoice via the existing conversion, and (d) sets status to "invoiced". The returned invoice_id is valid.

**Validates: Requirements 6.2, 6.3, 6.4**

### Property 19: Invoice includes job items and labour time

*For any* completed job card with line items and time entries, the generated invoice contains line items matching the job card's items, plus a labour line item whose quantity reflects the total accumulated `duration_minutes` from all time entries.

**Validates: Requirements 6.6**

### Property 20: Non-admin self-assignment only

*For any* non-admin user creating a job via booking conversion, the `assigned_to` value must equal the user's own `user_id`. If a different value is provided, the backend rejects with 403.

**Validates: Requirements 8.2**

### Property 21: Assign-to-me updates assigned_to

*For any* job card with `assigned_to = NULL` or assigned to another user, when a user calls the assign endpoint with their own `user_id`, the job card's `assigned_to` is updated to that user's `user_id`.

**Validates: Requirements 8.6**

### Property 22: Takeover appends note with provenance

*For any* job takeover, the job card's `notes` field after the operation contains the previous assignee's name and a timestamp, in addition to any pre-existing notes.

**Validates: Requirements 8.8**

### Property 23: Organisation-scoped access (RLS)

*For any* user in organisation A, all timer endpoints return only TimeEntry records where `org_id = A`. Requests for job cards belonging to a different organisation return 404.

**Validates: Requirements 7.6**

## Error Handling

### Backend Error Responses

| Scenario | HTTP Status | Response Body |
|----------|-------------|---------------|
| Start timer when one is already active | 409 Conflict | `{"detail": "A timer is already running for this job card"}` |
| Stop timer when none is active | 404 Not Found | `{"detail": "No active timer found for this job card"}` |
| Non-admin starts timer on unassigned job | 403 Forbidden | `{"detail": "You can only start jobs assigned to you."}` |
| Non-admin starts timer on job assigned to other | 403 Forbidden | `{"detail": "You can only start jobs assigned to you."}` |
| Non-admin modifies job assigned to other (non-reassign) | 403 Forbidden | `{"detail": "You can only modify jobs assigned to you."}` |
| Job card not found or wrong org | 404 Not Found | `{"detail": "Job card not found in this organisation"}` |
| Booking not found or wrong org | 404 Not Found | `{"detail": "Booking not found in this organisation"}` |
| Booking already converted | 400 Bad Request | `{"detail": "Booking has already been converted to a job card"}` |
| Invoice creation fails during complete | 500 Internal Server Error | `{"detail": "Invoice creation failed: [reason]"}` — job stays "completed" |
| Invalid status transition | 400 Bad Request | `{"detail": "Cannot transition from [current] to [target]"}` |

### Frontend Error Handling

- All API calls use try/catch with toast notifications for errors.
- Network errors show a generic "Connection error, please try again" message.
- The "Confirm Job Done" flow handles partial failure: if invoice creation fails after status is set to "completed", the UI shows a "Retry Invoice" button that calls `POST /api/v1/job-cards/{id}/convert` directly.
- Optimistic UI updates are NOT used for timer operations — the UI waits for server confirmation to maintain accuracy.

### Timer Edge Cases

- Browser tab goes to sleep: on visibility change (`document.visibilitychange`), the JobTimer re-fetches `GET /job-cards/{id}/timer` to resync elapsed time from server.
- Multiple browser tabs: since timer state is server-authoritative, all tabs will show consistent state after their next fetch.

## Testing Strategy

### Property-Based Testing

Library: **Hypothesis** (Python backend), **fast-check** (TypeScript frontend)

Each property test runs a minimum of 100 iterations with randomly generated inputs.

Each test is tagged with a comment referencing the design property:
```
# Feature: booking-to-job-workflow, Property {N}: {title}
```

Backend property tests focus on:
- Timer state machine (Properties 9, 10, 13, 14, 15)
- Role-based access control (Properties 8, 20)
- Job completion flow (Property 18)
- Invoice generation content (Property 19)
- Sorting and filtering (Properties 2, 16, 17)
- Assignment and takeover (Properties 21, 22)
- RLS enforcement (Property 23)

Frontend property tests focus on:
- Button visibility rules (Properties 3, 5)
- Date range filtering logic (Property 1)
- Elapsed time calculation (Property 11)
- Accumulated time summation (Property 12)
- Booking-to-job data mapping (Property 6)

### Unit Testing

Unit tests complement property tests for specific examples and edge cases:
- Cancellation confirmation dialog flow
- Modal open/close lifecycle
- Error message display on API failure
- "Retry Invoice" button appearance after partial failure
- Staff picker rendering for admin vs non-admin
- Timer display format (00:00:00)
- Navigation to invoice detail after completion

### Integration Testing

- End-to-end booking → job → timer → complete → invoice flow
- Concurrent timer start attempts (race condition)
- Cross-organisation access denial
