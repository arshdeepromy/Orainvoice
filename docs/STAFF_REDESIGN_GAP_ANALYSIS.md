# Staff & Staff Detail Redesign — Gap Analysis & Implementation Plan

**Status:** Investigation complete · proposed plan
**Date:** 2026-06-07
**Design source:** `OraInvoice_Handoff/app/Staff.html`, `OraInvoice_Handoff/app/StaffDetail.html`
**Target app:** `frontend-v2/` (active web app)
**Decisions captured from product:**
1. Keep the existing **tabbed detail shell** (Overview / Roster / Payslips / Documents); restyle the **Overview** tab to match the mockup. Do **not** flatten to the single-page layout in `StaffDetail.html`.
2. Build **all four** "This month" sidebar metrics: Hours logged, Jobs completed, Billable ratio, On-time rate.

---

## 1. Executive summary

Both the Staff list and Staff detail pages already exist in `frontend-v2`, on a mature backend (staff-management Phases 1–4 shipped, alembic head 0214) and already framed onto the same `ds.css` design tokens the mockups use. This is predominantly a **frontend polish** effort plus **one new backend metrics endpoint**.

| Area | Verdict | Effort |
|---|---|---|
| Staff list — KPI cards, segmented filters, day pips, avatar + role subline, Leave/Export buttons | Frontend-only; data largely present | **S–M** |
| Staff detail — restyle Overview to mockup, add hero + right sidebar panels within the existing tab shell | Frontend-only | **M** |
| Detail "This month" metrics (all 4) | **New backend aggregation endpoint** + frontend panel | **M** |
| "Last sign-in" + account panel | Small backend field surfacing + frontend | **S** |

**Rough total: ~1–1.5 weeks.** No new database tables or migrations are required — every metric maps to existing columns.

---

## 2. What already exists

### 2.1 Backend (`app/modules/staff/`)
- Full CRUD at `/api/v2/staff`: list (`page`, `page_size`, `role_type`, `is_active`, `search`), create, get, update, soft-delete; plus `/staff/{id}/permanent`, `/staff/{id}/activate`, `/staff/check-duplicate`, `/staff/{id}/pay-rates`, roster email/SMS, employment-agreement upload, public roster viewer.
- `StaffMember` model already carries every field both mockups display: `employee_id`, `position`, `role_type` (employee/contractor), `reporting_to` (+ resolved `reporting_to_name`), `hourly_rate`, `overtime_rate`, `skills[]` (JSONB), `availability_schedule` (per-day `{start,end}` JSONB), `is_active`, and the user link `user_id`.
- List response includes a `compliance_summary` (7 counters) — richer than the mockup.

### 2.2 Frontend (`frontend-v2/src/pages/staff/`)
- `StaffList.tsx` — paginated token-styled table with the exact mockup column set (Employee ID, Name→detail link, Position, Contact, Work days, Reports to, Status, Actions), search, role + status filters, full add/edit modal (incl. `WorkSchedule` per-day editor, "also create as user" invite with role + branch, inline duplicate checks), deactivate/activate, permanent-delete with "also delete user account".
- `StaffDetail.tsx` — tabbed shell (Overview / Roster / Payslips / Documents) via `useTabHash`, lazy-loaded tabs, dirty-state guard hook.
- `tabs/OverviewTab.tsx` — Personal / Employment / Tax & Pay / Schedule / Clock-in & roster / Skills sections, inline amber compliance warnings, `PayRateHistoryPanel`, `RecurringAllowancesPanel`. Already surfaces **Login access** and **User role**.

### 2.3 Data sources for the new metrics (no schema change needed)
- **Hours logged (this month):** `time_clock_entries.worked_minutes` summed over the staff member for the current calendar month (`clock_in_at` in month, `clock_out_at` not null).
- **Jobs completed (this month):** `job_cards` where `assigned_to = staff.id` and `status IN ('completed','invoiced')` with `updated_at` in the current month.
- **Billable ratio (this month):** from `time_tracking_v2.TimeEntry` (has `staff_id`, `duration_minutes`, `is_billable`) — `sum(billable_minutes) / sum(total_minutes)`. This mirrors the existing Staff Utilisation report in `reports_v2/service.py`, so the definition is consistent with reporting.
- **On-time rate (this month):** of `time_clock_entries` that matched a `scheduled_entry_id`, the share whose `clock_in_at` is at/before the scheduled start (plus a small grace window). Entries with no scheduled match are excluded from the denominator.

---

## 3. Gap analysis

### 3.1 Staff list page (`Staff.html` → `StaffList.tsx`)
| Mockup element | Status | Work |
|---|---|---|
| Page head (eyebrow/title/sub) | ✅ exists | — |
| Search + role + status filters | ✅ exists (as `<select>`) | Restyle to segmented `.seg` pills |
| Table columns (ID/Name/Position/Contact/Work days/Reports to/Status/Actions) | ✅ exists | — |
| Add/Edit modal incl. work schedule, "also create as user", invite | ✅ exists | Minor token polish |
| Deactivate/Activate/Delete (+ delete user) | ✅ exists | — |
| **4 KPI cards** (Total staff, Employees, With login access, Avg hourly rate) | ❌ missing | New KPI strip; counts derivable, "with login access" + "avg hourly rate" need small aggregates |
| **Day pips** (Mon–Sun colored squares) | ❌ (text today) | Restyle the Work days cell |
| **Avatar initials + Employee/Contractor subline** in Name cell | ❌ missing | Frontend |
| **Leave button w/ pending badge** + **Export button** in header | ❌ missing | Leave links to existing Leave Approvals; Export = CSV of current filter |

### 3.2 Staff detail page (`StaffDetail.html` → Overview tab restyle)
| Mockup element | Status | Work |
|---|---|---|
| Hero (big avatar, name, status badge, "Senior Technician · EMP-002 · Branch") | partial | Restyle Overview header to match hero |
| Personal / Employment / Work schedule cards w/ view↔edit toggle | ✅ exists (different framing) | Restyle to `.sec-head` + read-only `.ro` rows |
| Skills tags | ✅ exists | Token polish |
| **Right sidebar — "This month" metrics (4)** | ❌ missing | **New metrics endpoint + panel** |
| **Right sidebar — Account panel** (Login access / User role / Last sign-in) | partial | Login access + role exist; add **Last sign-in** |
| **"No account?" → Create user account modal** | ✅ exists (legacy) | Bring into Overview sidebar styling |

### 3.3 Backend
| Need | Status | Work |
|---|---|---|
| Staff fields for both pages | ✅ all present | — |
| **`GET /api/v2/staff/{id}/stats?period=this_month`** returning the 4 metrics | ❌ missing | **New endpoint + service aggregation** |
| **Last sign-in** on staff detail (from linked `users` row) | ❌ not surfaced | Add to staff get-response (or include in stats) |
| List KPI aggregates (with-login count, avg hourly rate) | ❌ | Add to list `compliance_summary` or a small `kpis` block |

**No new tables or migrations.**

---

## 4. Metric definitions (authoritative)

> These are the contract the stats endpoint implements. "This month" = current calendar month in the **org timezone**.

1. **Hours logged** — `SUM(time_clock_entries.worked_minutes) / 60` for the staff member where `clock_in_at` is within the month and `clock_out_at IS NOT NULL`. Display `142.5h` (one decimal).
2. **Jobs completed** — `COUNT(job_cards)` where `assigned_to = staff.id`, `status IN ('completed','invoiced')`, and `updated_at` within the month. (Job cards have no dedicated `completed_at`; `updated_at` at the completed/invoiced transition is the pragmatic proxy. Flagged as an accepted approximation.)
3. **Billable ratio** — using `time_tracking_v2.TimeEntry` for the staff member within the month: `SUM(duration_minutes WHERE is_billable) / SUM(duration_minutes) * 100`, rounded to whole percent. `0%` (not null) when there is no logged time. Consistent with `reports_v2` Staff Utilisation.
4. **On-time rate** — among `time_clock_entries` in the month that have a non-null `scheduled_entry_id`: the percentage whose `clock_in_at <= scheduled_start + GRACE` (propose `GRACE = 5 min`). Denominator excludes unscheduled clock-ins. `—` (not 0%) when there are no scheduled entries that month, to avoid a misleading 0.

**Empty/zero handling:** each metric returns a numeric value plus a `has_data` flag so the UI can render `—` rather than a misleading `0` where appropriate (notably on-time rate and billable ratio).

**RBAC / gating:** the stats endpoint is gated by the `staff_management` module and the same roles as the rest of staff CRUD (`org_admin`, `salesperson`; `branch_admin` scoped by location assignment). Self-service (`staff_member`) may read **only their own** stats.

---

## 5. Proposed implementation outline

### Backend
- `app/modules/staff/service.py`: add `get_staff_month_stats(db, org_id, staff_id, *, now)` returning `{ hours_logged, jobs_completed, billable_ratio, on_time_rate, last_sign_in, has_data flags }`. Four scoped aggregate queries (clock entries, job cards, billable time entries, scheduled-vs-actual) + a `users.last_login_at` lookup via `staff.user_id`.
- `app/modules/staff/schemas.py`: `StaffMonthStatsResponse`.
- `app/modules/staff/router.py`: `GET /api/v2/staff/{id}/stats` (module-gated, RBAC + self-scope).
- Tests: a service-level test per metric (incl. empty-data → `has_data=false`) and a router auth/scope test.

### Frontend — list
- KPI strip component (4 `.kpi` cards) fed by list totals + a tiny KPI aggregate.
- Restyle filters to `.seg` pills; render `.day-pip` work-days cell; add avatar initials + role subline in Name cell; add Leave (links to Leave Approvals, with pending count) and Export (CSV) buttons.

### Frontend — detail Overview
- Restyle Overview to the mockup's hero + `.sec-head`/`.ro` view rows with inline edit, **inside the existing tab shell** (no routing change).
- Right sidebar: new **"This month"** panel (consumes `/staff/{id}/stats`, renders `—` on `has_data=false`); **Account** panel adds **Last sign-in**; keep the **Create user account** modal.
- Safe API consumption (`?.` / `?? 0` / `?? '—'`); `AbortController` on the stats fetch.

---

## 6. Risks / call-outs
- **Jobs completed** relies on `job_cards.updated_at` as a completion proxy (no `completed_at` column). If precise completion timing is later required, a small status-transition timestamp would be the clean fix (separate, optional migration).
- **Billable ratio** depends on staff actually logging billable time via `time_tracking_v2`; orgs not using the billable timer will see `—`.
- **On-time rate** depends on `schedule_entries` being populated (scheduling module in use). Unscheduled shops will see `—`.
- Trade-family gating already governs the staff module; no new gating decisions required.

---

## 7. Effort estimate

| Workstream | Estimate |
|---|---|
| Backend stats endpoint + tests | ~2 days |
| Last sign-in + list KPI aggregates | ~0.5 day |
| Staff list restyle (KPIs, pills, pips, avatars, Leave/Export) | ~1.5 days |
| Staff detail Overview restyle + sidebar panels | ~2 days |
| QA, mobile/responsive, dark-mode pass | ~1 day |
| **Total** | **~6–7 working days (~1–1.5 weeks)** |

---

## 8. Recommended next step
Promote this into a formal spec (`.kiro/specs/staff-redesign/` with requirements → design → tasks). The metric definitions in §4 are ready to become the acceptance criteria for the stats endpoint.
