/**
 * Workshop Admin — Fleet quote queue.
 *
 * Lists fleet quote requests. "Link Quote" opens a picker showing the
 * org's draft/sent quotes; the admin selects one to attach. There's
 * also a "Create new quote" shortcut that opens the standard staff
 * quote-create page so they can fill in line items first, then come
 * back and link.
 *
 * Implements: B2B Fleet Portal — Req 16.3, 16.4.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

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

interface OrgQuote {
  id: string
  quote_number: string | null
  status: string
  total: string | number
  customer_name?: string | null
  vehicle_rego?: string | null
}

export default function QuoteQueue() {
  const [quotes, setQuotes] = useState<QuoteRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [linkingFor, setLinkingFor] = useState<QuoteRequest | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchQuotes = async (signal?: AbortSignal) => {
    setError(null)
    try {
      const res = await apiClient.get<{ items: QuoteRequest[]; total: number }>(
        '/api/v2/fleet-portal/admin/quotes',
        { params: { limit: 50 }, signal },
      )
      setQuotes(res.data?.items ?? [])
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to load quotes.'
      setError(detail)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    void fetchQuotes(controller.signal)
    return () => controller.abort()
  }, [])

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Fleet Quote Requests</h1>
        <Link
          to="/fleet-portal-admin"
          className="text-sm text-indigo-600 hover:underline"
        >
          ← Fleet Portal
        </Link>
      </div>

      {error ? (
        <p className="rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
          {error}
        </p>
      ) : null}

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
              {(quotes ?? []).map((q) => (
                <tr key={q.id}>
                  <td className="px-3 py-2">{q.requested_by_name ?? '—'}</td>
                  <td className="px-3 py-2 font-medium">{q.rego ?? '—'}</td>
                  <td className="px-3 py-2 max-w-[260px] truncate" title={q.service_description}>
                    {q.service_description}
                  </td>
                  <td className="px-3 py-2 text-gray-500">
                    {q.created_at ? new Date(q.created_at).toLocaleDateString() : '—'}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={
                        'rounded-full px-2 py-0.5 text-xs font-medium ' +
                        (q.status === 'pending'
                          ? 'bg-blue-100 text-blue-800'
                          : q.status === 'quoted'
                            ? 'bg-green-100 text-green-800'
                            : q.status === 'accepted'
                              ? 'bg-emerald-100 text-emerald-800'
                              : q.status === 'declined'
                                ? 'bg-red-100 text-red-800'
                                : 'bg-gray-100 text-gray-600')
                      }
                    >
                      {q.status}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {q.status === 'pending' ? (
                      <button
                        onClick={() => setLinkingFor(q)}
                        className="text-xs text-indigo-700 hover:underline min-h-[36px]"
                      >
                        Link / Create Quote
                      </button>
                    ) : null}
                    {q.quote_id ? (
                      <Link
                        to={`/quotes/${q.quote_id}`}
                        className="text-xs text-indigo-700 hover:underline min-h-[36px]"
                      >
                        View linked quote
                      </Link>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {linkingFor ? (
        <LinkQuoteModal
          fleetRequest={linkingFor}
          onClose={() => setLinkingFor(null)}
          onLinked={() => {
            setLinkingFor(null)
            void fetchQuotes()
          }}
        />
      ) : null}
    </div>
  )
}

function LinkQuoteModal({
  fleetRequest,
  onClose,
  onLinked,
}: {
  fleetRequest: QuoteRequest
  onClose: () => void
  onLinked: () => void
}) {
  const [orgQuotes, setOrgQuotes] = useState<OrgQuote[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    const c = new AbortController()
    const load = async () => {
      try {
        const res = await apiClient.get<{ items?: OrgQuote[]; quotes?: OrgQuote[] }>(
          '/api/v1/quotes',
          { signal: c.signal, params: { limit: 50, status: 'sent' } },
        )
        setOrgQuotes(res.data?.items ?? res.data?.quotes ?? [])
      } catch {
        if (!c.signal.aborted) setOrgQuotes([])
      } finally {
        if (!c.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => c.abort()
  }, [])

  const filtered = (orgQuotes ?? []).filter((q) => {
    if (!search.trim()) return true
    const needle = search.toLowerCase()
    return (
      (q.quote_number ?? '').toLowerCase().includes(needle) ||
      (q.customer_name ?? '').toLowerCase().includes(needle) ||
      (q.vehicle_rego ?? '').toLowerCase().includes(needle)
    )
  })

  const link = async (quoteId: string) => {
    setSubmitting(true)
    setErr(null)
    try {
      await apiClient.post(
        `/api/v2/fleet-portal/admin/quotes/${fleetRequest.id}/link`,
        { quote_id: quoteId },
      )
      onLinked()
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to link quote.'
      setErr(detail)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-2xl rounded-lg bg-white p-4 shadow-lg dark:bg-gray-900">
        <div className="mb-2 flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold">Link a quote to this request</h2>
            <p className="text-xs text-gray-500">
              {fleetRequest.rego ? `${fleetRequest.rego} — ` : ''}
              {fleetRequest.service_description}
            </p>
          </div>
          <Link
            to={`/quotes/new?vehicle_rego=${encodeURIComponent(fleetRequest.rego ?? '')}&description=${encodeURIComponent(fleetRequest.service_description)}`}
            className="text-xs text-indigo-600 hover:underline"
            target="_blank"
          >
            + Create new quote ↗
          </Link>
        </div>
        {err ? <p className="mb-2 text-xs text-red-600">{err}</p> : null}
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by number, customer, or rego"
          className="mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-800 dark:text-white"
        />
        <div className="max-h-96 overflow-y-auto rounded border border-gray-200 dark:border-gray-700">
          {loading ? (
            <p className="p-4 text-xs text-gray-500">Loading quotes…</p>
          ) : filtered.length === 0 ? (
            <p className="p-4 text-xs text-gray-500">No matching quotes.</p>
          ) : (
            <ul className="divide-y divide-gray-200 dark:divide-gray-700">
              {filtered.map((q) => (
                <li key={q.id} className="flex items-center justify-between px-3 py-2">
                  <div>
                    <p className="text-sm font-medium">{q.quote_number ?? q.id.slice(0, 8)}</p>
                    <p className="text-xs text-gray-500">
                      {q.customer_name ?? '—'} · {q.vehicle_rego ?? '—'} · {q.status}
                    </p>
                  </div>
                  <button
                    onClick={() => void link(q.id)}
                    disabled={submitting}
                    className="rounded-md border border-indigo-300 px-3 py-1.5 text-xs font-medium text-indigo-700 min-h-[36px] hover:bg-indigo-50 disabled:opacity-50"
                  >
                    Link
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={onClose}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] hover:bg-gray-50 dark:border-gray-700"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
