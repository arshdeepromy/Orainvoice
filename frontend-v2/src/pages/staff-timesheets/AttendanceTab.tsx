import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { useBranch } from '@/contexts/BranchContext'
import { useToast, ToastContainer } from '@/components/ui'
import { Modal } from '@/components/ui'
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

/** ISO datetime → "HH:MM" in the browser's local time (for time inputs). */
function isoToTimeInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

/** Combine a YYYY-MM-DD work date + "HH:MM" local time → ISO string. */
function combineDateTime(workDate: string, timeStr: string): string {
  const [y, m, d] = workDate.split('-').map(Number)
  const [hh, mm] = timeStr.split(':').map(Number)
  return new Date(y, (m ?? 1) - 1, d, hh ?? 0, mm ?? 0, 0).toISOString()
}

/** Decimal hours string → whole minutes (e.g. "8.5" → 510). */
function hoursToMinutes(hoursStr: string): number {
  const h = Number(hoursStr)
  if (!isFinite(h) || h < 0) return 0
  return Math.round(h * 60)
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
  const [editTarget, setEditTarget] = useState<AttendanceShift | null>(null)
  const [addOpen, setAddOpen] = useState(false)
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

  const apiMsg = (err: unknown, fallback: string): string => {
    const d = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    if (typeof d === 'string') return d
    if (d && typeof d === 'object' && 'message' in d) return String((d as { message: string }).message)
    return fallback
  }

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

  const saveEdit = useCallback(async (shift: AttendanceShift, payload: Record<string, unknown>) => {
    await apiClient.patch(`/api/v2/timesheets/attendance/shifts/${shift.id}`, payload)
    setEditTarget(null)
    addToast('success', 'Shift updated')
    await load()
    onReviewed()
  }, [load, onReviewed, addToast])

  const addDay = useCallback(async (payload: Record<string, unknown>) => {
    await apiClient.post(`/api/v2/timesheets/attendance/${staffId}/shifts`, payload)
    setAddOpen(false)
    addToast('success', 'Day added')
    await load()
    onReviewed()
  }, [staffId, load, onReviewed, addToast])

  const removeShift = useCallback(async (shift: AttendanceShift) => {
    setBusyId(shift.id)
    try {
      await apiClient.delete(`/api/v2/timesheets/attendance/shifts/${shift.id}`)
      addToast('success', 'Day removed')
      await load()
      onReviewed()
    } catch (err) {
      addToast('error', apiMsg(err, 'Could not remove this day'))
    } finally {
      setBusyId(null)
    }
  }, [load, onReviewed, addToast])

  const pending = detail?.pending_review_count ?? 0
  const arrangement = detail?.working_arrangement ?? null

  const header = (
    <div className="flex items-center justify-between gap-3">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">
        Shifts ({detail?.shifts.length ?? 0})
        {pending > 0 && <span className="ml-2 text-warn">· {pending} pending review</span>}
      </p>
      <div className="flex items-center gap-2">
        <button
          onClick={() => setAddOpen(true)}
          title="Add a worked day (for staff who didn't clock, or a missed day)"
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-text transition-colors hover:bg-canvas"
        >
          <svg className="h-3.5 w-3.5 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          Add day
        </button>
        <button
          onClick={() => navigate(`/timesheets?tab=timesheets&staff=${encodeURIComponent(staffName)}`)}
          title="Approve and lock for the pay run in the Timesheets tab"
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-text transition-colors hover:bg-canvas"
        >
          Open in Timesheets
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
  )

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
          ) : (
            <div className="space-y-3">
              {header}

              {!detail || detail.shifts.length === 0 ? (
                <p className="rounded-lg border border-dashed border-border py-6 text-center text-sm text-muted">
                  No shifts recorded in this range. Use <span className="font-medium text-text">Add day</span> to
                  record worked hours manually.
                </p>
              ) : (
                <div className="overflow-hidden rounded-lg border border-border">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border bg-card text-left text-[11px] font-medium uppercase tracking-wide text-muted">
                        <th className="px-3 py-2">Date</th>
                        <th className="px-3 py-2">Clock in</th>
                        <th className="px-3 py-2">Clock out</th>
                        <th className="px-3 py-2 text-right">Worked</th>
                        <th className="px-3 py-2">Scheduled</th>
                        <th className="px-3 py-2 text-right">Review</th>
                        <th className="px-3 py-2 text-right">Edit</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {detail.shifts.map((s) => (
                        <tr key={s.id} className="bg-canvas/30">
                          <td className="px-3 py-2 font-medium text-text">
                            {fmtDate(s.work_date)}
                            {s.is_manual && (
                              <span className="ml-1.5 rounded bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">manual</span>
                            )}
                            {s.edited && !s.is_manual && (
                              <span className="ml-1.5 rounded bg-warn/10 px-1.5 py-0.5 text-[10px] font-medium text-warn" title={s.edit_reason ?? 'Edited'}>edited</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-muted">
                            {s.corrected_clock_in_at ? (
                              <span>
                                {fmtTime(s.corrected_clock_in_at)}
                                <span className="ml-1 text-[10px] text-muted/60 line-through">{fmtTime(s.clock_in_at)}</span>
                              </span>
                            ) : s.is_manual_hours ? <span className="text-muted/60">—</span> : fmtTime(s.clock_in_at)}
                          </td>
                          <td className="px-3 py-2 text-muted">
                            {s.is_open ? (
                              <span className="inline-flex items-center gap-1 text-success"><span className="h-1.5 w-1.5 rounded-full bg-success" />On clock</span>
                            ) : s.corrected_clock_out_at ? (
                              <span>
                                {fmtTime(s.corrected_clock_out_at)}
                                <span className="ml-1 text-[10px] text-muted/60 line-through">{fmtTime(s.clock_out_at)}</span>
                              </span>
                            ) : s.is_manual_hours ? <span className="text-muted/60">—</span> : fmtTime(s.clock_out_at)}
                          </td>
                          <td className="px-3 py-2 text-right font-mono text-text">
                            {fmtHours(s.worked_hours)}
                            {s.edited && s.original_worked_hours != null && (
                              <span className="ml-1 text-[10px] text-muted/60 line-through">{fmtHours(s.original_worked_hours)}</span>
                            )}
                          </td>
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
                          <td className="px-3 py-2 text-right">
                            <div className="flex items-center justify-end gap-1">
                              {!s.is_open && (
                                <button
                                  onClick={() => setEditTarget(s)}
                                  title="Correct this shift's hours"
                                  className="rounded-md p-1.5 text-muted transition-colors hover:bg-muted/10 hover:text-text"
                                >
                                  <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
                                  </svg>
                                </button>
                              )}
                              {s.is_manual && (
                                <button
                                  onClick={() => removeShift(s)}
                                  disabled={busyId === s.id}
                                  title="Remove this manually added day"
                                  className="rounded-md p-1.5 text-muted transition-colors hover:bg-danger/10 hover:text-danger disabled:opacity-50"
                                >
                                  <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                                  </svg>
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <p className="text-[11px] leading-relaxed text-muted">
                {detail && (
                  <>Worked <span className="font-mono">{fmtHours(detail.worked_hours)}</span>
                  {detail.expected_hours != null && (
                    <> of <span className="font-mono">{fmtHours(detail.expected_hours)}</span> expected</>
                  )}. </>
                )}
                Approving signs off hours for payroll. <span className="font-medium">Edit</span> corrects a
                shift (clock-based staff keep their raw punch as evidence; the corrected time is an overlay);
                <span className="font-medium"> Add day</span> records hours for staff who didn&apos;t clock.
                Corrections flow straight into the pay-run; locked periods can&apos;t be changed.
              </p>
            </div>
          )}
        </div>
      </div>

      {editTarget && (
        <ShiftEditModal
          shift={editTarget}
          arrangement={arrangement}
          onClose={() => setEditTarget(null)}
          onSave={saveEdit}
          apiMsg={apiMsg}
        />
      )}
      {addOpen && (
        <ShiftAddModal
          arrangement={arrangement}
          defaultDate={start}
          onClose={() => setAddOpen(false)}
          onSave={addDay}
          apiMsg={apiMsg}
        />
      )}
    </div>
  )
}

interface ShiftEditModalProps {
  shift: AttendanceShift
  arrangement: string | null
  onClose: () => void
  onSave: (shift: AttendanceShift, payload: Record<string, unknown>) => Promise<void>
  apiMsg: (err: unknown, fallback: string) => string
}

function ShiftEditModal({ shift, arrangement, onClose, onSave, apiMsg }: ShiftEditModalProps) {
  const defaultHoursMode = shift.is_manual_hours || arrangement === 'fixed'
  const [mode, setMode] = useState<'times' | 'hours'>(defaultHoursMode ? 'hours' : 'times')
  const [inTime, setInTime] = useState(isoToTimeInput(shift.corrected_clock_in_at ?? shift.clock_in_at))
  const [outTime, setOutTime] = useState(isoToTimeInput(shift.corrected_clock_out_at ?? shift.clock_out_at))
  const [breakMin, setBreakMin] = useState(String(shift.break_minutes ?? 0))
  const [hoursStr, setHoursStr] = useState(shift.worked_hours != null ? String(shift.worked_hours) : '')
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async () => {
    if (!reason.trim()) { setErr('A reason is required.'); return }
    let payload: Record<string, unknown>
    if (mode === 'hours') {
      payload = { worked_minutes: hoursToMinutes(hoursStr), reason: reason.trim() }
    } else {
      if (!inTime || !outTime) { setErr('Enter both a clock-in and clock-out time.'); return }
      payload = {
        clock_in_at: combineDateTime(shift.work_date, inTime),
        clock_out_at: combineDateTime(shift.work_date, outTime),
        break_minutes: Number(breakMin) || 0,
        reason: reason.trim(),
      }
    }
    setSaving(true)
    setErr(null)
    try {
      await onSave(shift, payload)
    } catch (e) {
      setErr(apiMsg(e, 'Could not save the change.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open onClose={onClose} title={`Edit hours — ${fmtDate(shift.work_date)}`} className="max-w-md">
      <div className="space-y-4">
        <div className="inline-flex rounded-lg border border-border bg-card p-0.5">
          <button
            onClick={() => setMode('times')}
            className={`h-8 rounded-md px-3 text-xs font-medium transition-colors ${mode === 'times' ? 'bg-accent text-white' : 'text-muted hover:text-text'}`}
          >
            Correct times
          </button>
          <button
            onClick={() => setMode('hours')}
            className={`h-8 rounded-md px-3 text-xs font-medium transition-colors ${mode === 'hours' ? 'bg-accent text-white' : 'text-muted hover:text-text'}`}
          >
            Set hours
          </button>
        </div>

        {mode === 'times' ? (
          <div className="grid grid-cols-3 gap-3">
            <label className="text-xs text-muted">Clock in
              <input type="time" value={inTime} onChange={(e) => setInTime(e.target.value)}
                className="mt-1 h-9 w-full rounded-lg border border-border bg-canvas px-2 text-sm text-text" />
            </label>
            <label className="text-xs text-muted">Clock out
              <input type="time" value={outTime} onChange={(e) => setOutTime(e.target.value)}
                className="mt-1 h-9 w-full rounded-lg border border-border bg-canvas px-2 text-sm text-text" />
            </label>
            <label className="text-xs text-muted">Break (min)
              <input type="number" min={0} value={breakMin} onChange={(e) => setBreakMin(e.target.value)}
                className="mt-1 h-9 w-full rounded-lg border border-border bg-canvas px-2 text-sm text-text" />
            </label>
          </div>
        ) : (
          <label className="block text-xs text-muted">Worked hours
            <input type="number" min={0} step={0.25} value={hoursStr} onChange={(e) => setHoursStr(e.target.value)}
              placeholder="e.g. 8"
              className="mt-1 h-9 w-full rounded-lg border border-border bg-canvas px-2 text-sm text-text" />
          </label>
        )}

        {!shift.is_manual && mode === 'times' && (
          <p className="text-[11px] text-muted">
            The raw punch ({fmtTime(shift.clock_in_at)}–{shift.clock_out_at ? fmtTime(shift.clock_out_at) : '—'}) is
            kept as evidence; your correction is recorded as an overlay.
          </p>
        )}

        <label className="block text-xs text-muted">Reason <span className="text-danger">*</span>
          <input type="text" value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Forgot to clock out"
            className="mt-1 h-9 w-full rounded-lg border border-border bg-canvas px-2 text-sm text-text" />
        </label>

        {err && <p className="text-xs text-danger">{err}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="h-9 rounded-lg border border-border bg-card px-3 text-sm text-text hover:bg-canvas">Cancel</button>
          <button onClick={submit} disabled={saving}
            className="h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

interface ShiftAddModalProps {
  arrangement: string | null
  defaultDate: string
  onClose: () => void
  onSave: (payload: Record<string, unknown>) => Promise<void>
  apiMsg: (err: unknown, fallback: string) => string
}

function ShiftAddModal({ arrangement, defaultDate, onClose, onSave, apiMsg }: ShiftAddModalProps) {
  void arrangement
  const [mode, setMode] = useState<'hours' | 'times'>('hours')
  const [workDate, setWorkDate] = useState(defaultDate)
  const [inTime, setInTime] = useState('09:00')
  const [outTime, setOutTime] = useState('17:00')
  const [breakMin, setBreakMin] = useState('0')
  const [hoursStr, setHoursStr] = useState('')
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async () => {
    if (!workDate) { setErr('Pick a date.'); return }
    if (!reason.trim()) { setErr('A reason is required.'); return }
    let payload: Record<string, unknown>
    if (mode === 'hours') {
      if (!hoursStr) { setErr('Enter the worked hours.'); return }
      payload = { work_date: workDate, worked_minutes: hoursToMinutes(hoursStr), reason: reason.trim() }
    } else {
      if (!inTime || !outTime) { setErr('Enter both times.'); return }
      payload = {
        work_date: workDate,
        clock_in_at: combineDateTime(workDate, inTime),
        clock_out_at: combineDateTime(workDate, outTime),
        break_minutes: Number(breakMin) || 0,
        reason: reason.trim(),
      }
    }
    setSaving(true)
    setErr(null)
    try {
      await onSave(payload)
    } catch (e) {
      setErr(apiMsg(e, 'Could not add the day.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open onClose={onClose} title="Add a worked day" className="max-w-md">
      <div className="space-y-4">
        <label className="block text-xs text-muted">Date
          <input type="date" value={workDate} onChange={(e) => setWorkDate(e.target.value)}
            className="mt-1 h-9 w-full rounded-lg border border-border bg-canvas px-2 text-sm text-text" />
        </label>

        <div className="inline-flex rounded-lg border border-border bg-card p-0.5">
          <button
            onClick={() => setMode('hours')}
            className={`h-8 rounded-md px-3 text-xs font-medium transition-colors ${mode === 'hours' ? 'bg-accent text-white' : 'text-muted hover:text-text'}`}
          >
            Set hours
          </button>
          <button
            onClick={() => setMode('times')}
            className={`h-8 rounded-md px-3 text-xs font-medium transition-colors ${mode === 'times' ? 'bg-accent text-white' : 'text-muted hover:text-text'}`}
          >
            Enter times
          </button>
        </div>

        {mode === 'hours' ? (
          <label className="block text-xs text-muted">Worked hours
            <input type="number" min={0} step={0.25} value={hoursStr} onChange={(e) => setHoursStr(e.target.value)}
              placeholder="e.g. 8"
              className="mt-1 h-9 w-full rounded-lg border border-border bg-canvas px-2 text-sm text-text" />
          </label>
        ) : (
          <div className="grid grid-cols-3 gap-3">
            <label className="text-xs text-muted">Clock in
              <input type="time" value={inTime} onChange={(e) => setInTime(e.target.value)}
                className="mt-1 h-9 w-full rounded-lg border border-border bg-canvas px-2 text-sm text-text" />
            </label>
            <label className="text-xs text-muted">Clock out
              <input type="time" value={outTime} onChange={(e) => setOutTime(e.target.value)}
                className="mt-1 h-9 w-full rounded-lg border border-border bg-canvas px-2 text-sm text-text" />
            </label>
            <label className="text-xs text-muted">Break (min)
              <input type="number" min={0} value={breakMin} onChange={(e) => setBreakMin(e.target.value)}
                className="mt-1 h-9 w-full rounded-lg border border-border bg-canvas px-2 text-sm text-text" />
            </label>
          </div>
        )}

        <label className="block text-xs text-muted">Reason <span className="text-danger">*</span>
          <input type="text" value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Worked off-site, didn't clock in"
            className="mt-1 h-9 w-full rounded-lg border border-border bg-canvas px-2 text-sm text-text" />
        </label>

        {err && <p className="text-xs text-danger">{err}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="h-9 rounded-lg border border-border bg-card px-3 text-sm text-text hover:bg-canvas">Cancel</button>
          <button onClick={submit} disabled={saving}
            className="h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50">
            {saving ? 'Adding…' : 'Add day'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
