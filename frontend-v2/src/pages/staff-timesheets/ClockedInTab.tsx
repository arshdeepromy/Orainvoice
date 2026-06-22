import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'
import { useBranch } from '@/contexts/BranchContext'
import type { ClockedInResponse, ClockedInEntry } from './types'

export default function ClockedInTab() {
  const [data, setData] = useState<ClockedInResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date())

  // Branch filter (local to this tab)
  const { branches } = useBranch()
  const [filterBranch, setFilterBranch] = useState<string>('all')

  // Clock-out confirmation modal state
  const [clockOutTarget, setClockOutTarget] = useState<ClockedInEntry | null>(null)
  const [clockingOut, setClockingOut] = useState(false)
  const [reasonNote, setReasonNote] = useState('')
  const [clockOutError, setClockOutError] = useState<string | null>(null)

  // Collapsible sections state
  const [showOnLeave, setShowOnLeave] = useState(true)
  const [showRosterGaps, setShowRosterGaps] = useState(true)

  const fetchData = useCallback(async (signal?: AbortSignal) => {
    try {
      setLoading(true)
      // Use the EXISTING time-clock endpoint that returns real data
      // from time_clock_entries WHERE clock_out_at IS NULL
      const res = await apiClient.get<{ items: any[]; total: number }>('/api/v2/time-clock/clocked-in', {
        signal,
      })
      // Map the time-clock response shape to our ClockedInEntry type
      const rawItems = res.data?.items ?? []
      const mapped: ClockedInEntry[] = rawItems.map((item: any) => {
        const clockInAt = item?.clock_in_at ?? ''
        const elapsedMs = clockInAt ? Date.now() - new Date(clockInAt).getTime() : 0
        return {
          id: item?.time_clock_entry_id ?? item?.id ?? '',
          staff_id: item?.staff_id ?? '',
          staff_name: item?.staff_name ?? '',
          position: item?.position ?? null,
          clock_in_at: clockInAt,
          elapsed_minutes: Math.floor(elapsedMs / 60000),
          on_break: (item?.break_minutes ?? 0) > 0,
          break_started_at: null,
          clock_in_branch_name: item?.branch_name ?? item?.clock_in_branch_name ?? 'Main',
          clock_out_branch_name: null,
          source: item?.source ?? '',
          clock_in_ip: item?.clock_in_ip ?? null,
          rostered_start: null,
          punctuality: null,
        }
      })
      setData({ items: mapped, total: res.data?.total ?? mapped.length })
      setError(null)
      setLastRefresh(new Date())
    } catch (err: unknown) {
      if (!(err as { name?: string })?.name?.includes('Cancel')) {
        setError('Failed to load clocked-in data')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchData(controller.signal)
    // Auto-refresh every 30s
    const interval = setInterval(() => fetchData(), 30000)
    return () => {
      controller.abort()
      clearInterval(interval)
    }
  }, [fetchData])

  const handleClockOut = async () => {
    if (!clockOutTarget) return
    const trimmed = reasonNote.trim()
    if (trimmed.length < 3) {
      setClockOutError('Please enter a reason note (at least 3 characters).')
      return
    }
    setClockingOut(true)
    setClockOutError(null)
    try {
      // Use the existing time-clock admin clock-out endpoint. The reason
      // note is required (3..500) and is recorded on the audit log.
      await apiClient.post(`/api/v2/time-clock/admin-clock-out/${clockOutTarget.id}`, {
        reason_note: trimmed,
      })
      setClockOutTarget(null)
      setReasonNote('')
      // Refresh the list so the closed row drops off.
      fetchData()
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      const rawDetail = (err as {
        response?: { data?: { detail?: { detail?: string } | string } }
      })?.response?.data?.detail
      const detailStr =
        typeof rawDetail === 'string' ? rawDetail : rawDetail?.detail ?? ''
      if (status === 403 && detailStr === 'forbidden_scope') {
        setClockOutError(
          "This staff member is outside your branch scope — you can't clock them out.",
        )
      } else if (status === 409 && detailStr === 'already_clocked_out') {
        setClockOutError('This entry was already clocked out by someone else.')
      } else if (status === 409 && detailStr === 'timesheet_locked') {
        setClockOutError(
          "Can't close — this shift's week is already approved. Reopen the timesheet first.",
        )
      } else if (status === 404 || detailStr === 'time_clock_entry_not_found') {
        setClockOutError('That entry could not be found. It may have been deleted.')
      } else {
        setClockOutError("Couldn't clock the user out. Please try again.")
      }
    } finally {
      setClockingOut(false)
    }
  }

  if (loading && !data) {
    return (
      <div className="animate-pulse space-y-3">
        {[1, 2, 3].map((i) => (
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
        <button
          onClick={() => window.location.reload()}
          className="mt-2 text-sm text-accent hover:underline"
        >
          Retry
        </button>
      </div>
    )
  }

  const allItems = data?.items ?? []
  const total = data?.total ?? 0

  // Apply branch filter client-side
  const items = filterBranch === 'all'
    ? allItems
    : allItems.filter((entry) => entry.clock_in_branch_name === filterBranch)

  if (allItems.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <div className="rounded-full bg-muted/10 p-4">
          <svg className="h-8 w-8 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <p className="mt-4 text-sm font-medium text-text">No staff currently clocked in</p>
        <p className="mt-1 text-xs text-muted">
          Staff will appear here when they clock in via kiosk or self-service
        </p>
        <p className="mt-4 text-[11px] text-muted/60">
          Auto-refreshes every 30 seconds • Last checked {lastRefresh.toLocaleTimeString()}
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="inline-flex h-7 min-w-[28px] items-center justify-center rounded-full bg-accent/10 px-2 text-xs font-bold text-accent">
            {total}
          </span>
          <span className="text-sm text-muted">staff clocked in</span>
        </div>

        <div className="flex items-center gap-3">
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

          <p className="text-[11px] text-muted/60">
            Auto-refreshes • {lastRefresh.toLocaleTimeString()}
          </p>
        </div>
      </div>

      <div className="divide-y divide-border overflow-hidden rounded-lg border border-border">
        {items.map((entry) => (
          <div key={entry.id} className="flex items-center justify-between px-4 py-3 hover:bg-muted/5 transition-colors">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/10 text-xs font-bold text-accent">
                {entry.staff_name?.charAt(0) ?? '?'}
              </div>
              <div>
                <p className="text-sm font-medium text-text">{entry.staff_name}</p>
                <p className="text-xs text-muted">
                  {entry.position ?? 'Staff'} • {entry.clock_in_branch_name}
                </p>
                <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-muted/70">
                  {entry.clock_in_at && (
                    <span>In: {new Date(entry.clock_in_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                  )}
                  {entry.clock_in_ip && (
                    <span>• IP: {entry.clock_in_ip}</span>
                  )}
                  {entry.rostered_start && (
                    <span>• Rostered: {new Date(entry.rostered_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                  )}
                  {entry.punctuality && (
                    <span className={`font-medium ${
                      entry.punctuality === 'on_time' ? 'text-success' :
                      entry.punctuality === 'late' ? 'text-danger' :
                      'text-warning'
                    }`}>
                      • {entry.punctuality.replace('_', ' ')}
                    </span>
                  )}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {entry.on_break && (
                <span className="inline-flex items-center rounded-full bg-warning/10 px-2 py-0.5 text-[10px] font-bold text-warning">
                  ON BREAK
                </span>
              )}
              <div className="text-right">
                <p className="text-sm font-mono font-medium text-text">
                  {Math.floor(entry.elapsed_minutes / 60)}h {entry.elapsed_minutes % 60}m
                </p>
                <p className="text-xs text-muted capitalize">{entry.source?.replace(/_/g, ' ')}</p>
              </div>
              <button
                onClick={() => {
                  setClockOutTarget(entry)
                  setReasonNote('')
                  setClockOutError(null)
                }}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-danger hover:bg-danger/5 transition-colors"
              >
                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
                </svg>
                Clock Out
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* On Leave Today — collapsible section */}
      <div className="rounded-lg border border-border overflow-hidden">
        <button
          onClick={() => setShowOnLeave(!showOnLeave)}
          className="flex w-full items-center justify-between px-4 py-3 bg-canvas hover:bg-muted/5 transition-colors"
        >
          <div className="flex items-center gap-2">
            <svg className="h-4 w-4 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
            </svg>
            <span className="text-sm font-medium text-text">On Leave Today</span>
          </div>
          <svg className={`h-4 w-4 text-muted transition-transform ${showOnLeave ? 'rotate-180' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        {showOnLeave && (
          <div className="border-t border-border px-4 py-6 text-center">
            <p className="text-sm text-muted">No staff on leave today</p>
          </div>
        )}
      </div>

      {/* Rostered Not Clocked In — collapsible section */}
      <div className="rounded-lg border border-border overflow-hidden">
        <button
          onClick={() => setShowRosterGaps(!showRosterGaps)}
          className="flex w-full items-center justify-between px-4 py-3 bg-canvas hover:bg-muted/5 transition-colors"
        >
          <div className="flex items-center gap-2">
            <svg className="h-4 w-4 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
            <span className="text-sm font-medium text-text">Rostered Not Clocked In</span>
          </div>
          <svg className={`h-4 w-4 text-muted transition-transform ${showRosterGaps ? 'rotate-180' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        {showRosterGaps && (
          <div className="border-t border-border px-4 py-6 text-center">
            <p className="text-sm text-muted">No roster gaps detected</p>
          </div>
        )}
      </div>

      {/* Clock-out confirmation modal */}
      {clockOutTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50">
          <div className="w-full max-w-sm rounded-card bg-card p-6 shadow-pop">
            <h3 className="text-lg font-semibold text-text">Confirm Clock Out</h3>
            <p className="mt-2 text-sm text-muted">
              Clock out <span className="font-medium text-text">{clockOutTarget.staff_name}</span>?
            </p>
            <p className="mt-1 text-xs text-muted">
              They have been clocked in for {clockOutTarget.elapsed_minutes} minutes.
            </p>

            <div className="mt-4">
              <label
                htmlFor="clockout-reason-note"
                className="mb-1 block text-xs font-medium text-text"
              >
                Reason note <span className="text-danger">*</span>
              </label>
              <textarea
                id="clockout-reason-note"
                value={reasonNote}
                onChange={(e) => setReasonNote(e.target.value)}
                rows={3}
                maxLength={500}
                placeholder="e.g. Forgot to tap out at end of shift"
                className="w-full rounded-lg border border-border bg-canvas px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
                autoFocus
              />
              <p className="mt-1 text-[11px] text-muted">
                {reasonNote.trim().length}/500 — minimum 3 characters
              </p>
            </div>

            {clockOutError && (
              <div
                role="alert"
                className="mt-3 rounded-lg bg-danger/10 px-3 py-2 text-sm font-medium text-danger"
              >
                {clockOutError}
              </div>
            )}

            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                onClick={() => {
                  setClockOutTarget(null)
                  setReasonNote('')
                  setClockOutError(null)
                }}
                disabled={clockingOut}
                className="inline-flex h-10 items-center rounded-lg border border-border bg-card px-4 text-sm font-medium text-text hover:bg-canvas transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleClockOut}
                disabled={clockingOut || reasonNote.trim().length < 3}
                className="inline-flex h-10 items-center rounded-lg bg-danger px-4 text-sm font-medium text-white hover:bg-danger/90 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
              >
                {clockingOut ? 'Clocking out…' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
