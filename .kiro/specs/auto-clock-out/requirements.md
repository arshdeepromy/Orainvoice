# Requirements Document

## Introduction

This feature closes the gap around **open (un-clocked-out) time clock entries**.
Staff sometimes forget to clock out, and casual / on-call / emergency-cover
staff work without a roster. Today an open entry blocks the staff from clocking
in again (the kiosk returns a `409 already_clocked_in` and dead-ends them at
"see your manager"), and the only remedy is a manager admin clock-out. There is
an hourly alert for entries open more than 12 hours, but nothing closes them
automatically.

This feature adds an **opt-in automatic clock-out** (closes stale open entries
at a sensible end time, flags them for review, and notifies the staff member and
their manager), makes the **kiosk recover gracefully** from the
`already_clocked_in` conflict, and surfaces the **existing manager admin
clock-out** so a forgotten clock-out can be fixed on the spot. It must preserve
the current ability for staff to clock in **without a schedule**.

It builds on existing pieces and adds no new tables: the org
`clock_in_policy` JSONB already holds clock settings, the
`check_missed_clock_outs_task` already alerts on long-open entries, the
`time_clock_entries.flags` JSONB already carries soft review markers, and
`POST /api/v2/time-clock/admin-clock-out/{entry_id}` already performs a
manager-forced clock-out.

## Glossary

- **Time_Clock_Entry**: A row in `time_clock_entries` representing one shift's
  attendance. **Open** when `clock_out_at IS NULL`.
- **Open_Entry**: The single open Time_Clock_Entry for a staff member (found via
  `_find_open_entry`, ordered by `clock_in_at` desc).
- **Clock_In_Policy**: The org-level JSONB settings blob on `organisations`
  (read via `_load_clock_in_policy` / the org-settings endpoint).
- **Auto_Clock_Out**: A system-initiated clock-out that closes a stale Open_Entry.
- **Auto_Clock_Out_Threshold**: The maximum hours an entry may remain open before
  Auto_Clock_Out closes it (the safety-net cap for staff with no schedule).
- **Rostered_End**: The end time of the `schedule_entries` shift linked to the
  Open_Entry (`scheduled_entry_id`), or the fixed-arrangement staff member's
  configured end time for that day.
- **Scheduled_Task**: The recurring background task that scans for stale
  Open_Entry rows (today `check_missed_clock_outs_task`).
- **Org_User**: An authenticated organisation user (manager/admin) with the
  timesheet/clock permissions.
- **Kiosk**: The shared tablet clock-in/out surface
  (`POST /api/v1/kiosk/clock/action`).

## Requirements

### Requirement 1: Opt-in automatic clock-out configuration

**User Story:** As an Org_User, I want to enable and tune automatic clock-out for
my organisation, so that forgotten clock-outs are closed without manual cleanup.

#### Acceptance Criteria

1. THE Clock_In_Policy SHALL expose an `auto_clock_out_enabled` boolean that
   defaults to `false` when absent.
2. THE Clock_In_Policy SHALL expose an `auto_clock_out_after_hours` integer
   (the Auto_Clock_Out_Threshold) with a documented default WHEN absent.
3. THE Clock_In_Policy SHALL expose an `auto_clock_out_grace_minutes` integer
   applied after a Rostered_End, with a documented default WHEN absent.
4. WHERE `auto_clock_out_enabled` is `false`, THE Scheduled_Task SHALL NOT close
   any Open_Entry (alerting behaviour is unchanged).
5. WHEN an Org_User updates the auto clock-out settings, THE system SHALL persist
   them in the Clock_In_Policy without requiring a database migration.

### Requirement 2: Automatic clock-out of stale open entries

**User Story:** As an Org_User, I want stale open clock entries closed
automatically at a sensible time, so that timesheets and pay are not skewed by a
shift left open for days.

#### Acceptance Criteria

1. WHILE `auto_clock_out_enabled` is `true`, WHEN the Scheduled_Task runs and an
   Open_Entry has been open longer than the Auto_Clock_Out_Threshold, THE system
   SHALL close that Open_Entry by setting `clock_out_at` and computing
   `worked_minutes`.
2. WHEN the system closes an Open_Entry that is linked to a scheduled shift
   (`scheduled_entry_id` is set), THE system SHALL set `clock_out_at` to the
   Rostered_End plus `auto_clock_out_grace_minutes`.
3. WHERE the Open_Entry is not linked to a scheduled shift but the staff member's
   working_arrangement is fixed, THE system SHALL set `clock_out_at` to that
   day's configured fixed end time plus `auto_clock_out_grace_minutes`.
4. WHERE neither a scheduled shift nor a fixed end time is available
   (casual / on-call / no schedule), THE system SHALL set `clock_out_at` to
   `clock_in_at` plus the Auto_Clock_Out_Threshold.
5. THE system SHALL never set `clock_out_at` earlier than `clock_in_at`.
6. THE Auto_Clock_Out SHALL be idempotent: an entry already closed SHALL NOT be
   re-closed or altered by a subsequent Scheduled_Task run.
7. WHEN the Scheduled_Task processes multiple organisations, a failure for one
   organisation SHALL NOT prevent processing of the others.

### Requirement 3: Auto-closed entries are flagged for review

**User Story:** As an Org_User running payroll, I want auto-closed entries clearly
marked, so that I can review them before they flow into pay.

#### Acceptance Criteria

1. WHEN the system performs an Auto_Clock_Out, THE system SHALL record a marker
   in the entry's `flags` JSONB indicating it was auto-closed and the basis used
   (rostered_end | fixed_end | elapsed_cap).
2. WHEN the system performs an Auto_Clock_Out, THE system SHALL write an audit log
   entry attributable to the system (no user id) recording the entry id and the
   chosen clock-out time.
3. THE Auto_Clock_Out marker SHALL be readable so a later manager correction via
   admin clock-out can distinguish an auto-closed entry from a real punch.
4. IF recording the review marker in the entry's `flags` JSONB fails, THEN THE
   system SHALL still complete the Auto_Clock_Out (set `clock_out_at` and
   `worked_minutes`) and SHALL log the marker failure for follow-up, so a marker
   write failure never leaves a stale entry open.

### Requirement 4: Notify staff and manager on auto clock-out

**User Story:** As a staff member and as their manager, I want to be told when a
shift was auto-closed, so that we can correct the hours if they are wrong.

#### Acceptance Criteria

1. WHEN the system performs an Auto_Clock_Out, THE system SHALL notify the staff
   member using the organisation's configured clock alert channels, and SHALL NOT
   finalise the closure until the staff notification has been dispatched
   successfully.
2. IF the staff notification cannot be dispatched (send failure, or the staff
   member has no contactable channel), THEN THE system SHALL defer the
   Auto_Clock_Out for that entry and retry it on a subsequent Scheduled_Task run
   rather than closing it un-notified.
3. WHEN the system performs an Auto_Clock_Out, THE system SHALL also notify the
   staff member's manager when a manager is resolvable.
4. THE notification SHALL state the shift's clock-in time and the auto clock-out
   time, and direct the recipient to correct it if wrong.
5. IF the manager notification fails, THEN THE failure SHALL NOT prevent the
   Open_Entry from being closed (the staff notification having already succeeded)
   nor poison the rest of the batch.
6. THE system SHALL NOT notify more than once for the same auto-closed entry.

### Requirement 5: Clock-in without a schedule (casual / on-call)

**User Story:** As a casual, on-call, or emergency-cover staff member, I want to
clock in even though I have no roster, so that my worked time is captured.

#### Acceptance Criteria

1. WHEN a staff member with no matching scheduled shift clocks in, THE system
   SHALL create the Time_Clock_Entry successfully (no schedule is required).
2. WHERE a staff member has no schedule, THE Auto_Clock_Out SHALL use the
   Auto_Clock_Out_Threshold cap (Requirement 2.4) rather than a Rostered_End.

### Requirement 6: Manager-forced clock-out is reachable

**User Story:** As an Org_User, I want to clock a staff member out when they
forgot, so that they can clock in again and the record is corrected.

#### Acceptance Criteria

1. THE system SHALL allow an authorised Org_User to close a staff member's
   Open_Entry with a corrected clock-out time and a required reason.
2. WHEN an Org_User force-closes an Open_Entry, THE system SHALL record the reason
   and write an audit log entry.
3. THE manager-forced clock-out SHALL be reachable from a staff-facing operational
   view (the Clocked-in / Hours surface) without navigating to a separate tool.
4. THE system SHALL restrict which Open_Entry rows an Org_User may force-close to
   staff within that user's authorisation scope: an org-level admin MAY force-close
   any Open_Entry in the organisation, WHILE a branch-scoped user (e.g.
   branch_admin / location_manager) MAY force-close only Open_Entry rows for staff
   in their assigned branches.
5. IF an Org_User attempts to force-close an Open_Entry outside their authorisation
   scope, THEN THE system SHALL reject the request and SHALL NOT modify the entry.

### Requirement 7: Kiosk recovers gracefully from an open-entry conflict

**User Story:** As a staff member at the kiosk, I want a clear, recoverable
result when the system says I'm already clocked in, so that I'm not stuck.

#### Acceptance Criteria

1. WHEN a kiosk clock-in returns `already_clocked_in`, THE Kiosk SHALL present a
   recoverable message rather than a generic dead-end error.
2. IF a kiosk clock-in returns `already_clocked_in` immediately after this session
   attempted a clock-in (a double-submit / retry), THEN THE Kiosk SHALL treat the
   staff member as successfully clocked in (idempotent success).
3. WHERE the staff member is genuinely still clocked in from earlier, THE Kiosk
   SHALL direct them to a manager to correct it (consistent with Requirement 6),
   and SHALL NOT silently clock them out.
4. WHEN a kiosk clock-out returns `not_clocked_in`, THE Kiosk SHALL present an
   equivalent recoverable message.

### Requirement 8: Configuration UI

**User Story:** As an Org_User, I want a settings screen to control auto
clock-out, so that I can adopt it without editing data directly.

#### Acceptance Criteria

1. THE settings UI SHALL let an Org_User toggle `auto_clock_out_enabled`.
2. THE settings UI SHALL let an Org_User set the Auto_Clock_Out_Threshold and the
   grace minutes, with validation for sane ranges.
3. WHERE auto clock-out is disabled, THE settings UI SHALL still allow the
   existing missed-clock-out alert toggles to be configured independently.

### Requirement 9: Correctness and testing

**User Story:** As a maintainer, I want the auto clock-out logic covered by tests,
so that pay-affecting automation is protected against regression.

#### Acceptance Criteria

1. THE test suite SHALL verify the end-time basis hierarchy (rostered shift end →
   fixed end → elapsed cap) for closing an Open_Entry.
2. THE test suite SHALL verify that auto clock-out does nothing when
   `auto_clock_out_enabled` is `false`.
3. THE test suite SHALL verify idempotency (a second run does not re-close or
   double-notify an already-closed entry).
4. THE test suite SHALL verify that a staff member with no schedule can clock in
   and is closed via the cap.
5. THE test suite SHALL verify the kiosk treats a double-submit `already_clocked_in`
   as success and surfaces a recoverable message otherwise.
6. THE test suite SHALL verify that when the staff notification cannot be
   dispatched, the entry is deferred (left open, not closed un-notified) and is
   closed on a later run once notification succeeds.
7. THE test suite SHALL verify that a force-close request for a staff member
   outside the requester's authorisation scope is rejected and leaves the entry
   unchanged.
