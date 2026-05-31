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

- **Route:** existing `/staff/:id` route stays unchanged (registered in `App.tsx:575`). Route-level gate is `<ModuleRoute moduleSlug="staff">` — that's the **existing legacy `staff` module**, which controls whether `/staff/*` routes are reachable at all. Phase 1 does not change this gate.
- **Two separate module gates co-exist:**
  - **`staff` (legacy module, route gate):** if disabled, all `/staff/*` routes return the FeatureNotAvailable page. Pre-existing behaviour, untouched by Phase 1. Path-prefix middleware (`app/middleware/modules.py::MODULE_ENDPOINT_MAP`) returns HTTP **403** for any disabled-module API call. Frontend route gate is `<ModuleRoute moduleSlug="staff">`.
  - **`staff_management` (new module, feature gate, introduced in Phase 1):** if disabled (but `staff` enabled), the page renders the legacy single-form `LegacyStaffDetail` view. If enabled, the tabbed shell renders. The Payroll module's dependency chain points at `staff_management` (NOT the legacy `staff` slug), so enabling Payroll auto-enables `staff_management`. The new sub-feature endpoints use a service-layer call to `ModuleService.is_enabled` and return HTTP **404** `{"detail": "not_enabled", "module": "staff_management"}` (NOT 403 like the path-prefix gate). The 404 vs 403 difference is deliberate (P1-N4): the broad path-prefix gate already asserts access denial via 403 for any `/staff/*` call when the legacy `staff` module is off; the finer `staff_management` sub-gate uses 404 to hide the new sub-endpoints (e.g. `/pay-rates`, `/email-roster`) without re-asserting denial. Users never see a 404 in the UI because the frontend pre-checks `useModules().isEnabled('staff_management')` and renders `LegacyStaffDetail` instead.
- **Tabs are sub-routes via URL hash** (`/staff/:id#overview`).
- **Role guard:** existing roles (`org_admin`, `branch_admin`, `location_manager`) — no new role introduced (§4).
- **Module-gate hook usage:** `const { isEnabled } = useModules(); const moduleEnabled = isEnabled('staff_management')`. The hook is `useModules()` (returns `{ isEnabled, enabledModules, ... }`), not `useModuleEnabled()`.
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
            ADD COLUMN IF NOT EXISTS residency_type text NOT NULL DEFAULT 'citizen',
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
    # G2 — residency_type drives visa_expiry_date visibility + compliance counter.
    op.execute("""
        ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_residency_type;
        ALTER TABLE staff_members ADD CONSTRAINT ck_staff_residency_type
            CHECK (residency_type IN ('citizen','permanent_resident','work_visa','student_visa','other'));
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

    # Update unarchived subscription plans' enabled_modules — append both
    # slugs. STAFF-001 resolved (P1-N2): all unarchived plans get the
    # modules; per-org disablement is the gate. The redundant ILIKE
    # clauses were removed.
    op.execute("""
        UPDATE subscription_plans
        SET enabled_modules = (
            SELECT jsonb_agg(DISTINCT m)
            FROM jsonb_array_elements_text(enabled_modules || '["staff_management","payroll"]'::jsonb) m
        )
        WHERE is_archived = false;
    """)

    # Feature flag mirrors per implementation-completeness Rule 8.
    # P1-N1 fix: feature_flags has no `scope` or `default_enabled` columns;
    # actual columns are (id, key, display_name [NOT NULL], description,
    # category, access_level, dependencies, default_value, is_active,
    # targeting_rules). Pattern matches alembic 0067 + 0191 seed inserts.
    # P1-N14 fix: default_value=true follows the policy from migration
    # 0171_fix_feature_flag_defaults.py — module gate is the real lever;
    # the flag is a passive mirror.
    op.execute("""
        INSERT INTO feature_flags (
            id, key, display_name, description, category,
            access_level, dependencies, default_value,
            is_active, targeting_rules
        ) VALUES
        (
            gen_random_uuid(), 'staff_management', 'Staff Management',
            'Staff Management module — gates the tabbed staff record, pay rates, compliance counters, roster delivery.',
            'operations', 'all_users', '[]'::jsonb, true,
            true, '[]'::jsonb
        ),
        (
            gen_random_uuid(), 'payroll', 'Payroll & Payslips',
            'Payroll & Payslips module — gates payslip generation, allowances, KiwiSaver auto-calc, termination payouts.',
            'operations', 'all_users', '["staff_management"]'::jsonb, true,
            true, '[]'::jsonb
        )
        ON CONFLICT (key) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS staff_roster_view_tokens;")
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
            DROP COLUMN IF EXISTS residency_type,
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
        ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_residency_type;
    """)
    op.execute("DELETE FROM module_registry WHERE slug IN ('staff_management', 'payroll');")
    op.execute("DELETE FROM feature_flags WHERE key IN ('staff_management', 'payroll');")
```

### 3.1.1 `staff_roster_view_tokens` table (added inside the same migration, G8)

> **P1-N3 implementation note.** The CREATE statement below MUST be inlined into the `0203_staff_phase1_schema.py::upgrade()` body alongside the `staff_pay_rates` block — it is not a separate migration. The downgrade in §3.1 already drops `staff_roster_view_tokens` first; the upgrade body must match.

```sql
CREATE TABLE IF NOT EXISTS staff_roster_view_tokens (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    staff_id    uuid NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE,
    token       text NOT NULL,
    week_start  date NOT NULL,
    expires_at  timestamptz NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (staff_id, week_start)
);
ALTER TABLE staff_roster_view_tokens ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON staff_roster_view_tokens
    USING (org_id = current_setting('app.current_org_id', true)::uuid);
```

`ON DELETE CASCADE` on both FKs is the G8 fix — when a staff is hard-deleted via `DELETE /staff/:id/permanent`, all of their tokens go with them; same when an org is deleted. The unique `(staff_id, week_start)` index is the upsert key for `get_or_create_viewer_token` (resending the same week reuses the existing token, doesn't proliferate rows).

The unique index on `token` itself is created in migration `0204` (the CONCURRENTLY pack) since it's queried on every public viewer hit and must be fast.

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

The `audit_log` action `staff.minimum_wage_override` is restricted to `org_admin` because branch admins should not be authorising wages below the legal minimum.

## 5. API Surface

### 5.1 Existing endpoints — extended

| Endpoint | Phase 1 changes |
|---|---|
| `POST /api/v2/staff` | Accept new fields; envelope-encrypt IRD + bank; auto-set `probation_end_date`; auto-write initial `staff_pay_rates` row; gate behind `staff_management` module. |
| `PUT /api/v2/staff/:id` | Same accept-extended-payload logic; mask-pattern detection; auto-write `staff_pay_rates` row when rate changes; update `last_pay_review_date` when `change_reason='rate_change'`. |
| `GET /api/v2/staff/:id` | Mask IRD + bank; populate `employment_agreement_upload_url` (signed URL) for the Documents tab. |
| `GET /api/v2/staff` | Compliance counters in response payload: `compliance_summary: { probation_ending_soon, visa_expiring_soon, missing_agreement, pay_review_due, below_minimum_wage, missing_employee_id, missing_start_date }` (all 7 keys, all integer counts). **The list response shape stays `{ staff: [...], total, page, page_size }` (NOT renamed to `items` — would break existing consumers per `app/modules/staff/schemas.py:92`). The new field is `compliance_summary` as a parallel top-level key.** (P1-N8 + P1-N13.) |
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
    → write audit_log row action='roster.emailed'
    → return {ok: true, message_id: result.provider_message_id}
```

SMS path mirrors but composes a 160-char body (downgrading to UCS-2 multi-part when the staff `first_name` contains Māori macrons or other non-GSM-7 characters per R9.3) and uses `connexus_sms`. The viewer-token URL is generated with the same `secrets.token_urlsafe(32)` pattern used in `app/modules/portal/service.py`. Tokens stored in `staff_roster_view_tokens` (DDL in §3.1.1) with idempotent upsert per `(staff_id, week_start)` so re-sending the same week reuses the same link.

**Rate limit on public viewer (G5):** the unauthenticated `GET /api/v2/public/staff-roster/:token` endpoint inherits a per-IP rate limit at a tightened threshold: **30 requests per minute per IP**. (P1-N10 fix: `app/middleware/rate_limit.py` does NOT have a "policy map" data structure today; it uses hardcoded path-prefix conditionals.) Add a new conditional block to `_apply_rate_limits` mirroring the existing HA-heartbeat per-IP limit pattern (lines 252-265). Constants `_PUBLIC_STAFF_ROSTER_PATH_PREFIX = "/api/v2/public/staff-roster/"` and `_PUBLIC_STAFF_ROSTER_RATE_LIMIT = 30` (per minute), Redis key `rl:public_staff_roster:ip:{client_ip}`. Returns 429 with `Retry-After` header on breach. The 32-byte token's entropy makes brute-force impractical, but the limit defends against accidental scraping (e.g., a token leaked into a public Slack channel, scraped by web crawlers).

### 5.5 Token revocation on staff deactivation/termination (G4)

When a staff is deactivated (`PUT /staff/:id/deactivate` or sets `is_active=false`) or terminated (sets `employment_end_date`), the service-layer flow runs the following SQL inside the same transaction:

```python
# In StaffService.deactivate_staff / terminate_staff, after setting is_active=false:
result = await db.execute(
    update(StaffRosterViewToken)
    .where(
        StaffRosterViewToken.staff_id == staff_id,
        StaffRosterViewToken.org_id == org_id,
        StaffRosterViewToken.expires_at > func.now(),
    )
    .values(expires_at=func.now())
    .returning(StaffRosterViewToken.id)
)
revoked = result.rowcount or 0
if revoked > 0:
    await write_audit_log(
        session=db,
        org_id=org_id, user_id=current_user.id,
        action='roster.tokens_revoked',
        entity_type='staff_member', entity_id=staff_id,
        before_value=None, after_value={'tokens_revoked_count': revoked},
    )
```

The public viewer endpoint `GET /api/v2/public/staff-roster/:token` then checks `expires_at > now()` and returns **HTTP 410 Gone** with `{ "detail": "token_expired_staff_deactivated" }` for any revoked token. (Distinct from 404 — "this token did exist but is no longer valid", helps the legitimate recipient understand what happened without leaking which staff was deactivated.)

A reactivation flow (`POST /staff/:id/activate`) does **not** automatically un-revoke tokens — the staff would need a fresh roster email/SMS to get a new link. This is the safer default; we accept the minor inconvenience to avoid resurrecting stale tokens.

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
  const { isEnabled } = useModules()
  const moduleEnabled = isEnabled('staff_management')
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
2. **Employment** — type, start/end date, std hours/week, position, reporting_to, probation_end_date (auto-computed indicator), `residency_type` select (citizen / permanent resident / work visa / student visa / other), `visa_expiry_date` date input — **conditionally rendered (G2)**: only visible when `residency_type IN ('work_visa', 'student_visa', 'other')`. Switching residency_type back to citizen/resident hides the field but does NOT clear the existing value (the admin may need to set residency back temporarily without losing the data).
3. **Tax & Pay** — tax_code (select), IRD (masked input — type to overwrite), KiwiSaver enrolled + rates, student_loan, hourly_rate, overtime_rate, bank_account_number (masked), Pay Rate History panel (collapsible)
4. **Schedule** — existing `WorkSchedule` weekly grid (`shift_start` / `shift_end` fields + `availability_schedule` JSONB)
5. **Clock-in & roster delivery** — `self_service_clock_enabled` toggle, `weekly_roster_email_enabled` toggle, `weekly_roster_sms_enabled` toggle, on-file photo upload
6. **Skills** — existing comma-separated input

**Inline warnings on the Overview tab** (G1, G3):
- Above the Employment section, if `employee_id IS NULL` → amber inline banner *"This staff has no employee code. Kiosk clock-in (Phase 3) won't work until you set one. Tip: use the format `EMP-001` or `JD-2024`."* with a quick-set input.
- Above the Employment section, if `employment_start_date IS NULL` → amber inline banner *"Employment start date is required for Phase 2 leave accrual. Please set it before Phase 2 ships."*

Both inline banners disappear once the field is set + saved.

Modal triggers:
- Below-minimum-wage save → `MinimumWageWarningModal`
- Discard changes → standard confirm

State management: local `useState` for form fields, `useDirty()` hook for unsaved-state tracking, `useNavigationGuard()` for tab/route changes.

### 6.3 `RosterTab.tsx`

The Roster tab fetches scheduling entries from `GET /api/v2/schedule?staff_id=:id&start=:weekStartIso&end=:weekEndIso` (verified path per `app/main.py:516`; the endpoint accepts `start`, `end`, `staff_id`, `location_id`). Response shape is `{ entries: [...], total: N }` — note the key is `entries`, not `items`. The frontend MUST consume it as `res.data?.entries ?? []` per `safe-api-consumption.md`.

`ScheduleCalendar` today is a self-contained `export default function ScheduleCalendar()` with no props; Phase 1 task E4 extends its signature to accept ONLY a single new optional prop `focusStaffId?: string` and threads that into the existing internal `selectedStaffId` state used by `MobileDayView`. When `focusStaffId` is set, only that staff's entries render, hiding the multi-column staff grid. The calendar continues to fetch its own data via its existing internal data hook — Phase 1 does not invert the data flow (P1-N6 + P1-N7: the spec previously implied an `entries` / `readOnly` / `onChange` prop trio that would have required a much bigger refactor; that's deliberately out of scope here).

```tsx
export default function RosterTab({ staffId }: { staffId: string }) {
  const { weekStart, setWeekStart } = useRosterWeek()
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
      <ScheduleCalendar focusStaffId={staffId} />
    </div>
  )
}
```

`useRosterWeek` is a tiny local hook (just a `useState<Date>` initialised to `startOfWeek(new Date())`). The toolbar's email/SMS buttons need the active week, but the calendar itself owns the entries fetch.

```tsx
// Toolbar-only hook — tracks active week for the email/SMS buttons.
// (Reference-only data-fetching hook for E4 if the team later decides
// to drive entries from outside; not used in Phase 1's default path.)
export function useRosterWeek(initial?: Date) {
  const [weekStart, setWeekStart] = useState<Date>(initial ?? startOfWeek(new Date()))
  return { weekStart, setWeekStart }
}

// Reference-only — kept for future extension (P1-N7 — not active in Phase 1):
export function useStaffRoster(staffId: string, weekStart: Date) {
  const [entries, setEntries] = useState<ScheduleEntry[]>([])
  const [isLoading, setIsLoading] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    setIsLoading(true)
    apiClient
      .get('/api/v2/schedule', {
        signal: controller.signal,
        params: {
          staff_id: staffId,
          start: weekStart.toISOString(),
          end: addDays(weekStart, 7).toISOString(),
        },
      })
      .then(res => setEntries(res.data?.entries ?? []))
      .catch(err => { if (!controller.signal.aborted) console.error('roster fetch failed', err) })
      .finally(() => setIsLoading(false))
    return () => controller.abort()
  }, [staffId, weekStart])
  return { entries, isLoading }
}
```

Note the absolute `/api/v2/schedule` path — the project's `apiClient` is configured with `baseURL: '/api/v1'` and an interceptor that strips the baseURL when the URL starts with `/api/`. Every other v2 call in the codebase uses an absolute path; never an explicit `baseURL: '/api/v2'` override (P1-N5).

### 6.4 `DocumentsTab.tsx`

Single section: "Employment agreement". Renders an upload slot (drag-drop + file picker). On select → POST to `/api/v2/uploads` (existing endpoint) → on success POST `/api/v2/staff/:id/employment-agreement` with the returned `upload_id`. Shows current file name + "View" link + "Replace" button if already uploaded.

### 6.5 `StaffList.tsx` additions

Above the existing search bar, render a `<ComplianceBanner>` showing the **seven counters** from the new `compliance_summary` API response (R6.1). Each counter is a clickable badge that adds a filter chip (URL query param) to the list:

| Counter | API key | Filter chip query param | Row indicator |
|---|---|---|---|
| Probation ending in 14 days | `probation_ending_soon` | `?filter=probation_ending` | — |
| Visa expiring in 60 days (visa-holders only) | `visa_expiring_soon` | `?filter=visa_expiring` | — |
| Pay review due this month | `pay_review_due` | `?filter=pay_review_due` | — |
| Below NZ minimum wage | `below_minimum_wage` | `?filter=below_minimum_wage` | 🔴 red dot in row |
| Missing employment agreement | `missing_agreement` | `?filter=missing_agreement` | — |
| **Missing employee code (G1)** | `missing_employee_id` | `?filter=missing_employee_id` | 🟠 amber dot |
| **Missing employment start date (G3)** | `missing_start_date` | `?filter=missing_start_date` | 🟠 amber dot |

Multiple amber dots stack horizontally on the row (small chip cluster) so admins can see at a glance which fields a particular staff is missing. Hovering any dot shows a tooltip naming the missing field(s).

The "Missing employment start date" counter gets a **persistent banner** above the list when count > 0 reading:

> *"Phase 2 leave accrual will skip these staff until you backfill `employment_start_date`. Set start dates now to avoid disruption when Phase 2 ships."*

This banner stays visible (not dismissible) for the duration of Phase 1 lifecycle, dismissed only when the counter drops to zero. Rationale: the Phase 2 dependency is severe enough that admins should be nagged every time they hit the staff list, not just once.

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
    - writes audit_log (staff.created, staff.minimum_wage_override)
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
    - writes audit_log (staff.pay_rate_changed, staff.updated)
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
    - audit_log (roster.emailed)
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
| 410 token_expired_staff_deactivated (G4, public viewer) | Standalone error page: "This roster link is no longer valid — the staff member has been deactivated. Contact the workshop for the latest schedule." |
| 429 rate_limited (G5, public viewer) | Standalone error page: "Too many requests. Please try again in a minute." Reads `Retry-After` header. |
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
- **Module gates:** the existing `useModules().isEnabled('staff_management')` API just works once the migration runs. Phase 1 doesn't need to touch `app/core/modules.py`.
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
- ✅ `feature_flags` table key column is `key` (not `slug`), unique. (P1-N1: the actual columns are `id, key, display_name [NOT NULL], description, category, access_level, dependencies, default_value, is_active, targeting_rules, ...` — there is NO `scope` column and NO `default_enabled` column. The Phase 1 INSERT in §3.1 was corrected accordingly.)
- ✅ `subscription_plans.enabled_modules` is JSONB.
- ✅ `app/modules/staff/schemas.py::StaffMemberListResponse` returns `{ staff: [...], total, page, page_size }` — Phase 1 keeps the existing `staff` field name (does NOT rename to `items`); adds `compliance_summary` as a parallel top-level key (P1-N8).
- ✅ Latest alembic head pre-Phase-1 = `0202`. New migrations get 0203, 0204.
- ✅ `connexus_sms` is the SMS path — provider is keyed by `provider_key='connexus'` in `SmsVerificationProvider`. There is no module-level "send_sms" function today; Phase 1 introduces a thin helper in `app/integrations/sms_sender.py` (new file, mirroring email_sender's shape) that picks an active provider and calls `ConnexusSmsClient`.
- ✅ Public-token pattern from `app/modules/portal/service.py` — `secrets.token_urlsafe(32)`, expires_at timestamp column.
- ✅ Path-prefix module-disabled middleware (`app/middleware/modules.py`) returns HTTP **403** for any disabled-module API call. The new sub-feature `staff_management` gate uses HTTP **404** (P1-N4 — deliberate; covered in §2 dual-gate explanation).
- ✅ `app/middleware/rate_limit.py` uses hardcoded path-prefix conditionals (no policy map data structure). The HA-heartbeat block at lines 252-265 is the canonical pattern for new per-IP limits (P1-N10).
- ✅ `audit_log` table is **singular** (`audit_log`, not `audit_logs`) per `app/modules/admin/models.py:317`. Phase 1 spec text updated globally (P1-N11). The `write_audit_log` helper takes `before_value` / `after_value` JSONB fields — there is no separate `metadata` column (P1-N12).
- ✅ STAFF-001 resolved during P1-N2 review: all unarchived subscription plans receive both `staff_management` and `payroll` in `enabled_modules` (matches existing platform behaviour where modules ship enabled in every plan; per-org disablement is the gate).

## 17. Spec completeness checklist self-check

Per `.kiro/steering/spec-completeness-checklist.md`:

- ✅ §1 Navigation & Access — covered in §2.
- ✅ §2 Frontend Component Tree — §6.
- ✅ §3 User Workflow Trace — §7.
- ✅ §4 Modal/Panel Inventory — §8.
- ✅ §5 Toolbar/Action Bar — §6.3 RosterTab toolbar, §6.4 DocumentsTab.
- ✅ §6 List/Table Spec — §10.
- ✅ §7 Error & Edge Case UI — §9 (incl. new 410 + 429 cases for the public viewer endpoint).
- ✅ §8 Integration Points — §11.

## 18. Gap-analysis closure addendum

Tracking which gaps from the spec-vs-master-plan review (recorded in conversation history) are closed in this revision:

- ✅ **G1** — Missing-employee_id counter added to R6.1 + `compliance_summary` in §5.1 + `ComplianceBanner` in §6.5 + inline OverviewTab warning in §6.2.
- ✅ **G2** — `residency_type` column added to staff_members migration §3.1; CHECK constraint enforced; conditional rendering of `visa_expiry_date` in §6.2; visa-expiry compliance counter filtered to visa-holders only in R6.1.
- ✅ **G3** — Missing-employment_start_date counter added to R6.1 + `compliance_summary` + persistent banner above the Staff List (not dismissible until count drops to zero) + inline OverviewTab warning + explicit Non-Goal stating that admins must backfill before Phase 2.
- ✅ **G4** — Token revocation flow specified in §5.5; deactivation/termination writes `expires_at=now()` to all of a staff's active tokens + emits `roster.tokens_revoked` audit row; public viewer returns 410 Gone for revoked tokens.
- ✅ **G5** — Per-IP rate limit of 30 req/min applied to `GET /api/v2/public/staff-roster/:token` per §5.3.
- ✅ **G6** — Mobile-app changes explicitly listed as a Non-Goal for Phase 1.
- ✅ **G7** — UCS-2 multi-part SMS fallback documented in R9.3 — Māori macrons trigger UCS-2 encoding, multi-part SMS billing accepted, no transliteration.
- ✅ **G8** — `ON DELETE CASCADE` on both `staff_roster_view_tokens.org_id` and `staff_roster_view_tokens.staff_id` specified in §3.1.1.
