/**
 * Enhanced filterable list view for jobs with V2 features:
 * - Project hierarchy view with expandable/collapsible nodes
 * - Search, status filter, and pagination
 * - Job template selection dropdown on creation
 * - Context integration (TerminologyContext, FeatureFlagContext, useModuleGuard)
 *
 * Validates: Requirements 8.1, 8.2, 8.7
 */

import React, { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { useFlag } from '@/contexts/FeatureFlagContext'
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
  const jobsV2Enabled = useFlag('jobs_v2')
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
      setJobs(res.data.jobs)
      setTotal(res.data.total)
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h1>{jobLabel}s</h1>
        <button
          onClick={() => setShowCreateForm(!showCreateForm)}
          style={{ minWidth: 44, minHeight: 44 }}
        >
          New {jobLabel}
        </button>
      </div>

      {/* Template selection for new job */}
      {showCreateForm && templates.length > 0 && (
        <div style={{ marginBottom: '1rem', padding: '1rem', background: '#f9fafb', borderRadius: 8 }}>
          <label htmlFor="template-select">{jobLabel} Template</label>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginTop: '0.5rem' }}>
            <select
              id="template-select"
              value={selectedTemplate}
              onChange={e => setSelectedTemplate(e.target.value)}
              style={{ minHeight: 44 }}
            >
              <option value="">Select a template…</option>
              {templates.map(t => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
            <button
              onClick={handleCreateFromTemplate}
              disabled={!selectedTemplate}
              style={{ minWidth: 44, minHeight: 44 }}
            >
              Create from Template
            </button>
          </div>
        </div>
      )}

      {/* Filters */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        <div>
          <label htmlFor="job-search">Search jobs</label>
          <input
            id="job-search"
            type="search"
            placeholder="Search by title or number…"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
            style={{ minHeight: 44 }}
          />
        </div>
        <div>
          <label htmlFor="status-filter">Status</label>
          <select
            id="status-filter"
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(1) }}
            style={{ minHeight: 44 }}
          >
            {STATUS_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minHeight: 44 }}>
            <input
              type="checkbox"
              checked={groupByProject}
              onChange={e => setGroupByProject(e.target.checked)}
            />
            Group by {projectLabel}
          </label>
        </div>
      </div>

      {/* Job table */}
      {jobs.length === 0 ? (
        <p>No jobs found. Create your first {jobLabel.toLowerCase()} to get started.</p>
      ) : groupByProject && projectGroups ? (
        /* Project-grouped view */
        <div aria-label={`${jobLabel}s grouped by ${projectLabel.toLowerCase()}`}>
          {projectGroups.map(([pid, group]) => (
            <div key={pid} style={{ marginBottom: '1rem', border: '1px solid #e5e7eb', borderRadius: 8 }}>
              <button
                onClick={() => toggleProject(pid)}
                aria-expanded={expandedProjects.has(pid)}
                aria-label={`Toggle ${group.name}`}
                style={{
                  width: '100%',
                  display: 'flex',
                  justifyContent: 'space-between',
                  padding: '0.75rem 1rem',
                  background: '#f9fafb',
                  border: 'none',
                  cursor: 'pointer',
                  minHeight: 44,
                  fontWeight: 600,
                }}
              >
                <span>
                  {expandedProjects.has(pid) ? '▼' : '▶'} {group.name} ({group.jobs.length})
                </span>
              </button>
              {expandedProjects.has(pid) && (
                <table role="grid" aria-label={`${group.name} jobs`} style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: 'left', padding: '0.5rem' }}>{jobLabel} #</th>
                      <th style={{ textAlign: 'left', padding: '0.5rem' }}>Title</th>
                      <th style={{ textAlign: 'left', padding: '0.5rem' }}>Status</th>
                      <th style={{ textAlign: 'left', padding: '0.5rem' }}>Priority</th>
                      <th style={{ textAlign: 'left', padding: '0.5rem' }}>Scheduled</th>
                      <th style={{ textAlign: 'left', padding: '0.5rem' }}>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.jobs.map(job => (
                      <tr key={job.id} role="row">
                        <td style={{ padding: '0.5rem' }}>{job.job_number}</td>
                        <td style={{ padding: '0.5rem' }}>{job.title}</td>
                        <td style={{ padding: '0.5rem' }}>
                          <span className={`status-badge status-${job.status}`}>
                            {job.status.replace('_', ' ')}
                          </span>
                        </td>
                        <td style={{ padding: '0.5rem' }}>{job.priority}</td>
                        <td style={{ padding: '0.5rem' }}>{job.scheduled_start ? new Date(job.scheduled_start).toLocaleDateString() : '—'}</td>
                        <td style={{ padding: '0.5rem' }}>{new Date(job.created_at).toLocaleDateString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      ) : (
        /* Flat table view */
        <>
          <table role="grid" aria-label="Jobs list">
            <thead>
              <tr>
                <th>{jobLabel} #</th>
                <th>Title</th>
                <th>Status</th>
                <th>Priority</th>
                <th>{projectLabel}</th>
                <th>Scheduled</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map(job => (
                <tr key={job.id} role="row">
                  <td>{job.job_number}</td>
                  <td>{job.title}</td>
                  <td>
                    <span className={`status-badge status-${job.status}`}>
                      {job.status.replace('_', ' ')}
                    </span>
                  </td>
                  <td>{job.priority}</td>
                  <td>{job.project_name || '—'}</td>
                  <td>{job.scheduled_start ? new Date(job.scheduled_start).toLocaleDateString() : '—'}</td>
                  <td>{new Date(job.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Pagination */}
          {totalPages > 1 && (
            <nav aria-label="Pagination">
              <button
                disabled={page <= 1}
                onClick={() => setPage(p => p - 1)}
                style={{ minWidth: 44, minHeight: 44 }}
              >
                Previous
              </button>
              <span>Page {page} of {totalPages}</span>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage(p => p + 1)}
                style={{ minWidth: 44, minHeight: 44 }}
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
