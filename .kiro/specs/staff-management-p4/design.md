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
    amount numeric(12,2) NOT NULL,
    taxable boolean NOT NULL DEFAULT true
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
    ADD COLUMN IF NOT EXISTS pay_period_anchor_day int NOT NULL DEFAULT 1;
ALTER TABLE organisations DROP CONSTRAINT IF EXISTS ck_org_pay_period_cadence;
ALTER TABLE organisations ADD CONSTRAINT ck_org_pay_period_cadence
    CHECK (pay_period_cadence IN ('weekly','fortnightly','monthly'));
```

All RLS-enabled with tenant_isolation policy. Allowance defaults seeded for every existing org.

### 3.2 Indexes (`0210_payslip_indexes.py`) — CONCURRENTLY

- `idx_payslips_org_period_status ON payslips (org_id, pay_period_id, status)`
- `idx_payslips_staff_period ON payslips (staff_id, pay_period_id DESC)`
- `idx_pay_periods_org_status ON pay_periods (org_id, status, start_date DESC)`
- `idx_payslip_allowances_payslip ON payslip_allowances (payslip_id)`
- `idx_payslip_deductions_payslip ON payslip_deductions (payslip_id)`
- `idx_payslip_leave_lines_payslip ON payslip_leave_lines (payslip_id)`

## 4. Service layer

### 4.1 `calc.py` — wage math

```python
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
    KiwiSaver auto from rate columns."""
```

### 4.2 `service.py` — generate / finalise / void

```python
async def generate_for_period(db, period_id, *, staff_ids: list | None = None) -> list[Payslip]:
    """Create one DRAFT payslip per active staff. Idempotent: re-running on existing drafts UPDATEs them."""

async def finalise_payslip(db, payslip_id, *, send_email: bool):
    """Re-compute totals (in case admin edited drafts), render PDF (asyncio.to_thread),
    upload, set pdf_upload_id, status='finalised', finalised_at=now()."""

async def void_payslip(db, payslip_id, reason):
    """Status='voided'; admin must generate compensating draft if the original was wrong."""

async def email_payslip(db, payslip_id):
    """send_email with PDF attachment, dlq_task_name='payslip_email'."""

async def bulk_finalise_period(db, period_id, *, email_all: bool):
    """Iterates drafts, SAVEPOINT per payslip, dispatches background renders."""
```

### 4.3 Termination service `app/modules/payslips/termination.py`

```python
async def terminate_employment(db, staff_id, *, end_date, reason, final_pay_options):
    """Compute s27 payouts. Generate final payslip. Close balances. Audit."""

def s27_annual_leave_payout(remaining_hours, ordinary_weekly, fifty_two_week_avg) -> Decimal:
    """greater_of(ordinary_weekly, fifty_two_week_avg) per week × (remaining/std_hours)."""
```

### 4.4 PDF renderer `app/modules/payslips/pdf.py`

```python
async def render_pdf(payslip_id) -> bytes:
    html = render_template('payslips/payslip.html', payslip=...)
    pdf_bytes = await asyncio.to_thread(lambda: HTML(string=html).write_pdf())
    return pdf_bytes
```

Template includes every R7 field. CSS print stylesheet at `app/templates/payslips/payslip.css`.

## 5. API endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v2/pay-periods` | GET, POST | List + create |
| `/api/v2/pay-periods/:id` | GET, PATCH | Detail + update (close) |
| `/api/v2/pay-periods/:id/payslips` | GET, POST | List per period; POST = generate drafts for all active staff |
| `/api/v2/pay-periods/:id/finalise` | POST | Bulk finalise + optional email |
| `/api/v2/payslips/:id` | GET, PATCH | Detail + edit draft |
| `/api/v2/payslips/:id/finalise` | POST | Single finalise |
| `/api/v2/payslips/:id/email` | POST | Email |
| `/api/v2/payslips/:id/pdf` | GET | Download PDF |
| `/api/v2/payslips/:id/void` | POST | Void |
| `/api/v2/staff/:id/payslips` | GET | Per-staff history (Payslips tab) |
| `/api/v2/staff/:id/terminate` | POST | Termination workflow |
| `/api/v2/allowance-types` | GET, POST | List + create |
| `/api/v2/allowance-types/:id` | PATCH, DELETE | Update + deactivate |
| `/api/v2/reports/wage-variance` | GET | Variance report |

All list responses `{ items, total }`.

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

CRUD UIs, sortable, edit-in-place.

### 6.6 `WageVariancePage.tsx` (Reports)

Table: staff, this-period gross, last-period gross, delta, % change. Filter by % threshold.

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

## 10. Security / PII

- IRD + bank account decryption ONLY happens inside `pdf.render_pdf` and `termination.terminate_employment` calls.
- Returned payslip API responses keep IRD masked + bank masked.
- Finalised payslips are immutable: PUT/DELETE on `payslips WHERE status='finalised'` returns 409.

## 11. Verified-against-code addendum

- ✅ WeasyPrint pattern from `app/modules/invoices/service.py:4446` — Phase 4 reuses the same `await asyncio.to_thread(lambda: HTML(string=html).write_pdf())` shape.
- ✅ `app/modules/uploads/` is the storage path.
- ✅ `send_email` with `dlq_task_name` from quick win #10.
- ✅ Phase 2's `leave_balances` and `leave_ledger` provide the s130A "leave taken + remaining balance" data.
- ✅ Phase 3's `timesheet_approvals` provides the source-of-truth hours.
- ⚠️ Existing `app/modules/payments/` is unrelated — it handles invoice payments, not staff wages. Phase 4 lives in a brand-new `app/modules/payslips/`.

## 12. Spec completeness self-check

All 8 sections covered: navigation §2, component tree §6, workflow §7, modals §8, toolbar §6.1 PayRun, list/table §6.1, error UI (409 finalised + 422 missing email), integration points §11.
