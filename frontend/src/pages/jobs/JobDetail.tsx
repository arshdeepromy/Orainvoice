/**
 * Enhanced job detail page with V2 features:
 * - Job profitability panel (revenue, costs, margin)
 * - "Convert to Invoice" button on completed jobs
 * - Job template selection dropdown on creation
 * - Full form, checklist, attachments, status timeline
 * - Context integration (TerminologyContext, FeatureFlagContext, useModuleGuard)
 *
 * Validates: Requirements 8.1, 8.5, 8.6, 8.7
 */

import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { useTerm } from '@/contexts/TerminologyContext'
import { ToastContainer } from '@/components/ui/Toast'
import { calculateJobProfitability } from '@/utils/jobCalcs'

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
  project_id: string | null
  project_name?: string
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

interface JobTemplate {
  id: string
  name: string
  description: string
}

interface JobFinancials {
  total_revenue: number
  time_costs: number
  expense_costs: number
  material_costs: number
}

interface Props {
  jobId?: string
}

const TABS = ['Details', 'Profitability', 'Checklist', 'Attachments', 'Timeline'] as const
type Tab = typeof TABS[number]

export default function JobDetail({ jobId }: Props) {
  const { isAllowed, isLoading: guardLoading, toasts, dismissToast } = useModuleGuard('jobs')
  const jobLabel = useTerm('job', 'Job')
  const projectLabel = useTerm('project', 'Project')

  const [job, setJob] = useState<JobData | null>(null)
  const [loading, setLoading] = useState(!!jobId)
  const [activeTab, setActiveTab] = useState<Tab>('Details')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [history, setHistory] = useState<StatusHistoryEntry[]>([])
  const [financials, setFinancials] = useState<JobFinancials | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Form state for create mode
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState('normal')
  const [siteAddress, setSiteAddress] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [templates, setTemplates] = useState<JobTemplate[]>([])
  const [selectedTemplate, setSelectedTemplate] = useState('')

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

      // Fetch financials for profitability panel
      try {
        const finRes = await apiClient.get(`/api/v2/jobs/${jobId}/financials`)
        setFinancials(finRes.data)
      } catch {
        // Financials endpoint may not exist yet; use defaults
        setFinancials(null)
      }
    } catch {
      setError('Failed to load job')
    } finally {
      setLoading(false)
    }
  }, [jobId])

  const fetchTemplates = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/job-templates')
      setTemplates(res.data.templates || res.data || [])
    } catch {
      setTemplates([])
    }
  }, [])

  useEffect(() => { fetchJob() }, [fetchJob])
  useEffect(() => { if (isCreate) fetchTemplates() }, [isCreate, fetchTemplates])

  const handleCreate = async () => {
    setFormError(null)
    if (!title.trim()) {
      setFormError(`${jobLabel} title is required.`)
      return
    }
    try {
      const payload: Record<string, unknown> = {
        title, description, priority, site_address: siteAddress || null,
      }
      if (selectedTemplate) payload.template_id = selectedTemplate
      await apiClient.post('/api/v2/jobs', payload)
    } catch {
      setFormError(`Failed to create ${jobLabel.toLowerCase()}`)
    }
  }

  const handleConvertToInvoice = async () => {
    if (!job) return
    try {
      const res = await apiClient.post(`/api/v2/jobs/${job.id}/convert-to-invoice`, {
        time_entries: [], expenses: [], materials: [],
      })
      // Navigate to the new invoice if ID is returned
      if (res.data?.invoice_id) {
        window.location.href = `/invoices/${res.data.invoice_id}`
        return
      }
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

  /* Profitability calculation */
  const profitability = financials
    ? calculateJobProfitability(
        financials.total_revenue,
        financials.time_costs + financials.expense_costs + financials.material_costs,
      )
    : null

  if (guardLoading || loading) {
    return (
      <>
        <ToastContainer toasts={toasts} onDismiss={dismissToast} />
        <div role="status" aria-label="Loading job">Loading job…</div>
      </>
    )
  }

  if (!isAllowed) return <ToastContainer toasts={toasts} onDismiss={dismissToast} />

  // Create mode
  if (isCreate) {
    return (
      <div>
        <ToastContainer toasts={toasts} onDismiss={dismissToast} />
        <h1>New {jobLabel}</h1>
        {formError && <div role="alert">{formError}</div>}
        <form onSubmit={e => { e.preventDefault(); handleCreate() }}>
          {/* Template selection */}
          {templates.length > 0 && (
            <div style={{ marginBottom: '1rem' }}>
              <label htmlFor="template-select">{jobLabel} Template</label>
              <select
                id="template-select"
                value={selectedTemplate}
                onChange={e => setSelectedTemplate(e.target.value)}
                style={{ minHeight: 44, display: 'block', marginTop: '0.25rem' }}
              >
                <option value="">No template (blank {jobLabel.toLowerCase()})</option>
                {templates.map(t => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label htmlFor="job-title">{jobLabel} title *</label>
            <input
              id="job-title"
              value={title}
              onChange={e => setTitle(e.target.value)}
              style={{ minHeight: 44 }}
            />
          </div>
          <div>
            <label htmlFor="job-description">Description</label>
            <textarea
              id="job-description"
              value={description}
              onChange={e => setDescription(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="job-priority">Priority</label>
            <select
              id="job-priority"
              value={priority}
              onChange={e => setPriority(e.target.value)}
              style={{ minHeight: 44 }}
            >
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </select>
          </div>
          <div>
            <label htmlFor="job-site-address">Site address</label>
            <input
              id="job-site-address"
              value={siteAddress}
              onChange={e => setSiteAddress(e.target.value)}
              style={{ minHeight: 44 }}
            />
          </div>
          <button type="submit" style={{ minWidth: 44, minHeight: 44 }}>Create {jobLabel}</button>
        </form>
      </div>
    )
  }

  if (!job) return <div>Job not found</div>

  return (
    <div>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <h1>{job.job_number}: {job.title}</h1>
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        <span className={`status-badge status-${job.status}`}>{job.status}</span>
        <span className={`priority-badge priority-${job.priority}`}>{job.priority}</span>
        {job.project_name && (
          <span style={{ fontSize: '0.85rem', color: '#6B7280' }}>
            {projectLabel}: {job.project_name}
          </span>
        )}
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
            style={{ minWidth: 44, minHeight: 44 }}
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

      {activeTab === 'Profitability' && (
        <div role="tabpanel" aria-label="Profitability">
          {financials && profitability ? (
            <div data-testid="profitability-panel">
              <h2>{jobLabel} Profitability</h2>
              <dl>
                <dt>Total Revenue</dt>
                <dd>${(financials.total_revenue ?? 0).toFixed(2)}</dd>
                <dt>Time Costs</dt>
                <dd>${(financials.time_costs ?? 0).toFixed(2)}</dd>
                <dt>Expense Costs</dt>
                <dd>${(financials.expense_costs ?? 0).toFixed(2)}</dd>
                <dt>Material Costs</dt>
                <dd>${(financials.material_costs ?? 0).toFixed(2)}</dd>
                <dt>Total Costs</dt>
                <dd>${((financials.time_costs ?? 0) + (financials.expense_costs ?? 0) + (financials.material_costs ?? 0)).toFixed(2)}</dd>
                <dt>Profit Margin</dt>
                <dd>${(profitability.margin ?? 0).toFixed(2)}</dd>
                <dt>Margin Percentage</dt>
                <dd
                  style={{
                    color: profitability.marginPercentage >= 0 ? '#10B981' : '#EF4444',
                    fontWeight: 600,
                  }}
                >
                  {(profitability.marginPercentage ?? 0).toFixed(1)}%
                </dd>
              </dl>
            </div>
          ) : (
            <p>No financial data available for this {jobLabel.toLowerCase()}.</p>
          )}
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
        <button
          onClick={handleConvertToInvoice}
          aria-label="Convert to invoice"
          style={{ minWidth: 44, minHeight: 44, marginTop: '1rem' }}
        >
          Convert to Invoice
        </button>
      )}
    </div>
  )
}
