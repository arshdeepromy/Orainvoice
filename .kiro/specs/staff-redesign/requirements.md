# Requirements Document

## Introduction

The Staff Redesign feature brings the existing OraInvoice staff pages (in the active `frontend-v2/` web app) into line with two approved redesign mockups (`Staff.html`, `StaffDetail.html`) and fills the functional gaps identified in the approved gap analysis (`docs/STAFF_REDESIGN_GAP_ANALYSIS.md`). The work is predominantly frontend polish plus one new backend metrics aggregation endpoint. No new database tables or migrations are introduced.

This feature covers three surfaces:

1. **Staff list page** — adds a KPI strip, segmented filters, work-day "day pips", avatar initials with a role subline, and Leave/Export header actions, while preserving all existing list functionality.
2. **Staff detail Overview tab** — restyles the Overview tab to the mockup's hero header plus a right sidebar (This-month metrics, Account panel, Create-account prompt), kept inside the existing tabbed shell.
3. **Stats endpoint** — a new `GET /api/v2/staff/{id}/stats` endpoint computing four "this month" metrics plus last sign-in, with module gating, role-based access control, and explicit empty-data handling.

The existing tabbed detail shell (Overview / Roster / Payslips / Documents) is retained. Only the Overview tab is restyled. There is no routing change and no flattening to a single page.

## Glossary

- **Staff_List_Page**: The `frontend-v2` page that lists an organisation's staff members in a paginated table.
- **Staff_Detail_Page**: The `frontend-v2` page showing a single staff member inside a tabbed shell (Overview / Roster / Payslips / Documents).
- **Overview_Tab**: The first tab of the Staff_Detail_Page, the only tab restyled by this feature.
- **Stats_Endpoint**: The new backend endpoint `GET /api/v2/staff/{id}/stats` returning month metrics for a staff member.
- **Stats_Service**: The backend service function that computes the month metrics consumed by the Stats_Endpoint.
- **KPI_Strip**: The row of four summary cards at the top of the Staff_List_Page (Total staff, Employees, With login access, Avg hourly rate).
- **Day_Pips**: A compact set of seven labelled squares (Mon–Sun) indicating which work days a staff member has a scheduled shift, rendered in the Work days table cell.
- **Segmented_Filter**: A pill-style control group (`.seg`) replacing the existing `<select>` role and status filters.
- **This_Month**: The current calendar month evaluated in the organisation timezone.
- **Hours_Logged**: Total hours a staff member has clocked in This_Month.
- **Jobs_Completed**: Count of completed/invoiced job cards assigned to the staff member This_Month.
- **Billable_Ratio**: The proportion of a staff member's logged time This_Month that is billable, as a whole percentage.
- **On_Time_Rate**: The percentage of a staff member's scheduled clock-ins This_Month that occurred at or before the scheduled start plus a grace window.
- **Grace_Window**: A fixed 5-minute tolerance added to the scheduled start when evaluating On_Time_Rate.
- **Last_Sign_In**: The most recent login timestamp of the user account linked to the staff member, sourced from the linked `users` row via `staff.user_id`.
- **Has_Data_Flag**: A boolean returned alongside each metric indicating whether the metric was computed from real data, used to drive the "—" display.
- **List_KPI_Aggregates**: Backend-computed totals supporting the KPI_Strip (with-login count, average hourly rate).
- **Module_Gate**: The `staff_management` module gating that governs access to staff features.
- **Self_Scope**: The access rule allowing a `staff_member` to read only their own records/stats.

## Requirements

### Requirement 1: Staff list KPI strip

**User Story:** As an org administrator, I want summary KPI cards on the staff list, so that I can see headcount and account/pay metrics at a glance.

#### Acceptance Criteria

1. WHEN the Staff_List_Page loads, THE Staff_List_Page SHALL display a KPI_Strip containing four cards labelled "Total staff", "Employees", "With login access", and "Avg hourly rate".
2. THE Staff_List_Page SHALL display the total staff count in the "Total staff" card.
3. THE Staff_List_Page SHALL display the count of staff members with `role_type` of employee in the "Employees" card.
4. THE Staff_List_Page SHALL display the count of staff members who have a linked user account in the "With login access" card.
5. THE Staff_List_Page SHALL display the average hourly rate across staff members in the "Avg hourly rate" card formatted as a currency value.
6. WHERE List_KPI_Aggregates are required to populate the "With login access" and "Avg hourly rate" cards, THE Stats_Service SHALL provide those aggregates through the backend list response.
7. IF a KPI value is unavailable in the API response, THEN THE Staff_List_Page SHALL render "—" in place of a misleading 0.

### Requirement 2: Staff list segmented filters

**User Story:** As an org administrator, I want pill-style role and status filters, so that filtering matches the redesign and is quicker to operate.

#### Acceptance Criteria

1. THE Staff_List_Page SHALL render the role filter as a Segmented_Filter with options "All roles", "Employees", and "Contractors".
2. THE Staff_List_Page SHALL render the status filter as a Segmented_Filter with options "All", "Active", and "Inactive".
3. WHEN a Segmented_Filter option is selected, THE Staff_List_Page SHALL mark that option as active and apply the corresponding filter to the staff table.
4. WHEN a role filter and a status filter are both active, THE Staff_List_Page SHALL apply both filters together to the staff table.
5. THE Staff_List_Page SHALL preserve the existing search-by-name/email/ID behaviour alongside the Segmented_Filter controls.

### Requirement 3: Staff list work-day pips

**User Story:** As an org administrator, I want a compact visual of each staff member's work days, so that I can scan schedules without reading text.

#### Acceptance Criteria

1. THE Staff_List_Page SHALL render the Work days cell as Day_Pips containing seven labelled squares ordered Monday through Sunday.
2. WHERE a staff member has a scheduled shift on a given day in the availability schedule, THE Staff_List_Page SHALL render that day's pip in the active style.
3. WHERE a staff member has no scheduled shift on a given day, THE Staff_List_Page SHALL render that day's pip in the inactive style.
4. IF a staff member has no availability schedule, THEN THE Staff_List_Page SHALL render all seven pips in the inactive style.

### Requirement 4: Staff list name cell with avatar and role subline

**User Story:** As an org administrator, I want avatars and a role subline in the name cell, so that staff are easier to identify at a glance.

#### Acceptance Criteria

1. THE Staff_List_Page SHALL render avatar initials derived from the staff member's first and last name in the Name cell.
2. THE Staff_List_Page SHALL render a subline beneath the name showing "Employee" for staff with `role_type` employee and "Contractor" for staff with `role_type` contractor.
3. WHEN the staff name is activated, THE Staff_List_Page SHALL navigate to that staff member's Staff_Detail_Page.

### Requirement 5: Staff list Leave and Export actions

**User Story:** As an org administrator, I want Leave and Export actions in the staff header, so that I can reach leave approvals and export the current list.

#### Acceptance Criteria

1. THE Staff_List_Page SHALL display a "Leave" header action that navigates to the existing Leave Approvals view.
2. WHERE there are pending leave requests, THE Staff_List_Page SHALL display the pending count as a badge on the Leave action.
3. WHEN the Export action is activated, THE Staff_List_Page SHALL produce a CSV export reflecting the currently applied filters and search.
4. THE Staff_List_Page SHALL retain the existing "Add staff" header action.

### Requirement 6: Preserve existing staff list functionality

**User Story:** As an org administrator, I want all current staff list capabilities to keep working, so that the redesign adds value without removing function.

#### Acceptance Criteria

1. THE Staff_List_Page SHALL retain the add/edit staff modal including the per-day WorkSchedule editor.
2. THE Staff_List_Page SHALL retain the "also create as user" invite option with user role and branch selection in the add flow.
3. THE Staff_List_Page SHALL retain the deactivate and activate actions for staff members.
4. THE Staff_List_Page SHALL retain the permanent-delete action including the "also delete user account" option.
5. THE Staff_List_Page SHALL retain inline duplicate detection in the add/edit modal.
6. THE Staff_List_Page SHALL retain pagination of the staff table.

### Requirement 7: Staff detail Overview hero

**User Story:** As an org administrator, I want the Overview tab to lead with a hero header, so that the staff member's identity and status are immediately clear.

#### Acceptance Criteria

1. THE Overview_Tab SHALL display a hero header containing a large avatar with the staff member's initials, the staff member's full name, and a status badge.
2. THE Overview_Tab SHALL display a hero subline in the format "position · employee ID · branch".
3. WHERE a hero subline component (position, employee ID, or branch) is absent, THE Overview_Tab SHALL render "—" for that component.
4. THE Overview_Tab SHALL remain inside the existing tabbed shell with the Overview / Roster / Payslips / Documents tabs unchanged.
5. THE Stats_Endpoint and Overview restyle SHALL NOT introduce any routing change to the Staff_Detail_Page.

### Requirement 8: Staff detail "This month" metrics panel

**User Story:** As an org administrator, I want a "This month" metrics panel in the Overview sidebar, so that I can review a staff member's recent activity.

#### Acceptance Criteria

1. THE Overview_Tab SHALL display a right-sidebar panel labelled "This month" containing Hours_Logged, Jobs_Completed, Billable_Ratio, and On_Time_Rate.
2. WHEN the Overview_Tab loads, THE Overview_Tab SHALL fetch the metrics from the Stats_Endpoint for the displayed staff member with `period=this_month`.
3. WHERE a metric's Has_Data_Flag is false, THE Overview_Tab SHALL render "—" for that metric instead of a numeric value.
4. THE Overview_Tab SHALL render Hours_Logged with one decimal place followed by "h".
5. THE Overview_Tab SHALL render Billable_Ratio and On_Time_Rate as whole percentages.
6. THE Overview_Tab SHALL consume the Stats_Endpoint response using safe access (`?.` and `?? '—'` / `?? 0`).
7. WHEN the Overview_Tab unmounts or the staff member changes before the stats fetch completes, THE Overview_Tab SHALL abort the in-flight stats request using an AbortController.

### Requirement 9: Staff detail Account panel and create-account prompt

**User Story:** As an org administrator, I want an Account panel showing login status, role, and last sign-in, so that I can understand and manage a staff member's access.

#### Acceptance Criteria

1. THE Overview_Tab SHALL display an Account panel showing "Login access", "User role", and "Last sign-in".
2. WHERE the staff member has a linked user account, THE Overview_Tab SHALL display the login access status and the user role.
3. THE Overview_Tab SHALL display Last_Sign_In sourced from the linked user account.
4. WHERE the staff member has no last sign-in timestamp, THE Overview_Tab SHALL render "—" for Last_Sign_In.
5. WHERE the staff member has no linked user account, THE Overview_Tab SHALL display a "No account?" prompt with a "Create user account" action.
6. WHEN the "Create user account" action is activated, THE Overview_Tab SHALL open the existing create-user-account modal.

### Requirement 10: Preserve existing Overview tab content

**User Story:** As an org administrator, I want all current Overview information to remain available, so that the restyle does not remove employment detail.

#### Acceptance Criteria

1. THE Overview_Tab SHALL retain the Personal, Employment, Tax & Pay, Schedule, Clock-in & roster, and Skills sections.
2. THE Overview_Tab SHALL retain inline compliance warnings.
3. THE Overview_Tab SHALL retain the PayRateHistoryPanel.
4. THE Overview_Tab SHALL retain the RecurringAllowancesPanel.

### Requirement 11: Stats endpoint contract and metric definitions

**User Story:** As a frontend developer, I want a stats endpoint with precise metric definitions, so that the Overview metrics are accurate and consistent with reporting.

#### Acceptance Criteria

1. THE Stats_Endpoint SHALL accept `GET /api/v2/staff/{id}/stats?period=this_month` and return Hours_Logged, Jobs_Completed, Billable_Ratio, On_Time_Rate, Last_Sign_In, and a Has_Data_Flag per metric.
2. THE Stats_Service SHALL compute Hours_Logged as `SUM(time_clock_entries.worked_minutes) / 60` for the staff member where `clock_in_at` is within This_Month and `clock_out_at` is not null.
3. THE Stats_Service SHALL compute Jobs_Completed as the count of `job_cards` where `assigned_to` equals the staff member's id, `status` is in (`completed`, `invoiced`), and `updated_at` is within This_Month.
4. THE Stats_Service SHALL compute Billable_Ratio from `time_tracking_v2.TimeEntry` for the staff member within This_Month as `SUM(duration_minutes WHERE is_billable) / SUM(duration_minutes) * 100`, rounded to a whole percent, consistent with the reports_v2 Staff Utilisation report.
5. THE Stats_Service SHALL compute On_Time_Rate as the percentage of `time_clock_entries` in This_Month with a non-null `scheduled_entry_id` whose `clock_in_at` is at or before the scheduled start plus the Grace_Window of 5 minutes.
6. THE Stats_Service SHALL exclude unscheduled clock-ins (those with a null `scheduled_entry_id`) from the On_Time_Rate denominator.
7. THE Stats_Service SHALL evaluate This_Month as the current calendar month in the organisation timezone.
8. THE Stats_Service SHALL return Last_Sign_In from the `users` row linked via `staff.user_id`.
9. THE Stats_Endpoint and Stats_Service SHALL NOT require any new database tables or migrations.

### Requirement 12: Stats endpoint empty-data handling

**User Story:** As an org administrator, I want metrics with no underlying data to show "—" rather than 0, so that I am not misled by a false zero.

#### Acceptance Criteria

1. THE Stats_Service SHALL return a Has_Data_Flag for each of Hours_Logged, Jobs_Completed, Billable_Ratio, and On_Time_Rate.
2. WHERE a staff member has no completed clock entries This_Month, THE Stats_Service SHALL set the Hours_Logged Has_Data_Flag to false.
3. WHERE a staff member has no logged time entries This_Month, THE Stats_Service SHALL set the Billable_Ratio Has_Data_Flag to false.
4. WHERE a staff member has no scheduled clock-ins This_Month, THE Stats_Service SHALL set the On_Time_Rate Has_Data_Flag to false.
5. WHERE a metric's Has_Data_Flag is false, THE Stats_Service SHALL return that metric's value in a form the Overview_Tab can render as "—".

### Requirement 13: Stats endpoint access control and gating

**User Story:** As a security-conscious operator, I want the stats endpoint gated and access-controlled, so that staff metrics are only visible to authorised users.

#### Acceptance Criteria

1. THE Stats_Endpoint SHALL be gated by the `staff_management` Module_Gate.
2. WHERE the requester has the `org_admin` or `salesperson` role, THE Stats_Endpoint SHALL return stats for any staff member in the requester's organisation.
3. WHERE the requester has the `branch_admin` role, THE Stats_Endpoint SHALL return stats only for staff members within the requester's assigned location scope.
4. WHERE the requester has the `staff_member` role, THE Stats_Endpoint SHALL return stats only for the requester's own staff record (Self_Scope).
5. IF a `staff_member` requests stats for a staff record other than their own, THEN THE Stats_Endpoint SHALL deny the request with an authorization error.
6. IF the requested staff member does not belong to the requester's organisation, THEN THE Stats_Endpoint SHALL deny the request.

### Requirement 14: Cross-cutting design and consumption standards

**User Story:** As a developer, I want the redesign to follow the project's design system and safe-consumption standards, so that it is robust, accessible, and consistent.

#### Acceptance Criteria

1. THE Staff_List_Page and Overview_Tab SHALL consume all API data using safe access (`?.`, `?? []`, `?? 0`, `?? '—'`).
2. THE Staff_List_Page and Overview_Tab SHALL render correctly in dark mode using `dark:` variants.
3. THE Staff_List_Page and Overview_Tab SHALL render responsively across supported viewport widths.
4. THE Staff_List_Page and Overview_Tab SHALL render identifiers and dates using the monospace font per the design system.
5. THE Stats_Endpoint SHALL return its payload as a structured object and SHALL NOT return a bare array.

## Out of Scope

The following are explicitly excluded from this feature:

1. Mobile app changes.
2. The roster grid editor (covered by a separate spec).
3. Adding a `completed_at` column to `job_cards`; `updated_at` is the accepted completion proxy for Jobs_Completed.
4. Any new database tables or migrations.
