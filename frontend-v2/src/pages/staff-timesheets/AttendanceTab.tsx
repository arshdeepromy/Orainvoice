import { useCallback, useEffect, useMemo, useState } from 'react'
import apiClient from '@/api/client'
import { useBranch } from '@/contexts/BranchContext'
import type { AttendanceResponse, AttendanceRow } from './types'

type RangePreset = 'today' | 'week' | 'custom'

/** Local date as YYYY-MM-DD (no UTC shift). */
function localISO(d: Date): string {
  const tz = d.getTimezoneOffset() * 60000
  return new Date(d.getTime() - tz).toISOString().split('T')[0]
}

/** Monday (start) and Sunday (end) of the week containing `d`. */
function weekBounds(d: Date): { start: string; end: string } {
  const day = d.getDay() // 0=Sun..6=Sat
  const mondayOffset = day === 0 ? -6 : 1 - day
  const monday = new Date(d)
  monday.setDate(d.getDate() + mondayOffset)
  const sunday = new Date(monday)
  sunday.setDate(monday.getDate() + 6)
  return { start: localISO(monday), end: localISO(sunday) }
}

/** Decimal hours → "Xh Ym" (e.g. 7.5 → "7h 30m"). */
function fmtHours(hours: number | null | undefined): string {
  if (hours == null) return '—'
  const totalMin = Math.round(hours * 60)
  const h = Math.floor(totalMin / 60)
  const m = totalMin % 60
  if (h === 0 && m === 0) return '0h'
  return `${h}h${m ? ` ${m}m` : ''}`
}

const SOURCE_LABEL: Record<AttendanceRow['expected_source'], string> = {
  scheduled: 'Scheduled',
  fixed: 'Fixed',
  roster: 'Roster',
  none: '—',
}

export default function AttendanceTab() {
  const today = useMemo(() => localISO(new Date()), [])

  const [preset, setPreset] = useState<RangePreset>('today')
  const [start, setStart] = useState<string>(today)
  const [end, setEnd] = useState<string>(today)

  const { branches } = useBranch()
  const [filterBranch, setFilterBranch] = useState<string>('all')

  const [data, setData] = useState<AttendanceResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Apply a preset → recompute start/end.
  const applyPreset = useCallback((p: RangePreset) => {
    setPreset(p)
    if (p === 'today') {
      setStart(today)
      setEnd(today)
    } else if (p === 'week') {
      const b = weekBounds(new Date())
      setStart(b.start)
      setEnd(b.end)
    }
    // 'custom' keeps whatever is in the date inputs.
  }, [today])

  const fetchData = useCallback(async (signal?: AbortSignal) => {
    try {
      setLoading(true)
      const res = await apiClient.get<AttendanceResponse>('/api/v2/timesheets/attendance', {
        params: { start, end },
        signal,
      })
      setData(res.data ?? null)
      setError(null)
    } catch (err: unknown) {
      if (!(err as { name?: string })?.name?.includes('Cancel') &&
          !(err as { code?: string })?.code?.includes('CANCELED')) {
        setError('Failed to load attendance data')
      }
    } finally {
      setLoading(false)
    }
  }, [start, end])

  useEffect(() => {
    const controller = new AbortController()
    fetchData(controller.signal)
    return () => controller.abort()
  }, [fetchData])

  const allItems = data?.items ?? []
  const items = filterBranch === 'all'
    ? allItems
    : allItems.filter((r) => r.branch_name === filterBranch)

  const summary = data?.summary

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {(['today', 'week', 'custom'] as RangePreset[]).map((p) => (
            <button
              key={p}
              onClick={() => applyPreset(p)}
              className={`h-9 rounded-lg border px-3 text-sm font-medium transition-colors ${
                preset === p
                  ? 'border-accent bg-accent/10 text-accent'
                  : 'border-border bg-card text-text hover:bg-muted/5'
              }`}
            >
              {p === 'today' ? 'Today' : p === 'week' ? 'This Week' : 'Custom'}
            </button>
          ))}

          {preset === 'custom' && (
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={start}
                max={end || undefined}
                onChange={(e) => setStart(e.target.value)}
                className="h-9 rounded-lg border border-border bg-canvas px-2 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
              />
              <span className="text-xs text-muted">to</span>
              <input
                type="date"
                value={end}
                min={start || undefined}
                onChange={(e) => setEnd(e.target.value)}
                className="h-9 rounded-lg border border-border bg-canvas px-2 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
              />
            </div>
          )}
        </div>

        {/* Branch filter */}
        <select
          value={filterBranch}
          onChange={(e) => setFilterBranch(e.target.value)}
          className="h-9 rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
        >
          <option value="all">All Branches</option>
          {branches.map((b) => (
            <option key={b.id} value={b.name}>{b.name}</option>
          ))}
        </select>
      </div>

      {/* Summary cards */}
      {summary && !loading && !error && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <SummaryCard label="Staff" value={String(summary.total_staff)} />
          <SummaryCard label="Hours worked" value={fmtHours(summary.total_worked_hours)} />
          <SummaryCard label="Expected" value={fmtHours(summary.total_expected_hours)} />
          <SummaryCard label="Still clocked in" value={String(summary.clocked_in_count)} />
        </div>
      )}

      {/* Body */}
      {loading && !data ? (
        <div className="animate-pulse space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-14 rounded-lg bg-muted/10" />
          ))}
        </div>
      ) : error ? (
        <div className="flex flex-col items-center justify-center py-12">
          <div className="rounded-full bg-danger/10 p-3">
            <svg className="h-6 w-6 text-danger" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
          </div>
          <p className="mt-3 text-sm font-medium text-text">{error}</p>
          <button onClick={() => fetchData()} className="mt-2 text-sm text-accent hover:underline">
            Retry
          </button>
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16">
          <div className="rounded-full bg-muted/10 p-4">
            <svg className="h-8 w-8 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <p className="mt-4 text-sm font-medium text-text">No attendance in this range</p>
          <p className="mt-1 text-xs text-muted">
            Staff appear here once they clock in within the selected dates.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-canvas text-left text-xs font-medium text-muted">
                <th className="px-4 py-2.5">Staff</th>
                <th className="px-4 py-2.5">Branch</th>
                <th className="px-4 py-2.5 text-right">Worked</th>
                <th className="px-4 py-2.5 text-right">Expected</th>
                <th className="px-4 py-2.5 text-right">Variance</th>
                <th className="px-4 py-2.5 text-center">Shifts</th>
                <th className="px-4 py-2.5">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((r) => {
                const variance = r.variance_hours
                const varClass =
                  variance == null ? 'text-muted'
                    : variance < -0.01 ? 'text-danger'
                    : variance > 0.01 ? 'text-success'
                    : 'text-muted'
                return (
                  <tr key={r.staff_id} className="hover:bg-muted/5 transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/10 text-xs font-bold text-accent">
                          {r.staff_name?.charAt(0) ?? '?'}
                        </div>
                        <div>
                          <p className="font-medium text-text">{r.staff_name}</p>
                          {r.position && <p className="text-xs text-muted">{r.position}</p>}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-muted">{r.branch_name ?? '—'}</td>
                    <td className="px-4 py-3 text-right font-mono font-medium text-text">
                      {fmtHours(r.worked_hours)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="font-mono text-text">{fmtHours(r.expected_hours)}</span>
                      {r.expected_source !== 'none' && (
                        <span className="ml-2 inline-flex items-center rounded-full bg-muted/10 px-2 py-0.5 text-[10px] font-medium text-muted">
                          {SOURCE_LABEL[r.expected_source]}
                        </span>
                      )}
                    </td>
                    <td className={`px-4 py-3 text-right font-mono font-medium ${varClass}`}>
                      {variance == null
                        ? '—'
                        : `${variance > 0 ? '+' : ''}${fmtHours(Math.abs(variance)).replace(/^/, variance < 0 ? '-' : '')}`}
                    </td>
                    <td className="px-4 py-3 text-center text-muted">{r.shift_count}</td>
                    <td className="px-4 py-3">
                      {r.is_clocked_in ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2 py-0.5 text-[11px] font-medium text-success">
                          <span className="h-1.5 w-1.5 rounded-full bg-success" />
                          Clocked in
                        </span>
                      ) : r.last_clock_out_at ? (
                        <span className="text-xs text-muted">
                          Out {new Date(r.last_clock_out_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      ) : (
                        <span className="text-xs text-muted">—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-lg font-semibold text-text">{value}</p>
    </div>
  )
}
