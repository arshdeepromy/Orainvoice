---
inclusion: fileMatch
fileMatchPattern: "app/modules/timesheets/**,app/modules/payslips/**,frontend-v2/src/pages/staff-timesheets/**"
---

# Payroll & Timesheets Architecture

This file is loaded when editing timesheet, payslip, or staff-timesheets UI code. It documents the model these modules follow so changes stay consistent with the decisions already shipped.

## Core Principle: Review Is Decoupled From the Pay Cycle

Timesheet **review/approval** is **weekly and cycle-independent**. The **pay cadence** stays per-cycle. These are two separate axes — never re-couple them.

- Staff worked hours are reviewed/approved on a rolling weekly basis on the **Review Hours** (Attendance) tab, regardless of which pay cycle a staff member is on.
- A pay run (`run_pay_period` in `app/modules/timesheets/payrun.py`) consumes the review state — it does NOT impose its own per-cycle review lock.
- Approval is recorded per shift via `TimeClockEntry.flags["reviewed"]` (with `reviewed_by` / `reviewed_at`). A timesheet auto-locks for a period only when all its shifts are reviewed; shifts still pending review are skipped and surfaced via `PayRunSummary.skipped_pending_review`.

Do not reintroduce a per-cycle "lock the whole cycle before review" gate — that was deliberately removed (Option A).

## Tabs (frontend-v2 `staff-timesheets/`)

The page tabs are: **Review Hours**, **Clocked In**, **Pay Runs**. There is no standalone "Timesheets" tab and no "Weekly Breakdown" view — those were removed. Header cards point at the weekly attendance summary.

| Tab | File | Purpose |
|-----|------|---------|
| Review Hours | `AttendanceTab.tsx` | Worked-vs-expected, expandable rows, per-shift Approve, day-level edit, This Week/Month filters |
| Clocked In | `ClockedInTab.tsx` | Currently clocked-in staff, clock-out, on-leave/rostered-not-clocked-in sections |
| Pay Runs | `PayRunsTab.tsx` | Generate pay runs per cycle; payslips |

## Attendance Edit Model (Truthful Times vs Overrides)

Two distinct edit paths, both via `/api/v2/timesheets/attendance/...`:

1. **Correct clock times** — edits `clock_in` / `clock_out` so OT/break math stays exact. The DB trigger `tce_immutability_guard` (migration `0218`) blocks value-changes to `clock_in`/`clock_out` and `DELETE` on raw entries, so corrections are layered as an **adjustment overlay** on `flags["adjustment"]`, not by mutating the original row.
2. **Direct "set this day = N hours" override** — for fixed/casual staff who don't clock. Sets a `worked_minutes` override for the day.

Supporting service ops: `add_manual_shift`, `void_manual_shift`, `recompute_timesheets_for_staff_date`. Attendance endpoints: `GET /attendance`, `GET /attendance/{staff_id}/shifts`, `POST /attendance/shifts/{entry_id}/review`, `POST /attendance/{staff_id}/review-all`, `PATCH /attendance/shifts/{entry_id}`, `POST /attendance/{staff_id}/shifts`, `DELETE /attendance/shifts/{entry_id}`.

## PAYE / Tax Engine

NZ tax computation lives in `app/modules/timesheets/paye.py` (`compute_paye`) and is consumed by `app/modules/payslips/calc.py`. Rates (income tax brackets, secondary flat rates, ACC levy rate + max liable earnings, student loan rate + threshold, IETC, KiwiSaver default) are currently **hard-coded constants** in `paye.py`.

A two-tier GUI-configurable tax-settings model is specified in `.kiro/specs/payroll-tax-settings/` (platform default + org override → resolution → hard-coded safety net). When that spec is implemented, the hard-coded constants become the `SAFETY_NET` fallback and `compute_paye(config=...)` takes a resolved config. Until then, IRD rate changes still require a code change — do not scatter new rate constants elsewhere; keep them in `paye.py`.

## Rules

- Keep review/approval weekly and cycle-independent; keep pay cadence per-cycle.
- Never mutate `clock_in`/`clock_out` directly — the `tce_immutability_guard` trigger will reject it. Use the adjustment overlay.
- A pay run must skip (not block on) timesheets with unreviewed shifts and report them in `skipped_pending_review`.
- All tax rates stay centralised in `paye.py` (or the resolved config once `payroll-tax-settings` ships).
- Follow `safe-api-consumption.md` for the `staff-timesheets/` React code and the standard `session.begin()` transaction rules (no manual commit/rollback inside the context manager — see ISSUE-044).
