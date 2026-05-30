# Staff Management Phase 3 — Tasks

## Workstream A — Migrations

- [ ] **A1. `0207_time_clock_schema.py`** — six new tables + clock_in_policy column on organisations. RLS + tenant_isolation on all. CHECK constraints per design. Idempotent.
  - **Verify:** `\d+ time_clock_entries` shows the table; CHECK on kiosk-photo enforced by inserting bad row → fails.

- [ ] **A2. `0208_time_clock_indexes.py`** — 9 indexes via CONCURRENTLY.
  - **Verify:** `EXPLAIN SELECT FROM time_clock_entries WHERE staff_id=$1 AND clock_out_at IS NULL` shows partial index usage.

## Workstream B — Backend module `app/modules/time_clock/`

- [ ] **B1. ORM models** for all new tables.
- [ ] **B2. Pydantic schemas** including `{ items, total }` lists.
- [ ] **B3. `service.py`** — kiosk lookup + action; self-service action; admin manual; auto-match scheduled_entry; worked_minutes calc.
  - **Verify:** unit test covers in/out/break round-trip; worked_minutes correct after break deduction.
- [ ] **B4. `breaks.py`** — start/end break, suggested-window calc, ERA s69ZD validation chip.
- [ ] **B5. `approvals.py`** — week totals calc; lock check (refuses PUT/DELETE on entries inside approved weeks); upsert `timesheet_approvals`; TOIL accrual integration when policy=`toil`/`employee_chooses`.
  - **Verify:** approve a week, attempt PUT on a clock entry inside → 409 conflict; reopen → edit allowed.
- [ ] **B6. `swaps.py`, `cover.py`, `overtime.py`** — service functions.
- [ ] **B7. Router** — all endpoints. Module-gated by `staff_management`. Self-service action checks `self_service_clock_enabled` server-side.
- [ ] **B8. Register router in main.py**.
- [ ] **B9. Kiosk extension** — add `/kiosk/clock/lookup` + `/kiosk/clock/action` to `app/modules/kiosk/router.py` (no auth, rate-limited per (org_id, employee_id)).

## Workstream C — Scheduled tasks

- [ ] **C1. `check_late_arrivals` (5 min)** — see design §4.3. Per-shift dedupe via Redis.
- [ ] **C2. `check_missed_clock_outs` (1 hr)**.
- [ ] **C3. Both gated behind scheduler SETNX lock** (existing).

## Workstream D — Frontend

- [ ] **D1. `KioskClockScreen.tsx`** — multi-step welcome → entry → identity confirm → camera → confirmation.
- [ ] **D2. `HoursTab.tsx`** — week selector, scheduled vs actual table, drill-down list, Approve button.
- [ ] **D3. `SelfServiceClockScreen.tsx`** (web).
- [ ] **D4. `ClockInPolicyPage.tsx`** (settings).
- [ ] **D5. `OvertimeRequestModal.tsx` + `ApproveWeekModal.tsx` + `ManualEntryModal.tsx`**.
- [ ] **D6. `/shift-swaps` and `/shift-cover` pages**.
- [ ] **D7. Sidebar entries**: "Open shifts", "Shift swaps".
- [ ] **D8. Mobile `ClockScreen.tsx`** + lazy import in `StackRoutes.tsx` + ModuleGate. 44×44 touch targets, `pb-safe`. Capacitor guards. Hide button when `self_service_clock_enabled=false`.

## Workstream E — Tests

- [ ] **E1. Unit tests** — `tests/unit/test_time_clock_service.py`, `_breaks.py`, `_approvals.py`, `_swap_cover.py`, `_overtime.py`.
- [ ] **E2. Property test** `tests/property/test_clock_calc_invariants.py` — Hypothesis: any in/out/break sequence keeps worked_minutes >= 0 and consistent with elapsed - break_minutes.
- [ ] **E3. E2E** `scripts/test_staff_clock_in_out_e2e.py` per R17.

## Workstream F — Versioning + docs

- [ ] **F1. Bump 1.15.0 → 1.16.0** across the three package files.
- [ ] **F2. CHANGELOG `## [1.16.0]`** entry covering kiosk + self-service clock-in + breaks + approvals + lock + overtime + swap + cover + late/missed alerts.
- [ ] **F3. STAFF-005, STAFF-006, STAFF-007** in ISSUE_TRACKER updated with chosen direction.

## Pre-merge gate

Tick everything in source plan §12. Specifically:
- Kiosk endpoints rate-limited.
- `source='kiosk'` rows have `clock_in_photo_url NOT NULL` (CHECK enforced).
- Self-service refuses 403 when flag false.
- Geofence enforcement matches policy.
- Approve week locks edits.
- TOIL accrual round-trips through Phase 2 leave ledger correctly.
- Late-arrival dedupe key prevents duplicate SMS.
- Photo retention default 6 years (no deletion job in this phase; documented).
