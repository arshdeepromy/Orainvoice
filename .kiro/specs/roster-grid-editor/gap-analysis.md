# Roster Grid Editor — Gap Analysis

Generated as a pre-implementation audit pass over `requirements.md` + `tasks.md` against `.kiro/steering/*` and the actual codebase. Every gap is labelled `GAP-S<N>` (steering) or `CODE-GAP-<N>` (code) and is followed by **how it was closed** (an exact change made to `requirements.md` and/or `tasks.md`).

The spec was written against an outdated `project-overview.md` ("App version: 1.13.0"). The repo is actually at **1.17.0** across `pyproject.toml`, `frontend/package.json`, and `mobile/package.json`. The version bump targets in workstream E have been corrected to **1.17.0 → 1.18.0**.

---

## Pass 1 — Steering-doc gap analysis

### Inapplicable steering docs (skipped)

- **catalogue-reference-architecture.md** — inventory/catalogue domain only.
- **dashboard-widget-gating.md** — fileMatch only loads inside `dashboard/widgets/**`.
- **database-migration-checklist.md** — the spec adds zero migrations; `schedule_entries` and `shift_templates` already exist (migration 0037 / Req 57 era).
- **design-reference-from-screenshots.md** — `inclusion: manual`, no screenshots provided.
- **integration-credentials-architecture.md** — no third-party API keys.
- **large-file-generation.md** — applies to spec authoring, not implementation.
- **setup-guide-for-new-modules.md** — `scheduling` module is already registered with a `setup_question`.
- **trade-specific-catalogue-inventory.md** — fileMatch on catalogue/inventory.
- **vehicle-carjam-module-gating.md** — vehicle gating, not relevant to roster.
- **windows-shell-and-docker.md** — repo is Ubuntu/bash, not Windows; relevant deploy info is in `deployment-environments.md`.

### Steering gaps applied

- **GAP-S1: Trade-family gating not declared** — `trade-family-gating-for-new-features.md` requires every new feature to declare which trade family it serves. — **Fix**: Added Requirement R20 (universal — all trade families with the `scheduling` module) and noted in tasks.md preamble. Roster grid is universal because the `scheduling` module is universal across trade families and uses no trade-specific concepts (no `vehicles`, no `parts`).

- **GAP-S2: No end-to-end Python test script** — `feature-testing-workflow.md` mandates `scripts/test_<feature>_e2e.py`. — **Fix**: Added task **D4** in workstream D and a verify line in the pre-merge gate. Script exercises login → grid load → paint → conflict → CSV export → cleanup, and tests RBAC + module-gate per OWASP A1.

- **GAP-S3: Spec didn't reference the issue tracker** — `issue-tracking-workflow.md` requires every implementation failure to land in `docs/ISSUE_TRACKER.md`. — **Fix**: Updated tasks.md "Failure handling" line to require the failure detail land in BOTH `gap-analysis.md` AND a new `ISSUE-XXX` row in `docs/ISSUE_TRACKER.md` per the steering doc.

- **GAP-S4: Implementation-completeness rule 1 not followed** — `implementation-completeness-checklist.md` requires browser testing of frontend tasks before marking complete. — **Fix**: Added a "Browser test" sub-bullet to every Workstream B task that ships visible UI (B3, B5, B6, B7, B9, B10, B11, B14, B15, B16, B17, B18, B19, B20).

- **GAP-S5: Spec-completeness — error UI not enumerated** — `spec-completeness-checklist.md` §7 requires explicit error-state UI per HTTP code. — **Fix**: Added Requirement R21 (Error & loading state UI) covering 401/403/404/409/422/5xx + network error + abort.

- **GAP-S6: Performance-and-resilience rule 1 (transactions)** — `performance-and-resilience.md` rule 1 says never mix manual `db.rollback()` with the session context manager; use `begin_nested()`. — **Fix**: Tasks.md A2 already uses `async with self.db.begin_nested()`; added an explicit note that the router MUST NOT call `db.commit()` or `db.rollback()` (the `get_db_session` `session.begin()` context manager handles both), referencing ISSUE-044 in the issue tracker.

- **GAP-S7: Frontend-backend contract — Pydantic schema gate (Rule 8)** — when adding fields to a service dict, the Pydantic response schema MUST be updated or the field is silently dropped. — **Fix**: Added a verify step on A2 / A3 / A5 that asserts the bulk + copy-week responses round-trip through the Pydantic schemas without losing the new keys.

- **GAP-S8: Versioning targets** — spec planned 1.17.0 → 1.18.0 but referenced "1.13.0" inherited from a stale `project-overview.md`. The repo is at 1.17.0 today. — **Fix**: Confirmed 1.17.0 → 1.18.0; verify line in E1 grep-checks all three package files for `1.18.0`.

- **GAP-S9: Safe API consumption — no `as any`** — `safe-api-consumption.md` Pattern 5 forbids `as any` on responses. — **Fix**: Added explicit "no `as any`" verify line on B1 (typed API client), and required every `apiClient.get/put/post` to use a generic.

- **GAP-S10: Deployment environments** — `deployment-environments.md` documents that Pi prod prod runs on port 8999 + ARM64 with `git pull`-based deploys. — **Fix**: Added a "Deployment notes" section at the end of tasks.md noting that Pi prod deploys are out-of-scope for this PR (frontend-rebuild + Redis flush procedure documented), but the version bump in E1 will land on Pi prod via the standard pipeline; no Pi-specific code paths needed.

- **GAP-S11: No-shortcut implementations** — rule 4 says any change that replaces a component's rendering approach must go through a spec. — **Fix**: Confirmed the existing `ScheduleCalendar` and `StaffSchedule` pages are NOT modified by this spec — only a "Grid view" link is added (B19). Documented in tasks.md preamble.

- **GAP-S12: Mobile-app gating** — the spec correctly observed mobile is not in scope; verified by `fileSearch` returning no `mobile/src/screens/**roster|**schedule` matches. — **Fix**: No code change. Confirmed in CODE-GAP-14.

---

## Pass 2 — Code-assumption verification

| # | Assumption | Verdict | Evidence |
|---|------------|---------|----------|
| 1 | `SchedulingService.detect_conflicts(org_id, staff_id, start_time, end_time, *, exclude_entry_id=None)` exists | **YES** | `app/modules/scheduling_v2/service.py:217` |
| 2 | `MODULE_ENDPOINT_MAP['/api/v2/schedule'] = 'scheduling'` | **YES** | `app/middleware/modules.py:46` |
| 3 | Role-guard idiom `Depends(require_role(...))` | **PARTIAL** | `app/modules/auth/rbac.py:246` — `require_role(*allowed_roles)` is varargs, used directly in `dependencies=[require_role(...)]` (no wrapping `Depends()`); spec used a list literal `[...]` |
| 4 | `write_audit_log(...)` exists | **PARTIAL** | `app/core/audit.py:35` — first kwarg is `action`, **not** `event_type` |
| 5 | `ScheduleEntryModal` accepts `defaultValues` | **NO** | `frontend/src/pages/schedule/ScheduleEntryModal.tsx:39` — props are `{ open, onClose, onSave, entry, defaultEntryType }`. No `defaultValues`. |
| 6 | `@dnd-kit/core` in deps | **YES** | `frontend/package.json:14` `^6.3.1` |
| 6b | `@tanstack/react-virtual` in deps | **NO** | grep returns no matches; the spec's D2 fallback to `content-visibility: auto` is the right path |
| 7 | `fast-check` in devDeps | **YES** | `frontend/package.json:39` `^4.6.0` |
| 8 | `RequireAuth` wrapper + scheduling-module gate | **YES** | `frontend/src/App.tsx:263` `RequireAuth`; existing `/schedule` route nests `<ModuleRoute moduleSlug="scheduling">` inside `<RequireAuth>` |
| 9 | Leave endpoint accepts `start_lte` / `end_gte` | **NO** | `app/modules/leave/router.py:786` `/api/v2/leave/approvals` accepts only `status, offset, limit`; per-staff `list_staff_requests:543` accepts only `status, offset, limit`. **No date params.** |
| 10 | `BranchContext` exposes `selectedBranchId, branches` | **YES** | `frontend/src/contexts/BranchContext.tsx:18` |
| 11 | `apiClient` import path `@/api/client` | **YES** | default export from `frontend/src/api/client.ts` |
| 12 | `staff_members.position` column exists | **YES** | `app/modules/staff/models.py:66` `String(100), nullable=True` |
| 13 | Frontend `useToast` API | **PARTIAL** | `frontend/src/components/ui/Toast.tsx:80` — `addToast(variant, message, duration?)`, NOT a `<Toast variant>` JSX component. Spec referenced `<Toast variant="warning">` which doesn't exist. |
| 14 | Mobile bundle ships no roster screen | **YES** | `fileSearch` for `mobile/src/screens/**[Rr]oster|**[Ss]chedule` returns zero results |
| 15 | `staff_members.availability_schedule` JSONB shape | **YES** | `app/modules/staff/models.py:84` JSONB; per ISSUE-046 the keys are `monday..sunday` mapping to `{start, end}` |
| 16a | `tests/property/` directory exists | **NO** | `fileSearch` for `tests/property` returns nothing. All existing hypothesis tests live at `tests/test_*.py` (flat). |
| 16b | `hypothesis` available in dev deps | **YES** | `pyproject.toml:39` `hypothesis>=6.151.12` |
| 17 | `audit_log` (singular) table name | **YES** | `app/modules/admin/models.py:318` `__tablename__ = "audit_log"` |
| 18 | Existing `POST /api/v2/schedule` has a role guard | **NO** | `app/modules/scheduling_v2/router.py` has zero `dependencies=[require_role(...)]` decorators. The single-entry endpoints are open to any authed user with the `scheduling` module enabled. **Adding a role guard now would be a regression** for any existing org calling the v2 schedule API without the org_admin/salesperson role. |

### Bonus assumptions surfaced during verification

| # | Assumption | Verdict | Evidence |
|---|------------|---------|----------|
| 19 | `GET /api/v2/staff` accepts `branch_id` query param | **NO** | `app/modules/staff/router.py:236` and `service.py:66` accept only `page, page_size, role_type, is_active`. No `branch_id`. The spec's B4 plan to call `?branch_id=...` will silently ignore the filter. |
| 20 | `/api/v2/staff` sorts by `last_name, first_name` | **NO** | `service.py:88` sorts by `StaffMember.name` (the legacy combined column). The spec's R2.2 ordering will not be honoured by the server. |
| 21 | `StaffMemberListResponse` returns `staff: [...]` not `items: [...]` | **YES** | `app/modules/staff/schemas.py:340` — the existing schema names the array `staff`, not `items`. The spec's B4 hook must read `res.data?.staff ?? []`. |

### CODE-GAPs raised and how they were closed

- **CODE-GAP-1 (Assumption 3): Role-guard varargs vs list literal** — `require_role` takes positional varargs (`*allowed_roles: str`). — **Fix**: Updated tasks.md A6 and the new A7 to use `dependencies=[require_role("org_admin", "salesperson")]` (varargs, no list, no `Depends()` wrapper — matches the canonical usage in `app/modules/quotes/router.py`).

- **CODE-GAP-2 (Assumption 4): `write_audit_log` kwarg is `action` not `event_type`** — — **Fix**: Updated A4 in tasks.md and Requirement R17.3 in requirements.md to call `write_audit_log(... action="schedule.bulk_created", entity_type="schedule_entry", entity_id=None, before_value=None, after_value={...})`. Removed all references to `event_type=` and replaced with `action=`.

- **CODE-GAP-3 (Assumption 5): `ScheduleEntryModal` does not accept `defaultValues`** — props are `{ open, onClose, onSave, entry, defaultEntryType }` only. — **Fix**: Added a new task **B6a** (extend the modal) BEFORE B6 (use the modal). B6a adds an optional `defaultValues?: Partial<ScheduleEntryCreate>` prop that pre-fills the form when `entry` is null. Updated B6 to depend on B6a. Tests for B6a pinned to a small property test that asserts the form fields equal the defaults when the modal opens.

- **CODE-GAP-4 (Assumption 6b): `@tanstack/react-virtual` not installed** — already addressed by D2's fallback. — **Fix**: D2 task description updated to make the fallback the **default** path: virtualisation via `content-visibility: auto` per row. The optional pull-in of `@tanstack/react-virtual` is dropped from the spec to keep the dependency footprint stable. Verify line updated to assert no `@tanstack/react-virtual` import in the new files.

- **CODE-GAP-5 (Assumption 9): Leave endpoint missing date-range params** — neither `/api/v2/leave/approvals` nor `/api/v2/staff/{id}/leave/requests` accepts `start_lte` / `end_gte`. **Trade-off considered:** building a new endpoint, OR adding query params, OR client-side filtering of a broader query. The simplest correct fix is **add `start_lte` and `end_gte` query params to the existing approval queue endpoint**, since the org-wide approval queue is the only org-scoped read path and adding optional date-range filters is non-breaking for existing clients. — **Fix**: Added new backend task **A7** to extend `/api/v2/leave/approvals` with optional `start_lte: date | None` and `end_gte: date | None` query params (filter `LeaveRequest.start_date <= start_lte AND LeaveRequest.end_date >= end_gte`). Updated B4 in tasks.md to use `/api/v2/leave/approvals?status=approved&start_lte=...&end_gte=...` and to read `res.data?.items ?? []`. Updated Requirement R3.7 to point at the approvals endpoint instead of a generic "leave_requests endpoint".

- **CODE-GAP-6 (Assumption 13): `useToast` API** — `addToast(variant, message)` not `<Toast variant=...>`. — **Fix**: Replaced every `<Toast variant="warning">...` reference in tasks.md with `addToast('warning', '...')` and added the import line `import { useToast } from '@/components/ui/Toast'` to the relevant tasks (B7, B11, B14, B20).

- **CODE-GAP-7 (Assumption 16a): `tests/property/` directory does not exist** — existing hypothesis tests live flat in `tests/`. — **Fix**: Updated C2 to put the new property test at `tests/test_scheduling_v2_bulk_property.py` (flat, naming convention matches `tests/test_invoice_properties.py`, `tests/test_quote_cancellation_properties.py`, etc.). Removed the `mkdir tests/property` step and the verify command was changed to `pytest tests/test_scheduling_v2_bulk_property.py -q`.

- **CODE-GAP-8 (Assumption 18): Existing single-entry endpoints have no role guard** — adding `dependencies=[require_role(...)]` to the existing `POST /api/v2/schedule`, `PUT /api/v2/schedule/{id}`, `DELETE /api/v2/schedule/{id}` would be a regression for any org that currently relies on the open-by-module-gate behaviour (e.g. `staff_member` users creating their own entries). — **Fix**: Marked **A6 sub-bullet "and on the existing single-entry endpoints" as `[~]`** with a reason. The new bulk + copy-week endpoints DO get the role guard (R1.5 still holds). The frontend already checks role before rendering the grid editor; the back-end check is restricted to the bulk paths added by this spec. Added requirement R22 to make this scope explicit ("existing single-entry endpoints retain their pre-spec role policy").

- **CODE-GAP-9 (Assumption 19): `/api/v2/staff` does not accept `branch_id` filter** — calling `?branch_id=...` is silently ignored. — **Fix**: Updated B4 to drop the `branch_id` query param. Branch filtering is now applied client-side using the `staff_locations` data already loaded for staff (out-of-scope deferred — see open question). For the initial release, the branch filter is **org-wide only when the user has access to all branches** and **scoped to the user's `branch_ids`** when they don't. The R3 acceptance criteria are updated to reflect this. A follow-up backend task is logged in `gap-analysis.md` to add `branch_id` server-side filtering to `/api/v2/staff` if perf becomes a problem.

- **CODE-GAP-10 (Assumption 20): `/api/v2/staff` sort order is `name`, not `last_name, first_name`** — server returns the wrong order vs spec R2.2. — **Fix**: B5 / RosterGrid sorts the staff array client-side by `(s.last_name ?? '').toLowerCase()` then `(s.first_name ?? '').toLowerCase()` after the fetch returns. R2.2 unchanged — the sort order is preserved at the UI layer.

- **CODE-GAP-11 (Assumption 21): `/api/v2/staff` returns `staff: [...]` not `items: [...]`** — — **Fix**: B4 updated to read `res.data?.staff ?? []`. The typed API client in B1 already references `StaffMemberListResponse` which uses `staff` not `items` — confirmed in `app/modules/staff/schemas.py:340`.

- **CODE-GAP-12: "mechanic" role does not exist** — A6's verify step said `"test logs in as `mechanic` role → 403"` but the project's role enum is `{global_admin, franchise_admin, org_admin, branch_admin, location_manager, salesperson, staff_member, kiosk}`. There is no `mechanic`. — **Fix**: Replaced "mechanic" with `staff_member` in A6's verify step (the next-lowest org role). Same fix in the pre-merge gate.

- **CODE-GAP-13: ShiftTemplate response field types are `time` not `str`** — schema declares `start_time: time`, `end_time: time` (Python `datetime.time`). The frontend B7 helper builds end_time strings in `HH:MM` — these will be auto-serialised by Pydantic to `"HH:MM:SS"`. — **Fix**: Added a note to B7 / B8 that the frontend must parse the time strings as `HH:MM[:SS]` (either form) before computing the entry's `start_time` / `end_time` ISO strings.

- **CODE-GAP-14: Mobile fallback observation** — confirmed correct. No code change. R18 stands.

---

## Out-of-scope / parked items

- **Server-side branch filter on `/api/v2/staff`** — adding `branch_id` to the staff list endpoint is a small enhancement that would tighten R3.3, but is deferred to a follow-up spec to avoid scope creep on the staff module from this PR.
- **Server-side `last_name, first_name` sort on `/api/v2/staff`** — same rationale; spec R2.2 is preserved at the UI layer for now.
- **Pi prod deploy** — covered by the standard `deployment-environments.md` flow; no spec-specific tooling required.

---

## Summary table

| Item | Severity | Action |
|------|----------|--------|
| GAP-S1 (trade-family) | Medium | Added R20 |
| GAP-S2 (e2e test) | Medium | Added D4 |
| GAP-S3 (issue tracker) | Low | Updated tasks preamble |
| GAP-S4 (browser test) | Low | Sub-bullets added to B-tasks |
| GAP-S5 (error UI) | Medium | Added R21 |
| GAP-S6 (transactions) | High | A2 explicit-note |
| GAP-S7 (Pydantic gate) | Medium | A2/A3/A5 verify lines |
| GAP-S8 (version) | Low | E1 fixed to 1.17.0→1.18.0 |
| GAP-S9 (no `as any`) | Low | B1 verify |
| GAP-S10 (deploy) | Low | Tasks footer |
| GAP-S11 (no shortcut) | Low | Tasks preamble |
| GAP-S12 (mobile) | Confirmed | No change |
| CODE-GAP-1 (role guard) | High | A6/A7 syntax fixed |
| CODE-GAP-2 (audit kwarg) | High | A4 + R17.3 fixed to `action=` |
| CODE-GAP-3 (modal prop) | High | New task B6a |
| CODE-GAP-4 (react-virtual) | Medium | D2 path = `content-visibility` only |
| CODE-GAP-5 (leave dates) | High | New task A7 |
| CODE-GAP-6 (Toast) | Medium | Replaced JSX with `addToast()` |
| CODE-GAP-7 (test path) | Low | C2 path = flat `tests/test_*.py` |
| CODE-GAP-8 (existing role) | High | A6 single-entry sub-bullet `[~]`; R22 |
| CODE-GAP-9 (staff branch filter) | Medium | B4 client-side filter |
| CODE-GAP-10 (staff sort) | Low | B5 client-side sort |
| CODE-GAP-11 (staff resp shape) | Low | B4 `res.data?.staff` |
| CODE-GAP-12 (mechanic role) | Low | A6 → `staff_member` |
| CODE-GAP-13 (time vs str) | Low | B7/B8 parse note |
| CODE-GAP-14 (mobile) | Confirmed | No change |

After applying these fixes the spec is implementable end-to-end with no false assumptions about the codebase and full coverage of every applicable steering doc.


---

## Implementation gaps (raised during execution)

### A7 spec text vs. its own predicate (resolved in code)

The original task A7 specified:

> Query with `?status=approved&start_lte=2025-06-08&end_gte=2025-06-04` → `items` length 2 (Jun 5–7 and Jun 10–12 overlap; Jun 1–3 doesn't because it ends before Jun 4)

This is internally inconsistent with the documented SQL predicate
`LeaveRequest.start_date <= start_lte AND LeaveRequest.end_date >= end_gte`.
With `start_lte = Jun 8` and `end_gte = Jun 4`, the predicate yields:

- **Jun 1–3** — `end_date = Jun 3 < Jun 4` → **excluded** ✓ (matches spec)
- **Jun 5–7** — `start_date = Jun 5 ≤ Jun 8 AND end_date = Jun 7 ≥ Jun 4` → **included** ✓
- **Jun 10–12** — `start_date = Jun 10 > Jun 8` → **excluded** ✗ (spec said included, but the predicate excludes)

The standard half-open overlap test `request_start ≤ window_end ∧ request_end ≥ window_start` is correct for "find leave requests that overlap the visible window [Jun 4, Jun 8]". A request starting on Jun 10 cannot overlap a window that ends on Jun 8.

**Resolution:** The implementation follows the documented predicate (the SQL contract). The integration test at `tests/integration/test_leave_approvals_dates.py::test_filter_returns_only_overlapping_requests` asserts `length == 1` (only Jun 5–7 overlaps the [Jun 4, Jun 8] window). A second test (`test_filter_includes_request_starting_inside_window`) widens the window to `[Jun 4, Jun 15]` and confirms both Jun 5–7 and Jun 10–12 are returned. A third (`test_filter_omitted_returns_all_requests`) verifies the param is non-breaking when omitted.

The frontend B4 task uses `start_lte = window_end_iso_date` and `end_gte = window_start_iso_date`, which lines up correctly with the predicate.
