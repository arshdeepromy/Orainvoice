/**
 * JobBoard — Task 26 port of frontend/src/pages/jobs/JobBoard.tsx.
 *
 * Kanban / project-hierarchy / resource-timeline board for jobs (v2). ALL logic
 * copied VERBATIM: the module guard (useModuleGuard('jobs')) + terminology
 * labels, the fetch (GET /api/v2/jobs?page_size=200), the drag-and-drop status
 * transitions validated via isValidStatusTransition (PUT /api/v2/jobs/:id/
 * status), the memoised project grouping with expand/collapse, and the staff
 * resource timeline with overlap-conflict detection. Presentation is remapped
 * from inline styles onto the design tokens per OraInvoice_Handoff/app/
 * JobBoard.html (the .board/.col/.jcard kanban language, hierarchy accordions,
 * conflict rows tinted danger-soft).
 *
 * Validates: Requirements 8.1, 8.2, 8.3, 8.4
 */

import { useEffect, useState, useCallback, type DragEvent, useMemo } from 'react'
import apiClient from '@/api/client'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { useTerm } from '@/contexts/TerminologyContext'
import { ToastContainer } from '@/components/ui/Toast'
import { isValidStatusTransition } from '@/utils/jobCalcs'

interface Job {
  id: string
  job_number: string
  title: string
  status: string
  priority: string
  customer_id: string | null
  project_id: string | null
  project_name?: string
  scheduled_start: string | null
  scheduled_end: string | null
  staff_assignments?: StaffAssignment[]
}

interface StaffAssignment {
  id: string
  user_id: string
  user_name?: string
  role: string
  assigned_at: string
}

interface ProjectGroup {
  project_id: string
  project_name: string
  jobs: Job[]
  totalHours: number
  totalCosts: number
  totalRevenue: number
  expanded: boolean
}

const STATUS_COLUMNS = [
  { key: 'draft', label: 'Draft', color: '#97A0AE' },
  { key: 'quoted', label: 'Quoted', color: '#2F62F0' },
  { key: 'accepted', label: 'Accepted', color: '#06B6D4' },
  { key: 'in_progress', label: 'In Progress', color: '#B5740F' },
  { key: 'completed', label: 'Completed', color: '#1F8A5B' },
  { key: 'invoiced', label: 'Invoiced', color: '#6D5AE6' },
  { key: 'cancelled', label: 'Cancelled', color: '#C8412F' },
]

type ViewMode = 'kanban' | 'hierarchy' | 'timeline'

export default function JobBoard() {
  const { isAllowed, isLoading: guardLoading, toasts, dismissToast } = useModuleGuard('jobs')
  const jobLabel = useTerm('job', 'Job')
  const projectLabel = useTerm('project', 'Project')

  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [draggedJob, setDraggedJob] = useState<Job | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('kanban')
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(new Set())

  const fetchJobs = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.get('/api/v2/jobs?page_size=200')
      setJobs(res.data?.jobs ?? [])
    } catch {
      setError('Failed to load jobs')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchJobs() }, [fetchJobs])

  /* ---- Drag-and-drop handlers ---- */

  const handleDragStart = (e: DragEvent<HTMLDivElement>, job: Job) => {
    setDraggedJob(job)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', job.id)
  }

  const handleDragOver = (e: DragEvent<HTMLDivElement>, targetStatus: string) => {
    e.preventDefault()
    if (!draggedJob) return
    e.dataTransfer.dropEffect = isValidStatusTransition(draggedJob.status, targetStatus) ? 'move' : 'none'
  }

  const handleDrop = async (e: DragEvent<HTMLDivElement>, targetStatus: string) => {
    e.preventDefault()
    if (!draggedJob) return
    if (!isValidStatusTransition(draggedJob.status, targetStatus)) {
      setError(`Cannot move from ${draggedJob.status} to ${targetStatus}`)
      setDraggedJob(null)
      return
    }
    try {
      await apiClient.put(`/api/v2/jobs/${draggedJob.id}/status`, { status: targetStatus })
      setJobs(prev =>
        prev.map(j => j.id === draggedJob.id ? { ...j, status: targetStatus } : j)
      )
      setError(null)
    } catch {
      setError('Failed to update job status')
    }
    setDraggedJob(null)
  }

  /* ---- Project hierarchy ---- */

  const projectGroups = useMemo<ProjectGroup[]>(() => {
    const groups: Record<string, ProjectGroup> = {}
    for (const job of jobs) {
      const pid = job.project_id || '__unassigned__'
      const pname = job.project_name || 'Unassigned'
      if (!groups[pid]) {
        groups[pid] = {
          project_id: pid,
          project_name: pname,
          jobs: [],
          totalHours: 0,
          totalCosts: 0,
          totalRevenue: 0,
          expanded: expandedProjects.has(pid),
        }
      }
      groups[pid].jobs.push(job)
    }
    return Object.values(groups)
  }, [jobs, expandedProjects])

  const toggleProject = (projectId: string) => {
    setExpandedProjects(prev => {
      const next = new Set(prev)
      if (next.has(projectId)) next.delete(projectId)
      else next.add(projectId)
      return next
    })
  }

  /* ---- Resource allocation timeline ---- */

  const staffTimeline = useMemo(() => {
    const staffMap: Record<string, { name: string; assignments: { job: Job; start: string; end: string }[] }> = {}
    for (const job of jobs) {
      if (!job.staff_assignments || !job.scheduled_start) continue
      for (const assignment of job.staff_assignments) {
        const uid = assignment.user_id
        if (!staffMap[uid]) {
          staffMap[uid] = { name: assignment.user_name || uid, assignments: [] }
        }
        staffMap[uid].assignments.push({
          job,
          start: job.scheduled_start!,
          end: job.scheduled_end || job.scheduled_start!,
        })
      }
    }
    // Detect conflicts
    const result: { userId: string; name: string; assignments: { job: Job; start: string; end: string; conflict: boolean }[] }[] = []
    for (const [userId, data] of Object.entries(staffMap)) {
      const sorted = [...data.assignments].sort((a, b) => a.start.localeCompare(b.start))
      const withConflict = sorted.map((a, i) => {
        let conflict = false
        for (let j = 0; j < sorted.length; j++) {
          if (i === j) continue
          if (a.start < sorted[j].end && sorted[j].start < a.end) {
            conflict = true
            break
          }
        }
        return { ...a, conflict }
      })
      result.push({ userId, name: data.name, assignments: withConflict })
    }
    return result
  }, [jobs])

  const jobsByStatus = (status: string) => jobs.filter(j => j.status === status)

  const TH = 'mono border-b border-border px-3 py-2.5 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

  if (guardLoading || loading) {
    return (
      <>
        <ToastContainer toasts={toasts} onDismiss={dismissToast} />
        <div role="status" aria-label="Loading jobs" className="py-16 text-center text-[13px] text-muted">Loading jobs…</div>
      </>
    )
  }

  if (!isAllowed) return <ToastContainer toasts={toasts} onDismiss={dismissToast} />

  return (
    <div className="page page-wide">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="page-head">
        <div>
          <div className="eyebrow">Work</div>
          <h1>{jobLabel} Board</h1>
          <p className="sub">Drag cards between columns to update status</p>
        </div>
      </div>

      {error && <div role="alert" className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger">{error}</div>}

      {/* View mode switcher (prototype .seg) */}
      <div className="mb-4 inline-flex overflow-hidden rounded-ctl border border-border">
        {(['kanban', 'hierarchy', 'timeline'] as const).map((mode, i) => (
          <button
            key={mode}
            onClick={() => setViewMode(mode)}
            aria-pressed={viewMode === mode}
            className={`min-h-[40px] px-4 text-[13px] font-medium transition-colors ${i > 0 ? 'border-l border-border' : ''} ${
              viewMode === mode ? 'bg-accent text-white' : 'bg-card text-muted hover:bg-canvas hover:text-text'
            }`}
          >
            {mode === 'kanban' ? 'Kanban' : mode === 'hierarchy' ? `${projectLabel} Hierarchy` : 'Resource Timeline'}
          </button>
        ))}
      </div>

      {/* Kanban view */}
      {viewMode === 'kanban' && (
        <div role="grid" aria-label="Job board" className="flex gap-3.5 overflow-x-auto pb-2">
          {STATUS_COLUMNS.map(col => (
            <div
              key={col.key}
              role="group"
              aria-label={`${col.label} column`}
              onDragOver={e => handleDragOver(e, col.key)}
              onDrop={e => handleDrop(e, col.key)}
              className="min-w-[248px] flex-[1_0_248px] rounded-card border border-border bg-canvas p-3"
            >
              <h2 className="mb-3 flex items-center gap-2 px-0.5 text-[12.5px] font-semibold" style={{ color: col.color }}>
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: col.color }} aria-hidden="true" />
                {col.label}
                <span className="mono ml-auto text-[11px] text-muted-2">{jobsByStatus(col.key).length}</span>
              </h2>
              {jobsByStatus(col.key).map(job => (
                <div
                  key={job.id}
                  draggable
                  onDragStart={e => handleDragStart(e, job)}
                  role="row"
                  aria-label={`${jobLabel} ${job.job_number}: ${job.title}`}
                  className="mb-2.5 cursor-grab rounded-ctl border border-border bg-card p-3 shadow-card active:cursor-grabbing"
                  style={{ borderLeft: `3px solid ${col.color}` }}
                >
                  <div className="mono text-[11px] text-muted">{job.job_number}</div>
                  <div className="my-1 text-[13px] font-semibold text-text">{job.title}</div>
                  {job.project_name && (
                    <div className="text-[11.5px] text-muted">{job.project_name}</div>
                  )}
                  {job.priority !== 'normal' && (
                    <span className="mt-1.5 inline-block text-[10px] font-semibold uppercase tracking-[0.05em] text-danger">
                      {job.priority}
                    </span>
                  )}
                </div>
              ))}
              {jobsByStatus(col.key).length === 0 && (
                <div className="py-4 text-center text-[12px] text-muted-2">No jobs</div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Project hierarchy view */}
      {viewMode === 'hierarchy' && (
        <div aria-label={`${projectLabel} hierarchy`}>
          {projectGroups.length === 0 ? (
            <p className="text-[13px] text-muted">No jobs found.</p>
          ) : (
            projectGroups.map(group => {
              const open = expandedProjects.has(group.project_id)
              return (
                <div key={group.project_id} className="mb-3.5 overflow-hidden rounded-card border border-border bg-card">
                  <button
                    onClick={() => toggleProject(group.project_id)}
                    aria-expanded={open}
                    aria-label={`Toggle ${group.project_name}`}
                    className="flex min-h-[44px] w-full items-center gap-2.5 bg-card px-[18px] py-3.5 text-left text-[14px] font-semibold text-text"
                  >
                    <span className="text-muted">{open ? '▼' : '▶'}</span>
                    {group.project_name}
                    <span className="text-[13px] font-normal text-muted-2">
                      {group.jobs.length} {group.jobs.length === 1 ? jobLabel.toLowerCase() : `${jobLabel.toLowerCase()}s`}
                    </span>
                  </button>
                  {open && (
                    <div className="px-[18px] pb-3.5">
                      <table role="grid" aria-label={`${group.project_name} jobs`} className="w-full border-collapse">
                        <thead>
                          <tr>
                            <th className={TH}>{jobLabel} #</th>
                            <th className={TH}>Title</th>
                            <th className={TH}>Status</th>
                            <th className={TH}>Priority</th>
                          </tr>
                        </thead>
                        <tbody>
                          {group.jobs.map(job => (
                            <tr key={job.id} className="border-b border-border last:border-b-0">
                              <td className="mono px-3 py-2.5 text-[13px] text-text">{job.job_number}</td>
                              <td className="px-3 py-2.5 text-[13.5px] text-text">{job.title}</td>
                              <td className="px-3 py-2.5 text-[13px] capitalize text-muted">{job.status.replace('_', ' ')}</td>
                              <td className="px-3 py-2.5 text-[13px] capitalize text-muted">{job.priority}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      )}

      {/* Resource allocation timeline view */}
      {viewMode === 'timeline' && (
        <div aria-label="Resource allocation timeline">
          {staffTimeline.length === 0 ? (
            <p className="text-[13px] text-muted">No staff assignments with scheduled dates found.</p>
          ) : (
            <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
              <table role="grid" aria-label="Staff resource timeline" className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className={TH}>Staff</th>
                    <th className={TH}>{jobLabel}</th>
                    <th className={TH}>Start</th>
                    <th className={TH}>End</th>
                    <th className={TH}>Conflict</th>
                  </tr>
                </thead>
                <tbody>
                  {staffTimeline.flatMap(staff =>
                    staff.assignments.map((a, i) => (
                      <tr
                        key={`${staff.userId}-${i}`}
                        className={`border-b border-border last:border-b-0 ${a.conflict ? 'bg-danger-soft' : ''}`}
                      >
                        {i === 0 && (
                          <td rowSpan={staff.assignments.length} className="px-3 py-2.5 align-top text-[13.5px] font-semibold text-text">
                            {staff.name}
                          </td>
                        )}
                        <td className="px-3 py-2.5 text-[13.5px] text-text">{a.job.job_number}: {a.job.title}</td>
                        <td className="mono px-3 py-2.5 text-[13px] text-muted">{new Date(a.start).toLocaleDateString()}</td>
                        <td className="mono px-3 py-2.5 text-[13px] text-muted">{new Date(a.end).toLocaleDateString()}</td>
                        <td className="px-3 py-2.5 text-[13px]">
                          {a.conflict && (
                            <span className="font-semibold text-danger" aria-label="Scheduling conflict">
                              ⚠ Conflict
                            </span>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
