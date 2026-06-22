# Implementation Plan: Auto Clock-Out & Forgotten-Clock-Out Recovery

## Overview

Build opt-in auto clock-out on top of the existing hourly
`check_missed_clock_outs_task`, make the kiosk recover from the
`already_clocked_in` 409, scope-restrict and surface the existing manager admin
clock-out, and add the settings UI. No new tables, no migration (org
`clock_in_policy` and `time_clock_entries.flags` are JSONB).

Backend is Python (`app/tasks/scheduled.py`, `app/modules/organisations`,
`app/modules/time_clock`), frontend is TypeScript/React (`frontend-v2`), matching
the existing code. The auto-close pipeline is built bottom-up — policy keys →
pure resolver → notification helpers → single-entry closer → task wiring — so
each step builds on the previous and nothing is left orphaned. Tests live
alongside the code (Hypothesis for the pure invariants, pytest for integration,
Vitest + RTL for the frontend). Requirement references map to `requirements.md`;
property references map to the Correctness Properties in `design.md`.

## Tasks

- [x] 1. Clock-in-policy keys + defaults (backend config)
  - [x] 1.1 Add the three auto-clock-out keys to the policy read/write path
    - Add `auto_clock_out_enabled` (bool, default `false`), `auto_clock_out_after_hours`
      (int, default `14`, range 1..48), `auto_clock_out_grace_minutes` (int, default
      **15**, range 0..240) to `_CLOCK_IN_POLICY_DEFAULTS` in
      `app/modules/organisations/service.py` and to `ClockInPolicyBlock` in
      `app/modules/organisations/schemas.py`.
    - Add the same three keys (auto-close OFF) to `_ALERT_POLICY_FALLBACK` in
      `app/tasks/scheduled.py` so a missing `clock_in_policy` fails safe (never auto-closes).
    - Confirm `get_clock_in_policy` merge-with-defaults and `update_clock_in_policy`
      field-by-field merge surface the keys with no migration.
    - _Requirements: 1.1, 1.2, 1.3, 1.5_

  - [x] 1.2 Unit tests for policy defaults + validation
    - Absent keys resolve to defaults (grace **15**, after-hours 14, enabled false);
      out-of-range values rejected; partial PUT leaves other policy keys intact.
    - _Requirements: 1.1, 1.2, 1.3, 1.5_

- [x] 2. End-time resolver + fixed-end helper (pure functions, `app/tasks/scheduled.py`)
  - [x] 2.1 Implement `_resolve_auto_clock_out_end` and `_fixed_end_minutes_for_date`
    - `_resolve_auto_clock_out_end(*, clock_in_at, now, after_hours, grace_minutes,
      scheduled_end, fixed_end_minutes)` applies the basis hierarchy
      (scheduled_end + grace → fixed day end + grace → `clock_in_at + after_hours` cap),
      handles the overnight/wrapped fixed shift, and clamps to `[clock_in_at, now]`.
    - `_fixed_end_minutes_for_date` reuses `_WEEKDAY_KEYS` / `_parse_hhmm` from
      `app/modules/timesheets/service.py` (single source of truth).
    - _Requirements: 2.2, 2.3, 2.4, 2.5_

  - [x] 2.2 Property tests for resolver invariants (Hypothesis)
    - **Property 3: End never before clock-in** — `clock_out_at >= clock_in_at`.
    - **Property 4: End never in the future** — `clock_out_at <= now`.
    - **Property 5: Basis hierarchy priority** — scheduled → fixed → cap selection.
    - **Property 6: Grace applied** — scheduled/fixed pre-clamp end == basis end + grace.
    - **Validates: Requirements 2.2, 2.3, 2.4, 2.5**

  - [x] 2.3 Unit tests for fixed-end helper + clamp/eligibility edges
    - `_fixed_end_minutes_for_date` for present / absent / malformed / overnight days;
      end-time basis hierarchy example cases (rostered → fixed → elapsed cap).
    - _Requirements: 9.1_

- [x] 3. Notification helpers (staff gating + manager best-effort, `app/tasks/scheduled.py`)
  - [x] 3.1 Implement `_resolve_manager`, `_notify_staff_auto_clock_out`, `_notify_manager_auto_clock_out`
    - `_resolve_manager(session, staff)` walks the `reporting_to` chain (first reachable
      manager with a phone/email), mirroring `check_late_arrivals_task`.
    - `_notify_staff_auto_clock_out(...) -> bool` sends over `missed_clock_out_alert_channels`
      via the existing `send_sms`/`send_email` senders; returns `True` only when a
      notification was actually dispatched, `False` on send failure or no contactable
      channel (this gates the closure).
    - `_notify_manager_auto_clock_out(...) -> None` is best-effort; both messages state the
      clock-in time and the auto clock-out time and direct the recipient to correct it.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 3.2 Unit tests for notification helpers
    - Staff helper returns `True` on dispatch, `False` on send failure and on no contactable
      channel; manager helper raising does not propagate; message content includes both times.
    - _Requirements: 4.1, 4.2, 4.4, 4.5_

- [x] 4. Single-entry closer `_auto_close_entry` (returns bool, `app/tasks/scheduled.py`)
  - [x] 4.1 Implement the gated closer
    - Resolve scheduled/fixed basis (load `ScheduleEntry` / `StaffMember`), call
      `_resolve_auto_clock_out_end`, derive the basis label.
    - Attempt `_notify_staff_auto_clock_out` FIRST; if it returns `False`, return `False`
      (DEFER — leave entry open, write nothing).
    - On success: set `clock_out_at`, compute `worked_minutes` via `_compute_worked_minutes`,
      flush the close columns.
    - Write the `flags` review marker (`auto_clocked_out`, `auto_clock_out_reason`,
      `auto_clock_out_at`, `needs_review`) inside a `begin_nested` savepoint; on failure roll
      back only the marker and log it, keeping the closure intact.
    - Write the system-attributable `time_clock.auto_clock_out` audit row (user_id=None).
    - Attempt `_notify_manager_auto_clock_out` best-effort (failure logged, never reverts).
    - Return `True`.
    - _Requirements: 2.1, 2.5, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.5_

  - [x] 4.2 Property test: worked_minutes consistency (Hypothesis)
    - **Property 11: worked_minutes consistency** — equals
      `_compute_worked_minutes(clock_in_at, clock_out_at, break_minutes)`, floored at zero.
    - **Validates: Requirements 2.1**

  - [x] 4.3 Property/integration test: flagged + audited
    - **Property 7: Flagged + audited** — closed entry has `flags.auto_clocked_out == true`
      (with reason) AND a `time_clock.auto_clock_out` audit row with before/after snapshots.
    - **Validates: Requirements 3.1, 3.2, 3.3**

  - [x] 4.4 Unit test: marker write is non-fatal
    - **Property 14: Marker write is non-fatal** — when the `flags` marker write raises, the
      closure still completes (`clock_out_at` / `worked_minutes` remain set) and the failure
      is logged.
    - **Validates: Requirements 3.4**

  - [x] 4.5 Unit test: staff notification gates closure, manager best-effort
    - **Property 8: Staff notification gates closure; manager best-effort** — entry is closed
      only after the staff notify is dispatched; a failed staff notify defers (returns
      `False`, no close); a failed manager notify never reverts the closure.
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.5**

- [x] 5. Wire auto-close into `check_missed_clock_outs_task` (`app/tasks/scheduled.py`)
  - [x] 5.1 Add the auto-close branch to the hourly task
    - Per open entry, load the org policy (memoised); when `auto_clock_out_enabled` and
      `open_hours >= auto_clock_out_after_hours`, check the `auto_clockout:{entry_id}` Redis
      dedupe key, call `_auto_close_entry`, and set the dedupe key (24h TTL) ONLY after a
      finalised closure (`True`); on `False` (deferred) leave the entry open with no dedupe so
      it retries next run.
    - Closed/deferred entries skip the reminder branch; fold the existing 12h reminder
      threshold into `missed_clock_out_reminder_hours` (default 12); disabled org ⇒ unchanged
      alert-only path; per-org failure isolation preserved (one org's error never blocks others).
    - _Requirements: 1.4, 2.1, 2.6, 2.7, 4.6_

  - [x] 5.2 Property test: disabled means never closed (Hypothesis)
    - **Property 1: Disabled means never closed** — with `auto_clock_out_enabled` false the
      task never sets `clock_out_at`.
    - **Validates: Requirements 1.4, 9.2**

  - [x] 5.3 Property test: threshold gate (Hypothesis)
    - **Property 2: Threshold gate** — an entry is auto-closed only when open duration
      `(now - clock_in_at)` ≥ `auto_clock_out_after_hours`.
    - **Validates: Requirements 2.1**

  - [x] 5.4 Integration test: idempotent run
    - **Property 10: Idempotent run** — running the task twice closes a given entry at most
      once and notifies at most once (Redis dedupe set only after closure).
    - **Validates: Requirements 2.6, 4.6, 9.3**

  - [x] 5.5 Integration test: deferral on staff-notify failure, close on later run
    - When the staff notification cannot be dispatched the entry is left open (no dedupe,
      not closed un-notified); on a later run, once the notification succeeds, the entry is
      closed.
    - **Validates: Requirements 4.2, 9.6**

  - [x] 5.6 Integration test: per-org isolation + casual no-schedule cap
    - **Property 9: Casual clock-in preserved** — a no-schedule staff member can clock in and
      is closed via the safety-net cap; a failure for one org does not block others; an
      enabled org closes + notifies once.
    - **Validates: Requirements 2.7, 5.1, 5.2, 9.4**

- [x] 6. Force-close authorisation scope (backend, `app/modules/time_clock`)
  - [x] 6.1 Scope-restrict the admin force clock-out
    - In `admin_force_clock_out` (behind `POST /api/v2/time-clock/admin-clock-out/{entry_id}`)
      enforce: an org-level admin MAY close any Open_Entry in the org; a branch-scoped user
      (branch_admin / location_manager) MAY close only entries for staff in their assigned
      branches.
    - Reject out-of-scope requests (e.g. 403 `forbidden_scope`) WITHOUT modifying the entry,
      preserving the existing reason + audit behaviour for in-scope closes.
    - _Requirements: 6.4, 6.5_

  - [x] 6.2 Integration test: force-close scope enforced
    - **Property 15: Force-close scope enforced** — a branch-scoped user targeting a staff
      member in another branch is rejected and the Open_Entry is left unchanged; an org-level
      admin may close any entry in the org.
    - **Validates: Requirements 6.4, 6.5, 9.7**

- [x] 7. Kiosk 409 recovery (frontend, `frontend-v2/src/pages/kiosk/KioskClockScreen.tsx`)
  - [x] 7.1 Implement the recovery logic
    - Add `is409AlreadyClockedIn`, `reLookup`, and `looksLikeJustNow`; on an `in` attempt that
      returns `already_clocked_in`, re-check live state: a self-caused double-submit resolves
      to a success confirmation, a genuine old open entry routes to a new `needs-manager`
      sub-screen.
    - Add the refined `already_clocked_in` / `not_clocked_in` messages in `getErrorMessage`
      and soften the `IdentityConfirmStep` `stateMismatch` guard so the flow proceeds into
      recovery instead of dead-ending.
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 7.2 Frontend tests for kiosk recovery (Vitest + RTL)
    - **Property 12: Kiosk idempotent retry** — double-submit `already_clocked_in` → success
      confirmation.
    - **Property 13: Genuine stale entry routes to manager** — old open entry →
      `needs-manager`, never a fabricated clock-in; `not_clocked_in` on `out` → recoverable
      message.
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 9.5**

- [x] 8. Admin clock-out UI wiring (frontend)
  - [x] 8.1 Wire the existing admin clock-out endpoint into both surfaces
    - Call `POST /api/v2/time-clock/admin-clock-out/{entry_id}` (reason required) from the
      kiosk `needs-manager` sub-screen and from the Clocked-in / Hours dashboard row action.
    - Surface only in-scope entries; map a scope rejection (403 `forbidden_scope`) and the
      existing `already_clocked_out` / `time_clock_entry_not_found` errors to inline messages;
      refresh the list on success.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 8.2 Frontend tests for admin clock-out (Vitest + RTL)
    - Reason-modal happy path closes the entry; already-closed 409 shows "already closed";
      out-of-scope rejection shows the "outside your branch scope" inline message.
    - _Requirements: 6.1, 6.2, 6.3, 6.5_

- [x] 9. Settings UI for auto clock-out (frontend)
  - [x] 9.1 Add the auto clock-out controls to the clock settings screen
    - Toggle `auto_clock_out_enabled` + numeric `auto_clock_out_after_hours` (1..48) and
      `auto_clock_out_grace_minutes` (0..240) read/written via `GET/PUT
      /api/v2/org/clock-in-policy`; disable the numeric inputs when the toggle is OFF; keep
      the existing missed-clock-out alert toggles independent; PUT only the three keys.
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 9.2 Frontend test for the settings form (Vitest + RTL)
    - Persists the three keys; range validation enforced; toggles independent of the alert
      settings.
    - _Requirements: 8.1, 8.2, 8.3_

- [x] 10. Checkpoint — Ensure all tests pass
  - Run backend tests (`pytest` for service + task + scope) and frontend (`vitest --run` +
    `tsc --noEmit`).
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP.
- No migration: `clock_in_policy` and `time_clock_entries.flags` are JSONB.
- Auto clock-out is **off by default** — pay-affecting automation is opt-in.
- Defaults per design D4 / requirements: `auto_clock_out_after_hours` = **14**,
  `auto_clock_out_grace_minutes` = **15**, `auto_clock_out_enabled` = **false**.
- The staff notification **gates** the closure (REQ 4.1/4.2): a non-dispatchable staff
  notify defers the entry; the Redis dedupe key is set only after a finalised closure. The
  manager notification is best-effort after closure (REQ 4.3/4.5).
- The `flags` review-marker write is non-fatal (REQ 3.4): written in a `begin_nested`
  savepoint so a marker failure never leaves a stale entry open.
- Force-close is scope-restricted (REQ 6.4/6.5): org admin closes any org entry; branch-scoped
  users only their branches' entries.
- The backend `409 already_clocked_in` is correct and unchanged; only the kiosk's handling
  of it changes.
- Reuses `check_missed_clock_outs_task`, `_find_open_entry`, `_compute_worked_minutes`,
  `_load_clock_in_policy`/`_load_org_clock_in_policy`, the alert channel plumbing, and the
  existing `admin_clock_out` endpoint.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "6.1", "7.1", "9.1"] },
    { "id": 1, "tasks": ["2.1", "1.2", "8.1", "6.2", "9.2", "7.2"] },
    { "id": 2, "tasks": ["3.1", "2.2", "2.3", "8.2"] },
    { "id": 3, "tasks": ["4.1", "3.2"] },
    { "id": 4, "tasks": ["5.1", "4.2", "4.3", "4.4", "4.5"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4", "5.5", "5.6"] }
  ]
}
```
