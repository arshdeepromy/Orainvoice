import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

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

export default function VariationList() {
  const [variations, setVariations] = useState<VariationOrder[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')

  const fetchVariations = useCallback(async () => {
    setLoading(true)
    try {
      const params = statusFilter ? `?status=${statusFilter}` : ''
      const res = await apiClient.get(`/api/v2/variations${params}`)
      setVariations(res.data.variations)
      setTotal(res.data.total)
    } catch {
      setVariations([])
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => { fetchVariations() }, [fetchVariations])

  const handleApprove = async (id: string) => {
    try {
      await apiClient.put(`/api/v2/variations/${id}/approve`)
      fetchVariations()
    } catch {
      // Error handling
    }
  }

  if (loading) {
    return <div role="status" aria-label="Loading variations">Loading…</div>
  }

  return (
    <div>
      <h1>Variation Orders</h1>
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
        <button onClick={() => setShowForm(true)} aria-label="New variation">
          New Variation
        </button>
      </div>

      {showForm && (
        <VariationInlineForm
          onCreated={() => { setShowForm(false); fetchVariations() }}
          onCancel={() => setShowForm(false)}
        />
      )}

      {variations.length === 0 ? (
        <p>No variation orders found</p>
      ) : (
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
            {variations.map((v) => (
              <tr key={v.id}>
                <td>{v.variation_number}</td>
                <td>{v.description}</td>
                <td>${Number(v.cost_impact).toLocaleString()}</td>
                <td>{v.status}</td>
                <td>
                  {(v.status === 'draft' || v.status === 'submitted') && (
                    <button
                      onClick={() => handleApprove(v.id)}
                      aria-label={`Approve variation ${v.variation_number}`}
                    >
                      Approve
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function VariationInlineForm({
  onCreated,
  onCancel,
}: {
  onCreated: () => void
  onCancel: () => void
}) {
  const [projectId, setProjectId] = useState('')
  const [description, setDescription] = useState('')
  const [costImpact, setCostImpact] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    await apiClient.post('/api/v2/variations', {
      project_id: projectId,
      description,
      cost_impact: Number(costImpact),
    })
    onCreated()
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Create variation order">
      <div>
        <label htmlFor="vo-project-id">Project ID</label>
        <input id="vo-project-id" value={projectId} onChange={(e) => setProjectId(e.target.value)} required />
      </div>
      <div>
        <label htmlFor="vo-description">Description</label>
        <textarea id="vo-description" value={description} onChange={(e) => setDescription(e.target.value)} required />
      </div>
      <div>
        <label htmlFor="vo-cost-impact">Cost Impact</label>
        <input id="vo-cost-impact" type="number" step="0.01" value={costImpact} onChange={(e) => setCostImpact(e.target.value)} required />
      </div>
      <button type="submit" aria-label="Save Variation">Save Variation</button>
      <button type="button" onClick={onCancel}>Cancel</button>
    </form>
  )
}
