# Staff Management Phase 5 — Design

## 1. Architecture overview

Phase 5 is read-heavy + export-heavy. New module `app/modules/payroll_reports/` contains reports + bank-file generators. Dashboard widgets extend `app/modules/organisations/dashboard_service.py` (the existing widget framework).

Backend touches:
- `app/modules/payroll_reports/{models,schemas,service,router,bank_files,ird_export}.py`
- `app/modules/organisations/dashboard_service.py` — add `get_labour_cost_vs_revenue` + `get_wage_forecast` per `dashboard-widget-gating.md` 10-step process.
- `app/modules/organisations/schemas.py` — extend `DashboardWidgetsResponse`.
- `app/main.py` — include router.
- No new tables in this phase. (Bank-file export streams from existing payslip data.)

Frontend touches:
- `frontend/src/pages/reports/AttendancePatternsPage.tsx`
- `frontend/src/pages/reports/LeaveProjectionPage.tsx`
- `frontend/src/pages/reports/StaffCalendarPage.tsx`
- `frontend/src/pages/reports/BankFileExportPage.tsx`
- `frontend/src/pages/reports/IRDExportPage.tsx`
- `frontend/src/pages/dashboard/widgets/LabourCostVsRevenueWidget.tsx`
- `frontend/src/pages/dashboard/widgets/WageForecastWidget.tsx`
- `frontend/src/hooks/useDashboardWidgets.ts` — extend.

## 2. Navigation

- Sidebar: "Reports" already exists; new sub-items: Attendance Patterns, Leave Projection, Staff Calendar, Bank File Export, IRD Export.
- Dashboard widgets auto-appear when their respective module is enabled and the user hasn't reordered them lower. **Per-widget module gating (P5-N7):**
  - `labour-cost-vs-revenue` → gated by `payroll` (reads `payslips.gross_pay`; useless without P4 shipped).
  - `wage-forecast` → gated by `staff_management` (reads schedule + staff + leave + overtime; works even without P4 shipped).
- **Trade-family gating (P5-N1 + P5-N8):** the `WidgetGrid` itself is currently rendered ONLY for automotive-transport orgs (verified at `OrgAdminDashboard.tsx:346`). Payroll widgets apply to all 16 trade families — STAFF-011 must be resolved before widget work begins. Recommended path: drop the trade-family gate so the per-module gates above are the source of truth.
- Bank/IRD export gated by `payroll` (reads `payslips`).

## 3. Service layer

### 3.1 Dashboard widgets

Per `dashboard-widget-gating.md`:

```python
async def get_labour_cost_vs_revenue(db, org_id, branch_id) -> WidgetDataSection:
    """P5-N2: queries `invoices.total` (the actual column name; NOT `total_amount`).
    Verified at `app/modules/invoices/models.py:184`. Status filter matches the
    `ck_invoices_status` CHECK constraint enum at line 238."""
    try:
        sp = await db.begin_nested()
        try:
            # 7d, 30d, YTD windows
            results = []
            for label, since in [('7d', d7), ('30d', d30), ('YTD', dytd)]:
                labour = await db.scalar(sa_text("""
                    SELECT COALESCE(SUM(gross_pay),0) FROM payslips
                    WHERE org_id=:org AND status='finalised' AND finalised_at >= :since
                """), {'org': org_id, 'since': since}) or Decimal(0)
                revenue = await db.scalar(sa_text("""
                    SELECT COALESCE(SUM(total),0) FROM invoices
                    WHERE org_id=:org AND status IN ('issued','partially_paid','paid')
                          AND created_at >= :since
                """), {'org': org_id, 'since': since}) or Decimal(0)
                pct = (labour / revenue * 100) if revenue else None
                results.append({'period': label, 'labour': labour, 'revenue': revenue, 'pct': pct})
            return {'items': results, 'total': len(results)}
        except Exception:
            await sp.rollback()
            return _empty_section()
    except Exception:
        logger.exception('get_labour_cost_vs_revenue failed')
        return _empty_section()
```

Same SAVEPOINT-protected pattern for `get_wage_forecast`. **P5-N3:** the wage-forecast query filters `schedule_entries.status IN ('scheduled', 'completed')` — the actual `ENTRY_STATUSES` enum (verified at `app/modules/scheduling_v2/models.py:21`). The earlier draft said "published `schedule_entries`" — that status value does not exist.

### 3.2 Bank-file generators

```python
class BankFileFormat(str, Enum):
    BNZ_MULTIPAY = 'bnz_multipay'
    ANZ_DIRECT_CREDIT = 'anz_direct_credit'
    ASB = 'asb'
    WESTPAC = 'westpac'
    KIWIBANK = 'kiwibank'

async def generate_bank_file(db, pay_period_id, fmt: BankFileFormat) -> AsyncIterator[bytes]:
    """Streams CSV bytes. Decrypts bank account inside the generator."""
    payslips = await load_finalised_payslips(db, pay_period_id)
    yield format_header(fmt).encode()
    for slip in payslips:
        staff = await load_staff(db, slip.staff_id)
        bank_acct = envelope_decrypt_str(staff.bank_account_number_encrypted)
        yield format_row(fmt, slip, staff, bank_acct).encode() + b'\n'
    yield format_footer(fmt).encode()
```

Each `format_row` is bank-specific. Phase 5 ships BNZ Multi-Pay first (per STAFF-004); others as add-on functions.

### 3.3 IRD export

```python
async def generate_ird_export(db, pay_period_id) -> AsyncIterator[bytes]:
    """CSV: employee_name, ird, gross, paye, kiwisaver_employee, kiwisaver_employer, esct."""
    yield b'employee_name,ird_number,gross,paye,ks_employee,ks_employer,esct\n'
    for slip in await load_finalised_payslips(db, pay_period_id):
        staff = await load_staff(db, slip.staff_id)
        ird = envelope_decrypt_str(staff.ird_number_encrypted)
        paye = sum(d.amount for d in slip.deductions if d.kind == 'paye')
        ks_e = sum(d.amount for d in slip.deductions if d.kind == 'kiwisaver_employee')
        ks_er = sum(d.amount for d in slip.deductions if d.kind == 'kiwisaver_employer')
        yield csv_row(staff.name, ird, slip.gross_pay, paye, ks_e, ks_er, '').encode() + b'\n'
```

## 4. API endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v2/reports/attendance-patterns` | GET | Per-staff attendance metrics |
| `/api/v2/reports/leave-projection` | GET | Upcoming approved leave |
| `/api/v2/reports/staff-calendar` | GET | Anniversary/probation/visa events |
| `/api/v2/reports/bank-file` | GET | Streamed CSV |
| `/api/v2/reports/ird-export` | GET | Streamed CSV (org_admin only) |

## 5. Frontend Component Tree

### 5.1 `LabourCostVsRevenueWidget.tsx`

P5-N4: `WidgetCard` (verified at `frontend/src/pages/dashboard/widgets/WidgetCard.tsx:14-21`) accepts `title, icon, actionLink, children, isLoading, error` only. There is **no `empty` or `emptyText` prop**. The empty state pattern is to render the empty message inside `children` conditionally — matches all 9 existing widgets (e.g., `RecentCustomersWidget.tsx`, `PublicHolidaysWidget.tsx`).

```tsx
import { WidgetCard } from './WidgetCard'
import type { LabourCostItem, WidgetDataSection } from './types'

// Inline SVG icon following existing widget convention (no heroicons dep).
function BanknotesIcon({ className }: { className?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"
         strokeWidth={1.5} stroke="currentColor" className={className}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M2.25 18.75a60.07 60.07 0 0 1 15.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 0 1 3 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 0 0-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 0 1-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 0 0 3 15h-.75M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm3 0h.008v.008H18V10.5Zm-12 0h.008v.008H6V10.5Z" />
    </svg>
  )
}

interface Props {
  data: WidgetDataSection<LabourCostItem> | undefined | null
  isLoading: boolean
  error: string | null
}

export function LabourCostVsRevenueWidget({ data, isLoading, error }: Props) {
  const items = data?.items ?? []
  return (
    <WidgetCard title="Labour cost vs revenue" icon={BanknotesIcon} isLoading={isLoading} error={error}>
      {items.length === 0 ? (
        <p className="text-sm text-gray-500">No staff payslips yet — generate your first pay run.</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {items.map(it => (
            <li key={it?.period ?? Math.random()} className="flex items-center justify-between py-2 text-sm">
              <span className="font-medium">{it?.period ?? '-'}</span>
              <span className="text-gray-700">${(it?.labour ?? 0).toLocaleString()}</span>
              <span className="text-gray-500">${(it?.revenue ?? 0).toLocaleString()}</span>
              <span className="font-mono">{it?.pct != null ? `${it.pct.toFixed(1)}%` : '-'}</span>
            </li>
          ))}
        </ul>
      )}
    </WidgetCard>
  )
}
```

Mandatory patterns (per `safe-api-consumption.md` + `dashboard-widget-gating.md`):
- All API data accesses guarded with `?.` and `?? []` / `?? 0`.
- Empty-state message inside `children` (not a `WidgetCard` prop).
- Inline SVG icon (no heroicons dependency).
- `data` typed as `WidgetDataSection<LabourCostItem> | undefined | null`.

### 5.2 Reports pages

Each page is a sortable table + filter chips + Export-CSV button. `BankFileExportPage` adds a format-picker dropdown. `IRDExportPage` is org_admin only (route guard).

## 6. User Workflow Traces

### 6.1 Bank-file export

```
Admin opens /reports/bank-file
→ Picks pay period 1-7 June, format=BNZ Multi-Pay
→ Click Export
→ GET /api/v2/reports/bank-file?pay_period_id=...&format=bnz_multipay
→ Server streams CSV
→ Browser downloads "bnz-multipay-2026-06-07.csv"
→ Audit row written
```

## 7. Modal Inventory

| Element | Trigger | Contains |
|---|---|---|
| BankFileFormatHelpModal | Help icon | Per-format docs link to bank's spec |
| ExportConfirmModal | Click Export | "This decrypts staff bank accounts. Continue?" |

## 8. Performance

- Streaming CSVs handle pay periods of any size without OOM.
- Dashboard widgets cached at page level (existing Redis cache for the dashboard endpoint).
- All reports paginate where the data set could exceed 1000 rows.

## 9. Verified-against-code addendum

- ✅ Existing `dashboard_service.py::get_public_holidays` and `get_recent_customers` follow the SAVEPOINT-per-widget pattern. New widgets mirror it.
- ✅ Existing `WidgetCard` + `useDashboardWidgets` hook pattern.
- ✅ Existing `app/core/encryption.py::envelope_decrypt_str` decrypts the bytea fields.
- ✅ FastAPI streaming response pattern available via `fastapi.responses.StreamingResponse`.
- ✅ **Decryption authorisation (cross-phase X6).** P5's bank-files and ird-export modules are listed in P4 design §10's authorised-decryption-paths registry. The four authorised paths are: P4 `pdf.render_pdf`, P4 `termination.terminate_employment`, P5 `bank_files.generate_bank_file`, P5 `ird_export.generate_ird_export`. The lint test in P4 §10 will accept `envelope_decrypt_str` calls in P5's two modules.

## 10. Spec completeness self-check

All 8 sections covered.
