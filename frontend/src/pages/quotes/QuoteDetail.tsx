/**
 * Quote detail view with send, accept, convert, and revise actions.
 *
 * Validates: Requirement 12.2, 12.4, 12.5, 12.6, 12.7
 */

import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

interface QuoteDetail {
  id: string
  quote_number: string
  customer_id: string
  project_id: string | null
  status: string
  expiry_date: string | null
  terms: string | null
  internal_notes: string | null
  line_items: Array<{
    description: string
    quantity: string
    unit_price: string
    tax_rate?: string
  }>
  subtotal: string
  tax_amount: string
  total: string
  currency: string | null
  version_number: number
  previous_version_id: string | null
  converted_invoice_id: string | null
  acceptance_token: string | null
  created_at: string
  updated_at: string
}

interface QuoteDetailProps {
  quoteId: string
}

export default function QuoteDetail({ quoteId }: QuoteDetailProps) {
  const [quote, setQuote] = useState<QuoteDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  const fetchQuote = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.get(`/api/v2/quotes/${quoteId}`)
      setQuote(res.data)
    } catch {
      setError('Failed to load quote')
    } finally {
      setLoading(false)
    }
  }, [quoteId])

  useEffect(() => { fetchQuote() }, [fetchQuote])

  const handleAction = async (action: string, method: 'put' | 'post' = 'post') => {
    setActionLoading(true)
    setError(null)
    setSuccessMsg(null)
    try {
      const url = `/api/v2/quotes/${quoteId}/${action}`
      if (method === 'put') {
        await apiClient.put(url)
      } else {
        await apiClient.post(url)
      }
      setSuccessMsg(`Action "${action}" completed successfully`)
      await fetchQuote()
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? `Failed to ${action}`)
    } finally {
      setActionLoading(false)
    }
  }

  if (loading) {
    return <div role="status" aria-label="Loading quote">Loading quote…</div>
  }

  if (!quote) {
    return <div role="alert">Quote not found</div>
  }

  return (
    <div>
      <h1>Quote {quote.quote_number}</h1>
      <p>Status: <strong>{quote.status}</strong> | Version: v{quote.version_number}</p>

      {error && <div role="alert" style={{ color: 'red' }}>{error}</div>}
      {successMsg && <div role="status">{successMsg}</div>}

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: '0.5rem', margin: '1rem 0' }}>
        {quote.status === 'draft' && (
          <button
            onClick={() => handleAction('send', 'put')}
            disabled={actionLoading}
            aria-label="Send quote"
          >
            Send to Customer
          </button>
        )}
        {quote.status === 'accepted' && !quote.converted_invoice_id && (
          <button
            onClick={() => handleAction('convert-to-invoice')}
            disabled={actionLoading}
            aria-label="Convert to invoice"
          >
            Convert to Invoice
          </button>
        )}
        {['draft', 'sent', 'declined'].includes(quote.status) && (
          <button
            onClick={() => handleAction('revise')}
            disabled={actionLoading}
            aria-label="Create revision"
          >
            Create Revision
          </button>
        )}
      </div>

      {/* Quote details */}
      <section aria-label="Quote details">
        <h2>Details</h2>
        <dl>
          <dt>Customer ID</dt><dd>{quote.customer_id}</dd>
          {quote.expiry_date && <><dt>Expiry Date</dt><dd>{quote.expiry_date}</dd></>}
          {quote.terms && <><dt>Terms</dt><dd>{quote.terms}</dd></>}
          {quote.converted_invoice_id && <><dt>Invoice ID</dt><dd>{quote.converted_invoice_id}</dd></>}
          {quote.previous_version_id && <><dt>Previous Version</dt><dd>{quote.previous_version_id}</dd></>}
        </dl>
      </section>

      {/* Line items */}
      <section aria-label="Line items">
        <h2>Line Items</h2>
        {quote.line_items.length === 0 ? (
          <p>No line items.</p>
        ) : (
          <table role="table" aria-label="Quote line items">
            <thead>
              <tr>
                <th>Description</th>
                <th>Qty</th>
                <th>Unit Price</th>
                <th>Tax Rate</th>
              </tr>
            </thead>
            <tbody>
              {quote.line_items.map((item, idx) => (
                <tr key={idx}>
                  <td>{item.description}</td>
                  <td>{item.quantity}</td>
                  <td>{item.unit_price}</td>
                  <td>{item.tax_rate ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Totals */}
      <section aria-label="Quote totals">
        <p>Subtotal: {quote.currency ?? ''} {quote.subtotal}</p>
        <p>Tax: {quote.currency ?? ''} {quote.tax_amount}</p>
        <p><strong>Total: {quote.currency ?? ''} {quote.total}</strong></p>
      </section>
    </div>
  )
}
