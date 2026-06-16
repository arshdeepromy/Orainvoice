import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'
import type { TimesheetListResponse, TimesheetSummary, PeriodSummary } from './types'

interface TimesheetsTabProps {
  onPeriodSummary?: (summary: PeriodSummary) => void
}

export default function TimesheetsTab({ onPeriodSummary }: TimesheetsTabProps) {
  const [data, setData] = useState<TimesheetListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedPeriod, setSelectedPeriod] = useState<string>('current')

  // Filter state
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')

  // Action loading state (per row)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  // Adjust modal state
  const [adjustTarget, setAdjustTarget] = useState<TimesheetSummary | null>(null)
  const [adjustMinutes, setAdjustMinutes] = useState<string>('')
  const [adjustNotes, setAdjustNotes] = useState<string>('')
  const [adjusting, setAdjusting] = useState(false)

  // Fetch available pay periods
  const [periods, setPeriods] = useState<{ id: string; start_date: string; end_date: string; status: string }[]>([])

  useEffect(() => {
    const controller = new AbortController()
    const loadPeriods = async () => {
      try {
        // First check if there's a configured pay cycle
        const cyclesRes = await apiClient.get<{ items: any[]; total: number }>('/api/v2/pay-cycles/', { signal: controller.signal })
        const cycles = cyclesRes.data?.items ?? []

        // If a cycle exists, try to generate periods from it (idempotent)
        if (cycles.length > 0) {
          const cycleId = cycles[0]?.id
          if (cycleId) {
            try {
              await apiClient.post(`/api/v2/pay-cycles/${cycleId}/generate-periods/`, { count: 8 })
            } catch { /* ignore — already exists or not org_admin */ }
          }
        }

        // Now fetch periods
        const res = await apiClient.get<{ items: any[]; total: number; pay_periods?: any[] }>('/api/v2/pay-periods', { signal: controller.signal })
        const items = res.data?.items ?? res.data?.pay_periods ?? []
        if (Array.isArray(items) && items.length > 0) {
          // Sort by start_date descending (most recent first) and limit to recent 20
          const sorted = [...items]
            .sort((a: any, b: any) => (b?.start_date ?? '').localeCompare(a?.start_date ?? ''))
            .slice(0, 20)
          setPeriods(sorted)
          // Auto-select the period covering today
          const today = new Date().toISOString().split('T')[0]
          const current = sorted.find((p: any) => p?.start_date <= today && p?.end_date >= today)
          if (current) {
            setSelectedPeriod(current.id)
          } else if (sorted[0]) {
            setSelectedPeriod(sorted[0].id)
          }
        }
      } catch { /* ignore */ }
    }
    loadPeriods()
    return () => controller.abort()
  }, [])

  const fetchData = useCallback(async (signal?: AbortSignal) => {
    if (!selectedPeriod || selectedPeriod === 'current' || selectedPeriod === 'previous') {
      // No valid period selected yet
      setLoading(false)
      return
    }
    try {
      setLoading(true)
      const res = await apiClient.get<TimesheetListResponse>('/api/v2/timesheets/', {
        params: { pay_period_id: selectedPeriod },
        signal,
      })
      setData(res.data)
      setError(null)
      // Report period summary up to parent
      if (res.data?.period_summary) {
        onPeriodSummary?.(res.data.period_summary)
      }
    } catch (err: unknown) {
      if (!(err as { name?: string })?.name?.includes('Cancel')) {
        setError('Failed to load timesheets')
      }
    } finally {
      setLoading(false)
    }
  }, [onPeriodSummary])

  useEffect(() => {
    const controller = new AbortController()
    fetchData(controller.signal)
    return () => controller.abort()
  }, [selectedPeriod, fetchData])

  // Row-level action handler
  const handleAction = async (id: string, action: 'submit' | 'approve' | 'reject' | 'lock') => {
    setActionLoading(`${id}-${action}`)
    try {
      await apiClient.post(`/api/v2/timesheets/${id}/${action}/`)
      // Refresh data after action
      fetchData()
    } catch {
      // Could show error toast
    } finally {
      setActionLoading(null)
    }
  }

  // Adjust handler
  const handleAdjust = async () => {
    if (!adjustTarget) return
    setAdjusting(true)
    try {
      await apiClient.put(`/api/v2/timesheets/${adjustTarget.id}/adjust/`, {
        adjusted_minutes: Number(adjustMinutes) || 0,
        notes: adjustNotes,
      })
      setAdjustTarget(null)
      setAdjustMinutes('')
      setAdjustNotes('')
      fetchData()
    } catch {
      // Could show error toast
    } finally {
      setAdjusting(false)
    }
  }

  if (loading && !data) {
    return (
      <div className="animate-pulse space-y-3">
        <div className="h-10 w-64 rounded-lg bg-muted/10" />
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-14 rounded-lg bg-muted/10" />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <div className="rounded-full bg-danger/10 p-3">
          <svg className="h-6 w-6 text-danger" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
          </svg>
        </div>
        <p className="mt-3 text-sm font-medium text-text">{error}</p>
        <button onClick={() => window.location.reload()} className="mt-2 text-sm text-accent hover:underline">Retry</button>
      </div>
    )
  }

  const items = data?.items ?? []
  const total = data?.total ?? 0

  // Apply client-side filters
  const filteredItems = items.filter((ts) => {
    // Search by staff_name
    if (searchQuery && !(ts.staff_name ?? '').toLowerCase().includes(searchQuery.toLowerCase())) {
      return false
    }
    // Status filter
    if (statusFilter !== 'all') {
      const statusMap: Record<string, string> = {
        open: 'open',
        pending: 'pending_approval',
        approved: 'approved',
        locked: 'locked',
      }
      if ((ts.status ?? '') !== statusMap[statusFilter]) return false
    }
    return true
  })

  return (
    <div className="space-y-4">
      {/* Toolbar: Period selector + Bulk actions */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          {/* Pay Period Selector */}
          <select
            value={selectedPeriod}
            onChange={(e) => setSelectedPeriod(e.target.value)}
            className="h-9 rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
          >
            {periods.length === 0 && <option value="">Loading periods...</option>}
            {periods.map((p) => {
              const start = new Date(p.start_date + 'T00:00:00')
              const end = new Date(p.end_date + 'T00:00:00')
              const today = new Date().toISOString().split('T')[0]
              const rel = p.end_date < today ? '' : p.start_date > today ? ' • Upcoming' : ' • This week'
              // ISO week number of the period start.
              const wk = (() => {
                const t = new Date(Date.UTC(start.getFullYear(), start.getMonth(), start.getDate()))
                const dayNr = (t.getUTCDay() + 6) % 7
                t.setUTCDate(t.getUTCDate() - dayNr + 3)
                const firstThu = new Date(Date.UTC(t.getUTCFullYear(), 0, 4))
                const firstDayNr = (firstThu.getUTCDay() + 6) % 7
                firstThu.setUTCDate(firstThu.getUTCDate() - firstDayNr + 3)
                return 1 + Math.round((t.getTime() - firstThu.getTime()) / (7 * 24 * 3600 * 1000))
              })()
              const fmtStart = (d: Date) => d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' })
              const fmtEnd = (d: Date) => d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' })
              return (
                <option key={p.id} value={p.id}>
                  Wk {wk} · {fmtStart(start)} – {fmtEnd(end)}{rel}{p.status !== 'open' ? ` (${p.status})` : ''}
                </option>
              )
            })}
          </select>
          <span className="text-xs text-muted">{total} timesheets</span>
        </div>

        {/* Bulk Actions */}
        <div className="flex items-center gap-2">
          <button className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-text hover:bg-canvas transition-colors">
            <svg className="h-3.5 w-3.5 text-success" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Approve All Clean
          </button>
          <button className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-text hover:bg-canvas transition-colors">
            <svg className="h-3.5 w-3.5 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
            </svg>
            Lock All Approved
          </button>
          <button className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-text hover:bg-canvas transition-colors">
            <svg className="h-3.5 w-3.5 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
            </svg>
            Match All
          </button>
          <button
            onClick={async () => {
              // First materialise missing timesheets for this period, then refresh
              if (selectedPeriod && selectedPeriod !== 'current' && selectedPeriod !== 'previous') {
                try {
                  await apiClient.post(`/api/v2/timesheets/materialise/`, null, {
                    params: { pay_period_id: selectedPeriod },
                  })
                } catch { /* ignore — materialise is best-effort */ }
              }
              fetchData()
            }}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-text hover:bg-canvas transition-colors"
          >
            <svg className="h-3.5 w-3.5 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
            Refresh
          </button>
        </div>
      </div>

      {/* Filters: Search + Status */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[180px] max-w-xs">
          <svg className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by staff name…"
            className="h-9 w-full rounded-lg border border-border bg-canvas pl-9 pr-3 text-sm text-text placeholder:text-muted/50 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="h-9 rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
        >
          <option value="all">All Statuses</option>
          <option value="open">Open</option>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="locked">Locked</option>
        </select>
        {(searchQuery || statusFilter !== 'all') && (
          <span className="text-xs text-muted">{filteredItems.length} of {items.length} shown</span>
        )}
      </div>

      {/* Timesheets table or empty state */}
      {filteredItems.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16">
          <div className="rounded-full bg-muted/10 p-4">
            <svg className="h-8 w-8 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" />
            </svg>
          </div>
          <p className="mt-4 text-sm font-medium text-text">No timesheets for this period</p>
          <p className="mt-1 max-w-sm text-center text-xs text-muted">
            Timesheets are created automatically when staff clock in, get rostered,
            or have approved leave. Select a pay period with activity to see timesheets here.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-border bg-canvas">
                <th className="px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-muted">Staff</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-muted">Status</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium uppercase tracking-wide text-muted">Rostered</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium uppercase tracking-wide text-muted">Actual</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium uppercase tracking-wide text-muted">Variance</th>
                <th className="px-4 py-2.5 text-center text-xs font-medium uppercase tracking-wide text-muted">Flags</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium uppercase tracking-wide text-muted">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filteredItems.map((ts) => (
                <tr key={ts.id} className="hover:bg-muted/5 transition-colors">
                  <td className="px-4 py-3">
                    <p className="font-medium text-text">{ts.staff_name}</p>
                    <p className="text-xs text-muted">{ts.branch_name ?? 'No branch'}</p>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                      ts.status === 'approved' ? 'bg-success/10 text-success' :
                      ts.status === 'locked' ? 'bg-muted/20 text-muted' :
                      ts.status === 'pending_approval' ? 'bg-warning/10 text-warning' :
                      'bg-accent/10 text-accent'
                    }`}>
                      {ts.status?.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-sm">{ts.rostered_hours}h</td>
                  <td className="px-4 py-3 text-right font-mono text-sm">{ts.actual_hours}h</td>
                  <td className={`px-4 py-3 text-right font-mono text-sm ${
                    Number(ts.variance_hours) > 0 ? 'text-success' :
                    Number(ts.variance_hours) < 0 ? 'text-danger' : 'text-muted'
                  }`}>
                    {Number(ts.variance_hours) > 0 ? '+' : ''}{ts.variance_hours}h
                  </td>
                  <td className="px-4 py-3 text-center">
                    {ts.exception_count > 0 ? (
                      <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-warning/10 px-1.5 text-xs font-bold text-warning">
                        {ts.exception_count}
                      </span>
                    ) : (
                      <span className="text-xs text-muted">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      {/* Status-based action buttons */}
                      {ts.status === 'open' && (
                        <button
                          onClick={() => handleAction(ts.id, 'submit')}
                          disabled={actionLoading === `${ts.id}-submit`}
                          className="inline-flex h-7 items-center rounded-lg border border-border bg-card px-2.5 text-xs font-medium text-accent hover:bg-accent/5 transition-colors disabled:opacity-50"
                        >
                          Submit
                        </button>
                      )}
                      {ts.status === 'pending_approval' && (
                        <>
                          <button
                            onClick={() => handleAction(ts.id, 'approve')}
                            disabled={actionLoading === `${ts.id}-approve`}
                            className="inline-flex h-7 items-center rounded-lg border border-border bg-card px-2.5 text-xs font-medium text-success hover:bg-success/5 transition-colors disabled:opacity-50"
                          >
                            Approve
                          </button>
                          <button
                            onClick={() => handleAction(ts.id, 'reject')}
                            disabled={actionLoading === `${ts.id}-reject`}
                            className="inline-flex h-7 items-center rounded-lg border border-border bg-card px-2.5 text-xs font-medium text-danger hover:bg-danger/5 transition-colors disabled:opacity-50"
                          >
                            Reject
                          </button>
                        </>
                      )}
                      {ts.status === 'approved' && (
                        <button
                          onClick={() => handleAction(ts.id, 'lock')}
                          disabled={actionLoading === `${ts.id}-lock`}
                          className="inline-flex h-7 items-center rounded-lg border border-border bg-card px-2.5 text-xs font-medium text-muted hover:bg-muted/10 transition-colors disabled:opacity-50"
                        >
                          Lock
                        </button>
                      )}
                      {ts.status === 'locked' && (
                        <span className="inline-flex h-7 items-center px-2">
                          <svg className="h-4 w-4 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
                          </svg>
                        </span>
                      )}

                      {/* Adjust button for open/pending_approval */}
                      {(ts.status === 'open' || ts.status === 'pending_approval') && (
                        <button
                          onClick={() => {
                            setAdjustTarget(ts)
                            setAdjustMinutes('')
                            setAdjustNotes('')
                          }}
                          className="inline-flex h-7 items-center rounded-lg border border-border bg-card px-2.5 text-xs font-medium text-text hover:bg-canvas transition-colors"
                        >
                          Adjust
                        </button>
                      )}

                      <button className="text-xs text-accent hover:underline ml-1">View</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Adjust modal */}
      {adjustTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50">
          <div className="w-full max-w-sm rounded-card bg-card p-6 shadow-pop">
            <h3 className="text-lg font-semibold text-text">Adjust Timesheet</h3>
            <p className="mt-1 text-sm text-muted">
              {adjustTarget.staff_name} — {adjustTarget.actual_hours}h actual
            </p>

            <div className="mt-4 space-y-3">
              <div>
                <label className="block text-xs font-medium text-muted mb-1">Adjustment (minutes)</label>
                <input
                  type="number"
                  value={adjustMinutes}
                  onChange={(e) => setAdjustMinutes(e.target.value)}
                  placeholder="e.g. 30 or -15"
                  className="h-10 w-full rounded-lg border border-border bg-canvas px-3 text-sm text-text placeholder:text-muted/50 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-muted mb-1">Notes</label>
                <textarea
                  value={adjustNotes}
                  onChange={(e) => setAdjustNotes(e.target.value)}
                  placeholder="Reason for adjustment…"
                  rows={3}
                  className="w-full rounded-lg border border-border bg-canvas px-3 py-2 text-sm text-text placeholder:text-muted/50 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 resize-none"
                />
              </div>
            </div>

            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                onClick={() => setAdjustTarget(null)}
                disabled={adjusting}
                className="inline-flex h-10 items-center rounded-lg border border-border bg-card px-4 text-sm font-medium text-text hover:bg-canvas transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleAdjust}
                disabled={adjusting || !adjustMinutes}
                className="inline-flex h-10 items-center rounded-lg bg-accent px-4 text-sm font-medium text-white hover:bg-accent/90 transition-colors disabled:opacity-50"
              >
                {adjusting ? 'Saving…' : 'Save Adjustment'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
