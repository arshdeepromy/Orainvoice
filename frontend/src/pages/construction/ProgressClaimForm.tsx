/**
 * Standalone Progress Claim Form page with auto-calculated fields,
 * real-time cumulative validation, and TerminologyContext integration.
 *
 * Validates: Requirements 3.3, 3.4, 3.5, 3.8
 */
import { useState } from 'react'
import apiClient from '@/api/client'
import { useTerm } from '@/contexts/TerminologyContext'
import {
  calculateProgressClaimFields,
  validateCumulativeNotExceeded,
} from '@/utils/progressClaimCalcs'

interface ProgressClaimFormProps {
  projectId?: string
  cumulativePreviousClaimed?: number
  onSaved?: () => void
}

export default function ProgressClaimForm({
  projectId = '',
  cumulativePreviousClaimed = 0,
  onSaved,
}: ProgressClaimFormProps) {
  const claimLabel = useTerm('progress_claim', 'Progress Claim')

  const [contractValue, setContractValue] = useState('')
  const [variations, setVariations] = useState('0')
  const [workToDate, setWorkToDate] = useState('')
  const [workPrevious, setWorkPrevious] = useState('0')
  const [materials, setMaterials] = useState('0')
  const [retention, setRetention] = useState('0')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const cv = Number(contractValue) || 0
  const v = Number(variations) || 0
  const wtd = Number(workToDate) || 0
  const wp = Number(workPrevious) || 0
  const m = Number(materials) || 0
  const r = Number(retention) || 0

  const calc = calculateProgressClaimFields({
    originalContractValue: cv,
    approvedVariations: v,
    workCompletedToDate: wtd,
    workCompletedPrevious: wp,
    materialsOnSite: m,
    retentionWithheld: r,
  })

  const isOverContract = wtd > calc.revisedContractValue && calc.revisedContractValue > 0

  const cumulativeError = validateCumulativeNotExceeded(
    cumulativePreviousClaimed,
    calc.amountDue,
    calc.revisedContractValue,
  )

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (isOverContract) {
      setError('Work completed to date cannot exceed revised contract value')
      return
    }
    if (cumulativeError) {
      setError(cumulativeError)
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
      onSaved?.()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to save claim')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Progress claim form">
      {error && <div role="alert">{error}</div>}
      {cumulativeError && !error && <div role="alert">{cumulativeError}</div>}

      <div>
        <label htmlFor="pcf-contract-value">Contract Value</label>
        <input
          id="pcf-contract-value"
          type="number"
          step="0.01"
          inputMode="numeric"
          value={contractValue}
          onChange={(e) => setContractValue(e.target.value)}
          required
          style={{ minHeight: 44 }}
        />
      </div>
      <div>
        <label htmlFor="pcf-variations">Variations to Date</label>
        <input
          id="pcf-variations"
          type="number"
          step="0.01"
          inputMode="numeric"
          value={variations}
          onChange={(e) => setVariations(e.target.value)}
          style={{ minHeight: 44 }}
        />
      </div>
      <div>
        <label htmlFor="pcf-work-to-date">Work Completed to Date</label>
        <input
          id="pcf-work-to-date"
          type="number"
          step="0.01"
          inputMode="numeric"
          value={workToDate}
          onChange={(e) => setWorkToDate(e.target.value)}
          required
          style={{ minHeight: 44 }}
        />
      </div>
      <div>
        <label htmlFor="pcf-work-previous">Work Completed Previous</label>
        <input
          id="pcf-work-previous"
          type="number"
          step="0.01"
          inputMode="numeric"
          value={workPrevious}
          onChange={(e) => setWorkPrevious(e.target.value)}
          style={{ minHeight: 44 }}
        />
      </div>
      <div>
        <label htmlFor="pcf-materials">Materials on Site</label>
        <input
          id="pcf-materials"
          type="number"
          step="0.01"
          inputMode="numeric"
          value={materials}
          onChange={(e) => setMaterials(e.target.value)}
          style={{ minHeight: 44 }}
        />
      </div>
      <div>
        <label htmlFor="pcf-retention">Retention Withheld</label>
        <input
          id="pcf-retention"
          type="number"
          step="0.01"
          inputMode="numeric"
          value={retention}
          onChange={(e) => setRetention(e.target.value)}
          style={{ minHeight: 44 }}
        />
      </div>

      <div aria-label="Calculated fields" style={{ marginTop: 12, padding: 12, backgroundColor: '#f9fafb', borderRadius: 6 }}>
        <p>Revised Contract: <span data-testid="revised-contract">${calc.revisedContractValue.toLocaleString()}</span></p>
        <p>This Period: <span data-testid="this-period">${calc.workCompletedThisPeriod.toLocaleString()}</span></p>
        <p>Amount Due: <span data-testid="amount-due">${calc.amountDue.toLocaleString()}</span></p>
        <p>Completion: <span data-testid="completion-pct">{calc.completionPercentage.toFixed(2)}%</span></p>
      </div>

      {isOverContract && (
        <div role="alert">Work completed exceeds revised contract value</div>
      )}

      <button type="submit" disabled={saving || !!cumulativeError} aria-label="Save Claim" style={{ minWidth: 44, minHeight: 44 }}>
        {saving ? 'Saving…' : `Save ${claimLabel}`}
      </button>
    </form>
  )
}
