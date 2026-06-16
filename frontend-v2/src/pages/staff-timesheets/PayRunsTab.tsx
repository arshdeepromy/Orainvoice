import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/api/client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PayCycle {
  id: string
  name: string
  frequency: string
  anchor_date: string
  pay_date_offset_days: number
  is_default: boolean
}

interface PayPeriod {
  id: string
  start_date: string
  end_date: string
  pay_date?: string
  status: string
  pay_cycle_id?: string | null
}

interface GeneratedPeriod {
  id: string
  start_date: string
  end_date: string
  pay_date: string
}

interface TimesheetRow {
  id: string
  staff_name: string
  status: string
  actual_hours: number
}

interface PeriodSummary {
  total_staff: number
  approved_count: number
  pending_count: number
  locked_count: number
}

interface Adjustment {
  id: string
  original_timesheet_id: string
  adjustment_minutes: number
  reason: string
  category: string
  created_at: string | null
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const fmtDate = (iso: string) => {
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' })
}

const fmtDateLong = (iso: string) => {
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' })
}

/** ISO 8601 week number (weeks start Monday; week 1 contains the first Thursday). */
const isoWeek = (iso: string): number => {
  const d = new Date(iso + 'T00:00:00')
  // Shift to Thursday of the current week, then count weeks from Jan 1.
  const target = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
  const dayNr = (target.getUTCDay() + 6) % 7 // Mon=0 … Sun=6
  target.setUTCDate(target.getUTCDate() - dayNr + 3)
  const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4))
  const firstDayNr = (firstThursday.getUTCDay() + 6) % 7
  firstThursday.setUTCDate(firstThursday.getUTCDate() - firstDayNr + 3)
  return 1 + Math.round((target.getTime() - firstThursday.getTime()) / (7 * 24 * 3600 * 1000))
}

type PeriodRelative = 'current' | 'past' | 'future'

const periodRelative = (p: PayPeriod): PeriodRelative => {
  const today = new Date().toISOString().split('T')[0]
  if (p.end_date < today) return 'past'
  if (p.start_date > today) return 'future'
  return 'current'
}

/** Builds a rich label: "Wk 24 · 8 – 21 Jun 2026". */
const fmtPeriodLabel = (p: PayPeriod): string => {
  const startD = new Date(p.start_date + 'T00:00:00')
  const endD = new Date(p.end_date + 'T00:00:00')
  const sameMonth = startD.getMonth() === endD.getMonth() && startD.getFullYear() === endD.getFullYear()
  const sameYear = startD.getFullYear() === endD.getFullYear()
  const startLabel = sameMonth
    ? startD.toLocaleDateString('en-NZ', { day: 'numeric' })
    : sameYear
      ? startD.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' })
      : startD.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' })
  const endLabel = endD.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' })
  const rel = periodRelative(p)
  const relTag = rel === 'current' ? ' • This week' : ''
  const statusTag = p.status !== 'open' ? ` (${p.status})` : ''
  return `Wk ${isoWeek(p.start_date)} · ${startLabel} – ${endLabel}${relTag}${statusTag}`
}

const fmtMinutes = (mins: number) => {
  const sign = mins < 0 ? '-' : '+'
  const abs = Math.abs(mins)
  const h = Math.floor(abs / 60)
  const m = abs % 60
  if (h === 0) return `${sign}${m}m`
  if (m === 0) return `${sign}${h}h`
  return `${sign}${h}h ${m}m`
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PayRunsTab() {
  const [cycles, setCycles] = useState<PayCycle[]>([])
  const [periods, setPeriods] = useState<PayPeriod[]>([])
  const [selectedPeriod, setSelectedPeriod] = useState<string>('')
  const [summary, setSummary] = useState<PeriodSummary | null>(null)
  const [timesheets, setTimesheets] = useState<TimesheetRow[]>([])
  const [adjustments, setAdjustments] = useState<Adjustment[]>([])

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)

  const [generatingRun, setGeneratingRun] = useState(false)
  const [generatingPeriods, setGeneratingPeriods] = useState(false)
  const [previewPeriods, setPreviewPeriods] = useState<GeneratedPeriod[] | null>(null)

  // Adjustment modal
  const [showAdjustModal, setShowAdjustModal] = useState(false)
  const [adjStaffTimesheet, setAdjStaffTimesheet] = useState('')
  const [adjMinutes, setAdjMinutes] = useState('')
  const [adjReason, setAdjReason] = useState('')
  const [adjCategory, setAdjCategory] = useState('correction')
  const [savingAdjustment, setSavingAdjustment] = useState(false)

  const flash = (kind: 'success' | 'error', text: string) => {
    setFeedback({ kind, text })
    setTimeout(() => setFeedback(null), 5000)
  }

  // --- Initial load: cycles + periods -------------------------------------
  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        setLoading(true)
        const [cyclesRes, periodsRes] = await Promise.all([
          apiClient.get<{ items: PayCycle[]; total: number }>('/api/v2/pay-cycles/', { signal: controller.signal }),
          apiClient.get<{ items: PayPeriod[]; total: number }>('/api/v2/pay-periods', {
            params: { limit: 50 },
            signal: controller.signal,
          }),
        ])
        const loadedCycles = cyclesRes.data?.items ?? []
        const allPeriods = (periodsRes.data?.items ?? [])
          .slice()
          .sort((a, b) => (b?.start_date ?? '').localeCompare(a?.start_date ?? ''))
        // Source of truth: when a pay cycle is configured, the Timesheets-managed
        // periods (those carrying a pay_cycle_id) take precedence. Fall back to all
        // periods only if no cycle-managed periods exist yet.
        const cycleManaged = allPeriods.filter((p) => !!p.pay_cycle_id)
        const loadedPeriods = loadedCycles.length > 0 && cycleManaged.length > 0 ? cycleManaged : allPeriods
        setCycles(loadedCycles)
        setPeriods(loadedPeriods)

        // Auto-select the period covering today, else most recent
        const today = new Date().toISOString().split('T')[0]
        const current = loadedPeriods.find((p) => p.start_date <= today && p.end_date >= today)
        setSelectedPeriod(current?.id ?? loadedPeriods[0]?.id ?? '')
        setError(null)
      } catch (err: unknown) {
        if (!controller.signal.aborted) setError('Failed to load pay runs')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    load()
    return () => controller.abort()
  }, [])

  // --- Load period detail (summary + timesheets + adjustments) ------------
  const loadPeriodDetail = useCallback(async (periodId: string, signal?: AbortSignal) => {
    if (!periodId) {
      setSummary(null)
      setTimesheets([])
      setAdjustments([])
      return
    }
    try {
      const [tsRes, adjRes] = await Promise.all([
        apiClient.get<{ items: TimesheetRow[]; total: number; period_summary: PeriodSummary }>(
          '/api/v2/timesheets/',
          { params: { pay_period_id: periodId }, signal },
        ),
        apiClient.get<{ items: Adjustment[]; total: number }>('/api/v2/pay-run/adjustments/', {
          params: { pay_period_id: periodId },
          signal,
        }),
      ])
      setTimesheets(tsRes.data?.items ?? [])
      setSummary(tsRes.data?.period_summary ?? null)
      setAdjustments(adjRes.data?.items ?? [])
    } catch {
      /* non-fatal — leave summary blank */
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    loadPeriodDetail(selectedPeriod, controller.signal)
    return () => controller.abort()
  }, [selectedPeriod, loadPeriodDetail])

  // --- Actions ------------------------------------------------------------
  const handleGeneratePeriods = async () => {
    const cycle = cycles.find((c) => c.is_default) ?? cycles[0]
    if (!cycle) {
      flash('error', 'Configure a pay cycle in Settings before generating periods')
      return
    }
    setGeneratingPeriods(true)
    try {
      const res = await apiClient.post<{ created: GeneratedPeriod[]; count: number }>(
        `/api/v2/pay-cycles/${cycle.id}/generate-periods/`,
        { count: 8 },
      )
      const created = res.data?.created ?? []
      if (created.length > 0) {
        setPreviewPeriods(created)
        // Refresh the period list
        const periodsRes = await apiClient.get<{ items: PayPeriod[]; total: number }>('/api/v2/pay-periods', {
          params: { limit: 50 },
        })
        const allReloaded = (periodsRes.data?.items ?? [])
          .slice()
          .sort((a, b) => (b?.start_date ?? '').localeCompare(a?.start_date ?? ''))
        const cycleManaged = allReloaded.filter((p) => !!p.pay_cycle_id)
        setPeriods(cycleManaged.length > 0 ? cycleManaged : allReloaded)
      } else {
        flash('success', `All periods for "${cycle.name}" already exist — nothing new to generate`)
      }
    } catch {
      flash('error', 'Failed to generate pay periods')
    } finally {
      setGeneratingPeriods(false)
    }
  }

  const handleGeneratePayRun = async () => {
    if (!selectedPeriod) {
      flash('error', 'Select a pay period first')
      return
    }
    const lockedCount = summary?.locked_count ?? 0
    if (lockedCount === 0) {
      flash('error', 'No locked timesheets in this period. Lock approved timesheets in the Timesheets tab first.')
      return
    }
    setGeneratingRun(true)
    try {
      const res = await apiClient.post<{
        payslips_generated: number
        total_timesheets: number
        adjustments_included: number
        errors: string[]
      }>('/api/v2/pay-run/generate/', null, {
        params: { pay_period_id: selectedPeriod },
      })
      const data = res.data
      flash(
        'success',
        `Pay run complete — ${data?.payslips_generated ?? 0} payslip draft(s) created from ${data?.total_timesheets ?? 0} locked timesheet(s)${
          data?.adjustments_included ? `, ${data.adjustments_included} adjustment(s) included` : ''
        }`,
      )
    } catch {
      flash('error', 'Failed to generate pay run')
    } finally {
      setGeneratingRun(false)
    }
  }

  const handleSaveAdjustment = async () => {
    if (!adjStaffTimesheet || !adjMinutes || !adjReason || !selectedPeriod) return
    setSavingAdjustment(true)
    try {
      await apiClient.post('/api/v2/pay-run/adjustments/', {
        original_timesheet_id: adjStaffTimesheet,
        correction_period_id: selectedPeriod,
        adjustment_minutes: Number(adjMinutes),
        reason: adjReason,
        category: adjCategory,
      })
      setShowAdjustModal(false)
      setAdjStaffTimesheet('')
      setAdjMinutes('')
      setAdjReason('')
      setAdjCategory('correction')
      flash('success', 'Adjustment recorded — it will carry into this period\u2019s pay run')
      loadPeriodDetail(selectedPeriod)
    } catch {
      flash('error', 'Failed to save adjustment')
    } finally {
      setSavingAdjustment(false)
    }
  }

  const staffNameForTimesheet = (id: string) => timesheets.find((t) => t.id === id)?.staff_name ?? 'Unknown'

  // --- Render -------------------------------------------------------------
  if (loading) {
    return (
      <div className="animate-pulse space-y-3">
        <div className="h-10 w-64 rounded-lg bg-muted/10" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-24 rounded-lg bg-muted/10" />
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

  const lockedCount = summary?.locked_count ?? 0
  const approvedCount = summary?.approved_count ?? 0
  const pendingCount = summary?.pending_count ?? 0
  const totalStaff = summary?.total_staff ?? 0
  const readyToRun = lockedCount > 0

  return (
    <div className="space-y-6">
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

      {/* Workflow guidance (empty state for no cycles) */}
      {cycles.length === 0 && (
        <div className="rounded-lg border border-dashed border-border p-6">
          <div className="flex items-start gap-3">
            <div className="rounded-full bg-warning/10 p-2.5">
              <svg className="h-5 w-5 text-warning" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-text">No pay cycle configured yet</p>
              <p className="mt-1 text-xs text-muted">
                A pay cycle defines how often staff are paid (weekly, fortnightly, monthly) and is the source of
                truth for pay-period dates. Set one up in the <span className="font-medium text-text">Settings</span> tab,
                then return here to generate periods and run payroll.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Step 1: Pay Period selection */}
      <div className="rounded-lg border border-border p-5">
        <div className="mb-3 flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-xs font-bold text-white">1</span>
          <h3 className="text-sm font-semibold text-text">Select Pay Period</h3>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={selectedPeriod}
            onChange={(e) => setSelectedPeriod(e.target.value)}
            className="h-9 rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
          >
            {periods.length === 0 && <option value="">No periods — generate below</option>}
            {(() => {
              const current = periods.filter((p) => periodRelative(p) === 'current')
              const future = periods.filter((p) => periodRelative(p) === 'future')
              const past = periods.filter((p) => periodRelative(p) === 'past')
              return (
                <>
                  {current.length > 0 && (
                    <optgroup label="Current">
                      {current.map((p) => (
                        <option key={p.id} value={p.id}>{fmtPeriodLabel(p)}</option>
                      ))}
                    </optgroup>
                  )}
                  {future.length > 0 && (
                    <optgroup label="Upcoming">
                      {future.map((p) => (
                        <option key={p.id} value={p.id}>{fmtPeriodLabel(p)}</option>
                      ))}
                    </optgroup>
                  )}
                  {past.length > 0 && (
                    <optgroup label="Past">
                      {past.map((p) => (
                        <option key={p.id} value={p.id}>{fmtPeriodLabel(p)}</option>
                      ))}
                    </optgroup>
                  )}
                </>
              )
            })()}
          </select>
          {(() => {
            const sel = periods.find((p) => p.id === selectedPeriod)
            if (!sel) return null
            const rel = periodRelative(sel)
            const map = {
              current: { label: 'This week', cls: 'bg-success/10 text-success' },
              future: { label: 'Upcoming', cls: 'bg-accent/10 text-accent' },
              past: { label: 'Past', cls: 'bg-muted/20 text-muted' },
            } as const
            return (
              <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${map[rel].cls}`}>
                {map[rel].label}
              </span>
            )
          })()}
          <button
            onClick={handleGeneratePeriods}
            disabled={generatingPeriods || cycles.length === 0}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-text hover:bg-canvas transition-colors disabled:opacity-50"
          >
            {generatingPeriods ? (
              <>
                <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Generating…
              </>
            ) : (
              <>
                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
                </svg>
                Generate Periods
              </>
            )}
          </button>
        </div>
        {cycles.length > 0 && (
          <p className="mt-2 text-xs text-muted">
            Periods are derived from the{' '}
            <span className="font-medium text-text">{(cycles.find((c) => c.is_default) ?? cycles[0])?.name}</span>{' '}
            cycle ({(cycles.find((c) => c.is_default) ?? cycles[0])?.frequency}). Manage cycles in the Settings tab.
          </p>
        )}
      </div>

      {/* Step 2: Period readiness */}
      {selectedPeriod && (
        <div className="rounded-lg border border-border p-5">
          <div className="mb-3 flex items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-xs font-bold text-white">2</span>
            <h3 className="text-sm font-semibold text-text">Period Readiness</h3>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-lg bg-canvas p-3 text-center">
              <p className="text-lg font-semibold text-text">{totalStaff}</p>
              <p className="text-xs text-muted">Timesheets</p>
            </div>
            <div className="rounded-lg bg-warning/5 p-3 text-center">
              <p className="text-lg font-semibold text-warning">{pendingCount}</p>
              <p className="text-xs text-muted">Pending</p>
            </div>
            <div className="rounded-lg bg-success/5 p-3 text-center">
              <p className="text-lg font-semibold text-success">{approvedCount}</p>
              <p className="text-xs text-muted">Approved</p>
            </div>
            <div className="rounded-lg bg-accent/5 p-3 text-center">
              <p className="text-lg font-semibold text-accent">{lockedCount}</p>
              <p className="text-xs text-muted">Locked</p>
            </div>
          </div>
          {!readyToRun && totalStaff > 0 && (
            <p className="mt-3 text-xs text-muted">
              Approve and lock timesheets in the <span className="font-medium text-text">Timesheets</span> tab before running pay.
              Only locked timesheets flow into the pay run.
            </p>
          )}
          {totalStaff === 0 && (
            <p className="mt-3 text-xs text-muted">
              No timesheets in this period yet. Use the Timesheets tab to materialise them, or wait for staff to clock in.
            </p>
          )}
        </div>
      )}

      {/* Step 3: Generate Pay Run */}
      {selectedPeriod && (
        <div className="rounded-lg border border-border p-5">
          <div className="mb-3 flex items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-xs font-bold text-white">3</span>
            <h3 className="text-sm font-semibold text-text">Generate Pay Run</h3>
          </div>
          <div className="flex items-start gap-4">
            <div className="rounded-full bg-accent/10 p-2.5">
              <svg className="h-5 w-5 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z" />
              </svg>
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium text-text">Create payslip drafts for {lockedCount} locked timesheet(s)</p>
              <p className="mt-0.5 text-xs text-muted">
                Generates draft payslips in the Payroll module. Hour bands (ordinary, overtime, public holiday) and any
                recorded adjustments flow into each payslip. Draft payslips can be reviewed and finalised in Payroll.
              </p>
              <button
                onClick={handleGeneratePayRun}
                disabled={generatingRun || !readyToRun}
                className="mt-3 inline-flex h-9 items-center gap-2 rounded-lg bg-accent px-4 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50 transition-colors"
                title={!readyToRun ? 'Lock at least one timesheet first' : undefined}
              >
                {generatingRun ? (
                  <>
                    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Generating…
                  </>
                ) : (
                  'Generate Pay Run'
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Adjustments */}
      {selectedPeriod && (
        <div className="rounded-lg border border-border p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text">Corrections &amp; Adjustments</h3>
            <button
              onClick={() => setShowAdjustModal(true)}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-text hover:bg-canvas transition-colors"
            >
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              New Adjustment
            </button>
          </div>
          {adjustments.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-6 text-center">
              <p className="text-sm text-muted">No adjustments for this period</p>
              <p className="mt-0.5 text-xs text-muted">
                Use an adjustment to correct a prior locked timesheet. The correction carries into this period&apos;s pay run.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {adjustments.map((a) => (
                <div key={a.id} className="flex items-center justify-between rounded-lg border border-border p-3">
                  <div>
                    <p className="text-sm font-medium text-text">{staffNameForTimesheet(a.original_timesheet_id)}</p>
                    <p className="text-xs text-muted capitalize">{a.category} • {a.reason}</p>
                  </div>
                  <span
                    className={`font-mono text-sm font-semibold ${a.adjustment_minutes < 0 ? 'text-danger' : 'text-success'}`}
                  >
                    {fmtMinutes(a.adjustment_minutes)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Pay cycle overview (read-only — managed in Settings) */}
      {cycles.length > 0 && (
        <div className="rounded-lg border border-border p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text">Configured Pay Cycles</h3>
            <span className="text-xs text-muted">Manage in Settings</span>
          </div>
          <div className="space-y-2">
            {cycles.map((cycle) => (
              <div key={cycle.id} className="flex items-center gap-3 rounded-lg border border-border p-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/10">
                  <svg className="h-4 w-4 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
                  </svg>
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-text">{cycle.name}</p>
                    {cycle.is_default && (
                      <span className="rounded bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">Default</span>
                    )}
                  </div>
                  <p className="text-xs text-muted capitalize">
                    {cycle.frequency} • Anchored {fmtDateLong(cycle.anchor_date)} • Pay {cycle.pay_date_offset_days} day(s) after period end
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Generated periods preview modal */}
      {previewPeriods && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 p-4">
          <div className="w-full max-w-md rounded-card bg-card p-6 shadow-pop">
            <h3 className="text-lg font-semibold text-text">{previewPeriods.length} pay period(s) generated</h3>
            <p className="mt-1 text-sm text-muted">These periods are now available in the selector above.</p>
            <div className="mt-4 max-h-72 space-y-2 overflow-y-auto">
              {previewPeriods.map((p) => (
                <div key={p.id} className="flex items-center justify-between rounded-lg border border-border p-3">
                  <div>
                    <p className="text-sm font-medium text-text">{fmtDate(p.start_date)} – {fmtDate(p.end_date)}</p>
                    <p className="text-xs text-muted">Pay date: {fmtDateLong(p.pay_date)}</p>
                  </div>
                  <span className="rounded-full bg-success/10 px-2 py-0.5 text-xs font-medium text-success">New</span>
                </div>
              ))}
            </div>
            <div className="mt-6 flex justify-end">
              <button
                onClick={() => setPreviewPeriods(null)}
                className="inline-flex h-10 items-center rounded-lg bg-accent px-4 text-sm font-medium text-white hover:bg-accent/90 transition-colors"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {/* New adjustment modal */}
      {showAdjustModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 p-4">
          <div className="w-full max-w-md rounded-card bg-card p-6 shadow-pop">
            <h3 className="text-lg font-semibold text-text">New Adjustment</h3>
            <p className="mt-1 text-sm text-muted">
              Correct hours that were missed on a locked timesheet. The correction is applied to the current period&apos;s pay run.
            </p>

            <div className="mt-4 space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-muted">Staff timesheet</label>
                <select
                  value={adjStaffTimesheet}
                  onChange={(e) => setAdjStaffTimesheet(e.target.value)}
                  className="h-10 w-full rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
                >
                  <option value="">Select staff…</option>
                  {timesheets.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.staff_name} ({t.actual_hours}h, {t.status.replace(/_/g, ' ')})
                    </option>
                  ))}
                </select>
                {timesheets.length === 0 && (
                  <p className="mt-1 text-xs text-muted">No timesheets in this period to adjust.</p>
                )}
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted">Adjustment (minutes)</label>
                <input
                  type="number"
                  value={adjMinutes}
                  onChange={(e) => setAdjMinutes(e.target.value)}
                  placeholder="e.g. 30 to add, -15 to deduct"
                  className="h-10 w-full rounded-lg border border-border bg-canvas px-3 text-sm text-text placeholder:text-muted/50 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted">Category</label>
                <select
                  value={adjCategory}
                  onChange={(e) => setAdjCategory(e.target.value)}
                  className="h-10 w-full rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
                >
                  <option value="correction">Correction</option>
                  <option value="missed_punch">Missed punch</option>
                  <option value="back_pay">Back pay</option>
                  <option value="other">Other</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted">Reason</label>
                <textarea
                  value={adjReason}
                  onChange={(e) => setAdjReason(e.target.value)}
                  placeholder="Why is this adjustment needed?"
                  rows={3}
                  className="w-full resize-none rounded-lg border border-border bg-canvas px-3 py-2 text-sm text-text placeholder:text-muted/50 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
                />
              </div>
            </div>

            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                onClick={() => setShowAdjustModal(false)}
                disabled={savingAdjustment}
                className="inline-flex h-10 items-center rounded-lg border border-border bg-card px-4 text-sm font-medium text-text hover:bg-canvas transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveAdjustment}
                disabled={savingAdjustment || !adjStaffTimesheet || !adjMinutes || !adjReason}
                className="inline-flex h-10 items-center rounded-lg bg-accent px-4 text-sm font-medium text-white hover:bg-accent/90 transition-colors disabled:opacity-50"
              >
                {savingAdjustment ? 'Saving…' : 'Save Adjustment'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
