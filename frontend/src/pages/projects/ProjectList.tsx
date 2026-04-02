/**
 * Filterable list view for projects with search, status filter, and pagination.
 *
 * Validates: Requirement 14.1 (Project Module)
 */

import React, { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'
import { useBranch } from '@/contexts/BranchContext'

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
    return <div role="status" aria-label="Loading projects">Loading projects…</div>
  }

  return (
    <div>
      <h1>Projects</h1>

      {/* Filters */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
        <div>
          <label htmlFor="project-search">Search projects</label>
          <input
            id="project-search"
            type="search"
            placeholder="Search by name…"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
          />
        </div>
        <div>
          <label htmlFor="status-filter">Status</label>
          <select
            id="status-filter"
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(1) }}
          >
            {STATUS_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Project table */}
      {projects.length === 0 ? (
        <p>No projects found. Create your first project to get started.</p>
      ) : (
        <>
          <table role="grid" aria-label="Projects list">
            <thead>
              <tr>
                <th>Name</th>
                <th>Branch</th>
                <th>Status</th>
                <th>Contract Value</th>
                <th>Budget</th>
                <th>Start Date</th>
                <th>End Date</th>
              </tr>
            </thead>
            <tbody>
              {projects.map(project => (
                <tr key={project.id} role="row">
                  <td>{project.name}</td>
                  <td>{project.branch_id ? ((branchList ?? []).find(b => b.id === project.branch_id)?.name ?? '—') : '—'}</td>
                  <td>
                    <span className={`status-badge status-${project.status}`}>
                      {project.status.replace('_', ' ')}
                    </span>
                  </td>
                  <td>{project.contract_value ? `$${Number(project.contract_value).toLocaleString()}` : '—'}</td>
                  <td>{project.budget_amount ? `$${Number(project.budget_amount).toLocaleString()}` : '—'}</td>
                  <td>{project.start_date ? new Date(project.start_date).toLocaleDateString() : '—'}</td>
                  <td>{project.target_end_date ? new Date(project.target_end_date).toLocaleDateString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Pagination */}
          {totalPages > 1 && (
            <nav aria-label="Pagination">
              <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
                Previous
              </button>
              <span>Page {page} of {totalPages}</span>
              <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
                Next
              </button>
            </nav>
          )}
        </>
      )}
    </div>
  )
}
