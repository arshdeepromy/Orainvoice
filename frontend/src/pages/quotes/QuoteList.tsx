/**
 * Filterable list view for quotes with search, status filter, and pagination.
 *
 * Validates: Requirement 12.1, 12.2
 */

import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

interface Quote {
  id: string
  quote_number: string
  customer_id: string
  status: string
  total: string
  currency: string | null
  expiry_date: string | null
  version_number: number
  created_at: string
}

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'draft', label: 'Draft' },
  { value: 'sent', label: 'Sent' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'declined', label: 'Declined' },
  { value: 'expired', label: 'Expired' },
  { value: 'converted', label: 'Converted' },
]

export default function QuoteList() {
  const [quotes, setQuotes] = useState<Quote[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')
  const pageSize = 20

  const fetchQuotes = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      })
      if (statusFilter) params.set('status', statusFilter)

      const res = await apiClient.get(`/api/v2/quotes?${params}`)
      setQuotes(res.data.quotes)
      setTotal(res.data.total)
    } catch {
      setQuotes([])
    } finally {
      setLoading(false)
    }
  }, [page, statusFilter])

  useEffect(() => { fetchQuotes() }, [fetchQuotes])

  const totalPages = Math.ceil(total / pageSize)

  if (loading) {
    return <div role="status" aria-label="Loading quotes">Loading quotes…</div>
  }

  return (
    <div>
      <h1>Quotes</h1>

      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
        <div>
          <label htmlFor="quote-status-filter">Status</label>
          <select
            id="quote-status-filter"
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      </div>

      {quotes.length === 0 ? (
        <p>No quotes found.</p>
      ) : (
        <table role="table" aria-label="Quotes list">
          <thead>
            <tr>
              <th>Quote #</th>
              <th>Status</th>
              <th>Total</th>
              <th>Expiry</th>
              <th>Version</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {quotes.map((q) => (
              <tr key={q.id}>
                <td>{q.quote_number}</td>
                <td>{q.status}</td>
                <td>{q.currency ?? ''} {q.total}</td>
                <td>{q.expiry_date ?? '—'}</td>
                <td>v{q.version_number}</td>
                <td>{new Date(q.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {totalPages > 1 && (
        <nav aria-label="Quote pagination">
          <button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span> Page {page} of {totalPages} </span>
          <button disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Next</button>
        </nav>
      )}
    </div>
  )
}
