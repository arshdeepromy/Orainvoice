/**
 * Variation Order Form with TerminologyContext integration,
 * inputMode="numeric" on cost impact, and impact summary display.
 *
 * Validates: Requirements 4.3, 4.5
 */
import { useState } from 'react'
import apiClient from '@/api/client'
import { useTerm } from '@/contexts/TerminologyContext'

interface VariationFormProps {
  projectId?: string
  onSaved?: () => void
}

export default function VariationForm({ projectId = '', onSaved }: VariationFormProps) {
  const variationLabel = useTerm('variation', 'Variation')

  const [description, setDescription] = useState('')
  const [costImpact, setCostImpact] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const impact = Number(costImpact) || 0
  const impactLabel = impact >= 0 ? 'Addition' : 'Deduction'

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!description.trim()) {
      setError('Description is required')
      return
    }

    setSaving(true)
    try {
      await apiClient.post('/api/v2/variations', {
        project_id: projectId,
        description: description.trim(),
        cost_impact: impact,
      })
      onSaved?.()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to save variation')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Variation order form">
      {error && <div role="alert">{error}</div>}

      <div>
        <label htmlFor="vf-description">Description</label>
        <textarea
          id="vf-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          required
          aria-label="Description"
          style={{ minHeight: 44, width: '100%' }}
        />
      </div>
      <div>
        <label htmlFor="vf-cost-impact">Cost Impact</label>
        <input
          id="vf-cost-impact"
          type="number"
          step="0.01"
          inputMode="numeric"
          value={costImpact}
          onChange={(e) => setCostImpact(e.target.value)}
          required
          aria-label="Cost Impact"
          style={{ minHeight: 44, width: '100%' }}
        />
      </div>

      <div aria-label="Impact summary" style={{ marginTop: 12, padding: 12, backgroundColor: '#f9fafb', borderRadius: 6 }}>
        <p>Type: <span data-testid="impact-type">{impactLabel}</span></p>
        <p>Amount: <span data-testid="impact-amount">${Math.abs(impact).toLocaleString()}</span></p>
      </div>

      <button type="submit" disabled={saving} aria-label={`Save ${variationLabel}`} style={{ minWidth: 44, minHeight: 44, marginTop: 12 }}>
        {saving ? 'Saving…' : `Save ${variationLabel}`}
      </button>
    </form>
  )
}
