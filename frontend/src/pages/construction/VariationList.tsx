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

const STATUS_COLOURS: Record<string, string> = {
  draft: '#6b7280',
  submitted: '#2563eb',
  approved: '#16a34a',
  rejected: '#dc2626',
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
      setVariations(res.data.variations)
      setTotal(res.data.total)
      if (res.data.original_contract_value != null) {
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
    return <div role="status" aria-label="Loading variations">Loading…</div>
  }

  if (!isAllowed || !constructionEnabled) return null

  return (
    <section aria-label="Variation Orders">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <h1>{variationLabel} Orders</h1>

      {error && (
        <div role="alert" className="error-banner">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      {/* Cumulative impact and revised contract value summary */}
      <div
        aria-label="Contract summary"
        data-testid="contract-summary"
        style={{
          marginBottom: 16,
          padding: 12,
          backgroundColor: '#f9fafb',
          borderRadius: 6,
          display: 'flex',
          gap: 24,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <span style={{ fontSize: 13, color: '#6b7280' }}>Original Contract</span>
          <p style={{ fontWeight: 600 }} data-testid="original-contract-value">
            ${originalContractValue.toLocaleString()}
          </p>
        </div>
        <div>
          <span style={{ fontSize: 13, color: '#6b7280' }}>Cumulative {variationLabel} Impact</span>
          <p
            style={{ fontWeight: 600, color: cumulativeImpact >= 0 ? '#16a34a' : '#dc2626' }}
            data-testid="cumulative-impact"
          >
            {cumulativeImpact >= 0 ? '+' : ''}${cumulativeImpact.toLocaleString()}
          </p>
        </div>
        <div>
          <span style={{ fontSize: 13, color: '#6b7280' }}>Revised Contract Value</span>
          <p style={{ fontWeight: 600 }} data-testid="revised-contract-value">
            ${revisedContractValue.toLocaleString()}
          </p>
        </div>
      </div>

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
          aria-label="New variation"
          style={{ minWidth: 44, minHeight: 44 }}
        >
          New {variationLabel}
        </button>
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
        <p>No variation orders found</p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table role="grid" aria-label="Variation orders list">
            <thead>
              <tr>
                <th>VO #</th>
                <th>Description</th>
                <th>Cost Impact</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {variations.map((v) => {
                const immutable = isVariationImmutable(v.status)
                return (
                  <tr key={v.id} data-testid={`variation-row-${v.id}`}>
                    <td>{v.variation_number}</td>
                    <td>{v.description}</td>
                    <td>
                      <span style={{ color: Number(v.cost_impact) >= 0 ? '#16a34a' : '#dc2626' }}>
                        {Number(v.cost_impact) >= 0 ? '+' : ''}${Number(v.cost_impact).toLocaleString()}
                      </span>
                    </td>
                    <td><StatusBadge status={v.status} /></td>
                    <td style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      <button
                        onClick={() => handleGeneratePdf(v.id)}
                        disabled={pdfLoading === v.id}
                        aria-label={`Generate PDF for variation ${v.variation_number}`}
                        style={{ minWidth: 44, minHeight: 44 }}
                      >
                        {pdfLoading === v.id ? 'Generating…' : 'PDF'}
                      </button>
                      {immutable ? (
                        <span
                          data-testid={`immutable-message-${v.id}`}
                          style={{ fontSize: 12, color: '#6b7280', alignSelf: 'center' }}
                        >
                          {v.status === 'approved' ? 'Approved' : 'Rejected'} — create an offsetting variation to adjust
                        </span>
                      ) : (
                        <>
                          {v.status === 'submitted' && (
                            <button
                              onClick={() => handleApprove(v.id)}
                              aria-label={`Approve variation ${v.variation_number}`}
                              style={{ minWidth: 44, minHeight: 44 }}
                            >
                              Approve
                            </button>
                          )}
                          <button
                            onClick={() => handleDelete(v.id)}
                            aria-label={`Delete variation ${v.variation_number}`}
                            style={{ minWidth: 44, minHeight: 44 }}
                          >
                            Delete
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <p aria-label="Total variations" style={{ marginTop: 8, fontSize: 14, color: '#6b7280' }}>
        Total: {total} {variationLabel.toLowerCase()}(s)
      </p>
    </section>
  )
}


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
      style={{ marginBottom: 24, padding: 16, border: '1px solid #e5e7eb', borderRadius: 8 }}
    >
      <h3>New {variationLabel}</h3>
      {formError && <div role="alert" style={{ color: '#dc2626', marginBottom: 8 }}>{formError}</div>}

      <div
        className="responsive-grid"
        style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}
      >
        <div>
          <label htmlFor="vo-project-id">{projectLabel} ID</label>
          <input
            id="vo-project-id"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            required
            style={{ minHeight: 44, width: '100%' }}
          />
        </div>
        <div>
          <label htmlFor="vo-description">Description</label>
          <textarea
            id="vo-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
            style={{ minHeight: 44, width: '100%' }}
          />
        </div>
        <div>
          <label htmlFor="vo-cost-impact">Cost Impact</label>
          <input
            id="vo-cost-impact"
            type="number"
            step="0.01"
            inputMode="numeric"
            value={costImpact}
            onChange={(e) => setCostImpact(e.target.value)}
            required
            style={{ minHeight: 44, width: '100%' }}
          />
        </div>
      </div>

      <div aria-label="Impact summary" style={{ marginTop: 12, padding: 12, backgroundColor: '#f9fafb', borderRadius: 6 }}>
        <p>Type: <span data-testid="impact-type">{impactLabel}</span></p>
        <p>Amount: <span data-testid="impact-amount">${Math.abs(impact).toLocaleString()}</span></p>
      </div>

      <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
        <button type="submit" disabled={saving} aria-label="Save Variation" style={{ minWidth: 44, minHeight: 44 }}>
          {saving ? 'Saving…' : `Save ${variationLabel}`}
        </button>
        <button type="button" onClick={onCancel} style={{ minWidth: 44, minHeight: 44 }}>Cancel</button>
      </div>
    </form>
  )
}
