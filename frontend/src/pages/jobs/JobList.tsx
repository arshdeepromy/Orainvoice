/**
 * Filterable list view for jobs with search, status filter, and pagination.
 *
 * Validates: Requirement 11.4
 */

import React, { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

interface Job {
  id: string
  job_number: string
  title: string
  status: string
  priority: string
  customer_id: string | null
  scheduled_start: string | null
  created_at: string
}

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'draft', label: 'Draft' },
  { value: 'scheduled', label: 'Scheduled' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'on_hold', label: 'On Hold' },
  { value: 'completed', label: 'Completed' },
  { value: 'invoiced', label: 'Invoiced' },
  { value: 'cancelled', label: 'Cancelled' },
]

export default function JobList() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
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

  useEffect(() => { fetchJobs() }, [fetchJobs])

  const totalPages = Math.ceil(total / pageSize)

  if (loading) {
    return <div role="status" aria-label="Loading jobs">Loading jobs…</div>
  }

  return (
    <div>
      <h1>Jobs</h1>

      {/* Filters */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
        <div>
          <label htmlFor="job-search">Search jobs</label>
          <input
            id="job-search"
            type="search"
            placeholder="Search by title or number…"
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

      {/* Job table */}
      {jobs.length === 0 ? (
        <p>No jobs found. Create your first job to get started.</p>
      ) : (
        <>
          <table role="grid" aria-label="Jobs list">
            <thead>
              <tr>
                <th>Job #</th>
                <th>Title</th>
                <th>Status</th>
                <th>Priority</th>
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
              >
                Previous
              </button>
              <span>Page {page} of {totalPages}</span>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage(p => p + 1)}
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
