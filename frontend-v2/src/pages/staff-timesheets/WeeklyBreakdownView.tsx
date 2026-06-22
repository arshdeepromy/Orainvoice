/**
 * WeeklyBreakdownView — renders a pay period split into per-week (Mon–Sun)
 * sections for the "weekly lens" review aid.
 *
 * READ-ONLY. Each section shows a header (Week N · date range · week total
 * hours) and the per-staff hours for that week. Visually consistent with the
 * existing timesheets table/section styling (border-border, bg-card/canvas,
 * text-muted tokens). Hours are minutes / 60 formatted to 2dp.
 *
 * All inputs are consumed safely (`?.` / `?? []`); a missing or empty weeks
 * array simply renders an empty-state message rather than throwing.
 */
import { fmtRange } from './CyclePeriodControls'
import type { WeeklyBreakdownResponse, WeeklyBreakdownWeek } from './types'

/** Minutes → hours, 2dp + an "h" suffix (e.g. 130 → "2.17h"). */
function fmtHours(minutes: number | null | undefined): string {
  return `${((Number(minutes) || 0) / 60).toFixed(2)}h`
}

interface WeeklyBreakdownViewProps {
  data: WeeklyBreakdownResponse | null
  loading?: boolean
}

export default function WeeklyBreakdownView({ data, loading }: WeeklyBreakdownViewProps) {
  if (loading) {
    return (
      <div className="animate-pulse space-y-3" data-testid="weekly-breakdown-loading">
        {[1, 2].map((i) => (
          <div key={i} className="h-28 rounded-lg bg-muted/10" />
        ))}
      </div>
    )
  }

  const weeks = data?.weeks ?? []

  if (weeks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <p className="text-sm font-medium text-text">No weekly breakdown for this period</p>
        <p className="mt-1 max-w-sm text-center text-xs text-muted">
          Per-week hours appear here once staff have timesheets for the period.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4" data-testid="weekly-breakdown">
      {weeks.map((week: WeeklyBreakdownWeek) => {
        const staff = week?.staff ?? []
        // CyclePeriodControls.fmtRange expects {start_date, end_date}; the week
        // bucket carries exactly those clamped fields.
        const range = fmtRange({
          id: '',
          start_date: week?.start_date ?? '',
          end_date: week?.end_date ?? '',
          status: 'open',
        })
        return (
          <section
            key={`${week?.week_index}-${week?.start_date}`}
            className="overflow-hidden rounded-lg border border-border bg-card"
            data-testid="weekly-breakdown-week"
          >
            {/* Week header */}
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-canvas px-4 py-2.5">
              <div className="flex items-baseline gap-2">
                <span className="text-sm font-semibold text-text">Week {week?.week_index}</span>
                <span className="text-xs text-muted">{range}</span>
                <span className="text-[11px] text-muted">· ISO wk {week?.iso_week}</span>
              </div>
              <span className="font-mono text-sm font-semibold text-text">
                {fmtHours(week?.total_minutes)}
              </span>
            </div>

            {/* Per-staff hours for this week */}
            {staff.length === 0 ? (
              <p className="px-4 py-3 text-xs text-muted">No hours recorded this week.</p>
            ) : (
              <table className="w-full border-collapse text-sm">
                <tbody className="divide-y divide-border">
                  {staff.map((s) => (
                    <tr key={s?.staff_id} className="hover:bg-muted/5 transition-colors">
                      <td className="px-4 py-2.5 text-text">{s?.staff_name ?? 'Unknown'}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-sm text-text">
                        {fmtHours(s?.minutes)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        )
      })}
    </div>
  )
}
