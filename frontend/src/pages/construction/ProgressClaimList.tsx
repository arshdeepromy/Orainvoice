import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

interface ProgressClaim {
  id: string
  project_id: string
  claim_number: number
  contract_value: string
  revised_contract_value: string
  work_completed_to_date: string
  work_completed_this_period: string
  amount_due: string
  completion_percentage: string
  status: string
  created_at: string
}

export default function ProgressClaimList() {
  const [claims, setClaims] = useState<ProgressClaim[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')

  const fetchClaims = useCallback(async () => {
    setLoading(true)
    try {
      const params = statusFilter ? `?status=${statusFilter}` : ''
      const res = await apiClient.get(`/api/v2/progress-claims${params}`)
      setClaims(res.data.claims)
      setTotal(res.data.total)
    } catch {
      setClaims([])
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => { fetchClaims() }, [fetchClaims])

  if (loading) {
    return <div role="status" aria-label="Loading claims">Loading…</div>
  }

  return (
    <div>
      <h1>Progress Claims</h1>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <label htmlFor="status-filter">Status</label>
        <select
          id="status-filter"
          aria-label="Status"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All</option>
          <option value="draft">Draft</option>
          <option value="submitted">Submitted</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
        <button onClick={() => setShowForm(true)} aria-label="New claim">
          New Claim
        </button>
      </div>

      {showForm && (
        <ProgressClaimInlineForm
          onCreated={() => { setShowForm(false); fetchClaims() }}
          onCancel={() => setShowForm(false)}
        />
      )}

      {claims.length === 0 ? (
        <p>No progress claims found</p>
      ) : (
        <table role="grid" aria-label="Progress claims list">
          <thead>
            <tr>
              <th>Claim #</th>
              <th>Contract Value</th>
              <th>Revised Value</th>
              <th>This Period</th>
              <th>Amount Due</th>
              <th>Completion</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((c) => (
              <tr key={c.id}>
                <td>{c.claim_number}</td>
                <td>${Number(c.contract_value).toLocaleString()}</td>
                <td>${Number(c.revised_contract_value).toLocaleString()}</td>
                <td>${Number(c.work_completed_this_period).toLocaleString()}</td>
                <td>${Number(c.amount_due).toLocaleString()}</td>
                <td>{c.completion_percentage}%</td>
                <td>{c.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function ProgressClaimInlineForm({
  onCreated,
  onCancel,
}: {
  onCreated: () => void
  onCancel: () => void
}) {
  const [contractValue, setContractValue] = useState('')
  const [variations, setVariations] = useState('0')
  const [workToDate, setWorkToDate] = useState('')
  const [workPrevious, setWorkPrevious] = useState('0')
  const [materials, setMaterials] = useState('0')
  const [retention, setRetention] = useState('0')
  const [projectId, setProjectId] = useState('')

  // Auto-calculated fields
  const cv = Number(contractValue) || 0
  const v = Number(variations) || 0
  const wtd = Number(workToDate) || 0
  const wp = Number(workPrevious) || 0
  const m = Number(materials) || 0
  const r = Number(retention) || 0

  const revisedContract = cv + v
  const thisPeriod = wtd - wp
  const amountDue = thisPeriod + m - r
  const completionPct = revisedContract > 0 ? ((wtd / revisedContract) * 100).toFixed(2) : '0.00'

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
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
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Create progress claim">
      <div>
        <label htmlFor="project-id">Project ID</label>
        <input id="project-id" value={projectId} onChange={(e) => setProjectId(e.target.value)} required />
      </div>
      <div>
        <label htmlFor="contract-value">Contract Value</label>
        <input id="contract-value" type="number" step="0.01" value={contractValue} onChange={(e) => setContractValue(e.target.value)} required />
      </div>
      <div>
        <label htmlFor="variations">Variations to Date</label>
        <input id="variations" type="number" step="0.01" value={variations} onChange={(e) => setVariations(e.target.value)} />
      </div>
      <div>
        <label htmlFor="work-to-date">Work Completed to Date</label>
        <input id="work-to-date" type="number" step="0.01" value={workToDate} onChange={(e) => setWorkToDate(e.target.value)} required />
      </div>
      <div>
        <label htmlFor="work-previous">Work Completed Previous</label>
        <input id="work-previous" type="number" step="0.01" value={workPrevious} onChange={(e) => setWorkPrevious(e.target.value)} />
      </div>
      <div>
        <label htmlFor="materials">Materials on Site</label>
        <input id="materials" type="number" step="0.01" value={materials} onChange={(e) => setMaterials(e.target.value)} />
      </div>
      <div>
        <label htmlFor="retention">Retention Withheld</label>
        <input id="retention" type="number" step="0.01" value={retention} onChange={(e) => setRetention(e.target.value)} />
      </div>

      <div aria-label="Calculated fields">
        <p>Revised Contract: <span data-testid="revised-contract">${revisedContract.toLocaleString()}</span></p>
        <p>This Period: <span data-testid="this-period">${thisPeriod.toLocaleString()}</span></p>
        <p>Amount Due: <span data-testid="amount-due">${amountDue.toLocaleString()}</span></p>
        <p>Completion: <span data-testid="completion-pct">{completionPct}%</span></p>
      </div>

      <button type="submit" aria-label="Save Claim">Save Claim</button>
      <button type="button" onClick={onCancel}>Cancel</button>
    </form>
  )
}
