/**
 * Variation Order Form with TerminologyContext integration,
 * inputMode="numeric" on cost impact, and impact summary display.
 *
 * Validates: Requirements 4.3, 4.5
 */
import { useState } from 'react'
import apiClient from '@/api/client'
import { useTerm } from '@/contexts/TerminologyContext'
import { Button } from '@/components/ui'

interface VariationFormProps {
  projectId?: string
  onSaved?: () => void
}

const inputClass =
  'min-h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent'
const labelClass = 'mb-1 block text-sm font-medium text-text'

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
    <form onSubmit={handleSubmit} aria-label="Variation order form" className="space-y-4">
      {error && (
        <div role="alert" className="rounded-ctl border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
          {error}
        </div>
      )}

      <div>
        <label htmlFor="vf-description" className={labelClass}>Description</label>
        <textarea
          id="vf-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          required
          aria-label="Description"
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="vf-cost-impact" className={labelClass}>Cost Impact</label>
        <input
          id="vf-cost-impact"
          type="number"
          step="0.01"
          inputMode="numeric"
          value={costImpact}
          onChange={(e) => setCostImpact(e.target.value)}
          required
          aria-label="Cost Impact"
          className={inputClass}
        />
      </div>

      <div aria-label="Impact summary" className="rounded-card border border-border bg-canvas p-3 text-sm text-text">
        <p>Type: <span data-testid="impact-type">{impactLabel}</span></p>
        <p>Amount: <span data-testid="impact-amount" className="mono">${Math.abs(impact).toLocaleString()}</span></p>
      </div>

      <Button type="submit" disabled={saving} aria-label={`Save ${variationLabel}`}>
        {saving ? 'Saving…' : `Save ${variationLabel}`}
      </Button>
    </form>
  )
}
