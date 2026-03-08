/**
 * Enhanced weekly timesheet with V2 features:
 * - Project-based time reporting view (total hours, billable vs non-billable, cost analysis)
 * - Weekly timesheet grid (project × day with row/column totals)
 * - "Convert to Invoice" action on billable entries
 * - Overlap validation in real-time
 * - Time entry panel for Job Detail page integration
 *
 * Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
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
    return <div role="status" aria-label="Loading timesheet">Loading timesheet…</div>
  }

  if (!isAllowed || !timeTrackingEnabled) return null

  if (!timesheet) {
    return (
      <div>
        <ToastContainer toasts={toasts} onDismiss={dismissToast} />
        <div role="alert">{error ?? 'Failed to load timesheet'}</div>
      </div>
    )
  }

  /* ---- Main render ---- */

  return (
    <div>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <h1>Weekly Timesheet</h1>

      {error && (
        <div role="alert" className="error-banner" style={{ background: '#fee', padding: '0.75rem', borderRadius: 4, marginBottom: '1rem' }}>
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error" style={{ marginLeft: 8 }}>×</button>
        </div>
      )}

      {/* Overlap warnings */}
      {overlapWarnings.length > 0 && (
        <div role="alert" data-testid="overlap-warnings" style={{ background: '#fff3cd', padding: '0.75rem', borderRadius: 4, marginBottom: '1rem', border: '1px solid #ffc107' }}>
          <strong>⚠ Overlap Detected</strong>
          <ul style={{ margin: '0.5rem 0 0', paddingLeft: '1.25rem' }}>
            {overlapWarnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </div>
      )}

      {/* View mode tabs */}
      <div role="tablist" aria-label="Timesheet views" style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
        <button
          role="tab"
          aria-selected={viewMode === 'timesheet'}
          onClick={() => setViewMode('timesheet')}
          data-testid="tab-timesheet"
          style={{ minWidth: 44, minHeight: 44, fontWeight: viewMode === 'timesheet' ? 700 : 400 }}
        >
          Timesheet
        </button>
        <button
          role="tab"
          aria-selected={viewMode === 'project-report'}
          onClick={() => setViewMode('project-report')}
          data-testid="tab-project-report"
          style={{ minWidth: 44, minHeight: 44, fontWeight: viewMode === 'project-report' ? 700 : 400 }}
        >
          {projectLabel} Report
        </button>
        <button
          role="tab"
          aria-selected={viewMode === 'weekly-grid'}
          onClick={() => setViewMode('weekly-grid')}
          data-testid="tab-weekly-grid"
          style={{ minWidth: 44, minHeight: 44, fontWeight: viewMode === 'weekly-grid' ? 700 : 400 }}
        >
          Weekly Grid
        </button>
      </div>

      {/* Week navigation */}
      <nav aria-label="Week navigation" style={{ display: 'flex', gap: '1rem', alignItems: 'center', margin: '1rem 0' }}>
        <button onClick={() => navigateWeek(-1)} aria-label="Previous week" style={{ minWidth: 44, minHeight: 44 }}>← Prev</button>
        <span>{timesheet.week_start} — {timesheet.week_end}</span>
        <button onClick={() => navigateWeek(1)} aria-label="Next week" style={{ minWidth: 44, minHeight: 44 }}>Next →</button>
      </nav>

      {/* ============ TIMESHEET VIEW ============ */}
      {viewMode === 'timesheet' && (
        <div data-testid="timesheet-view">
          <table role="table" aria-label="Weekly timesheet">
            <thead>
              <tr>
                <th>Day</th>
                <th>Entries</th>
                <th>Total</th>
                <th>Billable</th>
              </tr>
            </thead>
            <tbody>
              {timesheet.days.map((day, idx) => (
                <tr key={day.date}>
                  <td>
                    <strong>{DAY_NAMES[idx]}</strong>
                    <br />
                    <small>{day.date}</small>
                  </td>
                  <td>
                    {day.entries.length === 0 ? (
                      <span style={{ color: '#999' }}>—</span>
                    ) : (
                      <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                        {day.entries.map((entry) => (
                          <li key={entry.id} style={{ marginBottom: 4 }}>
                            {entry.description || 'Untitled'}{' '}
                            <small>
                              ({formatTime(entry.start_time)}
                              {entry.end_time ? ` – ${formatTime(entry.end_time)}` : ' (running)'}
                              )
                            </small>
                            {entry.is_billable && <span title="Billable"> 💰</span>}
                            {entry.is_invoiced && <span title="Invoiced" style={{ color: '#999' }}> ✓ invoiced</span>}
                            {entry.project_id && (
                              <small style={{ color: '#3b82f6' }}> [{getProjectName(entry.project_id)}]</small>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                  <td>{formatMinutes(day.total_minutes)}</td>
                  <td>{formatMinutes(day.billable_minutes)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={2}><strong>Weekly Total</strong></td>
                <td><strong>{formatMinutes(timesheet.weekly_total_minutes)}</strong></td>
                <td><strong>{formatMinutes(timesheet.weekly_billable_minutes)}</strong></td>
              </tr>
            </tfoot>
          </table>

          {/* Convert to Invoice section */}
          {convertibleEntries.length > 0 && (
            <div data-testid="convert-to-invoice" style={{ marginTop: '1.5rem', padding: '1rem', border: '1px solid #ddd', borderRadius: 8 }}>
              <h3>Convert Billable Entries to Invoice</h3>
              <p style={{ color: '#666', fontSize: '0.9em' }}>
                Select billable entries to create invoice line items (hours × rate).
              </p>
              <ul style={{ listStyle: 'none', padding: 0 }}>
                {convertibleEntries.map((entry) => (
                  <li key={entry.id} style={{ padding: '4px 0' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minHeight: 44, cursor: 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={selectedEntries.has(entry.id)}
                        onChange={() => toggleEntrySelection(entry.id)}
                        aria-label={`Select entry: ${entry.description || 'Untitled'}`}
                        style={{ width: 20, height: 20 }}
                      />
                      <span>
                        {entry.description || 'Untitled'} — {formatMinutes(entry.duration_minutes ?? 0)}
                        {entry.hourly_rate && ` @ $${entry.hourly_rate}/hr`}
                        {entry.project_id && <small style={{ color: '#3b82f6' }}> [{getProjectName(entry.project_id)}]</small>}
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
                style={{ marginTop: '0.75rem', background: '#3b82f6', color: '#fff', border: 'none', borderRadius: 4, padding: '8px 20px', cursor: 'pointer', minHeight: 44 }}
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
          <h2>{projectLabel}-Based Time Report</h2>
          {Object.keys(projectAggregation).length === 0 ? (
            <p style={{ color: '#999' }}>No project-assigned time entries this week.</p>
          ) : (
            <table role="table" aria-label="Project time report" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', padding: '8px', borderBottom: '2px solid #ddd' }}>{projectLabel}</th>
                  <th style={{ textAlign: 'right', padding: '8px', borderBottom: '2px solid #ddd' }}>Total Hours</th>
                  <th style={{ textAlign: 'right', padding: '8px', borderBottom: '2px solid #ddd' }}>Billable</th>
                  <th style={{ textAlign: 'right', padding: '8px', borderBottom: '2px solid #ddd' }}>Non-Billable</th>
                  <th style={{ textAlign: 'right', padding: '8px', borderBottom: '2px solid #ddd' }}>Cost ($)</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(projectAggregation).map(([pid, agg]) => (
                  <tr key={pid} data-testid={`project-row-${pid}`}>
                    <td style={{ padding: '8px', borderBottom: '1px solid #eee' }}>{getProjectName(pid)}</td>
                    <td style={{ textAlign: 'right', padding: '8px', borderBottom: '1px solid #eee' }}>{agg.totalHours.toFixed(1)}</td>
                    <td style={{ textAlign: 'right', padding: '8px', borderBottom: '1px solid #eee' }}>{agg.billableHours.toFixed(1)}</td>
                    <td style={{ textAlign: 'right', padding: '8px', borderBottom: '1px solid #eee' }}>{agg.nonBillableHours.toFixed(1)}</td>
                    <td style={{ textAlign: 'right', padding: '8px', borderBottom: '1px solid #eee' }}>${agg.totalCost.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ============ WEEKLY GRID VIEW ============ */}
      {viewMode === 'weekly-grid' && (
        <div data-testid="weekly-grid-view" style={{ overflowX: 'auto' }}>
          <h2>Weekly Grid ({projectLabel} × Day)</h2>
          <table role="table" aria-label="Weekly time grid" style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ textAlign: 'left', padding: '8px', borderBottom: '2px solid #ddd' }}>{projectLabel}</th>
                {DAY_NAMES.map((d) => (
                  <th key={d} style={{ textAlign: 'right', padding: '8px', borderBottom: '2px solid #ddd', minWidth: 60 }}>{d}</th>
                ))}
                <th style={{ textAlign: 'right', padding: '8px', borderBottom: '2px solid #ddd' }}>Total</th>
              </tr>
            </thead>
            <tbody>
              {weeklyGridData.projectIds.map((pid) => {
                const row = weeklyGridData.grid[pid] ?? [0, 0, 0, 0, 0, 0, 0]
                const rowTotal = row.reduce((a, b) => a + b, 0)
                return (
                  <tr key={pid} data-testid={`grid-row-${pid}`}>
                    <td style={{ padding: '8px', borderBottom: '1px solid #eee' }}>{getProjectName(pid)}</td>
                    {row.map((hrs, i) => (
                      <td key={i} style={{ textAlign: 'right', padding: '8px', borderBottom: '1px solid #eee' }}>
                        {hrs > 0 ? hrs.toFixed(1) : '—'}
                      </td>
                    ))}
                    <td style={{ textAlign: 'right', padding: '8px', borderBottom: '1px solid #eee', fontWeight: 600 }}>
                      {rowTotal.toFixed(1)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
            <tfoot>
              <tr>
                <td style={{ padding: '8px', fontWeight: 700, borderTop: '2px solid #ddd' }}>Day Total</td>
                {weeklyGridData.dayTotals.map((t, i) => (
                  <td key={i} style={{ textAlign: 'right', padding: '8px', fontWeight: 700, borderTop: '2px solid #ddd' }}>
                    {t > 0 ? t.toFixed(1) : '—'}
                  </td>
                ))}
                <td style={{ textAlign: 'right', padding: '8px', fontWeight: 700, borderTop: '2px solid #ddd' }}>
                  {weeklyGridData.dayTotals.reduce((a, b) => a + b, 0).toFixed(1)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {/* Job-specific time entry panel (when embedded in Job Detail) */}
      {jobId && (
        <div data-testid="job-time-panel" style={{ marginTop: '2rem', padding: '1rem', border: '1px solid #ddd', borderRadius: 8 }}>
          <h3>Time Entries for {jobLabel}</h3>
          {allEntries.filter((e) => e.job_id === jobId).length === 0 ? (
            <p style={{ color: '#999' }}>No time entries logged against this {jobLabel.toLowerCase()}.</p>
          ) : (
            <ul style={{ listStyle: 'none', padding: 0 }}>
              {allEntries
                .filter((e) => e.job_id === jobId)
                .map((entry) => (
                  <li key={entry.id} style={{ padding: '6px 0', borderBottom: '1px solid #eee' }}>
                    <strong>{entry.description || 'Untitled'}</strong>{' '}
                    <small>
                      {formatTime(entry.start_time)}
                      {entry.end_time ? ` – ${formatTime(entry.end_time)}` : ' (running)'}
                    </small>
                    {' — '}{formatMinutes(entry.duration_minutes ?? 0)}
                    {entry.is_billable && <span title="Billable"> 💰</span>}
                    {entry.is_invoiced && <span style={{ color: '#999' }}> ✓ invoiced</span>}
                  </li>
                ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
