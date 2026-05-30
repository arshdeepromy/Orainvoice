# Staff Management Phase 4 — Design

## 1. Architecture overview

Phase 4 adds the payroll surface. New module `app/modules/payslips/` contains the bulk of code. The Pay Periods page lives under Settings → People → Pay Periods. The PDF renderer reuses the existing Jinja + WeasyPrint setup (path mirrored on `app/modules/invoices/service.py:4446`).

Backend touches:
- `alembic/versions/0209_payslip_schema.py`
- `alembic/versions/0210_payslip_indexes.py`
- `app/modules/payslips/{models,schemas,service,router,pdf,calc,termination}.py`
- `app/templates/payslips/payslip.html` (new Jinja template) + a print-CSS file.
- `app/tasks/scheduled.py` — register `roll_pay_periods` daily; update existing `update_adp_snapshots` to use real data.
- `app/main.py` — include router.

Frontend touches:
- `frontend/src/pages/staff/tabs/PayslipsTab.tsx`
- `frontend/src/pages/payroll/PayRunPage.tsx` (bulk pay run)
- `frontend/src/pages/payroll/PayslipDetail.tsx` (draft editor)
- `frontend/src/pages/settings/people/PayPeriodsPage.tsx`
- `frontend/src/pages/settings/people/AllowanceTypesPage.tsx`
- `frontend/src/pages/staff/components/TerminationModal.tsx`
- `frontend/src/pages/reports/WageVariancePage.tsx`

## 2. Navigation

- Sidebar: "Payroll" under People (visible when `payroll` module enabled).
- Tab on Staff Detail: "Payslips" — added between Hours and Documents.
- Settings → People → Pay Periods + Allowance Types.
- Reports: Wage variance.
- Module gate: `payroll` (which depends on `staff_management` per Phase 1's module_registry insert).

## 3. Data Model

### 3.1 Migration `0209_payslip_schema.py`

```sql
CREATE TABLE IF NOT EXISTS pay_periods (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    pay_date date NOT NULL,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','finalised','paid')),
    created_at timestamptz NOT NULL DEFAULT now(),
    finalised_at timestamptz,
    paid_at timestamptz,
    UNIQUE (org_id, start_date)
);

CREATE TABLE IF NOT EXISTS allowance_types (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    taxable boolean NOT NULL DEFAULT true,
    default_amount numeric(10,2),
    unit text NOT NULL DEFAULT 'shift' CHECK (unit IN ('shift','period','km')),
    active boolean NOT NULL DEFAULT true,
    display_order int NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, code)
);

CREATE TABLE IF NOT EXISTS payslips (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    staff_id uuid NOT NULL REFERENCES staff_members(id),
    pay_period_id uuid NOT NULL REFERENCES pay_periods(id),
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','finalised','voided')),
    ordinary_hours numeric(8,2) NOT NULL DEFAULT 0,
    overtime_hours numeric(8,2) NOT NULL DEFAULT 0,
    public_holiday_hours numeric(8,2) NOT NULL DEFAULT 0,
    ordinary_rate numeric(10,2),
    overtime_rate numeric(10,2),
    public_holiday_rate numeric(10,2),                              -- G2: defaulted to ordinary_rate × 1.5
    gross_pay numeric(12,2) NOT NULL DEFAULT 0,
    gross_ytd numeric(12,2) NOT NULL DEFAULT 0,
    net_pay numeric(12,2) NOT NULL DEFAULT 0,
    pdf_upload_id uuid,
    emailed_at timestamptz,
    finalised_at timestamptz,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (staff_id, pay_period_id)
);

CREATE TABLE IF NOT EXISTS payslip_allowances (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payslip_id uuid NOT NULL REFERENCES payslips(id) ON DELETE CASCADE,
    allowance_type_id uuid REFERENCES allowance_types(id),
    label text NOT NULL,
    quantity numeric(10,2) NOT NULL DEFAULT 1,                      -- G18: shifts / km / 1 (period)
    unit text NOT NULL DEFAULT 'period'                             -- G18: copied from allowance_types.unit at attach time
        CHECK (unit IN ('shift','period','km')),
    amount numeric(12,2) NOT NULL,
    taxable boolean NOT NULL DEFAULT true
);

-- G4 — staff-specific recurring allowance rules.
CREATE TABLE IF NOT EXISTS staff_recurring_allowances (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    staff_id uuid NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE,
    allowance_type_id uuid NOT NULL REFERENCES allowance_types(id) ON DELETE RESTRICT,
    amount numeric(10,2),                                           -- NULL = inherit allowance_types.default_amount
    quantity numeric(10,2),                                         -- NULL = derive from unit per R4.6
    active boolean NOT NULL DEFAULT true,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (staff_id, allowance_type_id)
);

CREATE TABLE IF NOT EXISTS payslip_deductions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payslip_id uuid NOT NULL REFERENCES payslips(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN (
        'paye','acc_levy','kiwisaver_employee','kiwisaver_employer',
        'student_loan','child_support','voluntary'
    )),
    label text NOT NULL,
    amount numeric(12,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS payslip_reimbursements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payslip_id uuid NOT NULL REFERENCES payslips(id) ON DELETE CASCADE,
    label text NOT NULL,
    amount numeric(12,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS payslip_leave_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payslip_id uuid NOT NULL REFERENCES payslips(id) ON DELETE CASCADE,
    leave_type_id uuid NOT NULL REFERENCES leave_types(id),
    hours numeric(8,2) NOT NULL,
    rate numeric(10,2) NOT NULL,
    amount numeric(12,2) NOT NULL,
    balance_after numeric(8,2) NOT NULL
);

ALTER TABLE organisations
    ADD COLUMN IF NOT EXISTS pay_period_cadence text NOT NULL DEFAULT 'fortnightly',
    ADD COLUMN IF NOT EXISTS pay_period_anchor_day int NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS pay_date_offset_days int NOT NULL DEFAULT 3;  -- G5: days after end_date when payment goes out
ALTER TABLE organisations DROP CONSTRAINT IF EXISTS ck_org_pay_period_cadence;
ALTER TABLE organisations ADD CONSTRAINT ck_org_pay_period_cadence
    CHECK (pay_period_cadence IN ('weekly','fortnightly','monthly'));
```

All RLS-enabled with tenant_isolation policy. Allowance defaults seeded for every existing org.

### 3.2 Indexes (`0210_payslip_indexes.py`) — CONCURRENTLY

- `idx_payslips_org_period_status ON payslips (org_id, pay_period_id, status)`
- `idx_payslips_staff_period ON payslips (staff_id, pay_period_id DESC)`
- `idx_payslips_staff_status_finalised_desc ON payslips (staff_id, status, finalised_at DESC)` — G9: staff self-service list ordered by recency, only finalised.
- `idx_pay_periods_org_status ON pay_periods (org_id, status, start_date DESC)`
- `idx_pay_periods_org_dates ON pay_periods (org_id, start_date, end_date)` — G25: covering query "pay_period containing :end_date" during termination.
- `idx_payslip_allowances_payslip ON payslip_allowances (payslip_id)`
- `idx_payslip_deductions_payslip ON payslip_deductions (payslip_id)`
- `idx_payslip_leave_lines_payslip ON payslip_leave_lines (payslip_id)`
- `idx_staff_recurring_allowances_staff ON staff_recurring_allowances (staff_id) WHERE active = true` — G4: lookup at draft-generation time.

## 4. Service layer

### 4.1 `calc.py` — wage math

```python
from decimal import Decimal

PUBLIC_HOLIDAY_DEFAULT_MULTIPLIER = Decimal('1.5')  # Holidays Act s50 (G2)

@dataclass
class PayslipCalc:
    ordinary: Decimal
    overtime: Decimal
    public_holiday: Decimal
    allowances_taxable: Decimal
    allowances_non_taxable: Decimal
    casual_8pct: Decimal
    gross: Decimal
    deductions_total: Decimal
    reimbursements_total: Decimal
    net: Decimal
    kiwisaver_employee: Decimal
    kiwisaver_employer: Decimal


async def compute_payslip(db, staff: StaffMember, period: PayPeriod) -> PayslipCalc:
    """Single source of truth for math.
    Reads timesheet_approvals, leave_lines, allowances, deductions.
    Casual 8% line auto-attached.
    KiwiSaver auto from rate columns.

    G2 — public_holiday band:
        ordinary_rate = staff.hourly_rate
        overtime_rate = staff.overtime_rate or (ordinary_rate × 1.5)
        public_holiday_rate = (
            payslip.public_holiday_rate          # admin override on draft, if set
            or ordinary_rate × PUBLIC_HOLIDAY_DEFAULT_MULTIPLIER
        )
        public_holiday_total = public_holiday_hours × public_holiday_rate

    Gross composition:
        gross = (ordinary_hours × ordinary_rate)
              + (overtime_hours × overtime_rate)
              + (public_holiday_hours × public_holiday_rate)
              + sum(taxable_allowances)
              + casual_8pct (if employment_type='casual')
    """
```

### 4.2 `service.py` — generate / finalise / void / reopen-period

```python
async def generate_for_period(
    db, period_id, *, staff_ids: list | None = None,
) -> list[Payslip]:
    """Create one DRAFT payslip per active staff. Idempotent: re-running on
    existing drafts UPDATEs them.

    G4 — recurring allowance auto-attach:
        For each draft created, look up
            staff_recurring_allowances WHERE staff_id=:s AND active=true
        and insert a payslip_allowances row per match. Use the rule's
        override `amount`/`quantity` when set; else fall back to
        allowance_types.default_amount × unit-derived quantity per
        the G18 semantics in `_resolve_allowance_quantity` below.

    G2 — public_holiday_rate populated:
        On insert, set payslips.public_holiday_rate = ordinary_rate × 1.5.
        Admin can override on draft via PATCH; finalise re-reads the
        stored value (does NOT recompute from multiplier).

    G18 — quantity + unit on payslip_allowances:
        Every auto-attached row carries (quantity, unit, amount). The
        unit is COPIED from allowance_types at attach time so a future
        edit to allowance_types.unit doesn't retroactively change a
        finalised payslip's interpretation.
    """


async def _resolve_allowance_quantity(
    db, *, allowance_type, recurring_rule, staff, period,
) -> tuple[Decimal, Decimal]:
    """Returns (quantity, amount) per G18 unit semantics.

    unit='period' → quantity = 1; amount = override_amount or default_amount.
    unit='shift'  → quantity = count of approved shifts in period;
                    amount = quantity × (override_amount or default_amount).
    unit='km'     → quantity = recurring_rule.quantity (often 0 — admin
                    fills km on draft); amount = quantity × default_amount,
                    recomputed on every save when quantity edits.
    """
    unit = allowance_type.unit
    base = recurring_rule.amount if recurring_rule and recurring_rule.amount is not None else allowance_type.default_amount or Decimal(0)
    if unit == 'period':
        return Decimal(1), base
    if unit == 'shift':
        n_shifts = await _count_approved_shifts(db, staff.id, period)
        return Decimal(n_shifts), Decimal(n_shifts) * base
    if unit == 'km':
        q = recurring_rule.quantity if recurring_rule and recurring_rule.quantity is not None else Decimal(0)
        return q, q * base
    return Decimal(1), base


async def finalise_payslip(db, payslip_id, *, send_email: bool):
    """Re-compute totals (in case admin edited drafts), render PDF
    (asyncio.to_thread), upload, set pdf_upload_id, status='finalised',
    finalised_at=now()."""


async def void_payslip(db, payslip_id, reason):
    """Status='voided'; admin must generate compensating draft if the
    original was wrong. The parent pay_period must be 'open' for the new
    draft to attach — see reopen_pay_period (G21) below."""


async def email_payslip(db, payslip_id):
    """send_email with PDF attachment, dlq_task_name='payslip_email'."""


async def bulk_finalise_period(db, period_id, *, email_all: bool):
    """Iterates drafts, SAVEPOINT per payslip, dispatches background
    renders. Returns {finalised, failed, emailed}."""


# G21 — pay-period reopen flow.
async def reopen_pay_period(db, period_id, *, reopened_by, reason):
    """Reopen a finalised pay period for corrections.

    Refuses with 409 'period_already_paid' when status='paid' (money's
    out — too late). Refuses with 422 when already 'open'. Otherwise:

        UPDATE pay_periods SET status='open', finalised_at=NULL
        WHERE id=:id AND status='finalised';

    Existing finalised payslips inside this period STAY locked (still
    immutable per R3.4). The reopen only allows new compensating drafts
    or void+regen flows to proceed in the same period.

    Audit: pay_period.reopened with {reopened_by, reason, originally_finalised_at}.
    """
```

### 4.2.1 Pay-period rolling algorithm `app/modules/payslips/period_rolling.py` (G5 + G14)

```python
from datetime import date, timedelta
import calendar


WEEKLY_INTERVAL = timedelta(days=7)
FORTNIGHTLY_INTERVAL = timedelta(days=14)


def compute_next_period_dates(
    *,
    cadence: str,
    anchor_day: int,
    pay_date_offset_days: int,
    latest_end: date | None,
    today: date,
) -> tuple[date, date, date]:
    """Compute (start_date, end_date, pay_date) for the next pay period.

    G5 algorithm:
      weekly:      start = latest_end + 1 day
                          (or today's week's anchor_day if no history)
                   end   = start + 6 days
      fortnightly: start = latest_end + 1 day
                          (or today's week's anchor_day if no history)
                   end   = start + 13 days
      monthly:     start = anchor_day of next month (clamped to month length)
                   end   = day before next anchor

      pay_date = end + pay_date_offset_days, rolled forward to next
                 weekday if it lands on Sat/Sun.

    G14 — cadence change behaviour: when cadence flips, the next call
    uses `latest_end + 1` regardless of cadence — no retroactive merging.
    """
    if latest_end is not None:
        start = latest_end + timedelta(days=1)
    else:
        start = _anchor_start_for_cadence(cadence, anchor_day, today)

    if cadence == 'weekly':
        end = start + timedelta(days=6)
    elif cadence == 'fortnightly':
        end = start + timedelta(days=13)
    elif cadence == 'monthly':
        # If we already have history, start was set to latest_end+1.
        # For monthly we need to instead use anchor_day of the next month
        # — override `start` here.
        if latest_end is not None:
            next_month = _add_months(latest_end, 1)
            start = _clamp_to_month(date(next_month.year, next_month.month, anchor_day), next_month)
        next_anchor_month = _add_months(start, 1)
        next_anchor = _clamp_to_month(date(next_anchor_month.year, next_anchor_month.month, anchor_day), next_anchor_month)
        end = next_anchor - timedelta(days=1)
    else:
        raise ValueError(f"Unknown cadence: {cadence}")

    raw_pay = end + timedelta(days=pay_date_offset_days)
    pay_date = _next_business_day(raw_pay)
    return start, end, pay_date


def _anchor_start_for_cadence(cadence: str, anchor_day: int, today: date) -> date:
    """First-period anchor: weekly/fortnightly use anchor_day in the
    current week (1=Mon ... 7=Sun); monthly uses anchor_day in current month."""
    if cadence in ('weekly', 'fortnightly'):
        # ISO weekday: Mon=1 ... Sun=7
        weekday = today.isoweekday()
        delta = anchor_day - weekday
        return today + timedelta(days=delta)
    # monthly
    last_day = calendar.monthrange(today.year, today.month)[1]
    return date(today.year, today.month, min(anchor_day, last_day))


def _clamp_to_month(d: date, month_anchor: date) -> date:
    """Clamp day-of-month to the month's actual length (28/29/30/31)."""
    last_day = calendar.monthrange(month_anchor.year, month_anchor.month)[1]
    return d.replace(day=min(d.day, last_day))


def _add_months(d: date, n: int) -> date:
    m_total = d.month - 1 + n
    y = d.year + m_total // 12
    m = m_total % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def _next_business_day(d: date) -> date:
    """Roll forward Sat→Mon, Sun→Mon. Public holidays are NOT skipped
    here (would require app-side query against public_holidays table —
    deferred; admin can manually adjust pay_date if it lands on a PH)."""
    while d.isoweekday() > 5:
        d += timedelta(days=1)
    return d
```

The daily `roll_pay_periods` task:

```python
async def roll_pay_periods_task():
    """For each org with payroll module enabled, ensure the next 4
    pay-periods exist. Idempotent via UNIQUE (org_id, start_date)."""
    async for org in iter_payroll_orgs():
        latest = await db.scalar(
            select(func.max(PayPeriod.end_date))
            .where(PayPeriod.org_id == org.id)
        )
        for _ in range(4):
            start, end, pay = compute_next_period_dates(
                cadence=org.pay_period_cadence,
                anchor_day=org.pay_period_anchor_day,
                pay_date_offset_days=org.pay_date_offset_days,
                latest_end=latest,
                today=date.today(),
            )
            try:
                db.add(PayPeriod(
                    org_id=org.id, start_date=start, end_date=end,
                    pay_date=pay, status='open',
                ))
                await db.flush()
                latest = end
            except IntegrityError:
                # Already exists (UNIQUE constraint) — skip and recompute next
                await db.rollback()
                latest = end
```

### 4.3 Termination service `app/modules/payslips/termination.py`

```python
async def terminate_employment(
    db, staff_id, *, end_date, reason, final_pay_options,
):
    """Compute s27 payouts. Generate final payslip. Close balances. Audit.

    Operates as a single transaction. Steps in order:

    1. Reconcile future-dated approved leave (G16)
       - Find leave_requests WHERE staff_id=:id AND status='approved'
         AND start_date > :end_date.
       - For each: cancel the request, restore hours via leave_ledger
         row reason='request_cancelled_after_approval', cancel future
         schedule_entries.
       - Audit: staff.termination_cancelled_future_leave.

    2. Compute payouts on the now-corrected balances:
       - Annual: remaining accrued × greater_of(ordinary_weekly, 52wk_avg).
       - Alt-days: count × ADP snapshot (Phase 2 column refreshed by R13).
       - Casual 8% remainder: YTD_gross × 0.08 - sum(8% lines paid YTD).

    3. Pick the final-payslip pay_period (G25):
       - First match: pay_period whose [start, end] contains :end_date.
       - If status='open' → use it.
       - If status='finalised' → call reopen_pay_period (R1a) with
         reason='termination', audit pay_period.reopened_for_termination.
       - If status='paid' → 409 pay_period_already_paid.
       - If no match → call roll_pay_periods_for_org synchronously,
         iterating until a period covers :end_date. Audit
         pay_period.rolled_for_termination per created period.

    4. Generate the final payslip in the chosen period with the s27 +
       alt-day + casual-8% breakdown lines, notes='termination',
       status='draft' (admin still needs to enter final PAYE/ACC and
       finalise).

    5. Update staff:
       - employment_end_date = :end_date, is_active = false.
       - Flip leave balances to zero for accruing types (write
         leave_ledger rows reason='termination_payout').
       - Audit staff.terminated with redacted breakdown per G12 rules
         (counts only, no dollar amounts).
    """


def s27_annual_leave_payout(
    remaining_hours: Decimal,
    ordinary_weekly: Decimal,
    fifty_two_week_avg: Decimal,
    standard_hours_per_week: Decimal,
) -> Decimal:
    """Holidays Act s27. Returns dollars.

    Per-week-rate = greater_of(ordinary_weekly, fifty_two_week_avg).
    Hourly equivalent = per_week_rate / standard_hours_per_week.
    Total payout = hourly × remaining_hours.
    """
    per_week = max(ordinary_weekly, fifty_two_week_avg)
    if standard_hours_per_week and standard_hours_per_week > 0:
        hourly = per_week / standard_hours_per_week
    else:
        hourly = Decimal(0)
    return (hourly * remaining_hours).quantize(Decimal('0.01'))
```

### 4.4 PDF renderer `app/modules/payslips/pdf.py`

```python
async def render_pdf(payslip_id) -> bytes:
    html = render_template('payslips/payslip.html', payslip=...)
    pdf_bytes = await asyncio.to_thread(lambda: HTML(string=html).write_pdf())
    return pdf_bytes
```

Template includes every R7 field plus the bank-account-masked footer (G1) and the public-holiday band rate (G2). CSS print stylesheet at `app/templates/payslips/payslip.css` per the spec in §6.7 below.

### 4.5 Audit redaction (G12)

Payslip-event audit rows MUST NOT contain raw monetary amounts or decrypted PII. The service-layer write_audit_log call sites construct the redacted dict explicitly:

```python
# Right
await write_audit_log(
    session=db,
    action='payslip.finalised',
    entity_type='payslip',
    entity_id=payslip.id,
    org_id=payslip.org_id,
    user_id=current_user.id,
    after_value={
        'payslip_id': str(payslip.id),
        'staff_id': str(payslip.staff_id),
        'pay_period_id': str(payslip.pay_period_id),
        'finalised_at': payslip.finalised_at.isoformat(),
        'pdf_upload_id': str(payslip.pdf_upload_id) if payslip.pdf_upload_id else None,
    },
)

# Wrong (would leak gross/net to audit)
await write_audit_log(..., after_value=payslip.dict())
```

Per-event after_value shapes per R14 spec text:
- `payslip.generated` → `{ payslip_id, staff_id, pay_period_id, source }`
- `payslip.finalised` → `{ payslip_id, staff_id, pay_period_id, finalised_at, pdf_upload_id }`
- `payslip.emailed` → `{ payslip_id, staff_id, recipient_email_domain_only }` (split on `@` and keep tail only)
- `payslip.voided` → `{ payslip_id, staff_id, reason }`
- `staff.terminated` → counts only, no dollar amounts.

## 5. API endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v2/pay-periods` | GET, POST | List + create |
| `/api/v2/pay-periods/:id` | GET, PATCH | Detail + update (close) |
| `/api/v2/pay-periods/:id/payslips` | GET, POST | List per period; POST = generate drafts for all active staff |
| `/api/v2/pay-periods/:id/finalise` | POST | Bulk finalise + optional email |
| `/api/v2/pay-periods/:id/reopen` | POST | **G21**: reopen a finalised period for corrections (org_admin only). Refuses 409 when status='paid'. |
| `/api/v2/payslips/:id` | GET, PATCH | Detail + edit draft |
| `/api/v2/payslips/:id/finalise` | POST | Single finalise |
| `/api/v2/payslips/:id/email` | POST | Email |
| `/api/v2/payslips/:id/pdf` | GET | Download PDF |
| `/api/v2/payslips/:id/void` | POST | Void |
| `/api/v2/staff/:id/payslips` | GET | Per-staff history (Payslips tab — admin view; includes drafts/voided) |
| `/api/v2/staff/:id/payslips/recurring-allowances` | GET, POST | **G4**: list + add recurring allowance rules for a staff (admin only) |
| `/api/v2/staff/:id/payslips/recurring-allowances/:rule_id` | PATCH, DELETE | **G4**: update / deactivate a recurring rule |
| `/api/v2/staff/:id/terminate` | POST | Termination workflow |
| `/api/v2/staff/me/payslips` | GET | **G9**: own payslip list — finalised only, drafts/voided NOT visible to staff |
| `/api/v2/staff/me/payslips/:id` | GET | **G9**: own payslip detail (server-side ownership check; 404 not 403 if mismatch) |
| `/api/v2/staff/me/payslips/:id/pdf` | GET | **G9**: own PDF download |
| `/api/v2/allowance-types` | GET, POST | List + create |
| `/api/v2/allowance-types/:id` | PATCH, DELETE | Update + deactivate |
| `/api/v2/reports/wage-variance` | GET | Variance report |

All list responses `{ items, total }`.

The `/staff/me/*` endpoints (G9) are gated behind the `payroll` module — when disabled, return 404 `not_enabled` (matching the rest of P4's module-gate pattern). Server-side ownership is checked at every endpoint via `payslip.staff_id == staff_id_from_user(current_user.id)`; non-match returns 404 (not 403) to avoid leaking the existence of payslips that aren't yours. The IRD + bank decryption rule still applies — `pdf.render_pdf` is the only path that touches encrypted fields, even on the self-service surface.

## 6. Frontend Component Tree

### 6.1 `PayRunPage.tsx`

Bulk pay-run console:
- Pay period selector (auto-selects current open).
- Generate drafts button (creates one per active staff).
- Table of staff × draft payslip with inline totals.
- Click row → `PayslipDetail` drawer.
- "Finalise all" button → bulk-finalise with email-all checkbox.
- Live progress bar during bulk finalise (long polling or SSE).

### 6.2 `PayslipDetail.tsx`

Draft editor:
- Header: staff name + period dates + status chip.
- Hours section (read-only, sourced from approved timesheet): ordinary, overtime, public_holiday.
- Allowances: editable list, "Add allowance" → picks allowance_type + amount.
- Reimbursements: editable list.
- Deductions: PAYE numeric input (admin enters from IRD), ACC numeric, KiwiSaver auto-shown read-only, student_loan visible if `staff.student_loan=true`, child_support, voluntary.
- Leave taken section (read-only).
- Live computed: gross, net, kiwisaver_employer (informational).
- Save (draft only), Finalise, Send (post-finalise), Download PDF, Void.

### 6.3 `PayslipsTab.tsx` (Staff Detail)

List of past payslips with PDF download + Email button + Void (admin) + status chip.

### 6.4 `TerminationModal.tsx`

Form:
- end_date (date picker)
- reason (text)
- preview of computed payouts (annual-leave 52-week avg vs ordinary, alt-days, casual 8% remainder).
- Confirm → POST `/staff/:id/terminate`.

### 6.5 Settings: `PayPeriodsPage.tsx` + `AllowanceTypesPage.tsx`

CRUD UIs, sortable, edit-in-place. **G21 — `PayPeriodsPage` shows a "Reopen" button next to finalised periods**; click opens a confirmation modal that requires a `reason` text and warns that any new corrections will sit alongside the existing locked finalised payslips. Periods with status='paid' have the Reopen button disabled with tooltip "Already paid — contact support".

### 6.6 `WageVariancePage.tsx` (Reports)

Table: staff, this-period gross, last-period gross, delta, % change. Filter by % threshold.

### 6.7 Recurring Allowances panel on Staff Detail Overview tab (G4)

Lives under a collapsible "Recurring allowances" section on the Phase 1 Overview tab. Phase 4 ships this surface; Phase 1 reserved the slot.

```tsx
function RecurringAllowancesPanel({ staffId }: { staffId: string }) {
  const { allowances, refresh } = useRecurringAllowances(staffId)
  const [adding, setAdding] = useState(false)
  return (
    <CollapsibleSection title="Recurring allowances">
      <Table>
        {(allowances ?? []).map(a => (
          <Row key={a.id}>
            <td>{a.allowance_type?.name}</td>
            <td>${a.amount ?? a.allowance_type?.default_amount}</td>
            <td>{a.allowance_type?.unit}</td>
            <td><Toggle on={a.active} onChange={v => toggleActive(a.id, v)} /></td>
            <td><button onClick={() => deleteRule(a.id, refresh)}>Remove</button></td>
          </Row>
        ))}
      </Table>
      <button onClick={() => setAdding(true)}>+ Add recurring allowance</button>
      {adding && <AddRecurringAllowanceModal staffId={staffId} onClose={() => { setAdding(false); refresh() }} />}
    </CollapsibleSection>
  )
}
```

### 6.8 Staff self-service Payslips (G9)

**Web** — new route `/staff/me/payslips`:

```tsx
export default function MyPayslipsPage() {
  const { items, total, isLoading } = useMyPayslips()  // GET /staff/me/payslips
  const [openId, setOpenId] = useState<string | null>(null)
  return (
    <ModuleGate moduleSlug="payroll">
      <Page title="My payslips">
        {isLoading && <Spinner />}
        <Table>
          {(items ?? []).map(p => (
            <Row key={p.id} onClick={() => setOpenId(p.id)}>
              <td>{formatPeriod(p.pay_period)}</td>
              <td>{p.gross_pay}</td>
              <td>{p.net_pay}</td>
              <td><a href={`/api/v2/staff/me/payslips/${p.id}/pdf`} target="_blank">PDF</a></td>
            </Row>
          ))}
        </Table>
        {openId && <MyPayslipDrawer payslipId={openId} onClose={() => setOpenId(null)} />}
      </Page>
    </ModuleGate>
  )
}
```

**Mobile** — `mobile/src/screens/payslips/PayslipsScreen.tsx`, lazy-loaded in `StackRoutes.tsx`, behind `ModuleGate moduleSlug="payroll"`. Renders a `<MobileList>` of past payslips with a download button per row that uses Capacitor's share sheet on native (downloads + opens system share when `isNativePlatform()` returns true).

### 6.9 Print CSS spec (G20)

`app/templates/payslips/payslip.css` MUST specify:

```css
@page {
  size: A4 portrait;
  margin: 15mm 12mm;

  @top-center {
    content: element(payslipHeader);  /* org logo + name */
  }
  @bottom-center {
    content: "Page " counter(page) " of " counter(pages) " · Generated by OraInvoice";
    font-size: 8pt;
    color: #666;
  }
}

body {
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  font-size: 10pt;
  color: #111;
  background: #fff;
}

h1 { font-size: 14pt; font-weight: 700; }
h2 { font-size: 12pt; font-weight: 600; margin-top: 8mm; }

table {
  width: 100%;
  border-collapse: collapse;
  page-break-inside: avoid;       /* keep each line-item table on one page */
}

td.numeric, th.numeric { text-align: right; font-variant-numeric: tabular-nums; }

.payslip-header {
  position: running(payslipHeader);
  display: flex;
  align-items: center;
  gap: 5mm;
}

.section { page-break-inside: avoid; margin-bottom: 6mm; }

/* High-contrast — no background fills that increase ink usage. */
tr.row-alt { background: #f8f8f8; }   /* still printable if using draft mode */
```

The Jinja template at `app/templates/payslips/payslip.html` references this stylesheet via `<link rel="stylesheet" href="{{ static('payslips/payslip.css') }}">` rendered server-side before passing to WeasyPrint.

## 7. User Workflow Traces

### 7.1 Generate + finalise + email a pay run

```
Admin opens /payroll
→ Sees "Pay period 1-7 June (open)" → clicks Generate drafts
→ POST /pay-periods/:id/payslips → creates 9 drafts
→ Table populates with one row per staff
→ Admin opens Jane's draft → adds $50 meal allowance, enters PAYE=$210, saves
→ Admin clicks "Finalise all" with email_all=true
→ POST /pay-periods/:id/finalise?email_all=true
   - For each: compute → render PDF → upload → set finalised → email
   - Each per-payslip wrapped in SAVEPOINT
→ Returns {finalised:9, failed:[], emailed:9}
→ Toast "Pay run finalised. 9 payslips emailed."
```

### 7.2 Termination

```
Admin opens Jane's Overview tab → "End employment"
→ TerminationModal: end_date=2026-06-30, reason="Resigning"
→ Modal preview shows:
   - 80h annual leave remaining × greater(weekly: $1000, 52-wk: $1080) = $86.40/h × 80h = $6912 (illustrative)
   - 2 alt-days × $200 RDP = $400
   - Casual: N/A (permanent)
→ Confirm → POST /staff/:id/terminate
   - sets is_active=false, employment_end_date
   - writes leave_ledger reasons termination_payout
   - generates final payslip in next open pay_period with the breakdown
   - audit_logs staff.terminated
→ Toast "Final payslip queued in pay period 8-14 June"
```

### 7.3 Casual employee payslip

```
Generate for casual Bob:
→ ordinary 30h × $24 = $720
→ allowance auto-attached: casual_8pct_holiday = $720 × 0.08 = $57.60 taxable
→ gross = $777.60
→ KiwiSaver employee 3% = $23.33; employer 3% = $23.33 (informational)
→ admin enters PAYE = $98, ACC = $11
→ net = 777.60 - 98 - 11 - 23.33 = $645.27
```

## 8. Modal Inventory

| Element | Trigger | Contains |
|---|---|---|
| GenerateDraftsConfirm | Generate button on PayRun | "Will create N drafts?" |
| BulkFinaliseConfirm | Finalise all | Counts + email checkbox |
| VoidPayslipModal | Void | Reason text |
| TerminationModal | "End employment" | end_date, reason, payout preview |
| AddAllowanceModal | Add allowance on draft | type select, amount |
| AddDeductionModal | Add voluntary deduction | label, amount |
| ConfirmFinaliseSingle | Finalise one | "PDF will be rendered + locked" |

## 9. Performance

- PDF rendering wrapped in `asyncio.to_thread` — won't block event loop.
- Bulk pay-run dispatches per-payslip as background tasks via existing dispatch path.
- `gross_ytd` cached on the row (avoids re-summing across 26 fortnightly payslips).
- Indexes ensure per-staff history is single-page lookup.

### 9.1 SLOs (G24)

| API | Target | Notes |
|---|---|---|
| `POST /api/v2/pay-periods/:id/payslips/generate` (single-org draft generation, 50 staff) | **<3s p99** | Reads timesheet_approvals + leave_requests + recurring_allowances; SAVEPOINT-per-staff; minimal computation. |
| `POST /api/v2/pay-periods/:id/finalise` (bulk, 50 staff) | **<5s p99 to return**; `pdf_upload_id` populated within 60s p99 per payslip | The endpoint returns once payslips are status='finalised'. PDF render runs as a background task; `pdf_upload_id` patched in async. Bulk-email dispatch is async via `send_email`'s DLQ; emails follow PDF availability. |
| `POST /api/v2/payslips/:id/finalise` (single) | **<2s p99** | PDF render in `asyncio.to_thread`; upload + email queued. |
| `GET /api/v2/payslips/:id/pdf` (download) | **<500ms p99** | Reads pre-rendered PDF from uploads volume; no rendering on this path. |
| `GET /api/v2/staff/me/payslips` (G9 self-service list) | **<300ms p99** | Single indexed query (`idx_payslips_staff_status_finalised_desc`); paginated 20/page. |
| `roll_pay_periods` daily task | **<60s** for an org with 4 periods to compute | Pure Python `compute_next_period_dates` + 4 INSERTs per org; idempotent via UNIQUE (org_id, start_date). |
| `terminate_employment` (single staff) | **<3s p99** | Includes future-leave reconciliation, payout calc, period selection (with possible reopen), final draft creation, balance close. |

## 10. Security / PII

- IRD + bank account decryption ONLY happens inside `pdf.render_pdf` and `termination.terminate_employment` calls.
- Returned payslip API responses keep IRD masked + bank masked.
- Finalised payslips are immutable: PUT/DELETE on `payslips WHERE status='finalised'` returns 409.

## 11. Verified-against-code addendum

- ✅ WeasyPrint pattern from `app/modules/invoices/service.py:4446` — Phase 4 reuses the same `await asyncio.to_thread(lambda: HTML(string=html).write_pdf())` shape.
- ✅ `app/modules/uploads/` is the storage path. PDFs stored under category `payslips/` per the existing `_store(category=...)` helper.
- ✅ `send_email` with `dlq_task_name` from quick win #10.
- ✅ Phase 2's `leave_balances` and `leave_ledger` provide the s130A "leave taken + remaining balance" data.
- ✅ Phase 3's `timesheet_approvals` provides the source-of-truth hours; `time_clock_entries` linked via `scheduled_entry_id` for shift-count derivation (G18 unit='shift').
- ✅ Phase 1's `staff_pay_rates` history table is read for "ordinary_weekly" baseline in s27 calc.
- ⚠️ Existing `app/modules/payments/` is unrelated — it handles invoice payments, not staff wages. Phase 4 lives in a brand-new `app/modules/payslips/`.

## 12. Spec completeness self-check

All 8 sections covered: navigation §2, component tree §6 (incl. G4 recurring panel + G9 self-service screens), workflow §7, modals §8, toolbar §6.1 PayRun, list/table §6.1, error UI (409 finalised + 422 missing email + 409 period_already_paid + 404 payslip-not-yours), integration points §11. SLOs §9.1 (G24).

## 13. Gap-analysis closure addendum

Real gaps from the user's audit, all closed in this revision:

- ✅ **G1** — PDF includes masked bank account (R7.2 + §4.4 PDF template).
- ✅ **G2** — `public_holiday_rate` column on payslips; defaulted to ordinary × 1.5; admin overridable; PDF row renders the rate (R3.1 + R4a + §4.1 PUBLIC_HOLIDAY_DEFAULT_MULTIPLIER).
- ✅ **G4** — `staff_recurring_allowances` table + auto-attach in generate_for_period; admin UI on Phase 1 Overview tab (R3.5 + §6.7 + new endpoints in §5).
- ✅ **G5** — `compute_next_period_dates` algorithm with concrete weekly/fortnightly/monthly rules (R1.5 + §4.2.1).
- ✅ **G6** — Termination synchronously rolls periods if no period covers `:end_date` (R10 step 3 + §4.3).
- ✅ **G9** — Three new `/staff/me/payslips/*` endpoints with ownership check + payroll module gate; web + mobile self-service screens (R8a + §5 + §6.8).
- ✅ **G12** — Audit redaction rules in R14 + §4.5 spell out the per-event after_value shapes.
- ✅ **G14** — Cadence change behaviour documented in R1.6 + §4.2.1 docstring.
- ✅ **G16** — Termination reconciles future-dated approved leave first (R10 step 1 + §4.3 docstring).
- ✅ **G18** — Allowance unit semantics with quantity column on payslip_allowances; auto-quantity derivation (R4.6 + §4.2 `_resolve_allowance_quantity`).
- ✅ **G20** — Print-CSS basics enumerated (R7.5 + §6.9 full stylesheet sketch).
- ✅ **G21** — Pay-period reopen flow (R1a + §4.2 `reopen_pay_period`).
- ✅ **G24** — Bulk-finalise SLOs (§9.1 table).
- ✅ **G25** — Final-payslip pay-period selection logic (R10 step 3 + §4.3 docstring).

Back-port candidates (D1–D4) were already addressed in the master plan in earlier revisions.
