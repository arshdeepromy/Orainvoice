import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { useBranch } from '@/contexts/BranchContext'
import { useToast, ToastContainer } from '@/components/ui'
import type {
  AttendanceResponse,
  AttendanceRow,
  AttendanceDetailResponse,
  AttendanceShift,
} from './types'

type RangePreset = 'today' | 'week' | 'month' | 'custom'

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

/** First and last day of the calendar month containing `d`. */
function monthBounds(d: Date): { start: string; end: string } {
  const first = new Date(d.getFullYear(), d.getMonth(), 1)
  const last = new Date(d.getFullYear(), d.getMonth() + 1, 0)
  return { start: localISO(first), end: localISO(last) }
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

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function fmtDate(iso: string): string {
  // iso is YYYY-MM-DD — render as e.g. "Mon 23 Jun"
  const [y, m, d] = iso.split('-').map(Number)
  const dt = new Date(y, (m ?? 1) - 1, d)
  return dt.toLocaleDateString([], { weekday: 'short', day: '2-digit', month: 'short' })
}

const SOURCE_LABEL: Record<AttendanceRow['expected_source'], string> = {
  scheduled: 'Scheduled',
  fixed: 'Fixed',
  roster: 'Roster',
  none: '—',
}

export default function AttendanceTab() {
  const today = useMemo(() => localISO(new Date()), [])
  const { toasts, addToast, dismissToast } = useToast()

  const [preset, setPreset] = useState<RangePreset>('today')
  const [start, setStart] = useState<string>(today)
  const [end, setEnd] = useState<string>(today)

  const { branches } = useBranch()
  const [filterBranch, setFilterBranch] = useState<string>('all')

  const [data, setData] = useState<AttendanceResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Expand-row state: one open at a time, lazily fetched + cached per staff/range.
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Apply a preset → recompute start/end.
  const applyPreset = useCallback((p: RangePreset) => {
    setPreset(p)
    setExpandedId(null)
    if (p === 'today') {
      setStart(today)
      setEnd(today)
    } else if (p === 'week') {
      const b = weekBounds(new Date())
      setStart(b.start)
      setEnd(b.end)
    } else if (p === 'month') {
      const b = monthBounds(new Date())
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

  const rangeIsToday = start === today && end === today

  const toggleExpand = useCallback((staffId: string) => {
    setExpandedId((cur) => (cur === staffId ? null : staffId))
  }, [])

  return (
    <div className="space-y-4">
      {/* Intro: this tab reviews already-worked hours (not the live clocked-in view) */}
      <p className="text-xs text-muted">
        Review hours staff have already worked, then sign them off for payroll. Expand a
        row to see each shift. For who is on the clock right now, use the{' '}
        <span className="font-medium text-text">Clocked In</span> tab.
      </p>

      {/* Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {(['today', 'week', 'month', 'custom'] as RangePreset[]).map((p) => (
            <button
              key={p}
              onClick={() => applyPreset(p)}
              className={`h-9 rounded-lg border px-3 text-sm font-medium transition-colors ${
                preset === p
                  ? 'border-accent bg-accent/10 text-accent'
                  : 'border-border bg-card text-text hover:bg-muted/5'
              }`}
            >
              {p === 'today' ? 'Today' : p === 'week' ? 'This Week' : p === 'month' ? 'This Month' : 'Custom'}
            </button>
          ))}

          {preset === 'custom' && (
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={start}
                max={end || undefined}
                onChange={(e) => { setStart(e.target.value); setExpandedId(null) }}
                className="h-9 rounded-lg border border-border bg-canvas px-2 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
              />
              <span className="text-xs text-muted">to</span>
              <input
                type="date"
                value={end}
                min={start || undefined}
                onChange={(e) => { setEnd(e.target.value); setExpandedId(null) }}
                className="h-9 rounded-lg border border-border bg-canvas px-2 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
              />
            </div>
          )}
        </div>

        {/* Branch filter */}
        <select
          value={filterBranch}
          onChange={(e) => { setFilterBranch(e.target.value); setExpandedId(null) }}
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
          <SummaryCard
            label="Pending review"
            value={String(summary.pending_review_count)}
            tone={summary.pending_review_count > 0 ? 'warn' : 'success'}
          />
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
          <p className="mt-4 text-sm font-medium text-text">No worked hours in this range</p>
          <p className="mt-1 text-xs text-muted">
            {rangeIsToday
              ? 'Try This Week or This Month to review earlier shifts.'
              : 'Staff appear here once they have clocked shifts within the selected dates.'}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-canvas text-left text-xs font-medium text-muted">
                <th className="w-8 px-2 py-2.5" />
                <th className="px-4 py-2.5">Staff</th>
                <th className="px-4 py-2.5">Branch</th>
                <th className="px-4 py-2.5 text-right">Worked</th>
                <th className="px-4 py-2.5 text-right">Expected</th>
                <th className="px-4 py-2.5 text-right">Variance</th>
                <th className="px-4 py-2.5 text-center">Shifts</th>
                <th className="px-4 py-2.5">Review</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((r) => (
                <AttendanceRowItem
                  key={r.staff_id}
                  row={r}
                  start={start}
                  end={end}
                  expanded={expandedId === r.staff_id}
                  onToggle={() => toggleExpand(r.staff_id)}
                  onReviewed={() => fetchData()}
                  addToast={addToast}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}

function SummaryCard({ label, value, tone }: { label: string; value: string; tone?: 'warn' | 'success' }) {
  const valueClass =
    tone === 'warn' ? 'text-warn' : tone === 'success' ? 'text-success' : 'text-text'
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <p className="text-xs text-muted">{label}</p>
      <p className={`mt-1 text-lg font-semibold ${valueClass}`}>{value}</p>
    </div>
  )
}

interface RowProps {
  row: AttendanceRow
  start: string
  end: string
  expanded: boolean
  onToggle: () => void
  onReviewed: () => void
  addToast: (kind: 'success' | 'error' | 'info', msg: string) => void
}

function AttendanceRowItem({ row, start, end, expanded, onToggle, onReviewed, addToast }: RowProps) {
  const variance = row.variance_hours
  const varClass =
    variance == null ? 'text-muted'
      : variance < -0.01 ? 'text-danger'
      : variance > 0.01 ? 'text-success'
      : 'text-muted'

  const reviewBadge = (() => {
    if (row.pending_review_count > 0) {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-warn/10 px-2 py-0.5 text-[11px] font-medium text-warn">
          {row.pending_review_count} pending
        </span>
      )
    }
    if (row.reviewed_count > 0) {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2 py-0.5 text-[11px] font-medium text-success">
          <svg className="h-3 w-3" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M16.7 5.3a1 1 0 010 1.4l-7.5 7.5a1 1 0 01-1.4 0L3.3 9.7a1 1 0 011.4-1.4l3.1 3.1 6.8-6.8a1 1 0 011.4 0z" clipRule="evenodd" /></svg>
          Reviewed
        </span>
      )
    }
    return <span className="text-xs text-muted">—</span>
  })()

  return (
    <>
      <tr
        className="cursor-pointer transition-colors hover:bg-muted/5"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <td className="px-2 py-3 text-center align-middle">
          <svg
            className={`mx-auto h-4 w-4 text-muted transition-transform duration-200 ${expanded ? 'rotate-90' : ''}`}
            viewBox="0 0 20 20" fill="currentColor"
          >
            <path fillRule="evenodd" d="M7.3 5.3a1 1 0 011.4 0l4 4a1 1 0 010 1.4l-4 4a1 1 0 01-1.4-1.4L10.6 10 7.3 6.7a1 1 0 010-1.4z" clipRule="evenodd" />
          </svg>
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-2.5">
            <div className="relative flex h-8 w-8 items-center justify-center rounded-full bg-accent/10 text-xs font-bold text-accent">
              {row.staff_name?.charAt(0) ?? '?'}
              {row.is_clocked_in && (
                <span
                  className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-card bg-success"
                  title="Currently clocked in"
                />
              )}
            </div>
            <div>
              <p className="font-medium text-text">{row.staff_name}</p>
              {row.position && <p className="text-xs text-muted">{row.position}</p>}
            </div>
          </div>
        </td>
        <td className="px-4 py-3 text-muted">{row.branch_name ?? '—'}</td>
        <td className="px-4 py-3 text-right font-mono font-medium text-text">
          {fmtHours(row.worked_hours)}
        </td>
        <td className="px-4 py-3 text-right">
          <span className="font-mono text-text">{fmtHours(row.expected_hours)}</span>
          {row.expected_source !== 'none' && (
            <span className="ml-2 inline-flex items-center rounded-full bg-muted/10 px-2 py-0.5 text-[10px] font-medium text-muted">
              {SOURCE_LABEL[row.expected_source]}
            </span>
          )}
        </td>
        <td className={`px-4 py-3 text-right font-mono font-medium ${varClass}`}>
          {variance == null
            ? '—'
            : `${variance < 0 ? '-' : variance > 0 ? '+' : ''}${fmtHours(Math.abs(variance))}`}
        </td>
        <td className="px-4 py-3 text-center text-muted">{row.shift_count}</td>
        <td className="px-4 py-3">{reviewBadge}</td>
      </tr>
      <tr>
        <td colSpan={8} className="p-0">
          <ExpandPanel
            open={expanded}
            staffId={row.staff_id}
            staffName={row.staff_name}
            start={start}
            end={end}
            onReviewed={onReviewed}
            addToast={addToast}
          />
        </td>
      </tr>
    </>
  )
}

interface ExpandPanelProps {
  open: boolean
  staffId: string
  staffName: string
  start: string
  end: string
  onReviewed: () => void
  addToast: (kind: 'success' | 'error' | 'info', msg: string) => void
}

function ExpandPanel({ open, staffId, staffName, start, end, onReviewed, addToast }: ExpandPanelProps) {
  const navigate = useNavigate()
  const [detail, setDetail] = useState<AttendanceDetailResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [busyAll, setBusyAll] = useState(false)
  const loadedKey = useRef<string | null>(null)

  const rangeKey = `${staffId}|${start}|${end}`

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      setLoading(true)
      setError(null)
      const res = await apiClient.get<AttendanceDetailResponse>(
        `/api/v2/timesheets/attendance/${staffId}/shifts`,
        { params: { start, end }, signal },
      )
      setDetail(res.data ?? null)
      loadedKey.current = rangeKey
    } catch (err: unknown) {
      if (!(err as { name?: string })?.name?.includes('Cancel') &&
          !(err as { code?: string })?.code?.includes('CANCELED')) {
        setError('Failed to load shifts')
      }
    } finally {
      setLoading(false)
    }
  }, [staffId, start, end, rangeKey])

  // Lazily load (and reload when the range changes) only while open.
  useEffect(() => {
    if (!open) return
    if (loadedKey.current === rangeKey && detail) return
    const controller = new AbortController()
    load(controller.signal)
    return () => controller.abort()
  }, [open, rangeKey, load, detail])

  const reviewShift = useCallback(async (shift: AttendanceShift) => {
    setBusyId(shift.id)
    try {
      await apiClient.post(`/api/v2/timesheets/attendance/shifts/${shift.id}/review`, {
        reviewed: !shift.reviewed,
      })
      await load()
      onReviewed()
    } catch {
      addToast('error', 'Could not update review status')
    } finally {
      setBusyId(null)
    }
  }, [load, onReviewed, addToast])

  const reviewAll = useCallback(async () => {
    setBusyAll(true)
    try {
      const res = await apiClient.post<{ affected_count: number }>(
        `/api/v2/timesheets/attendance/${staffId}/review-all`,
        null,
        { params: { start, end } },
      )
      const n = res.data?.affected_count ?? 0
      addToast('success', n > 0 ? `Approved ${n} shift${n === 1 ? '' : 's'}` : 'All shifts already reviewed')
      await load()
      onReviewed()
    } catch {
      addToast('error', 'Could not approve shifts')
    } finally {
      setBusyAll(false)
    }
  }, [staffId, start, end, load, onReviewed, addToast])

  const pending = detail?.pending_review_count ?? 0

  return (
    <div
      className="grid bg-canvas/40 transition-[grid-template-rows] duration-300 ease-in-out"
      style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
    >
      <div className="overflow-hidden">
        <div className="border-t border-border px-4 py-4">
          {loading && !detail ? (
            <div className="animate-pulse space-y-2">
              {[1, 2, 3].map((i) => <div key={i} className="h-10 rounded bg-muted/10" />)}
            </div>
          ) : error ? (
            <div className="flex items-center justify-between rounded-lg bg-danger/5 px-3 py-2 text-sm text-danger">
              <span>{error}</span>
              <button onClick={() => load()} className="text-accent hover:underline">Retry</button>
            </div>
          ) : !detail || detail.shifts.length === 0 ? (
            <p className="py-2 text-sm text-muted">No shifts recorded in this range.</p>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs font-medium uppercase tracking-wide text-muted">
                  Shifts ({detail.shifts.length})
                  {pending > 0 && <span className="ml-2 text-warn">· {pending} pending review</span>}
                </p>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => navigate(`/timesheets?tab=timesheets&staff=${encodeURIComponent(staffName)}`)}
                    title="Adjust payable hours, approve and lock for the pay run in the Timesheets tab"
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-text transition-colors hover:bg-canvas"
                  >
                    Adjust in Timesheets
                    <svg className="h-3.5 w-3.5 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                    </svg>
                  </button>
                  {pending > 0 && (
                    <button
                      onClick={reviewAll}
                      disabled={busyAll}
                      className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-accent px-3 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                    >
                      {busyAll ? 'Approving…' : `Approve all (${pending})`}
                    </button>
                  )}
                </div>
              </div>

              <div className="overflow-hidden rounded-lg border border-border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-card text-left text-[11px] font-medium uppercase tracking-wide text-muted">
                      <th className="px-3 py-2">Date</th>
                      <th className="px-3 py-2">Clock in</th>
                      <th className="px-3 py-2">Clock out</th>
                      <th className="px-3 py-2 text-right">Worked</th>
                      <th className="px-3 py-2">Scheduled</th>
                      <th className="px-3 py-2">Branch</th>
                      <th className="px-3 py-2 text-right">Review</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {detail.shifts.map((s) => (
                      <tr key={s.id} className="bg-canvas/30">
                        <td className="px-3 py-2 font-medium text-text">{fmtDate(s.work_date)}</td>
                        <td className="px-3 py-2 text-muted">{fmtTime(s.clock_in_at)}</td>
                        <td className="px-3 py-2 text-muted">
                          {s.is_open
                            ? <span className="inline-flex items-center gap-1 text-success"><span className="h-1.5 w-1.5 rounded-full bg-success" />On clock</span>
                            : fmtTime(s.clock_out_at)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-text">{fmtHours(s.worked_hours)}</td>
                        <td className="px-3 py-2 text-xs text-muted">
                          {s.scheduled_start ? (
                            `${fmtTime(s.scheduled_start)}–${fmtTime(s.scheduled_end)}`
                          ) : s.pattern_start ? (
                            <span title="From this staff member's fixed weekly pattern (no rostered shift)">
                              {s.pattern_start}–{s.pattern_end}
                              <span className="ml-1 text-[10px] italic text-muted/70">pattern</span>
                            </span>
                          ) : (
                            <span className="italic">unmatched</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-xs text-muted">{s.branch_name ?? '—'}</td>
                        <td className="px-3 py-2 text-right">
                          {s.is_open ? (
                            <span className="text-xs text-muted">—</span>
                          ) : s.reviewed ? (
                            <button
                              onClick={() => reviewShift(s)}
                              disabled={busyId === s.id}
                              title={s.reviewed_by_name ? `Approved by ${s.reviewed_by_name}` : 'Approved'}
                              className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2 py-1 text-[11px] font-medium text-success transition-colors hover:bg-success/20 disabled:opacity-50"
                            >
                              <svg className="h-3 w-3" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M16.7 5.3a1 1 0 010 1.4l-7.5 7.5a1 1 0 01-1.4 0L3.3 9.7a1 1 0 011.4-1.4l3.1 3.1 6.8-6.8a1 1 0 011.4 0z" clipRule="evenodd" /></svg>
                              Approved
                            </button>
                          ) : (
                            <button
                              onClick={() => reviewShift(s)}
                              disabled={busyId === s.id}
                              className="inline-flex items-center gap-1 rounded-full border border-accent/40 px-2.5 py-1 text-[11px] font-semibold text-accent transition-colors hover:bg-accent/10 disabled:opacity-50"
                            >
                              {busyId === s.id ? '…' : 'Approve'}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <p className="text-[11px] leading-relaxed text-muted">
                Approving a shift signs off its hours for payroll. Worked{' '}
                <span className="font-mono">{fmtHours(detail.worked_hours)}</span>
                {detail.expected_hours != null && (
                  <> of <span className="font-mono">{fmtHours(detail.expected_hours)}</span> expected</>
                )}.
                <br />
                <span className="font-medium">Scheduled</span> shows the rostered shift a clock-in
                matched; <span className="italic">pattern</span> is the fixed weekly schedule for
                fixed-hours staff (no rostered shift to match); <span className="italic">unmatched</span>{' '}
                means neither applies. To change payable hours, run the approve/lock pay-run flow, or
                adjust the final figure, use <span className="font-medium">Adjust in Timesheets</span>.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
