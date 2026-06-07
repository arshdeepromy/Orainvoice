/**
 * StaffKpiStrip — the row of four summary cards at the top of the Staff list
 * (R1: Total staff, Employees, With login access, Avg hourly rate).
 *
 * Sourcing (per design.md):
 *   - "Total staff"        ← the list payload `total` (passed as a prop, so it
 *                            reflects the same count the page already shows).
 *   - "Employees"          ← `getStaffListKpis().employee_count`.
 *   - "With login access"  ← `getStaffListKpis().with_login_count`.
 *   - "Avg hourly rate"    ← `getStaffListKpis().avg_hourly_rate`, currency-
 *                            formatted; `null` renders as "—".
 *
 * Any unavailable value renders "—" rather than a misleading 0 (R1.7). The
 * org-wide KPIs are fetched once on mount via an AbortController-guarded
 * effect (R14.1). Presentation mirrors the design-system `.kpi` card used on
 * the Reports landing (`rounded-card border border-border bg-card shadow-card`,
 * muted label, mono value) and relies on the same CSS tokens for dark mode as
 * the rest of `StaffList.tsx`.
 *
 * _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 14.1_
 */

import { useEffect, useState } from 'react'
import { getStaffListKpis, type StaffListKpis } from '@/api/staff'

const PLACEHOLDER = '—'

const NZD = new Intl.NumberFormat('en-NZ', {
  style: 'currency',
  currency: 'NZD',
})

interface StaffKpiStripProps {
  /** Total staff count from the list payload (`total`). */
  totalStaff: number
}

interface KpiCardProps {
  label: string
  /** Pre-formatted display value, or "—" when unavailable. */
  value: string
}

/** Single KPI tile — mirrors the prototype `.kpi` (muted label, mono value). */
function KpiCard({ label, value }: KpiCardProps) {
  return (
    <div className="rounded-card border border-border bg-card p-5 shadow-card">
      <div className="mb-3.5 text-[12.5px] font-medium text-muted-2">{label}</div>
      <div className="mono text-[27px] font-semibold leading-none tracking-[-0.02em] text-text">
        {value}
      </div>
    </div>
  )
}

export default function StaffKpiStrip({ totalStaff }: StaffKpiStripProps) {
  const [kpis, setKpis] = useState<StaffListKpis | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getStaffListKpis(controller.signal)
      .then((data) => setKpis(data))
      .catch(() => {
        /* leave kpis null → cards render "—" (R1.7) */
      })
    return () => controller.abort()
  }, [])

  // Total staff comes from the list payload; the rest come from the KPIs
  // endpoint. Each value falls back to "—" when unavailable (R1.7).
  const totalValue =
    Number.isFinite(totalStaff) ? String(totalStaff) : PLACEHOLDER
  const employeesValue =
    kpis != null ? String(kpis.employee_count) : PLACEHOLDER
  const withLoginValue =
    kpis != null ? String(kpis.with_login_count) : PLACEHOLDER
  const avgRateValue =
    kpis?.avg_hourly_rate != null ? NZD.format(kpis.avg_hourly_rate) : PLACEHOLDER

  return (
    <div className="mb-[22px] grid grid-cols-4 gap-gap max-[1080px]:grid-cols-2 max-[520px]:grid-cols-1">
      <KpiCard label="Total staff" value={totalValue} />
      <KpiCard label="Employees" value={employeesValue} />
      <KpiCard label="With login access" value={withLoginValue} />
      <KpiCard label="Avg hourly rate" value={avgRateValue} />
    </div>
  )
}
