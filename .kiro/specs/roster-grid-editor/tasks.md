# Roster Grid Editor — Tasks

## Execution policy

- **Scoped testing only** — run only the tests for the files each task touches; never the full suite. Use `vitest run`, `pytest`, `tsc --noEmit`. No watchers.
- **No interactive prompts** — every CLI uses `--yes` / `-y` / `--non-interactive` where applicable.
- **Never stop for confirmation** — only stop on a verify failure or an explicit unresolved blocking open question.
- **Project conventions** — `{ items, total }` (or named `{ entries, total }`) response shape, `?.` + `?? []` / `?? 0` on every API consumption, `await db.refresh(obj)` after `db.flush()`, no `db.commit()` (the `get_db_session` dependency drives commit), audit table is `audit_log` (singular), RLS + tenant_isolation on every new table (no new tables here).
- **Failure handling** — log the failure detail to `gap-analysis.md` AND open an `ISSUE-XXX` row in `docs/ISSUE_TRACKER.md` per `.kiro/steering/issue-tracking-workflow.md`, mark the task `[~]`, continue with the next non-dependent task. Stop only after 3 consecutive failures.
- **Trade-family scope** — universal feature (R20). Do NOT add `tradeFamily ===` checks to any new component. Gating is module-only via the existing `scheduling` slug.
- **No replacing existing components** — per `.kiro/steering/no-shortcut-implementations.md`, do NOT modify the existing `ScheduleCalendar` or `StaffSchedule` components beyond adding the "Grid view" link in B19.
- **Browser test every B-task that ships UI** — per `.kiro/steering/implementation-completeness-checklist.md` rule 1, every Workstream B task that ships visible UI must be loaded in the browser before being marked complete. The Verify line on each B-task lists the browser checks.
- **No new migrations** — this feature reuses `schedule_entries` and `shift_templates` only.
- **Module gate** — every new endpoint must be covered by `MODULE_ENDPOINT_MAP['/api/v2/schedule'] = 'scheduling'` (already present); the bulk + copy-week endpoints inherit this prefix automatically.
- **`require_role` syntax** — varargs, no `Depends()` wrapper, no list literal. The canonical usage is `dependencies=[require_role("org_admin", "salesperson")]`. See `app/modules/quotes/router.py` for live reference.
- **`write_audit_log` kwargs** — first kwarg is `action`, NOT `event_type`. Second is `entity_type`. See `app/core/audit.py`.

Anchors against requirements.md: each task ends with `(R<n>.<m>)` referencing one or more acceptance criteria from `requirements.md`.

## Workstream A — Backend bulk endpoints

- [x] **A1. Pydantic schemas — `app/modules/scheduling_v2/schemas.py`.** Add `BulkScheduleEntryCreateRequest` (`entries: list[ScheduleEntryCreate]` with `min_length=1, max_length=200`), `BulkConflictItem` (`index: int`, `attempted: ScheduleEntryCreate`, `conflicts_with: list[ScheduleEntryResponse]`), `BulkScheduleEntryResponse` (`created: list[ScheduleEntryResponse]`, `conflicts: list[BulkConflictItem]`), `CopyWeekRequest` (`source_week_start: date`, `target_week_start: date`, `overwrite_existing: bool = False`). Pydantic v2 model_config inherits.
  - **Verify:** `pytest tests/unit/test_scheduling_v2_schemas.py -k bulk` — bulk request with 0 entries → ValidationError; with 201 entries → ValidationError; with 200 entries → ok. (R11.1, R11.2)

- [x] **A2. `bulk_create` service method on `SchedulingService`.** Add `async def bulk_create(self, org_id, payload: BulkScheduleEntryCreateRequest) -> tuple[list[ScheduleEntry], list[BulkConflictItem]]` per requirements §11.3–11.5. For each entry: open a SAVEPOINT (`async with self.db.begin_nested()`), run `_validate_create(entry)`, run `detect_conflicts(org_id, staff_id, start_time, end_time)`, on conflict → roll back the SAVEPOINT and append a `BulkConflictItem` to the conflicts list, on success → INSERT, `await self.db.flush()`, `await self.db.refresh(entry)`, append to created list. The outer transaction commits via `get_db_session`'s `session.begin()`.
  - **Per-entry validation** mirrors `create_entry`: `end_time > start_time`, `entry_type` matches the regex pattern from the schema, `staff_id` belongs to the org (FK is enough at the DB level — no extra query needed).
  - **Refuse cross-org `org_id`** — every inserted row uses the resolved `org_id` from the request, never any value from the payload (R11.9).
  - **DO NOT call `db.commit()` or `db.rollback()` from the router or service** (per `.kiro/steering/performance-and-resilience.md` rule 1 + ISSUE-044). Per-entry rollback is handled by `begin_nested()` SAVEPOINTs; the outer transaction is committed/rolled-back by the `get_db_session` `session.begin()` context manager.
  - **Verify:** unit test `tests/unit/test_scheduling_v2_bulk.py::test_bulk_create_partial_conflict` — submit 5 entries where the 3rd overlaps an existing entry → response has `len(created) == 4` and `len(conflicts) == 1` with `conflicts[0].index == 2`. The 4th and 5th still get inserted. (R11.3, R11.4, R11.5)
  - **Verify:** `tests/unit/test_scheduling_v2_bulk.py::test_bulk_create_zero_or_too_many` — 0 entries → 422; 201 entries → 422. (R11.2)
  - **Verify (Pydantic round-trip — GAP-S7):** submit a 2-entry bulk_create and assert `BulkScheduleEntryResponse(**raw_dict)` round-trips with no missing keys; every field on `BulkConflictItem` and `ScheduleEntryResponse` is reachable from the response. Catches the silent-drop pattern from `frontend-backend-contract-alignment.md` Rule 8.

- [x] **A3. `copy_week` service method on `SchedulingService`.** Add `async def copy_week(self, org_id, payload: CopyWeekRequest) -> tuple[list[ScheduleEntry], list[BulkConflictItem]]` per requirements §8.3–8.9. SELECT every `schedule_entries` row in the org where `start_time >= source_week_start AND start_time < source_week_start + 7 days`. For each source entry compute `delta = target_week_start - source_week_start` (a `timedelta` of exactly 7 days for the user-facing case but the method accepts any 7-day-aligned delta), build a `ScheduleEntryCreate` with `start_time = source.start_time + delta`, `end_time = source.end_time + delta`, preserving `entry_type`, `title`, `description`, `notes`, `staff_id`, `job_id`, `booking_id`, `location_id`, **forcing `recurrence_group_id = None`** (R8.5), and **forcing `status = 'scheduled'`** (R8.6). Then delegate to `bulk_create`.
  - **`overwrite_existing=true`** — for each source entry compute the projected target window, run `detect_conflicts` once before the SAVEPOINT, and `await self.db.execute(delete(ScheduleEntry).where(...))` for every conflicting target entry inside the same SAVEPOINT before the INSERT (R8.9 + R11.8).
  - **Validate that `(target_week_start - source_week_start).days % 7 == 0`** — refuse 422 otherwise (the requirements only spec a +7-day shift, but allowing any 7-day-aligned multiple keeps the method useful for "Copy Week 2 → next-but-one" without expanding scope).
  - **Verify:** unit test `tests/unit/test_scheduling_v2_copy_week.py::test_copy_week_preserves_duration_and_metadata` — Property test (Hypothesis) over arbitrary source entries with random `(start_time, duration_minutes, entry_type, title)` tuples → for every created entry, `(end_time - start_time) == (source.end_time - source.start_time)` and `entry_type == source.entry_type` and `title == source.title` and `description == source.description` and `recurrence_group_id is None` and `status == 'scheduled'`. (R8.4, R8.5, R8.6, R14.2)
  - **Verify:** `tests/unit/test_scheduling_v2_copy_week.py::test_copy_week_overwrite_deletes_targets` — pre-seed a target-week entry that overlaps; submit `overwrite_existing=true` → existing target deleted, new copy inserted, response `created` count includes the copy, `conflicts` is empty. (R8.9)
  - **Verify:** `tests/unit/test_scheduling_v2_copy_week.py::test_copy_week_skip_on_conflict_no_overwrite` — same setup, `overwrite_existing=false` → existing target untouched, source skipped, response includes the source under `conflicts[0]`. (R8.7)
  - **Verify (Pydantic round-trip — GAP-S7):** the response from `copy_week` deserialises into `BulkScheduleEntryResponse` with no missing fields; `created[i]` is a fully-populated `ScheduleEntryResponse`.

- [x] **A4. Audit log integration.** In `bulk_create` and `copy_week`, after the loop, call `write_audit_log(session=db, action='schedule.bulk_created'` (or `'schedule.copied_week'`)`, entity_type='schedule_entry', entity_id=None, org_id=org_id, user_id=current_user_id, before_value=None, after_value={ 'created_count': N, 'conflicts_count': M, 'source_week_start': ..., 'target_week_start': ..., 'overwrite_existing': bool })`. Note: the helper kwarg is `action`, NOT `event_type` (CODE-GAP-2). **Never expand individual entry payloads into the audit row** (R17.3) — keep summaries only.
  - **Verify:** integration test `tests/integration/test_scheduling_v2_audit.py` — submit a bulk_create of 3 entries (1 conflict, 2 created) → assert exactly one `audit_log` row written with `action='schedule.bulk_created'`, `entity_type='schedule_entry'`, `after_value['created_count']==2`, `after_value['conflicts_count']==1`, and **no key in `after_value` containing the word `entry` or `entries`** (the dict-literal shape must not include per-row data). (R17.3)

- [x] **A5. Router endpoints — `app/modules/scheduling_v2/router.py`.** Add `POST /bulk` and `POST /copy-week` per design.
  - **`POST /api/v2/schedule/bulk`** — body `BulkScheduleEntryCreateRequest`, response `BulkScheduleEntryResponse`. On `ValueError` from service → HTTP 422. On success → 200 with both arrays (NOT 201 — partial success isn't a creation event in the HTTP sense; mirrors how `PUT /reschedule` returns 200).
  - **`POST /api/v2/schedule/copy-week`** — body `CopyWeekRequest`, response `BulkScheduleEntryResponse`. Same status semantics.
  - Both endpoints use the existing `_get_org_id(request)` helper for auth.
  - **Verify:** `pytest tests/integration/test_scheduling_v2_routes.py -k bulk` — unauth'd request → 401. Authed request with disabled `scheduling` module → 403 with `{ "detail": "Module 'scheduling' is not enabled for your organisation.", "module": "scheduling" }` (R1.2). Authed request with module enabled → 200 with the documented shape. (R11.1, R11.6, R11.7)
  - **Verify (Pydantic round-trip — GAP-S7):** assert that `BulkScheduleEntryResponse.model_validate(raw_response_dict)` does not drop any keys; the `created` and `conflicts` arrays are typed end-to-end.

- [x] **A6. RBAC enforcement on NEW endpoints only.** Add `dependencies=[require_role("org_admin", "salesperson")]` (varargs, no list, no `Depends()` wrapper — see CODE-GAP-1) to the `POST /bulk` and `POST /copy-week` route decorators only. Import path: `from app.modules.auth.rbac import require_role`. Reference usage: `app/modules/quotes/router.py`.
  - [~] **DO NOT add role guards to the existing single-entry POST/PUT/DELETE endpoints** — they are currently open to any authed user with the `scheduling` module enabled, and tightening them would be a regression for orgs whose `staff_member` users self-create their own entries (R22; CODE-GAP-8). Tightening is parked for a follow-up spec.
  - **Verify:** test logs in as `staff_member` role (NOT "mechanic" — that role does not exist in this codebase; see CODE-GAP-12) → `POST /api/v2/schedule/bulk` → 403. Test as `org_admin` → 200. Test as `salesperson` → 200. The existing `POST /api/v2/schedule` SHALL still accept a `staff_member` request as a regression check. (R1.5, R22)

- [x] **A7. Add date-range filters to `GET /api/v2/leave/approvals`.** The frontend B4 hook needs to fetch approved leave_requests overlapping the visible 14-day window, but the existing endpoint only accepts `status`, `offset`, `limit` (CODE-GAP-5). Extend the endpoint at `app/modules/leave/router.py::list_approval_queue` with two optional query params: `start_lte: date | None = Query(None)` and `end_gte: date | None = Query(None)`. When both are set, add `LeaveRequest.start_date <= start_lte AND LeaveRequest.end_date >= end_gte` to BOTH the count and detail queries (before `_scope_approval_queue`). The role-scoping and confidential-filter pipeline are unchanged.
  - **Backwards-compatible** — existing callers passing only `status` / `offset` / `limit` are unaffected.
  - **Verify:** `pytest tests/integration/test_leave_approvals_dates.py` — seed 3 approved requests at dates `[Jun 1–3, Jun 5–7, Jun 10–12]`, query with `?status=approved&start_lte=2025-06-08&end_gte=2025-06-04` → response `items.length == 2` (Jun 5–7 and Jun 10–12 overlap; Jun 1–3 doesn't because it ends before Jun 4). (R3.7)

## Workstream B — Frontend grid editor

- [x] **B1. Typed API client — `frontend/src/api/schedule.ts`.** Create a thin module wrapping the four endpoints used by the grid:
  - `listEntries({ start, end, staff_id?, signal })` → `GET /api/v2/schedule` → typed `{ entries: ScheduleEntryResponse[], total: number }`
  - `bulkCreate({ entries, signal })` → `POST /api/v2/schedule/bulk` → typed `{ created: ScheduleEntryResponse[], conflicts: BulkConflictItem[] }`
  - `copyWeek({ source_week_start, target_week_start, overwrite_existing, signal })` → `POST /api/v2/schedule/copy-week`
  - `listTemplates({ signal })` → `GET /api/v2/schedule/templates` → typed `{ templates: ShiftTemplateResponse[], total: number }`
  - Every method takes an `AbortSignal` and threads it into `apiClient.{get,post}`. Every response accessor uses `?.` + `?? []` / `?? 0`. **No `as any`** anywhere — every API call must be typed via a generic on the apiClient method (per `.kiro/steering/safe-api-consumption.md` Pattern 5; closes GAP-S9).
  - Types live in `frontend/src/types/schedule.ts` mirrored from the backend Pydantic schemas (manual sync — there is no auto-generated openapi client at the time of writing this spec).
  - **Verify:** `cd frontend && npx tsc --noEmit` passes.
  - **Verify (no `as any`):** `cd frontend && grep -n "as any" src/api/schedule.ts src/types/schedule.ts src/pages/staff-schedule/` returns zero matches.

- [x] **B2. Route registration — `frontend/src/App.tsx`.** Add lazy import + route entry for `/staff-schedule/grid` behind `<RequireAuth>` + the existing scheduling-module gate idiom (look at how `/schedule` is registered — replicate it). Do NOT register a redirect for `/grid` or any other shorter path.
  - **Verify:** browser navigate to `/staff-schedule/grid` → page mounts (with empty grid until B3 lands).

- [x] **B3. Grid skeleton — `frontend/src/pages/staff-schedule/RosterGridPage.tsx`.** Page shell with toolbar (placeholder buttons), Visible_Window state defaulting to `startOfISOWeek(new Date())`, prev/next-fortnight + Today buttons that mutate that state, and a placeholder `<RosterGrid>` body. No data fetching yet.
  - **Verify:** page renders with the toolbar; clicking "Next fortnight" updates a visible date label by 14 days; "Today" resets it. (R2.5, R2.6)

- [x] **B4. Data fetching — `useRosterGridData(visibleWindow, branchId)` hook.** Fetches three things in parallel inside a single `useEffect` with one shared `AbortController`:
  - Active staff (`apiClient.get('/staff', { baseURL: '/api/v2', params: { is_active: true, page_size: 200 }, signal })`). The response shape is `{ staff: StaffMemberResponse[], total: number, page: number, page_size: number, compliance_summary: ... }` (see `app/modules/staff/schemas.py:340`) — read as `res.data?.staff ?? []`. Note: `/api/v2/staff` does NOT accept a `branch_id` query param at the time of writing this spec (CODE-GAP-9). Branch filtering is applied **client-side** by intersecting `staff.location_assignments.location_id` with `branchId` (when set).
  - Schedule entries via the typed `listEntries` from B1.
  - Approved leave_requests overlapping the window via `apiClient.get('/leave/approvals', { baseURL: '/api/v2', params: { status: 'approved', start_lte: window_end_iso_date, end_gte: window_start_iso_date, limit: 500 }, signal })`. The endpoint accepts `start_lte` / `end_gte` per task A7. Response shape is `{ items: LeaveRequestResponse[], total: number }` — read as `res.data?.items ?? []`.
  - Returns `{ staff, entries, leaveByStaffDate, isLoading, error, refetch }` where `leaveByStaffDate` is a `Map<string, Map<string, LeaveOverlay>>` keyed by `staff_id` then `YYYY-MM-DD`.
  - Every state setter uses `?? []`, `?? 0`. The `useEffect` returns `() => controller.abort()`. Errors that aren't `AbortError` / `CanceledError` set `error`; aborts are silent.
  - **Verify:** unit test `frontend/src/pages/staff-schedule/__tests__/useRosterGridData.test.ts` — mocks the three endpoints (staff returns `{ staff: [...] }`, entries returns `{ entries: [...] }`, leave returns `{ items: [...] }`), asserts the hook resolves with merged data, asserts that re-fetching with a new window aborts the previous controller (no warnings about state-after-unmount). (R2.7, R3.7, R16.1, R16.4)

- [x] **B5. `<RosterGrid>` component — staff rows × 14 day columns.**
  - 14 column headers showing `Mon 3 Jun` style labels. Vertical separator between week 1 and week 2 (R2.4).
  - One row per staff. **Client-side sort** by `(s.last_name ?? '').toLowerCase()` then `(s.first_name ?? '').toLowerCase()` — required because `/api/v2/staff` sorts server-side by the legacy `name` column, not `last_name, first_name` (CODE-GAP-10). Row header column shows name + position.
  - Each cell renders the schedule_entries that fall on that staff_id × date. Multi-entry cells stack the blocks vertically; cells with 1 entry show title + time range; empty cells show a hover "+ Add" affordance.
  - Leave-shaded cells render diagonal stripes + the leave_type label and have `aria-disabled="true"` (R3.5).
  - Skeleton state (5×14 grey blocks) while initial fetch is in flight (R2.9).
  - Empty state ("No active staff") when the staff array is empty (R2.8).
  - **All number formatting** uses `(value ?? 0).toLocaleString()` per safe-api-consumption rules.
  - **Verify:** unit test `__tests__/RosterGrid.test.tsx` covers each of: empty staff, populated grid with 3 staff × 14 days × 5 entries, leave-shaded cell render. Property test (fast-check) — for any staff array of length 0–25 and entries array of length 0–100, the rendered DOM contains exactly `staff_count × 14` cells. (R2.1, R2.2, R2.3, R2.8, R2.9, R3.5, R14)
  - **Verify (browser test — GAP-S4):** load `/staff-schedule/grid` in the browser, see the grid render with the org's actual staff and entries, no console errors.

- [x] **B6a. Extend `ScheduleEntryModal` to accept a `defaultValues` prop.** The modal at `frontend/src/pages/schedule/ScheduleEntryModal.tsx` currently exposes only `{ open, onClose, onSave, entry, defaultEntryType }` (CODE-GAP-3). The grid editor's click-to-create flow needs to pre-fill `staff_id`, `start_time`, `end_time` on a brand-new entry. Add an OPTIONAL `defaultValues?: { staff_id?: string; start_time?: string; end_time?: string; entry_type?: string }` prop and wire its values into the existing reset-on-open `useEffect` (the one that runs when `open && !entry`). When `defaultValues` is supplied alongside `entry == null`, the form fields initialise to the defaults instead of empty strings. When `entry` is provided (edit mode), `defaultValues` is ignored.
  - **Do NOT change any existing behaviour** of `ScheduleCalendar` callers — `defaultValues` is purely additive (per `.kiro/steering/no-shortcut-implementations.md`).
  - **Verify:** unit test `frontend/src/pages/schedule/__tests__/ScheduleEntryModal.defaults.test.tsx` — render the modal with `open={true} entry={null} defaultValues={{ staff_id: 'abc', start_time: '2026-06-01T09:00', end_time: '2026-06-01T17:00' }}` and assert the `<select name="staff_id">` and the two `<input type="datetime-local">` inputs are pre-populated. Render with `entry={someEntry}` + `defaultValues={...}` and assert the entry's values win.
  - **Verify (existing tests still pass):** `cd frontend && npx vitest run src/pages/schedule/__tests__/ScheduleEntryModal` (existing suite — no regression).

- [x] **B6. Click-to-create / click-to-edit — wire the existing ScheduleEntryModal.** (Depends on B6a.)
  - Single click on an empty cell → open `<ScheduleEntryModal>` from `frontend/src/pages/schedule/ScheduleEntryModal.tsx` with `entry={null}` and `defaultValues={{ staff_id, start_time: cellDate + workStartTime, end_time: cellDate + workEndTime, entry_type: 'job' }}`. Fall back to `09:00`/`17:00` when the staff has no `availability_schedule[dayKey]`. The `availability_schedule` JSONB shape is `{ "monday": { "start": "09:00", "end": "17:00" }, ... }` per the existing `WorkSchedule` component (ISSUE-046).
  - Single click on a cell with exactly 1 entry → open the modal with `entry=<the entry>` (edit mode).
  - Single click on a cell with >1 entry → render `<CellDisambiguationPopover entries={...} onPick={open-modal-for-it}>` anchored to the cell.
  - On modal save / delete, mutate the in-memory entries cache (do NOT refetch the whole window) — append/replace/remove the affected entry by id (R4.4, R4.5).
  - **Verify:** unit test asserts that clicking an empty cell opens the modal pre-filled with the cell's staff_id + date; clicking a 1-entry cell opens edit mode; clicking a 3-entry cell opens the popover and clicking one of its rows opens edit mode for that entry. (R4.1, R4.2, R4.3)
  - **Verify (browser test — GAP-S4):** in the browser, click an empty cell → modal opens with the right staff and date pre-filled.

- [x] **B7. Drag-resize handle on entry blocks.**
  - Each `<EntryBlock>` renders a 6-px-wide grab handle on its right edge.
  - Pointer-down on the handle starts a drag; pointer-move shows a ghost end_time snapped to the next 15-minute increment between `start_time + 15min` and `min(start_time + 24h, 23:59:59 of cell date)` (R5.6).
  - Pointer-up calls `apiClient.put(\`/schedule/${entry.id}/reschedule\`, { start_time, end_time }, { baseURL: '/api/v2' })`.
  - On 409 → revert the visual change, show a warning toast via `const { addToast } = useToast()` → `addToast('warning', \`Conflicts with "\${conflictingTitle}"\`)`. Import `useToast` from `@/components/ui/Toast` (CODE-GAP-6 — there is no `<Toast variant>` JSX component; the API is `addToast(variant, message, duration?)`).
  - On 422 → revert, show validation message via `addToast('error', detailMessage)`.
  - Use `@dnd-kit/core`'s low-level `useDraggable` + `pointermove` listener — match the existing pattern in `ScheduleCalendar.tsx`. (`@dnd-kit/core` is already in deps at `^6.3.1`.)
  - **Note (CODE-GAP-13):** `ShiftTemplateResponse.start_time` / `end_time` are serialised as `time` (e.g. `"09:00:00"`), not `"09:00"`. Helpers that consume template times must accept both `HH:MM` and `HH:MM:SS` forms.
  - **Verify:** unit test on the `computeResizedEndTime(start, pointerXDelta, pixelsPerHour)` helper — Property test: for any pointer delta in [-1000, 1000] px and any starting hour, the returned end_time is always `start_time + k×15min` for some positive integer `k`, and never crosses midnight of the cell's date. (R5.2, R5.6, R14)
  - **Verify (browser test — GAP-S4):** in the browser, drag a cell's right edge → the entry resizes in 15-min steps, releases save successfully.

- [x] **B8. Template_Palette sidebar — `<TemplatePalette>`.**
  - Renders templates from `listTemplates()`. Empty state: "No shift templates. Create one in Settings → Shift Templates" with a link to `/settings/shift-templates`.
  - Selecting a template sets a `selectedTemplate` context value and toggles `paintMode=true`. Clicking the same template again clears it (R6.10).
  - Visible-only on viewports ≥ 1024px wide (gated by the same media-query as the grid itself per R18.1).
  - **Note (CODE-GAP-13):** template `start_time` / `end_time` arrive as `"HH:MM:SS"` strings. When applying a template to a cell to build a `ScheduleEntryCreate`, parse with a helper that accepts `HH:MM` or `HH:MM:SS` and combine with the cell's date in the org's local timezone.
  - **Verify:** unit test — render with 3 templates → click first → it gets `aria-pressed="true"`; click again → unset. (R6.1, R6.2)
  - **Verify (browser test — GAP-S4):** in the browser, the template palette renders the org's templates and clicking one enters paint mode (cursor changes).

- [x] **B9. Paint_Mode rectangle drag.**
  - In `<RosterGrid>`, when `paintMode=true`, pointer-down on a cell sets `paintAnchor`; pointer-move tracks `paintEnd`; the rectangle `[min(anchor.row, end.row)..max, min(anchor.col, end.col)..max]` highlights every cell inside.
  - Pointer-up computes the cells, filters out ones that already contain a schedule_entry created from the same template on the same date for the same staff (idempotence, R6.7), filters out leave-shaded cells unless Alt was held (R3.6 + R6.8 — but Alt+leave still routes through `<LeaveOverlapConfirmationModal>` before the bulk submit fires).
  - If the resulting cell count > 200 → call `addToast('warning', 'Maximum 200 cells per paint action...')` and do NOT call the API (R6.9). Import `useToast` from `@/components/ui/Toast`.
  - Otherwise build `entries: ScheduleEntryCreate[]` (one per cell, applying template start_time / end_time / entry_type to the cell's date with the staff_id), submit via `bulkCreate(...)`. Optimistic UI per R12 (placeholder entries with `id="optimistic-${uuid()}"` and `status='saving'`).
  - On success → replace placeholders with `created` from the response. On any `conflicts` → remove those placeholders + raise the conflict banner (B14). On 5xx / network → remove all placeholders + `addToast('error', 'Failed to save shifts. Please try again.')`.
  - Pressing Escape exits paint mode without submitting (R6.6).
  - **Verify:** unit test on `computePaintRectangle(anchor, current)` — Property test: for any `(anchor, current)` pair in a 50×14 grid, the returned rectangle is bounded by `[0,49]×[0,13]`, has `count == (rowSpan × colSpan)`, and is order-invariant (anchor at top-left or bottom-right gives the same rectangle). (R6.3, R6.4, R14.4-style bound check)
  - **Verify:** integration test — render grid with 1 template + 1 staff + empty entries → simulate paint of 5-cell horizontal rectangle → mock `bulkCreate` returns `{ created: [...5...], conflicts: [] }` → all 5 cells render the new entry. Re-paint the same rectangle with the same template → no `bulkCreate` call (idempotence, R6.7 + R14.3). (R6.5, R6.7, R12.1, R12.2)
  - **Verify (browser test — GAP-S4):** in the browser, paint a 3×3 rectangle → 9 entries appear with the saving spinner, then resolve to created entries.

- [x] **B10. Multi-select rows + columns + Apply Template.**
  - Click row header → toggle staff_id in `selectedStaff`. Shift+click → range-select between previous click and this one (R7.1, R7.2). Same shape for column headers ↔ `selectedDays` (R7.3, R7.4).
  - When `selectedStaff.size > 0 && selectedDays.size > 0 && selectedTemplate != null`, render the "Apply template" toolbar button (R7.5).
  - Click → submit `bulkCreate` with one entry per `(staff, day)` pair, idempotent on (template, staff, day) (R7.6, R7.7), 200-cell cap (R7.9).
  - Escape clears both sets (R7.8).
  - **Verify:** unit test on the `computeApplyMatrix(selectedStaff, selectedDays, template)` function — Property test: result length is `selectedStaff.size × selectedDays.size` minus matches in the existing entries cache; never exceeds 200 unless an explicit override is requested (none is). (R7, R14)

- [x] **B11. Copy Week 1 → Week 2 button.**
  - Toolbar button "Copy Week 1 → Week 2" opens `<CopyWeekConfirmModal>` with counts of source entries and existing target entries fetched from the in-memory cache.
  - On confirm → `copyWeek({ source_week_start: visibleWindow.start, target_week_start: addDays(visibleWindow.start, 7), overwrite_existing: modal.overwrite })`.
  - Optimistic placeholders for the source entries with `+7d` shifted times (R12.1).
  - On response → call `useToast().addToast('success', \`Copied \${created.length} entries, skipped \${conflicts.length} due to conflicts.\`)`. Replace placeholders with `created`; if conflicts, raise banner.
  - **Verify:** unit test mocks `copyWeek` returning `{ created: [...3...], conflicts: [...1...] }` → assert `addToast` called with `('success', 'Copied 3 entries, skipped 1 due to conflicts.')`. (R8.8)
  - **Verify (browser test — GAP-S4):** in the browser, click "Copy Week 1 → Week 2" → confirm dialog appears with counts → confirm → toast shows summary → week 2 cells populate.

- [x] **B12. Cell clipboard (Ctrl+C / Ctrl+V).**
  - Page-level keydown listener (only when the grid has focus — guard via `document.activeElement?.closest('[role="grid"]')`).
  - `Ctrl+C` (or `Cmd+C`) on focused cell with ≥1 entry → set `cellClipboard = { entries: [{ entry, dx: 0, dy: 0 }, ...] }`.
  - `Ctrl+C` while a multi-cell selection rectangle is active → copy every entry inside, with `dx`/`dy` offsets relative to the rectangle's top-left.
  - `Ctrl+V` on focused cell → submit `bulkCreate` with each clipboard item shifted by the focused cell's date + `dx` days × 1, scoped to the focused cell's staff_id + the offset row.
  - `cellClipboard` lives in component state — does NOT touch `navigator.clipboard` (R9.4).
  - **Verify:** unit test on `shiftClipboardToFocusCell(clipboard, focus)` — Property test: for any clipboard with N items and any focus cell, the resulting entries preserve `entry_type, title, description, (end_time - start_time)`, and only `start_time`, `end_time`, `staff_id` shift by the offset. (R9, R14.2-style)

- [x] **B13. Keyboard navigation — `useGridKeyboardNav(rows, cols, focusedCell, setFocusedCell)`.**
  - Cells are `role="gridcell"`. The grid container is `role="grid"`. Only the focused cell has `tabindex=0`.
  - ArrowRight/Left/Up/Down — clamped to grid bounds (R10.2-R10.5).
  - Tab — exits the grid to the next focusable element (R10.6) — implemented by NOT preventing the default Tab behaviour but by ensuring only one cell has `tabindex=0`.
  - Enter on a focused cell → same as `<RosterGrid>` `onCellClick` (R10.7).
  - Delete/Backspace on a focused cell → if 1 entry, inline confirm + `DELETE /api/v2/schedule/{id}`; if >1, open the disambiguation popover with delete buttons (R10.8, R10.9).
  - Shift+Arrow extends the multi-cell selection rectangle (R10.10).
  - **Verify:** Property test on the navigation reducer — for any sequence of arrow keypresses starting from any cell in a 50×14 grid, the resulting focused cell is always in `[0,49]×[0,13]`. (R10, R14.4 — Property P4)

- [x] **B14. Conflict warning banner — `<ConflictBanner conflicts={...} onScrollToCell={...} onDismiss={...}>`.**
  - Persistent (no auto-dismiss, R13.5).
  - Each conflict row shows `(staff_name, date, attempted_time_range, conflicting_titles)` and is clickable → scrolls grid + sets focus on the cell (R13.3).
  - Conflict cells get `data-conflict="true"` → red outline via Tailwind `outline outline-red-500` selector (R13.2).
  - Dismiss button clears state + outlines (R13.4).
  - **Verify:** unit test renders banner with 3 conflicts → click first → assert grid `scrollTo` called with the right cell coords + `focus()` on that cell. Click dismiss → banner hidden, no `data-conflict` cells remain. (R13)
  - **Verify (browser test — GAP-S4):** in the browser, paint a rectangle that overlaps an existing entry → banner appears, click conflict row → grid scrolls + outlines turn red, dismiss → outlines clear.

- [x] **B15. CSV export.**
  - Toolbar "Export CSV" button calls `generateRosterGridCSV(visibleWindow, staff, entries, leaveByStaffDate)` and triggers a `<a download>` blob download.
  - Header row: `staff_name,position,YYYY-MM-DD (Mon),YYYY-MM-DD (Tue),...,YYYY-MM-DD (Sun)` for 14 days (R15.2).
  - Each cell value: empty string for empty cells; `LEAVE: <leave_type_label>` for leave-shaded cells; otherwise a comma-free, semicolon-separated `HH:MM-HH:MM Title` string sorted by start_time (R15.3).
  - RFC 4180 escaping for embedded `"`, `,`, `\n` (R15.4).
  - **Verify:** unit test `generateRosterGridCSV.test.ts` — Property test: round-trips through `parse(generate(rows)) == rows` for any rows containing arbitrary unicode + commas + quotes + newlines. (R15.4)

- [x] **B16. Print stylesheet.**
  - Toolbar "Print" button calls `window.print()`.
  - `RosterGridPage.module.css` (or inline `<style>`) defines `@media print { @page { size: A3 landscape; margin: 10mm; } [data-no-print] { display: none; } body { background: white; color: black; } }` plus rules to compress cell padding and ensure 14 columns + a row-header column fit on one A3 landscape page (R15.5, R15.6).
  - Toolbar, palette, filters all carry `data-no-print` so they vanish when printing.
  - **Verify:** manual — open the page, hit Ctrl+P, confirm the preview shows only the grid on a landscape page. (R15.5, R15.6 — manual gate, no automated assertion needed.)

- [x] **B17. Branch + position filters — `<RosterGridFilters>`.**
  - Branch filter pulls from existing `BranchContext` (`{ selectedBranchId, branches }`). Changing the branch filters the existing in-memory staff array client-side by intersecting `staff.location_assignments[*].location_id` with the selected branch (R3.3 — server-side `branch_id` filtering on `/api/v2/staff` is parked per CODE-GAP-9).
  - Position filter — populated from `[...new Set(staff.map(s => s.position).filter(Boolean))]` after staff load. Changing it filters the existing rows client-side (R3.4) — does NOT refetch.
  - **Verify:** unit test asserts that switching branch filters the rendered rows in-memory (no refetch); switching position filters in-memory only. Assert no extra `apiClient.get('/staff', ...)` call is made when the branch filter changes.

- [x] **B18. Mobile fallback banner.**
  - On mount, if `window.matchMedia('(min-width: 1024px)').matches === false`, render `<MobileFallback>` showing the info message + a button linking to `/schedule`. Skip the entire grid render below the threshold (R18.1, R18.2).
  - Listen to the `change` event on the media query so resizing past the threshold reveals the grid live (matches the pattern in `ScheduleCalendar.tsx` `useIsMobile` hook).
  - **Verify:** unit test sets `window.innerWidth = 800` + mocks `matchMedia` → grid is not rendered, fallback banner is.

- [x] **B19. "Grid view" toggle button on existing pages.**
  - Touch `frontend/src/pages/scheduling/StaffSchedule.tsx` — add a `<Link to="/staff-schedule/grid">Grid view</Link>` button next to the existing "Add Shift" button (R1.3).
  - Touch `frontend/src/pages/schedule/ScheduleCalendar.tsx` — add the same link in the toolbar (the desktop-only controls row). Only render the link when the viewport is ≥ 1024px wide (suppress the link on mobile to avoid a navigation that lands on the fallback banner).
  - **Verify:** browser test — navigate to `/staff-schedule` → see "Grid view" button → click → land on `/staff-schedule/grid` (R1.3, R1.4).

- [x] **B20. Loading + error UX polish.**
  - While the bulk submit is in flight, disable the Template_Palette, Apply-template button, Copy-week button, paint-mode capture, and Ctrl+V handler (R12.5). Use `disabled` attribute + a `aria-busy="true"` on the grid container.
  - Saving placeholders render with a `class="opacity-60 animate-pulse"` Tailwind combo (visual saving state, R12.1).
  - Network/5xx → `useToast().addToast('error', 'Failed to save shifts. Please try again.')` with a retry action that re-runs the original call (R12.4, R21.7).
  - HTTP 401 → handled by the existing axios interceptor (redirects to login).
  - HTTP 403 with `module: 'scheduling'` → render module-disabled empty state (R21.2).
  - HTTP 403 without module key → redirect to `/dashboard` (R21.3 + R1.5).
  - HTTP 422 → `addToast('error', detailMessage)` with the validation message from the response (R21.5).
  - Aborted requests → silent (R21.8).
  - **Verify:** unit test — mock `bulkCreate` to never resolve → palette + apply button get `disabled`; on resolve they re-enable. Mock to reject with 500 → assert `addToast('error', ...)` is called. Mock to reject with 422 detail → assert the detail message is shown.

## Workstream C — Property tests (centralised)

- [x] **C1. `frontend/src/pages/staff-schedule/__tests__/properties.test.ts` — fast-check property suite.**
  - **P1**: `bulkCreateLocalShape(N)` — for any N in [1, 200], the local request builder returns an entries array of length N; for N in [0, ∞) outside that, the helper throws `BulkCellCapError`. (Backend cardinality is verified separately in A2.)
  - **P2**: `copyWeekShift(entry, +7d)` produces an entry with identical `entry_type/title/description/notes` and `start_time`/`end_time` shifted by exactly 7 days. (Verifies the client-side assertion that mirrors the backend invariant.)
  - **P3**: `paintIdempotenceFilter(rectangle, existingEntries, template)` — re-running with the same args twice returns an empty entries array on the second call.
  - **P4**: `gridKeyboardReducer(state, key)` — for any sequence of keys in `{ArrowLeft, ArrowRight, ArrowUp, ArrowDown}`, the resulting `(row, col)` is in `[0, R) × [0, C)` for any `R ∈ [1, 100], C = 14`.
  - **Verify:** `cd frontend && npx vitest run src/pages/staff-schedule/__tests__/properties.test.ts` — all four properties pass with default `numRuns=200`.

- [x] **C2. `tests/test_scheduling_v2_bulk_property.py` — Hypothesis property suite.** (Flat path; `tests/property/` does not exist in this repo — see CODE-GAP-7. Hypothesis tests live as `tests/test_*_property.py` or `tests/test_*_properties.py` — see e.g. `tests/test_quote_cancellation_properties.py`.)
  - **P5**: For any `entries` list of size [1, 200] with arbitrary `(staff_id, start_time, duration_minutes)` tuples, `bulk_create` returns a response where `len(created) + len(conflicts) == len(entries)` and `len(created) ≤ len(entries)`. (R14.1)
  - **P6**: For `copy_week` over an arbitrary set of source entries, every created entry preserves duration and metadata per R14.2.
  - **Verify:** `pytest tests/test_scheduling_v2_bulk_property.py -q` — both strategies pass with `--hypothesis-profile=ci` (or default if no ci profile is registered).

## Workstream D — Performance + verification

- [x] **D1. Render-time benchmark.**
  - Vitest microbench (or a plain `console.time` block in a `__tests__/perf.test.ts` skipped in CI but runnable locally) — render the grid with 50 staff × 700 entries → assert `< 1000ms` from prop change to commit using `react-test-renderer.create().toJSON()` time. (R19.1)
  - **Verify:** locally — `npx vitest run src/pages/staff-schedule/__tests__/perf.test.ts` and read the timing log; track the number in the PR description.

- [x] **D2. Row virtualisation when staff > 100 — CSS `content-visibility: auto`.**
  - The spec originally considered `@tanstack/react-virtual`, but it is **not** in `frontend/package.json` (CODE-GAP-4). To keep the dependency footprint stable, the default path is the CSS-only strategy: when `staff.length > 100`, apply `style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 56px' }}` (or the appropriate per-row height) to each row wrapper. Browsers skip layout/paint for off-screen rows automatically.
  - Do NOT pull in `@tanstack/react-virtual` — keep the dep footprint stable for this spec.
  - **Verify:** unit test renders with 250 staff → asserts every row has `style.contentVisibility == 'auto'` (browser will skip rendering off-screen rows; we assert the CSS hint is set, not the actual paint behaviour).
  - **Verify (no new dep):** `cd frontend && grep -r "@tanstack/react-virtual" src/pages/staff-schedule` returns no matches; `grep "@tanstack/react-virtual" package.json` returns no matches.

- [x] **D3. Backend bulk timing test.**
  - `pytest tests/integration/test_scheduling_v2_bulk_perf.py` — seed 200 entries, time the `bulk_create` service call → assert `< 5s` p99 across 5 runs. Run with `pytest --durations=10` to track timing. Skipped in CI by default (decorate with `@pytest.mark.perf` and gate behind `RUN_PERF=1`). (R19.4)

- [x] **D4. End-to-end Python script — `scripts/test_roster_grid_editor_e2e.py`.** Per `.kiro/steering/feature-testing-workflow.md` (closes GAP-S2). Emulates the full user flow inside the app container. The script MUST follow the structure documented in the steering doc: `passed/failed` counters, per-step log lines, mandatory cleanup of every created resource, and OWASP A1 checks.
  - Steps:
    1. Login as the seeded `org_admin` user (uses `demo@orainvoice.com` / `demo123` per the steering doc reference accounts).
    2. `GET /api/v2/schedule?start=...&end=...` — confirm the response shape `{ entries: [...], total: N }`.
    3. `GET /api/v2/schedule/templates` — confirm at least one template exists (or seed one for the test).
    4. `POST /api/v2/schedule/bulk` with 5 entries — confirm 5 in `created`, 0 in `conflicts`.
    5. Re-submit the same 5 entries — confirm 5 in `conflicts` (idempotence check, R14.3).
    6. `POST /api/v2/schedule/copy-week` — confirm response shape and that target-week entries appear.
    7. `POST /api/v2/schedule/bulk` as a `staff_member` user — expect 403 (R1.5 / OWASP A1).
    8. `POST /api/v2/schedule/bulk` with `scheduling` module disabled — expect 403 with `module: 'scheduling'` (R1.2).
    9. `POST /api/v2/schedule/bulk` with cross-org `org_id` in the payload — confirm the inserted rows use the resolved org_id, NOT the payload's (R11.9 / OWASP A1).
    10. Cleanup — every created entry deleted via `DELETE /api/v2/schedule/{id}` in a `finally` block. Names prefixed `TEST_E2E_RosterGrid_*`. Verify zero `TEST_E2E_RosterGrid_*` entries remain after cleanup.
  - **Verify:** `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python scripts/test_roster_grid_editor_e2e.py` exits 0.

## Workstream E — Versioning + docs

- [x] **E1. Bump app version.**
  - `pyproject.toml` 1.17.0 → 1.18.0 (CONFIRMED current = 1.17.0 — see `pyproject.toml:3`; CODE-GAP-8 in original spec referenced 1.13.0 which was stale steering text).
  - `frontend/package.json` 1.17.0 → 1.18.0.
  - `mobile/package.json` 1.17.0 → 1.18.0 (informational; mobile isn't shipping changes for this feature, but per `.kiro/steering/versioning-and-changelog.md` all three packages must match).
  - **Verify:** `grep -E "\"?version\"?\s*[:=]\s*\"1\\.18\\.0\"" pyproject.toml frontend/package.json mobile/package.json` returns three matches.

- [x] **E2. CHANGELOG entry.**
  - Append a `## [1.18.0]` section to `CHANGELOG.md` summarising: roster grid editor at `/staff-schedule/grid`, bulk and copy-week endpoints, paint mode, multi-select, keyboard nav, CSV + landscape A3 print, mobile fallback below 1024px.
  - **Verify:** `head -30 CHANGELOG.md` shows the new section above the previous most recent.

- [x] **E3. Update `.kiro/specs/roster-grid-editor/.config.kiro` to mark workflow complete.**
  - Add `"workflowState": "tasks-ready"` (or whatever the project's existing config-state convention is — investigate `.config.kiro` files in shipped specs first).

## Pre-merge gate

Tick everything below before opening the PR. Anything left unticked moves to `gap-analysis.md` with a one-paragraph reason AND a row in `docs/ISSUE_TRACKER.md`.

- [ ] All Workstream A unit + integration tests pass; backend coverage on `app/modules/scheduling_v2/` does not regress vs `main`.
- [ ] All Workstream B unit + render tests pass; `cd frontend && npx tsc --noEmit` is clean for the new files.
- [ ] Workstream C property tests pass (front + back).
- [ ] Workstream D performance budgets met or formally deferred in `gap-analysis.md` with a target ticket id.
- [ ] **D4 e2e script** — `python scripts/test_roster_grid_editor_e2e.py` runs end-to-end with zero `TEST_E2E_RosterGrid_*` rows remaining after cleanup (GAP-S2).
- [ ] Module gating verified manually — disabling `scheduling` for an org returns 403 from every new endpoint AND the `/staff-schedule/grid` route renders the disabled-module empty state.
- [ ] RBAC verified manually — `staff_member` role gets 403 from the NEW bulk endpoints (NOT the existing single-entry endpoints — those retain pre-spec behaviour per R22). Org_admin/salesperson get 200. Existing `POST /api/v2/schedule` still accepts `staff_member` (regression check; CODE-GAP-12).
- [ ] Audit log inspection — running a paint of 5 cells produces exactly one `audit_log` row with `action='schedule.bulk_created'` (NOT `event_type=`; CODE-GAP-2) and **no per-entry payload** in `after_value`.
- [ ] Idempotence verified manually — paint a 5-cell rectangle, paint the same rectangle again with the same template → no second batch of creates, no API call.
- [ ] Conflict UX verified manually — paint over an existing entry → banner appears with red-outlined cell, click banner row → grid scrolls + cell focused, dismiss banner → outline cleared.
- [ ] CSV round-trip verified manually with an entry whose title contains `"`, `,`, and `\n` — exported file passes RFC 4180 parser cleanup.
- [ ] Print preview verified manually on Chrome desktop — A3 landscape, toolbar/palette/filters hidden, 14 columns + row header fit one page.
- [ ] Mobile fallback verified manually at 800px viewport.
- [ ] Toast API — `grep -r "<Toast variant" frontend/src/pages/staff-schedule` returns zero matches (CODE-GAP-6 — the only correct API is `useToast().addToast(variant, message)`).
- [ ] No `as any` — `cd frontend && grep -rn "as any" src/api/schedule.ts src/types/schedule.ts src/pages/staff-schedule/` returns zero matches (GAP-S9).
- [ ] No `@tanstack/react-virtual` — `grep "@tanstack/react-virtual" frontend/package.json` returns no matches (CODE-GAP-4).
- [ ] CHANGELOG + version bump committed; all three package files at `1.18.0`.

## Open questions / parked decisions

None at the time of writing. Add here as they surface during implementation.

## Deployment notes

Per `.kiro/steering/deployment-environments.md`, this feature deploys via the standard Pi prod pipeline:

1. Push to GitHub `main`.
2. `ssh nerdy@192.168.1.90 "cd ~/invoicing && git pull origin main"`.
3. Backend rebuild (auto-runs `alembic upgrade head` — but this spec adds **zero** migrations, so no schema changes hit prod): `docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate app`.
4. Frontend rebuild — MUST delete `invoicing_frontend_dist` volume to clear cached chunks: `docker compose stop frontend nginx && docker compose rm -f frontend nginx && docker volume rm invoicing_frontend_dist && docker compose up -d --build frontend nginx`.
5. Permissions fix: `chmod -R 755 /app/dist/assets` inside the frontend container.
6. Flush Redis to clear cached module-enablement maps: `docker compose exec redis redis-cli FLUSHALL`.
7. Verify in browser at `http://192.168.1.90:8999/staff-schedule/grid` — confirm grid loads with the org's actual scheduling data.

No Pi-specific code paths required. The version bump in E1 is the only Pi-prod-visible change beyond the new endpoints + page.
