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
import { Badge, Button } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'

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

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  draft: 'neutral',
  submitted: 'info',
  approved: 'ok',
  paid: 'paid',
  disputed: 'danger',
}

function StatusBadge({ status }: { status: string }) {
  const variant = STATUS_VARIANT[status] ?? 'neutral'
  return (
    <Badge variant={variant} data-testid={`status-badge-${status}`} className="capitalize">
      {status}
    </Badge>
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
      setClaims(res.data?.claims ?? [])
      setTotal(res.data?.total ?? 0)
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
          c.id === claimId ? { ...c, status: res.data?.status ?? newStatus } : c,
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
    return <div role="status" aria-label="Loading claims" className="py-12 text-center text-sm text-muted">Loading…</div>
  }

  if (!isAllowed || !constructionEnabled) return null

  return (
    <section aria-label="Progress Claims" className="space-y-4 px-4 py-6 sm:px-6 lg:px-8">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <h1 className="text-2xl font-semibold text-text">{claimLabel}s</h1>

      {error && (
        <div role="alert" className="flex items-center justify-between rounded-card border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error" className="ml-2 text-danger">×</button>
        </div>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label htmlFor="status-filter" className="mb-1 block text-xs font-medium text-muted">Status</label>
          <select
            id="status-filter"
            aria-label="Status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="min-h-[44px] rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent"
          >
            <option value="">All</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
            ))}
          </select>
        </div>
        <Button onClick={() => setShowForm(true)} aria-label="New claim">
          New {claimLabel}
        </Button>
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
        <p className="text-sm text-muted">No progress claims found</p>
      ) : (
        <div className="overflow-x-auto overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table role="grid" aria-label="Progress claims list" className="w-full text-sm">
            <thead>
              <tr>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">{claimLabel} #</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Contract Value</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Revised Value</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">This Period</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Amount Due</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Completion</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(claims ?? []).map((c) => (
                <tr key={c.id} data-testid={`claim-row-${c.id}`} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="mono px-4 py-3 text-text">{c.claim_number}</td>
                  <td className="mono px-4 py-3 text-text">${Number(c.contract_value).toLocaleString()}</td>
                  <td className="mono px-4 py-3 text-text">${Number(c.revised_contract_value).toLocaleString()}</td>
                  <td className="mono px-4 py-3 text-text">${Number(c.work_completed_this_period).toLocaleString()}</td>
                  <td className="mono px-4 py-3 text-text">${Number(c.amount_due).toLocaleString()}</td>
                  <td className="mono px-4 py-3 text-text">{c.completion_percentage}%</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={c.status} />
                    {c.status === 'draft' && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleStatusChange(c.id, 'submitted')}
                        aria-label={`Submit claim ${c.claim_number}`}
                        className="ml-2"
                      >
                        Submit
                      </Button>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => handleGeneratePdf(c.id)}
                      disabled={pdfLoading === c.id}
                      aria-label={`Generate PDF for claim ${c.claim_number}`}
                    >
                      {pdfLoading === c.id ? 'Generating…' : 'PDF'}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p aria-label="Total claims" className="text-sm text-muted">
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

const inlineInputClass =
  'min-h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent'
const inlineLabelClass = 'mb-1 block text-sm font-medium text-text'

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
    <form onSubmit={handleSubmit} aria-label="Create progress claim" className="rounded-card border border-border bg-card p-4 shadow-card">
      <h3 className="mb-3 text-base font-semibold text-text">New {claimLabel}</h3>
      {formError && <div role="alert" className="mb-2 text-sm text-danger">{formError}</div>}
      {cumulativeError && !formError && <div role="alert" className="mb-2 text-sm text-danger">{cumulativeError}</div>}

      <div className="responsive-grid grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
        <div>
          <label htmlFor="project-id" className={inlineLabelClass}>{projectLabel} ID</label>
          <input id="project-id" value={projectId} onChange={(e) => setProjectId(e.target.value)} required className={inlineInputClass} />
        </div>
        <div>
          <label htmlFor="contract-value" className={inlineLabelClass}>Contract Value</label>
          <input id="contract-value" type="number" step="0.01" inputMode="numeric" value={contractValue} onChange={(e) => setContractValue(e.target.value)} required className={inlineInputClass} />
        </div>
        <div>
          <label htmlFor="variations" className={inlineLabelClass}>Variations to Date</label>
          <input id="variations" type="number" step="0.01" inputMode="numeric" value={variations} onChange={(e) => setVariations(e.target.value)} className={inlineInputClass} />
        </div>
        <div>
          <label htmlFor="work-to-date" className={inlineLabelClass}>Work Completed to Date</label>
          <input id="work-to-date" type="number" step="0.01" inputMode="numeric" value={workToDate} onChange={(e) => setWorkToDate(e.target.value)} required className={inlineInputClass} />
        </div>
        <div>
          <label htmlFor="work-previous" className={inlineLabelClass}>Work Completed Previous</label>
          <input id="work-previous" type="number" step="0.01" inputMode="numeric" value={workPrevious} onChange={(e) => setWorkPrevious(e.target.value)} className={inlineInputClass} />
        </div>
        <div>
          <label htmlFor="materials" className={inlineLabelClass}>Materials on Site</label>
          <input id="materials" type="number" step="0.01" inputMode="numeric" value={materials} onChange={(e) => setMaterials(e.target.value)} className={inlineInputClass} />
        </div>
        <div>
          <label htmlFor="retention" className={inlineLabelClass}>Retention Withheld</label>
          <input id="retention" type="number" step="0.01" inputMode="numeric" value={retention} onChange={(e) => setRetention(e.target.value)} className={inlineInputClass} />
        </div>
        <div>
          <label htmlFor="cumulative-previous" className={inlineLabelClass}>Cumulative Previously Claimed</label>
          <input id="cumulative-previous" type="number" step="0.01" inputMode="numeric" value={cumulativePrevious} onChange={(e) => setCumulativePrevious(e.target.value)} className={inlineInputClass} />
        </div>
      </div>

      <div aria-label="Calculated fields" className="mt-3 rounded-card border border-border bg-canvas p-3 text-sm text-text">
        <p>Revised Contract: <span data-testid="revised-contract" className="mono">${calc.revisedContractValue.toLocaleString()}</span></p>
        <p>This Period: <span data-testid="this-period" className="mono">${calc.workCompletedThisPeriod.toLocaleString()}</span></p>
        <p>Amount Due: <span data-testid="amount-due" className="mono">${calc.amountDue.toLocaleString()}</span></p>
        <p>Completion: <span data-testid="completion-pct" className="mono">{calc.completionPercentage.toFixed(2)}%</span></p>
      </div>

      {isOverContract && (
        <div role="alert" className="mt-2 text-sm text-danger">Work completed exceeds revised contract value</div>
      )}

      <div className="mt-3 flex gap-2">
        <Button type="submit" disabled={saving || !!cumulativeError} aria-label="Save Claim">
          {saving ? 'Saving…' : `Save ${claimLabel}`}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  )
}
