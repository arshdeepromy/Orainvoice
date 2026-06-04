/**
 * JobList — Task 26 port of frontend/src/pages/jobs/JobList.tsx.
 *
 * Filterable list view for jobs (v2) with project-hierarchy grouping. ALL logic
 * copied VERBATIM: module guard + terminology labels, the paginated fetch
 * (GET /api/v2/jobs?page&page_size&search&status), the job-template dropdown
 * (GET /api/v2/job-templates → POST /api/v2/jobs { template_id }), the search /
 * status filters, the group-by-project expand/collapse, and pagination.
 * Presentation remapped from inline styles onto the design tokens (FR-2b):
 * `page page-wide` head, token toolbar inputs, a card-wrapped token table,
 * accordion project groups, and ds.css pagination footer.
 *
 * Validates: Requirements 8.1, 8.2, 8.7
 */

import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { useTerm } from '@/contexts/TerminologyContext'
import { ToastContainer } from '@/components/ui/Toast'

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
  created_at: string
}

interface JobTemplate {
  id: string
  name: string
  description: string
}

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'draft', label: 'Draft' },
  { value: 'quoted', label: 'Quoted' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'on_hold', label: 'On Hold' },
  { value: 'completed', label: 'Completed' },
  { value: 'invoiced', label: 'Invoiced' },
  { value: 'cancelled', label: 'Cancelled' },
]

export default function JobList() {
  const { isAllowed, isLoading: guardLoading, toasts, dismissToast } = useModuleGuard('jobs')
  const jobLabel = useTerm('job', 'Job')
  const projectLabel = useTerm('project', 'Project')

  const [jobs, setJobs] = useState<Job[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [groupByProject, setGroupByProject] = useState(false)
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(new Set())
  const [templates, setTemplates] = useState<JobTemplate[]>([])
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const pageSize = 20

  const fetchJobs = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      })
      if (search) params.set('search', search)
      if (statusFilter) params.set('status', statusFilter)

      const res = await apiClient.get(`/api/v2/jobs?${params}`)
      setJobs(res.data?.jobs ?? [])
      setTotal(res.data?.total ?? 0)
    } catch {
      setJobs([])
    } finally {
      setLoading(false)
    }
  }, [page, search, statusFilter])

  const fetchTemplates = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/job-templates')
      setTemplates(res.data.templates || res.data || [])
    } catch {
      setTemplates([])
    }
  }, [])

  useEffect(() => { fetchJobs() }, [fetchJobs])
  useEffect(() => { fetchTemplates() }, [fetchTemplates])

  const totalPages = Math.ceil(total / pageSize)

  const toggleProject = (projectId: string) => {
    setExpandedProjects(prev => {
      const next = new Set(prev)
      if (next.has(projectId)) next.delete(projectId)
      else next.add(projectId)
      return next
    })
  }

  /* Group jobs by project */
  const projectGroups = (() => {
    if (!groupByProject) return null
    const groups: Record<string, { name: string; jobs: Job[] }> = {}
    for (const job of jobs) {
      const pid = job.project_id || '__unassigned__'
      const pname = job.project_name || 'Unassigned'
      if (!groups[pid]) groups[pid] = { name: pname, jobs: [] }
      groups[pid].jobs.push(job)
    }
    return Object.entries(groups)
  })()

  const handleCreateFromTemplate = async () => {
    if (!selectedTemplate) return
    try {
      await apiClient.post('/api/v2/jobs', { template_id: selectedTemplate })
      setShowCreateForm(false)
      setSelectedTemplate('')
      fetchJobs()
    } catch {
      // Error handled silently
    }
  }

  const TH = 'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
  const SELECT_CLS = 'h-[42px] appearance-none rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'

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
          <h1>{jobLabel}s</h1>
        </div>
        <div className="head-actions">
          <button
            onClick={() => setShowCreateForm(!showCreateForm)}
            className="inline-flex min-h-[40px] items-center rounded-ctl bg-accent px-4 text-[13px] font-semibold text-white transition-colors hover:bg-accent-press"
          >
            New {jobLabel}
          </button>
        </div>
      </div>

      {/* Template selection for new job */}
      {showCreateForm && templates.length > 0 && (
        <div className="mb-4 rounded-card border border-border bg-canvas p-4">
          <label htmlFor="template-select" className="text-[12.5px] font-medium text-text">{jobLabel} Template</label>
          <div className="mt-2 flex items-center gap-2">
            <select
              id="template-select"
              value={selectedTemplate}
              onChange={e => setSelectedTemplate(e.target.value)}
              className={SELECT_CLS}
            >
              <option value="">Select a template…</option>
              {templates.map(t => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
            <button
              onClick={handleCreateFromTemplate}
              disabled={!selectedTemplate}
              className="inline-flex min-h-[40px] items-center rounded-ctl bg-accent px-4 text-[13px] font-semibold text-white transition-colors hover:bg-accent-press disabled:pointer-events-none disabled:opacity-60"
            >
              Create from Template
            </button>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-[7px]">
          <label htmlFor="job-search" className="text-[12.5px] font-medium text-text">Search jobs</label>
          <input
            id="job-search"
            type="search"
            placeholder="Search by title or number…"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
            className="h-[42px] rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          />
        </div>
        <div className="flex flex-col gap-[7px]">
          <label htmlFor="status-filter" className="text-[12.5px] font-medium text-text">Status</label>
          <select
            id="status-filter"
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(1) }}
            className={SELECT_CLS}
          >
            {STATUS_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <label className="flex min-h-[44px] items-center gap-2 text-[13px] text-text">
          <input
            type="checkbox"
            checked={groupByProject}
            onChange={e => setGroupByProject(e.target.checked)}
            className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
          />
          Group by {projectLabel}
        </label>
      </div>

      {/* Job table */}
      {jobs.length === 0 ? (
        <p className="py-12 text-center text-[13px] text-muted">No jobs found. Create your first {jobLabel.toLowerCase()} to get started.</p>
      ) : groupByProject && projectGroups ? (
        /* Project-grouped view */
        <div aria-label={`${jobLabel}s grouped by ${projectLabel.toLowerCase()}`}>
          {projectGroups.map(([pid, group]) => {
            const open = expandedProjects.has(pid)
            return (
              <div key={pid} className="mb-4 overflow-hidden rounded-card border border-border bg-card">
                <button
                  onClick={() => toggleProject(pid)}
                  aria-expanded={open}
                  aria-label={`Toggle ${group.name}`}
                  className="flex min-h-[44px] w-full items-center justify-between bg-card px-4 py-3.5 text-[13.5px] font-semibold text-text"
                >
                  <span>{open ? '▼' : '▶'} {group.name} ({group.jobs.length})</span>
                </button>
                {open && (
                  <table role="grid" aria-label={`${group.name} jobs`} className="w-full border-collapse">
                    <thead>
                      <tr>
                        <th className={TH}>{jobLabel} #</th>
                        <th className={TH}>Title</th>
                        <th className={TH}>Status</th>
                        <th className={TH}>Priority</th>
                        <th className={TH}>Scheduled</th>
                        <th className={TH}>Created</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.jobs.map(job => (
                        <tr key={job.id} role="row" className="border-b border-border last:border-b-0">
                          <td className="mono px-4 py-3 text-[13px] text-text">{job.job_number}</td>
                          <td className="px-4 py-3 text-[13.5px] text-text">{job.title}</td>
                          <td className="px-4 py-3 text-[13px] capitalize text-muted">{job.status.replace('_', ' ')}</td>
                          <td className="px-4 py-3 text-[13px] capitalize text-muted">{job.priority}</td>
                          <td className="mono px-4 py-3 text-[13px] text-muted">{job.scheduled_start ? new Date(job.scheduled_start).toLocaleDateString() : '—'}</td>
                          <td className="mono px-4 py-3 text-[13px] text-muted">{new Date(job.created_at).toLocaleDateString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        /* Flat table view */
        <>
          <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <div className="overflow-x-auto">
              <table role="grid" aria-label="Jobs list" className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className={TH}>{jobLabel} #</th>
                    <th className={TH}>Title</th>
                    <th className={TH}>Status</th>
                    <th className={TH}>Priority</th>
                    <th className={TH}>{projectLabel}</th>
                    <th className={TH}>Scheduled</th>
                    <th className={TH}>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map(job => (
                    <tr key={job.id} role="row" className="border-b border-border last:border-b-0 hover:bg-canvas">
                      <td className="mono px-4 py-3 text-[13px] text-text">{job.job_number}</td>
                      <td className="px-4 py-3 text-[13.5px] text-text">{job.title}</td>
                      <td className="px-4 py-3 text-[13px] capitalize text-muted">{job.status.replace('_', ' ')}</td>
                      <td className="px-4 py-3 text-[13px] capitalize text-muted">{job.priority}</td>
                      <td className="px-4 py-3 text-[13.5px] text-muted">{job.project_name || '—'}</td>
                      <td className="mono px-4 py-3 text-[13px] text-muted">{job.scheduled_start ? new Date(job.scheduled_start).toLocaleDateString() : '—'}</td>
                      <td className="mono px-4 py-3 text-[13px] text-muted">{new Date(job.created_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* Pagination */}
          {totalPages > 1 && (
            <nav aria-label="Pagination" className="mt-4 flex items-center justify-end gap-3">
              <button
                disabled={page <= 1}
                onClick={() => setPage(p => p - 1)}
                className="inline-flex min-h-[36px] items-center rounded-ctl border border-border bg-card px-3 text-[13px] text-text transition-colors hover:bg-canvas disabled:pointer-events-none disabled:opacity-50"
              >
                Previous
              </button>
              <span className="text-[12.5px] text-muted">Page <span className="mono text-text">{page}</span> of <span className="mono text-text">{totalPages}</span></span>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage(p => p + 1)}
                className="inline-flex min-h-[36px] items-center rounded-ctl border border-border bg-card px-3 text-[13px] text-text transition-colors hover:bg-canvas disabled:pointer-events-none disabled:opacity-50"
              >
                Next
              </button>
            </nav>
          )}
        </>
      )}
    </div>
  )
}
