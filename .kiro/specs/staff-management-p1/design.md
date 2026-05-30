# Staff Management Phase 1 — Design

## 1. Architecture overview

Phase 1 is a **schema-additive + UI-restructure** release. No new modules in `app/modules/` (the work extends the existing `app/modules/staff/`). Two new tables (`staff_pay_rates`, plus columns on `staff_members`). One new scheduled task (`weekly_roster_broadcast`). Two new endpoints per staff (`/email-roster`, `/sms-roster`). One new endpoint for pay rate history (`/pay-rates`). Module registration via Alembic insert.

Backend touches:
- `alembic/versions/0203_staff_phase1_schema.py` (data DDL + RLS policies + module/feature-flag inserts)
- `alembic/versions/0204_staff_phase1_indexes.py` (CREATE INDEX CONCURRENTLY pack — separate file because index DDL must run outside Alembic's transaction wrapper)
- `app/modules/staff/models.py` — extend `StaffMember` ORM, add `StaffPayRate` ORM
- `app/modules/staff/schemas.py` — extend Pydantic schemas, mask logic
- `app/modules/staff/service.py` — extend create/update flows, add pay-rate-history methods
- `app/modules/staff/router.py` — add endpoints
- `app/modules/staff/roster_delivery.py` — new file for email + SMS delivery helpers
- `app/tasks/scheduled.py` — register `weekly_roster_broadcast`

Frontend touches:
- `frontend/src/pages/staff/StaffDetail.tsx` — refactor into tabbed shell
- `frontend/src/pages/staff/StaffList.tsx` — add compliance counters + filter chips
- `frontend/src/pages/staff/tabs/OverviewTab.tsx` — new (the bulk of the form)
- `frontend/src/pages/staff/tabs/RosterTab.tsx` — new (embeds ScheduleCalendar filtered by staff_id)
- `frontend/src/pages/staff/tabs/DocumentsTab.tsx` — new (employment agreement slot)
- `frontend/src/pages/staff/components/PayRateHistoryPanel.tsx` — new
- `frontend/src/pages/staff/components/MinimumWageWarningModal.tsx` — new

## 2. Navigation & Access

- **Route:** existing `/staff/:id` route stays unchanged (registered in `App.tsx`). Tabs are sub-routes via URL hash (`/staff/:id#overview`).
- **Guard:** `RequireOrgAdmin` (existing). Role gate uses existing `org_admin`, `branch_admin`, `location_manager` (no new role introduced — see §4).
- **Module gate:** the tabbed UI conditionally renders only when `useModuleEnabled('staff_management')` returns true. When disabled, the legacy single-form view renders (back-compat).
- **Sidebar item:** existing "Staff" sidebar entry already exists. No nav changes in Phase 1.
- **Lazy imports:** `OverviewTab`, `RosterTab`, `DocumentsTab` lazy-loaded via `React.lazy()` so the staff list page doesn't pull the calendar bundle.

## 3. Data Model

### 3.1 Migration `0203_staff_phase1_schema.py`

```python
"""Staff phase 1 — expanded employment record + pay rate history + module registration.

Revision ID: 0203
Revises: 0202
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0203"
down_revision = "0202"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extend staff_members with employment + payroll fields
    # ------------------------------------------------------------------
    op.execute("""
        ALTER TABLE staff_members
            ADD COLUMN IF NOT EXISTS employment_start_date date,
            ADD COLUMN IF NOT EXISTS employment_end_date date,
            ADD COLUMN IF NOT EXISTS employment_type text NOT NULL DEFAULT 'permanent',
            ADD COLUMN IF NOT EXISTS standard_hours_per_week numeric(5,2),
            ADD COLUMN IF NOT EXISTS tax_code text,
            ADD COLUMN IF NOT EXISTS ird_number_encrypted bytea,
            ADD COLUMN IF NOT EXISTS student_loan boolean NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS kiwisaver_enrolled boolean NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS kiwisaver_employee_rate numeric(4,2),
            ADD COLUMN IF NOT EXISTS kiwisaver_employer_rate numeric(4,2) NOT NULL DEFAULT 3.00,
            ADD COLUMN IF NOT EXISTS bank_account_number_encrypted bytea,
            ADD COLUMN IF NOT EXISTS probation_end_date date,
            ADD COLUMN IF NOT EXISTS visa_expiry_date date,
            ADD COLUMN IF NOT EXISTS self_service_clock_enabled boolean NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS on_file_photo_url text,
            ADD COLUMN IF NOT EXISTS emergency_contact_name text,
            ADD COLUMN IF NOT EXISTS emergency_contact_phone text,
            ADD COLUMN IF NOT EXISTS weekly_roster_email_enabled boolean NOT NULL DEFAULT true,
            ADD COLUMN IF NOT EXISTS weekly_roster_sms_enabled boolean NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS last_pay_review_date date,
            ADD COLUMN IF NOT EXISTS employment_agreement_upload_id uuid;
    """)

    # CHECK constraint for employment_type enum (idempotent — drop+recreate)
    op.execute("""
        ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_employment_type;
        ALTER TABLE staff_members ADD CONSTRAINT ck_staff_employment_type
            CHECK (employment_type IN ('permanent','casual','fixed_term'));
    """)
    op.execute("""
        ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_tax_code;
        ALTER TABLE staff_members ADD CONSTRAINT ck_staff_tax_code
            CHECK (tax_code IS NULL OR tax_code IN ('M','ME','S','SH','ST','SB','CAE','NSW','ND'));
    """)

    # ------------------------------------------------------------------
    # staff_pay_rates table (audit ledger)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS staff_pay_rates (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id          uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            staff_id        uuid NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE,
            hourly_rate     numeric(10,2),
            overtime_rate   numeric(10,2),
            effective_from  date NOT NULL,
            changed_by      uuid REFERENCES users(id),
            change_reason   text,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
    """)
    op.execute("ALTER TABLE staff_pay_rates ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        DROP POLICY IF EXISTS tenant_isolation ON staff_pay_rates;
        CREATE POLICY tenant_isolation ON staff_pay_rates
            USING (org_id = current_setting('app.current_org_id', true)::uuid);
    """)

    # ------------------------------------------------------------------
    # Module registry inserts (idempotent ON CONFLICT)
    # ------------------------------------------------------------------
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

    # Update default subscription plan's enabled_modules — append both slugs.
    # 'default' is a placeholder; STAFF-001 settles whether to also touch
    # 'starter'/'pro' or only the first plan.
    op.execute("""
        UPDATE subscription_plans
        SET enabled_modules = (
            SELECT jsonb_agg(DISTINCT m)
            FROM jsonb_array_elements_text(enabled_modules || '["staff_management","payroll"]'::jsonb) m
        )
        WHERE name ILIKE '%default%' OR name ILIKE '%starter%' OR is_archived = false;
    """)

    # Feature flag mirrors per implementation-completeness Rule 8
    op.execute("""
        INSERT INTO feature_flags (id, key, description, default_enabled, scope)
        VALUES
            (gen_random_uuid(), 'staff_management', 'Staff Management module', false, 'org'),
            (gen_random_uuid(), 'payroll', 'Payroll & Payslips module', false, 'org')
        ON CONFLICT (key) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS staff_pay_rates;")
    op.execute("""
        ALTER TABLE staff_members
            DROP COLUMN IF EXISTS employment_start_date,
            DROP COLUMN IF EXISTS employment_end_date,
            DROP COLUMN IF EXISTS employment_type,
            DROP COLUMN IF EXISTS standard_hours_per_week,
            DROP COLUMN IF EXISTS tax_code,
            DROP COLUMN IF EXISTS ird_number_encrypted,
            DROP COLUMN IF EXISTS student_loan,
            DROP COLUMN IF EXISTS kiwisaver_enrolled,
            DROP COLUMN IF EXISTS kiwisaver_employee_rate,
            DROP COLUMN IF EXISTS kiwisaver_employer_rate,
            DROP COLUMN IF EXISTS bank_account_number_encrypted,
            DROP COLUMN IF EXISTS probation_end_date,
            DROP COLUMN IF EXISTS visa_expiry_date,
            DROP COLUMN IF EXISTS self_service_clock_enabled,
            DROP COLUMN IF EXISTS on_file_photo_url,
            DROP COLUMN IF EXISTS emergency_contact_name,
            DROP COLUMN IF EXISTS emergency_contact_phone,
            DROP COLUMN IF EXISTS weekly_roster_email_enabled,
            DROP COLUMN IF EXISTS weekly_roster_sms_enabled,
            DROP COLUMN IF EXISTS last_pay_review_date,
            DROP COLUMN IF EXISTS employment_agreement_upload_id;
        ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_employment_type;
        ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_tax_code;
    """)
    op.execute("DELETE FROM module_registry WHERE slug IN ('staff_management', 'payroll');")
    op.execute("DELETE FROM feature_flags WHERE key IN ('staff_management', 'payroll');")
```

### 3.2 Migration `0204_staff_phase1_indexes.py` (CONCURRENTLY pack)

Per `database-migration-checklist.md` — every index ships as raw SQL `CREATE INDEX CONCURRENTLY ... IF NOT EXISTS` inside `op.get_context().autocommit_block()`. Mirrors the canonical 0202 template.

```python
from alembic import op

revision = "0204"
down_revision = "0203"

_UPGRADE: list[tuple[str, str]] = [
    (
        "FK index for staff_pay_rates lookups by staff",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_pay_rates_staff_effective "
        "ON staff_pay_rates (staff_id, effective_from DESC)",
    ),
    (
        "FK index for staff_pay_rates by org",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_pay_rates_org "
        "ON staff_pay_rates (org_id)",
    ),
    (
        "Anniversary review surface — pay-review-due query",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_review_due "
        "ON staff_members (org_id, last_pay_review_date) "
        "WHERE is_active = true",
    ),
    (
        "Probation expiry surface",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_probation_end "
        "ON staff_members (org_id, probation_end_date) "
        "WHERE is_active = true AND probation_end_date IS NOT NULL",
    ),
    (
        "Visa expiry surface",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_visa_expiry "
        "ON staff_members (org_id, visa_expiry_date) "
        "WHERE is_active = true AND visa_expiry_date IS NOT NULL",
    ),
    (
        "Roster broadcast scan — active staff with email opt-in",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_roster_email_optin "
        "ON staff_members (org_id) "
        "WHERE is_active = true AND weekly_roster_email_enabled = true",
    ),
    (
        "Roster broadcast scan — active staff with SMS opt-in",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_roster_sms_optin "
        "ON staff_members (org_id) "
        "WHERE is_active = true AND weekly_roster_sms_enabled = true",
    ),
]

_DOWNGRADE: list[tuple[str, str]] = [
    (d, "DROP INDEX CONCURRENTLY IF EXISTS " + s.split("idx_")[1].split()[0])
    for d, s in _UPGRADE if "CREATE INDEX" in s
]
# (helper above is illustrative — actual file enumerates each DROP literally)


def _run_outside_tx(stmts):
    with op.get_context().autocommit_block():
        for _desc, sql in stmts:
            op.execute(sql)


def upgrade():
    _run_outside_tx(_UPGRADE)


def downgrade():
    _run_outside_tx(_DOWNGRADE)
```

### 3.3 ORM extensions (`app/modules/staff/models.py`)

Add the new mapped columns to `StaffMember` (one-to-one with the migration). Add a new `StaffPayRate` model. No relationships eager-loaded (kept light per `D-H6` audit guidance).

### 3.4 Pydantic schema additions (`app/modules/staff/schemas.py`)

- `StaffMemberCreate` and `StaffMemberUpdate` gain all new fields. Plain-text inputs for `ird_number` and `bank_account_number`; the service is what envelope-encrypts.
- `StaffMemberResponse` gains masked outputs (`ird_number: str | None` set to `***123` form by the service serializer).
- `StaffPayRateResponse` — `id`, `effective_from`, `hourly_rate`, `overtime_rate`, `change_reason`, `changed_by_email` (resolved via join).
- `StaffPayRateListResponse` — `{ items: [StaffPayRateResponse], total: int }` per project-overview.md rule.
- `RosterEmailRequest` — `{ week_start: date }`, `RosterSendResponse` — `{ ok: bool, message_id: str | None, reason: str | None }`.

The mask helpers live in `app/modules/staff/security.py`:

```python
import re

_MASKED_IRD_RE = re.compile(r"^\*+\d{2,4}$")
_MASKED_BANK_RE = re.compile(r"^\*\*-\*+-\*+\d{2}-\*+$|^\*+\d{2}-\*+$")


def mask_ird(plaintext: str | None) -> str | None:
    if not plaintext:
        return None
    digits = "".join(c for c in plaintext if c.isdigit())
    if len(digits) < 3:
        return "***"
    return "***" + digits[-3:]


def mask_bank_account(plaintext: str | None) -> str | None:
    if not plaintext:
        return None
    digits = "".join(c for c in plaintext if c.isdigit())
    if len(digits) < 4:
        return "**-****-****-**"
    return f"**-****-****{digits[-4:-2]}-**"


def is_masked_ird(value: str | None) -> bool:
    return bool(value and _MASKED_IRD_RE.match(value.strip()))


def is_masked_bank(value: str | None) -> bool:
    return bool(value and _MASKED_BANK_RE.match(value.strip()))
```

The service applies these to the outbound dict, and detects them on inbound saves to skip the field.

## 4. RBAC

No new roles. Phase 1 uses existing roles per `auth/service.py`:

- `global_admin` — everything.
- `org_admin` — full access org-wide.
- `branch_admin` / `location_manager` — full access for staff at their branch only (existing scoping logic continues to apply).
- `staff_member` (linked user) — read-only on own record. Phase 1 does not introduce a self-service edit path.

The `audit_logs` action `staff.minimum_wage_override` is restricted to `org_admin` because branch admins should not be authorising wages below the legal minimum.

## 5. API Surface

### 5.1 Existing endpoints — extended

| Endpoint | Phase 1 changes |
|---|---|
| `POST /api/v2/staff` | Accept new fields; envelope-encrypt IRD + bank; auto-set `probation_end_date`; auto-write initial `staff_pay_rates` row; gate behind `staff_management` module. |
| `PUT /api/v2/staff/:id` | Same accept-extended-payload logic; mask-pattern detection; auto-write `staff_pay_rates` row when rate changes; update `last_pay_review_date` when `change_reason='rate_change'`. |
| `GET /api/v2/staff/:id` | Mask IRD + bank; populate `employment_agreement_upload_url` (signed URL) for the Documents tab. |
| `GET /api/v2/staff` | Compliance counters in response payload: `compliance_summary: { probation_ending_soon: N, visa_expiring_soon: N, missing_agreement: N, pay_review_due: N, below_minimum_wage: N }`. |
| `POST /api/v2/staff` (create) + minimum-wage path | If submitted `hourly_rate < minimum_wage_threshold_nzd`, accept body field `minimum_wage_override: true` to allow; otherwise return HTTP 422 `{detail: 'minimum_wage_below_threshold', threshold: 23.15}`. |

### 5.2 New endpoints

| Endpoint | Method | Purpose | Returns |
|---|---|---|---|
| `/api/v2/staff/:id/pay-rates` | GET | Pay rate history list | `{ items: [...], total: N }` |
| `/api/v2/staff/:id/pay-rates` | POST | Manual rate-change entry (effective_from in future) | `StaffPayRateResponse` |
| `/api/v2/staff/:id/email-roster` | POST | Trigger roster email | `RosterSendResponse` |
| `/api/v2/staff/:id/sms-roster` | POST | Trigger roster SMS | `RosterSendResponse` |
| `/api/v2/staff/:id/employment-agreement` | POST | Multipart upload OR JSON `{ upload_id }` after a separate `/uploads` POST. Returns updated staff. | `StaffMemberResponse` |
| `/api/v2/public/staff-roster/:token` | GET | Public read-only roster view (no auth) | `{ staff_name, week_start, week_end, entries: [...] }` |

### 5.3 Roster delivery flow

```
POST /api/v2/staff/:id/email-roster {week_start}
  → service.send_roster_email(db, org_id, staff_id, week_start)
    → query schedule_entries WHERE staff_id=? AND start_time IN [week_start, week_end]
    → if no entries → return {ok: false, reason: 'no_shifts_in_week'}
    → render Jinja template app/templates/email/roster.html
    → call send_email(db, EmailMessage(...), dlq_task_name='roster_email',
                      dlq_task_args={...})
    → write audit_logs row action='roster.emailed'
    → return {ok: true, message_id: result.provider_message_id}
```

SMS path mirrors but composes a 160-char body and uses `connexus_sms`. The viewer-token URL is generated with the same `secrets.token_urlsafe(32)` pattern used in `app/modules/portal/service.py`. Tokens stored in a new lightweight table `staff_roster_view_tokens (id, org_id, staff_id, token, week_start, expires_at)` with idempotent upsert per (staff_id, week_start) so re-sending the same week reuses the same link.

### 5.4 Scheduled task `weekly_roster_broadcast`

Registered in `app/tasks/scheduled.py`:
- Runs every 30 min (existing scheduler tick) but the body short-circuits unless `(now() in org tz).weekday() == 4` (Friday) AND `now().hour == 16` (4 PM local).
- Holds the existing scheduler Redis SETNX lock per ISSUE-164 — no extra coordination needed.
- For each org with `staff_management` enabled, iterates staff with opt-in flags. Each staff send wrapped in `db.begin_nested()` SAVEPOINT.
- Logs per-staff outcome for ops grep.

## 6. Frontend Component Tree

### 6.1 `StaffDetail.tsx` — refactored

Becomes a thin shell:

```tsx
export default function StaffDetail({ staffId }: Props) {
  const moduleEnabled = useModuleEnabled('staff_management')
  const [activeTab, setActiveTab] = useTabHash('overview', ['overview', 'roster', 'documents'])
  const { staff, refresh, isLoading, error } = useStaffDetail(staffId)

  if (!moduleEnabled) {
    return <LegacyStaffDetail staffId={staffId} />
  }

  return (
    <Layout>
      <StaffHeader staff={staff} />
      <TabStrip
        tabs={[
          { id: 'overview', label: 'Overview' },
          { id: 'roster', label: 'Roster' },
          { id: 'documents', label: 'Documents' },
        ]}
        active={activeTab}
        onChange={setActiveTab}
      />
      <Suspense fallback={<MobileSpinner />}>
        {activeTab === 'overview' && <OverviewTab staff={staff} onSaved={refresh} />}
        {activeTab === 'roster' && <RosterTab staffId={staffId} />}
        {activeTab === 'documents' && <DocumentsTab staff={staff} onSaved={refresh} />}
      </Suspense>
    </Layout>
  )
}
```

### 6.2 `OverviewTab.tsx`

Sections:
1. **Personal info** — first/last name, email, phone, emergency contact (new)
2. **Employment** — type, start/end date, std hours/week, position, reporting_to, probation_end_date (auto-computed indicator), visa_expiry_date
3. **Tax & Pay** — tax_code (select), IRD (masked input — type to overwrite), KiwiSaver enrolled + rates, student_loan, hourly_rate, overtime_rate, bank_account_number (masked), Pay Rate History panel (collapsible)
4. **Schedule** — existing `WorkSchedule` weekly grid (`shift_start` / `shift_end` fields + `availability_schedule` JSONB)
5. **Clock-in & roster delivery** — `self_service_clock_enabled` toggle, `weekly_roster_email_enabled` toggle, `weekly_roster_sms_enabled` toggle, on-file photo upload
6. **Skills** — existing comma-separated input

Modal triggers:
- Below-minimum-wage save → `MinimumWageWarningModal`
- Discard changes → standard confirm

State management: local `useState` for form fields, `useDirty()` hook for unsaved-state tracking, `useNavigationGuard()` for tab/route changes.

### 6.3 `RosterTab.tsx`

```tsx
export default function RosterTab({ staffId }: { staffId: string }) {
  const [weekStart, setWeekStart] = useState(startOfWeek(new Date()))
  const { entries, refresh, isLoading } = useStaffRoster(staffId, weekStart)
  const [emailing, setEmailing] = useState(false)
  const [smsing, setSmsing] = useState(false)

  return (
    <div>
      <Toolbar>
        <WeekNavigator weekStart={weekStart} onChange={setWeekStart} />
        <button onClick={() => openAddShiftDrawer({ staffId, weekStart })}>Add shift</button>
        <button onClick={() => openTemplatePicker({ staffId, weekStart })}>Apply template</button>
        <button disabled={emailing} onClick={() => sendRosterEmail(staffId, weekStart, setEmailing)}>
          Email roster
        </button>
        <button disabled={smsing} onClick={() => sendRosterSms(staffId, weekStart, setSmsing)}>
          Send roster SMS
        </button>
      </Toolbar>
      <ScheduleCalendar
        entries={entries}
        focusStaffId={staffId}
        readOnly={false}
        onChange={refresh}
      />
    </div>
  )
}
```

### 6.4 `DocumentsTab.tsx`

Single section: "Employment agreement". Renders an upload slot (drag-drop + file picker). On select → POST to `/api/v2/uploads` (existing endpoint) → on success POST `/api/v2/staff/:id/employment-agreement` with the returned `upload_id`. Shows current file name + "View" link + "Replace" button if already uploaded.

### 6.5 `StaffList.tsx` additions

Above the existing search bar, render a `<ComplianceBanner>` showing the four counters from the new `compliance_summary` API response. Each counter is a clickable badge that adds a filter chip (URL-param) to the list. Below-minimum-wage staff get a red dot in the row.

## 7. User Workflow Traces

### 7.1 Create new staff with full employment data

```
User clicks "Add staff" on StaffList
→ existing CreateStaffModal opens (now with the expanded fieldset)
→ user fills name, email, hourly_rate=20.00, tax_code='M', IRD='123-456-789', kiwisaver_enrolled=true, ...
→ User clicks Save
→ Frontend: POST /api/v2/staff with raw payload
→ Backend service.create_staff:
    - validates duplicates (existing logic)
    - checks 20.00 < threshold(23.15) → returns 422 minimum_wage_below_threshold
→ Frontend opens MinimumWageWarningModal
→ User confirms
→ Frontend re-POSTs with minimum_wage_override=true
→ Backend:
    - envelope_encrypt IRD + bank → bytea columns
    - sets probation_end_date = start_date + 90d
    - inserts StaffMember
    - inserts staff_pay_rates row (initial_rate)
    - writes audit_logs (staff.created, staff.minimum_wage_override)
    - flush + refresh
    - returns masked StaffMemberResponse
→ Frontend redirects to /staff/:id#overview
```

### 7.2 Edit existing pay rate

```
User opens /staff/:id#overview
→ types new hourly_rate in the input (e.g. 25.00 → 27.50)
→ clicks Save
→ Frontend: PUT /api/v2/staff/:id with full payload
→ Backend service.update_staff:
    - detects 27.50 != current 25.00
    - writes audit_logs (staff.pay_rate_changed, staff.updated)
    - inserts staff_pay_rates row (rate_change, changed_by=user)
    - sets staff.last_pay_review_date = today
    - flush + refresh
→ Frontend: refetches staff + pay-rates history
→ PayRateHistoryPanel shows the new row at the top
```

### 7.3 Email roster button click

```
User clicks "Email roster" on RosterTab
→ Frontend: POST /api/v2/staff/:id/email-roster {week_start: '2026-06-08'}
→ Backend service.send_roster_email:
    - load schedule_entries
    - if 0 entries → returns {ok:false, reason:'no_shifts_in_week'}
    - render Jinja → HTML body
    - call send_email(db, EmailMessage(to=staff.email, subject=..., html_body=...), dlq_task_name='roster_email')
    - audit_logs (roster.emailed)
    - returns {ok:true, message_id}
→ Frontend: toast "Roster emailed to jane@example.com" or error toast
```

### 7.4 SMS roster button click

Same as 7.3 but uses `connexus_sms` provider. Body composed by helper `compose_roster_sms_body(staff, entries, viewer_url)`. Returns 422 with reason when phone missing or `weekly_roster_sms_enabled=false`.

## 8. Modal/Panel Inventory

| Element | Triggered by | Contains | Closes via |
|---|---|---|---|
| `MinimumWageWarningModal` | Save with rate < threshold | Warning copy + "Cancel" / "Confirm and override" | Backdrop click cancels; Confirm re-submits |
| `DiscardChangesModal` | Tab/route change with unsaved | "Discard changes?" / "Keep editing" | Backdrop = Keep editing |
| `AddShiftDrawer` | Roster tab "Add shift" | Date, start, end, entry_type, notes | X / Esc / Cancel / Save |
| `ApplyTemplateModal` | Roster tab "Apply template" | List of `shift_templates` + week-start picker | X / Save |
| `ConfirmDeleteShiftModal` | Click X on a shift | "Delete this shift?" | Backdrop / Cancel / Delete |
| `PayRateHistoryPanel` | Click "Show pay rate history" | Read-only list of `staff_pay_rates` | Click again to collapse |
| `EmailRosterToast` | Email roster outcome | Success or error message | Auto-dismiss 5s |

## 9. Error & Edge Case UI

| Case | UI |
|---|---|
| 422 minimum_wage_below_threshold | `MinimumWageWarningModal` |
| 422 missing required field | Inline red text under the field |
| 422 no_shifts_in_week (roster send) | Toast: "No shifts to send this week" |
| 422 phone_missing (sms roster) | Toast: "This staff has no phone number" |
| 404 staff not found | Redirect to /staff with toast |
| 403 (org_admin only) | Toast: "You don't have permission" |
| 409 (duplicate IRD or employee_id) | Inline red text under the offending field |
| 500 / network | Banner across top: "Save failed. Try again?" with retry button |
| Empty pay rate history | "No pay rate changes yet." |
| No on-file photo | Placeholder silhouette + "Upload photo" button |
| Module disabled (staff_management) | Legacy single-form view (no error — graceful fallback) |
| Loading | `MobileSpinner` |

## 10. List/Table specs

### 10.1 StaffList enhancements

- New columns: `Compliance` chip column (red dot if any of: below min wage / missing agreement / probation ending / visa expiring), `Last review` date.
- New filters: "Below min wage", "Probation ending", "Visa expiring", "Missing agreement", "Pay review due".
- Sorts: existing + new on `last_pay_review_date`.
- Empty state unchanged.

### 10.2 PayRateHistoryPanel

- Columns: `Effective from`, `Hourly`, `Overtime`, `Change`, `By`.
- Pagination: top 20, "Show more" button (rare to need pagination — most staff have <10 changes).
- Sort: descending by `effective_from`.

## 11. Integration Points

- **Setup wizard:** `staff_management` module's `setup_question` is automatically rendered by the existing `SetupGuide.tsx` flow once the module-registry insert lands. No frontend changes needed in setup-wizard.
- **Module gates:** the existing `useModuleEnabled('staff_management')` hook just works once the migration runs. Phase 1 doesn't need to touch `app/core/modules.py`.
- **Audit log viewer:** existing `AuditLog.tsx` admin screen will surface new actions automatically since it's slug-agnostic.
- **Subscription plan UI:** existing `SubscriptionPlans.tsx` global-admin screen will list `staff_management` and `payroll` in the modules picker without changes.
- **Email provider:** routes through unified `send_email` — no provider config changes needed.
- **SMS provider:** routes through `connexus_sms` — no provider changes; uses `SmsVerificationProvider` configured at global-admin level.

## 12. Concurrency / safety

- Pay-rate inserts are idempotent within a single update transaction — if two writes from the same browser tab race, the second may insert a duplicate row with the same `effective_from`. Phase 1 accepts this; if it becomes a real problem, add a partial unique index `(staff_id, effective_from, hourly_rate, overtime_rate)`.
- Roster-email opt-out: if a staff is deactivated the same minute a Friday-broadcast tick fires, the SAVEPOINT pattern means just that staff's send is skipped, batch continues.
- Mask round-trip: the form serialises masked values for display, but a save with the unchanged masked value MUST NOT clobber the real value. This is enforced server-side by the mask-detection regex; the client should also send the field as `null` when unchanged, but server-side is the definitive guard.

## 13. Performance considerations

- All new queries hit the new partial indexes (compliance counters use `idx_staff_review_due`, `idx_staff_probation_end`, `idx_staff_visa_expiry`).
- Compliance summary on `GET /staff` is computed inline as part of the existing query (single roundtrip — five small `COUNT(*) FILTER (WHERE ...)` aggregates).
- Roster-email Jinja render and SMS compose are quick (<10 ms). The `send_email` and `connexus_sms.send` calls are the heavy work — already async and DLQ-backed.

## 14. Testing plan

Unit tests:
- `tests/unit/test_staff_phase1_mask.py` — round-trip masking + mask-detection edge cases.
- `tests/unit/test_staff_pay_rate_history.py` — initial-rate write, rate-change write, no write on no-change.
- `tests/unit/test_staff_phase1_minimum_wage.py` — 422 path, override path, audit row.
- `tests/unit/test_staff_phase1_roster_delivery.py` — email + SMS happy paths, missing-email/phone refuse paths.
- Hypothesis property test on `mask_ird` and `mask_bank_account` (any input, output never exposes more than the documented digits).

E2E:
- `scripts/test_staff_employment_record_e2e.py` per R13.

Migration smoke:
- `docker compose exec app alembic upgrade head` runs cleanly on dev.
- Verify counters: `SELECT slug FROM module_registry WHERE slug IN ('staff_management','payroll')` returns 2 rows; same for `feature_flags.key`.

## 15. Rollout

1. Apply migrations 0203 + 0204 on dev → verify schema + module rows.
2. Ship backend changes behind module-gate (default disabled).
3. Ship frontend changes — legacy single-form view remains the default for any org without the module enabled.
4. Manually flip `staff_management` enabled on Pi PROD's primary org → smoke-test in production with one staff record.
5. Once smoke passes, leave the module gate as-is and let orgs self-enable via the setup wizard.

Rollback path: `alembic downgrade -1` removes columns + tables. Module-registry inserts are reversible. Frontend code is feature-gated, so reverting the gate flag also reverts the UI.

## 16. Verified-against-code addendum

Cross-reference against the actual codebase before implementation begins:

- ✅ `app/core/encryption.py::envelope_encrypt` exists and accepts str|bytes, returns bytes.
- ✅ `app/integrations/email_sender.py::send_email` accepts `dlq_task_name` + `dlq_task_args` kwargs (post-quick-win-#10).
- ✅ `app/modules/staff/models.py::StaffMember` is the existing ORM — additive changes only.
- ✅ `app/modules/scheduling_v2/models.py::ScheduleEntry` has `entry_type IN ('job','booking','break','other','leave')` — Phase 1 doesn't add new entry_type values.
- ✅ `app/core/modules.py::ModuleService.is_enabled` is the gate API; it queries `module_registry` + `org_modules`.
- ✅ `module_registry` columns include `setup_question` + `setup_question_description` (verified in DATABASE_TABLES.md and setup_guide tests).
- ✅ `feature_flags` table key is `key` (not `slug`), scope column exists, default_enabled column exists.
- ✅ `subscription_plans.enabled_modules` is JSONB.
- ✅ Latest alembic head pre-Phase-1 = `0202`. New migrations get 0203, 0204.
- ✅ `connexus_sms` is the SMS path — provider is keyed by `provider_key='connexus'` in `SmsVerificationProvider`. There is no module-level "send_sms" function today; Phase 1 introduces a thin helper in `app/integrations/sms_sender.py` (new file, mirroring email_sender's shape) that picks an active provider and calls `ConnexusSmsClient`.
- ✅ Public-token pattern from `app/modules/portal/service.py` — `secrets.token_urlsafe(32)`, expires_at timestamp column.
- ⚠️ The "default subscription plan" slug is uncertain — `subscription_plans` has `name`, `is_archived`, but no `slug` column we can rely on. Migration uses `name ILIKE` heuristic + `is_archived=false`. Logged as STAFF-001 to settle the exact target before merge.

## 17. Spec completeness checklist self-check

Per `.kiro/steering/spec-completeness-checklist.md`:

- ✅ §1 Navigation & Access — covered in §2.
- ✅ §2 Frontend Component Tree — §6.
- ✅ §3 User Workflow Trace — §7.
- ✅ §4 Modal/Panel Inventory — §8.
- ✅ §5 Toolbar/Action Bar — §6.3 RosterTab toolbar, §6.4 DocumentsTab.
- ✅ §6 List/Table Spec — §10.
- ✅ §7 Error & Edge Case UI — §9.
- ✅ §8 Integration Points — §11.
