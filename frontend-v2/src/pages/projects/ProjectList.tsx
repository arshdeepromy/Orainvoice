/**
 * Filterable list view for projects with search, status filter, and pagination.
 *
 * Validates: Requirement 14.1 (Project Module)
 */

import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import apiClient from '@/api/client'
import { useBranch } from '@/contexts/BranchContext'
import { Button } from '@/components/ui'

interface Project {
  id: string
  name: string
  customer_id: string | null
  status: string
  contract_value: string | null
  budget_amount: string | null
  start_date: string | null
  target_end_date: string | null
  created_at: string
  branch_id?: string | null
}

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'active', label: 'Active' },
  { value: 'completed', label: 'Completed' },
  { value: 'on_hold', label: 'On Hold' },
  { value: 'cancelled', label: 'Cancelled' },
]

const headerCell =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const inputClass =
  'min-h-[44px] rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent'
const labelClass = 'mb-1 block text-sm font-medium text-text'

export default function ProjectList() {
  const { branches: branchList } = useBranch()
  const [projects, setProjects] = useState<Project[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const pageSize = 20

  const fetchProjects = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      })
      if (search) params.set('search', search)
      if (statusFilter) params.set('status', statusFilter)

      const res = await apiClient.get(`/api/v2/projects?${params}`)
      setProjects(res.data?.projects ?? [])
      setTotal(res.data?.total ?? 0)
    } catch {
      setProjects([])
    } finally {
      setLoading(false)
    }
  }, [page, search, statusFilter])

  useEffect(() => { fetchProjects() }, [fetchProjects])

  const totalPages = Math.ceil(total / pageSize)

  if (loading) {
    return <div role="status" aria-label="Loading projects" className="py-12 text-center text-sm text-muted">Loading projects…</div>
  }

  return (
    <div className="space-y-4 px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-text">Projects</h1>

      {/* Filters */}
      <div className="flex flex-wrap gap-4">
        <div>
          <label htmlFor="project-search" className={labelClass}>Search projects</label>
          <input
            id="project-search"
            type="search"
            placeholder="Search by name…"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
            className={inputClass}
          />
        </div>
        <div>
          <label htmlFor="status-filter" className={labelClass}>Status</label>
          <select
            id="status-filter"
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(1) }}
            className={inputClass}
          >
            {STATUS_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Project table */}
      {projects.length === 0 ? (
        <p className="text-sm text-muted">No projects found. Create your first project to get started.</p>
      ) : (
        <>
          <div className="overflow-x-auto overflow-hidden rounded-card border border-border bg-card shadow-card">
            <table role="grid" aria-label="Projects list" className="w-full text-sm">
              <thead>
                <tr>
                  <th className={headerCell}>Name</th>
                  <th className={headerCell}>Branch</th>
                  <th className={headerCell}>Status</th>
                  <th className={headerCell}>Contract Value</th>
                  <th className={headerCell}>Budget</th>
                  <th className={headerCell}>Start Date</th>
                  <th className={headerCell}>End Date</th>
                </tr>
              </thead>
              <tbody>
                {projects.map(project => (
                  <tr key={project.id} role="row" className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="px-4 py-3"><Link to={`/projects/${project.id}`} className="text-accent hover:underline">{project.name}</Link></td>
                    <td className="px-4 py-3 text-text">{project.branch_id ? ((branchList ?? []).find(b => b.id === project.branch_id)?.name ?? '—') : '—'}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-block rounded-ctl bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent status-badge status-${project.status}`}>
                        {project.status.replace('_', ' ')}
                      </span>
                    </td>
                    <td className="mono px-4 py-3 text-text">{project.contract_value ? `${Number(project.contract_value).toLocaleString()}` : '—'}</td>
                    <td className="mono px-4 py-3 text-text">{project.budget_amount ? `${Number(project.budget_amount).toLocaleString()}` : '—'}</td>
                    <td className="mono px-4 py-3 text-text">{project.start_date ? new Date(project.start_date).toLocaleDateString() : '—'}</td>
                    <td className="mono px-4 py-3 text-text">{project.target_end_date ? new Date(project.target_end_date).toLocaleDateString() : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <nav aria-label="Pagination" className="flex items-center gap-3">
              <Button variant="ghost" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
                Previous
              </Button>
              <span className="text-sm text-muted">Page {page} of {totalPages}</span>
              <Button variant="ghost" size="sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
                Next
              </Button>
            </nav>
          )}
        </>
      )}
    </div>
  )
}
