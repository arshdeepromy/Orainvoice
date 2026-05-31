/**
 * ComplianceBanner
 *
 * Renders 7 clickable counters that toggle URL filter chips per Staff
 * Management Phase 1 design §6.5. When `compliance_summary.missing_start_date`
 * is non-zero, an additional non-dismissible banner is rendered above the
 * counter row warning admins about Phase 2 leave accrual gaps.
 *
 * Also exports a `StaffRowDots` helper that renders a chip-cluster of dots
 * for staff rows missing key compliance fields (employee_id, employment_start_date,
 * or below-min-wage). The helper hover-tooltip names the missing field(s).
 *
 * Refs: Staff Management Phase 1 — R6, G1, G3
 */

import React from 'react'

export interface ComplianceSummary {
  probation_ending_soon: number
  visa_expiring_soon: number
  pay_review_due: number
  below_minimum_wage: number
  missing_agreement: number
  missing_employee_id: number
  missing_start_date: number
}

interface Props {
  summary: ComplianceSummary | null | undefined
  activeFilter: string | null
  onFilterChange: (filter: string | null) => void
}

interface CounterDef {
  key: keyof ComplianceSummary
  filter: string
  label: string
  // 'red' = critical (e.g. below min wage). 'amber' = warning (default).
  variant?: 'red' | 'amber'
}

const COUNTERS: CounterDef[] = [
  { key: 'probation_ending_soon', filter: 'probation_ending', label: 'Probation ending' },
  { key: 'visa_expiring_soon', filter: 'visa_expiring', label: 'Visa expiring' },
  { key: 'pay_review_due', filter: 'pay_review_due', label: 'Pay review due' },
  { key: 'below_minimum_wage', filter: 'below_minimum_wage', label: 'Below min wage', variant: 'red' },
  { key: 'missing_agreement', filter: 'missing_agreement', label: 'Missing agreement' },
  { key: 'missing_employee_id', filter: 'missing_employee_id', label: 'Missing code', variant: 'amber' },
  { key: 'missing_start_date', filter: 'missing_start_date', label: 'Missing start date', variant: 'amber' },
]

export default function ComplianceBanner({ summary, activeFilter, onFilterChange }: Props) {
  if (!summary) return null

  const showG3Banner = (summary.missing_start_date ?? 0) > 0
  const anyNonZero = COUNTERS.some(c => (summary[c.key] ?? 0) > 0)

  // Nothing to surface — render nothing.
  if (!anyNonZero) return null

  return (
    <div className="mb-4">
      {showG3Banner && (
        <div
          data-testid="g3-persistent-banner"
          role="alert"
          className="mb-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-700 rounded p-3 text-sm text-amber-800 dark:text-amber-200"
        >
          Phase 2 leave accrual will skip these staff until you backfill{' '}
          <code className="font-mono text-xs bg-amber-100 dark:bg-amber-900/40 px-1 py-0.5 rounded">
            employment_start_date
          </code>
          . Set start dates now to avoid disruption when Phase 2 ships.
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {COUNTERS.map(c => {
          const count = summary[c.key] ?? 0
          if (count === 0) return null
          const isActive = activeFilter === c.filter
          const variant = c.variant ?? 'amber'
          const colorCls =
            variant === 'red'
              ? isActive
                ? 'bg-red-600 text-white hover:bg-red-700'
                : 'bg-red-100 text-red-800 hover:bg-red-200 dark:bg-red-900/30 dark:text-red-200 dark:hover:bg-red-900/50'
              : isActive
                ? 'bg-amber-600 text-white hover:bg-amber-700'
                : 'bg-amber-100 text-amber-800 hover:bg-amber-200 dark:bg-amber-900/30 dark:text-amber-200 dark:hover:bg-amber-900/50'
          return (
            <button
              key={c.key}
              type="button"
              data-testid={`counter-${c.filter}`}
              aria-pressed={isActive}
              onClick={() => onFilterChange(isActive ? null : c.filter)}
              className={`px-3 py-2 min-h-[44px] rounded text-sm font-medium transition-colors ${colorCls}`}
            >
              <span className="font-semibold">{count}</span> {c.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

/**
 * StaffRowDots
 *
 * Chip-cluster of small dots indicating which compliance fields a staff
 * row is missing. Hover tooltip names the missing field(s).
 *
 * - 🟠 amber dot for `employee_id == null` (G1)
 * - 🟠 amber dot for `employment_start_date == null` (G3)
 * - 🔴 red dot for below-minimum-wage (computed when threshold is provided)
 */
export interface StaffRowDotsInput {
  employee_id: string | null
  employment_start_date: string | null
  hourly_rate: string | null
  /** NZ minimum wage threshold in dollars; if omitted, no red dot is rendered. */
  minimum_wage_threshold?: number
}

interface Dot {
  color: 'red' | 'amber'
  tooltip: string
}

export function StaffRowDots({ staff }: { staff: StaffRowDotsInput }) {
  const dots: Dot[] = []

  if (staff.employee_id === null) {
    dots.push({ color: 'amber', tooltip: 'employee code' })
  }
  if (staff.employment_start_date === null) {
    dots.push({ color: 'amber', tooltip: 'employment start date' })
  }

  // Below-min-wage detection — only when both the rate and the threshold
  // are present and the rate is strictly below the threshold.
  if (
    staff.minimum_wage_threshold !== undefined &&
    staff.hourly_rate !== null &&
    staff.hourly_rate !== ''
  ) {
    const rate = parseFloat(staff.hourly_rate)
    if (!Number.isNaN(rate) && rate < staff.minimum_wage_threshold) {
      dots.push({ color: 'red', tooltip: 'below minimum wage' })
    }
  }

  if (dots.length === 0) return null

  const tooltip = `Missing: ${dots.map(d => d.tooltip).join(', ')}`

  return (
    <span
      title={tooltip}
      data-testid="staff-row-dots"
      className="inline-flex gap-1 align-middle"
      aria-label={tooltip}
    >
      {dots.map((d, i) => (
        <span
          key={i}
          className={`inline-block w-2 h-2 rounded-full ${
            d.color === 'red' ? 'bg-red-500' : 'bg-amber-500'
          }`}
        />
      ))}
    </span>
  )
}
