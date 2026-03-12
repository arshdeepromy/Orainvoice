# Requirements Document

## Introduction

This feature implements the end-to-end workflow from booking to job to invoice. Users see a list of bookings below the calendar with actions to cancel or create a job. Job creation pre-fills the logged-in user as the assignee and allows selecting another staff member. Active jobs display on a dedicated Jobs page with a live timer, job details, and a "Confirm Job Done" button that automatically creates a draft invoice and hands off to the existing invoice flow.

## Glossary

- **Booking_List_Panel**: The UI panel rendered below the BookingCalendar component that displays bookings for the currently selected date range in a tabular/list format with action buttons.
- **Job_Creation_Modal**: A popup dialog triggered from the Booking_List_Panel that allows the user to create a job card from a booking, pre-filling the logged-in user as the assignee.
- **Job_Card**: An existing entity (`job_cards` table) representing a unit of work, with statuses: open, in_progress, completed, invoiced.
- **Time_Entry**: An existing entity (`time_entries` table) that tracks start/stop timestamps and duration for work performed on a Job_Card.
- **Jobs_Page**: A new frontend page that displays all active (open and in_progress) Job_Cards for the organisation with real-time details.
- **Job_Timer**: A frontend component that displays elapsed time for an active Time_Entry on a Job_Card, with start and stop controls.
- **Staff_Picker**: A dropdown/select component that lists active staff members from the staff module, used in the Job_Creation_Modal to assign work.
- **Auth_Context**: The existing React context that provides the current user's user_id, org_id, and role.
- **Invoice_Flow**: The existing invoice module workflow including draft creation, line item management, PDF generation, and sending.

## Requirements

### Requirement 1: Booking List Panel Below Calendar

**User Story:** As a user, I want to see a list of my bookings below the calendar, so that I can quickly review and act on upcoming appointments.

#### Acceptance Criteria

1. WHEN the BookingCalendar page loads, THE Booking_List_Panel SHALL render below the calendar displaying all bookings for the currently selected date range.
2. THE Booking_List_Panel SHALL display each booking's customer name, service type, scheduled date/time, status, and vehicle registration.
3. WHEN the user changes the calendar date range or view (day/week/month), THE Booking_List_Panel SHALL update to show bookings matching the new date range.
4. THE Booking_List_Panel SHALL sort bookings by start_time in ascending order.
5. WHILE a booking has status "cancelled" or "completed", THE Booking_List_Panel SHALL visually distinguish the booking from active bookings using muted styling.

### Requirement 2: Cancel Booking Action

**User Story:** As a user, I want to cancel a booking from the list, so that I can manage my schedule without navigating away from the calendar.

#### Acceptance Criteria

1. THE Booking_List_Panel SHALL display a "Cancel" button for each booking that has a status of "pending", "scheduled", or "confirmed".
2. WHEN the user clicks the "Cancel" button, THE Booking_List_Panel SHALL display a confirmation dialog asking the user to confirm the cancellation.
3. WHEN the user confirms the cancellation, THE Booking_List_Panel SHALL send a status update request setting the booking status to "cancelled" and refresh the booking list.
4. IF the cancellation request fails, THEN THE Booking_List_Panel SHALL display an error message describing the failure reason.
5. WHILE a booking has status "cancelled", "completed", or has a non-null converted_job_id, THE Booking_List_Panel SHALL hide the "Cancel" button for that booking.

### Requirement 3: Create Job from Booking

**User Story:** As a user, I want to create a job directly from a booking, so that I can start working on the appointment without re-entering details.

#### Acceptance Criteria

1. THE Booking_List_Panel SHALL display a "Create Job" button for each booking that has a status of "pending", "scheduled", or "confirmed" and has a null converted_job_id.
2. WHEN the user clicks the "Create Job" button, THE Job_Creation_Modal SHALL open and pre-populate the booking's customer name, vehicle registration, service type, and notes.
3. THE Job_Creation_Modal SHALL automatically set the logged-in user (from Auth_Context) as the default job assignee and display the user's name in the assigned-to field.
4. WHEN the logged-in user has role "org_admin", THE Job_Creation_Modal SHALL include a Staff_Picker that lists all active staff members, allowing the admin to assign the job to any staff member.
5. WHEN the logged-in user has a non-admin role (e.g. "salesperson"), THE Job_Creation_Modal SHALL only allow the user to assign the job to themselves (the Staff_Picker SHALL be hidden or disabled, showing only the current user's name).
6. WHEN the user submits the Job_Creation_Modal, THE Job_Creation_Modal SHALL call the existing booking conversion endpoint (POST /bookings/{id}/convert?target=job_card) with the selected assignee, creating a Job_Card with status "open".
7. WHEN the job creation succeeds, THE Job_Creation_Modal SHALL close, update the booking's converted_job_id, and refresh the Booking_List_Panel.
8. IF the job creation request fails, THEN THE Job_Creation_Modal SHALL display an error message and remain open so the user can retry.
9. WHILE a booking already has a non-null converted_job_id, THE Booking_List_Panel SHALL hide the "Create Job" button and display a link to the existing Job_Card.

### Requirement 4: Job Timer Functionality

**User Story:** As a user, I want to start and stop a timer on a job, so that I can accurately track how long the work takes.

#### Acceptance Criteria

1. WHEN a Job_Card has status "open" or "in_progress", THE Job_Timer SHALL display a "Start Timer" button.
2. WHEN the logged-in user has role "org_admin", THE Job_Timer SHALL allow starting the timer on any Job_Card regardless of who it is assigned to (the admin can start jobs on behalf of any staff member).
3. WHEN the logged-in user has a non-admin role, THE Job_Timer SHALL only allow starting the timer if the Job_Card is assigned to the logged-in user.
4. WHEN a non-admin user views a Job_Card that is not assigned to them, THE Job_Timer SHALL hide the "Start Timer" button and display a message: "This job is assigned to [assignee name]. Assign it to yourself to start working."
5. WHEN a non-admin user views a Job_Card that has no assignee (assigned_to is null), THE Job_Timer SHALL hide the "Start Timer" button and display a message: "This job is not assigned. Assign it to yourself to start working." with an "Assign to Me" button.
6. WHEN the user clicks "Start Timer", THE Job_Timer SHALL create a new Time_Entry with started_at set to the current timestamp and update the Job_Card status to "in_progress".
7. WHILE a Time_Entry is active (stopped_at is null), THE Job_Timer SHALL display a live elapsed-time counter updating every second showing hours, minutes, and seconds.
8. WHILE a Time_Entry is active, THE Job_Timer SHALL display a "Stop Timer" button instead of "Start Timer".
9. WHEN the user clicks "Stop Timer", THE Job_Timer SHALL set stopped_at on the active Time_Entry to the current timestamp and calculate duration_minutes as the difference between stopped_at and started_at.
10. THE Job_Timer SHALL allow multiple Time_Entry records per Job_Card, enabling the user to start and stop the timer multiple times.
11. THE Job_Timer SHALL display the total accumulated time across all Time_Entry records for the Job_Card.
12. IF the user navigates away from the Jobs_Page while a timer is running, THEN THE Job_Timer SHALL continue tracking time server-side and restore the correct elapsed time when the user returns.

### Requirement 5: Jobs Page with Active Jobs

**User Story:** As a user, I want a dedicated Jobs page showing all active jobs, so that I can monitor ongoing work and manage my workload.

#### Acceptance Criteria

1. THE Jobs_Page SHALL display all Job_Cards with status "open" or "in_progress" for the current organisation.
2. THE Jobs_Page SHALL display each Job_Card's customer name, service type/description, vehicle registration, assigned staff member name, status, created_at timestamp, and the Job_Timer component.
3. THE Jobs_Page SHALL sort Job_Cards with "in_progress" jobs first, then "open" jobs, each group sorted by created_at descending.
4. WHEN a Job_Card's status changes to "completed" or "invoiced", THE Jobs_Page SHALL remove the Job_Card from the active jobs list.
5. THE Jobs_Page SHALL provide a filter to show all jobs (including completed and invoiced) or only active jobs.
6. WHEN the user clicks on a Job_Card row, THE Jobs_Page SHALL navigate to or expand a detail view showing the full job information including all Time_Entry records and line items.

### Requirement 6: Confirm Job Done and Auto-Create Invoice

**User Story:** As a user, I want to confirm a job is done and have an invoice automatically created, so that I can move seamlessly from completing work to billing the customer.

#### Acceptance Criteria

1. WHEN a Job_Card has status "in_progress", THE Jobs_Page SHALL display a "Confirm Job Done" button for that Job_Card.
2. WHEN the user clicks "Confirm Job Done" and a Time_Entry is still active (stopped_at is null), THE Jobs_Page SHALL automatically stop the active timer before proceeding.
3. WHEN the user clicks "Confirm Job Done", THE Jobs_Page SHALL update the Job_Card status to "completed" and invoke the existing job-card-to-invoice conversion endpoint to create a draft invoice.
4. WHEN the invoice creation succeeds, THE Jobs_Page SHALL update the Job_Card status to "invoiced" and navigate the user to the invoice detail page to continue the existing Invoice_Flow.
5. IF the invoice creation fails, THEN THE Jobs_Page SHALL display an error message, keep the Job_Card status as "completed", and provide a "Retry Invoice" button.
6. THE Jobs_Page SHALL include the Job_Card's line items and accumulated labour time (from Time_Entry records) as line items on the generated invoice.

### Requirement 7: Backend Timer Endpoints

**User Story:** As a developer, I want API endpoints for managing time entries, so that the frontend can start, stop, and query job timers.

#### Acceptance Criteria

1. WHEN a POST request is made to /api/v1/job-cards/{id}/timer/start, THE Job_Card_API SHALL create a new Time_Entry with started_at set to the server's current timestamp and return the Time_Entry details.
2. WHEN a POST request is made to /api/v1/job-cards/{id}/timer/stop, THE Job_Card_API SHALL set stopped_at on the active Time_Entry, calculate duration_minutes, and return the updated Time_Entry details.
3. IF a start-timer request is made while a Time_Entry is already active for the Job_Card, THEN THE Job_Card_API SHALL return a 409 Conflict error indicating a timer is already running.
4. IF a stop-timer request is made when no Time_Entry is active for the Job_Card, THEN THE Job_Card_API SHALL return a 404 Not Found error indicating no active timer exists.
5. WHEN a GET request is made to /api/v1/job-cards/{id}/timer, THE Job_Card_API SHALL return all Time_Entry records for the Job_Card and indicate whether a timer is currently active.
6. THE Job_Card_API SHALL enforce organisation-scoped access (RLS) on all timer endpoints, ensuring users can only access Time_Entry records belonging to their organisation.

### Requirement 8: Role-Based Job Assignment and Access Control

**User Story:** As an org admin, I want to assign and start jobs on any staff member's behalf, while non-admin staff can only work on jobs assigned to them, so that there is clear ownership and accountability for each job.

#### Acceptance Criteria

1. WHEN the logged-in user has role "org_admin", THE Job_Creation_Modal and Jobs_Page SHALL allow the admin to assign a job to any active staff member and start/stop the timer on any Job_Card.
2. WHEN the logged-in user has a non-admin role, THE Job_Creation_Modal SHALL only allow the user to assign the job to themselves.
3. WHEN a non-admin user attempts to start a timer on a Job_Card that is assigned to a different user, THE backend SHALL return a 403 Forbidden error with the message "You can only start jobs assigned to you."
4. WHEN a non-admin user views a Job_Card assigned to someone else on the Jobs_Page, THE Jobs_Page SHALL show the job details in read-only mode with a clear message indicating who the job is assigned to.
5. WHEN a non-admin user views a Job_Card with no assignee, THE Jobs_Page SHALL display an "Assign to Me" button that sets the Job_Card's assigned_to to the current user's staff_id.
6. WHEN a non-admin user clicks "Assign to Me", THE Jobs_Page SHALL update the Job_Card's assigned_to field and then enable the "Start Timer" button for that job.
7. WHEN a non-admin user wants to pick up a Job_Card that is currently assigned to someone else, THE Jobs_Page SHALL display a "Take Over Job" button that opens a note dialog requiring the user to enter a reason/note before reassigning the job to themselves.
8. WHEN the user submits the "Take Over Job" note dialog, THE Jobs_Page SHALL update the Job_Card's assigned_to to the current user's staff_id and append the takeover note (including the previous assignee's name and timestamp) to the Job_Card's notes field.
9. THE backend SHALL validate on all timer start/stop and job update endpoints that non-admin users can only modify Job_Cards assigned to them, returning 403 Forbidden otherwise. The reassign-to-self endpoint SHALL be exempt from this check since it is the mechanism for taking ownership.
