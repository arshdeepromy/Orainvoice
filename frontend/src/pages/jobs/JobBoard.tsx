/**
 * Enhanced Kanban board view for jobs with V2 features:
 * - Project hierarchy view with expandable/collapsible nodes
 * - Drag-and-drop Kanban with status transition validation
 * - Resource allocation timeline view with conflict highlighting
 * - Context integration (TerminologyContext, FeatureFlagContext, useModuleGuard)
 *
 * Validates: Requirements 8.1, 8.2, 8.3, 8.4
 */

import { useEffect, useState, useCallback, DragEvent, useMemo } from 'react'
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
  { key: 'draft', label: 'Draft', color: '#6B7280' },
  { key: 'quoted', label: 'Quoted', color: '#3B82F6' },
  { key: 'accepted', label: 'Accepted', color: '#06B6D4' },
  { key: 'in_progress', label: 'In Progress', color: '#F59E0B' },
  { key: 'completed', label: 'Completed', color: '#10B981' },
  { key: 'invoiced', label: 'Invoiced', color: '#8B5CF6' },
  { key: 'cancelled', label: 'Cancelled', color: '#9CA3AF' },
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

  if (guardLoading || loading) {
    return (
      <>
        <ToastContainer toasts={toasts} onDismiss={dismissToast} />
        <div role="status" aria-label="Loading jobs">Loading jobs…</div>
      </>
    )
  }

  if (!isAllowed) return <ToastContainer toasts={toasts} onDismiss={dismissToast} />

  return (
    <div>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <h1>{jobLabel} Board</h1>
      {error && <div role="alert" className="error-banner">{error}</div>}

      {/* View mode switcher */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
        <button
          onClick={() => setViewMode('kanban')}
          aria-pressed={viewMode === 'kanban'}
          style={{ minWidth: 44, minHeight: 44, fontWeight: viewMode === 'kanban' ? 700 : 400 }}
        >
          Kanban
        </button>
        <button
          onClick={() => setViewMode('hierarchy')}
          aria-pressed={viewMode === 'hierarchy'}
          style={{ minWidth: 44, minHeight: 44, fontWeight: viewMode === 'hierarchy' ? 700 : 400 }}
        >
          {projectLabel} Hierarchy
        </button>
        <button
          onClick={() => setViewMode('timeline')}
          aria-pressed={viewMode === 'timeline'}
          style={{ minWidth: 44, minHeight: 44, fontWeight: viewMode === 'timeline' ? 700 : 400 }}
        >
          Resource Timeline
        </button>
      </div>

      {/* Kanban view */}
      {viewMode === 'kanban' && (
        <div
          role="grid"
          aria-label="Job board"
          style={{ display: 'flex', gap: '1rem', overflowX: 'auto', padding: '1rem 0' }}
        >
          {STATUS_COLUMNS.map(col => (
            <div
              key={col.key}
              role="group"
              aria-label={`${col.label} column`}
              onDragOver={e => handleDragOver(e, col.key)}
              onDrop={e => handleDrop(e, col.key)}
              style={{
                minWidth: 220,
                flex: '1 0 220px',
                background: '#f9fafb',
                borderRadius: 8,
                padding: '0.75rem',
              }}
            >
              <h2 style={{ fontSize: '0.875rem', color: col.color, marginBottom: '0.5rem' }}>
                {col.label}
                <span style={{ marginLeft: 8, color: '#9CA3AF' }}>
                  ({jobsByStatus(col.key).length})
                </span>
              </h2>
              {jobsByStatus(col.key).map(job => (
                <div
                  key={job.id}
                  draggable
                  onDragStart={e => handleDragStart(e, job)}
                  role="row"
                  aria-label={`${jobLabel} ${job.job_number}: ${job.title}`}
                  style={{
                    background: '#fff',
                    borderRadius: 6,
                    padding: '0.5rem',
                    marginBottom: '0.5rem',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
                    cursor: 'grab',
                    borderLeft: `3px solid ${col.color}`,
                    minHeight: 44,
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: '0.8rem' }}>{job.job_number}</div>
                  <div style={{ fontSize: '0.85rem' }}>{job.title}</div>
                  {job.project_name && (
                    <div style={{ fontSize: '0.75rem', color: '#6B7280' }}>{job.project_name}</div>
                  )}
                  {job.priority !== 'normal' && (
                    <span style={{ fontSize: '0.75rem', color: '#EF4444' }}>
                      {job.priority}
                    </span>
                  )}
                </div>
              ))}
              {jobsByStatus(col.key).length === 0 && (
                <div style={{ color: '#9CA3AF', fontSize: '0.8rem', textAlign: 'center', padding: '1rem' }}>
                  No jobs
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Project hierarchy view */}
      {viewMode === 'hierarchy' && (
        <div aria-label={`${projectLabel} hierarchy`}>
          {projectGroups.length === 0 ? (
            <p>No jobs found.</p>
          ) : (
            projectGroups.map(group => (
              <div
                key={group.project_id}
                style={{ marginBottom: '1rem', border: '1px solid #e5e7eb', borderRadius: 8, overflow: 'hidden' }}
              >
                <button
                  onClick={() => toggleProject(group.project_id)}
                  aria-expanded={expandedProjects.has(group.project_id)}
                  aria-label={`Toggle ${group.project_name}`}
                  style={{
                    width: '100%',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '0.75rem 1rem',
                    background: '#f9fafb',
                    border: 'none',
                    cursor: 'pointer',
                    minHeight: 44,
                    fontSize: '1rem',
                    fontWeight: 600,
                  }}
                >
                  <span>
                    {expandedProjects.has(group.project_id) ? '▼' : '▶'}{' '}
                    {group.project_name} ({group.jobs.length} {group.jobs.length === 1 ? jobLabel.toLowerCase() : `${jobLabel.toLowerCase()}s`})
                  </span>
                </button>
                {expandedProjects.has(group.project_id) && (
                  <div style={{ padding: '0.5rem 1rem' }}>
                    <table role="grid" aria-label={`${group.project_name} jobs`} style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <thead>
                        <tr>
                          <th style={{ textAlign: 'left', padding: '0.5rem' }}>{jobLabel} #</th>
                          <th style={{ textAlign: 'left', padding: '0.5rem' }}>Title</th>
                          <th style={{ textAlign: 'left', padding: '0.5rem' }}>Status</th>
                          <th style={{ textAlign: 'left', padding: '0.5rem' }}>Priority</th>
                        </tr>
                      </thead>
                      <tbody>
                        {group.jobs.map(job => (
                          <tr key={job.id}>
                            <td style={{ padding: '0.5rem' }}>{job.job_number}</td>
                            <td style={{ padding: '0.5rem' }}>{job.title}</td>
                            <td style={{ padding: '0.5rem' }}>
                              <span className={`status-badge status-${job.status}`}>
                                {job.status.replace('_', ' ')}
                              </span>
                            </td>
                            <td style={{ padding: '0.5rem' }}>{job.priority}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}

      {/* Resource allocation timeline view */}
      {viewMode === 'timeline' && (
        <div aria-label="Resource allocation timeline">
          {staffTimeline.length === 0 ? (
            <p>No staff assignments with scheduled dates found.</p>
          ) : (
            <table role="grid" aria-label="Staff resource timeline" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', padding: '0.5rem' }}>Staff</th>
                  <th style={{ textAlign: 'left', padding: '0.5rem' }}>{jobLabel}</th>
                  <th style={{ textAlign: 'left', padding: '0.5rem' }}>Start</th>
                  <th style={{ textAlign: 'left', padding: '0.5rem' }}>End</th>
                  <th style={{ textAlign: 'left', padding: '0.5rem' }}>Conflict</th>
                </tr>
              </thead>
              <tbody>
                {staffTimeline.flatMap(staff =>
                  staff.assignments.map((a, i) => (
                    <tr
                      key={`${staff.userId}-${i}`}
                      style={{ background: a.conflict ? '#FEF2F2' : undefined }}
                    >
                      {i === 0 && (
                        <td rowSpan={staff.assignments.length} style={{ padding: '0.5rem', fontWeight: 600, verticalAlign: 'top' }}>
                          {staff.name}
                        </td>
                      )}
                      <td style={{ padding: '0.5rem' }}>{a.job.job_number}: {a.job.title}</td>
                      <td style={{ padding: '0.5rem' }}>{new Date(a.start).toLocaleDateString()}</td>
                      <td style={{ padding: '0.5rem' }}>{new Date(a.end).toLocaleDateString()}</td>
                      <td style={{ padding: '0.5rem' }}>
                        {a.conflict && (
                          <span style={{ color: '#EF4444', fontWeight: 600 }} aria-label="Scheduling conflict">
                            ⚠ Conflict
                          </span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
