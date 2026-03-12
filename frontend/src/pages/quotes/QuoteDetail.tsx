/**
 * Zoho-style quote detail view with send, convert, and status actions.
 */

import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '../../api/client'
import { Button } from '../../components/ui'

interface LineItem {
  id: string
  item_type: string
  description: string
  quantity: string | number
  unit_price: string | number
  hours: string | number | null
  hourly_rate: string | number | null
  is_gst_exempt: boolean
  warranty_note: string | null
  line_total: string | number
  sort_order: number
}

interface QuoteData {
  id: string
  org_id: string
  customer_id: string
  quote_number: string
  vehicle_rego: string | null
  vehicle_make: string | null
  vehicle_model: string | null
  vehicle_year: number | null
  project_id: string | null
  status: string
  valid_until: string | null
  subtotal: string | number
  gst_amount: string | number
  total: string | number
  discount_type: string | null
  discount_value: string | number
  discount_amount: string | number
  shipping_charges: string | number
  adjustment: string | number
  notes: string | null
  terms: string | null
  subject: string | null
  acceptance_token: string | null
  converted_invoice_id: string | null
  line_items: LineItem[]
  created_by: string
  created_at: string
  updated_at: string
}

interface QuoteDetailProps {
  quoteId: string
}

const STATUS_STYLES: Record<string, { bg: string; text: string }> = {
  draft: { bg: 'bg-gray-100', text: 'text-gray-700' },
  sent: { bg: 'bg-blue-50', text: 'text-blue-700' },
  accepted: { bg: 'bg-emerald-50', text: 'text-emerald-700' },
  declined: { bg: 'bg-red-50', text: 'text-red-700' },
  expired: { bg: 'bg-gray-100', text: 'text-gray-500' },
  converted: { bg: 'bg-emerald-50', text: 'text-emerald-700' },
}

function formatNZD(amount: number | string | null | undefined): string {
  if (amount == null) return '$0.00'
  const num = typeof amount === 'string' ? parseFloat(amount) : amount
  if (isNaN(num)) return '$0.00'
  return `$${num.toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(dateStr))
}

export default function QuoteDetail({ quoteId }: QuoteDetailProps) {
  const navigate = useNavigate()
  const [quote, setQuote] = useState<QuoteData | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState(false)

  const fetchQuote = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.get(`/quotes/${quoteId}`)
      const data = res.data as any
      // Handle both wrapped and unwrapped response
      setQuote(data?.quote || data)
    } catch {
      setError('Failed to load quote')
    } finally {
      setLoading(false)
    }
  }, [quoteId])

  useEffect(() => { fetchQuote() }, [fetchQuote])

  const handleSend = async () => {
    setActionLoading(true)
    setError(null)
    setSuccessMsg(null)
    try {
      await apiClient.post(`/quotes/${quoteId}/send`)
      setSuccessMsg('Quote sent to customer')
      await fetchQuote()
    } catch (err: unknown) {
      const detail = (err as any)?.response?.data?.detail
      setError(detail || 'Failed to send quote')
    } finally {
      setActionLoading(false)
    }
  }

  const handleConvert = async () => {
    setActionLoading(true)
    setError(null)
    setSuccessMsg(null)
    try {
      const res = await apiClient.post(`/quotes/${quoteId}/convert`)
      const data = res.data as any
      setSuccessMsg(`Quote converted to invoice`)
      if (data?.invoice_id) {
        setTimeout(() => navigate(`/invoices/${data.invoice_id}`), 1500)
      } else {
        await fetchQuote()
      }
    } catch (err: unknown) {
      const detail = (err as any)?.response?.data?.detail
      setError(detail || 'Failed to convert quote')
    } finally {
      setActionLoading(false)
    }
  }

  const handleRequote = async () => {
    setActionLoading(true)
    setError(null)
    try {
      await apiClient.put(`/quotes/${quoteId}`, { status: 'draft' })
      navigate(`/quotes/${quoteId}/edit`)
    } catch (err: unknown) {
      const detail = (err as any)?.response?.data?.detail
      setError(detail || 'Failed to requote')
    } finally {
      setActionLoading(false)
    }
  }

  const handleDelete = async () => {
    setActionLoading(true)
    setError(null)
    try {
      await apiClient.delete(`/quotes/${quoteId}`)
      navigate('/quotes')
    } catch (err: unknown) {
      const detail = (err as any)?.response?.data?.detail
      setError(detail || 'Failed to delete quote')
    } finally {
      setActionLoading(false)
      setDeleteConfirm(false)
    }
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-16 text-center">
        <div className="text-gray-500">Loading quote…</div>
      </div>
    )
  }

  if (!quote) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-16 text-center">
        <div className="text-red-600">Quote not found</div>
        <button onClick={() => navigate('/quotes')} className="mt-4 text-sm text-blue-600 hover:text-blue-800">
          Back to Quotes
        </button>
      </div>
    )
  }

  const statusStyle = STATUS_STYLES[quote.status] || STATUS_STYLES.draft
  const lineItems = quote.line_items || []
  const canSend = quote.status === 'draft'
  const canConvert = (quote.status === 'sent' || quote.status === 'accepted') && !quote.converted_invoice_id
  const canRequote = quote.status === 'sent'
  const canDelete = ['draft', 'declined', 'expired'].includes(quote.status)

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <button onClick={() => navigate('/quotes')} className="text-gray-400 hover:text-gray-600" aria-label="Back">
            ← Back
          </button>
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">{quote.quote_number}</h1>
            {quote.subject && <p className="text-sm text-gray-500 mt-0.5">{quote.subject}</p>}
          </div>
          <span className={`ml-2 inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold uppercase ${statusStyle.bg} ${statusStyle.text}`}>
            {quote.status}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {canSend && (
            <>
              <Button variant="secondary" onClick={() => navigate(`/quotes/${quoteId}/edit`)}>
                Edit
              </Button>
              <Button variant="primary" onClick={handleSend} loading={actionLoading} disabled={actionLoading}>
                Send to Customer
              </Button>
            </>
          )}
          {canRequote && (
            <Button variant="secondary" onClick={handleRequote} loading={actionLoading} disabled={actionLoading}>
              Requote
            </Button>
          )}
          {canConvert && (
            <Button variant="secondary" onClick={handleConvert} loading={actionLoading} disabled={actionLoading}>
              Convert to Invoice
            </Button>
          )}
          {canDelete && !deleteConfirm && (
            <button
              onClick={() => setDeleteConfirm(true)}
              className="rounded-md border border-red-200 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50"
              disabled={actionLoading}
            >
              Delete
            </button>
          )}
          {deleteConfirm && (
            <div className="flex items-center gap-2">
              <span className="text-sm text-red-600">Delete this quote?</span>
              <button
                onClick={handleDelete}
                disabled={actionLoading}
                className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {actionLoading ? 'Deleting…' : 'Confirm'}
              </button>
              <button
                onClick={() => setDeleteConfirm(false)}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Messages */}
      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}
      {successMsg && (
        <div className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700" role="status">
          {successMsg}
        </div>
      )}

      {/* Converted invoice link */}
      {quote.converted_invoice_id && (
        <div className="mb-4 rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700">
          This quote has been converted to an invoice.{' '}
          <button onClick={() => navigate(`/invoices/${quote.converted_invoice_id}`)}
            className="font-medium underline hover:text-blue-900">
            View Invoice
          </button>
        </div>
      )}

      <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
        {/* Quote info grid */}
        <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-3">
            <div>
              <span className="text-xs font-medium uppercase text-gray-500">Quote Date</span>
              <p className="text-sm text-gray-900">{formatDate(quote.created_at)}</p>
            </div>
            <div>
              <span className="text-xs font-medium uppercase text-gray-500">Valid Until</span>
              <p className="text-sm text-gray-900">{formatDate(quote.valid_until)}</p>
            </div>
            {quote.vehicle_rego && (
              <div>
                <span className="text-xs font-medium uppercase text-gray-500">Vehicle</span>
                <p className="text-sm text-gray-900">
                  <span className="font-semibold">{quote.vehicle_rego}</span>
                  {' '}{quote.vehicle_year || ''} {quote.vehicle_make || ''} {quote.vehicle_model || ''}
                </p>
              </div>
            )}
          </div>
          <div className="space-y-3">
            <div>
              <span className="text-xs font-medium uppercase text-gray-500">Status</span>
              <p className="text-sm">
                <span className={`font-semibold uppercase ${statusStyle.text}`}>{quote.status}</span>
              </p>
            </div>
            <div>
              <span className="text-xs font-medium uppercase text-gray-500">Quote Number</span>
              <p className="text-sm text-gray-900 font-medium">{quote.quote_number}</p>
            </div>
          </div>
        </div>

        {/* Line Items Table */}
        <div className="border-t border-gray-200 p-6">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Line Items</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-2 px-2 text-xs font-medium uppercase text-gray-500 w-[45%]">Item Details</th>
                  <th className="text-center py-2 px-2 text-xs font-medium uppercase text-gray-500 w-[12%]">Qty</th>
                  <th className="text-right py-2 px-2 text-xs font-medium uppercase text-gray-500 w-[15%]">Rate</th>
                  <th className="text-center py-2 px-2 text-xs font-medium uppercase text-gray-500 w-[10%]">Tax</th>
                  <th className="text-right py-2 px-2 text-xs font-medium uppercase text-gray-500 w-[18%]">Amount</th>
                </tr>
              </thead>
              <tbody>
                {lineItems.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-2 py-8 text-center text-gray-500">No line items</td>
                  </tr>
                ) : (
                  lineItems.map((item, idx) => (
                    <tr key={item.id || idx} className="border-b border-gray-100">
                      <td className="py-2.5 px-2 text-gray-900">
                        <div>{item.description?.split('\n')[0]}</div>
                        {item.description?.includes('\n') && (
                          <div className="text-xs text-gray-500 mt-0.5 whitespace-pre-line">{item.description.split('\n').slice(1).join('\n')}</div>
                        )}
                      </td>
                      <td className="py-2.5 px-2 text-center text-gray-700">
                        {item.item_type === 'labour' ? (item.hours || '—') : item.quantity}
                      </td>
                      <td className="py-2.5 px-2 text-right text-gray-700">
                        {formatNZD(item.item_type === 'labour' ? item.hourly_rate : item.unit_price)}
                      </td>
                      <td className="py-2.5 px-2 text-center text-gray-500 text-xs">
                        {item.is_gst_exempt ? 'Exempt' : 'GST 15%'}
                      </td>
                      <td className="py-2.5 px-2 text-right font-medium text-gray-900">
                        {formatNZD(item.line_total)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Totals */}
          <div className="flex justify-end mt-6">
            <div className="w-80 space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">Sub Total</span>
                <span className="font-medium text-gray-900">{formatNZD(quote.subtotal)}</span>
              </div>

              {/* Discount */}
              {Number(quote.discount_amount || 0) > 0 && (
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">
                    Discount
                    {quote.discount_type === 'percentage' && Number(quote.discount_value || 0) > 0
                      ? ` (${quote.discount_value}%)`
                      : ''}
                  </span>
                  <span className="text-red-600">-{formatNZD(quote.discount_amount)}</span>
                </div>
              )}

              <div className="flex justify-between text-sm text-gray-600">
                <span>GST (15%)</span>
                <span className="text-gray-900">{formatNZD(quote.gst_amount)}</span>
              </div>

              {/* Shipping */}
              {Number(quote.shipping_charges || 0) > 0 && (
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Shipping Charges</span>
                  <span className="text-gray-900">{formatNZD(quote.shipping_charges)}</span>
                </div>
              )}

              {/* Adjustment */}
              {Number(quote.adjustment || 0) !== 0 && (
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Adjustment</span>
                  <span className="text-gray-900">{formatNZD(quote.adjustment)}</span>
                </div>
              )}

              <div className="flex justify-between text-base font-semibold text-gray-900 border-t border-gray-200 pt-2">
                <span>Total (NZD)</span>
                <span>{formatNZD(quote.total)}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Notes & Terms */}
        {(quote.notes || quote.terms) && (
          <div className="border-t border-gray-200 p-6 grid grid-cols-1 md:grid-cols-2 gap-6">
            {quote.notes && (
              <div>
                <span className="text-xs font-medium uppercase text-gray-500">Customer Notes</span>
                <p className="mt-1 text-sm text-gray-700 whitespace-pre-wrap">{quote.notes}</p>
              </div>
            )}
            {quote.terms && (
              <div>
                <span className="text-xs font-medium uppercase text-gray-500">Terms & Conditions</span>
                <p className="mt-1 text-sm text-gray-700 whitespace-pre-wrap">{quote.terms}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
