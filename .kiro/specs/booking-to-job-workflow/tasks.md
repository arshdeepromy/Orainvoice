# Implementation Plan: Booking-to-Job Workflow

## Overview

Implement the end-to-end booking → job → invoice workflow. Backend work extends existing bookings and job_cards modules with timer service functions and new endpoints. Frontend work adds BookingListPanel, JobCreationModal, StaffPicker, JobsPage with JobTimer, and TakeOverDialog. All changes build on existing FastAPI + SQLAlchemy backend and React + TypeScript frontend.

## Tasks

- [x] 1. Extend backend booking conversion with assigned_to support
  - [x] 1.1 Update `create_job_card` in `app/modules/job_cards/service.py` to accept and set `assigned_to` parameter
    - Add `assigned_to: uuid.UUID | None = None` parameter to `create_job_card()`
    - Pass `assigned_to` to the `JobCard` model constructor
    - _Requirements: 3.6, 3.7_
  - [x] 1.2 Update `convert_booking_to_job_card` in `app/modules/bookings/service.py` to accept and forward `assigned_to`
    - Add `assigned_to: uuid.UUID | None = None` parameter
    - Pass it through to `create_job_card()`
    - _Requirements: 3.6_
  - [x] 1.3 Add `BookingConvertBody` schema and update the convert endpoint in `app/modules/bookings/router.py`
    - Create `BookingConvertBody(BaseModel)` with optional `assigned_to: uuid.UUID | None = None` in `app/modules/bookings/schemas.py`
    - Update `POST /bookings/{id}/convert` to accept the body and pass `assigned_to` to the service
    - _Requirements: 3.6_
  - [x] 1.4 Write property test for conversion with assignee (backend)
    - **Property 7: Conversion creates job with correct assignee**
    - **Validates: Requirements 3.6**

- [x] 2. Implement backend timer service functions
  - [x] 2.1 Implement `start_timer` in `app/modules/job_cards/service.py`
    - Create TimeEntry with `started_at=now()`, `stopped_at=NULL`
    - Update job card status to `in_progress`
    - Raise `ValueError` if a timer is already active (409)
    - Raise `PermissionError` if non-admin user is not the assignee (403)
    - _Requirements: 4.6, 7.1, 4.2, 4.3, 8.3_
  - [x] 2.2 Implement `stop_timer` in `app/modules/job_cards/service.py`
    - Set `stopped_at=now()` on active TimeEntry, calculate `duration_minutes`
    - Raise `ValueError` if no active timer (404)
    - Raise `PermissionError` if non-admin user is not the assignee (403)
    - _Requirements: 4.9, 7.2, 8.9_
  - [x] 2.3 Implement `get_timer_entries` in `app/modules/job_cards/service.py`
    - Return all TimeEntry records for a job card ordered by `started_at`
    - Include `is_active` flag (true if any entry has `stopped_at IS NULL`)
    - _Requirements: 7.5, 4.11_
  - [x] 2.4 Write property tests for timer state machine (backend)
    - **Property 9: Start timer creates TimeEntry**
    - **Property 10: Stop timer sets stopped_at and duration**
    - **Property 13: Double start returns 409**
    - **Property 14: Stop with no active timer returns 404**
    - **Property 15: GET timer returns entries with active flag**
    - **Validates: Requirements 4.6, 4.9, 7.1, 7.2, 7.3, 7.4, 7.5**
  - [x] 2.5 Write property test for role-based timer access (backend)
    - **Property 8: Role-based timer access control**
    - **Validates: Requirements 4.2, 4.3, 8.1, 8.3, 8.9**

- [x] 3. Implement backend complete-job and assign-job service functions
  - [x] 3.1 Implement `complete_job` in `app/modules/job_cards/service.py`
    - Stop active timer if any, set status to `completed`
    - Call existing `convert_job_card_to_invoice` to create draft invoice
    - Set status to `invoiced`, return `{job_card_id, invoice_id}`
    - Handle invoice creation failure: keep status as `completed`, raise error
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.6_
  - [x] 3.2 Implement `assign_job` in `app/modules/job_cards/service.py`
    - Non-admin can only assign to self; admin can assign to any active staff
    - If `takeover_note` provided, append note with previous assignee name and timestamp to job card notes
    - _Requirements: 8.5, 8.6, 8.7, 8.8_
  - [x] 3.3 Write property tests for complete-job and assignment (backend)
    - **Property 18: Complete job flow**
    - **Property 21: Assign-to-me updates assigned_to**
    - **Property 22: Takeover appends note with provenance**
    - **Validates: Requirements 6.2, 6.3, 6.4, 8.6, 8.8**

- [x] 4. Add backend timer and job management endpoints
  - [x] 4.1 Add timer endpoints to `app/modules/job_cards/router.py`
    - `POST /api/v1/job-cards/{id}/timer/start` — calls `start_timer`, returns TimeEntry
    - `POST /api/v1/job-cards/{id}/timer/stop` — calls `stop_timer`, returns updated TimeEntry
    - `GET /api/v1/job-cards/{id}/timer` — calls `get_timer_entries`, returns entries + active flag
    - Map `ValueError` to 409/404, `PermissionError` to 403
    - Enforce RLS via org_id from auth context
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_
  - [x] 4.2 Add complete and assign endpoints to `app/modules/job_cards/router.py`
    - `POST /api/v1/job-cards/{id}/complete` — calls `complete_job`, returns `{job_card_id, invoice_id}`
    - `PUT /api/v1/job-cards/{id}/assign` — accepts `{new_assignee_id, takeover_note?}`, calls `assign_job`
    - _Requirements: 6.3, 8.5, 8.6, 8.7, 8.8_
  - [x] 4.3 Add response schemas in `app/modules/job_cards/schemas.py`
    - `TimeEntryResponse`, `TimerStatusResponse`, `CompleteJobResponse`, `AssignJobRequest`, `AssignJobResponse`
    - _Requirements: 7.1, 7.2, 7.5_
  - [x] 4.4 Write property test for non-admin self-assignment enforcement (backend)
    - **Property 20: Non-admin self-assignment only**
    - **Validates: Requirements 8.2**
  - [x] 4.5 Write property test for RLS enforcement (backend)
    - **Property 23: Organisation-scoped access (RLS)**
    - **Validates: Requirements 7.6**

- [x] 5. Checkpoint — Backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement StaffPicker shared component
  - [x] 6.1 Create `frontend/src/components/StaffPicker.tsx`
    - Fetch `GET /api/v1/staff?is_active=true` on mount
    - Render a select dropdown with staff name options
    - Accept `value`, `onChange`, `disabled` props
    - _Requirements: 3.4_

- [x] 7. Implement BookingListPanel and JobCreationModal
  - [x] 7.1 Create `frontend/src/pages/bookings/BookingListPanel.tsx`
    - Accept `startDate`, `endDate`, `view`, `refreshKey`, `onRefresh` props
    - Fetch bookings for the date range via `GET /api/v1/bookings?start_date=...&end_date=...`
    - Render table with columns: Customer, Service, Date/Time, Vehicle Rego, Status, Actions
    - Sort by `start_time` ascending
    - Show "Cancel" button when status ∈ {pending, scheduled, confirmed} and `converted_job_id` is null
    - Show "Create Job" button when status ∈ {pending, scheduled, confirmed} and `converted_job_id` is null
    - Show "View Job" link when `converted_job_id` is not null
    - Apply muted styling for cancelled/completed bookings
    - Cancel action: show confirmation dialog, call status update, refresh list
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.9_
  - [x] 7.2 Integrate BookingListPanel into `frontend/src/pages/bookings/BookingCalendarPage.tsx`
    - Render BookingListPanel below the BookingCalendar component
    - Pass current date range and view from calendar state
    - Wire up refresh callback
    - _Requirements: 1.1, 1.3_
  - [x] 7.3 Create `frontend/src/pages/bookings/JobCreationModal.tsx`
    - Accept `booking`, `isOpen`, `onClose`, `onSuccess` props
    - Pre-fill customer name, vehicle rego, service type, notes from booking
    - If user role is `org_admin`: show StaffPicker defaulting to current user
    - If user role is non-admin: show current user name as read-only assignee
    - Submit via `POST /api/v1/bookings/{booking.id}/convert?target=job_card` with `{ assigned_to }` body
    - On success: close modal, call `onSuccess` with job card ID
    - On failure: show error toast, keep modal open
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_
  - [x] 7.4 Write property tests for button visibility rules (frontend)
    - **Property 3: Cancel button visibility**
    - **Property 5: Create Job button visibility**
    - **Validates: Requirements 2.1, 2.5, 3.1, 3.9**
  - [x] 7.5 Write property test for booking-to-job data mapping (frontend)
    - **Property 6: Job creation pre-populates from booking**
    - **Validates: Requirements 3.2**

- [x] 8. Checkpoint — Booking panel and modal complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implement JobTimer component
  - [x] 9.1 Create `frontend/src/pages/jobs/JobTimer.tsx`
    - Accept `jobCardId`, `assignedTo`, `assignedToName`, `status`, `onStatusChange` props
    - Fetch `GET /api/v1/job-cards/{id}/timer` on mount to get entries and active state
    - If active timer: show live elapsed counter (1s interval from server `started_at`) + "Stop Timer" button
    - If no active timer and job is open/in_progress: show "Start Timer" button (subject to role checks)
    - Display total accumulated time across all completed entries
    - Role-based visibility: admin sees all controls; non-admin assigned sees controls; non-admin not assigned sees message + "Take Over Job"; unassigned shows "Assign to Me"
    - Re-fetch on `document.visibilitychange` to resync after tab sleep
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12_
  - [x] 9.2 Write property tests for timer display logic (frontend)
    - **Property 11: Elapsed time calculation**
    - **Property 12: Accumulated time is sum of durations**
    - **Validates: Requirements 4.7, 4.10, 4.11**

- [x] 10. Implement TakeOverDialog component
  - [x] 10.1 Create `frontend/src/pages/jobs/TakeOverDialog.tsx`
    - Modal with required textarea for takeover note
    - Submit calls `PUT /api/v1/job-cards/{id}/assign` with `{ new_assignee_id, takeover_note }`
    - On success: close dialog, trigger parent refresh
    - _Requirements: 8.7, 8.8_

- [x] 11. Implement JobsPage
  - [x] 11.1 Create/update `frontend/src/pages/jobs/JobsPage.tsx`
    - Fetch `GET /api/v1/job-cards?status=open,in_progress` for active jobs
    - Display job cards with: customer name, service description, vehicle rego, assigned staff name, status badge, JobTimer component
    - Sort: `in_progress` first, then `open`, each group by `created_at` descending
    - "Confirm Job Done" button visible when status is `in_progress`
    - Filter toggle: Active only / All jobs
    - "Confirm Job Done" flow: call `POST /api/v1/job-cards/{id}/complete`, on success navigate to `/invoices/{invoice_id}`
    - Handle partial failure: if invoice creation fails, show "Retry Invoice" button
    - Non-admin viewing job assigned to others: read-only mode with assignee message
    - Non-admin viewing unassigned job: show "Assign to Me" button
    - Non-admin viewing job assigned to someone else: show "Take Over Job" button opening TakeOverDialog
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 6.4, 6.5, 8.1, 8.4, 8.5, 8.6, 8.7_
  - [x] 11.2 Add `/jobs` route to the app router
    - Register JobsPage at `/jobs` in the frontend routing configuration
    - _Requirements: 5.1_
  - [x] 11.3 Write property tests for jobs page filtering and sorting (frontend)
    - **Property 16: Active jobs filtering**
    - **Property 17: Jobs page sort order**
    - **Validates: Requirements 5.1, 5.3, 5.4**

- [x] 12. Wire everything together and final integration
  - [x] 12.1 Add navigation link to Jobs page in the app sidebar/nav
    - Add "Jobs" entry to the main navigation menu
    - _Requirements: 5.1_
  - [x] 12.2 Verify end-to-end flow: booking list → create job → start timer → stop timer → confirm done → invoice
    - Ensure BookingListPanel refresh after job creation updates button states
    - Ensure JobsPage reflects new jobs immediately
    - Ensure navigation to invoice detail page works after completion
    - _Requirements: 3.7, 3.9, 6.4_
  - [x] 12.3 Write property tests for booking list filtering and sorting (frontend)
    - **Property 1: Booking date range filtering**
    - **Property 2: Booking list sort order**
    - **Validates: Requirements 1.3, 1.4**
  - [x] 12.4 Write property test for cancellation status transition (backend)
    - **Property 4: Cancellation status transition**
    - **Validates: Requirements 2.3**
  - [x] 12.5 Write property test for invoice content (backend)
    - **Property 19: Invoice includes job items and labour time**
    - **Validates: Requirements 6.6**

- [x] 13. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Backend tests use Hypothesis with `max_examples=5`; frontend tests use fast-check with `numRuns: 5`
- Backend tests run via: `docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec app pytest ...`
- Frontend tests run via: `docker-compose ... exec frontend npx vitest run ...`
- No new database tables or migrations are needed — existing `job_cards`, `time_entries` tables have all required columns
- Property tests validate universal correctness properties; unit tests validate specific examples and edge cases
- Checkpoints at tasks 5, 8, and 13 ensure incremental validation
