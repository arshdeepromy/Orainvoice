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
- Dashboard widgets auto-appear when `staff_management` module enabled and the user hasn't reordered them lower.
- All widgets module-gated by `staff_management`; bank/IRD export gated by `payroll`.

## 3. Service layer

### 3.1 Dashboard widgets

Per `dashboard-widget-gating.md`:

```python
async def get_labour_cost_vs_revenue(db, org_id, branch_id) -> WidgetDataSection:
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
                    SELECT COALESCE(SUM(total_amount),0) FROM invoices
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

Same SAVEPOINT-protected pattern for `get_wage_forecast`.

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

```tsx
export default function LabourCostVsRevenueWidget() {
  const data = useDashboardWidgets()?.labour_cost_vs_revenue
  return (
    <WidgetCard title="Labour cost vs revenue" empty={!data?.items?.length} emptyText="No staff payslips yet — generate your first pay run">
      {data?.items?.map(it => (
        <Row key={it.period}>
          <Period>{it.period}</Period>
          <Cost>${it.labour}</Cost>
          <Rev>${it.revenue}</Rev>
          <Pct>{it.pct ? `${it.pct.toFixed(1)}%` : '-'}</Pct>
        </Row>
      ))}
    </WidgetCard>
  )
}
```

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

## 10. Spec completeness self-check

All 8 sections covered.
