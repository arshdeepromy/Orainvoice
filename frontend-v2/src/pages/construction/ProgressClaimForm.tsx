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
import { Button } from '@/components/ui'

interface ProgressClaimFormProps {
  projectId?: string
  cumulativePreviousClaimed?: number
  onSaved?: () => void
}

const inputClass =
  'min-h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent'
const labelClass = 'mb-1 block text-sm font-medium text-text'

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
    <form onSubmit={handleSubmit} aria-label="Progress claim form" className="space-y-4">
      {error && (
        <div role="alert" className="rounded-ctl border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
          {error}
        </div>
      )}
      {cumulativeError && !error && (
        <div role="alert" className="rounded-ctl border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
          {cumulativeError}
        </div>
      )}

      <div>
        <label htmlFor="pcf-contract-value" className={labelClass}>Contract Value</label>
        <input
          id="pcf-contract-value"
          type="number"
          step="0.01"
          inputMode="numeric"
          value={contractValue}
          onChange={(e) => setContractValue(e.target.value)}
          required
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="pcf-variations" className={labelClass}>Variations to Date</label>
        <input
          id="pcf-variations"
          type="number"
          step="0.01"
          inputMode="numeric"
          value={variations}
          onChange={(e) => setVariations(e.target.value)}
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="pcf-work-to-date" className={labelClass}>Work Completed to Date</label>
        <input
          id="pcf-work-to-date"
          type="number"
          step="0.01"
          inputMode="numeric"
          value={workToDate}
          onChange={(e) => setWorkToDate(e.target.value)}
          required
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="pcf-work-previous" className={labelClass}>Work Completed Previous</label>
        <input
          id="pcf-work-previous"
          type="number"
          step="0.01"
          inputMode="numeric"
          value={workPrevious}
          onChange={(e) => setWorkPrevious(e.target.value)}
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="pcf-materials" className={labelClass}>Materials on Site</label>
        <input
          id="pcf-materials"
          type="number"
          step="0.01"
          inputMode="numeric"
          value={materials}
          onChange={(e) => setMaterials(e.target.value)}
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="pcf-retention" className={labelClass}>Retention Withheld</label>
        <input
          id="pcf-retention"
          type="number"
          step="0.01"
          inputMode="numeric"
          value={retention}
          onChange={(e) => setRetention(e.target.value)}
          className={inputClass}
        />
      </div>

      <div aria-label="Calculated fields" className="rounded-card border border-border bg-canvas p-3 text-sm text-text">
        <p>Revised Contract: <span data-testid="revised-contract" className="mono">${calc.revisedContractValue.toLocaleString()}</span></p>
        <p>This Period: <span data-testid="this-period" className="mono">${calc.workCompletedThisPeriod.toLocaleString()}</span></p>
        <p>Amount Due: <span data-testid="amount-due" className="mono">${calc.amountDue.toLocaleString()}</span></p>
        <p>Completion: <span data-testid="completion-pct" className="mono">{calc.completionPercentage.toFixed(2)}%</span></p>
      </div>

      {isOverContract && (
        <div role="alert" className="text-sm text-danger">Work completed exceeds revised contract value</div>
      )}

      <Button type="submit" disabled={saving || !!cumulativeError} aria-label="Save Claim">
        {saving ? 'Saving…' : `Save ${claimLabel}`}
      </Button>
    </form>
  )
}
