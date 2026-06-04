/**
 * JobDetail — Task 26 port of frontend/src/pages/jobs/JobDetail.tsx.
 *
 * Job detail / create page (v2). ALL logic copied VERBATIM: module guard +
 * terminology labels, the parallel fetch (job + attachments + history) plus
 * financials, the create-mode form with template dropdown (POST /api/v2/jobs),
 * the five tabs (Details / Profitability / Checklist / Attachments / Timeline),
 * the profitability calc (calculateJobProfitability over revenue vs time+
 * expense+material costs), attachment upload, the embedded LinkedComplianceDocs,
 * and Convert-to-Invoice on completed jobs. Presentation remapped from inline
 * styles onto the design tokens per JobDetail.html (FR-2b).
 *
 * Validates: Requirements 8.1, 8.5, 8.6, 8.7
 */

import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { useTerm } from '@/contexts/TerminologyContext'
import { ToastContainer } from '@/components/ui/Toast'
import { calculateJobProfitability } from '@/utils/jobCalcs'
import LinkedComplianceDocs from '@/pages/compliance/LinkedComplianceDocs'

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

  const INPUT_CLS = 'h-[42px] w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'
  const SELECT_CLS = `${INPUT_CLS} appearance-none`

  if (guardLoading || loading) {
    return (
      <>
        <ToastContainer toasts={toasts} onDismiss={dismissToast} />
        <div role="status" aria-label="Loading job" className="py-16 text-center text-[13px] text-muted">Loading job…</div>
      </>
    )
  }

  if (!isAllowed) return <ToastContainer toasts={toasts} onDismiss={dismissToast} />

  // Create mode
  if (isCreate) {
    return (
      <div className="page">
        <ToastContainer toasts={toasts} onDismiss={dismissToast} />
        <div className="page-head">
          <div>
            <div className="eyebrow">Work</div>
            <h1>New {jobLabel}</h1>
          </div>
        </div>
        {formError && <div role="alert" className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger">{formError}</div>}
        <form onSubmit={e => { e.preventDefault(); handleCreate() }} className="max-w-xl space-y-4">
          {/* Template selection */}
          {templates.length > 0 && (
            <div className="flex flex-col gap-[7px]">
              <label htmlFor="template-select" className="text-[12.5px] font-medium text-text">{jobLabel} Template</label>
              <select
                id="template-select"
                value={selectedTemplate}
                onChange={e => setSelectedTemplate(e.target.value)}
                className={SELECT_CLS}
              >
                <option value="">No template (blank {jobLabel.toLowerCase()})</option>
                {templates.map(t => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
          )}
          <div className="flex flex-col gap-[7px]">
            <label htmlFor="job-title" className="text-[12.5px] font-medium text-text">{jobLabel} title *</label>
            <input id="job-title" value={title} onChange={e => setTitle(e.target.value)} className={INPUT_CLS} />
          </div>
          <div className="flex flex-col gap-[7px]">
            <label htmlFor="job-description" className="text-[12.5px] font-medium text-text">Description</label>
            <textarea
              id="job-description"
              value={description}
              onChange={e => setDescription(e.target.value)}
              rows={3}
              className="w-full rounded-ctl border border-border bg-card px-[13px] py-2 text-[13.5px] text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            />
          </div>
          <div className="flex flex-col gap-[7px]">
            <label htmlFor="job-priority" className="text-[12.5px] font-medium text-text">Priority</label>
            <select id="job-priority" value={priority} onChange={e => setPriority(e.target.value)} className={SELECT_CLS}>
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </select>
          </div>
          <div className="flex flex-col gap-[7px]">
            <label htmlFor="job-site-address" className="text-[12.5px] font-medium text-text">Site address</label>
            <input id="job-site-address" value={siteAddress} onChange={e => setSiteAddress(e.target.value)} className={INPUT_CLS} />
          </div>
          <button type="submit" className="inline-flex min-h-[40px] items-center rounded-ctl bg-accent px-4 text-[13.5px] font-semibold text-white transition-colors hover:bg-accent-press">Create {jobLabel}</button>
        </form>
      </div>
    )
  }

  if (!job) return <div className="page text-[13px] text-muted">Job not found</div>

  return (
    <div className="page page-wide">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <div className="page-head">
        <div>
          <div className="eyebrow">Work · {jobLabel}</div>
          <h1>{job.job_number}: {job.title}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <span className="rounded-[20px] bg-accent-soft px-2.5 py-[3px] text-[11.5px] font-medium capitalize text-accent">{job.status.replace('_', ' ')}</span>
            <span className="rounded-[20px] bg-[#EEF0F4] px-2.5 py-[3px] text-[11.5px] font-medium capitalize text-muted">{job.priority}</span>
            {job.project_name && (
              <span className="text-[13px] text-muted">{projectLabel}: {job.project_name}</span>
            )}
          </div>
        </div>
      </div>
      {error && <div role="alert" className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger">{error}</div>}

      {/* Tab navigation */}
      <div role="tablist" aria-label="Job sections" className="mb-4 flex gap-1 border-b border-border">
        {TABS.map(tab => (
          <button
            key={tab}
            role="tab"
            aria-selected={activeTab === tab}
            onClick={() => setActiveTab(tab)}
            className={`-mb-px border-b-2 px-3.5 py-[11px] text-[13.5px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset ${
              activeTab === tab ? 'border-accent text-accent' : 'border-transparent text-muted hover:text-text'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab panels */}
      {activeTab === 'Details' && (
        <div role="tabpanel" aria-label="Details" className="rounded-card border border-border p-4">
          <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-[13.5px] sm:grid-cols-2">
            <div><dt className="text-muted">Description</dt><dd className="text-text">{job.description || '—'}</dd></div>
            <div><dt className="text-muted">Site Address</dt><dd className="text-text">{job.site_address || '—'}</dd></div>
            <div><dt className="text-muted">Scheduled</dt><dd className="mono text-text">{job.scheduled_start || '—'} — {job.scheduled_end || '—'}</dd></div>
            <div><dt className="text-muted">Actual</dt><dd className="mono text-text">{job.actual_start || '—'} — {job.actual_end || '—'}</dd></div>
            <div className="sm:col-span-2">
              <dt className="text-muted">Staff</dt>
              <dd className="text-text">
                {job.staff_assignments.length > 0
                  ? job.staff_assignments.map(a => `${a.role}: ${a.user_id}`).join(', ')
                  : 'No staff assigned'}
              </dd>
            </div>
          </dl>
        </div>
      )}

      {activeTab === 'Profitability' && (
        <div role="tabpanel" aria-label="Profitability">
          {financials && profitability ? (
            <div className="rounded-card border border-border p-4" data-testid="profitability-panel">
              <h2 className="mb-3 text-[15px] font-semibold text-text">{jobLabel} Profitability</h2>
              <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-[13.5px] sm:grid-cols-2">
                <div className="flex justify-between"><dt className="text-muted">Total Revenue</dt><dd className="mono text-text">${(financials.total_revenue ?? 0).toFixed(2)}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Time Costs</dt><dd className="mono text-text">${(financials.time_costs ?? 0).toFixed(2)}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Expense Costs</dt><dd className="mono text-text">${(financials.expense_costs ?? 0).toFixed(2)}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Material Costs</dt><dd className="mono text-text">${(financials.material_costs ?? 0).toFixed(2)}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Total Costs</dt><dd className="mono text-text">${((financials.time_costs ?? 0) + (financials.expense_costs ?? 0) + (financials.material_costs ?? 0)).toFixed(2)}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Profit Margin</dt><dd className="mono text-text">${(profitability.margin ?? 0).toFixed(2)}</dd></div>
                <div className="flex justify-between sm:col-span-2">
                  <dt className="text-muted">Margin Percentage</dt>
                  <dd className={`mono font-semibold ${profitability.marginPercentage >= 0 ? 'text-ok' : 'text-danger'}`}>
                    {(profitability.marginPercentage ?? 0).toFixed(1)}%
                  </dd>
                </div>
              </dl>
            </div>
          ) : (
            <p className="text-[13px] text-muted">No financial data available for this {jobLabel.toLowerCase()}.</p>
          )}
        </div>
      )}

      {activeTab === 'Checklist' && (
        <div role="tabpanel" aria-label="Checklist">
          {job.checklist.length === 0 ? (
            <p className="text-[13px] text-muted">No checklist items</p>
          ) : (
            <ul className="space-y-2">
              {job.checklist.map((item, i) => (
                <li key={i}>
                  <label className="flex items-center gap-2 text-[13.5px] text-text">
                    <input type="checkbox" checked={item.completed} readOnly className="h-4 w-4 rounded border-border text-accent" />
                    {item.text}
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {activeTab === 'Attachments' && (
        <div role="tabpanel" aria-label="Attachments" className="space-y-3">
          <div className="flex flex-col gap-[7px]">
            <label htmlFor="attachment-upload" className="text-[12.5px] font-medium text-text">Upload file</label>
            <input
              id="attachment-upload"
              type="file"
              onChange={e => {
                const file = e.target.files?.[0]
                if (file) handleUploadAttachment(file)
              }}
              className="text-[13px] text-muted file:mr-3 file:rounded-ctl file:border file:border-border file:bg-card file:px-3 file:py-1.5 file:text-[13px] file:text-text"
            />
          </div>
          {attachments.length === 0 ? (
            <p className="text-[13px] text-muted">No attachments</p>
          ) : (
            <ul aria-label="Attachment list" className="space-y-1 text-[13.5px] text-text">
              {attachments.map(a => (
                <li key={a.id}>
                  {a.file_name} <span className="mono text-muted-2">({(a.file_size / 1024).toFixed(1)} KB)</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {activeTab === 'Timeline' && (
        <div role="tabpanel" aria-label="Timeline">
          {history.length === 0 ? (
            <p className="text-[13px] text-muted">No status changes</p>
          ) : (
            <ol aria-label="Status timeline" className="space-y-2 text-[13.5px]">
              {history.map(h => (
                <li key={h.id} className="rounded-ctl border border-border bg-card px-3 py-2">
                  <strong className="capitalize text-text">{h.from_status || '(new)'} → {h.to_status}</strong>
                  <span className="mono text-muted"> — {new Date(h.changed_at).toLocaleString()}</span>
                  {h.notes && <span className="text-muted"> — {h.notes}</span>}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {/* ---- Linked Compliance Documents ---- */}
      <LinkedComplianceDocs jobId={job.id} />

      {/* Convert to invoice button */}
      {job.status === 'completed' && !job.converted_invoice_id && (
        <button
          onClick={handleConvertToInvoice}
          aria-label="Convert to invoice"
          className="mt-4 inline-flex min-h-[40px] items-center rounded-ctl bg-accent px-4 text-[13.5px] font-semibold text-white transition-colors hover:bg-accent-press"
        >
          Convert to Invoice
        </button>
      )}
    </div>
  )
}
