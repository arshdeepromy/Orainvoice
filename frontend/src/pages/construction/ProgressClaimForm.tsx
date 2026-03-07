import { useState } from 'react'
import apiClient from '@/api/client'

interface ProgressClaimFormProps {
  projectId?: string
  onSaved?: () => void
}

export default function ProgressClaimForm({ projectId = '', onSaved }: ProgressClaimFormProps) {
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

  const revisedContract = cv + v
  const thisPeriod = wtd - wp
  const amountDue = thisPeriod + m - r
  const completionPct = revisedContract > 0
    ? ((wtd / revisedContract) * 100).toFixed(2)
    : '0.00'

  const isOverContract = wtd > revisedContract && revisedContract > 0

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (isOverContract) {
      setError('Work completed to date cannot exceed revised contract value')
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

      <div>
        <label htmlFor="pcf-contract-value">Contract Value</label>
        <input id="pcf-contract-value" type="number" step="0.01" value={contractValue} onChange={(e) => setContractValue(e.target.value)} required />
      </div>
      <div>
        <label htmlFor="pcf-variations">Variations to Date</label>
        <input id="pcf-variations" type="number" step="0.01" value={variations} onChange={(e) => setVariations(e.target.value)} />
      </div>
      <div>
        <label htmlFor="pcf-work-to-date">Work Completed to Date</label>
        <input id="pcf-work-to-date" type="number" step="0.01" value={workToDate} onChange={(e) => setWorkToDate(e.target.value)} required />
      </div>
      <div>
        <label htmlFor="pcf-work-previous">Work Completed Previous</label>
        <input id="pcf-work-previous" type="number" step="0.01" value={workPrevious} onChange={(e) => setWorkPrevious(e.target.value)} />
      </div>
      <div>
        <label htmlFor="pcf-materials">Materials on Site</label>
        <input id="pcf-materials" type="number" step="0.01" value={materials} onChange={(e) => setMaterials(e.target.value)} />
      </div>
      <div>
        <label htmlFor="pcf-retention">Retention Withheld</label>
        <input id="pcf-retention" type="number" step="0.01" value={retention} onChange={(e) => setRetention(e.target.value)} />
      </div>

      <div aria-label="Calculated fields">
        <p>Revised Contract: <span data-testid="revised-contract">${revisedContract.toLocaleString()}</span></p>
        <p>This Period: <span data-testid="this-period">${thisPeriod.toLocaleString()}</span></p>
        <p>Amount Due: <span data-testid="amount-due">${amountDue.toLocaleString()}</span></p>
        <p>Completion: <span data-testid="completion-pct">{completionPct}%</span></p>
      </div>

      {isOverContract && (
        <div role="alert">Work completed exceeds revised contract value</div>
      )}

      <button type="submit" disabled={saving} aria-label="Save Claim">
        {saving ? 'Saving…' : 'Save Claim'}
      </button>
    </form>
  )
}
