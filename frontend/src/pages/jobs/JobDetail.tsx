/**
 * Job detail page with full form, checklist, attachments,
 * status timeline, and convert-to-invoice button.
 *
 * Validates: Requirement 11.1, 11.5, 11.6, 11.7
 */

import React, { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

interface JobData {
  id: string
  org_id: string
  job_number: string
  title: string
  description: string | null
  status: string
  priority: string
  customer_id: string | null
  location_id: string | null
  site_address: string | null
  scheduled_start: string | null
  scheduled_end: string | null
  actual_start: string | null
  actual_end: string | null
  checklist: ChecklistItem[]
  internal_notes: string | null
  customer_notes: string | null
  converted_invoice_id: string | null
  created_at: string
  updated_at: string
  staff_assignments: StaffAssignment[]
}

interface ChecklistItem {
  text: string
  completed: boolean
}

interface StaffAssignment {
  id: string
  user_id: string
  role: string
  assigned_at: string
}

interface Attachment {
  id: string
  file_name: string
  file_size: number
  content_type: string | null
  uploaded_at: string
}

interface StatusHistoryEntry {
  id: string
  from_status: string | null
  to_status: string
  changed_at: string
  notes: string | null
}

interface Props {
  jobId?: string
}

const TABS = ['Details', 'Checklist', 'Attachments', 'Timeline'] as const
type Tab = typeof TABS[number]

export default function JobDetail({ jobId }: Props) {
  const [job, setJob] = useState<JobData | null>(null)
  const [loading, setLoading] = useState(!!jobId)
  const [activeTab, setActiveTab] = useState<Tab>('Details')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [history, setHistory] = useState<StatusHistoryEntry[]>([])
  const [error, setError] = useState<string | null>(null)

  // Form state for create mode
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState('normal')
  const [siteAddress, setSiteAddress] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  const isCreate = !jobId

  const fetchJob = useCallback(async () => {
    if (!jobId) return
    setLoading(true)
    try {
      const [jobRes, attachRes, histRes] = await Promise.all([
        apiClient.get(`/api/v2/jobs/${jobId}`),
        apiClient.get(`/api/v2/jobs/${jobId}/attachments`),
        apiClient.get(`/api/v2/jobs/${jobId}/history`),
      ])
      setJob(jobRes.data)
      setAttachments(attachRes.data)
      setHistory(histRes.data)
    } catch {
      setError('Failed to load job')
    } finally {
      setLoading(false)
    }
  }, [jobId])

  useEffect(() => { fetchJob() }, [fetchJob])

  const handleCreate = async () => {
    setFormError(null)
    if (!title.trim()) {
      setFormError('Job title is required.')
      return
    }
    try {
      await apiClient.post('/api/v2/jobs', {
        title, description, priority, site_address: siteAddress || null,
      })
    } catch {
      setFormError('Failed to create job')
    }
  }

  const handleConvertToInvoice = async () => {
    if (!job) return
    try {
      await apiClient.post(`/api/v2/jobs/${job.id}/convert-to-invoice`, {
        time_entries: [], expenses: [], materials: [],
      })
      await fetchJob()
    } catch {
      setError('Failed to convert to invoice')
    }
  }

  const handleUploadAttachment = async (file: File) => {
    if (!job) return
    try {
      await apiClient.post(`/api/v2/jobs/${job.id}/attachments`, {
        file_key: `uploads/${file.name}`,
        file_name: file.name,
        file_size: file.size,
        content_type: file.type,
      })
      const res = await apiClient.get(`/api/v2/jobs/${job.id}/attachments`)
      setAttachments(res.data)
    } catch {
      setError('Failed to upload attachment')
    }
  }

  if (loading) {
    return <div role="status" aria-label="Loading job">Loading job…</div>
  }

  // Create mode
  if (isCreate) {
    return (
      <div>
        <h1>New Job</h1>
        {formError && <div role="alert">{formError}</div>}
        <form onSubmit={e => { e.preventDefault(); handleCreate() }}>
          <div>
            <label htmlFor="job-title">Job title *</label>
            <input id="job-title" value={title} onChange={e => setTitle(e.target.value)} />
          </div>
          <div>
            <label htmlFor="job-description">Description</label>
            <textarea id="job-description" value={description} onChange={e => setDescription(e.target.value)} />
          </div>
          <div>
            <label htmlFor="job-priority">Priority</label>
            <select id="job-priority" value={priority} onChange={e => setPriority(e.target.value)}>
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </select>
          </div>
          <div>
            <label htmlFor="job-site-address">Site address</label>
            <input id="job-site-address" value={siteAddress} onChange={e => setSiteAddress(e.target.value)} />
          </div>
          <button type="submit">Create Job</button>
        </form>
      </div>
    )
  }

  if (!job) return <div>Job not found</div>

  return (
    <div>
      <h1>{job.job_number}: {job.title}</h1>
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
        <span className={`status-badge status-${job.status}`}>{job.status}</span>
        <span className={`priority-badge priority-${job.priority}`}>{job.priority}</span>
      </div>
      {error && <div role="alert">{error}</div>}

      {/* Tab navigation */}
      <div role="tablist" aria-label="Job sections">
        {TABS.map(tab => (
          <button
            key={tab}
            role="tab"
            aria-selected={activeTab === tab}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab panels */}
      {activeTab === 'Details' && (
        <div role="tabpanel" aria-label="Details">
          <dl>
            <dt>Description</dt><dd>{job.description || '—'}</dd>
            <dt>Site Address</dt><dd>{job.site_address || '—'}</dd>
            <dt>Scheduled</dt>
            <dd>{job.scheduled_start || '—'} — {job.scheduled_end || '—'}</dd>
            <dt>Actual</dt>
            <dd>{job.actual_start || '—'} — {job.actual_end || '—'}</dd>
            <dt>Staff</dt>
            <dd>
              {job.staff_assignments.length > 0
                ? job.staff_assignments.map(a => `${a.role}: ${a.user_id}`).join(', ')
                : 'No staff assigned'}
            </dd>
          </dl>
        </div>
      )}

      {activeTab === 'Checklist' && (
        <div role="tabpanel" aria-label="Checklist">
          {job.checklist.length === 0 ? (
            <p>No checklist items</p>
          ) : (
            <ul>
              {job.checklist.map((item, i) => (
                <li key={i}>
                  <label>
                    <input type="checkbox" checked={item.completed} readOnly />
                    {item.text}
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {activeTab === 'Attachments' && (
        <div role="tabpanel" aria-label="Attachments">
          <label htmlFor="attachment-upload">Upload file</label>
          <input
            id="attachment-upload"
            type="file"
            onChange={e => {
              const file = e.target.files?.[0]
              if (file) handleUploadAttachment(file)
            }}
          />
          {attachments.length === 0 ? (
            <p>No attachments</p>
          ) : (
            <ul aria-label="Attachment list">
              {attachments.map(a => (
                <li key={a.id}>
                  {a.file_name} ({(a.file_size / 1024).toFixed(1)} KB)
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {activeTab === 'Timeline' && (
        <div role="tabpanel" aria-label="Timeline">
          {history.length === 0 ? (
            <p>No status changes</p>
          ) : (
            <ol aria-label="Status timeline">
              {history.map(h => (
                <li key={h.id}>
                  <strong>{h.from_status || '(new)'} → {h.to_status}</strong>
                  <span> — {new Date(h.changed_at).toLocaleString()}</span>
                  {h.notes && <span> — {h.notes}</span>}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {/* Convert to invoice button */}
      {job.status === 'completed' && !job.converted_invoice_id && (
        <button onClick={handleConvertToInvoice} aria-label="Convert to invoice">
          Convert to Invoice
        </button>
      )}
    </div>
  )
}
