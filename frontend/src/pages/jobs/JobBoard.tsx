/**
 * Kanban board view for jobs with drag-and-drop status changes.
 *
 * Validates: Requirement 11.4
 */

import React, { useEffect, useState, useCallback, DragEvent } from 'react'
import apiClient from '@/api/client'

interface Job {
  id: string
  job_number: string
  title: string
  status: string
  priority: string
  customer_id: string | null
  scheduled_start: string | null
  scheduled_end: string | null
}

const STATUS_COLUMNS = [
  { key: 'draft', label: 'Draft', color: '#6B7280' },
  { key: 'scheduled', label: 'Scheduled', color: '#3B82F6' },
  { key: 'in_progress', label: 'In Progress', color: '#F59E0B' },
  { key: 'on_hold', label: 'On Hold', color: '#EF4444' },
  { key: 'completed', label: 'Completed', color: '#10B981' },
  { key: 'invoiced', label: 'Invoiced', color: '#8B5CF6' },
  { key: 'cancelled', label: 'Cancelled', color: '#9CA3AF' },
]

const VALID_TRANSITIONS: Record<string, string[]> = {
  draft: ['scheduled', 'cancelled'],
  scheduled: ['in_progress', 'cancelled'],
  in_progress: ['on_hold', 'completed', 'cancelled'],
  on_hold: ['in_progress', 'cancelled'],
  completed: ['invoiced', 'cancelled'],
  invoiced: ['cancelled'],
  cancelled: [],
}

export default function JobBoard() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [draggedJob, setDraggedJob] = useState<Job | null>(null)

  const fetchJobs = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.get('/api/v2/jobs?page_size=200')
      setJobs(res.data.jobs)
    } catch {
      setError('Failed to load jobs')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchJobs() }, [fetchJobs])

  const handleDragStart = (e: DragEvent<HTMLDivElement>, job: Job) => {
    setDraggedJob(job)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', job.id)
  }

  const handleDragOver = (e: DragEvent<HTMLDivElement>, targetStatus: string) => {
    e.preventDefault()
    if (!draggedJob) return
    const allowed = VALID_TRANSITIONS[draggedJob.status] || []
    e.dataTransfer.dropEffect = allowed.includes(targetStatus) ? 'move' : 'none'
  }

  const handleDrop = async (e: DragEvent<HTMLDivElement>, targetStatus: string) => {
    e.preventDefault()
    if (!draggedJob) return
    const allowed = VALID_TRANSITIONS[draggedJob.status] || []
    if (!allowed.includes(targetStatus)) {
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

  const jobsByStatus = (status: string) => jobs.filter(j => j.status === status)

  if (loading) {
    return <div role="status" aria-label="Loading jobs">Loading jobs…</div>
  }

  return (
    <div>
      <h1>Job Board</h1>
      {error && <div role="alert" className="error-banner">{error}</div>}
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
                aria-label={`Job ${job.job_number}: ${job.title}`}
                style={{
                  background: '#fff',
                  borderRadius: 6,
                  padding: '0.5rem',
                  marginBottom: '0.5rem',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
                  cursor: 'grab',
                  borderLeft: `3px solid ${col.color}`,
                }}
              >
                <div style={{ fontWeight: 600, fontSize: '0.8rem' }}>{job.job_number}</div>
                <div style={{ fontSize: '0.85rem' }}>{job.title}</div>
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
    </div>
  )
}
