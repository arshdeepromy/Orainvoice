/**
 * ThisMonthPanel
 *
 * Right-sidebar card on the Staff detail Overview tab showing four
 * "this month" metrics for the displayed staff member:
 *   - Hours logged
 *   - Jobs completed
 *   - Billable ratio
 *   - On-time rate
 *
 * Metrics are fetched once on mount (and again when `staffId` changes) from
 * the stats endpoint via `getStaffMonthStats(id, 'this_month', signal)`. An
 * AbortController cancels the in-flight request on unmount or staff change
 * (R8.7). Each metric renders "—" when its `has_data` flag is false (R8.3),
 * otherwise formatted per the design (R8.4/R8.5). On a non-abort fetch
 * failure all four metrics render "—" without crashing the tab.
 *
 * _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_
 */

import { useEffect, useState } from 'react'
import {
  getStaffMonthStats,
  type StaffMetric,
  type StaffMonthStats,
} from '@/api/staff'

interface Props {
  staffId: string
  /**
   * Optional lifted stats. When provided the panel renders these directly
   * and does NOT self-fetch — OverviewTab fetches once and shares the result
   * with both this panel and the Account panel (single source, R8.6). When
   * omitted the panel self-fetches (preserving standalone usage).
   */
  stats?: StaffMonthStats | null
  /** When using lifted stats, indicates the shared fetch failed. */
  failed?: boolean
}

/** Render '—' when has_data is false, else the formatted value. */
export function formatHours(metric: StaffMetric | undefined): string {
  if (!metric?.has_data) return '—'
  return `${(metric.value ?? 0).toFixed(1)}h`
}

export function formatCount(metric: StaffMetric | undefined): string {
  if (!metric?.has_data) return '—'
  return String(Math.round(metric.value ?? 0))
}

export function formatPercent(metric: StaffMetric | undefined): string {
  if (!metric?.has_data) return '—'
  return `${Math.round(metric.value ?? 0)}%`
}

export default function ThisMonthPanel({
  staffId,
  stats: liftedStats,
  failed: liftedFailed,
}: Props) {
  const controlled = liftedStats !== undefined || liftedFailed !== undefined
  const [stats, setStats] = useState<StaffMonthStats | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    // When stats are supplied by the parent, skip the self-fetch.
    if (controlled) return
    const controller = new AbortController()
    setStats(null)
    setFailed(false)
    const fetchStats = async () => {
      try {
        const data = await getStaffMonthStats(
          staffId,
          'this_month',
          controller.signal,
        )
        if (controller.signal.aborted) return
        setStats(data)
      } catch (err) {
        if (controller.signal.aborted) return
        // Non-abort failure — render all four as "—" without crashing.
        setFailed(true)
      }
    }
    fetchStats()
    return () => controller.abort()
  }, [staffId, controlled])

  // On failure or while loading we have no stats → every row renders "—".
  const effectiveFailed = controlled ? !!liftedFailed : failed
  const effectiveStats = controlled ? liftedStats ?? null : stats
  const safeStats = effectiveFailed ? null : effectiveStats

  const rows: Array<{ label: string; value: string }> = [
    { label: 'Hours logged', value: formatHours(safeStats?.hours_logged) },
    { label: 'Jobs completed', value: formatCount(safeStats?.jobs_completed) },
    { label: 'Billable ratio', value: formatPercent(safeStats?.billable_ratio) },
    { label: 'On-time rate', value: formatPercent(safeStats?.on_time_rate) },
  ]

  return (
    <section
      className="rounded-card border border-border bg-card shadow-card mb-4"
      aria-label="This month"
      data-testid="this-month-panel"
    >
      <div className="p-5">
        <div className="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.1em] text-muted-2">
          This month
        </div>
        <div>
          {rows.map((row, i) => (
            <div
              key={row.label}
              className={`flex items-center justify-between py-[11px] ${
                i < rows.length - 1 ? 'border-b border-border' : ''
              }`}
            >
              <span className="text-[13px] text-muted">{row.label}</span>
              <span className="mono text-[13px] font-medium text-text">
                {row.value}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
