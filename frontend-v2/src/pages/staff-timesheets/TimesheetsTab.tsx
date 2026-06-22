import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'
import type {
  TimesheetListResponse,
  TimesheetSummary,
  PeriodSummary,
  TimesheetDetail,
  WeeklyBreakdownResponse,
} from './types'
import WeeklyBreakdownView from './WeeklyBreakdownView'
import {
  CycleBoxes,
  PeriodStepper,
  activeCyclesOf,
  defaultCycleId,
  periodsForCycle,
  pickDefaultPeriodId,
  type CycleLike,
  type PeriodLike,
} from './CyclePeriodControls'

interface TimesheetsTabProps {
  onPeriodSummary?: (summary: PeriodSummary) => void
}

/**
 * Monday (ISO date) of the week containing `iso`. Used to decide whether a
 * period spans more than one ISO week (Mon–Sun) — i.e. its start and end fall
 * in different Monday-anchored weeks. Mirrors the backend's Monday-anchored
 * week bucketing for the weekly-breakdown review aid.
 */
function mondayOf(iso: string): string {
  const d = new Date(iso + 'T00:00:00')
  const dayNr = (d.getDay() + 6) % 7 // Mon = 0 … Sun = 6
  d.setDate(d.getDate() - dayNr)
  return d.toISOString().split('T')[0]
}

export default function TimesheetsTab({ onPeriodSummary }: TimesheetsTabProps) {
  const [data, setData] = useState<TimesheetListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // The selected period is always a real id (or '' before anything loads); the
  // cycle-first control derives a smart default per cycle.
  const [selectedPeriod, setSelectedPeriod] = useState<string>('')
  const [selectedCycleId, setSelectedCycleId] = useState<string>('')

  // Filter state
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')

  // Action loading state (per row)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  // Toolbar (bulk) action state
  const [bulkBusy, setBulkBusy] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const flash = (kind: 'success' | 'error', text: string) => {
    setFeedback({ kind, text })
    setTimeout(() => setFeedback(null), 5000)
  }

  // Adjust modal state
  const [adjustTarget, setAdjustTarget] = useState<TimesheetSummary | null>(null)
  const [adjustMinutes, setAdjustMinutes] = useState<string>('')
  const [adjustNotes, setAdjustNotes] = useState<string>('')
  const [adjusting, setAdjusting] = useState(false)

  // View (detail) modal state
  const [viewId, setViewId] = useState<string | null>(null)
  const [viewData, setViewData] = useState<TimesheetDetail | null>(null)
  const [viewLoading, setViewLoading] = useState(false)

  // Weekly-lens view state (READ-ONLY review aid). Only offered when the
  // selected period spans more than one ISO week (fortnightly / monthly).
  const [viewMode, setViewMode] = useState<'period' | 'weekly'>('period')
  const [weeklyData, setWeeklyData] = useState<WeeklyBreakdownResponse | null>(null)
  const [weeklyLoading, setWeeklyLoading] = useState(false)

  const openView = async (id: string) => {
    setViewId(id)
    setViewData(null)
    setViewLoading(true)
    try {
      const res = await apiClient.get<TimesheetDetail>(`/api/v2/timesheets/${id}`)
      setViewData(res.data ?? null)
    } catch {
      setViewData(null)
    } finally {
      setViewLoading(false)
    }
  }

  // Fetch available pay cycles + periods
  const [cycles, setCycles] = useState<CycleLike[]>([])
  const [periods, setPeriods] = useState<PeriodLike[]>([])

  useEffect(() => {
    const controller = new AbortController()
    const loadPeriods = async () => {
      try {
        // Fetch the organisation's pay cycles. Multiple active cycles can run
        // at once (e.g. weekly for casual staff, fortnightly for permanent).
        const cyclesRes = await apiClient.get<{ items: CycleLike[]; total: number }>('/api/v2/pay-cycles/', { signal: controller.signal })
        const loadedCycles = cyclesRes.data?.items ?? []
        // Active cycles only — generate a period schedule for every one of them
        // so periods exist for each cycle the org runs (REQ 8.1).
        const activeCycles = activeCyclesOf(loadedCycles)

        // Generate periods for ALL active cycles (idempotent). Run in parallel;
        // each call is independent and failures (already-exists / not org_admin)
        // are ignored per cycle.
        await Promise.all(
          activeCycles.map(async (cycle) => {
            const cycleId = cycle?.id
            if (!cycleId) return
            try {
              await apiClient.post(`/api/v2/pay-cycles/${cycleId}/generate-periods/`, { count: 8 }, { signal: controller.signal })
            } catch { /* ignore — already exists or not org_admin */ }
          }),
        )

        // Now fetch periods
        const res = await apiClient.get<{ items: PeriodLike[]; total: number; pay_periods?: PeriodLike[] }>('/api/v2/pay-periods', { signal: controller.signal })
        const allItems = res.data?.items ?? res.data?.pay_periods ?? []
        setCycles(loadedCycles)
        if (Array.isArray(allItems) && allItems.length > 0) {
          // Sort by start_date descending (most recent first).
          const sortedAll = [...allItems]
            .sort((a, b) => (b?.start_date ?? '').localeCompare(a?.start_date ?? ''))
          // Source of truth: when pay cycles are configured, the cycle-managed
          // periods (those carrying a pay_cycle_id) take precedence — this keeps
          // the Timesheets tab aligned with the Pay Runs tab and avoids showing
          // stale/orphan periods from a previous cycle. Fall back to all periods
          // only when no cycle-managed periods exist yet.
          const cycleManaged = sortedAll.filter((p) => !!p?.pay_cycle_id)
          const sorted = (activeCycles.length > 0 && cycleManaged.length > 0 ? cycleManaged : sortedAll).slice(0, 40)
          setPeriods(sorted)
          // Default the cycle to the org default (else first active), then pick
          // the smart default period within that cycle (most recently completed).
          const cycleId = defaultCycleId(loadedCycles)
          setSelectedCycleId(cycleId)
          const scoped = cycleId ? periodsForCycle(sorted, cycleId) : sorted
          setSelectedPeriod(pickDefaultPeriodId(scoped.length > 0 ? scoped : sorted))
        }
      } catch { /* ignore */ }
    }
    loadPeriods()
    return () => controller.abort()
  }, [])

  // Switching cycle re-scopes the period list and re-defaults the period.
  const handleSelectCycle = useCallback((cycleId: string) => {
    setSelectedCycleId(cycleId)
    setSelectedPeriod(pickDefaultPeriodId(periodsForCycle(periods, cycleId)))
  }, [periods])

  const cyclePeriods = periodsForCycle(periods, selectedCycleId)

  const fetchData = useCallback(async (signal?: AbortSignal) => {
    if (!selectedPeriod) {
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
  }, [selectedPeriod, onPeriodSummary])

  useEffect(() => {
    const controller = new AbortController()
    fetchData(controller.signal)
    return () => controller.abort()
  }, [selectedPeriod, fetchData])

  // Whether the selected period spans more than one ISO week (Mon–Sun). The
  // weekly-lens toggle only appears for multi-week periods.
  const selectedPeriodObj = periods.find((p) => p?.id === selectedPeriod) ?? null
  const isMultiWeek = !!(
    selectedPeriodObj?.start_date &&
    selectedPeriodObj?.end_date &&
    mondayOf(selectedPeriodObj.start_date) !== mondayOf(selectedPeriodObj.end_date)
  )
  // Effective view: only show weekly when the period actually supports it.
  const showWeekly = isMultiWeek && viewMode === 'weekly'

  // Fetch the weekly breakdown when the weekly lens is active for a period.
  useEffect(() => {
    if (!showWeekly || !selectedPeriod) return
    const controller = new AbortController()
    const loadWeekly = async () => {
      setWeeklyLoading(true)
      try {
        const res = await apiClient.get<WeeklyBreakdownResponse>('/api/v2/timesheets/weekly-breakdown', {
          params: { pay_period_id: selectedPeriod },
          signal: controller.signal,
        })
        setWeeklyData(res.data ?? null)
      } catch (err: unknown) {
        if (!(err as { name?: string })?.name?.includes('Cancel')) {
          setWeeklyData(null)
        }
      } finally {
        setWeeklyLoading(false)
      }
    }
    loadWeekly()
    return () => controller.abort()
  }, [showWeekly, selectedPeriod])

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

  // Toolbar bulk-action handlers ------------------------------------------
  const periodReady = !!selectedPeriod

  const handleGenerate = async () => {
    if (!periodReady) {
      flash('error', 'Select a pay period first')
      return
    }
    setBulkBusy('generate')
    try {
      const res = await apiClient.post<{ created_count: number }>(
        '/api/v2/timesheets/materialise/',
        null,
        { params: { pay_period_id: selectedPeriod, include_all_active: true } },
      )
      const created = res.data?.created_count ?? 0
      flash(
        'success',
        created > 0
          ? `Generated ${created} timesheet${created === 1 ? '' : 's'} for staff in this period`
          : 'All active staff already have a timesheet for this period',
      )
      await fetchData()
    } catch {
      flash('error', 'Failed to generate timesheets')
    } finally {
      setBulkBusy(null)
    }
  }

  const handleApproveAll = async () => {
    if (!periodReady) return
    setBulkBusy('approve')
    try {
      const res = await apiClient.post<{ affected_count: number; skipped_count: number }>(
        '/api/v2/timesheets/bulk-approve',
        null,
        { params: { pay_period_id: selectedPeriod } },
      )
      const { affected_count = 0, skipped_count = 0 } = res.data ?? {}
      flash('success', `Approved ${affected_count} timesheet(s)${skipped_count ? `, skipped ${skipped_count}` : ''}`)
      await fetchData()
    } catch {
      flash('error', 'Failed to approve timesheets')
    } finally {
      setBulkBusy(null)
    }
  }

  const handleLockAll = async () => {
    if (!periodReady) return
    setBulkBusy('lock')
    try {
      const res = await apiClient.post<{ affected_count: number; skipped_count: number }>(
        '/api/v2/timesheets/bulk-lock',
        null,
        { params: { pay_period_id: selectedPeriod } },
      )
      const { affected_count = 0 } = res.data ?? {}
      flash('success', `Locked ${affected_count} approved timesheet(s)`)
      await fetchData()
    } catch {
      flash('error', 'Failed to lock timesheets')
    } finally {
      setBulkBusy(null)
    }
  }

  const handleMatchAll = async () => {
    if (!periodReady) return
    setBulkBusy('match')
    try {
      await apiClient.post('/api/v2/timesheets/match-all', null, {
        params: { pay_period_id: selectedPeriod },
      })
      flash('success', 'Re-matched clock entries for this period')
      await fetchData()
    } catch {
      flash('error', 'Failed to match entries')
    } finally {
      setBulkBusy(null)
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
      {/* Cycle-first period filter */}
      <div className="space-y-3">
        {activeCyclesOf(cycles).length === 0 ? (
          <p className="text-sm text-muted">No active pay cycles — configure one in the Settings tab.</p>
        ) : (
          <CycleBoxes
            cycles={cycles}
            periods={periods}
            selectedCycleId={selectedCycleId}
            onSelect={handleSelectCycle}
          />
        )}
      </div>

      {/* Toolbar: Period stepper + Bulk actions */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <PeriodStepper
            cyclePeriods={cyclePeriods}
            selectedPeriod={selectedPeriod}
            onChange={setSelectedPeriod}
          />
          <span className="text-xs text-muted">{total} timesheets</span>
          {/* Weekly-lens toggle — only for periods spanning >1 ISO week. */}
          {isMultiWeek && (
            <div
              className="inline-flex rounded-lg border border-border bg-card p-0.5"
              role="group"
              aria-label="Timesheet view"
            >
              <button
                type="button"
                onClick={() => setViewMode('period')}
                aria-pressed={viewMode === 'period'}
                className={`inline-flex h-7 items-center rounded-md px-2.5 text-xs font-medium transition-colors ${
                  viewMode === 'period' ? 'bg-accent text-white' : 'text-muted hover:text-text'
                }`}
              >
                Period total
              </button>
              <button
                type="button"
                onClick={() => setViewMode('weekly')}
                aria-pressed={viewMode === 'weekly'}
                className={`inline-flex h-7 items-center rounded-md px-2.5 text-xs font-medium transition-colors ${
                  viewMode === 'weekly' ? 'bg-accent text-white' : 'text-muted hover:text-text'
                }`}
              >
                Weekly
              </button>
            </div>
          )}
        </div>

        {/* Bulk Actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={handleGenerate}
            disabled={!periodReady || bulkBusy !== null}
            title="Create timesheets for all active staff in this period (fixed, rostered, or casual)"
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-accent px-3 text-xs font-medium text-white hover:bg-accent/90 transition-colors disabled:opacity-50"
          >
            {bulkBusy === 'generate' ? (
              <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
            )}
            Generate Timesheets
          </button>
          <button
            onClick={handleApproveAll}
            disabled={!periodReady || bulkBusy !== null}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-text hover:bg-canvas transition-colors disabled:opacity-50"
          >
            <svg className="h-3.5 w-3.5 text-success" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Approve All Clean
          </button>
          <button
            onClick={handleLockAll}
            disabled={!periodReady || bulkBusy !== null}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-text hover:bg-canvas transition-colors disabled:opacity-50"
          >
            <svg className="h-3.5 w-3.5 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
            </svg>
            Lock All Approved
          </button>
          <button
            onClick={handleMatchAll}
            disabled={!periodReady || bulkBusy !== null}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-text hover:bg-canvas transition-colors disabled:opacity-50"
          >
            <svg className="h-3.5 w-3.5 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
            </svg>
            Match All
          </button>
          <button
            onClick={async () => {
              // Refresh: re-run the automatic (non-manual) materialise sweep
              // for clock + fixed staff, then reload.
              if (periodReady) {
                try {
                  await apiClient.post(`/api/v2/timesheets/materialise/`, null, {
                    params: { pay_period_id: selectedPeriod },
                  })
                } catch { /* ignore — materialise is best-effort */ }
              }
              fetchData()
            }}
            disabled={bulkBusy !== null}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-text hover:bg-canvas transition-colors disabled:opacity-50"
          >
            <svg className="h-3.5 w-3.5 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
            Refresh
          </button>
        </div>
      </div>

      {/* Feedback banner */}
      {feedback && (
        <div
          className={`rounded-lg px-4 py-2.5 text-sm font-medium ${
            feedback.kind === 'success'
              ? 'border border-success/20 bg-success/5 text-success'
              : 'border border-danger/20 bg-danger/5 text-danger'
          }`}
        >
          {feedback.text}
        </div>
      )}

      {/* Filters: Search + Status (period-total view only) */}
      {showWeekly ? (
        <WeeklyBreakdownView data={weeklyData} loading={weeklyLoading} />
      ) : (
        <>
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
            or have approved leave. For fixed, rostered, or casual staff who don&apos;t
            clock in, use <span className="font-medium text-text">Generate Timesheets</span> above
            to create them for everyone in this period.
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

                      <button
                        onClick={() => openView(ts.id)}
                        className="text-xs text-accent hover:underline ml-1"
                      >
                        View
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
        </>
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

      {/* View (detail) modal */}
      {viewId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 p-4" onClick={() => setViewId(null)}>
          <div className="w-full max-w-lg rounded-card bg-card p-6 shadow-pop" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-lg font-semibold text-text">Timesheet Detail</h3>
                {viewData && (
                  <p className="mt-0.5 text-sm text-muted">
                    {viewData.staff_name}
                    {viewData.period_start && ` · ${viewData.period_start} – ${viewData.period_end}`}
                  </p>
                )}
              </div>
              <button
                onClick={() => setViewId(null)}
                className="rounded-lg p-1 text-muted hover:bg-canvas hover:text-text transition-colors"
                aria-label="Close"
              >
                <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {viewLoading ? (
              <div className="mt-6 space-y-3 animate-pulse">
                <div className="h-5 w-40 rounded bg-muted/10" />
                <div className="h-20 rounded bg-muted/10" />
              </div>
            ) : !viewData ? (
              <p className="mt-6 text-sm text-muted">Failed to load timesheet detail.</p>
            ) : (
              <div className="mt-4 space-y-4">
                {/* Status + hour summary */}
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                    viewData.status === 'approved' ? 'bg-success/10 text-success' :
                    viewData.status === 'locked' ? 'bg-muted/20 text-muted' :
                    viewData.status === 'pending_approval' ? 'bg-warning/10 text-warning' :
                    'bg-accent/10 text-accent'
                  }`}>
                    {viewData.status?.replace(/_/g, ' ')}
                  </span>
                  {viewData.branch_name && <span className="text-xs text-muted">{viewData.branch_name}</span>}
                </div>

                <div className="grid grid-cols-3 gap-3">
                  {[
                    ['Rostered', viewData.rostered_minutes],
                    ['Actual', viewData.actual_minutes],
                    ['Ordinary', viewData.ordinary_minutes],
                    ['Overtime', viewData.overtime_minutes],
                    ['Public Hol.', viewData.public_holiday_minutes],
                    ['Adjusted', viewData.adjusted_minutes ?? 0],
                  ].map(([label, mins]) => (
                    <div key={label as string} className="rounded-lg bg-canvas p-3 text-center">
                      <p className="text-sm font-semibold text-text">{((Number(mins) || 0) / 60).toFixed(2)}h</p>
                      <p className="text-xs text-muted">{label as string}</p>
                    </div>
                  ))}
                </div>

                {viewData.notes && (
                  <div className="rounded-lg border border-border p-3">
                    <p className="text-xs font-medium text-muted">Notes</p>
                    <p className="mt-0.5 text-sm text-text">{viewData.notes}</p>
                  </div>
                )}

                {/* Approval / lock trail */}
                {(viewData.approved_by_name || viewData.locked_by_name) && (
                  <div className="space-y-1 text-xs text-muted">
                    {viewData.approved_by_name && (
                      <p>Approved by {viewData.approved_by_name}{viewData.approved_at ? ` on ${new Date(viewData.approved_at).toLocaleString('en-NZ')}` : ''}</p>
                    )}
                    {viewData.locked_by_name && (
                      <p>Locked by {viewData.locked_by_name}{viewData.locked_at ? ` on ${new Date(viewData.locked_at).toLocaleString('en-NZ')}` : ''}</p>
                    )}
                  </div>
                )}

                {/* Clock entries */}
                <div>
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                    Clock Entries ({viewData.entries.length})
                  </p>
                  {viewData.entries.length === 0 ? (
                    <p className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-muted">
                      No clock entries — hours come from the staff member&apos;s configured schedule.
                    </p>
                  ) : (
                    <div className="max-h-48 space-y-1.5 overflow-y-auto">
                      {viewData.entries.map((e) => (
                        <div key={e.id} className="flex items-center justify-between rounded-lg border border-border p-2.5 text-xs">
                          <span className="text-text">
                            {new Date(e.clock_in_at).toLocaleString('en-NZ', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
                            {' → '}
                            {e.clock_out_at ? new Date(e.clock_out_at).toLocaleTimeString('en-NZ', { hour: '2-digit', minute: '2-digit' }) : '—'}
                          </span>
                          <span className="font-mono text-muted">
                            {e.worked_minutes != null ? `${(e.worked_minutes / 60).toFixed(2)}h` : '—'}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="flex justify-end">
                  <button
                    onClick={() => setViewId(null)}
                    className="inline-flex h-10 items-center rounded-lg bg-accent px-4 text-sm font-medium text-white hover:bg-accent/90 transition-colors"
                  >
                    Close
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
