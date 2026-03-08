/**
 * Progress Claim List page with status filtering, PDF generation,
 * inline status changes, and TerminologyContext integration.
 *
 * Validates: Requirements 3.1, 3.2, 3.3, 3.6, 3.7, 3.8
 */
import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { useFlag } from '@/contexts/FeatureFlagContext'
import { useTerm } from '@/contexts/TerminologyContext'
import { ToastContainer } from '@/components/ui/Toast'

interface ProgressClaim {
  id: string
  project_id: string
  project_name?: string
  claim_number: number
  contract_value: string
  revised_contract_value: string
  work_completed_to_date: string
  work_completed_this_period: string
  materials_on_site: string
  retention_withheld: string
  amount_due: string
  completion_percentage: string
  status: string
  created_at: string
  submitted_at?: string | null
}

const STATUS_OPTIONS = ['draft', 'submitted', 'approved', 'paid', 'disputed'] as const

const STATUS_COLOURS: Record<string, string> = {
  draft: '#6b7280',
  submitted: '#2563eb',
  approved: '#16a34a',
  paid: '#7c3aed',
  disputed: '#dc2626',
}

function StatusBadge({ status }: { status: string }) {
  const bg = STATUS_COLOURS[status] ?? '#6b7280'
  return (
    <span
      data-testid={`status-badge-${status}`}
      style={{
        display: 'inline-block',
        padding: '2px 10px',
        borderRadius: 12,
        fontSize: 13,
        fontWeight: 600,
        color: '#fff',
        backgroundColor: bg,
        textTransform: 'capitalize',
        minWidth: 44,
        minHeight: 24,
        textAlign: 'center',
      }}
    >
      {status}
    </span>
  )
}

export default function ProgressClaimList() {
  const { isAllowed, isLoading: guardLoading, toasts, dismissToast } = useModuleGuard('construction')
  const constructionEnabled = useFlag('construction')
  const claimLabel = useTerm('progress_claim', 'Progress Claim')
  const projectLabel = useTerm('project', 'Project')

  const [claims, setClaims] = useState<ProgressClaim[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')
  const [pdfLoading, setPdfLoading] = useState<string | null>(null)

  const fetchClaims = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = statusFilter ? `?status=${statusFilter}` : ''
      const res = await apiClient.get(`/api/v2/progress-claims${params}`)
      setClaims(res.data.claims)
      setTotal(res.data.total)
    } catch {
      setError('Failed to load progress claims')
      setClaims([])
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => { fetchClaims() }, [fetchClaims])

  const handleStatusChange = async (claimId: string, newStatus: string) => {
    try {
      const res = await apiClient.put(`/api/v2/progress-claims/${claimId}`, {
        status: newStatus,
      })
      setClaims((prev) =>
        prev.map((c) =>
          c.id === claimId ? { ...c, status: res.data.status ?? newStatus } : c,
        ),
      )
    } catch {
      setError('Failed to update claim status')
    }
  }

  const handleGeneratePdf = async (claimId: string) => {
    setPdfLoading(claimId)
    try {
      const res = await apiClient.get(`/api/v2/progress-claims/${claimId}/pdf`, {
        responseType: 'blob',
      })
      const blob = new Blob([res.data], { type: 'application/pdf' })
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank')
    } catch {
      setError('Failed to generate PDF')
    } finally {
      setPdfLoading(null)
    }
  }

  if (guardLoading || loading) {
    return <div role="status" aria-label="Loading claims">Loading…</div>
  }

  if (!isAllowed || !constructionEnabled) return null

  return (
    <section aria-label="Progress Claims">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <h1>{claimLabel}s</h1>

      {error && (
        <div role="alert" className="error-banner">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <label htmlFor="status-filter">Status</label>
        <select
          id="status-filter"
          aria-label="Status"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{ minHeight: 44 }}
        >
          <option value="">All</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
          ))}
        </select>
        <button
          onClick={() => setShowForm(true)}
          aria-label="New claim"
          style={{ minWidth: 44, minHeight: 44 }}
        >
          New {claimLabel}
        </button>
      </div>

      {showForm && (
        <ProgressClaimInlineForm
          projectLabel={projectLabel}
          claimLabel={claimLabel}
          onCreated={() => { setShowForm(false); fetchClaims() }}
          onCancel={() => setShowForm(false)}
        />
      )}

      {claims.length === 0 ? (
        <p>No progress claims found</p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table role="grid" aria-label="Progress claims list">
            <thead>
              <tr>
                <th>{claimLabel} #</th>
                <th>Contract Value</th>
                <th>Revised Value</th>
                <th>This Period</th>
                <th>Amount Due</th>
                <th>Completion</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {claims.map((c) => (
                <tr key={c.id} data-testid={`claim-row-${c.id}`}>
                  <td>{c.claim_number}</td>
                  <td>${Number(c.contract_value).toLocaleString()}</td>
                  <td>${Number(c.revised_contract_value).toLocaleString()}</td>
                  <td>${Number(c.work_completed_this_period).toLocaleString()}</td>
                  <td>${Number(c.amount_due).toLocaleString()}</td>
                  <td>{c.completion_percentage}%</td>
                  <td>
                    <StatusBadge status={c.status} />
                    {c.status === 'draft' && (
                      <button
                        onClick={() => handleStatusChange(c.id, 'submitted')}
                        aria-label={`Submit claim ${c.claim_number}`}
                        style={{ marginLeft: 8, minWidth: 44, minHeight: 32, fontSize: 12 }}
                      >
                        Submit
                      </button>
                    )}
                  </td>
                  <td>
                    <button
                      onClick={() => handleGeneratePdf(c.id)}
                      disabled={pdfLoading === c.id}
                      aria-label={`Generate PDF for claim ${c.claim_number}`}
                      style={{ minWidth: 44, minHeight: 44 }}
                    >
                      {pdfLoading === c.id ? 'Generating…' : 'PDF'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p aria-label="Total claims" style={{ marginTop: 8, fontSize: 14, color: '#6b7280' }}>
        Total: {total} {claimLabel.toLowerCase()}(s)
      </p>
    </section>
  )
}


/**
 * Inline form for creating a progress claim from the list page.
 * Uses calculateProgressClaimFields for auto-calculated fields
 * and validateCumulativeNotExceeded for real-time validation.
 */
import { calculateProgressClaimFields, validateCumulativeNotExceeded } from '@/utils/progressClaimCalcs'

function ProgressClaimInlineForm({
  projectLabel,
  claimLabel,
  onCreated,
  onCancel,
}: {
  projectLabel: string
  claimLabel: string
  onCreated: () => void
  onCancel: () => void
}) {
  const [contractValue, setContractValue] = useState('')
  const [variations, setVariations] = useState('0')
  const [workToDate, setWorkToDate] = useState('')
  const [workPrevious, setWorkPrevious] = useState('0')
  const [materials, setMaterials] = useState('0')
  const [retention, setRetention] = useState('0')
  const [cumulativePrevious, setCumulativePrevious] = useState('0')
  const [projectId, setProjectId] = useState('')
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  const cv = Number(contractValue) || 0
  const v = Number(variations) || 0
  const wtd = Number(workToDate) || 0
  const wp = Number(workPrevious) || 0
  const m = Number(materials) || 0
  const r = Number(retention) || 0
  const cumPrev = Number(cumulativePrevious) || 0

  const calc = calculateProgressClaimFields({
    originalContractValue: cv,
    approvedVariations: v,
    workCompletedToDate: wtd,
    workCompletedPrevious: wp,
    materialsOnSite: m,
    retentionWithheld: r,
  })

  const cumulativeError = validateCumulativeNotExceeded(
    cumPrev,
    calc.amountDue,
    calc.revisedContractValue,
  )

  const isOverContract = wtd > calc.revisedContractValue && calc.revisedContractValue > 0

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError('')

    if (isOverContract) {
      setFormError('Work completed exceeds revised contract value')
      return
    }
    if (cumulativeError) {
      setFormError(cumulativeError)
      return
    }

    setSaving(true)
    try {
      await apiClient.post('/api/v2/progress-claims', {
        project_id: projectId,
        contract_value: cv,
        variations_to_date: v,
        work_completed_to_date: wtd,
        work_completed_previous: wp,
        materials_on_site: m,
        retention_withheld: r,
      })
      onCreated()
    } catch (err: any) {
      setFormError(err?.response?.data?.detail || 'Failed to save claim')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Create progress claim" style={{ marginBottom: 24, padding: 16, border: '1px solid #e5e7eb', borderRadius: 8 }}>
      <h3>New {claimLabel}</h3>
      {formError && <div role="alert" style={{ color: '#dc2626', marginBottom: 8 }}>{formError}</div>}
      {cumulativeError && !formError && <div role="alert" style={{ color: '#dc2626', marginBottom: 8 }}>{cumulativeError}</div>}

      <div className="responsive-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
        <div>
          <label htmlFor="project-id">{projectLabel} ID</label>
          <input id="project-id" value={projectId} onChange={(e) => setProjectId(e.target.value)} required style={{ minHeight: 44, width: '100%' }} />
        </div>
        <div>
          <label htmlFor="contract-value">Contract Value</label>
          <input id="contract-value" type="number" step="0.01" inputMode="numeric" value={contractValue} onChange={(e) => setContractValue(e.target.value)} required style={{ minHeight: 44, width: '100%' }} />
        </div>
        <div>
          <label htmlFor="variations">Variations to Date</label>
          <input id="variations" type="number" step="0.01" inputMode="numeric" value={variations} onChange={(e) => setVariations(e.target.value)} style={{ minHeight: 44, width: '100%' }} />
        </div>
        <div>
          <label htmlFor="work-to-date">Work Completed to Date</label>
          <input id="work-to-date" type="number" step="0.01" inputMode="numeric" value={workToDate} onChange={(e) => setWorkToDate(e.target.value)} required style={{ minHeight: 44, width: '100%' }} />
        </div>
        <div>
          <label htmlFor="work-previous">Work Completed Previous</label>
          <input id="work-previous" type="number" step="0.01" inputMode="numeric" value={workPrevious} onChange={(e) => setWorkPrevious(e.target.value)} style={{ minHeight: 44, width: '100%' }} />
        </div>
        <div>
          <label htmlFor="materials">Materials on Site</label>
          <input id="materials" type="number" step="0.01" inputMode="numeric" value={materials} onChange={(e) => setMaterials(e.target.value)} style={{ minHeight: 44, width: '100%' }} />
        </div>
        <div>
          <label htmlFor="retention">Retention Withheld</label>
          <input id="retention" type="number" step="0.01" inputMode="numeric" value={retention} onChange={(e) => setRetention(e.target.value)} style={{ minHeight: 44, width: '100%' }} />
        </div>
        <div>
          <label htmlFor="cumulative-previous">Cumulative Previously Claimed</label>
          <input id="cumulative-previous" type="number" step="0.01" inputMode="numeric" value={cumulativePrevious} onChange={(e) => setCumulativePrevious(e.target.value)} style={{ minHeight: 44, width: '100%' }} />
        </div>
      </div>

      <div aria-label="Calculated fields" style={{ marginTop: 12, padding: 12, backgroundColor: '#f9fafb', borderRadius: 6 }}>
        <p>Revised Contract: <span data-testid="revised-contract">${calc.revisedContractValue.toLocaleString()}</span></p>
        <p>This Period: <span data-testid="this-period">${calc.workCompletedThisPeriod.toLocaleString()}</span></p>
        <p>Amount Due: <span data-testid="amount-due">${calc.amountDue.toLocaleString()}</span></p>
        <p>Completion: <span data-testid="completion-pct">{calc.completionPercentage.toFixed(2)}%</span></p>
      </div>

      {isOverContract && (
        <div role="alert" style={{ color: '#dc2626', marginTop: 8 }}>Work completed exceeds revised contract value</div>
      )}

      <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
        <button type="submit" disabled={saving || !!cumulativeError} aria-label="Save Claim" style={{ minWidth: 44, minHeight: 44 }}>
          {saving ? 'Saving…' : `Save ${claimLabel}`}
        </button>
        <button type="button" onClick={onCancel} style={{ minWidth: 44, minHeight: 44 }}>Cancel</button>
      </div>
    </form>
  )
}
