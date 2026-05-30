# Staff Management Phase 3 — Tasks

## Workstream A — Migrations

- [ ] **A1. `0207_time_clock_schema.py`** — six new tables + clock_in_policy + overtime_policy JSONB columns on organisations. RLS + tenant_isolation on all. CHECK constraints per design. Idempotent.
  - `time_clock_entries` includes a `flags jsonb DEFAULT '{}'::jsonb` column (G10). **Column name is `flags`, NOT `metadata`** — the latter is reserved by SQLAlchemy DeclarativeBase and would raise `InvalidRequestError` at startup if used as a column name on the ORM model.
  - `shift_swap_requests.status` CHECK enum is extended to include `'awaiting_manager'` (G8).
  - `clock_in_policy` JSONB default block includes `shift_swap_requires_manager_approval: false` (G8).
  - **New `overtime_policy` JSONB column on organisations** (G1) with defaults `{ "weekly_threshold_minutes": 2400, "daily_threshold_minutes": 480, "require_pre_approval": false }`.
  - `branches` ADD COLUMN: `lat, lng, geofence_radius_metres int default 200`. Backfill `geofence_radius_metres` from each org's `clock_in_policy.branch_radius_metres` for existing branches (G17).
  - **Phase 2 prerequisite: `overtime_handling` must be in `organisations.settings` JSONB with `'overtime_handling'` in `SETTINGS_JSONB_KEYS`** (per Phase 2 code-verification §2.5). Phase 3 reads it via `get_org_settings(...).get('overtime_handling', 'pay_cash')`. If P2 ships with `overtime_handling` as a typed column instead, Phase 3 R6a.2 must be re-aligned.
  - **Verify:** `\d+ time_clock_entries` shows the table incl. `flags` column; CHECK on kiosk-photo enforced by inserting bad row → fails; `SELECT overtime_policy FROM organisations LIMIT 1` returns the default JSONB; `SELECT geofence_radius_metres FROM branches LIMIT 1` returns 200 (or whatever org default was at upgrade time).

- [ ] **A2. `0208_time_clock_indexes.py`** — 9 indexes via CONCURRENTLY.
  - Plus 1 partial index `idx_time_clock_flagged ON time_clock_entries (org_id, staff_id) WHERE (flags->>'flagged_for_review')::boolean = true` (G10) — supports the flagged-entries query on Hours tab.
  - **Verify:** `EXPLAIN SELECT FROM time_clock_entries WHERE staff_id=$1 AND clock_out_at IS NULL` shows partial index usage. `EXPLAIN SELECT FROM time_clock_entries WHERE org_id=$1 AND (flags->>'flagged_for_review')::boolean = true` uses `idx_time_clock_flagged`.

## Workstream B — Backend module `app/modules/time_clock/`

- [ ] **B1. ORM models** for all new tables. `TimeClockEntry.flags` typed as `Mapped[dict]` with `JSONB` (column literal name `flags` — NOT `metadata` because SQLAlchemy DeclarativeBase reserves that attribute). `ShiftSwapRequest.status` includes `'awaiting_manager'` literal.
- [ ] **B2. Pydantic schemas** including `{ items, total }` lists. New schemas: `RunningLateRequest`, `RunningLateResponse`, `FlagForReviewRequest`, `OvertimePolicyResponse`, `ClockInPolicyResponse` (extends to include `shift_swap_requires_manager_approval`).
- [ ] **B3. `service.py`** — kiosk lookup + action; self-service action; admin manual; auto-match scheduled_entry; worked_minutes calc.
  - **Verify:** unit test covers in/out/break round-trip; worked_minutes correct after break deduction.

- [ ] **B3a. Cross-phase patch to Phase 1 `app/modules/staff/service.py::create_staff` (G9)** — when `payload.self_service_clock_enabled is None`, read `organisations.clock_in_policy.default_channel` and set the flag accordingly. Make `StaffMemberCreate.self_service_clock_enabled: Optional[bool] = None` so caller can distinguish "didn't say" from "explicitly false".
  - **Verify:** unit test `tests/unit/test_staff_create_default_channel.py`:
    - Org with `default_channel='kiosk_only'`, payload omits flag → new staff has `self_service_clock_enabled=false`.
    - Same org, payload sets flag=true explicitly → new staff has `self_service_clock_enabled=true`.
    - Org with `default_channel='kiosk_and_self_service'`, payload omits flag → new staff has `self_service_clock_enabled=true`.
    - Existing staff records not mutated when org policy changes.

- [ ] **B4. `breaks.py`** — start/end break, suggested-window calc, ERA s69ZD validation chip.

- [ ] **B5. `approvals.py`** — week totals calc per design §4.2 (G1: applies `overtime_policy.daily_threshold_minutes` + `weekly_threshold_minutes` to split ordinary/overtime; G1.5: appends `unapproved_overtime` notes when `require_pre_approval=true`); lock check (refuses PUT/DELETE on entries inside approved weeks — scope: `time_clock_entries` only per G7); upsert `timesheet_approvals`; TOIL accrual integration when `overtime_handling`=`toil`/`employee_chooses` (read via `get_org_settings(...).get('overtime_handling', 'pay_cash')` per Phase 2 verification §2.5).
  - **Verify:** approve a week, attempt PUT on a clock entry inside → 409 conflict; reopen → edit allowed. Unit test for overtime split: 9h Mon + 9h Tue + 9h Wed + 9h Thu = 36h worked; with `daily_threshold=480` → 4h overtime (1h × 4 days) even though weekly under 40h. Another test: 10h × 5 days = 50h worked; daily ot = 10h (2h × 5), weekly ot = max(0, 50-40-10) = 0, total ot = 10h. **G7 — `time_entries` table is NOT touched by approval**: existing lock at `app/modules/time_tracking_v2/service.py:172-184` already raises `ValueError("Cannot update an invoiced time entry")` when `is_invoiced=true`. Phase 3 must NOT add a second lock. Test: approve a week → attempt PUT on a *non-invoiced* `time_entries` row inside that week's window → succeeds (only the existing `is_invoiced` lock blocks any edit, never the new timesheet-approval lock).

- [ ] **B6. `swaps.py`, `cover.py`, `overtime.py`** — service functions.
  - **`swaps.py` (G8 + G13):**
    - `target_accepts_swap`, `target_rejects_swap`, `manager_approves_swap`, `manager_rejects_swap`, `cancel_swap` per design §4.8.
    - Reads `clock_in_policy.shift_swap_requires_manager_approval` to decide auto-approve vs `awaiting_manager` flow.
    - `_notify_swap(swap, event)` helper sends the per-event SMS matrix from R12.5; writes `shift_swap.sms_sent` / `shift_swap.sms_skipped` audit rows.
    - Re-checks eligibility at the flip moment (auto-approve OR manager-approve) — 409 with `scheduling_conflict_at_accept` / `scheduling_conflict_at_manager_approval` if staff has been scheduled into a conflicting shift since the request was raised.
  - **`cover.py` (G6):**
    - Eligibility filter at broadcast time: `is_active AND (employee_id IS NOT NULL OR user_id IS NOT NULL) AND not_scheduled_in_window([shift.start-30min, shift.end+30min]) AND skills_overlap AND id != requester_staff_id`.
    - Eligibility re-check at claim time — 409 `scheduling_conflict_at_claim` if claiming staff has been scheduled into the window since broadcast; audit row `shift_cover.claim_conflict`.

- [ ] **B7. Router** — all endpoints from design §5 (incl. the four new shift-swap endpoints, the flag-for-follow-up endpoint, `/staff/me/running-late`). Module-gated by `staff_management`. Self-service action checks `self_service_clock_enabled` server-side. The flag-for-review endpoint enforces RBAC (org_admin / branch_admin / location_manager only).

- [ ] **B7a. Roster-change SMS hook (G2)** — hook into `app/modules/scheduling_v2/service.py::update_entry` and `::reschedule` (note: real method is `reschedule`, NOT `reschedule_entry`, verified at `service.py:215`) plus shift-swap accept + cover accept paths in the time_clock module, per design §4.6. Detects in-window changes (start_time/end_time/staff_id within 48h), Redis dedupes via `roster_change:{schedule_entry_id}`, composes SMS via `compose_change_sms_body(...)` (templates spelled out in design §4.6), calls `send_sms` with `dlq_task_name='roster_change_sms'`, writes audit rows. Honors `staff.weekly_roster_sms_enabled` opt-out.
  - **Verify:** unit test `tests/unit/test_roster_change_sms.py`: update an entry within 48h → SMS sent; update again within 1h → second SMS dedup'd; update with staff opted-out → audit row `roster.change_sms_skipped` reason=`opt_out`.

- [ ] **B7b. Running-late endpoint (G3)** — `POST /api/v2/staff/me/running-late` per design §4.7. Finds in-window shift, sends manager SMS, snoozes `late:{shift_id}` Redis key, audit `staff.reported_late`. Per-shift rate limit (3/shift).
  - **Verify:** call when staff has no in-window shift → 422 `no_upcoming_shift`. Call 4× for the same shift → 4th returns 429 `too_many_late_reports`. Verify `check_late_arrivals` task subsequently skips the snoozed shift.

- [ ] **B8. Register router in main.py**.

- [ ] **B9. Kiosk extension** — add `/api/v1/kiosk/clock/lookup` + `/api/v1/kiosk/clock/action` to `app/modules/kiosk/router.py`. **Auth model:** these routes use the SAME `dependencies=[require_role("kiosk"), Depends(_check_kiosk_rate_limit)]` pattern as the existing `POST /api/v1/kiosk/check-in` endpoint (verified at `app/modules/kiosk/router.py:108-112`). The kiosk tablet's pre-existing role-`kiosk` JWT (30-day refresh) is the auth surface — no separate per-staff login. Routes are NOT in `PUBLIC_PATHS` / `PUBLIC_PREFIXES`.
  - **Lookup-specific rate-limit per design §R3.3 (G12), in addition to the existing `_check_kiosk_rate_limit`:**
    - Inline check in `/api/v1/kiosk/clock/lookup` handler: hash `employee_id` via `hashlib.sha256(employee_id.encode()).hexdigest()[:16]`; Redis key `kiosk_lookup:{org_id}:{hash}`; `INCR` + `EXPIRE 60` on first hit; reject when counter > 10 with HTTP 429 + `Retry-After: 60` + body `{ "detail": "kiosk_lookup_rate_limited" }`. Audit row `kiosk.lookup_rate_limited` with hashed identifier.
    - Does NOT modify `app/middleware/rate_limit.py` policy map.
  - **Photo upload endpoint:** add `POST /api/v2/uploads/clock-photos` to `app/modules/uploads/router.py` (mirrors the existing `/receipts` and `/attachments` endpoints; calls `_store(content, filename, org_id, "clock_photos", db)` with the existing helper). Returns `{ file_key, file_name, file_size }`. **The clock-action endpoints accept `photo_file_key` (the same string returned as `file_key` from this upload) — NOT `photo_upload_id` (the spec name in early drafts).**
  - **Verify:** 11th lookup for same `(org_id, employee_id)` within 60s returns 429 with `Retry-After: 60` header. Audit row written. Raw employee_id never appears in Redis SCAN output or audit `after_value`. Mobile/web kiosk app's clock-action POST works using the existing kiosk JWT in the device's session.

## Workstream C — Scheduled tasks

- [ ] **C1. `check_late_arrivals` (300s, name `check_late_arrivals`)** — see design §4.3. Per-shift dedupe via Redis key `late:{shift_id}`. **Honors snooze set by R14b running-late report (G3)** — if the key already exists, skip. **Add the task name to `WRITE_TASKS` set at `app/tasks/scheduled.py:849`** so it's skipped on standby HA nodes (preventing duplicate SMS sends). Append `(check_late_arrivals_task, 300, "check_late_arrivals")` to `_DAILY_TASKS` list at line 872.
- [ ] **C2. `check_missed_clock_outs` (3600s, name `check_missed_clock_outs`)**. **Add to `WRITE_TASKS`** for the same standby-skip reason. Append `(check_missed_clock_outs_task, 3600, "check_missed_clock_outs")` to `_DAILY_TASKS`.
- [ ] **C3. Both gated behind scheduler SETNX lock** (existing).

## Workstream D — Frontend

- [ ] **D1. `KioskClockScreen.tsx`** — multi-step welcome → entry → identity confirm → camera → confirmation.
- [ ] **D2. `HoursTab.tsx` (G10)** — week selector, scheduled vs actual table, drill-down list, Approve button. **Each `ClockEntriesList` row renders clock-in / clock-out photo thumbnails (when role permits)**; clicking opens a side-by-side modal with the on-file photo for buddy-punch comparison. Each row has a "Flag for follow-up" button that POSTs `/staff/:id/clock/:entry_id/flag` and visually marks the row with a 🚩. The Hours tab shows a `FlaggedReviewBanner` when any flagged entries exist in the week.
  - Photos use `?.` chaining and `?? null` defaults per safe-api-consumption.
  - RBAC: backend serializer returns photo URLs only when caller role is org_admin / branch_admin / location_manager; lower roles get `null` and the frontend renders "[photo]" placeholder.
  - **Verify:** browser test — admin sees photo thumbnails; staff_member viewing own hours sees placeholders. Flag a row → row gets red 🚩; banner counter increments.

- [ ] **D3. `SelfServiceClockScreen.tsx`** (web).
- [ ] **D4. `ClockInPolicyPage.tsx` (settings, G1 + G8 + G17)** — clock-in policy card + new **overtime policy card** (weekly/daily thresholds, require_pre_approval toggle, `overtime_handling` enum from Phase 2) + `shift_swap_requires_manager_approval` toggle. PATCH writes back. The page also surfaces a note clarifying the per-branch vs org-default geofence radius (G17): "The org-level radius is the default applied to new branches; existing branches keep their own value unless edited directly on the branch page."
- [ ] **D5. `OvertimeRequestModal.tsx` + `ApproveWeekModal.tsx` + `ManualEntryModal.tsx` + `RunningLateSheet.tsx` (G3) + `FlagForReviewModal.tsx` (G10)**.
  - `ApproveWeekModal` (G1 + G10): shows totals breakdown with explicit ordinary/overtime/public-holiday split, displays count of `unapproved_overtime` minutes when `require_pre_approval=true`, requires explicit acknowledgement when there are flagged entries.
  - `RunningLateSheet`: minutes slider (1–180) + reason input + Send button. POSTs `/api/v2/staff/me/running-late`.
- [ ] **D6. `/shift-swaps` and `/shift-cover` pages**. The swap page reflects the 5-state state machine (G8) — UI shows "Awaiting manager approval" badge when applicable; managers see a queue of `awaiting_manager` rows with approve/reject buttons.
- [ ] **D7. Sidebar entries**: "Open shifts", "Shift swaps". The Shift swaps entry shows a red dot counter for managers when there are `awaiting_manager` rows.
- [ ] **D8. Mobile `ClockScreen.tsx` (G3 — running late button)** + lazy import in `StackRoutes.tsx` + ModuleGate. 44×44 touch targets, `pb-safe`. Capacitor guards. Hide Clock button when `self_service_clock_enabled=false`. **Show "I'm running late" button when (a) staff is NOT currently clocked in AND (b) staff has an in-window shift per R14b criterion 2** — opens `RunningLateSheet`. Same logic in web `/staff/me/clock` (D3).

## Workstream E — Tests

- [ ] **E1. Unit tests** — covering every new service path:
  - `tests/unit/test_time_clock_service.py` — kiosk + self-service + admin manual; auto-match scheduled_entry_id; worked_minutes calc.
  - `tests/unit/test_time_clock_breaks.py` — start/end break, ERA s69ZD suggested windows, meal_unpaid deduction.
  - `tests/unit/test_time_clock_approvals.py` — week totals; overtime split per G1 (daily + weekly thresholds); `unapproved_overtime` notes; lock-check; **G16 — `edited_after_approval` state**: approve a week → admin manually edits a clock entry inside → assert `timesheet_approvals.status='edited_after_approval'`, totals recomputed, audit row written; reopen flow.
  - `tests/unit/test_time_clock_swap_cover.py` — G6 eligibility filter (in-window scheduled staff excluded; employee_id/user_id required); G8 auto-approve vs manager-approval state transitions; G13 notification matrix per event; eligibility re-check at claim time.
  - `tests/unit/test_time_clock_overtime.py` — overtime_requests workflow.
  - `tests/unit/test_staff_create_default_channel.py` (G9) — cross-phase test that `create_staff` reads `default_channel` policy.
  - `tests/unit/test_roster_change_sms.py` (G2) — hook fires within 48h, Redis dedupe, opt-out skip, no_phone skip.
  - `tests/unit/test_running_late.py` (G3) — endpoint accepts in-window report, snoozes `late:{shift_id}` key, rate-limit 3/shift, manager SMS sent.
  - `tests/unit/test_kiosk_lookup_rate_limit.py` (G12) — 11th lookup returns 429; hashed identifier in Redis; audit row written.
- [ ] **E2. Property test** `tests/property/test_clock_calc_invariants.py` — Hypothesis: any in/out/break sequence keeps worked_minutes >= 0 and consistent with elapsed - break_minutes. **Extended (G1):** for any random (worked_minutes, daily_thresh, weekly_thresh) triple, `ordinary + overtime + public_holiday == total_worked` and `ordinary >= 0` and `overtime >= 0`.
- [ ] **E3. E2E** `scripts/test_staff_clock_in_out_e2e.py` per R17. **Extended to cover all 14 gap paths:**
  - **G1:** approve a week with 50h worked, daily_threshold=480, weekly_threshold=2400 → assert `total_overtime_minutes=600` (10h × 1h daily-OT per day for 5 days; weekly-OT contribution = 0 since daily already captured the excess).
  - **G2:** update a schedule_entry within 48h → SMS log shows roster-change SMS sent; update same entry again 30 minutes later → second SMS dedupe'd.
  - **G3:** POST `/staff/me/running-late` → check manager's SMS log + `late:{shift_id}` Redis key set with proper TTL + audit `staff.reported_late`.
  - **G6:** create cover request → only eligible staff (not already scheduled, has employee_id or user_id) receive SMS; claim from an ineligible staff → 409.
  - **G7:** approve a week → attempt PUT on a `time_entries` row inside that window → succeeds (we don't lock the billable timer).
  - **G8 + G13:** with `shift_swap_requires_manager_approval=true`: target accepts → state=`awaiting_manager`, manager gets SMS; manager approves → state=`accepted`, both staff get SMS per matrix.
  - **G9:** with `default_channel='kiosk_and_self_service'`, create new staff without specifying flag → `self_service_clock_enabled=true` on the new row.
  - **G10:** clock in via kiosk → flag the entry from Hours tab → row gets metadata flag + audit row; approve week with flagged entry → modal requires acknowledgement before submit.
  - **G12:** 11 kiosk lookups in 60s → 11th returns 429 with Retry-After header.
  - **G16:** approve week → admin manually edits a clock entry inside → status flips to `edited_after_approval` + audit row.

## Workstream F — Versioning + docs

- [ ] **F1. Bump 1.15.0 → 1.16.0** across the three package files.
- [ ] **F2. CHANGELOG `## [1.16.0]`** entry covering kiosk + self-service clock-in + breaks + approvals + lock + overtime + swap + cover + late/missed alerts.
- [ ] **F3. STAFF-005, STAFF-006, STAFF-007** in ISSUE_TRACKER updated with chosen direction.

## Pre-merge gate

Tick everything in source plan §12. Specifically:
- Kiosk endpoints rate-limited per G12 (hashed key, 429 response, audit row).
- `source='kiosk'` rows have `clock_in_photo_url NOT NULL` (CHECK enforced).
- Self-service refuses 403 when flag false.
- Geofence enforcement matches policy; per-branch `branches.geofence_radius_metres` is authoritative (G17).
- Approve week locks `time_clock_entries` edits ONLY (G7 — `time_entries` not locked).
- TOIL accrual round-trips through Phase 2 leave ledger correctly.
- Late-arrival dedupe key prevents duplicate SMS.
- **Photo retention default 6 years (G15) — no deletion job in Phase 3; Non-Goals + design §3.1 documented.**

**G1–G17 closure ticks (added during spec review)**
- [ ] **G1:** `overtime_policy` JSONB on organisations; `compute_week_totals` splits ordinary/overtime via daily + weekly thresholds; `unapproved_overtime` notes when `require_pre_approval=true`; Settings → Clock-in Policy card renders the three policy fields.
- [ ] **G2:** Roster-change SMS hook fires for in-window changes; Redis dedupe; opt-out + no-phone skips written to audit log.
- [ ] **G3:** `/staff/me/running-late` endpoint live; mobile + web "I'm running late" button visible when staff has in-window shift; snoozes late-arrival check; rate-limited 3/shift.
- [ ] **G4:** Performance SLO targets met — mobile clock-action <200ms p99; kiosk action <300ms p99 (measure via load test or production tracing once deployed).
- [ ] **G6:** Cover broadcast eligibility filter excludes already-scheduled staff in window; requires `employee_id OR user_id`; re-checks at claim time (409 on conflict).
- [ ] **G7:** `time_entries` (billable timer) edits inside an approved week still succeed; only `time_clock_entries` are locked.
- [ ] **G8:** `shift_swap_requires_manager_approval` toggle in Settings; `awaiting_manager` state in schema; manager queue + endpoints; auto-approve mode still works when flag false.
- [ ] **G9:** Cross-phase `create_staff` patch reads `default_channel` and pre-populates `self_service_clock_enabled`. Existing staff unchanged when policy changes.
- [ ] **G10:** `metadata.flagged_for_review` written on flag action; photos surfaced in Hours tab for managers; side-by-side comparison modal works; flagged-entry acknowledgement required to approve week.
- [ ] **G12:** Kiosk lookup rate-limit Redis key is SHA-256-hashed; 11th lookup → 429 + Retry-After; audit row written; raw employee_id never in Redis or audit.
- [ ] **G13:** Per-event SMS notification matrix runs; both parties notified on swap approve/reject; missing phone → audit row reason=`no_phone`, no exception.
- [ ] **G15:** No photo deletion job; Non-Goals + design §3.1 paragraph in place; orphan policy 6-year retention documented.
- [ ] **G16:** `edited_after_approval` unit test passes (`tests/unit/test_time_clock_approvals.py::test_edit_after_approval`).
- [ ] **G17:** Per-branch `branches.geofence_radius_metres` overrides org default; migration backfills existing branches from org default; changing org default does NOT mass-update existing branches.

The phase is NOT done until every box is ticked. Any item that can't be ticked goes into `gap-analysis.md` with the reason.
