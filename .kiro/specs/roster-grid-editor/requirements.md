# Requirements Document — Roster Grid Editor

## Introduction

The Roster Grid Editor is a desktop-first, Excel-like rostering view that lets an org admin manage shifts for every active staff member across a 14-day window from a single screen. It is a fourth view alongside the three existing roster surfaces:

- `/schedule` — `ScheduleCalendar` (day/week dnd-kit calendar)
- `/staff-schedule` — branch-scoped basic table view with Add Shift form
- `/staff/:id` Roster tab — embeds `ScheduleCalendar` with `focusStaffId`

The grid editor lives at `/staff-schedule/grid`. It does not replace any existing surface and ships no new data model — every entry is a row in the existing `schedule_entries` table, every paintable shift comes from the existing `shift_templates` table, conflicts are detected by the existing `SchedulingService.detect_conflicts(...)`, and the screen is module-gated by `scheduling`.

The grid supports keyboard navigation, copy/paste of cell entries, paint-mode bulk creation by dragging a selected template across cells, multi-select of staff rows for cross-row template application, a "Copy week 1 → week 2" button, branch + position filters, leave-aware shading, and CSV/print export of the visible window.

To keep paint-mode UX responsive, the backend gains one new endpoint — `POST /api/v2/schedule/bulk` — that accepts up to 200 entries in a single transaction with per-entry SAVEPOINT rollback so a single conflict does not kill the whole batch. No migrations are required.

## Glossary

- **Roster_Grid_Editor**: The new page at `/staff-schedule/grid` rendering active staff as rows × 14 days as columns.
- **Grid_Cell**: One staff_id × calendar_date intersection. May be empty, contain one or more `schedule_entries`, or be in a leave-shaded state.
- **Active_Staff**: Rows from `staff_members` where `is_active = true` and (when a branch filter is set) linked to that branch via `staff_locations`.
- **Schedule_Entry**: An existing row in `schedule_entries` with `entry_type ∈ ('job','booking','break','other','leave')` and `status ∈ ('scheduled','completed','cancelled')`.
- **Shift_Template**: A reusable row in `shift_templates` with `name`, `start_time time`, `end_time time`, `entry_type`. Drives the paint palette and quick-apply.
- **Template_Palette**: The sidebar listing the org's shift templates; selecting one enters Paint_Mode.
- **Paint_Mode**: The UI state entered by selecting a template; while active, click-and-drag across grid cells creates one schedule_entry per painted cell using the selected template.
- **Paint_Rectangle**: The (top-left, bottom-right) cell rectangle defined by the anchor cell where pointer-down occurred and the current cell under the pointer.
- **Selected_Staff_Set**: The set of staff rows currently multi-selected via Shift+click on row headers; defaults to empty.
- **Selected_Day_Set**: The set of date columns currently multi-selected via Shift+click on column headers; defaults to empty.
- **Schedule_API**: The existing v2 router at `/api/v2/schedule` + `/api/v2/schedule/templates` + the new `/api/v2/schedule/bulk`.
- **Bulk_Schedule_Service**: The service-layer function backing `POST /api/v2/schedule/bulk` and `POST /api/v2/schedule/copy-week` that wraps each entry insert in a SAVEPOINT and aggregates per-entry results.
- **Conflict_Detector**: The existing `SchedulingService.detect_conflicts(...)` used to flag overlap entries before/after bulk creation.
- **Schedule_Entry_Modal**: The existing modal opened from `ScheduleCalendar` for creating and editing single entries; reused unchanged by the grid editor.
- **Keyboard_Navigator**: The grid's keyboard handler that maps arrow keys, Tab, Enter, Delete, and Ctrl+C/Ctrl+V to focus and clipboard actions.
- **Cell_Clipboard**: An in-memory client-side clipboard holding one or more copied schedule entries with their relative offsets, used by Ctrl+V paste.
- **Leave_Shaded_Cell**: A grid cell where the staff has an approved leave_request overlapping that date; rendered greyed-out and excluded from paint and bulk-apply by default.
- **Module_Gate**: The middleware that returns 403 unless the org has the `scheduling` module enabled.
- **Visible_Window**: The 14 contiguous calendar dates currently rendered in the grid; defaults to "this week + next week" anchored on Monday.
- **Week_1**: The first 7 days of the Visible_Window. **Week_2**: the last 7 days.
- **Org_Admin**: A user whose role is `org_admin`. **Salesperson**: role `salesperson`. Both can read and write the grid; lower roles are 403.

## Requirements

### Requirement 1: Module gating and access

**User Story:** As an org_admin, I want the Roster Grid Editor to only be reachable when the scheduling module is enabled, so that orgs without the module never see broken navigation.

#### Acceptance Criteria

1. WHILE the `scheduling` module is enabled for the org, THE Roster_Grid_Editor SHALL be reachable at `/staff-schedule/grid` for users with role `org_admin` or `salesperson`.
2. WHILE the `scheduling` module is disabled for the org, THE Module_Gate SHALL return HTTP 403 for every Schedule_API call from the grid and the `/staff-schedule/grid` route SHALL render a module-disabled empty state.
3. THE Roster_Grid_Editor SHALL add a "Grid view" toggle button to the toolbar of the existing `/staff-schedule` page that links to `/staff-schedule/grid`.
4. THE Roster_Grid_Editor SHALL add a "Grid view" toggle button to the toolbar of the existing `/schedule` page that links to `/staff-schedule/grid`.
5. WHEN a user with a role other than `org_admin` or `salesperson` visits `/staff-schedule/grid`, THE Roster_Grid_Editor SHALL redirect to `/dashboard`.

### Requirement 2: 14-day grid layout with active staff rows

**User Story:** As an org_admin, I want to open the grid view and see every active staff member as a row across 14 days as columns, so that I can plan two weeks at a glance from one screen.

#### Acceptance Criteria

1. WHEN the Roster_Grid_Editor first loads, THE Roster_Grid_Editor SHALL set the Visible_Window to the Monday of the current ISO week through the Sunday 13 days later.
2. THE Roster_Grid_Editor SHALL render one row per Active_Staff member sorted by `last_name`, `first_name`.
3. THE Roster_Grid_Editor SHALL render 14 date columns spanning the Visible_Window with the day-of-week and day-of-month visible in the header.
4. THE Roster_Grid_Editor SHALL display a vertical separator between Week_1 and Week_2 columns.
5. WHEN the user clicks "Previous fortnight" or "Next fortnight", THE Roster_Grid_Editor SHALL shift the Visible_Window by exactly 14 days and refetch entries.
6. WHEN the user clicks "Today", THE Roster_Grid_Editor SHALL reset the Visible_Window to the Monday of the current ISO week.
7. THE Roster_Grid_Editor SHALL fetch Schedule_Entries via `GET /api/v2/schedule?start={visible_window_start}&end={visible_window_end}` once per Visible_Window change and reuse the result for every cell render.
8. IF the org has zero Active_Staff, THEN THE Roster_Grid_Editor SHALL display an empty state with copy "No active staff. Add a staff member to start rostering." and a button linking to `/staff`.
9. WHILE the initial fetch is in flight, THE Roster_Grid_Editor SHALL display a skeleton grid with the same row and column count as the previous render (or a default 5×14 skeleton on first load).

### Requirement 3: Branch, position, and leave filters

**User Story:** As an org_admin, I want to filter the grid by branch and position so that I only see the staff I am rostering for right now.

#### Acceptance Criteria

1. THE Roster_Grid_Editor SHALL render a branch filter dropdown populated from the user's accessible branches via the existing `BranchContext` (shape: `{ selectedBranchId, branches }`).
2. THE Roster_Grid_Editor SHALL render a position filter dropdown populated from the distinct non-null `staff_members.position` values within the org.
3. WHEN the user changes the branch filter, THE Roster_Grid_Editor SHALL fetch the org's staff list once via `GET /api/v2/staff?is_active=true&page_size=200` and SHALL filter the rows client-side to the selected branch using the staff member's `location_assignments` (CODE-GAP-9 — `/api/v2/staff` does not accept a `branch_id` query param at the time of writing this spec; server-side filtering is parked for a follow-up).
4. WHEN the user changes the position filter, THE Roster_Grid_Editor SHALL filter the existing staff rows client-side by exact-match on `position`.
5. WHILE a staff member has an approved leave_request overlapping a cell's date, THE Roster_Grid_Editor SHALL render that cell as a Leave_Shaded_Cell with the leave_type label and SHALL exclude that cell from Paint_Mode rectangle expansion by default.
6. WHEN the user holds the Alt key while painting, THE Roster_Grid_Editor SHALL include Leave_Shaded_Cells in the Paint_Rectangle and surface a confirmation prompt before submitting bulk creates that overlap leave.
7. THE Roster_Grid_Editor SHALL fetch leave overlaps for the Visible_Window via `GET /api/v2/leave/approvals?status=approved&start_lte=<visible_window_end>&end_gte=<visible_window_start>&limit=500`. THE backend SHALL accept `start_lte: date | None` and `end_gte: date | None` query params on `/api/v2/leave/approvals` (added by task A7) so the predicate `LeaveRequest.start_date <= start_lte AND LeaveRequest.end_date >= end_gte` is enforced server-side.

### Requirement 4: Single-cell click-to-create and click-to-edit

**User Story:** As an org_admin, I want to click an empty cell to create a single shift and click an existing entry to edit it, so that the grid works as a direct-manipulation surface for one-off shifts.

#### Acceptance Criteria

1. WHEN the user single-clicks an empty Grid_Cell while no Paint_Mode template is selected, THE Roster_Grid_Editor SHALL open the existing Schedule_Entry_Modal in create mode pre-filled with that cell's `staff_id` and the cell's date as the `start_time` date and the staff member's default working hours (or 09:00–17:00 if none configured).
2. WHEN the user single-clicks a cell that contains exactly one Schedule_Entry, THE Roster_Grid_Editor SHALL open the Schedule_Entry_Modal in edit mode with that entry's id.
3. WHEN the user single-clicks a cell that contains more than one Schedule_Entry, THE Roster_Grid_Editor SHALL open a disambiguation popover listing each entry by title and start_time and SHALL open the Schedule_Entry_Modal in edit mode for the entry the user picks.
4. WHEN the Schedule_Entry_Modal saves a create, THE Roster_Grid_Editor SHALL append the new entry into the in-memory Visible_Window cache and re-render the affected cell without a full refetch.
5. WHEN the Schedule_Entry_Modal saves an edit or delete, THE Roster_Grid_Editor SHALL update or remove the entry in the in-memory cache and re-render the affected cell without a full refetch.

### Requirement 5: Drag-handle resize on a cell extends end_time

**User Story:** As an org_admin, I want to drag the right edge of a cell entry to extend its end time, so that I can quickly stretch a shift without opening the modal.

#### Acceptance Criteria

1. THE Roster_Grid_Editor SHALL render a drag handle on the right edge of every Schedule_Entry block within a Grid_Cell.
2. WHEN the user drags the handle horizontally, THE Roster_Grid_Editor SHALL snap the new end_time to the nearest 15-minute increment between `start_time + 15 minutes` and `start_time + 24 hours`.
3. WHEN the user releases the drag, THE Roster_Grid_Editor SHALL call `PUT /api/v2/schedule/{id}/reschedule` with the original `start_time` and the new `end_time`.
4. IF the reschedule call returns HTTP 409 with conflict information, THEN THE Roster_Grid_Editor SHALL revert the visual change and display a non-blocking warning toast naming the conflicting entry.
5. IF the reschedule call returns HTTP 422, THEN THE Roster_Grid_Editor SHALL revert the visual change and display the validation message.
6. THE Roster_Grid_Editor SHALL NOT allow drag-resize across midnight on the cell's date; an attempt to do so SHALL clamp end_time to 23:59 of the cell's date.

### Requirement 6: Paint mode — select template and drag to bulk-create

**User Story:** As an org_admin, I want to select a shift template from the sidebar and click-and-drag across cells to create that shift on every painted cell, so that I can build a roster in seconds.

#### Acceptance Criteria

1. THE Template_Palette SHALL render the org's Shift_Templates fetched from `GET /api/v2/schedule/templates` sorted by `name`.
2. WHEN the user clicks a template in the Template_Palette, THE Roster_Grid_Editor SHALL enter Paint_Mode with that template selected and SHALL change the cursor to a paint-bucket indicator over Grid_Cells.
3. WHEN the user presses pointer-down on a Grid_Cell while in Paint_Mode, THE Roster_Grid_Editor SHALL set that cell as the Paint_Rectangle anchor and begin tracking the rectangle.
4. WHILE the user drags the pointer in Paint_Mode, THE Roster_Grid_Editor SHALL render the Paint_Rectangle as the bounding rectangle of the anchor cell and the cell currently under the pointer and SHALL highlight every cell inside that rectangle.
5. WHEN the user releases the pointer in Paint_Mode, THE Roster_Grid_Editor SHALL submit one Schedule_Entry per highlighted cell via `POST /api/v2/schedule/bulk` with `entry_type`, `start_time`, `end_time` derived from the selected template applied to each cell's date.
6. WHEN the user presses Escape while in Paint_Mode, THE Roster_Grid_Editor SHALL exit Paint_Mode and clear the highlighted Paint_Rectangle without making any API call.
7. WHILE Paint_Mode is active and a Grid_Cell already contains a Schedule_Entry created from the same template on the same date for the same staff member, THE Roster_Grid_Editor SHALL skip that cell in the bulk submit (idempotence — see Requirement 14.3).
8. WHILE Paint_Mode is active and a Grid_Cell already contains a Schedule_Entry from a *different* template, THE Roster_Grid_Editor SHALL include that cell in the submit and SHALL surface any returned conflicts via the conflict warning banner (Requirement 13).
9. IF the Paint_Rectangle exceeds 200 cells, THEN THE Roster_Grid_Editor SHALL refuse the submit and display the message "Maximum 200 cells per paint action. Reduce the rectangle and try again." without calling the API.
10. THE Roster_Grid_Editor SHALL exit Paint_Mode when the user clicks the selected template a second time or clicks a "Cancel paint" button in the toolbar.

### Requirement 7: Multi-select staff rows and bulk-apply a template

**User Story:** As an org_admin, I want to multi-select staff rows and click a template to create that shift on every selected staff for a focused day or day-range, so that I can roster a whole crew with two clicks.

#### Acceptance Criteria

1. WHEN the user clicks a row header, THE Roster_Grid_Editor SHALL toggle that staff_id in the Selected_Staff_Set.
2. WHEN the user Shift+clicks a second row header, THE Roster_Grid_Editor SHALL set the Selected_Staff_Set to every staff_id between the previous click and the new click inclusive (range select).
3. WHEN the user clicks a column header, THE Roster_Grid_Editor SHALL toggle that date in the Selected_Day_Set.
4. WHEN the user Shift+clicks a second column header, THE Roster_Grid_Editor SHALL set the Selected_Day_Set to every date between the previous click and the new click inclusive.
5. WHILE Selected_Staff_Set is non-empty AND Selected_Day_Set is non-empty AND a template is selected in the Template_Palette, THE Roster_Grid_Editor SHALL display an "Apply template" toolbar button.
6. WHEN the user clicks "Apply template", THE Roster_Grid_Editor SHALL submit `|Selected_Staff_Set| × |Selected_Day_Set|` entries via `POST /api/v2/schedule/bulk` with the template's `start_time`/`end_time`/`entry_type` applied to each (staff, date) pair.
7. THE "Apply template" submit SHALL skip cells that already contain a Schedule_Entry created from the same template for the same (staff, date) pair (idempotence).
8. WHEN the user presses Escape, THE Roster_Grid_Editor SHALL clear Selected_Staff_Set and Selected_Day_Set.
9. IF `|Selected_Staff_Set| × |Selected_Day_Set|` exceeds 200, THEN THE Roster_Grid_Editor SHALL refuse the submit with the same 200-cell-cap message as Paint_Mode.

### Requirement 8: Copy this week → next week

**User Story:** As an org_admin, I want to copy week 1 of the visible window into week 2 with a single button, so that I can repeat a recurring fortnight pattern without painting twice.

#### Acceptance Criteria

1. THE Roster_Grid_Editor SHALL render a "Copy Week 1 → Week 2" button in the toolbar.
2. WHEN the user clicks "Copy Week 1 → Week 2", THE Roster_Grid_Editor SHALL display a confirmation modal listing the count of source entries and the count of destination cells that already contain entries.
3. WHEN the user confirms the copy, THE Roster_Grid_Editor SHALL submit every Schedule_Entry whose `start_time` is within Week_1 to `POST /api/v2/schedule/copy-week` with body `{ source_week_start, target_week_start, overwrite_existing: false }`.
4. THE Bulk_Schedule_Service SHALL produce one new Schedule_Entry per source entry with `start_time` and `end_time` shifted by exactly +7 calendar days and SHALL preserve `entry_type`, `title`, `description`, `notes`, `staff_id`, `job_id`, `booking_id`, `location_id`.
5. THE Bulk_Schedule_Service SHALL set `recurrence_group_id = NULL` on every copied entry (the copy is not a recurrence).
6. THE Bulk_Schedule_Service SHALL set `status = 'scheduled'` on every copied entry regardless of the source status.
7. IF a target cell already contains a Schedule_Entry on the same staff and same date with overlapping times, THEN THE Bulk_Schedule_Service SHALL skip that source entry, record it under `conflicts` in the response, and continue with the remaining entries.
8. WHEN the response returns, THE Roster_Grid_Editor SHALL display a summary toast "Copied N entries, skipped M due to conflicts." and SHALL render the new entries in Week_2.
9. WHEN the user toggles "Overwrite existing" in the confirmation modal, THE Roster_Grid_Editor SHALL submit `overwrite_existing: true` and THE Bulk_Schedule_Service SHALL delete overlapping target entries before inserting the copies.

### Requirement 9: Cell copy and paste with the keyboard

**User Story:** As an org_admin, I want to copy a cell's shift and paste it onto another cell using Ctrl+C and Ctrl+V, so that I can replicate a one-off shift across the grid.

#### Acceptance Criteria

1. WHEN the user presses Ctrl+C (or Cmd+C on macOS) while one Grid_Cell has keyboard focus and that cell contains at least one Schedule_Entry, THE Roster_Grid_Editor SHALL place every Schedule_Entry in that cell into the Cell_Clipboard with their (staff_id, date) offsets relative to the focused cell.
2. WHEN the user presses Ctrl+V (or Cmd+V on macOS) while one Grid_Cell has keyboard focus and Cell_Clipboard is non-empty, THE Roster_Grid_Editor SHALL submit one Schedule_Entry per clipboard item via `POST /api/v2/schedule/bulk` with `start_time` and `end_time` shifted to the focused cell's date plus each clipboard item's relative offset.
3. THE Cell_Clipboard SHALL persist for the lifetime of the page (no cross-tab clipboard).
4. THE Roster_Grid_Editor SHALL NOT use the system clipboard for cell copy/paste; the Cell_Clipboard is in-memory only.
5. WHEN the user presses Ctrl+C with multiple cells selected via Shift+arrow, THE Roster_Grid_Editor SHALL copy every Schedule_Entry in the selected rectangle into the Cell_Clipboard preserving relative offsets.

### Requirement 10: Keyboard navigation

**User Story:** As an org_admin, I want to navigate the grid with arrow keys, open the modal with Enter, and delete a focused entry with Delete, so that I can roster without a mouse.

#### Acceptance Criteria

1. THE Roster_Grid_Editor SHALL render the grid as an ARIA `role="grid"` with each cell as `role="gridcell"` and the focused cell receiving `tabindex=0` while all other cells receive `tabindex=-1`.
2. WHEN the user presses ArrowRight while a cell has focus, THE Keyboard_Navigator SHALL move focus to the next cell to the right; if the focused cell is in the rightmost column, focus SHALL stay on that cell.
3. WHEN the user presses ArrowLeft while a cell has focus, THE Keyboard_Navigator SHALL move focus to the next cell to the left; if the focused cell is in the leftmost column, focus SHALL stay on that cell.
4. WHEN the user presses ArrowDown while a cell has focus, THE Keyboard_Navigator SHALL move focus to the cell directly below; if the focused cell is in the bottom row, focus SHALL stay on that cell.
5. WHEN the user presses ArrowUp while a cell has focus, THE Keyboard_Navigator SHALL move focus to the cell directly above; if the focused cell is in the top row, focus SHALL stay on that cell.
6. WHEN the user presses Tab while a cell has focus, THE Keyboard_Navigator SHALL move focus out of the grid to the next focusable element on the page.
7. WHEN the user presses Enter while a cell has focus, THE Keyboard_Navigator SHALL trigger the same behaviour as a single-click on that cell (Requirement 4).
8. WHEN the user presses Delete or Backspace while a cell has focus and that cell contains exactly one Schedule_Entry, THE Keyboard_Navigator SHALL display an inline confirmation, and on confirm SHALL call `DELETE /api/v2/schedule/{id}` and remove the entry from the cell.
9. WHEN the user presses Delete or Backspace on a cell with multiple Schedule_Entries, THE Keyboard_Navigator SHALL open the disambiguation popover from Requirement 4.3 with each entry showing a Delete button.
10. WHEN the user presses Shift+ArrowRight/Left/Up/Down, THE Keyboard_Navigator SHALL extend the current cell selection rectangle by one cell in that direction without moving focus outside the grid.

### Requirement 11: Bulk-create endpoint with per-entry SAVEPOINT rollback

**User Story:** As a developer, I want a bulk-create endpoint that accepts up to 200 entries and rolls back per entry on conflict, so that paint-mode UX is fast and a single conflict does not lose 199 successful creates.

#### Acceptance Criteria

1. THE Schedule_API SHALL expose `POST /api/v2/schedule/bulk` with body `{ entries: ScheduleEntryCreate[] }` (the existing `ScheduleEntryCreate` schema).
2. THE Schedule_API SHALL refuse with HTTP 422 when `entries` contains zero items or more than 200 items.
3. WHEN `POST /api/v2/schedule/bulk` is called, THE Bulk_Schedule_Service SHALL wrap each entry insert in a SAVEPOINT, run Conflict_Detector for each entry, and on conflict SHALL roll back that SAVEPOINT and append the source index, attempted entry, and the conflicting entries to the response under `conflicts`.
4. THE Bulk_Schedule_Service SHALL return `{ created: ScheduleEntryResponse[], conflicts: [{ index: int, attempted: ScheduleEntryCreate, conflicts_with: ScheduleEntryResponse[] }] }` with `len(created) + len(conflicts) == len(entries)`.
5. THE Bulk_Schedule_Service SHALL commit the surrounding transaction even when one or more entries conflicted, so that successful entries persist.
6. THE Schedule_API SHALL apply the same `scheduling` Module_Gate to `/api/v2/schedule/bulk` as to the existing `/api/v2/schedule` endpoints.
7. THE Schedule_API SHALL expose `POST /api/v2/schedule/copy-week` with body `{ source_week_start: date, target_week_start: date, overwrite_existing: bool }` returning the same `{ created, conflicts }` shape.
8. WHEN `overwrite_existing` is true, THE Bulk_Schedule_Service SHALL delete every Schedule_Entry on the target staff/date that overlaps an incoming source entry's shifted time range before inserting the copy, within the same SAVEPOINT.
9. THE Bulk_Schedule_Service SHALL set `entry_type`, `start_time`, `end_time`, `staff_id`, `org_id` on every created entry and SHALL never accept a different `org_id` than the request's resolved org.

### Requirement 12: Optimistic UI with rollback on bulk failures

**User Story:** As an org_admin, I want the grid to feel instant when I paint, so that the roster reflects my action before the round-trip completes.

#### Acceptance Criteria

1. WHEN the Roster_Grid_Editor submits a bulk create (Paint_Mode, Apply template, Copy week, or Cell paste), THE Roster_Grid_Editor SHALL append placeholder entries to the in-memory Visible_Window cache before the API call returns and SHALL render them with a "Saving" visual state.
2. WHEN the bulk response returns successfully, THE Roster_Grid_Editor SHALL replace each placeholder with the corresponding `ScheduleEntryResponse` from `created`.
3. IF the bulk response includes any `conflicts`, THEN THE Roster_Grid_Editor SHALL remove the placeholders for those source indices and SHALL display the conflict warning banner from Requirement 13.
4. IF the bulk request fails with HTTP 5xx or a network error, THEN THE Roster_Grid_Editor SHALL remove every placeholder for that submit and SHALL display an error toast "Failed to save shifts. Please try again."
5. WHILE a bulk submit is in flight, THE Roster_Grid_Editor SHALL disable the Template_Palette, Paint_Mode, Apply template, Copy week, and Ctrl+V handlers to prevent overlapping submits.

### Requirement 13: Conflict warning banner

**User Story:** As an org_admin, when a bulk action produces conflicts, I want a single warning banner that lists the conflicting cells and the existing entries, so that I can resolve them without scrolling the grid hunting for red cells.

#### Acceptance Criteria

1. WHEN a bulk response includes one or more `conflicts`, THE Roster_Grid_Editor SHALL render a dismissible warning banner at the top of the grid listing each conflict's `(staff_name, date, attempted_time_range, conflicting_entry_titles)`.
2. THE Roster_Grid_Editor SHALL highlight every Grid_Cell referenced in a conflict with a red outline that persists until the banner is dismissed.
3. WHEN the user clicks a conflict row in the banner, THE Roster_Grid_Editor SHALL scroll the grid so that the referenced Grid_Cell is centred and SHALL set keyboard focus on that cell.
4. WHEN the user dismisses the banner, THE Roster_Grid_Editor SHALL clear every red-outline highlight.
5. THE Roster_Grid_Editor SHALL NOT auto-dismiss the banner on a timeout; only an explicit dismiss action SHALL clear it.

### Requirement 14: Idempotence and bounded behaviour properties

**User Story:** As a developer, I want the grid's bulk operations to behave predictably under repeated input, so that the implementation is testable with property-based tests.

#### Acceptance Criteria

1. THE Bulk_Schedule_Service SHALL accept a list of N entries and SHALL produce a response where `len(created) + len(conflicts) == N` and `len(created) ≤ N` (Property P1).
2. THE Bulk_Schedule_Service `copy-week` operation SHALL produce one created entry per source entry minus any conflicts; for every created entry, `(end_time - start_time) == (source.end_time - source.start_time)` and `entry_type == source.entry_type` and `title == source.title` and `description == source.description` (Property P2).
3. WHEN the user re-paints the same Paint_Rectangle with the same selected template, THE Roster_Grid_Editor SHALL produce zero new Schedule_Entries because every cell already contains an entry from that template on that date for that staff member (Property P3 — idempotence).
4. WHEN the user issues any sequence of arrow-key presses starting from any cell in the grid, THE Keyboard_Navigator SHALL leave focus on a cell that is in the grid; that is, for an `R × C` grid the focused `(row, col)` SHALL remain in `[0, R) × [0, C)` (Property P4 — bounded navigation).

### Requirement 15: CSV and print export of the visible window

**User Story:** As an org_admin, I want to export the grid as CSV or print it, so that I can share the roster with staff who do not use the app.

#### Acceptance Criteria

1. THE Roster_Grid_Editor SHALL render an "Export CSV" button in the toolbar.
2. WHEN the user clicks "Export CSV", THE Roster_Grid_Editor SHALL produce a CSV with a header row of `staff_name, position` followed by 14 date columns labelled `YYYY-MM-DD (Day)`.
3. THE CSV SHALL render each cell as a comma-free, semicolon-separated list of `HH:MM-HH:MM Title` strings sorted by `start_time`; an empty cell SHALL render as the empty string; a Leave_Shaded_Cell SHALL render as `LEAVE: <leave_type_label>`.
4. THE CSV SHALL escape any embedded double-quotes in titles per RFC 4180 and wrap fields containing commas, newlines, or double-quotes in double-quotes.
5. WHEN the user clicks "Print", THE Roster_Grid_Editor SHALL invoke `window.print()` after applying a print-only stylesheet that removes the Template_Palette, toolbar, and filters and forces the grid onto landscape A3.
6. THE printed output SHALL fit 14 columns plus a row-header column on a single landscape A3 page using a stylesheet rule of `@page { size: A3 landscape; margin: 10mm; }`.

### Requirement 16: Frontend contract for Schedule_API responses

**User Story:** As a developer maintaining the grid editor, I want every API response to be consumed safely, so that a missing field on the server never crashes the UI.

#### Acceptance Criteria

1. THE Roster_Grid_Editor SHALL access every `entries` array as `res.data?.entries ?? []` and every total as `res.data?.total ?? 0`.
2. THE Roster_Grid_Editor SHALL access every `created` array on bulk responses as `res.data?.created ?? []` and every `conflicts` array as `res.data?.conflicts ?? []`.
3. THE Roster_Grid_Editor SHALL access every `templates` array as `res.data?.templates ?? []`.
4. THE Roster_Grid_Editor SHALL guard every `useEffect` that issues an API call with an `AbortController` and abort the controller in the cleanup function.
5. THE Roster_Grid_Editor SHALL NOT use `as any` on any Schedule_API response; every API call SHALL be typed via a generic on the apiClient method.

### Requirement 17: Backend conventions

**User Story:** As a developer, I want the new bulk endpoints to follow project conventions for sessions, audit, and ORM refresh, so that they integrate cleanly with the existing scheduling module.

#### Acceptance Criteria

1. THE Bulk_Schedule_Service SHALL use `db.flush()` after each insert and `await db.refresh(entry)` before returning the entry in the `created` array.
2. THE Bulk_Schedule_Service SHALL NOT call `db.commit()` directly; the surrounding `get_db_session` `session.begin()` context SHALL drive the commit.
3. THE Bulk_Schedule_Service SHALL write one `audit_log` row per bulk action via `app.core.audit.write_audit_log(session=db, action='schedule.bulk_created' (or 'schedule.copied_week'), entity_type='schedule_entry', entity_id=None, before_value=None, after_value={'created_count': N, 'conflicts_count': M, 'source_week_start': ..., 'target_week_start': ..., 'overwrite_existing': bool})`. Note: the helper kwarg is `action`, NOT `event_type` (CODE-GAP-2). Individual entry payloads SHALL NOT be expanded into the audit row.
4. THE Schedule_API SHALL respond with `{ items: [...], total: N }` shape on every list endpoint; the bulk endpoints SHALL respond with `{ created, conflicts }` (named, not bare arrays).
5. THE Roster_Grid_Editor frontend SHALL use the `apiClient` baseURL override pattern `apiClient.get('/schedule', { baseURL: '/api/v2' })` (or equivalent) per the existing `/api/v2` v2 interceptor convention.

### Requirement 18: Mobile fallback

**User Story:** As an org_admin on a phone, I want the existing day-stack roster view to keep working, so that I am not forced into an unusable grid on a small screen.

#### Acceptance Criteria

1. WHILE the viewport width is below 1024 CSS pixels, THE Roster_Grid_Editor SHALL render an info banner "The grid editor needs at least 1024px width. Use the day or week view on mobile." and a button linking to `/schedule`.
2. THE Roster_Grid_Editor SHALL NOT attempt to render the 14-column grid below 1024px width.
3. THE existing mobile roster surfaces (`/schedule` day view, the per-staff Roster tab) SHALL remain unchanged by this feature.

### Requirement 19: Performance budget

**User Story:** As an org_admin with a 50-staff team, I want the grid to render and paint quickly, so that the editor does not feel slower than the existing calendar.

#### Acceptance Criteria

1. WHEN the Visible_Window is loaded for an org with up to 50 Active_Staff and up to 700 Schedule_Entries in the window, THE Roster_Grid_Editor SHALL render the initial grid within 1000ms of the API response landing on the client.
2. WHEN the user paints a 14-cell rectangle (one row × 14 days), THE Roster_Grid_Editor SHALL display the bulk response and re-render the affected row within 500ms of the API response landing on the client (server response time excluded from this budget).
3. THE Roster_Grid_Editor SHALL virtualise rows when the Active_Staff count exceeds 100 so that the DOM contains at most the visible rows plus a 5-row buffer above and below.
4. THE Bulk_Schedule_Service SHALL handle a 200-entry bulk insert within 5 seconds p99 on the existing Pi production hardware (single-tenant, no cold-start cost).

### Requirement 20: Trade-family scope

**User Story:** As an org_admin in any trade family, I want the Roster Grid Editor to be available without trade-specific gating, so that any business with the scheduling module can use it.

#### Acceptance Criteria

1. THE Roster_Grid_Editor SHALL be a universal feature — it does not depend on the org's `trade_family` or `trade_category_id` and contains no trade-specific UI (no `vehicles`, `parts`, `fluids`, `pipe sizes`, etc.).
2. THE Roster_Grid_Editor SHALL be gated only by the `scheduling` module enablement (Module_Gate, Requirement 1).
3. THE Roster_Grid_Editor SHALL NOT introduce any new `org_modules`, `module_registry`, or `feature_flags` rows. The existing `scheduling` module already covers this surface.

(Per `.kiro/steering/trade-family-gating-for-new-features.md` — closed as GAP-S1.)

### Requirement 21: Error and loading state UI

**User Story:** As an org_admin, when the API returns an error, I want a clear visible message so I can decide whether to retry, contact support, or work around it.

#### Acceptance Criteria

1. WHEN the initial fetch (staff + entries + leave overlaps) returns HTTP 401, THE Roster_Grid_Editor SHALL redirect to `/login` (handled by the existing axios interceptor on 401; no new UI needed).
2. WHEN the initial fetch returns HTTP 403 with `{ "module": "scheduling" }`, THE Roster_Grid_Editor SHALL render a module-disabled empty state with copy "Scheduling module is disabled. Ask your org admin to enable it." and a link to Settings → Modules.
3. WHEN the initial fetch returns HTTP 403 without a module key, THE Roster_Grid_Editor SHALL redirect to `/dashboard` (the user is not org_admin/salesperson — Requirement 1.5).
4. WHEN any API call returns HTTP 404, THE Roster_Grid_Editor SHALL display an inline error banner "The requested data was not found. Try refreshing the page." with a refresh button.
5. WHEN any API call returns HTTP 422, THE Roster_Grid_Editor SHALL display the validation message from `response.data.detail` (or the first item in `response.data.detail` if it is an array of Pydantic errors).
6. WHEN any bulk-create call returns HTTP 409, THE Roster_Grid_Editor SHALL surface the conflicts via the existing conflict banner (Requirement 13). HTTP 409 is treated identically to a 200 response with non-empty `conflicts`.
7. WHEN any API call returns HTTP 5xx OR a network error, THE Roster_Grid_Editor SHALL display a non-blocking error toast via `useToast().addToast('error', 'Failed to ...')` (NOT `<Toast variant="error">` — see CODE-GAP-6). The toast SHALL include a "Retry" action that re-runs the original call.
8. WHEN an in-flight request is aborted via `AbortController` (e.g. on unmount, on filter change), THE Roster_Grid_Editor SHALL silently swallow the resulting `CanceledError` and NOT update state — matching the canonical pattern in the existing `ScheduleEntryModal.fetchStaff` callback.

(Per `.kiro/steering/spec-completeness-checklist.md` §7 — closed as GAP-S5.)

### Requirement 22: Scope of role gating on existing endpoints

**User Story:** As a developer, I want the bulk + copy-week endpoints to be guarded by `org_admin`/`salesperson` roles without regressing the existing single-entry `/api/v2/schedule` endpoints.

#### Acceptance Criteria

1. THE Schedule_API SHALL apply `dependencies=[require_role("org_admin", "salesperson")]` to the NEW endpoints `POST /api/v2/schedule/bulk` and `POST /api/v2/schedule/copy-week` only.
2. THE Schedule_API SHALL NOT add new role guards to the EXISTING endpoints `POST /api/v2/schedule`, `PUT /api/v2/schedule/{id}`, `PUT /api/v2/schedule/{id}/reschedule`, `DELETE /api/v2/schedule/{id}`, `GET /api/v2/schedule`, `GET /api/v2/schedule/{id}`, `GET /api/v2/schedule/{id}/conflicts`, `GET /api/v2/schedule/templates`, `POST /api/v2/schedule/templates`, `DELETE /api/v2/schedule/templates/{id}`. These retain their pre-spec behaviour: open to any authed user with the `scheduling` module enabled. Tightening them is parked for a follow-up — see `gap-analysis.md` CODE-GAP-8.
3. THE Roster_Grid_Editor frontend SHALL also guard the route at `/staff-schedule/grid` so that users without `org_admin` or `salesperson` role are redirected to `/dashboard` (Requirement 1.5). The frontend role check is the primary user-facing enforcement; the new bulk endpoints add the back-end belt-and-braces.

(Closes CODE-GAP-8 — preserves backward compatibility.)
