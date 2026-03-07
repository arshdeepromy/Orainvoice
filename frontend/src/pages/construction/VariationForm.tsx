import { useState } from 'react'
import apiClient from '@/api/client'

interface VariationFormProps {
  projectId?: string
  onSaved?: () => void
}

export default function VariationForm({ projectId = '', onSaved }: VariationFormProps) {
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
        />
      </div>
      <div>
        <label htmlFor="vf-cost-impact">Cost Impact</label>
        <input
          id="vf-cost-impact"
          type="number"
          step="0.01"
          value={costImpact}
          onChange={(e) => setCostImpact(e.target.value)}
          required
          aria-label="Cost Impact"
        />
      </div>

      <div aria-label="Impact summary">
        <p>Type: <span data-testid="impact-type">{impactLabel}</span></p>
        <p>Amount: <span data-testid="impact-amount">${Math.abs(impact).toLocaleString()}</span></p>
      </div>

      <button type="submit" disabled={saving} aria-label="Save Variation">
        {saving ? 'Saving…' : 'Save Variation'}
      </button>
    </form>
  )
}
