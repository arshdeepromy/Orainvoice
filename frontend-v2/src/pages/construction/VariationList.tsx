/**
 * Variation Order List page with cumulative impact display, PDF generation,
 * immutability for approved/rejected variations, revised contract value display,
 * and TerminologyContext integration.
 *
 * Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
 */
import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { useFlag } from '@/contexts/FeatureFlagContext'
import { useTerm } from '@/contexts/TerminologyContext'
import { ToastContainer } from '@/components/ui/Toast'
import { calculateRevisedContractValue, isVariationImmutable } from '@/utils/variationCalcs'
import { Badge, Button } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'

interface VariationOrder {
  id: string
  project_id: string
  variation_number: number
  description: string
  cost_impact: string
  status: string
  submitted_at: string | null
  approved_at: string | null
  created_at: string
}

const STATUS_OPTIONS = ['draft', 'submitted', 'approved', 'rejected'] as const

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  draft: 'neutral',
  submitted: 'info',
  approved: 'ok',
  rejected: 'danger',
}

function StatusBadge({ status }: { status: string }) {
  const variant = STATUS_VARIANT[status] ?? 'neutral'
  return (
    <Badge variant={variant} data-testid={`status-badge-${status}`} className="capitalize">
      {status}
    </Badge>
  )
}


export default function VariationList() {
  const { isAllowed, isLoading: guardLoading, toasts, dismissToast } = useModuleGuard('construction')
  const constructionEnabled = useFlag('construction')
  const variationLabel = useTerm('variation', 'Variation')
  const projectLabel = useTerm('project', 'Project')

  const [variations, setVariations] = useState<VariationOrder[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')
  const [pdfLoading, setPdfLoading] = useState<string | null>(null)
  const [originalContractValue, setOriginalContractValue] = useState(0)

  const fetchVariations = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = statusFilter ? `?status=${statusFilter}` : ''
      const res = await apiClient.get(`/api/v2/variations${params}`)
      setVariations(res.data?.variations ?? [])
      setTotal(res.data?.total ?? 0)
      if (res.data?.original_contract_value != null) {
        setOriginalContractValue(Number(res.data.original_contract_value))
      }
    } catch {
      setError('Failed to load variation orders')
      setVariations([])
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => { fetchVariations() }, [fetchVariations])

  const approvedVariations = variations
    .filter((v) => v.status === 'approved')
    .map((v) => ({ cost_impact: Number(v.cost_impact) }))

  const revisedContractValue = calculateRevisedContractValue(
    originalContractValue,
    approvedVariations,
  )

  const cumulativeImpact = approvedVariations.reduce(
    (sum, v) => sum + v.cost_impact,
    0,
  )

  const handleApprove = async (id: string) => {
    try {
      await apiClient.put(`/api/v2/variations/${id}/approve`)
      fetchVariations()
    } catch {
      setError('Failed to approve variation')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await apiClient.delete(`/api/v2/variations/${id}`)
      fetchVariations()
    } catch {
      setError('Failed to delete variation')
    }
  }

  const handleGeneratePdf = async (id: string) => {
    setPdfLoading(id)
    try {
      const res = await apiClient.get(`/api/v2/variations/${id}/pdf`, {
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
    return <div role="status" aria-label="Loading variations" className="py-12 text-center text-sm text-muted">Loading…</div>
  }

  if (!isAllowed || !constructionEnabled) return null

  return (
    <section aria-label="Variation Orders" className="space-y-4 px-4 py-6 sm:px-6 lg:px-8">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <h1 className="text-2xl font-semibold text-text">{variationLabel} Orders</h1>

      {error && (
        <div role="alert" className="flex items-center justify-between rounded-card border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error" className="ml-2 text-danger">×</button>
        </div>
      )}

      {/* Cumulative impact and revised contract value summary */}
      <div
        aria-label="Contract summary"
        data-testid="contract-summary"
        className="flex flex-wrap gap-6 rounded-card border border-border bg-canvas p-3"
      >
        <div>
          <span className="text-[13px] text-muted">Original Contract</span>
          <p className="mono font-semibold text-text" data-testid="original-contract-value">
            ${originalContractValue.toLocaleString()}
          </p>
        </div>
        <div>
          <span className="text-[13px] text-muted">Cumulative {variationLabel} Impact</span>
          <p
            className={`mono font-semibold ${cumulativeImpact >= 0 ? 'text-ok' : 'text-danger'}`}
            data-testid="cumulative-impact"
          >
            {cumulativeImpact >= 0 ? '+' : ''}${cumulativeImpact.toLocaleString()}
          </p>
        </div>
        <div>
          <span className="text-[13px] text-muted">Revised Contract Value</span>
          <p className="mono font-semibold text-text" data-testid="revised-contract-value">
            ${revisedContractValue.toLocaleString()}
          </p>
        </div>
      </div>

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
        <Button onClick={() => setShowForm(true)} aria-label="New variation">
          New {variationLabel}
        </Button>
      </div>

      {showForm && (
        <VariationInlineForm
          variationLabel={variationLabel}
          projectLabel={projectLabel}
          onCreated={() => { setShowForm(false); fetchVariations() }}
          onCancel={() => setShowForm(false)}
        />
      )}

      {variations.length === 0 ? (
        <p className="text-sm text-muted">No variation orders found</p>
      ) : (
        <div className="overflow-x-auto overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table role="grid" aria-label="Variation orders list" className="w-full text-sm">
            <thead>
              <tr>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">VO #</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Description</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Cost Impact</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(variations ?? []).map((v) => {
                const immutable = isVariationImmutable(v.status)
                return (
                  <tr key={v.id} data-testid={`variation-row-${v.id}`} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="mono px-4 py-3 text-text">{v.variation_number}</td>
                    <td className="px-4 py-3 text-text">{v.description}</td>
                    <td className="px-4 py-3">
                      <span className={`mono ${Number(v.cost_impact) >= 0 ? 'text-ok' : 'text-danger'}`}>
                        {Number(v.cost_impact) >= 0 ? '+' : ''}${Number(v.cost_impact).toLocaleString()}
                      </span>
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={v.status} /></td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap items-center gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleGeneratePdf(v.id)}
                          disabled={pdfLoading === v.id}
                          aria-label={`Generate PDF for variation ${v.variation_number}`}
                        >
                          {pdfLoading === v.id ? 'Generating…' : 'PDF'}
                        </Button>
                        {immutable ? (
                          <span
                            data-testid={`immutable-message-${v.id}`}
                            className="self-center text-xs text-muted"
                          >
                            {v.status === 'approved' ? 'Approved' : 'Rejected'} — create an offsetting variation to adjust
                          </span>
                        ) : (
                          <>
                            {v.status === 'submitted' && (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => handleApprove(v.id)}
                                aria-label={`Approve variation ${v.variation_number}`}
                              >
                                Approve
                              </Button>
                            )}
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => handleDelete(v.id)}
                              aria-label={`Delete variation ${v.variation_number}`}
                            >
                              Delete
                            </Button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <p aria-label="Total variations" className="text-sm text-muted">
        Total: {total} {variationLabel.toLowerCase()}(s)
      </p>
    </section>
  )
}

const inlineInputClass =
  'min-h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent'
const inlineLabelClass = 'mb-1 block text-sm font-medium text-text'

function VariationInlineForm({
  variationLabel,
  projectLabel,
  onCreated,
  onCancel,
}: {
  variationLabel: string
  projectLabel: string
  onCreated: () => void
  onCancel: () => void
}) {
  const [projectId, setProjectId] = useState('')
  const [description, setDescription] = useState('')
  const [costImpact, setCostImpact] = useState('')
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  const impact = Number(costImpact) || 0
  const impactLabel = impact >= 0 ? 'Addition' : 'Deduction'

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError('')

    if (!description.trim()) {
      setFormError('Description is required')
      return
    }

    setSaving(true)
    try {
      await apiClient.post('/api/v2/variations', {
        project_id: projectId,
        description: description.trim(),
        cost_impact: impact,
      })
      onCreated()
    } catch (err: any) {
      setFormError(err?.response?.data?.detail || 'Failed to save variation')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      aria-label="Create variation order"
      className="rounded-card border border-border bg-card p-4 shadow-card"
    >
      <h3 className="mb-3 text-base font-semibold text-text">New {variationLabel}</h3>
      {formError && <div role="alert" className="mb-2 text-sm text-danger">{formError}</div>}

      <div
        className="responsive-grid grid gap-3"
        style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}
      >
        <div>
          <label htmlFor="vo-project-id" className={inlineLabelClass}>{projectLabel} ID</label>
          <input
            id="vo-project-id"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            required
            className={inlineInputClass}
          />
        </div>
        <div>
          <label htmlFor="vo-description" className={inlineLabelClass}>Description</label>
          <textarea
            id="vo-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
            className={inlineInputClass}
          />
        </div>
        <div>
          <label htmlFor="vo-cost-impact" className={inlineLabelClass}>Cost Impact</label>
          <input
            id="vo-cost-impact"
            type="number"
            step="0.01"
            inputMode="numeric"
            value={costImpact}
            onChange={(e) => setCostImpact(e.target.value)}
            required
            className={inlineInputClass}
          />
        </div>
      </div>

      <div aria-label="Impact summary" className="mt-3 rounded-card border border-border bg-canvas p-3 text-sm text-text">
        <p>Type: <span data-testid="impact-type">{impactLabel}</span></p>
        <p>Amount: <span data-testid="impact-amount" className="mono">${Math.abs(impact).toLocaleString()}</span></p>
      </div>

      <div className="mt-3 flex gap-2">
        <Button type="submit" disabled={saving} aria-label="Save Variation">
          {saving ? 'Saving…' : `Save ${variationLabel}`}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  )
}
