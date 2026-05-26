/**
 * Fleet Portal quotes page — list + request form + accept/decline.
 *
 * Implements: B2B Fleet Portal — Requirements 12.1–12.7.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import { fleetClient } from '../api/client'
import { listQuotes, listVehicles } from '../api/endpoints'
import type { QuoteRequest, VehicleListItem } from '../api/types'

export default function QuotesPage() {
  const [quotes, setQuotes] = useState<QuoteRequest[]>([])
  const [vehicles, setVehicles] = useState<VehicleListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)

  const fetchData = async () => {
    try {
      const [q, v] = await Promise.all([listQuotes(), listVehicles(0, 100)])
      setQuotes(q.items ?? [])
      setVehicles(v.items ?? [])
    } catch {} finally { setLoading(false) }
  }

  useEffect(() => { fetchData() }, [])

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Quotes</h1>
        <button onClick={() => setShowForm(true)} className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-indigo-700">
          + Request Quote
        </button>
      </div>

      {showForm && <QuoteForm vehicles={vehicles} onClose={() => setShowForm(false)} onCreated={() => { setShowForm(false); fetchData() }} />}

      {(quotes ?? []).length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center dark:border-gray-700">
          <p className="text-sm text-gray-500">No quotes yet. Request a quote for vehicle servicing and the workshop will respond with pricing.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {(quotes ?? []).map(q => (
            <div key={q.id} className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">{q.service_description}</p>
                  <p className="text-xs text-gray-500 mt-1">{q.rego || 'Vehicle'} · Requested {new Date(q.created_at).toLocaleDateString()}</p>
                  {q.quote_total && <p className="text-sm font-semibold mt-1 text-green-700">${q.quote_total}</p>}
                  {q.quote_valid_until && <p className="text-xs text-gray-500">Valid until {q.quote_valid_until}</p>}
                </div>
                <StatusChip status={q.status} />
              </div>
              {q.status === 'quoted' && (
                <div className="mt-3 flex gap-2">
                  <button onClick={() => acceptQuote(q.id, fetchData)} className="rounded-md bg-green-600 px-3 py-1.5 text-xs font-medium text-white min-h-[44px] hover:bg-green-700">Accept</button>
                  <button onClick={() => declineQuote(q.id, fetchData)} className="rounded-md border border-red-300 px-3 py-1.5 text-xs font-medium text-red-700 min-h-[44px] hover:bg-red-50">Decline</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function StatusChip({ status }: { status: string }) {
  const cls = status === 'accepted' ? 'bg-green-100 text-green-800' : status === 'declined' ? 'bg-red-100 text-red-800' : status === 'quoted' ? 'bg-amber-100 text-amber-800' : status === 'expired' ? 'bg-gray-100 text-gray-600' : 'bg-blue-100 text-blue-800'
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>{status}</span>
}

async function acceptQuote(id: string, refresh: () => void) {
  if (!confirm('Accept this quote?')) return
  try { await fleetClient.post(`/quotes/${id}/accept`); refresh() } catch {}
}

async function declineQuote(id: string, refresh: () => void) {
  if (!confirm('Decline this quote?')) return
  try { await fleetClient.post(`/quotes/${id}/decline`); refresh() } catch {}
}

function QuoteForm({ vehicles, onClose, onCreated }: { vehicles: VehicleListItem[]; onClose: () => void; onCreated: () => void }) {
  const [vehicleId, setVehicleId] = useState('')
  const [desc, setDesc] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!vehicleId || desc.length < 10) { setError('Select a vehicle and describe the service (min 10 chars).'); return }
    setSubmitting(true); setError(null)
    try {
      await fleetClient.post('/quotes/request', { customer_vehicle_id: vehicleId, service_description: desc, notes: notes || null })
      onCreated()
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to request quote.')
    } finally { setSubmitting(false) }
  }

  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50/50 p-4 dark:border-indigo-900 dark:bg-indigo-950/20">
      <h2 className="text-sm font-medium mb-3">Request a Quote</h2>
      {error && <p className="text-xs text-red-600 mb-2">{error}</p>}
      <form onSubmit={handleSubmit} className="space-y-3">
        <select value={vehicleId} onChange={e => setVehicleId(e.target.value)} className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white">
          <option value="">Select vehicle…</option>
          {(vehicles ?? []).map(v => <option key={v.customer_vehicle_id} value={v.customer_vehicle_id}>{v.rego} — {v.make} {v.model}</option>)}
        </select>
        <textarea value={desc} onChange={e => setDesc(e.target.value)} placeholder="Describe the service needed (min 10 chars)…" rows={3}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
        <input type="text" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Additional notes (optional)"
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
        <div className="flex gap-2">
          <button type="submit" disabled={submitting} className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] disabled:opacity-50 hover:bg-indigo-700">
            {submitting ? 'Submitting…' : 'Request Quote'}
          </button>
          <button type="button" onClick={onClose} className="rounded-md border border-gray-300 px-4 py-2 text-sm min-h-[44px] hover:bg-gray-50 dark:border-gray-700">Cancel</button>
        </div>
      </form>
    </div>
  )
}
