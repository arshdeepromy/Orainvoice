/**
 * Enhanced weekly timesheet with V2 features:
 * - Project-based time reporting view (total hours, billable vs non-billable, cost analysis)
 * - Weekly timesheet grid (project × day with row/column totals)
 * - "Convert to Invoice" action on billable entries
 * - Overlap validation in real-time
 * - Time entry panel for Job Detail page integration
 *
 * Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
 *
 * Task 33 port: logic copied VERBATIM from
 * frontend/src/pages/time-tracking/TimeSheet.tsx; presentation remapped from
 * the original inline styles onto the design-system tokens (page/page-head,
 * token tab strip, week navigator, card-wrapped token tables with `.mono`
 * numerics) per the TimeTracking.html prototype. Every data-testid, ARIA role
 * and aria-label is preserved.
 */

import { useEffect, useState, useCallback, useMemo } from 'react'
import apiClient from '@/api/client'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { useFlag } from '@/contexts/FeatureFlagContext'
import { useTerm } from '@/contexts/TerminologyContext'
import { ToastContainer } from '@/components/ui/Toast'
import {
  detectOverlap,
  aggregateTimeByProject,
  canConvertToInvoice,
} from '@/utils/timeTrackingCalcs'
import type { AggregationEntry } from '@/utils/timeTrackingCalcs'

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

interface TimeEntryData {
  id: string
  description: string | null
  start_time: string
  end_time: string | null
  duration_minutes: number | null
  is_billable: boolean
  hourly_rate: string | null
  is_invoiced: boolean
  job_id: string | null
  project_id: string | null
  project_name?: string
}

interface TimesheetDay {
  date: string
  entries: TimeEntryData[]
  total_minutes: number
  billable_minutes: number
}

interface TimesheetData {
  week_start: string
  week_end: string
  days: TimesheetDay[]
  weekly_total_minutes: number
  weekly_billable_minutes: number
}

interface ProjectOption {
  id: string
  name: string
}

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

function formatMinutes(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return `${h}h ${m}m`
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function getMonday(d: Date): string {
  const date = new Date(d)
  const day = date.getDay()
  const diff = date.getDate() - day + (day === 0 ? -6 : 1)
  date.setDate(diff)
  return date.toISOString().split('T')[0]
}

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

type ViewMode = 'timesheet' | 'project-report' | 'weekly-grid'

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export default function TimeSheet({ jobId }: { jobId?: string }) {
  const { isAllowed, isLoading: guardLoading, toasts, dismissToast } = useModuleGuard('time_tracking')
  const timeTrackingEnabled = useFlag('time_tracking_v2')
  const projectLabel = useTerm('project', 'Project')
  const jobLabel = useTerm('job', 'Job')

  const [timesheet, setTimesheet] = useState<TimesheetData | null>(null)
  const [allEntries, setAllEntries] = useState<TimeEntryData[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [weekStart, setWeekStart] = useState(() => getMonday(new Date()))
  const [viewMode, setViewMode] = useState<ViewMode>('timesheet')
  const [projects, setProjects] = useState<ProjectOption[]>([])
  const [selectedEntries, setSelectedEntries] = useState<Set<string>>(new Set())
  const [converting, setConverting] = useState(false)
  const [overlapWarnings, setOverlapWarnings] = useState<string[]>([])

  /* ---- Data fetching ---- */

  const fetchTimesheet = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, string> = { week_start: weekStart }
      const res = await apiClient.get('/api/v2/time-entries/timesheet', { params })
      setTimesheet(res.data)

      // Flatten all entries for overlap detection and aggregation
      const flat: TimeEntryData[] = (res.data.days ?? []).flatMap(
        (d: TimesheetDay) => d.entries,
      )
      setAllEntries(flat)
    } catch {
      setError('Failed to load timesheet')
      setTimesheet(null)
    } finally {
      setLoading(false)
    }
  }, [weekStart])

  const fetchProjects = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/projects', { params: { page_size: 200 } })
      setProjects(
        (res.data.projects ?? res.data.items ?? []).map((p: any) => ({
          id: p.id,
          name: p.name ?? p.title ?? 'Unnamed',
        })),
      )
    } catch {
      /* non-critical */
    }
  }, [])

  useEffect(() => { fetchTimesheet() }, [fetchTimesheet])
  useEffect(() => { fetchProjects() }, [fetchProjects])

  /* ---- Overlap detection (real-time) ---- */

  useEffect(() => {
    const ranges = allEntries
      .filter((e) => e.end_time)
      .map((e) => ({
        start: new Date(e.start_time),
        end: new Date(e.end_time!),
      }))
    const overlaps = detectOverlap(ranges)
    if (overlaps.length > 0) {
      const warnings = overlaps.map(
        ({ index1, index2 }) =>
          `Overlap detected between entry ${index1 + 1} and entry ${index2 + 1}`,
      )
      setOverlapWarnings(warnings)
    } else {
      setOverlapWarnings([])
    }
  }, [allEntries])

  /* ---- Project aggregation ---- */

  const projectAggregation = useMemo(() => {
    const aggEntries: AggregationEntry[] = allEntries
      .filter((e) => e.project_id)
      .map((e) => ({
        project_id: e.project_id!,
        hours: (e.duration_minutes ?? 0) / 60,
        billable: e.is_billable,
        rate: e.hourly_rate ? parseFloat(e.hourly_rate) : 0,
      }))
    return aggregateTimeByProject(aggEntries)
  }, [allEntries])

  /* ---- Weekly grid data (project × day) ---- */

  const weeklyGridData = useMemo(() => {
    if (!timesheet) return { projectIds: [], grid: {} as Record<string, number[]>, dayTotals: [] as number[] }

    const grid: Record<string, number[]> = {}
    const projectIds = new Set<string>()

    timesheet.days.forEach((day, dayIdx) => {
      for (const entry of day.entries) {
        const pid = entry.project_id ?? '__unassigned__'
        projectIds.add(pid)
        if (!grid[pid]) grid[pid] = [0, 0, 0, 0, 0, 0, 0]
        grid[pid][dayIdx] += (entry.duration_minutes ?? 0) / 60
      }
    })

    const dayTotals = [0, 0, 0, 0, 0, 0, 0]
    for (const pid of Object.keys(grid)) {
      for (let d = 0; d < 7; d++) {
        dayTotals[d] += grid[pid][d]
      }
    }

    return { projectIds: Array.from(projectIds), grid, dayTotals }
  }, [timesheet])

  /* ---- Convert to Invoice ---- */

  const convertibleEntries = useMemo(
    () =>
      allEntries.filter((e) =>
        canConvertToInvoice({ billable: e.is_billable, status: e.is_invoiced ? 'invoiced' : 'billable' }),
      ),
    [allEntries],
  )

  const toggleEntrySelection = (id: string) => {
    setSelectedEntries((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleConvertToInvoice = useCallback(async () => {
    if (selectedEntries.size === 0) return
    setConverting(true)
    try {
      await apiClient.post('/api/v2/time-entries/add-to-invoice', {
        time_entry_ids: Array.from(selectedEntries),
        invoice_id: null, // Backend creates a new draft invoice
      })
      setSelectedEntries(new Set())
      fetchTimesheet()
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Failed to convert to invoice')
    } finally {
      setConverting(false)
    }
  }, [selectedEntries, fetchTimesheet])

  /* ---- Navigation ---- */

  const navigateWeek = (offset: number) => {
    const d = new Date(weekStart)
    d.setDate(d.getDate() + offset * 7)
    setWeekStart(d.toISOString().split('T')[0])
  }

  const getProjectName = (pid: string | null): string => {
    if (!pid || pid === '__unassigned__') return 'Unassigned'
    return projects.find((p) => p.id === pid)?.name ?? pid.slice(0, 8)
  }

  /* ---- Render guards ---- */

  if (guardLoading || loading) {
    return (
      <div className="page page-wide">
        <div role="status" aria-label="Loading timesheet" className="py-16 text-center text-sm text-muted">
          Loading timesheet…
        </div>
      </div>
    )
  }

  if (!isAllowed || !timeTrackingEnabled) return null

  if (!timesheet) {
    return (
      <div className="page page-wide">
        <ToastContainer toasts={toasts} onDismiss={dismissToast} />
        <div
          role="alert"
          className="rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger"
        >
          {error ?? 'Failed to load timesheet'}
        </div>
      </div>
    )
  }

  /* ---- Main render ---- */

  const TH_LEFT =
    'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
  const TH_RIGHT =
    'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

  return (
    <div className="page page-wide">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="page-head">
        <div>
          <div className="eyebrow">Work</div>
          <h1>Weekly Timesheet</h1>
          <p className="sub">
            {timesheet.week_start} — {timesheet.week_end}
          </p>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="error-banner mb-4 flex items-center justify-between rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger"
        >
          <span>{error}</span>
          <button
            onClick={() => setError(null)}
            aria-label="Dismiss error"
            className="ml-2 rounded p-0.5 hover:bg-danger/10"
          >
            ×
          </button>
        </div>
      )}

      {/* Overlap warnings */}
      {overlapWarnings.length > 0 && (
        <div
          role="alert"
          data-testid="overlap-warnings"
          className="mb-4 rounded-ctl border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-warn"
        >
          <strong>⚠ Overlap Detected</strong>
          <ul className="mt-2 list-disc pl-5">
            {overlapWarnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </div>
      )}

      {/* View mode tabs */}
      <div
        role="tablist"
        aria-label="Timesheet views"
        className="mb-4 flex flex-wrap gap-1 border-b border-border"
      >
        <button
          role="tab"
          aria-selected={viewMode === 'timesheet'}
          onClick={() => setViewMode('timesheet')}
          data-testid="tab-timesheet"
          className={`-mb-px min-h-[44px] border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
            viewMode === 'timesheet'
              ? 'border-accent text-accent'
              : 'border-transparent text-muted hover:text-text'
          }`}
        >
          Timesheet
        </button>
        <button
          role="tab"
          aria-selected={viewMode === 'project-report'}
          onClick={() => setViewMode('project-report')}
          data-testid="tab-project-report"
          className={`-mb-px min-h-[44px] border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
            viewMode === 'project-report'
              ? 'border-accent text-accent'
              : 'border-transparent text-muted hover:text-text'
          }`}
        >
          {projectLabel} Report
        </button>
        <button
          role="tab"
          aria-selected={viewMode === 'weekly-grid'}
          onClick={() => setViewMode('weekly-grid')}
          data-testid="tab-weekly-grid"
          className={`-mb-px min-h-[44px] border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
            viewMode === 'weekly-grid'
              ? 'border-accent text-accent'
              : 'border-transparent text-muted hover:text-text'
          }`}
        >
          Weekly Grid
        </button>
      </div>

      {/* Week navigation */}
      <nav
        aria-label="Week navigation"
        className="my-4 flex items-center gap-4"
      >
        <button
          onClick={() => navigateWeek(-1)}
          aria-label="Previous week"
          className="min-h-[44px] rounded-ctl border border-border bg-card px-3 py-2 text-sm font-medium text-text hover:bg-canvas"
        >
          ← Prev
        </button>
        <span className="mono text-sm text-text">{timesheet.week_start} — {timesheet.week_end}</span>
        <button
          onClick={() => navigateWeek(1)}
          aria-label="Next week"
          className="min-h-[44px] rounded-ctl border border-border bg-card px-3 py-2 text-sm font-medium text-text hover:bg-canvas"
        >
          Next →
        </button>
      </nav>

      {/* ============ TIMESHEET VIEW ============ */}
      {viewMode === 'timesheet' && (
        <div data-testid="timesheet-view">
          <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <div className="overflow-x-auto">
              <table role="table" aria-label="Weekly timesheet" className="w-full border-collapse text-sm">
                <thead>
                  <tr>
                    <th className={TH_LEFT}>Day</th>
                    <th className={TH_LEFT}>Entries</th>
                    <th className={TH_RIGHT}>Total</th>
                    <th className={TH_RIGHT}>Billable</th>
                  </tr>
                </thead>
                <tbody>
                  {timesheet.days.map((day, idx) => (
                    <tr key={day.date} className="border-b border-border last:border-b-0 hover:bg-canvas">
                      <td className="px-4 py-3 align-top text-[13.5px] text-text">
                        <strong>{DAY_NAMES[idx]}</strong>
                        <br />
                        <small className="mono text-muted-2">{day.date}</small>
                      </td>
                      <td className="px-4 py-3 align-top text-[13.5px] text-text">
                        {day.entries.length === 0 ? (
                          <span className="text-muted-2">—</span>
                        ) : (
                          <ul className="m-0 list-none p-0">
                            {day.entries.map((entry) => (
                              <li key={entry.id} className="mb-1">
                                {entry.description || 'Untitled'}{' '}
                                <small className="mono text-muted">
                                  ({formatTime(entry.start_time)}
                                  {entry.end_time ? ` – ${formatTime(entry.end_time)}` : ' (running)'}
                                  )
                                </small>
                                {entry.is_billable && <span title="Billable"> 💰</span>}
                                {entry.is_invoiced && <span title="Invoiced" className="text-muted-2"> ✓ invoiced</span>}
                                {entry.project_id && (
                                  <small className="text-accent"> [{getProjectName(entry.project_id)}]</small>
                                )}
                              </li>
                            ))}
                          </ul>
                        )}
                      </td>
                      <td className="mono px-4 py-3 text-right align-top text-[13px] text-muted">{formatMinutes(day.total_minutes)}</td>
                      <td className="mono px-4 py-3 text-right align-top text-[13px] text-muted">{formatMinutes(day.billable_minutes)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="bg-canvas">
                    <td colSpan={2} className="px-4 py-3 font-semibold text-text"><strong>Weekly Total</strong></td>
                    <td className="mono px-4 py-3 text-right font-semibold text-text"><strong>{formatMinutes(timesheet.weekly_total_minutes)}</strong></td>
                    <td className="mono px-4 py-3 text-right font-semibold text-text"><strong>{formatMinutes(timesheet.weekly_billable_minutes)}</strong></td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </section>

          {/* Convert to Invoice section */}
          {convertibleEntries.length > 0 && (
            <div
              data-testid="convert-to-invoice"
              className="mt-6 rounded-card border border-border bg-card p-4 shadow-card"
            >
              <h3 className="text-[15px] font-semibold text-text">Convert Billable Entries to Invoice</h3>
              <p className="mt-1 text-sm text-muted">
                Select billable entries to create invoice line items (hours × rate).
              </p>
              <ul className="mt-2 list-none p-0">
                {convertibleEntries.map((entry) => (
                  <li key={entry.id} className="py-1">
                    <label className="flex min-h-[44px] cursor-pointer items-center gap-2">
                      <input
                        type="checkbox"
                        checked={selectedEntries.has(entry.id)}
                        onChange={() => toggleEntrySelection(entry.id)}
                        aria-label={`Select entry: ${entry.description || 'Untitled'}`}
                        className="h-5 w-5 accent-[var(--accent)]"
                      />
                      <span className="text-[13.5px] text-text">
                        {entry.description || 'Untitled'} — <span className="mono">{formatMinutes(entry.duration_minutes ?? 0)}</span>
                        {entry.hourly_rate && <span className="mono"> @ {entry.hourly_rate}/hr</span>}
                        {entry.project_id && <small className="text-accent"> [{getProjectName(entry.project_id)}]</small>}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
              <button
                onClick={handleConvertToInvoice}
                disabled={converting || selectedEntries.size === 0}
                data-testid="convert-invoice-btn"
                aria-label="Convert selected entries to invoice"
                className="mt-3 min-h-[44px] rounded-ctl bg-accent px-5 py-2 text-sm font-medium text-white hover:bg-accent-press disabled:cursor-not-allowed disabled:opacity-50"
              >
                {converting ? 'Converting…' : `Convert ${selectedEntries.size} Entries to Invoice`}
              </button>
            </div>
          )}
        </div>
      )}

      {/* ============ PROJECT REPORT VIEW ============ */}
      {viewMode === 'project-report' && (
        <div data-testid="project-report-view">
          <h2 className="mb-3 text-[18px] font-semibold text-text">{projectLabel}-Based Time Report</h2>
          {Object.keys(projectAggregation).length === 0 ? (
            <p className="text-muted-2">No project-assigned time entries this week.</p>
          ) : (
            <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
              <div className="overflow-x-auto">
                <table role="table" aria-label="Project time report" className="w-full border-collapse text-sm">
                  <thead>
                    <tr>
                      <th className={TH_LEFT}>{projectLabel}</th>
                      <th className={TH_RIGHT}>Total Hours</th>
                      <th className={TH_RIGHT}>Billable</th>
                      <th className={TH_RIGHT}>Non-Billable</th>
                      <th className={TH_RIGHT}>Cost ($)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(projectAggregation).map(([pid, agg]) => (
                      <tr key={pid} data-testid={`project-row-${pid}`} className="border-b border-border last:border-b-0 hover:bg-canvas">
                        <td className="px-4 py-3 text-[13.5px] text-text">{getProjectName(pid)}</td>
                        <td className="mono px-4 py-3 text-right text-[13px] text-muted">{agg.totalHours.toFixed(1)}</td>
                        <td className="mono px-4 py-3 text-right text-[13px] text-muted">{agg.billableHours.toFixed(1)}</td>
                        <td className="mono px-4 py-3 text-right text-[13px] text-muted">{agg.nonBillableHours.toFixed(1)}</td>
                        <td className="mono px-4 py-3 text-right text-[13px] text-muted">${agg.totalCost.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      )}

      {/* ============ WEEKLY GRID VIEW ============ */}
      {viewMode === 'weekly-grid' && (
        <div data-testid="weekly-grid-view" className="overflow-x-auto">
          <h2 className="mb-3 text-[18px] font-semibold text-text">Weekly Grid ({projectLabel} × Day)</h2>
          <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <div className="overflow-x-auto">
              <table role="table" aria-label="Weekly time grid" className="w-full border-collapse text-sm">
                <thead>
                  <tr>
                    <th className={TH_LEFT}>{projectLabel}</th>
                    {DAY_NAMES.map((d) => (
                      <th key={d} className={`${TH_RIGHT} min-w-[60px]`}>{d}</th>
                    ))}
                    <th className={TH_RIGHT}>Total</th>
                  </tr>
                </thead>
                <tbody>
                  {weeklyGridData.projectIds.map((pid) => {
                    const row = weeklyGridData.grid[pid] ?? [0, 0, 0, 0, 0, 0, 0]
                    const rowTotal = row.reduce((a, b) => a + b, 0)
                    return (
                      <tr key={pid} data-testid={`grid-row-${pid}`} className="border-b border-border last:border-b-0 hover:bg-canvas">
                        <td className="px-4 py-3 text-[13.5px] text-text">{getProjectName(pid)}</td>
                        {row.map((hrs, i) => (
                          <td key={i} className="mono px-4 py-3 text-right text-[13px] text-muted">
                            {hrs > 0 ? hrs.toFixed(1) : '—'}
                          </td>
                        ))}
                        <td className="mono px-4 py-3 text-right text-[13px] font-semibold text-text">
                          {rowTotal.toFixed(1)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot>
                  <tr className="bg-canvas">
                    <td className="px-4 py-3 font-bold text-text">Day Total</td>
                    {weeklyGridData.dayTotals.map((t, i) => (
                      <td key={i} className="mono px-4 py-3 text-right font-bold text-text">
                        {t > 0 ? t.toFixed(1) : '—'}
                      </td>
                    ))}
                    <td className="mono px-4 py-3 text-right font-bold text-text">
                      {weeklyGridData.dayTotals.reduce((a, b) => a + b, 0).toFixed(1)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </section>
        </div>
      )}

      {/* Job-specific time entry panel (when embedded in Job Detail) */}
      {jobId && (
        <div
          data-testid="job-time-panel"
          className="mt-8 rounded-card border border-border bg-card p-4 shadow-card"
        >
          <h3 className="text-[15px] font-semibold text-text">Time Entries for {jobLabel}</h3>
          {allEntries.filter((e) => e.job_id === jobId).length === 0 ? (
            <p className="text-muted-2">No time entries logged against this {jobLabel.toLowerCase()}.</p>
          ) : (
            <ul className="list-none p-0">
              {allEntries
                .filter((e) => e.job_id === jobId)
                .map((entry) => (
                  <li key={entry.id} className="border-b border-border py-1.5 last:border-b-0 text-[13.5px] text-text">
                    <strong>{entry.description || 'Untitled'}</strong>{' '}
                    <small className="mono text-muted">
                      {formatTime(entry.start_time)}
                      {entry.end_time ? ` – ${formatTime(entry.end_time)}` : ' (running)'}
                    </small>
                    {' — '}<span className="mono">{formatMinutes(entry.duration_minutes ?? 0)}</span>
                    {entry.is_billable && <span title="Billable"> 💰</span>}
                    {entry.is_invoiced && <span className="text-muted-2"> ✓ invoiced</span>}
                  </li>
                ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
