# Staff & Contractor Management System — Investigation & Plan

**Status:** Phase 1 — Shipped. See `CHANGELOG.md` 1.14.0 (2026-05-31). Phases 2–5 still pending.
**Date:** 2026-05-30 (investigation), 2026-05-31 (Phase 1 shipped)
**Scope:** Turn the current staff module into a tabbed employee-management system covering rosters, leave, clock in/out, hours approval, and payslips — to NZ Holidays Act + Wages Protection Act compliance.
**Non-goal:** Becoming a full HR/payroll product. We are building the operational core that a small business genuinely needs to run staff legally and pay them correctly; not performance reviews, recruitment, learning management, etc.
**Trade-family scope:** Universal across all 16 trade families per [.kiro/steering/trade-family-gating-for-new-features.md](../../.kiro/steering/trade-family-gating-for-new-features.md). No `isAutomotive` / `isTargetTrade` gating in any of the staff UI — every business with staff needs this. Module gate via `staff_management` (basic) and `payroll` (Phase 4+) is the only conditional rendering.

---

## §0 — Alignment with .kiro/steering conventions

This plan complies with every steering doc that applies to a multi-module feature. Below is the explicit mapping, so a reviewer can audit each item before implementation begins. Each rule shows where it lands in the plan.

| Steering doc | Rule | Where this plan honours it |
|---|---|---|
| [project-overview.md](../../.kiro/steering/project-overview.md) | All API list responses wrap arrays in objects | All list endpoints in this plan return `{ items: [...], total: N }` or named-list shape (`{ leave_balances: [...], total: N }`). Never bare arrays. |
| project-overview.md | `await db.refresh(obj)` after `db.flush()` before returning ORM objects | Every service function that creates/updates rows uses this pattern (see Phase 1 task acceptance criteria). |
| project-overview.md | Migrations idempotent (`IF NOT EXISTS` for CREATE TABLE) | All schema in §3 uses `CREATE TABLE IF NOT EXISTS`. |
| project-overview.md | Integration API keys stored encrypted in DB, configured via GUI — never read from `.env` | Staff PII (IRD number, bank account) uses envelope encryption (`app/core/encryption.py`). Org-level config (overtime threshold, pay periods, leave types) lives in DB tables, configured via Settings UI. **Zero new env vars** introduced by this plan. |
| [setup-guide-for-new-modules.md](../../.kiro/steering/setup-guide-for-new-modules.md) | Every non-core, non-trade-gated module needs `setup_question` + `setup_question_description` in `module_registry` | Phase 1 migration inserts two modules (`staff_management`, `payroll`) into `module_registry` with the required fields — see §0.1 below. |
| setup-guide-for-new-modules.md | Module must be in at least one subscription plan's `enabled_modules` | Same Phase 1 migration appends both slugs to the default subscription plan's `enabled_modules` JSONB. |
| [implementation-completeness-checklist.md](../../.kiro/steering/implementation-completeness-checklist.md) | Rule 4: No "Coming soon" placeholder pages | Phase 1 does NOT render placeholder tabs for Phase 2–4 content. The Roster tab ships fully functional in Phase 1; Leave/Hours/Payslips tabs are simply not rendered until their phase ships (controlled by feature flag). |
| implementation-completeness-checklist.md | Rule 8: Feature flag ↔ module enablement bridge | Phase 1 migration inserts rows into BOTH `module_registry` AND `feature_flags`. The check at every gate-site queries either-being-true = enabled. |
| implementation-completeness-checklist.md | Rule 9: Every task includes `Verify:` line | All acceptance criteria below carry browser-test verification lines (URL, action, expected outcome, log line to grep). |
| implementation-completeness-checklist.md | Rule 1: Never mark a task done without a browser test | The phase acceptance gates require browser-tested end-to-end flows, not "code compiled cleanly". |
| [database-migration-checklist.md](../../.kiro/steering/database-migration-checklist.md) | Index DDL must use `CREATE INDEX CONCURRENTLY` inside `autocommit_block()` | Every index migration in this plan follows the canonical template from `alembic/versions/2026_05_30_2300-0202_add_perf_indexes.py`. **Zero uses of `op.create_index(...)`.** |
| database-migration-checklist.md | After creating an Alembic migration, run `alembic upgrade head` in the dev container | Phase rollout sequence calls this out as a mandatory step before frontend work begins per phase. |
| [security-hardening-checklist.md](../../.kiro/steering/security-hardening-checklist.md) | §2: Envelope encryption for stored credentials & PII | IRD number, bank account number, clock PIN (post-bcrypt) all stored encrypted-at-rest via `envelope_encrypt_str`. |
| security-hardening-checklist.md | §2: Never store masked values back to DB | When the Overview tab re-saves a form containing masked IRD/bank-account values (`****1234`), the backend detects the mask pattern and skips the update for that field. |
| security-hardening-checklist.md | §2: Mask PII in API responses | IRD numbers returned as `***1234` (last 3 digits); bank accounts as `**-****-****56-00`. Full values only behind a specific "decrypt-for-payslip" service call. |
| security-hardening-checklist.md | §4: When adding a new role, audit all middleware/role-lists | This plan does **not** introduce a new role. Permissions use existing roles (`org_admin`, `branch_admin`, `location_manager`, `staff_member`, `franchise_admin`) per `auth/service.py:2631`. Family-violence-leave visibility is restricted via a per-org `Settings → People → Permissions` toggle, not a new role. |
| [frontend-backend-contract-alignment.md](../../.kiro/steering/frontend-backend-contract-alignment.md) | Rule 8: New response fields must be added to Pydantic schemas | Every service-dict field listed in this plan must have a matching Pydantic schema field; the spec template for each phase has a pre-merge checklist verifying this. |
| frontend-backend-contract-alignment.md | Rule 3: `/api/v2/` endpoints need `baseURL: '/api/v2'` override | All new endpoints land at `/api/v2/...` (current v2-only modules per [mobile-app.md](../../.kiro/steering/mobile-app.md)). Frontend uses the v2 client. |
| [safe-api-consumption.md](../../.kiro/steering/safe-api-consumption.md) | All API consumption must use `?.` + `?? []` + `?? 0`; AbortController in useEffect; no `as any` | Every frontend snippet shown in this plan follows the pattern. The acceptance checklist at the end of each phase requires this. |
| [feature-testing-workflow.md](../../.kiro/steering/feature-testing-workflow.md) | Every feature must have a `scripts/test_*_e2e.py` script with cleanup | Each phase ships its own e2e script: `test_staff_employment_record_e2e.py`, `test_staff_leave_e2e.py`, `test_staff_clock_in_out_e2e.py`, `test_staff_payslip_e2e.py`, `test_staff_reporting_e2e.py`. All test data prefixed `TEST_E2E_`; all cleaned up in `finally` block. |
| [performance-and-resilience.md](../../.kiro/steering/performance-and-resilience.md) | Use SAVEPOINTs (`begin_nested()`), not `db.rollback()` inside session context | Leave accrual loop and bulk payslip generation iterate via SAVEPOINTs so one staff's failure doesn't kill the batch. |
| performance-and-resilience.md | Synchronous I/O is offloaded to background tasks | PDF payslip rendering uses `asyncio.to_thread` (per PERFORMANCE_AUDIT.md B-H1); bulk emails go through the unified `send_email` queue. |
| performance-and-resilience.md | Cache org-level config with TTL | Pay-period config, leave-type config, and overtime policy are cached in Redis with 5-min TTL, invalidated on settings save. |
| [integration-credentials-architecture.md](../../.kiro/steering/integration-credentials-architecture.md) | Use unified `send_email(db, message, ...)` from `app/integrations/email_sender.py` | All payslip emails, leave-decision emails, and roster emails route through the unified sender. **No `smtplib` imports.** |
| integration-credentials-architecture.md | Use the SMS providers table pattern | Roster SMS, late-arrival SMS, payslip-ready SMS all route through `app/modules/sms_providers/`. Multi-active failover via priority slider in the existing admin page. |
| [issue-tracking-workflow.md](../../.kiro/steering/issue-tracking-workflow.md) | Every bug discovered during implementation logged in `docs/ISSUE_TRACKER.md` | Reserved issue IDs allocated per phase before work begins so they don't clash with parallel work. |
| [versioning-and-changelog.md](../../.kiro/steering/versioning-and-changelog.md) | Each MINOR feature bump synchronises `pyproject.toml` + `frontend/package.json` + `mobile/package.json` + `CHANGELOG.md` | Each phase ships as a MINOR bump: Phase 1 → 1.14.0, Phase 2 → 1.15.0, Phase 3 → 1.16.0, Phase 4 → 1.17.0, Phase 5 → 1.18.0 (assuming current 1.13.0). Each phase commit includes the version sync + CHANGELOG entry. |
| [mobile-app.md](../../.kiro/steering/mobile-app.md) | Mobile is for org users only; all interactive elements 44×44; safe-area insets respected | Phase 3 mobile clock-in/out screen follows the existing mobile screen pattern (PullRefresh + MobileButton + MobileSpinner + MobileList). Lazy import in `StackRoutes.tsx`. Module-gated by `staff_management`. |
| mobile-app.md | Capacitor camera/GPS/biometrics behind `isNativePlatform()` guard | Photo capture and geofence checks for clock-in are guarded; web-browser clock-in falls back to PIN-only. |
| [dashboard-widget-gating.md](../../.kiro/steering/dashboard-widget-gating.md) | Dashboard widgets follow the 10-step process with module slug gating | Phase 5 labour-cost + wage-forecast widgets are added to `WIDGET_DEFINITIONS` with module slug `staff_management`. |
| [spec-completeness-checklist.md](../../.kiro/steering/spec-completeness-checklist.md) | Design docs must include Navigation, Component Tree, User Workflow Trace, Modal Inventory, Toolbar/List/Error spec | §5 (Frontend restructure) covers the tab layout; each phase's design doc (written before implementation starts) will include all 8 mandatory sections. |
| [no-shortcut-implementations.md](../../.kiro/steering/no-shortcut-implementations.md) | Large component changes require a spec | Each phase ships with a `.kiro/specs/staff-management-pX/` folder containing requirements.md, design.md, tasks.md before any code is written. |

### 0.1 Module registry inserts (Phase 1 migration body)

The Phase 1 migration that adds the new staff-management surfaces MUST include the following module-registry inserts so the Setup Guide picks them up automatically per [setup-guide-for-new-modules.md](../../.kiro/steering/setup-guide-for-new-modules.md):

```python
op.execute("""
    INSERT INTO module_registry (
        id, slug, display_name, description, category, is_core,
        dependencies, incompatibilities, status,
        setup_question, setup_question_description
    )
    VALUES (
        gen_random_uuid(),
        'staff_management',
        'Staff Management',
        'Employee records, rosters, leave, time tracking, and hours approval.',
        'operations',
        false,
        '[]'::jsonb,
        '[]'::jsonb,
        'available',
        'Do you employ staff or contractors that you need to roster and pay?',
        'Manage employee records, rosters, leave balances, clock-in/out, and weekly hours approval — built to NZ employment law.'
    )
    ON CONFLICT (slug) DO NOTHING;
""")

op.execute("""
    INSERT INTO module_registry (
        id, slug, display_name, description, category, is_core,
        dependencies, incompatibilities, status,
        setup_question, setup_question_description
    )
    VALUES (
        gen_random_uuid(),
        'payroll',
        'Payroll & Payslips',
        'Generate Wages-Protection-Act-compliant payslips, allowances, deductions, and termination payouts.',
        'operations',
        false,
        '["staff_management"]'::jsonb,
        '[]'::jsonb,
        'available',
        'Would you like to generate payslips for your staff inside this app?',
        'Produce payslips that meet the NZ Wages Protection Act + Holidays Act s130A, including leave balances, KiwiSaver, allowances, and termination payouts.'
    )
    ON CONFLICT (slug) DO NOTHING;
""")

# Add to the default subscription plan's enabled_modules so new orgs get the
# setup-guide questions. Existing orgs need a separate enable step.
op.execute("""
    UPDATE subscription_plans
    SET enabled_modules = enabled_modules || '["staff_management","payroll"]'::jsonb
    WHERE slug = 'default'  -- adjust to your real default plan slug
      AND NOT (enabled_modules @> '["staff_management"]'::jsonb);
""")

# Feature-flag mirrors (per implementation-completeness Rule 8 — the
# enablement check queries BOTH module_registry and feature_flags).
op.execute("""
    INSERT INTO feature_flags (id, key, description, default_enabled, scope)
    VALUES
        (gen_random_uuid(), 'staff_management', 'Staff Management module', false, 'org'),
        (gen_random_uuid(), 'payroll', 'Payroll & Payslips module', false, 'org')
    ON CONFLICT (key) DO NOTHING;
""")
```

The `payroll` module declares `dependencies: ["staff_management"]` — enabling Payroll auto-enables Staff Management for that org.

### 0.2 RLS posture

All new tables in this plan have `ENABLE ROW LEVEL SECURITY` + a `tenant_isolation` policy from creation, per the pattern in `alembic/versions/2025_01_15_0008-0008_create_rls_policies.py`. Once the broader `FORCE ROW LEVEL SECURITY` migration from [PERFORMANCE_AUDIT.md](../PERFORMANCE_AUDIT.md) Theme A lands, this module's tables will be included in the lock-down.

### 0.3 Index migrations — canonical template

Every index migration follows the template from `alembic/versions/2026_05_30_2300-0202_add_perf_indexes.py`. No `op.create_index(...)` calls anywhere in this plan. Each index runs as raw SQL `CREATE INDEX CONCURRENTLY IF NOT EXISTS ...` inside `with op.get_context().autocommit_block():`.

### 0.4 Encryption helpers for PII

Three new pieces of staff PII need envelope encryption:

| Field | Pattern |
|---|---|
| `staff_members.ird_number_encrypted` (bytea) | `envelope_encrypt_str(ird_number_str)` on save; `envelope_decrypt_str(...)` only inside the payslip-rendering service path. Mask in all other responses as `***1234`. |
| `staff_members.bank_account_number_encrypted` (bytea) | Same pattern. Mask as `**-****-****56-00`. |
| `staff_members.clock_pin_hash` (text) | bcrypt hash, not reversible. Verify-on-clock-in via `bcrypt.checkpw` wrapped in `asyncio.to_thread` (per PERFORMANCE_AUDIT.md B-H2). |

The Settings → People form must detect the mask pattern on save (regex `^\*+$|^.{0,4}\*{4,}$|^\*{2,}-\*+-\*+\d{2}-\*+$`) and skip the update for that field — never overwrite a real value with the mask string. Pattern documented in [security-hardening-checklist.md §2](../../.kiro/steering/security-hardening-checklist.md).

---

## §0.5 — End-to-end test scripts (one per phase)

Per [feature-testing-workflow.md](../../.kiro/steering/feature-testing-workflow.md), each phase ships its own e2e script. All test data prefixed `TEST_E2E_`; all cleaned up in `finally` block; all queries verified via asyncpg direct connection; all OWASP Top 10 security checks relevant to the phase included.

| Phase | Script | What it tests |
|---|---|---|
| 1 | `scripts/test_staff_employment_record_e2e.py` | Login as org_admin, create staff with TEST_E2E_ prefix, set tax code + IRD + KiwiSaver + bank acct + employment_start, verify masked response, fetch detail, edit pay rate (verify history row), upload signed agreement, send roster email + SMS, cleanup. |
| 2 | `scripts/test_staff_leave_e2e.py` | Configure leave types, set casual employee 8% flag, advance time to anniversary via mock, verify accrual ledger row, submit leave request, approve, verify balance decrement, verify schedule_entries row created, verify s40A extension fires for public holiday inside leave window, cleanup. |
| 3 | `scripts/test_staff_clock_in_out_e2e.py` | Set up shift in schedule_entries, clock in via PIN, log break, clock out, verify worked_minutes calc with break deduction, attempt buddy-punch (photo mismatch), trigger missed-clock-out reminder, approve week, verify lock prevents edit, cleanup. |
| 4 | `scripts/test_staff_payslip_e2e.py` | Set deductions (PAYE, ACC, KiwiSaver), add allowance + reimbursement, generate payslip from approved week, verify all Wages Protection Act + s130A fields in JSON response, render PDF, email payslip, terminate employment, verify final payslip with 52-week-avg payout, cleanup. |
| 5 | `scripts/test_staff_reporting_e2e.py` | Verify labour-cost-vs-revenue dashboard widget queries return correct totals; bank-file CSV export matches BNZ Multi-Pay format; IRD export matches the myIR upload shape; cleanup. |

Each script follows the structure in `scripts/test_storage_packages_e2e.py` (existing reference). Tests run inside the app container against `http://localhost:8000` (bypassing nginx).

---

---

## 0. TL;DR

- **You already have plenty of plumbing** — staff CRUD with hourly + overtime rates, two scheduling implementations (one is good and being used), a timer-based time-tracking module, a public-holidays sync, and an availability-schedule structure on each staff record.
- **What's missing is the *employment* layer.** There is no concept of leave types, leave balances, leave accrual, leave requests, clock-in/out vs scheduled hours, weekly hours approval, or payslips. None of that exists in the codebase today (zero hits for "leave_request", "payslip", "leave_balance", "clock_in" except an unrelated dashboard widget).
- **Real NZ compliance** sits on top of that missing layer — anniversary-based annual leave accrual, sick-leave kick-in after 6 months, public-holiday "otherwise working day" detection with time-and-a-half + alternative-holiday-day, payslip content requirements under the Wages Protection Act.
- **Realistic delivery:** 4 phases over ~8–12 dev-weeks. Phase 1 (tab restructure + leave types + balances) unblocks the experience, Phase 4 (payslips) is the largest single piece.

---

## 1. What already exists today

### 1.1 Staff data model
- [app/modules/staff/models.py](../../app/modules/staff/models.py) — `staff_members` and `staff_location_assignments`.
- Per staff member already stored: name, email, phone, employee_id, position, reporting_to, role_type (`employee`/`contractor`), `hourly_rate`, `overtime_rate`, `shift_start`/`shift_end` (default daily times as strings like "09:00"), `availability_schedule` (JSONB weekly template), `skills` (JSONB list), `is_active`, optional `user_id` (link to a login).
- Self-referential `reporting_to` (manager).
- Multi-location via `staff_location_assignments`.

### 1.2 Staff API
- [app/modules/staff/router.py](../../app/modules/staff/router.py) — CRUD, deactivate/activate, permanent delete, location assign/remove, **utilisation report**, **labour-cost report**, **create-account** (turns a staff record into a login).
- [app/modules/staff/service.py](../../app/modules/staff/service.py) — `calculate_utilisation` (billable hours / available hours from `availability_schedule`), `get_labour_costs` (sum minutes × `hourly_rate`).

### 1.3 Frontend staff
- [frontend/src/pages/staff/StaffList.tsx](../../frontend/src/pages/staff/StaffList.tsx) — list, filters, search.
- [frontend/src/pages/staff/StaffDetail.tsx](../../frontend/src/pages/staff/StaffDetail.tsx) — single-page form with three sections (Personal Info, Employment Details, Work Schedule). **No tabs.**
- [frontend/src/components/WorkSchedule.tsx](../../frontend/src/components/WorkSchedule.tsx) — weekly grid editor for `availability_schedule`.

### 1.4 Scheduling (two implementations co-exist)
- **v1**: [app/modules/scheduling/](../../app/modules/scheduling/) — branch-based, table is `schedules`, keyed on `user_id`. Older; used by [frontend/src/pages/scheduling/StaffSchedule.tsx](../../frontend/src/pages/scheduling/StaffSchedule.tsx).
- **v2**: [app/modules/scheduling_v2/](../../app/modules/scheduling_v2/) — staff-based, tables are `schedule_entries` and `shift_templates`, includes `entry_type` enum: `job | booking | break | other | leave`. Has reschedule, conflict detection, recurrence_group_id. Used by [frontend/src/pages/schedule/ScheduleCalendar.tsx](../../frontend/src/pages/schedule/ScheduleCalendar.tsx) — drag-drop roster view, staff as columns × time grid.
- **Note:** the leave value in `schedule_entries.entry_type` is a calendar-only marker today — there is no balance, no accrual, no link to a leave-type record. It just colours the cell grey on the calendar.

### 1.5 Time tracking
- [app/modules/time_tracking_v2/](../../app/modules/time_tracking_v2/) — `time_entries` table, start/stop timer, weekly timesheet, billable flag, add-to-invoice. Keyed on `user_id` (with optional `staff_id`).
- Designed for **billable customer work** (job_id, project_id, hourly_rate, is_invoiced, invoice_id). Not designed for "I'm starting/ending my shift today".
- Frontend: [frontend/src/pages/time-tracking/TimeSheet.tsx](../../frontend/src/pages/time-tracking/TimeSheet.tsx) — weekly timesheet, project view, weekly grid, convert-to-invoice.

### 1.6 Public holidays
- [app/modules/admin/models.py:464](../../app/modules/admin/models.py#L464) — `public_holidays` table.
- [app/modules/admin/service.py:4839](../../app/modules/admin/service.py#L4839) — `sync_public_holidays` pulls from Nager.Date API.
- The org dashboard already surfaces "next 5 upcoming public holidays" in [organisations/dashboard_service.py:264](../../app/modules/organisations/dashboard_service.py#L264).

### 1.7 What does NOT exist (verified by grep — zero hits)
- `payslip` / `pay_slip` / `payroll`
- `leave_balance` / `leave_type` / `leave_request`
- `clock_in` / `clock_out` / `attendance` (the one hit is an unrelated dashboard widget that reuses TimeEntry as an *approximation* of clock-in)
- Approval workflow for hours
- Email-roster-to-staff endpoint

---

## 2. Gap analysis vs. what you asked for

| You want | Exists today | Gap |
|---|---|---|
| **Staff page with tabs** (Personal, Roster, Leave, Hours, Payslips) | Single-form `StaffDetail.tsx`, no tabs | Restructure UI to tabbed layout (Phase 1) |
| **Roster/schedule per staff** | Org-wide grid view exists (`ScheduleCalendar`), no per-staff embed | Surface the same data, filtered to one staff, on the Roster tab |
| **Clear view of the roster** | `ScheduleCalendar` already provides this | Reuse — add print/export views |
| **Email roster to staff** | No endpoint | New endpoint + email template (Phase 1) |
| **Record leave** | `entry_type='leave'` only — calendar colour | Full leave system: types, balances, accrual, requests, approval (Phase 2) |
| **Configurable leave types in Settings** | No UI, no model | New `leave_types` table per-org + settings page (Phase 2) |
| **Auto-calc hours worked** | Timer exists for billable work; not for attendance | New `time_clock_entries` table for clock-in/out, separate from timer (Phase 3) |
| **Clock in/clock out system** | Timer is the closest primitive | Build dedicated UI (badge tap / kiosk PIN / mobile button), keyed on staff (Phase 3) |
| **Actual vs scheduled hours** | No comparison view | New report joining schedule_entries × time_clock_entries (Phase 3) |
| **Approve hours end of week** | No approval state | Approval table + locked-after-approval state (Phase 3) |
| **Auto-generate payslips** | Nothing | Largest single piece — see Phase 4 |
| **NZ leave compliance (auto-increment/auto-deduct)** | Public holidays synced; no accrual logic | Accrual engine running on a scheduler tick (Phase 2 → Phase 3) |
| **Hourly rate already configurable** | ✅ Already on `staff_members` | Reuse |
| **Per-staff employee detail page** | Exists (single page) | Convert to tabs in Phase 1 |

---

## 3. Proposed data model additions

All names final-ish; tweak in implementation. **Every new table below ships with:**

- `CREATE TABLE IF NOT EXISTS` (idempotent, per project-overview.md)
- `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` immediately after creation
- A `tenant_isolation` policy: `USING (org_id = current_setting('app.current_org_id', true)::uuid)`
- All FK/composite indexes via `CREATE INDEX CONCURRENTLY IF NOT EXISTS` inside `autocommit_block()` in a follow-up index migration (per database-migration-checklist.md)
- No `op.create_index(...)` calls
- PII columns (`ird_number_encrypted`, `bank_account_number_encrypted`) use `BYTEA` for envelope-encrypted ciphertext; never plaintext `TEXT`
- `clock_pin_hash` is bcrypt'd; verify with `await asyncio.to_thread(bcrypt.checkpw, ...)` (per PERFORMANCE_AUDIT.md B-H2)

### 3.1 Leave configuration (Phase 2)

```sql
-- Configurable leave types per org — annual, sick, bereavement, parental,
-- family violence, plus org-specific custom types ("Study leave" etc).
CREATE TABLE leave_types (
  id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id                  uuid NOT NULL REFERENCES organisations(id),
  code                    text NOT NULL,                  -- 'annual', 'sick', 'bereavement', 'family_violence', 'parental', 'unpaid', 'public_holiday_alt', 'custom_*'
  name                    text NOT NULL,                  -- "Annual leave"
  is_paid                 boolean NOT NULL DEFAULT true,
  accrual_method          text NOT NULL,                  -- 'anniversary', 'fixed_annual', 'per_period', 'unaccrued', 'event_based'
  accrual_amount          numeric(8,2),                   -- hours or days per accrual period
  accrual_unit            text NOT NULL DEFAULT 'hours',  -- 'hours' | 'days'
  carry_over_max          numeric(8,2),                   -- 0 = use-or-lose, NULL = unlimited
  requires_doctor_note    boolean NOT NULL DEFAULT false, -- Holidays Act s68 — sick leave > 3 consecutive working days
  confidential_visibility boolean NOT NULL DEFAULT false, -- family_violence: filtered to permitted approvers only (see §8.1)
  is_statutory            boolean NOT NULL DEFAULT false, -- true for the 6 NZ statutory types (locked from deletion)
  active                  boolean NOT NULL DEFAULT true,
  display_order           int NOT NULL DEFAULT 0,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  UNIQUE(org_id, code)
);

-- Per-staff entitlement & balance (one row per staff × leave_type).
CREATE TABLE leave_balances (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id            uuid NOT NULL,
  staff_id          uuid NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE,
  leave_type_id     uuid NOT NULL REFERENCES leave_types(id) ON DELETE RESTRICT,
  accrued_hours     numeric(8,2) NOT NULL DEFAULT 0,   -- total ever accrued
  used_hours        numeric(8,2) NOT NULL DEFAULT 0,   -- total ever used (incl. pending-approved)
  pending_hours     numeric(8,2) NOT NULL DEFAULT 0,   -- requested but not yet approved
  -- Anniversary tracking for accrual_method='anniversary'
  anniversary_date  date,                              -- usually employment_start_date
  last_accrual_at   timestamptz,
  updated_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE(staff_id, leave_type_id)
);

-- One per leave request (which can span multiple days).
CREATE TABLE leave_requests (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          uuid NOT NULL,
  staff_id        uuid NOT NULL REFERENCES staff_members(id),
  leave_type_id   uuid NOT NULL REFERENCES leave_types(id),
  start_date      date NOT NULL,
  end_date        date NOT NULL,
  hours_requested numeric(6,2) NOT NULL,
  status          text NOT NULL DEFAULT 'pending',  -- 'pending', 'approved', 'rejected', 'cancelled'
  reason          text,
  attachment_url  text,                             -- e.g. doctor's note for sick leave
  requested_by    uuid NOT NULL REFERENCES users(id),
  decided_by      uuid REFERENCES users(id),
  decided_at      timestamptz,
  decision_notes  text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Append-only ledger of every balance change (accrual, use, manual adj).
-- Lets the UI show "you accrued 6.2h on 1 May, used 8h on 3 May, current
-- balance 142.4h" without recalculating from scratch every time.
CREATE TABLE leave_ledger (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          uuid NOT NULL,
  staff_id        uuid NOT NULL,
  leave_type_id   uuid NOT NULL,
  delta_hours     numeric(8,2) NOT NULL,
  reason          text NOT NULL,                   -- 'accrual', 'request_approved', 'manual_adjustment', 'opening_balance', 'termination_payout'
  request_id      uuid REFERENCES leave_requests(id),
  occurred_at     date NOT NULL,
  created_by      uuid REFERENCES users(id),
  created_at      timestamptz NOT NULL DEFAULT now()
);
```

NZ baseline seeded on org creation: `annual` (4 weeks/year anniversary-based), `sick` (10 days/year, unlocks after 6 months), `bereavement` (3 days unaccrued, per-event), `family_violence` (10 days/year), `unpaid` (unaccrued). All marked `is_statutory=true` so they can't be deleted.

### 3.2 Clock in / clock out (Phase 3)

```sql
-- Dedicated attendance table — separate from time_entries (which is for
-- billable customer work). Keyed on staff_id, not user_id, so contractors
-- without a login can be clocked in at the kiosk.
CREATE TABLE IF NOT EXISTS time_clock_entries (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id              uuid NOT NULL,
  staff_id            uuid NOT NULL REFERENCES staff_members(id),
  clock_in_at         timestamptz NOT NULL,
  clock_out_at        timestamptz,                 -- NULL = currently clocked in
  source              text NOT NULL,               -- 'kiosk', 'self_service_mobile', 'self_service_web', 'admin_manual'
  -- Mandatory photo at kiosk; optional/configurable for self-service; null
  -- for admin_manual.
  clock_in_photo_url  text,
  clock_out_photo_url text,
  -- Geolocation (only populated when self-service with geofence enabled).
  clock_in_lat        numeric(9,6),
  clock_in_lng        numeric(9,6),
  clock_out_lat       numeric(9,6),
  clock_out_lng       numeric(9,6),
  scheduled_entry_id  uuid REFERENCES schedule_entries(id),  -- matched shift, if any
  break_minutes       int NOT NULL DEFAULT 0,      -- unpaid break inside this span
  notes               text,
  -- For admin_manual entries, who created it.
  created_by          uuid REFERENCES users(id),
  -- Calculated on close.
  worked_minutes      int,                         -- (clock_out - clock_in) - break_minutes
  created_at          timestamptz NOT NULL DEFAULT now(),
  CHECK (source IN ('kiosk', 'self_service_mobile', 'self_service_web', 'admin_manual')),
  -- Kiosk entries MUST have a clock-in photo (enforced at app level too;
  -- this is the data-integrity backstop).
  CHECK (source <> 'kiosk' OR clock_in_photo_url IS NOT NULL)
);
ALTER TABLE time_clock_entries ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON time_clock_entries
  USING (org_id = current_setting('app.current_org_id', true)::uuid);

-- Staff record additions for clock-in policy.
ALTER TABLE staff_members
  ADD COLUMN IF NOT EXISTS self_service_clock_enabled boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS on_file_photo_url text,
  ADD COLUMN IF NOT EXISTS employment_start_date date,           -- 6-month sick-leave gate + anniversary
  ADD COLUMN IF NOT EXISTS employment_end_date date,             -- triggers final payslip + leave payout
  ADD COLUMN IF NOT EXISTS standard_hours_per_week numeric(5,2); -- FTE-equivalent leave accrual

-- No clock_pin_hash column — verification at kiosk is photo-based, not
-- PIN-based. The on_file_photo_url provides the comparison reference;
-- the captured clock_in_photo_url is the audit trail.
```

### 3.3 Hours approval (Phase 3)

```sql
-- One row per (staff × week) — locks all time_clock_entries and any
-- billable time_entries inside that window after approval.
CREATE TABLE timesheet_approvals (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          uuid NOT NULL,
  staff_id        uuid NOT NULL REFERENCES staff_members(id),
  week_start      date NOT NULL,                   -- Monday of the week
  week_end        date NOT NULL,                   -- Sunday
  status          text NOT NULL DEFAULT 'pending', -- 'pending', 'approved', 'rejected', 'edited_after_approval'
  total_worked_minutes int,
  total_scheduled_minutes int,
  total_overtime_minutes int NOT NULL DEFAULT 0,
  approved_by     uuid REFERENCES users(id),
  approved_at     timestamptz,
  notes           text,
  UNIQUE(staff_id, week_start)
);
```

### 3.4 Payslips (Phase 4)

```sql
CREATE TABLE pay_periods (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id        uuid NOT NULL,
  start_date    date NOT NULL,
  end_date      date NOT NULL,
  pay_date      date NOT NULL,                     -- when payment goes out
  status        text NOT NULL DEFAULT 'open',      -- 'open', 'finalised', 'paid'
  UNIQUE(org_id, start_date)
);

CREATE TABLE payslips (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id              uuid NOT NULL,
  staff_id            uuid NOT NULL REFERENCES staff_members(id),
  pay_period_id       uuid NOT NULL REFERENCES pay_periods(id),
  -- Hours
  ordinary_hours      numeric(8,2) NOT NULL DEFAULT 0,
  overtime_hours      numeric(8,2) NOT NULL DEFAULT 0,
  public_hol_hours    numeric(8,2) NOT NULL DEFAULT 0,
  -- Pay
  ordinary_rate       numeric(10,2),
  overtime_rate       numeric(10,2),
  gross_pay           numeric(12,2) NOT NULL,
  -- Leave taken in this period (informational)
  leave_lines_json    jsonb NOT NULL DEFAULT '[]'::jsonb,
  -- Deductions (informational; NOT a payroll-tax calculator)
  deductions_json     jsonb NOT NULL DEFAULT '[]'::jsonb,
  -- Reimbursements
  reimbursements_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  -- Final
  net_pay             numeric(12,2) NOT NULL,
  pdf_url             text,
  emailed_at          timestamptz,
  finalised_at        timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now()
);
```

---

## 4. NZ employment-law specifics the engine must honour

This is the part most generic SaaS tools get wrong. Below is the minimum compliance baseline. Where I'm not 100% sure, I've called it out — please confirm with an employment-law adviser before launch.

### 4.1 Annual leave (Holidays Act 2003, s16)
- **4 weeks** per year for permanent employees, accrued on anniversary of start date.
- Accrual hours = `standard_hours_per_week × 4` granted in one chunk on each anniversary (not pro-rata per pay period). Holidays Act calls this "entitlement leave".
- Pre-anniversary period: leave is "in advance" — can be granted but not legally entitled until anniversary.
- On termination: pay out the unused portion at the **greater of ordinary weekly pay or average weekly earnings over the last 52 weeks**.
- Casual employees with no set hours: paid 8% of gross earnings instead (pay-as-you-go) — different mechanism, will need a `casual` flag on `staff_members`.

### 4.2 Sick leave (Holidays Act 2003, s63 + s68)
- **10 days/year** (changed from 5 in July 2021).
- **Kicks in after 6 months of continuous employment** — accrual must be gated on `employment_start_date + 6 months`.
- Carries over up to 20 days max.
- Family members count — sick leave covers caring for spouse, child, parent, etc.
- **Doctor's-note requirement (s68):** if an employee is absent for 3 or more consecutive working days, the employer may require proof of sickness. Surfaced via `leave_types.requires_doctor_note=true` on the sick row; the leave-request UI shows an "Attach doctor's note" upload slot when ticked, and the approval queue surfaces a yellow warning (not a block) when the request exceeds 3 consecutive working days without an attachment.

### 4.3 Bereavement leave (Holidays Act 2003, s70)
- **3 days** per event for close family (spouse, parent, child, sibling, grandparent, grandchild, in-law).
- **1 day** per event for any other person if the employer accepts the bereavement.
- Not accrued — granted per event. Implementation: `accrual_method='unaccrued'` on the leave type; balance always 0; requests draw against the per-event limit not a running balance.

### 4.4 Family violence leave (Domestic Violence — Victims' Protection Act 2018)
- **10 days/year** for any employee affected by family violence.
- After 6 months' employment, same as sick leave.
- Confidential — UI must restrict visibility to the approver only.

### 4.5 Public holidays (Holidays Act 2003, ss43–44)
- 11 named days; Nager.Date already syncs them ([admin/service.py:4839](../../app/modules/admin/service.py#L4839)).
- **If the employee normally works on that day of the week ("otherwise working day"):**
  - If they take the day off, paid at "relevant daily pay".
  - If they work, paid at **time-and-a-half** AND entitled to an **alternative holiday day** (also called a "day in lieu") — this is a new leave-balance line type (`public_holiday_alt`).
- **If it's not an otherwise-working day for them:** no holiday pay, no time-and-a-half, no alt day.
- "Otherwise working day" detection is a real engine: looks at the employee's pattern over the last 4 weeks of `time_clock_entries` (or their `availability_schedule` if no actual data yet) for the same weekday.

### 4.6 Payslip content (Wages Protection Act 1983, ss23-31; & Holidays Act s130A)
A payslip **must** show, for each pay period:
- Employee's name + pay-period dates
- Hours worked (by type: ordinary, overtime, public holiday)
- Hourly rate(s)
- Gross earnings
- All deductions (PAYE, ACC levy, KiwiSaver, student loan, child support, other voluntary)
- Net pay
- Leave taken during the period AND **remaining balances** (Holidays Act s130A — this is the often-missed requirement)
- Anniversary date for annual leave

We are **not** calculating PAYE/ACC/KiwiSaver ourselves — that's a regulated tax-engine concern. The payslip layer will accept deductions as a structured input (`deductions_json`) so the org can either enter them manually or, later, integrate with a payroll provider (Smartly, iPayroll, Crystal, etc.) that gives them the right tax numbers.

### 4.7 Termination payouts (Holidays Act s27)
- Final pay must include all accrued-and-untaken annual leave, paid at the greater of ordinary weekly / 52-week average.
- Unused alternative holidays converted to pay at relevant daily pay.
- Phase 4 must support a "Terminate employment" workflow that closes leave balances correctly and produces a final payslip.

### 4.8 Record-keeping (Employment Relations Act 2000, s130; Holidays Act s81)
- 6 years' retention for wage and time records.
- Implementation: all relevant tables already write `created_at`/`updated_at`; we'll need a per-row immutability convention on `payslips` and `leave_ledger` (append-only, no UPDATE/DELETE in the app code; manual ops via DB only).

---

## 5. Frontend restructure — tabbed Staff Detail

Convert [StaffDetail.tsx](../../frontend/src/pages/staff/StaffDetail.tsx) from a single scrolling form into a tabbed layout:

```
┌─────────────────────────────────────────────────────────────┐
│  ← Back   Jane Doe  [Active]            [Edit] [Deactivate] │
├─────────────────────────────────────────────────────────────┤
│ ┌Overview─┐ ┌Roster─┐ ┌Leave─┐ ┌Hours─┐ ┌Payslips─┐ ┌Docs┐  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  (tab content)                                              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

| Tab | What it shows | Backed by |
|---|---|---|
| **Overview** | Current `StaffDetail.tsx` form fields (personal, employment, work-schedule template). Plus: employment start date, std hours/week, quick-stat tiles (hours this week, leave balances summary, upcoming public holidays). | Existing `/api/v2/staff/:id` + new fields on `staff_members`. |
| **Roster** | This staff member's `schedule_entries` for the selected week. Embed the existing roster grid filtered to one staff column. Buttons: "Add shift", "Apply template", **"Email this week's roster"**. | Existing scheduling_v2 `/api/v2/scheduling/entries?staff_id=...` + new `POST /api/v2/staff/:id/email-roster`. |
| **Leave** | Balance card per leave_type (annual, sick, bereavement, family violence). Below: history table of `leave_ledger`. Bottom: "Request leave" + "Adjust balance" (admin only) buttons. | New `/api/v2/staff/:id/leave/balances`, `/leave/ledger`, `/leave/requests`. |
| **Hours** | Week selector. Two stacked rows: **Scheduled** (from `schedule_entries`) and **Actual** (from `time_clock_entries`). Diff column shows variance. At week's end: "Approve hours" button (admin only). Below: list of `time_clock_entries` with clock-in/out times and any manual adjustments. | New `/api/v2/staff/:id/timeclock`, `/timesheet-approvals`. |
| **Payslips** | List of past payslips with PDF download + "Email payslip" button. "Generate payslip" for current open `pay_periods`. | New `/api/v2/staff/:id/payslips`. |
| **Documents** *(optional, Phase 4+)* | Employment agreement, IRD form, KiwiSaver opt-in, certifications. Out of scope for this round. | Reuses [app/modules/uploads](../../app/modules/uploads/) infrastructure. |

Settings page additions:
- **Settings → People → Leave Types**: list of `leave_types` with edit/disable/reorder. Statutory types locked from delete but accrual rates editable above the legal minimum (e.g., org gives 5 weeks annual instead of 4).
- **Settings → People → Pay periods**: weekly / fortnightly / monthly, what day they end on, when pay is run. Drives the `pay_periods` cron.
- **Settings → People → Clock-in policy** (new — added in Phase 3, but the per-staff `self_service_clock_enabled` checkbox ships in Phase 1):
  - `default_channel`: `kiosk_only` (default) | `kiosk_and_self_service`
  - `self_service_require_photo`: bool (default true)
  - `self_service_require_geofence`: bool (default false) + branch lat/lng + radius metres
  - `allow_late_clock_out_edits`: bool (default true, manager-only)
  - `kiosk_employee_id_rate_limit`: int per minute (default 10)

---

## 6. Phased delivery plan

Four phases. Phases 1 and 2 deliver visible UX immediately; Phases 3 and 4 are the meatier engineering work.

### Phase 1 — Tab restructure + employee-file completeness + roster email/SMS (2–3 weeks)

**Goal:** Better UX **and** the employment-record fields that everything else depends on.

- Convert `StaffDetail.tsx` from single-form to tabbed layout. Existing form becomes the **Overview** tab.
- **Expand the Overview tab to a real employee record.** Add these fields (migration + UI):
  - `employment_start_date`, `employment_end_date`, `employment_type` ('permanent' | 'casual' | 'fixed_term'), `standard_hours_per_week`
  - `tax_code` ('M', 'ME', 'S', 'SH', 'ST', 'SB', 'CAE', 'NSW') — required for payslips
  - `ird_number` (encrypted-at-rest), `student_loan` (bool)
  - `kiwisaver_enrolled` (bool), `kiwisaver_employee_rate` (3/4/6/8/10%), `kiwisaver_employer_rate` (default 3%)
  - `bank_account_number` (encrypted) — even if we don't generate bank files, payslips need it
  - `probation_end_date` (90-day trial — auto-set to `start_date + 90d` on creation, editable)
  - `visa_expiry_date` (nullable — only shown for non-NZ residents)
  - `self_service_clock_enabled` (bool, **default false**) — when false (the default), this staff can ONLY clock in/out via the on-site kiosk; when true, the staff can also clock in/out from their own login. Drives the visibility of the Clock In button on the staff-self-service dashboard.
  - `on_file_photo_url` (text, nullable) — admin uploads a clear face photo when onboarding the staff member. Used for visual comparison against the photo captured at every kiosk clock-in (manager-only visibility during weekly approval review).
  - `emergency_contact_name`, `emergency_contact_phone`
- **`employee_id` becomes effectively required for any staff who will clock in/out.** The existing `employee_id` column is already nullable, but the Phase 1 UI will surface a warning badge ("No employee code set — clock-in disabled") on the staff card if the staff is active and `employee_id IS NULL`. The kiosk clock-in flow refuses to process any staff without an `employee_id`. The existing `/api/v2/staff/check-duplicate?field=employee_id&value=...` endpoint already enforces per-org uniqueness across active staff.
- **Pay rate history** (small new table `staff_pay_rates`): every change to `hourly_rate` / `overtime_rate` writes a row with `effective_from` and `changed_by`. Used for anniversary review reminders and audit.
- **Document upload** on Overview tab — at minimum a slot for the signed employment agreement (mandatory under ERA s64). Reuses [app/modules/uploads](../../app/modules/uploads/). Counter on the staff list: "3 staff without signed agreement on file" — gentle nag, not a block.
- **Minimum-wage warning**: if `hourly_rate < current NZ minimum wage` (configurable in `Settings → People`, defaults to $23.15 from 1 April 2024), show a red badge on the staff card and a confirmation prompt when saving.
- **Roster** tab — embed the existing `ScheduleCalendar` filtered to one staff. Reuse all backend.
- **Roster delivery** — two endpoints, not one:
  - `POST /api/v2/staff/:id/email-roster` — Jinja HTML email via [app/integrations/email_sender.py](../../app/integrations/email_sender.py).
  - `POST /api/v2/staff/:id/sms-roster` — short SMS with this-week summary + tokenised link to view full schedule via the [app/modules/sms_providers](../../app/modules/sms_providers/) layer.
  - Optional toggles on `staff_members`: `weekly_roster_email_enabled`, `weekly_roster_sms_enabled`. Auto Friday-afternoon broadcast via a new scheduled task.
- Add tab skeletons for **Leave**, **Hours**, **Payslips** showing "Coming soon" with a brief description so users see the roadmap.

**Acceptance:** Tabbed UI live; every employee record has the fields a payslip will need; minimum-wage warning fires; roster can be sent via email OR SMS; pay-rate-change writes audit history.

**Verify** (per implementation-completeness Rule 9):
- Navigate to `/staff/<id>` in browser → tabs render → switch to Roster tab → calendar loads for current week.
- POST `/api/v2/staff` with new staff payload including `tax_code='M'`, `ird_number='123-456-789'`, `kiwisaver_enrolled=true`, `employee_id='EMP-001'` → expect 201; GET same staff → expect masked `ird_number: '***789'` and `self_service_clock_enabled: false` (default).
- POST a new staff WITHOUT `employee_id` → row persists but list view shows "No employee code set — clock-in disabled" warning badge on the card.
- Toggle "Enable clock in/out via own login" checkbox on Overview tab → PUT staff → verify `self_service_clock_enabled=true` in DB; verify the staff-self-service dashboard now shows the "Clock In" button for that user (other staff still don't see it).
- Upload an on-file photo via Overview tab → check `staff_members.on_file_photo_url` is populated → confirm it renders as a thumbnail on the staff card.
- Save staff with `hourly_rate=20.00` (below NZ minimum) → expect modal warning before save; confirm → row persists with warning audit-logged.
- Click "Email roster" → check email_provider logs for `send_email` call → confirm template renders week's `schedule_entries`.
- Click "Send roster SMS" → check `sms_providers` logs → confirm SMS body has correct shift summary + tokenised link.
- Update `hourly_rate` from $25 to $27.50 → query `staff_pay_rates` directly → expect a new row with `effective_from=today` and `changed_by=current_user`.
- Run `scripts/test_staff_employment_record_e2e.py` → expect "passed: N, failed: 0".

**Module registration check before merge:**
- `SELECT slug, setup_question FROM module_registry WHERE slug IN ('staff_management', 'payroll');` → 2 rows.
- `SELECT key FROM feature_flags WHERE key IN ('staff_management', 'payroll');` → 2 rows.
- Default subscription plan's `enabled_modules` includes both slugs.

**Version bump:** `pyproject.toml` + `frontend/package.json` + `mobile/package.json` → 1.13.0 → 1.14.0; `CHANGELOG.md` entry under `## [1.14.0]` with bullet list of features added.

### Phase 2 — Leave, TOIL, casual flow, Holidays-Act edge cases (4–5 weeks) — **✅ SHIPPED 2026-05-31 (v1.15.0)**

**Goal:** All NZ leave types in one consistent engine, including the edge cases SMEs get audited on.

**Status (2026-05-31):** Phase 2 shipped. Migrations 0205+0206 applied to dev, prod-standby (local), and Pi dev-standby. Pi PROD primary upgrade pending the next maintenance window. All four leave tables shipped (`leave_types`, `leave_balances`, `leave_requests`, `leave_ledger`) plus `staff_members.average_daily_pay_snapshot` and `organisations.overtime_handling` columns. Leave service + accrual engine + public-holiday engine + approval queue + settings pages live. `leave.fv_view` permission backfilled for current org_admins. Confidential-leave audit redaction enforced via `_audit_after_value` helper + lint test. Property tests pass under Hypothesis (3 invariants × 20 examples). E2E browser script (`scripts/test_staff_leave_e2e.py`) deferred to Phase 3 cut-over (rationale logged in `.kiro/specs/staff-management-p2/gap-analysis.md`). Auto-advancing to Phase 3.

- Migration: `leave_types`, `leave_balances`, `leave_requests`, `leave_ledger` (per §3.1).
- Org-creation seed: **6** NZ statutory leave types (locked, not 5):
  - `annual` (4 weeks/year, anniversary)
  - `sick` (10 days/year, kicks in at 6 months)
  - `bereavement` (3/1 days per event, unaccrued)
  - `family_violence` (10 days/year, kicks in at 6 months)
  - `public_holiday_alt` (granted only when employee works an "otherwise working day" public holiday — unaccrued, balance grows from event triggers, not time)
  - `unpaid` (always available, no balance tracking)
- Settings → People → Leave Types page (CRUD, except can't delete statutory).
- Leave tab UI: balance cards, ledger history, request-leave form, admin-side approval queue, attach-document slot for sick-leave notes.
- **TOIL (Time Off In Lieu)** — first-class. Configurable per-org `Settings → People → Overtime policy = pay_cash | toil | employee_chooses`. When overtime hours are approved on a `timesheet_approvals` row (Phase 3) and policy is `toil`, the system writes those hours to the `toil` leave balance (a 7th non-statutory locked type, seeded for every org that picks the `toil` policy). When policy is `employee_chooses`, the approval UI offers a per-week toggle.
- **Casual employees** — first-class. Staff with `employment_type='casual'`:
  - Don't get anniversary annual-leave accrual.
  - Their payslips include an automatic **8% holiday pay** line on gross earnings each pay period (Holidays Act s28).
  - Sick / bereavement / family violence still apply (but pro-rata, accrued in proportion to hours worked).
  - The Leave tab shows "Casual — 8% pay-as-you-go" instead of an annual balance.
- Leave-request approval transition writes to `leave_ledger` and decrements the balance.
- **Leave accrual engine** — a daily scheduled task that:
  - For each `accrual_method='anniversary'`: on `employment_start_date + N years`, grant `standard_hours_per_week × 4` to annual balance.
  - For `accrual_method='per_period'`: on last day of each pay period, grant periodic amount (used for sick leave pro-rata).
  - Sick-leave special case: only accrue after `employment_start_date + 6 months`; standard 10 days for permanent, pro-rata for variable-hours staff.
  - Always write a `leave_ledger` row with `reason='accrual'`.
  - Idempotent — guards against double-accrual on retry.
- Approved leave-requests **also create matching `schedule_entries` with `entry_type='leave'`** so the roster auto-greys those days.
- **Public-holiday engine** — daily task that for each upcoming public holiday:
  - Detects each staff member's "otherwise working day" status from the rolling 4-week pattern (or `availability_schedule` template if no time-clock history yet).
  - If it's their OWD and they're scheduled to work → flags the day in the roster as "time-and-a-half + alt day eligible".
  - If it's their OWD and they're scheduled OFF → calculates "relevant daily pay" (a saved per-staff snapshot for payslip use).
  - If it's NOT their OWD → no holiday pay due, but stays in the calendar for visibility.
- **Public holiday during annual leave (Holidays Act s40A):** if an approved annual-leave request includes a date that's a public holiday on the employee's OWD, the engine **extends the leave by one paid day** automatically and writes a `leave_ledger` adjustment row.
- **Average daily pay calculation:** new helper that computes "average daily pay" from the last 52 weeks of pay (gross / days worked), saved as `staff.average_daily_pay_snapshot` daily. Used for public-holiday pay where ordinary daily pay can't be determined.

**Acceptance:** All 6 statutory types work; casual employees see 8% line on their payslip preview; TOIL accrues from approved overtime; public-holiday engine grants alt days correctly; s40A extension fires when a public holiday falls inside annual leave.

**Verify:**
- After Phase 1 migration runs, query `SELECT slug, name FROM leave_types WHERE org_id = '<test_org>' AND is_statutory = true;` → expect 6 rows (annual, sick, bereavement, family_violence, public_holiday_alt, unpaid).
- Navigate to Settings → People → Leave Types → attempt to delete `annual` row → expect 403 with "Statutory leave type cannot be deleted".
- Create a test staff with `employment_start_date = today - 12 months`. Run the leave-accrual scheduled task → query `leave_balances` for that staff → expect `accrued_hours = standard_hours_per_week × 4` for annual leave.
- Create a casual staff (`employment_type='casual'`) → navigate to Leave tab → expect "Casual — 8% pay-as-you-go" banner, no annual-leave balance card.
- Insert an approved annual-leave request spanning a date that's a NZ public holiday on the staff's OWD → check `leave_ledger` for an automatic `reason='public_holiday_extension'` row + `schedule_entries.entry_type='leave'` extension entry.
- Run `scripts/test_staff_leave_e2e.py` → expect "passed: N, failed: 0".
- Check `audit_logs` for `leave_type.created`, `leave_request.submitted`, `leave_request.approved` rows.

**Background-task safety check:** the daily leave-accrual task wraps each per-staff body in `db.begin_nested()` SAVEPOINT — one staff's failure must not poison the rest (per performance-and-resilience §1).

**Version bump:** 1.14.0 → 1.15.0.

### Phase 3 — Clock in/out + scheduled-vs-actual + approval + the operational layer SMEs spend their week on (4–5 weeks)

**Goal:** Capture actual hours, compare to schedule, lock approved weeks, **and** add the day-to-day workflows owners spend their time on.

- Migration: `time_clock_entries`, `timesheet_approvals`, `shift_swap_requests`, `shift_cover_requests`, `break_records` (per §3.2 + §3.3 + extensions below).

### Default policy: kiosk-only clock-in

**This is the design decision that drives the whole Phase 3 surface.** Every staff member is **kiosk-only by default** for clock-in/out. The self-service channel (web/mobile button on their own login) is **opt-in per staff member** via the `staff_members.self_service_clock_enabled` flag set on the Overview tab in Phase 1. Without that flag, the Clock In button does not appear anywhere outside the kiosk.

The org admin sets the default behaviour in `Settings → People → Clock-in policy`:

- `default_channel = 'kiosk_only'` (system default — every staff is kiosk-only unless individually overridden)
- `default_channel = 'kiosk_and_self_service'` (alternative — every new staff has `self_service_clock_enabled=true` set on creation; admin can still uncheck per staff)

In either mode, the `self_service_clock_enabled` flag on each staff record is the source of truth at clock-in time. The org setting only controls the default value on staff-creation.

### Kiosk clock-in flow (the primary channel)

Route: `/kiosk/clock` (existing kiosk module surface). No login required — same auth model as the existing customer-facing kiosk flow at [app/modules/kiosk/router.py](../../app/modules/kiosk/router.py).

Sequence:
1. Staff member taps "Clock in / Clock out" on the kiosk.
2. Enters their `employee_id` (e.g., `EMP-001`, `JD-2024`) in a numeric/alphanumeric field with on-screen keyboard.
3. System looks up `staff_members WHERE org_id=:org AND employee_id=:code AND is_active=true`. If no match: "Employee code not recognised. Please see your manager." If match: shows "Hi, {first_name}. Take a photo to confirm." with the staff's `on_file_photo_url` thumbnail next to the camera so the kiosk operator can visually compare.
4. **Camera capture is mandatory.** No skip. The captured frame uploads to [uploads](../../app/modules/uploads/), URL stored on `time_clock_entries.clock_in_photo_url` (or `clock_out_photo_url` for the clock-out leg).
5. If clocking in for the first time today: row inserted with `clock_in_at=now()`, `source='kiosk'`, `clock_in_photo_url=...`. Confirmation screen: "Clocked in at 08:42. Have a great day."
6. If clocking out (existing row with `clock_out_at IS NULL`): same flow, sets `clock_out_at` + `clock_out_photo_url`, computes `worked_minutes` minus any break time recorded. Confirmation screen shows today's worked hours.

Notes:
- The kiosk operator (front-desk staff, owner, or whoever's at the screen) is the human verification layer — they see the on-file photo and the just-taken photo side-by-side on the confirmation screen and can challenge mismatches in person.
- Photos are stored encrypted and visible only to managers + the kiosk-flow itself. They surface again in the manager's weekly approval queue with the on-file photo for visual review.
- No PIN, no password, no biometrics. Photo is the verification.
- Rate-limit: max 10 clock-in attempts per `employee_id` per minute (catches typos, prevents brute-force enumeration of valid IDs).

### Self-service clock-in flow (opt-in only)

Only available when `staff_members.self_service_clock_enabled = true` AND `staff_members.user_id IS NOT NULL` (they have a login).

- **Mobile**: PullRefresh screen with one big "Clock in" / "Clock out" button. Tap → POST `/api/v2/staff/me/clock-action`. Required photo capture (Capacitor camera, guarded by `isNativePlatform()`) configurable via `Settings → People → Clock-in policy.self_service_require_photo` (default true). Optional GPS geofence check (configurable).
- **Web**: Same button on the staff-self-service dashboard. Same photo requirement applies (using `getUserMedia` browser API; falls back to "Photo required — please use mobile or kiosk" if the browser denies camera access).
- **Backend enforcement**: the `/api/v2/staff/me/clock-action` endpoint refuses with **403** if `self_service_clock_enabled=false`. The error body says "Self-service clock-in not enabled for this account — please use the kiosk." This guarantees a misconfigured frontend can never bypass the policy.

### Admin-manual clock entry

Admin can insert a `time_clock_entries` row manually via the Hours tab (for "Bob forgot to clock out yesterday" cases). Source recorded as `source='admin_manual'`, no photo, audit-logged with the admin's `user_id`.

### Buddy-punch prevention

Buddy-punching is addressed by the **mandatory photo capture at every kiosk clock-in plus the on-file photo for visual reference**, not by PIN or biometrics. The defence layers:

1. **At the kiosk in real-time**: the on-file photo is displayed next to the camera live-view so a kiosk attendant (or even the next person in queue) can spot impersonation.
2. **At weekly approval**: manager scrolls through the week's clock-in photos in the Hours tab; mismatches with the on-file photo flag the entry for follow-up.
3. **Audit forever**: photos are immutable once written; managers can pull a date range for any staff member and visually verify attendance.
4. **Future enhancement** (out of scope for this round): automated face-match using `face-api.js` or a server-side library to flag low-confidence matches for manual review. The schema (`clock_in_photo_url`, `clock_out_photo_url`, `on_file_photo_url`) is ready for it without further migration.

Optional secondary layer for the self-service channel:

- `self_service_require_geofence` (default false) — staff using self-service must be within X metres of the configured branch lat/lng (computed via Capacitor Geolocation).
- **Break compliance (Employment Relations Act 2000 s69ZD):**
  - For shifts ≥ 4h: 1 paid 10-min rest break.
  - For shifts ≥ 6h: 1 paid rest + 1 unpaid 30-min meal break.
  - For shifts ≥ 10h: 2 paid rests + 1 unpaid meal.
  - System auto-suggests break windows when a shift is created; on clock-in/out flow, "Start break"/"End break" buttons write to `break_records` for the entry.
  - End-of-week approval warns admin if any shift had less than the legally required break time recorded.
- **Hours tab implementation:**
  - Week view: scheduled row vs actual row vs variance, with break time deducted from worked time per NZ law.
  - Drill-down to individual clock-in/out records + break records.
  - Admin can edit `clock_out_at` if employee forgot to clock out (writes an audit row noting who edited what and when).
  - At end of week, **Approve hours** button writes a `timesheet_approvals` row with `status='approved'`, calculates ordinary vs overtime, decides TOIL-vs-cash per the org policy, and locks the time_clock_entries for that week.
  - Re-opening an approved week requires a reason and writes `status='edited_after_approval'` audit.
- **Overtime policy (Settings → People → Overtime):**
  - `overtime_threshold_minutes_per_week` (e.g. 2400 = 40h).
  - `daily_overtime_threshold_minutes` (e.g. 480 = 8h/day — common in trades).
  - `overtime_handling` enum: `pay_cash`, `toil`, `employee_chooses` (drives the Phase 2 TOIL flow).
  - `require_pre_approval`: bool — if true, overtime hours past threshold need manager pre-approval before they count.
- **Shift swap workflow:**
  - `POST /api/v2/staff/me/shift-swap-request {entry_id, with_staff_id?, reason}` — employee A asks employee B to take their shift (or broadcasts to all eligible staff).
  - Counterparty accepts/declines from their own Roster tab.
  - Manager approves the swap (configurable: auto-approve if both parties agree, vs always-manager-approval).
  - On approval, the `schedule_entries.staff_id` flips and both staff get SMS notifications.
- **Open shift / cover request (sick call-out):**
  - When a manager marks a `schedule_entries` row as "needs cover" (e.g. employee called in sick), the system broadcasts SMS to all eligible staff (by skills + availability).
  - First staff to claim it via the response gets it; manager confirms.
  - Eligibility filter: must have `clock_pin_hash` or `user_id`, must not be already scheduled in that window, must have the required skills if the shift has any.
- **Roster-change SMS:** any change to a published `schedule_entries` row within the next 48h triggers an SMS to the affected staff member ("Your shift on Wed 5 Jun changed: now 09:00–14:00 instead of 10:00–15:00").
- **"I'm running late" upward message:** staff can SMS the system (or tap a button in the mobile app) to flag they're delayed. Pushes a notification to the manager.
- **Missed clock-out reminder:** if `clock_out_at` is still NULL 12h after `clock_in_at`, system pushes SMS to the staff and a separate one to their manager.

**Acceptance:** Employees clock in/out (with optional photo/geofence proof); break records get captured; the Hours tab shows scheduled vs actual vs variance with break time deducted; a week can be approved (with TOIL/cash decided per policy); shift swaps and cover requests work end-to-end with SMS; missed clock-outs are surfaced.

**Verify:**

*Kiosk clock-in (the default path for every staff):*
- Open the kiosk at `/kiosk/clock` (no login) → tap "Clock in / Clock out" → enter `employee_id` of a real staff → expect screen "Hi, {first_name}. Take a photo to confirm." with the on-file photo displayed alongside the camera.
- Skip the photo or close the camera → expect button disabled / "Photo required to clock in" message; no row created.
- Take the photo → expect 201 → row in `time_clock_entries` with `source='kiosk'`, `clock_in_at=now()`, `clock_in_photo_url` populated.
- Enter a non-existent `employee_id` → expect "Employee code not recognised. Please see your manager." → no row created.
- Submit the same `employee_id` 11 times within a minute → expect 429 with Retry-After header.
- Clock the same staff in again without clocking out → expect "Already clocked in at 08:42. Tap to clock out." → tap → take photo → existing row updates `clock_out_at`, `clock_out_photo_url`, `worked_minutes` computed minus break time.

*Self-service clock-in (opt-in only):*
- Log in as a staff with `self_service_clock_enabled=false` → confirm the "Clock In" button is NOT visible on their dashboard.
- Try `POST /api/v2/staff/me/clock-action` with that user's token anyway → expect 403 with body "Self-service clock-in not enabled for this account — please use the kiosk."
- Flip the flag on that staff's Overview tab → log back in → confirm the "Clock In" button now appears → tap → photo captured (mobile: Capacitor camera; web: getUserMedia) → 201 with `source='self_service_mobile'` (or `_web`).
- With `self_service_require_geofence=true` and clock from outside the branch radius → expect 403 "Out of range" → walk inside the radius and retry → expect 201.

*Approval + locking:*
- For an org with `overtime_handling='toil'`, work 45h scheduled-time (5h overtime), approve the week → expect 5h added to that staff's TOIL leave balance with `leave_ledger.reason='approved_overtime_toil'`.
- After a week is approved, attempt to edit a `time_clock_entries` row in that window → expect 409 "Week locked; reopen approval first".

*Hours tab manager view:*
- In the manager's weekly approval queue, open a staff's clock-in photos → confirm side-by-side comparison with the on-file photo renders → mismatch button on each photo logs an "investigate" flag against that entry.

*Shift swaps + cover + breaks:*
- POST `/api/v2/staff/me/shift-swap-request {entry_id, with_staff_id}` → counterparty's SMS log fires → counterparty accepts via the Roster tab → manager approves → `schedule_entries.staff_id` flips → both staff receive SMS.
- Mark a schedule entry as "needs cover" → SMS log shows broadcast to all eligible staff → first to claim gets it → other claimants see "already covered" message.
- Force a shift to exceed 4 hours without a break recorded → end-of-week approval banner warns "1 shift with non-compliant breaks" → admin can override with reason audit-logged.

*End-to-end:*
- Run `scripts/test_staff_clock_in_out_e2e.py` → expect "passed: N, failed: 0".

**Data-integrity check:**
- `INSERT` a `time_clock_entries` row with `source='kiosk'` and `clock_in_photo_url=NULL` directly via SQL → expect CHECK constraint violation. (Backstop for any future code path that tries to bypass the kiosk photo requirement.)

**Performance check:** mobile clock-in API call (`POST /api/v2/staff/clock-in`) must complete in &lt;200ms p99 — no synchronous I/O on the request path; photo upload is async.

**Mobile-app integration (per [mobile-app.md](../../.kiro/steering/mobile-app.md)):**
- `mobile/src/screens/clock/ClockScreen.tsx` lazy-imported in `StackRoutes.tsx`.
- ModuleGate `moduleSlug='staff_management'`.
- All buttons `min-h-[44px]`; safe-area insets respected.
- Capacitor camera + geolocation behind `isNativePlatform()` guard; web fallback to PIN-only.
- API uses `offset` (not `skip`).

**Version bump:** 1.15.0 → 1.16.0.

### Phase 4 — Payslips + allowances + termination payouts (4–5 weeks)

**Goal:** Generate, store, email and store-for-7-years payslips that meet NZ Wages Protection Act + Holidays Act s130A.

- Migration: `pay_periods`, `payslips`, `payslip_allowances`, `payslip_deductions`, `payslip_reimbursements` (per §3.4, normalised out of the JSONB columns from the original sketch — easier reporting + audit later).
- **Allowances** — first-class. Configurable per org in `Settings → People → Allowance Types` (CRUD):
  - Common defaults seeded: `meal_allowance`, `tool_allowance`, `vehicle_allowance`, `on_call_allowance`, `travel_per_km`, `uniform_laundering`.
  - Per allowance: `taxable` (bool), `default_amount` (numeric, can be per-shift or per-period), `unit` ('shift' | 'period' | 'km').
  - Entered per pay run on the staff's payslip preview, or auto-attached from a shift type.
- **Reimbursements** — separate from wages (tax-free), e.g. milage, expense claims, work tools bought by the employee.
- **Deductions** — typed, not free JSON:
  - `paye` (mandatory, enter from IRD calc)
  - `acc_levy` (mandatory)
  - `kiwisaver_employee` (auto-calc from `staff.kiwisaver_employee_rate × gross`)
  - `kiwisaver_employer` (separately tracked — employer contribution, not deducted from gross, but shown on payslip)
  - `student_loan` (auto-show only if `staff.student_loan=true`)
  - `child_support` (court-ordered, manual entry)
  - `voluntary` (catch-all)
- **Generate-payslip flow:**
  - Source data = approved `timesheet_approvals` + approved `leave_requests` + casual 8% line if applicable + public-holiday entries + allowances + reimbursements falling inside the pay period.
  - User enters PAYE, ACC, and any per-staff overrides (most defaults auto-fill).
  - Computes ordinary × overtime × public-holiday-at-1.5× hours, leave taken at appropriate rate (relevant daily pay / average daily pay / ordinary weekly), allowances, reimbursements, deductions.
  - **KiwiSaver auto-calculation**: employee contribution = `gross × employee_rate`; employer contribution = `gross × employer_rate` shown separately on payslip but not deducted from gross.
  - Renders payslip PDF (Jinja → WeasyPrint, same path as invoices) including **every Wages Protection Act + Holidays Act s130A field**:
    - Employee name, tax code, IRD number (last 3 digits masked)
    - Pay period start/end + pay date
    - Ordinary hours/rate, overtime hours/rate, public-holiday hours/rate
    - Each allowance line and amount
    - Gross pay
    - Each deduction line and amount
    - Net pay
    - **Leave taken this period** by type
    - **Remaining balances** for all accruing leave types
    - Year-to-date totals (gross, PAYE, KiwiSaver employee, KiwiSaver employer)
    - Anniversary date for annual leave
  - Stores PDF in [uploads](../../app/modules/uploads/), records URL on the payslip row. PDFs immutable post-finalisation.
  - Optional "Email payslip" sends via unified email_sender with payslip PDF attached.
- **Termination workflow** on the Overview tab:
  - "End employment" button → asks for end date, reason, and final-pay options.
  - On submit:
    - Closes all leave balances. Annual leave paid out at **greater of ordinary weekly pay or 52-week average weekly earnings** (Holidays Act s27). Unused alt days paid at relevant daily pay.
    - Casual employees: any remaining 8% holiday-pay obligation calculated on year-to-date gross minus what's already been paid each pay run.
    - Generates a final payslip row queued for the next pay run with the termination payout breakdown.
    - Deactivates the staff record.
- **Bulk pay run:** "Generate payslips for week ending X" → one payslip per active staff, review table → finalise all → optional bulk-email.
- **Pay rate review reminder:** if `staff.last_pay_review_date < (employment_start_date or last_review + 12 months)`, surface a banner on the staff list "5 staff are due a pay review this month".
- **Wage variance report**: "this pay run vs last pay run, per staff and total" — surfaces unexplained changes (someone got an extra 20h without comment, etc.).
- **Bank-file export (deferred to Phase 5, but document the data shape now):** payslips contain `bank_account_number`; later we can produce a CSV in the format banks accept (BNZ, ANZ, ASB, Westpac, Kiwibank — each has its own CSV layout).

**Acceptance:** Open → enter deductions → generate → finalise → email payslips → mark paid works end-to-end; produced PDFs include every Wages Protection Act + Holidays Act s130A field; termination payouts use 52-week-average where required; casual 8% line appears correctly; allowances and reimbursements track separately from wages.

**Verify:**
- Generate a payslip → download PDF → check it includes ALL of: employee name, tax code, IRD number masked, pay period dates, ordinary/overtime/PH hours+rates, every allowance line, every deduction line, gross, net, leave taken this period, remaining balances for every accruing leave type, YTD gross/PAYE/KiwiSaver employee/KiwiSaver employer, anniversary date.
- Create a payslip for a casual employee → verify `payslip_allowances` row includes auto-calculated 8% holiday-pay line on gross.
- Set staff KiwiSaver `employee_rate=4`, `employer_rate=3`; generate payslip with gross=$1000 → verify deduction lines: KiwiSaver employee $40, KiwiSaver employer $30 (shown separately, not deducted from gross). Net pay = $1000 − PAYE − ACC − $40.
- Terminate an employee with 80h accrued annual leave + 16h alt days → check the generated final payslip's `leave_lines_json` for: annual-leave payout calculated as greater of ordinary weekly vs 52-week average; alt-days at relevant daily pay.
- Run bulk-pay-run → all active staff get one payslip → review table shows expected totals → click "Finalise all" → PDFs render → emails queue → `payslips.finalised_at` set.
- POST to a finalised payslip's update endpoint → expect 409 "Payslip immutable post-finalisation".
- Run `scripts/test_staff_payslip_e2e.py` → expect "passed: N, failed: 0".

**PDF rendering performance check:** payslip generation wraps WeasyPrint call in `await asyncio.to_thread(lambda: HTML(...).write_pdf())` (per PERFORMANCE_AUDIT.md B-H1). Bulk pay-run dispatches via the unified background-task path, not request worker.

**PII safety check:** the payslip-rendering service is the ONLY code path that calls `envelope_decrypt_str(...)` on `ird_number_encrypted` and `bank_account_number_encrypted`. The bytea ciphertext columns are never returned in any other API response.

**Version bump:** 1.16.0 → 1.17.0.

---

## 7. What this plan deliberately does NOT include

To stay realistic and avoid scope creep:

- **No PAYE/ACC/KiwiSaver calculation.** That's regulated tax-engine territory. Deductions are accepted as inputs.
- **No bank-file generation (BNZ/ANZ/ASB direct-credit batch files).** Common in NZ but adds significant testing surface and bank-specific quirks. Add later if customers ask.
- **No IRD filing (Employer Information / IR348).** Same reason as above.
- **No performance reviews, recruitment, onboarding workflows, learning management.** That's full HR-software scope.
- **No multi-currency wages.** NZ-only orgs for now.
- **No union/award rates beyond simple ordinary+overtime.** No collective-agreement rate tables.

These can become Phase 5+ later if customers demand them. Most small NZ workshops use a separate payroll product (Smartly, iPayroll, Crystal, etc.) for tax filing anyway — our role is operational hours/leave management, with a payslip that meets the Wages Protection Act minimums.

---

## 8. Cross-cutting concerns

### 8.1 Permissions
- **Org admin**: everything.
- **Branch admin / location manager**: full access for staff at their branch only.
- **Staff member (linked user)**: own data only on Overview, Roster (read), Leave (read + request), Hours (read + clock-in/out), Payslips (read own).
- **Contractor**: subset — no Leave or Payslips tabs; hours visible if engaged on time-and-materials.
- **Family-violence-leave visibility** — uses the existing `user_permission_overrides` table with permission key `leave:family_violence:view`. Phase 2 migration grants this to all current org_admins as a one-time backfill with a 30-day "review and revoke" nag banner on the Settings → People → Permissions page. Toggling writes `permission.fv_leave_view.granted` / `.revoked` audit rows. The filter applies at every API endpoint that returns `leave_requests` for any `leave_type` with `confidential_visibility=true` — a request is returned to (a) the staff who submitted it, OR (b) users holding the permission. See Phase 2 spec design §4.4 for the implementation.

### 8.2 Audit logging
Every state change in this module must write to `audit_logs`:
- `staff.created`, `staff.updated`, `staff.deactivated`, `staff.terminated`
- `leave_type.created`, `leave_type.updated`, `leave_type.deactivated`, `leave_balance.adjusted` (manual adjustments need attached reason)
- `leave_request.submitted`, `leave_request.approved`, `leave_request.rejected`, `leave_request.cancelled`
- `leave_accrual.batch_run` (one row per scheduled accrual batch, with summary counters: orgs_processed, staff_accrued, ledger_rows_written, failures)
- `public_holiday.alt_granted` (when a staff works an "otherwise working day" public holiday and is granted an alt-day)
- `public_holiday.s40a_extension` (when an annual-leave request is auto-extended because it includes a public holiday on the staff's OWD)
- `time_clock.in`, `time_clock.out`, `time_clock.edited`
- `timesheet.approved`, `timesheet.reopened`
- `payslip.generated`, `payslip.finalised`, `payslip.emailed`, `payslip.voided`
- `permission.fv_leave_view.granted`, `permission.fv_leave_view.revoked` (family-violence-leave visibility permission grants — see §8.1)

For confidential leave types (`confidential_visibility=true`), audit rows redact free-text fields (`reason`, `decision_notes`) — the IDs and timestamps remain auditable but the content does not appear in the audit log itself, so audit-log readers without `leave:family_violence:view` permission don't accidentally see sensitive details.

### 8.3 Notifications
- Approved leave request → email to staff member.
- Rejected leave request → email to staff member with reason.
- Roster published / changed → opt-in email to staff member (the auto roster email from Phase 1).
- Upcoming public holiday: org-admin dashboard nudge "5 staff will be working Anzac Day — confirm time-and-a-half pay" 7 days out.
- Missed clock-out: notification to admin if a `time_clock_entries.clock_out_at IS NULL` and `clock_in_at < now() - 12 hours`.

### 8.4 Time zone
All `timestamptz`. Display uses the org's configured timezone from `organisations.timezone`. NZ has daylight saving — handle the autumn "extra hour" and spring "missing hour" carefully when computing worked_minutes; never store local-time strings except for `staff_members.shift_start`/`shift_end` (which are "HH:MM" intent, applied to whichever date is current).

### 8.5 Module gating
This adds enough surface area to warrant its own module flag in [app/core/modules.py](../../app/core/modules.py) — e.g. `staff_management` (basic) and `payroll` (Phase 4). Orgs without the payroll add-on still get Phases 1–3.

### 8.6 Data migration from existing v1 scheduling
The two scheduling implementations (v1 + v2) will continue to co-exist during the rollout. New Roster tab uses v2 only. Once the new UI is the default, schedule a deprecation of [app/modules/scheduling/](../../app/modules/scheduling/) and migrate any remaining `schedules` rows into `schedule_entries`.

---

## 9. Open product questions to settle before Phase 2 starts

1. **Casual vs permanent.** Do you support casual employees on pay-as-you-go 8% holiday pay, or only permanent staff with anniversary accrual? Affects schema (new `employment_type` enum) and accrual engine.
2. **Pre-launch leave balances.** When a staff member already exists with accrued leave from a previous payroll system, how do we import opening balances? Recommend: a CSV upload in Settings → People → Leave → Opening Balances that writes `leave_ledger` rows with `reason='opening_balance'`.
3. **Multi-org workers.** If a contractor works for multiple orgs in this system, do their hours/leave overlap or are they fully org-scoped? Currently fully org-scoped — confirm.
4. **Public-holiday substitution.** Sometimes a public holiday on a Saturday is "Monday-ised" (e.g. Waitangi Day on a weekend). Nager.Date typically returns the observed date; we should confirm this matches the legal observed date for NZ payroll purposes before relying on it.
5. **PIN security.** If a staff kiosk PIN is 4 digits and the kiosk is in the public area, what's the lockout / rate-limit policy? Suggest: 5 wrong attempts within 5 min → kiosk-PIN clock-in locked for 30 min for that staff member, fall back to manager unlock.
6. **Email roster format.** PDF attachment, inline HTML, or both? Suggest: inline HTML + a link to view the full schedule in the app (works for staff without login if we add a tokenised "magic link" — same pattern as the customer portal).
7. **Approval policy.** Who approves whose hours? Manager (via `staff_members.reporting_to`), or branch-admin only, or both? Affects the Hours-tab approval queue.

---

## 10. Cross-references

- Performance audit recommendations affecting this module:
  - All new tables need RLS + `FORCE ROW LEVEL SECURITY` once that work lands ([PERFORMANCE_AUDIT.md](../PERFORMANCE_AUDIT.md) Theme A).
  - All new FK columns need composite `(org_id, ...)` indexes from the outset ([PERFORMANCE_AUDIT.md](../PERFORMANCE_AUDIT.md) D-H4, D-H5).
- Future work on uniqueness constraints: aligned with [docs/future/rego-to-customer-autofill-and-link-uniqueness.md](rego-to-customer-autofill-and-link-uniqueness.md) — different table, same migration discipline.
- Existing test bed: [tests/unit/test_staff_*](../../tests/) and [tests/unit/test_time_tracking_*](../../tests/) — extend rather than duplicate.

---

### Phase 5 — Reporting + wage forecasting + bank export (2–3 weeks, optional)

**Goal:** Give owners the visibility they actually use to run the business — and the export they need to pay people quickly.

- **Labour-cost dashboard** (new tile on the org dashboard, plus its own Reports page):
  - Labour cost as % of revenue (rolling weekly, monthly, YTD) — needs to join `payslips` × `invoices`.
  - Labour cost per branch / per location.
  - Labour cost per project (where time entries are project-linked).
- **Wage forecast** — Monday-morning view: "based on this week's published roster + standard rates + expected leave + expected overtime, this week's wage bill will be ~$X." Updated daily as actuals come in.
- **Attendance patterns:**
  - Late-arrival heat-map per staff (clock_in vs scheduled start).
  - No-show counter.
  - Missed-clock-out frequency.
  - Average hours per staff per week, rolling.
- **Leave projection:** "in the next 30 days, X staff have approved leave covering Y hours" — helps cover planning.
- **Anniversary / probation calendar:** lists upcoming pay-review anniversaries, probation end dates, employment-contract anniversaries, visa expiries.
- **Bank-file export:** CSV in each major NZ bank's batch-credit format (BNZ "Multi-Pay", ANZ "Direct Credit", ASB, Westpac, Kiwibank). One CSV per pay run.
- **IRD-friendly export** (deferred from Phase 4): CSV of `(employee, IRD number, gross, PAYE, KiwiSaver employee, KiwiSaver employer)` per pay period, in the rough shape orgs upload to their IRD myIR portal. We're not filing for them, just making the manual upload trivial.

**Acceptance:** Owners can see wage cost in context of revenue; weekly forecast appears on Monday dashboard; bank-file export produces a CSV that the org's bank accepts on first try.

**Verify:**
- Per [dashboard-widget-gating.md](../../.kiro/steering/dashboard-widget-gating.md): the new labour-cost and wage-forecast widgets each follow the 10-step process. Specifically:
  - `WIDGET_DEFINITIONS` entry with `module: 'staff_management'`, `defaultOrder: 11/12`.
  - `WidgetCard` wrapper.
  - Empty state message ("No staff payslips yet — generate your first pay run").
  - Backend service function in `dashboard_service.py` returns `WidgetDataSection[LabourCostItem]` with per-widget try/except.
  - Pydantic schema added to `DashboardWidgetsResponse`.
  - Normalisation added to `useDashboardWidgets.ts`.
  - Property test in `tests/test_dashboard_widgets.py` covering the labour-cost-vs-revenue calc.
- Generate a BNZ Multi-Pay CSV → diff against BNZ's spec → 100% match. Repeat for each supported bank.
- Run `scripts/test_staff_reporting_e2e.py` → expect "passed: N, failed: 0".

**Version bump:** 1.17.0 → 1.18.0.

---

## 7A. Real-world SME gaps that drove the Phase revisions

Initial draft of this plan was thin on the operational reality of running hourly staff. After revisiting with that lens, six categories of must-have additions surfaced — captured below for completeness, then folded into the phases above.

### A. Employee record completeness (without this, payslips are impossible)

| Field | Why it matters | Phase |
|---|---|---|
| `tax_code` (M/ME/S/SH/ST/SB/CAE/NSW) | Required on every payslip; drives PAYE | Phase 1 |
| `ird_number` (encrypted) | Wages Protection Act requirement, even masked | Phase 1 |
| `kiwisaver_enrolled` + employee + employer rates | Mandatory employer-contribution calc; payslip line | Phase 1 (storage) → Phase 4 (calc) |
| `bank_account_number` (encrypted) | Without it the org can't pay them | Phase 1 |
| `student_loan` | Drives extra deduction line | Phase 1 |
| `employment_type` (permanent / casual / fixed_term) | Drives entire leave engine path | Phase 1 (storage) → Phase 2 (logic) |
| `probation_end_date` | 90-day-trial tracking is common | Phase 1 |
| `visa_expiry_date` | Right-to-work compliance for migrant staff | Phase 1 |
| `clock_pin_hash` | Kiosk clock-in for staff without logins | Phase 1 (storage) → Phase 3 (use) |
| `emergency_contact_*` | Standard small-business hygiene | Phase 1 |
| `staff_pay_rates` history | Audit + anniversary review reminder | Phase 1 |
| Signed employment agreement on file | Mandatory under ERA s64; SME compliance | Phase 1 (upload slot) |
| Minimum-wage compliance warning | $23.15 floor from 1 April 2024 (configurable in Settings) | Phase 1 |

### B. Operational hours management (the day-to-day SME owner reality)

| Feature | Why SMEs care | Phase |
|---|---|---|
| **Shift swap requests** | "I can't do Tues, can Bob take it?" — happens weekly | Phase 3 |
| **Open shift / cover broadcast** | Someone calls in sick at 6am, who can come in? SMS blast | Phase 3 |
| **Roster-change SMS** | Staff don't check email; need real-time push for shift changes | Phase 3 |
| **Break compliance recording** | ERA s69ZD legal requirement; audit trail | Phase 3 |
| **"Running late" upward msg** | Common — staff message via SMS/app | Phase 3 |
| **Missed clock-out alerts** | Stops 14h "shifts" from accruing | Phase 3 |
| **Pre-approval for overtime** | Stops staff manufacturing overtime; owner control | Phase 3 |
| **Kiosk-default policy** | Default channel is kiosk-only; self-service requires per-staff opt-in | Phase 1 (flag) + Phase 3 (enforcement) |
| **Mandatory photo at kiosk** | Photo + on-file comparison is the buddy-punch defence (no PIN) | Phase 3 |
| **Optional geofence for self-service** | Restricts mobile clock-in to within branch radius | Phase 3 |

### C. Compliance & risk (audit exposure if missing)

| Feature | Statute | Phase |
|---|---|---|
| Employment agreement upload | ERA 2000 s64 (must hold a signed copy) | Phase 1 |
| Right-to-work / visa expiry | Immigration Act 2009 — fine for employing past expiry | Phase 1 |
| 90-day trial period tracker | ERA s67A — calendar nudge before expiry | Phase 1 |
| Minimum wage warning | Minimum Wage Act 1983 | Phase 1 |
| Pay rate history | ERA s130 — wage records 6yr | Phase 1 |
| Break records | ERA s69ZD record-keeping | Phase 3 |
| Payslip Holidays Act s130A fields | Includes leave balances on every payslip | Phase 4 |
| Termination payout at 52-week avg | Holidays Act s27 | Phase 4 |

### D. Holidays Act 2003 edge cases (where SMEs get audited)

| Edge case | Section | Phase |
|---|---|---|
| Casual employees on 8% pay-as-you-go (no accrual) | s28 | Phase 2 |
| Public holiday on "otherwise working day" → 1.5× + alt day | s49–s50 | Phase 2 |
| Public holiday during annual leave → leave extended | s40A | Phase 2 |
| "Average daily pay" for PH where ordinary daily pay unclear | s9 | Phase 2 |
| Termination payout = greater of ordinary weekly vs 52-wk average | s27 | Phase 4 |
| Sick leave pro-rata for variable-hours staff | s63 | Phase 2 |

### E. TOIL (Time Off In Lieu) — the most-requested SME feature missing from the original draft

Many NZ SMEs run a TOIL policy: staff bank overtime as future leave hours rather than being paid cash. This needs explicit support:

- A 7th leave type seeded automatically for orgs that select `overtime_handling='toil'` or `'employee_chooses'`.
- Balance grows from approved overtime hours (not from a daily accrual job).
- Drawn down by approved TOIL leave requests, exactly like annual leave.
- On termination: TOIL balance paid out at the employee's ordinary rate.
- Phase 3 approval UI presents the choice (cash vs TOIL) for orgs with `employee_chooses`.

### F. Communications channels (SMS is not optional)

Hourly staff don't read work email. The plan now uses SMS for time-sensitive events:

- Roster published / changed (within 48h of shift) → SMS
- Open-shift cover broadcast → SMS
- Late-arrival alert (manager-bound) → SMS
- Missed clock-out reminder → SMS to staff + SMS to manager
- Approved leave request → SMS confirmation
- Pay-day → SMS "Your payslip is ready"

Each channel is opt-in per staff member in Phase 1's expanded staff record. Reuses the existing [app/modules/sms_providers](../../app/modules/sms_providers/) layer.

---

## 11. Summary

| Area | Today | P1 | P2 | P3 | P4 | P5 |
|---|---|---|---|---|---|---|
| Staff CRUD | ✅ Basic | ✅ Tabbed UI + full employee record | ✅ | ✅ | ✅ | ✅ |
| Employment record (tax code, IRD, KiwiSaver, bank, visa, probation) | ❌ | ✅ Stored | ✅ Used in leave | ✅ Used in approvals | ✅ Used in payslip | ✅ |
| Roster view | ✅ Org-wide | ✅ Per-staff + email/SMS delivery | ✅ Leave auto-shows | ✅ Variance overlay + swaps + cover | ✅ | ✅ |
| Leave types | ❌ | ❌ | ✅ All 6 NZ statutory + TOIL + custom | ✅ | ✅ | ✅ |
| Leave accrual | ❌ | ❌ | ✅ Anniversary + 6mo sick gate + casual 8% | ✅ + TOIL from approved OT | ✅ + termination payout | ✅ |
| Holidays Act edge cases (s40A, s27, OWD) | ❌ | ❌ | ✅ Engine + auto-extension | ✅ | ✅ Final pay 52-wk avg | ✅ |
| Clock in/out | ❌ | ❌ | ❌ | ✅ Kiosk-default + opt-in self-service; mandatory photo at kiosk | ✅ | ✅ |
| Scheduled vs actual + approval | ❌ | ❌ | ❌ | ✅ Variance + lock + TOIL choice | ✅ | ✅ |
| Break compliance | ❌ | ❌ | ❌ | ✅ Recorded + audited | ✅ Shown on payslip | ✅ |
| Shift swap / cover request | ❌ | ❌ | ❌ | ✅ SMS-driven workflow | ✅ | ✅ |
| Buddy-punch prevention | ❌ | ❌ | ❌ | ✅ Mandatory photo + on-file comparison at kiosk; optional geofence on self-service | ✅ | ✅ |
| SMS for roster / late / cover / payslip | ❌ | ✅ Roster send | ✅ Leave decisions | ✅ All operational events | ✅ Payday | ✅ |
| Payslips | ❌ | ❌ | ❌ | ❌ | ✅ Wages Protection Act + s130A | ✅ |
| Allowances + reimbursements (typed) | ❌ | ❌ | ❌ | ❌ | ✅ First-class | ✅ |
| Termination payout | ❌ | ❌ | ❌ | ❌ | ✅ Greater of ordinary vs 52-wk avg | ✅ |
| Labour cost vs revenue | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ Dashboard |
| Wage forecast (Monday view) | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Bank file export (BNZ/ANZ/ASB/Westpac/Kiwibank) | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Compliance docs (signed agreement, visa) | ❌ | ✅ Upload + expiry tracking | ✅ | ✅ | ✅ | ✅ |

**Revised total effort:** ~16–20 dev-weeks across 5 phases (was ~8–12 for the original 4-phase sketch). The increase reflects what real-world SME hourly-staff management actually needs.

**Recommended starting point unchanged: Phase 1.** Now ~2–3 weeks rather than 1.5–2, because the expanded scope includes the employment-record completeness that everything else depends on. Without those Phase 1 fields, Phases 2–4 either can't be built or produce broken outputs (payslips missing tax code, leave engine missing employment_type, etc.).

---

## 12. Pre-merge gate checklist (each phase must pass before merging)

Per [implementation-completeness-checklist.md](../../.kiro/steering/implementation-completeness-checklist.md) Rule 10 (gap-analysis before marking spec complete) and [spec-completeness-checklist.md](../../.kiro/steering/spec-completeness-checklist.md), each phase ships its own `.kiro/specs/staff-management-pX/` folder containing:

- `requirements.md` — acceptance criteria with EARS-style structure
- `design.md` — covering all 8 mandatory frontend sections (Navigation, Component Tree, User Workflow Trace, Modal Inventory, Toolbar, List/Table, Error UI, Integration Points)
- `tasks.md` — every task has a `**Verify:**` line per Rule 9
- `gap-analysis.md` — generated post-implementation, lists any unmet acceptance criteria

Before the phase PR is merged, ALL of the following must be ticked:

**Code completeness**
- [ ] All migration files run cleanly via `docker compose exec app alembic upgrade head` (per [database-migration-checklist.md](../../.kiro/steering/database-migration-checklist.md))
- [ ] All index migrations use `CREATE INDEX CONCURRENTLY IF NOT EXISTS` inside `autocommit_block()`
- [ ] Zero `op.create_index(...)` calls in any new migration
- [ ] All new tables have RLS enabled + `tenant_isolation` policy
- [ ] Module registry inserts include `setup_question` + `setup_question_description` (Phase 1 only)
- [ ] `feature_flags` row added alongside `module_registry` row (Rule 8)
- [ ] Subscription plan's `enabled_modules` updated

**API contract**
- [ ] Every new field on a service-dict has a matching field on the Pydantic response schema (Rule 8 of frontend-backend-contract)
- [ ] All list endpoints return `{ items: [...], total: N }` or named-list shape — never bare arrays
- [ ] No new env vars introduced (all runtime config in DB)
- [ ] Integration with `send_email` (unified email sender) for all outbound emails
- [ ] Integration with `sms_providers` (unified SMS sender) for all outbound SMS
- [ ] Audit log entries written for every state change (action names listed in §8.2)

**Frontend**
- [ ] Every API call uses `?.` + `?? []` / `?? 0`
- [ ] No `as any` on API responses
- [ ] Every useEffect with an API call has AbortController cleanup
- [ ] All buttons/list items 44×44 minimum (Phase 3 mobile screens)
- [ ] No "Coming soon" placeholders (Rule 4)
- [ ] Empty states, loading states, error states all implemented
- [ ] Mobile screens behind ModuleGate
- [ ] Capacitor calls guarded by `isNativePlatform()`

**Testing**
- [ ] Phase's `scripts/test_staff_<area>_e2e.py` script ships with the PR
- [ ] Test data prefixed `TEST_E2E_`
- [ ] Cleanup runs in `finally` block; orphaned-data check at end
- [ ] OWASP Top 10 security checks for the phase's surface area included
- [ ] Property test for non-trivial logic (leave accrual math, payslip calc, otherwise-working-day detection)

**Security (per [security-hardening-checklist.md](../../.kiro/steering/security-hardening-checklist.md))**
- [ ] PII columns (IRD, bank account) stored as `BYTEA` envelope-encrypted
- [ ] PII returned masked in API responses (`***1234` last-N-digits)
- [ ] Mask-pattern detection on save (don't overwrite real value with mask)
- [ ] bcrypt for clock_pin_hash; verification wrapped in `asyncio.to_thread`
- [ ] Rate limiting on clock-in PIN attempts (5/5min → 30min lockout per staff)
- [ ] Family-violence-leave records visible only to approver (per-org permission)

**Versioning**
- [ ] `pyproject.toml`, `frontend/package.json`, `mobile/package.json` version bumped in sync
- [ ] `CHANGELOG.md` entry under the new version heading
- [ ] Issue tracker updated if any bug was discovered + fixed during implementation

**Browser test**
- [ ] Every user-facing flow tested in the actual browser at the actual URL
- [ ] Network tab inspected for the expected request/response shapes
- [ ] No red console errors

A phase is NOT done until every box above is ticked. The phase's `gap-analysis.md` documents any item that couldn't be ticked and the reason (or follow-up issue raised).

---

## 13. Open issues to allocate before Phase 1 starts

Per [issue-tracking-workflow.md](../../.kiro/steering/issue-tracking-workflow.md), reserve issue IDs for items already known to need resolution:

- **STAFF-001**: Decide if `staff_management` should be in the default subscription plan or a paid add-on. Affects the Phase 1 migration body.
- **STAFF-002**: Decide if family-violence-leave records need a dedicated RBAC permission or if the existing role hierarchy is sufficient. Affects Phase 2.
- **STAFF-003**: Confirm Nager.Date's NZ public-holiday observed dates match Holidays Act observed dates (Monday-isation of weekend public holidays). Affects Phase 2's public-holiday engine accuracy.
- **STAFF-004**: Decide bank-file format priority — start with BNZ Multi-Pay or ASB? Affects Phase 5 scope.
- **STAFF-005**: Decide if the existing `staff_member` role suffices for staff self-service (clock-in/out, view own payslips, request leave) or if a more restricted role is needed. Affects Phase 3 RBAC matrix.
- **STAFF-006**: Decide if kiosk clock-in should use the **existing customer-kiosk surface** at `/kiosk/*` (shared route, separate "Staff" tile on the welcome screen) or a **dedicated staff-kiosk surface** at `/staff-kiosk` (separate route, possibly different visual treatment). Affects Phase 3 routing + the existing kiosk module's [router.py](../../app/modules/kiosk/router.py).
- **STAFF-007**: Decide photo retention period — keep all clock-in/out photos forever (Holidays Act 6-year wage record argument) or auto-purge after N days (privacy argument). Recommend 6 years to match wage-record retention.
- **STAFF-008**: Decide automatic face-match — defer (manual visual review only in Phase 3) or include in Phase 3 / Phase 5. Affects schema only if we want a `face_match_confidence` column on `time_clock_entries`.

Allocate IDs from the next available range in `docs/ISSUE_TRACKER.md` before kick-off.

**Recommended skip-strategy if time is tight:**
- Phase 5 (reporting + bank export) is the only fully optional phase.
- Within phases, the **deferrable** items are: GPS geofencing (P3), photo capture on clock-in (P3 — can launch with PIN only), bank-file CSV (P4 — defer to P5), the "Documents" tab (P1 — Overview's signed-agreement slot is sufficient).
- The **non-deferrable** items are: tax code + IRD + KiwiSaver + bank account fields (P1 — payslips need them), break recording (P3 — legal requirement), Holidays Act s40A + s27 + casual 8% (P2–P4 — audit exposure).
