/**
 * Workshop Admin — Fleet quote queue.
 * Shows pending quote requests with link-quote action.
 *
 * Implements: B2B Fleet Portal — Requirement 16.3.
 */
import { useEffect, useState } from 'react'

import apiClient from '../../api/client'

interface QuoteRequest {
  id: string
  customer_vehicle_id: string
  rego: string | null
  requested_by_name: string | null
  service_description: string
  notes: string | null
  status: string
  quote_id: string | null
  created_at: string
}

export default function QuoteQueue() {
  const [quotes, setQuotes] = useState<QuoteRequest[]>([])
  const [loading, setLoading] = useState(true)

  const fetchQuotes = async (signal?: AbortSignal) => {
    try {
      const res = await apiClient.get<{ items: QuoteRequest[]; total: number }>(
        '/api/v2/fleet-portal/admin/quotes',
        { params: { limit: 50 }, signal },
      )
      setQuotes(res.data?.items ?? [])
    } catch {} finally { setLoading(false) }
  }

  useEffect(() => {
    const controller = new AbortController()
    fetchQuotes(controller.signal)
    return () => controller.abort()
  }, [])

  const linkQuote = async (requestId: string) => {
    const quoteId = prompt('Enter the Quote ID to link to this request:')
    if (!quoteId) return
    try {
      await apiClient.post(`/api/v2/fleet-portal/admin/quotes/${requestId}/link`, {
        quote_id: quoteId,
      })
      await fetchQuotes()
    } catch { alert('Failed to link quote. Ensure the Quote ID is valid.') }
  }

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Fleet Quote Requests</h1>
      {(quotes ?? []).length === 0 ? (
        <p className="text-sm text-gray-500">No quote requests.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-800 text-sm">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Customer</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Vehicle</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Service Requested</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Date</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Status</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-800 bg-white dark:bg-gray-950">
              {(quotes ?? []).map(q => (
                <tr key={q.id}>
                  <td className="px-3 py-2">{q.requested_by_name ?? '—'}</td>
                  <td className="px-3 py-2 font-medium">{q.rego ?? '—'}</td>
                  <td className="px-3 py-2 max-w-[250px] truncate">{q.service_description}</td>
                  <td className="px-3 py-2 text-gray-500">{q.created_at ? new Date(q.created_at).toLocaleDateString() : '—'}</td>
                  <td className="px-3 py-2">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      q.status === 'pending' ? 'bg-blue-100 text-blue-800' :
                      q.status === 'quoted' ? 'bg-green-100 text-green-800' :
                      q.status === 'accepted' ? 'bg-emerald-100 text-emerald-800' :
                      q.status === 'declined' ? 'bg-red-100 text-red-800' :
                      'bg-gray-100 text-gray-600'
                    }`}>
                      {q.status}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {q.status === 'pending' && (
                      <button onClick={() => linkQuote(q.id)} className="text-xs text-indigo-700 hover:underline min-h-[36px]">
                        Link Quote
                      </button>
                    )}
                    {q.quote_id && (
                      <span className="text-xs text-gray-500">Linked</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
