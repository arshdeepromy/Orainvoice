# Requirements Document

## Introduction

This feature lets an organisation user assign a specific pay cycle to each staff
member when adding or editing that staff member. Pay cycles (weekly, fortnightly,
monthly) are already configured under Timesheets → Settings. Different staff in
the same organisation can run on different cycles (for example, weekly for casual
staff and fortnightly for permanent staff).

Once a staff member is assigned a cycle, the timesheet and pay-run flow must
respect that assignment: each pay period belongs to exactly one cycle, and a
period must only ever materialise and pay the staff whose resolved cycle matches
that period's cycle. This produces correct, separated timesheets and pay runs for
organisations that run multiple cycles at once, while preserving existing
behaviour for organisations that run a single cycle.

The underlying data model (`pay_cycles`, `pay_cycle_assignments`,
`PayPeriod.pay_cycle_id`) and several services (`assign_pay_cycle`,
`resolve_pay_cycle_for_staff`, `auto_generate_pay_periods`) already exist. This
feature wires those pieces together, completes the unfinished resolution logic,
defines correct replace semantics for staff-level assignments, and exposes
selection in the staff Add/Edit UI. It reuses the existing tables, models, and
endpoints rather than rebuilding them.

## Glossary

- **Pay_Cycle**: An org-level definition of pay frequency and timing, stored in
  the `pay_cycles` table. Has fields name, frequency (weekly/fortnightly/monthly),
  anchor_date, pay_date_offset_days, is_default, and active.
- **Default_Cycle**: The single Pay_Cycle for an organisation whose `is_default`
  field is true.
- **Pay_Cycle_Assignment**: A row in the `pay_cycle_assignments` table mapping a
  Pay_Cycle to a target scope. Has target_type in (`all`, `branch`,
  `employment_type`, `staff`) and an optional target_id. Constrained by
  UNIQUE(pay_cycle_id, target_type, target_id).
- **Staff_Assignment**: A Pay_Cycle_Assignment whose target_type is `staff` and
  whose target_id is a staff member identifier.
- **Resolved_Cycle**: The Pay_Cycle that applies to a given staff member after
  applying the resolution priority order.
- **Resolution_Service**: The `resolve_pay_cycle_for_staff` service that returns a
  staff member's Resolved_Cycle.
- **Staff_Service**: The backend staff module that handles `POST /api/v2/staff`
  and `PUT /api/v2/staff/{id}`.
- **Staff_Form**: The frontend Add staff modal (`StaffList.tsx`) and Edit staff
  page (`OverviewTab.tsx`).
- **Pay_Period**: A dated window for a single Pay_Cycle, stored in `pay_periods`
  with a `pay_cycle_id` column.
- **Materialisation_Service**: The `materialise_missing_timesheets` service that
  creates timesheet rows for a Pay_Period before a pay run.
- **Pay_Run_Service**: The `run_pay_period` service in `payrun.py` that executes a
  pay run for a Pay_Period.
- **Org_User**: An authenticated organisation user with permission to manage staff
  and run payroll.
- **Active_Cycle**: A Pay_Cycle whose `active` field is true.

## Requirements

### Requirement 1: Select a pay cycle on the staff form

**User Story:** As an Org_User, I want to choose a pay cycle when adding or editing
a staff member, so that each staff member is paid on the correct schedule.

#### Acceptance Criteria

1. WHERE an organisation has at least one Active_Cycle, WHEN the Staff_Form is opened to add or edit a staff member, THE Staff_Form SHALL display a pay cycle selector populated with the organisation's Active_Cycle records retrieved from `GET /api/v2/pay-cycles/`.
2. WHERE an organisation has at least one Active_Cycle, THE Staff_Form SHALL allow the Org_User to select exactly one Pay_Cycle for the staff member.
3. WHERE an organisation has at least one Active_Cycle, WHEN the Staff_Form is opened to edit a staff member who has a Resolved_Cycle, THE Staff_Form SHALL preselect that staff member's Resolved_Cycle in the pay cycle selector.
4. WHERE the Org_User does not select a Pay_Cycle on the Staff_Form, THE Staff_Form SHALL indicate that the organisation's Default_Cycle will apply.
5. IF an organisation has no Active_Cycle configured, THEN THE Staff_Form SHALL display a message directing the Org_User to configure a pay cycle under Timesheets → Settings.
6. IF an organisation has no Active_Cycle configured, THEN THE Staff_Form SHALL hide the pay cycle selector.

### Requirement 2: Persist the selected pay cycle as a staff-level assignment

**User Story:** As an Org_User, I want the pay cycle I choose to be saved against
the staff member, so that the choice persists and drives later pay runs.

#### Acceptance Criteria

1. WHEN the Staff_Service creates a staff member with a selected Pay_Cycle, THE Staff_Service SHALL persist a Staff_Assignment linking the selected Pay_Cycle to the new staff member.
2. WHEN the Staff_Service updates a staff member with a selected Pay_Cycle, THE Staff_Service SHALL persist a Staff_Assignment linking the selected Pay_Cycle to that staff member.
3. WHERE the Org_User submits the Staff_Form without selecting a Pay_Cycle, THE Staff_Service SHALL NOT create a Staff_Assignment, so that the staff member resolves to the organisation's Default_Cycle.
4. IF the selected Pay_Cycle identifier does not belong to the Org_User's organisation, THEN THE Staff_Service SHALL reject the entire operation with a validation error, SHALL NOT create or modify the staff member, and SHALL NOT create a Staff_Assignment.
5. IF the selected Pay_Cycle identifier refers to an inactive Pay_Cycle, THEN THE Staff_Service SHALL reject the entire operation with a validation error, SHALL NOT create or modify the staff member, and SHALL NOT create a Staff_Assignment.

### Requirement 3: Replace semantics when changing a staff member's pay cycle

**User Story:** As an Org_User, I want changing a staff member's pay cycle to
replace the previous choice cleanly, so that switching cycles never causes a
duplicate-assignment error.

#### Acceptance Criteria

1. WHEN the Staff_Service persists a Staff_Assignment for a staff member who already has a Staff_Assignment, THE Staff_Service SHALL replace the existing Staff_Assignment so that exactly one Staff_Assignment exists for that staff member.
2. WHEN the Staff_Service replaces a Staff_Assignment with one referencing the same Pay_Cycle already assigned, THE Staff_Service SHALL leave a single Staff_Assignment for that staff member and SHALL report success.
3. IF the Org_User edits a staff member and clears the previously selected Pay_Cycle, THEN THE Staff_Service SHALL remove the staff member's existing Staff_Assignment so that the staff member resolves to the organisation's Default_Cycle.
4. THE Staff_Service SHALL guarantee that, after any create or update, at most one Staff_Assignment exists for a given staff member, consistent with the UNIQUE(pay_cycle_id, target_type, target_id) constraint.

### Requirement 4: Resolve the pay cycle that applies to a staff member

**User Story:** As an Org_User, I want the system to determine each staff member's
effective pay cycle by a clear priority order, so that assignments at different
levels combine predictably.

#### Acceptance Criteria

1. WHEN the Resolution_Service is asked for a staff member's Resolved_Cycle, THE Resolution_Service SHALL apply the priority order staff, then employment_type, then branch, then all, then Default_Cycle, and SHALL return the first matching Active_Cycle.
2. WHERE a staff member has a Staff_Assignment to an Active_Cycle, THE Resolution_Service SHALL return that Active_Cycle as the Resolved_Cycle.
3. WHERE a staff member has no matching assignment at the staff, employment_type, branch, or all levels, THE Resolution_Service SHALL return the organisation's Default_Cycle as the Resolved_Cycle.
4. WHERE a staff member has no Staff_Assignment to an Active_Cycle, WHEN the Resolution_Service evaluates the employment_type level and the staff member's employment_type matches an employment_type assignment to an Active_Cycle, THE Resolution_Service SHALL return that Active_Cycle.
5. WHILE the Resolution_Service performs resolution, THE Resolution_Service SHALL exclude inactive Pay_Cycle records from every level of resolution.
6. IF no assignment matches at any level and the organisation has no Default_Cycle, THEN THE Resolution_Service SHALL return no Resolved_Cycle.

### Requirement 5: Read a staff member's resolved pay cycle

**User Story:** As an Org_User, I want to see which pay cycle a staff member is on,
so that I can confirm assignments and prefill the edit form.

#### Acceptance Criteria

1. WHEN the Staff_Service returns a staff member record, THE Staff_Service SHALL include the staff member's Resolved_Cycle identifier and name.
2. WHERE a staff member resolves to the organisation's Default_Cycle through the absence of a more specific assignment, THE Staff_Service SHALL indicate that the Resolved_Cycle is the Default_Cycle.
3. WHERE a staff member has no Resolved_Cycle because no assignment matches and no Default_Cycle exists, THE Staff_Service SHALL return an empty Resolved_Cycle value for that staff member.

### Requirement 6: Materialise timesheets only for staff matching the period's cycle

**User Story:** As an Org_User running payroll, I want a pay period to create
timesheets only for staff on that period's cycle, so that mixed-cycle
organisations produce correctly separated timesheets.

#### Acceptance Criteria

1. WHEN the Materialisation_Service runs for a Pay_Period, THE Materialisation_Service SHALL create timesheet rows only for staff members whose Resolved_Cycle matches the Pay_Period's pay_cycle_id.
2. IF an active staff member's Resolved_Cycle differs from the Pay_Period's pay_cycle_id, THEN THE Materialisation_Service SHALL prevent the creation of any timesheet row for that staff member in that Pay_Period.
3. WHERE a staff member has no Resolved_Cycle, THE Materialisation_Service SHALL exclude that staff member from every Pay_Period.
4. WHEN the Materialisation_Service runs with include_all_active enabled for a Pay_Period, THE Materialisation_Service SHALL create timesheet rows for every active staff member whose Resolved_Cycle matches the Pay_Period's pay_cycle_id and SHALL exclude all other staff members.

### Requirement 7: Run pay runs scoped to the period's cycle

**User Story:** As an Org_User running payroll, I want a pay run to process only
the staff on the period's cycle, so that pay runs for different cycles stay
separate.

#### Acceptance Criteria

1. WHEN the Pay_Run_Service runs a Pay_Period, THE Pay_Run_Service SHALL process only timesheets belonging to staff members whose Resolved_Cycle matches the Pay_Period's pay_cycle_id.
2. WHILE the Pay_Run_Service processes a Pay_Period, THE Pay_Run_Service SHALL exclude staff members whose Resolved_Cycle differs from the Pay_Period's pay_cycle_id.
3. WHERE an organisation runs multiple Active_Cycle records simultaneously, THE Pay_Run_Service SHALL produce one independent pay-run result per Pay_Period without combining staff across cycles.

### Requirement 8: Generate and select pay periods across multiple cycles

**User Story:** As an Org_User, I want pay periods generated for each active cycle
and clearly labelled by cycle, so that I can pick the correct period when an
organisation runs several cycles.

#### Acceptance Criteria

1. WHEN pay-period generation runs for an organisation, THE system SHALL generate Pay_Period records for each Active_Cycle of that organisation.
2. WHEN the period selector lists Pay_Period records for an organisation with more than one Active_Cycle, THE period selector SHALL display each Pay_Period with its associated Pay_Cycle name so that periods are disambiguated by cycle.
3. WHERE two Pay_Period records from different Active_Cycle records share the same date range, THE period selector SHALL distinguish the two records by their Pay_Cycle name.
4. WHEN the Org_User selects a Pay_Period for materialisation or a pay run, THE system SHALL use that Pay_Period's pay_cycle_id to scope the staff included.
5. IF the selected Pay_Period has no pay_cycle_id so that cycle-based scoping cannot be determined, THEN THE Pay_Run_Service SHALL NOT proceed with the pay run.

### Requirement 9: Backward compatibility for single-cycle organisations

**User Story:** As an Org_User in an organisation that runs a single pay cycle, I
want existing payroll behaviour to be unchanged, so that this feature introduces
no regression.

#### Acceptance Criteria

1. WHERE an organisation has exactly one Active_Cycle and that cycle is the Default_Cycle, THE Resolution_Service SHALL resolve every active staff member to that single Active_Cycle.
2. WHEN the Materialisation_Service runs for the sole Pay_Period of a single-cycle organisation, THE Materialisation_Service SHALL include the same active staff members it included before this feature, scoped to that cycle.
3. WHERE a staff member in a single-cycle organisation has no Staff_Assignment, THE system SHALL pay that staff member on the Default_Cycle without requiring any change to the staff record.

### Requirement 10: Correctness verification and testing

**User Story:** As a maintainer, I want the resolution and cycle-scoped
materialisation logic covered by automated tests, so that mixed-cycle correctness
is guaranteed and protected against regression.

#### Acceptance Criteria

1. THE test suite SHALL verify that the Resolution_Service returns the correct Resolved_Cycle for each priority level (staff, employment_type, branch, all, Default_Cycle).
2. THE test suite SHALL verify that a staff member with no assignment resolves to the Default_Cycle, and SHALL make no assertion about the Resolved_Cycle of a staff member that has an assignment.
3. THE test suite SHALL verify that the Resolution_Service excludes inactive Pay_Cycle records at every level.
4. THE test suite SHALL verify that the Materialisation_Service includes only staff whose Resolved_Cycle matches the Pay_Period's pay_cycle_id for organisations running a single Active_Cycle and for organisations running multiple Active_Cycle records.
5. THE test suite SHALL fail when switching a staff member's Pay_Cycle does not result in exactly one Staff_Assignment for that staff member.
6. THE test suite SHALL fail when a single-cycle organisation's materialised staff set differs from the materialised staff set produced before this feature.
