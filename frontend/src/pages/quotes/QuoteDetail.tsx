/**
 * Quote detail view with document template preview matching the invoice preview style.
 */

import { useEffect, useState, useCallback, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import apiClient from '../../api/client'
import { useTenant } from '../../contexts/TenantContext'
import { Button } from '../../components/ui'
import QuoteAttachmentList from '../../components/quotes/QuoteAttachmentList'
import { resolveTemplateStyles } from '@/utils/invoiceTemplateStyles'

const PRINT_STYLES = `
@media print {
  nav, aside, header, footer,
  [data-print-hide],
  .no-print {
    display: none !important;
  }
  html, body {
    margin: 0 !important;
    padding: 0 !important;
    background: white !important;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
    overflow: visible !important;
    height: auto !important;
  }
  .flex.h-screen,
  .flex.h-screen.overflow-hidden,
  .flex-1.flex-col.overflow-hidden,
  main.flex-1.overflow-y-auto {
    display: block !important;
    height: auto !important;
    overflow: visible !important;
    margin: 0 !important;
    padding: 0 !important;
    width: 100% !important;
  }
  [data-print-content] {
    max-width: 100% !important;
    margin: 0 !important;
    padding: 10mm !important;
    box-shadow: none !important;
    border: none !important;
    overflow: visible !important;
    height: auto !important;
  }
  table { page-break-inside: avoid; }
  tr    { page-break-inside: avoid; }
  .print-balance-bar {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
    color: #fff !important;
  }
  .print-balance-bar * {
    color: #fff !important;
  }
  .badge-print {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }
  @page {
    margin: 0;
    size: A4;
  }
}
`

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
  catalogue_item_id: string | null
  stock_item_id: string | null
  gst_inclusive: boolean
  inclusive_price: string | number | null
  tax_rate: string | number
  part_number?: string | null
}

interface Vehicle {
  id?: string | null
  rego?: string | null
  make?: string | null
  model?: string | null
  year?: number | null
  odometer?: number | null
  wof_expiry?: string | null
  cof_expiry?: string | null
}

interface FluidUsage {
  stock_item_id: string
  catalogue_item_id: string
  litres: number
  item_name: string
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
  vehicle_odometer?: number | null
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
  order_number: string | null
  salesperson_id: string | null
  salesperson_name: string | null
  additional_vehicles: Vehicle[]
  fluid_usage: FluidUsage[]
  attachment_count: number
  // Org info for template preview
  org_name?: string
  org_logo_url?: string
  org_address_unit?: string
  org_address_street?: string
  org_address_city?: string
  org_address_state?: string
  org_address_country?: string
  org_address_postcode?: string
  org_phone?: string
  org_email?: string
  org_website?: string
  org_gst_number?: string
  invoice_template_id?: string | null
  invoice_template_colours?: { primary_colour?: string; accent_colour?: string; header_bg_colour?: string } | null
  customer_name?: string
  customer_email?: string
  customer_portal_token?: string | null
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
  const [searchParams] = useSearchParams()
  const { tradeFamily } = useTenant()
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
  const [quote, setQuote] = useState<QuoteData | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState(false)
  const [downloading, setDownloading] = useState<boolean>(false)
  const [copied, setCopied] = useState<boolean>(false)

  const templateStyles = useMemo(
    () => resolveTemplateStyles(
      quote?.invoice_template_id,
      quote?.invoice_template_colours,
    ),
    [quote?.invoice_template_id, quote?.invoice_template_colours],
  )

  const fetchQuote = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.get(`/quotes/${quoteId}`)
      const data = res.data as Record<string, unknown>
      const q = (data?.quote ?? data) as QuoteData
      // Ensure arrays are safe
      if (q) {
        q.line_items = q.line_items ?? []
        q.additional_vehicles = q.additional_vehicles ?? []
        q.fluid_usage = q.fluid_usage ?? []
      }
      setQuote(q)
    } catch {
      setError('Failed to load quote')
    } finally {
      setLoading(false)
    }
  }, [quoteId])

  useEffect(() => { fetchQuote() }, [fetchQuote])

  // Auto-print when navigated with ?print=1
  useEffect(() => {
    if (searchParams.get('print') === '1' && quote && !loading) {
      setTimeout(() => window.print(), 300)
    }
  }, [searchParams, quote, loading])

  // Inject print styles
  useEffect(() => {
    const style = document.createElement('style')
    style.setAttribute('data-quote-print', 'true')
    style.textContent = PRINT_STYLES
    document.head.appendChild(style)
    return () => { style.remove() }
  }, [])

  const handleDownloadPDF = async (): Promise<void> => {
    if (!quote) return
    setDownloading(true)
    setError(null)
    try {
      const res = await apiClient.get(`/quotes/${quote.id}/pdf`, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${quote.quote_number || 'DRAFT'}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to download PDF. Please try again.')
    } finally {
      setDownloading(false)
    }
  }

  const handlePrint = (): void => { window.print() }

  const handleCopyLink = async (): Promise<void> => {
    if (!quote?.acceptance_token) return
    const shareUrl = `${window.location.origin}/api/v1/public/quotes/view/${quote.acceptance_token}`
    try {
      await navigator.clipboard.writeText(shareUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setError('Could not copy link to clipboard. Please copy manually.')
    }
  }

  const handleSend = async () => {
    setActionLoading(true)
    setError(null)
    setSuccessMsg(null)
    try {
      await apiClient.post(`/quotes/${quoteId}/send`)
      setSuccessMsg('Quote emailed to customer')
      await fetchQuote()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to email quote')
    } finally {
      setActionLoading(false)
    }
  }

  const handleIssueQuote = async () => {
    setActionLoading(true)
    setError(null)
    setSuccessMsg(null)
    try {
      await apiClient.put(`/quotes/${quoteId}`, { status: 'sent' })
      setSuccessMsg('Quote issued')
      await fetchQuote()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to issue quote')
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
      const data = res.data as { invoice_id?: string }
      setSuccessMsg('Quote converted to invoice')
      if (data?.invoice_id) {
        setTimeout(() => navigate(`/invoices/${data.invoice_id}`), 1500)
      } else {
        await fetchQuote()
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
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
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
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
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to delete quote')
    } finally {
      setActionLoading(false)
      setDeleteConfirm(false)
    }
  }

  if (loading) {
    return (
      <div className="px-4 py-16 text-center sm:px-6 lg:px-8">
        <div className="text-gray-500">Loading quote…</div>
      </div>
    )
  }

  if (!quote) {
    return (
      <div className="px-4 py-16 text-center sm:px-6 lg:px-8">
        <div className="text-red-600">Quote not found</div>
        <button onClick={() => navigate('/quotes')} className="mt-4 text-sm text-blue-600 hover:text-blue-800">
          Back to Quotes
        </button>
      </div>
    )
  }

  const statusStyle = STATUS_STYLES[quote.status] || STATUS_STYLES.draft
  const lineItems = quote.line_items ?? []
  const canSend = quote.status === 'draft'
  const canConvert = (quote.status === 'sent' || quote.status === 'accepted') && !quote.converted_invoice_id
  const canRequote = quote.status === 'sent'
  const canDelete = ['draft', 'declined', 'expired'].includes(quote.status)
  const isDraft = quote.status === 'draft'

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Action toolbar */}
      <div className="flex items-center justify-between mb-6" data-print-hide>
        <div className="flex items-center gap-4">
          <button onClick={() => navigate('/quotes')} className="text-gray-400 hover:text-gray-600" aria-label="Back">
            ← Back
          </button>
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">{quote.quote_number}</h1>
            {quote.subject && <p className="text-sm text-gray-500 mt-0.5">{quote.subject}</p>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={handlePrint}>Print</Button>
          <Button variant="secondary" onClick={handleDownloadPDF} loading={downloading} disabled={downloading}>
            {downloading ? 'Downloading…' : 'Download PDF'}
          </Button>
          {quote.acceptance_token && (
            <Button variant="secondary" onClick={handleCopyLink}>
              {copied ? 'Copied!' : 'Copy Link'}
            </Button>
          )}
          {canSend && (
            <>
              <Button variant="secondary" onClick={() => navigate(`/quotes/${quoteId}/edit`)}>Edit</Button>
              <Button variant="secondary" onClick={handleIssueQuote} loading={actionLoading} disabled={actionLoading}>
                Issue Quote
              </Button>
              <Button variant="primary" onClick={handleSend} loading={actionLoading} disabled={actionLoading}>
                Email
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
              <button onClick={handleDelete} disabled={actionLoading}
                className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50">
                {actionLoading ? 'Deleting…' : 'Confirm'}
              </button>
              <button onClick={() => setDeleteConfirm(false)}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50">
                Cancel
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Messages */}
      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert" data-print-hide>
          {error}
        </div>
      )}
      {successMsg && (
        <div className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700" role="status" data-print-hide>
          {successMsg}
        </div>
      )}

      {/* Converted invoice link */}
      {quote.converted_invoice_id && (
        <div className="mb-4 rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700" data-print-hide>
          This quote has been converted to an invoice.{' '}
          <button onClick={() => navigate(`/invoices/${quote.converted_invoice_id}`)}
            className="font-medium underline hover:text-blue-900">
            View Invoice
          </button>
        </div>
      )}

      {/* ---- Document Template Preview ---- */}
      <div className="max-w-3xl mx-auto bg-white rounded-xl shadow-sm overflow-hidden border border-gray-200" data-print-content>
        <div className="relative">
          {/* Draft watermark */}
          {isDraft && (
            <div className="absolute top-8 left-8 -rotate-12 text-gray-100 text-6xl font-black tracking-widest pointer-events-none select-none z-0 opacity-60">
              DRAFT
            </div>
          )}

          {/* Header with org info + QUOTE title + total box */}
          <div className={`relative z-10 ${templateStyles.layoutType === 'compact' ? 'px-6 pt-6 pb-4' : 'px-8 pt-8 pb-6'}`} style={{ backgroundColor: templateStyles.headerBgColour }}>
            <div className={`flex ${templateStyles.logoPosition === 'center' ? 'flex-col items-center text-center' : 'items-start justify-between'}`}>
              {/* Org info */}
              <div style={templateStyles.logoPosition === 'side' ? { order: 2 } : undefined}>
                {quote.org_logo_url ? (
                  <img src={quote.org_logo_url} alt={quote.org_name || 'Company'} className="h-12 mb-3" />
                ) : (
                  <div className="flex items-center gap-2 mb-3">
                    <div className="w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold text-lg" style={{ background: templateStyles.primaryColour }}>
                      {(quote.org_name || 'O')[0]}
                    </div>
                    <span className={`text-lg font-bold ${templateStyles.isHeaderDark ? 'text-white' : 'text-gray-900'}`}>{quote.org_name || 'Your Company'}</span>
                  </div>
                )}
                <div className={`text-xs ${templateStyles.isHeaderDark ? 'text-gray-200' : 'text-gray-500'} space-y-0.5`}>
                  {quote.org_address_street && (
                    <>
                      {quote.org_address_unit && <p>{quote.org_address_unit}</p>}
                      <p>{quote.org_address_street}</p>
                      {(quote.org_address_city || quote.org_address_state || quote.org_address_postcode) && (
                        <p>{[quote.org_address_city, quote.org_address_state, quote.org_address_postcode].filter(Boolean).join(', ')}</p>
                      )}
                      {quote.org_address_country && <p>{quote.org_address_country}</p>}
                    </>
                  )}
                  {quote.org_phone && <p>{quote.org_phone}</p>}
                  {quote.org_email && <p>{quote.org_email}</p>}
                  {quote.org_website && <p>{quote.org_website}</p>}
                </div>
              </div>

              {/* Quote title + total */}
              <div className={templateStyles.logoPosition === 'left' ? 'text-right' : ''} style={templateStyles.logoPosition === 'side' ? { order: 1 } : undefined}>
                <h1 className={`text-2xl font-bold tracking-tight ${templateStyles.isHeaderDark ? 'text-white' : 'text-gray-900'}`}>QUOTE</h1>
                <p className={`text-sm ${templateStyles.isHeaderDark ? 'text-gray-200' : 'text-gray-500'} mt-0.5`}># {quote.quote_number || 'DRAFT'}</p>
                <span className={`ml-2 inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase badge-print ${statusStyle.bg} ${statusStyle.text}`}>
                  {quote.status}
                </span>
                <div className={`mt-3 rounded-lg px-4 py-2 border ${templateStyles.isHeaderDark ? 'bg-white/10 border-white/20' : 'bg-gray-50 border-gray-100'}`}>
                  <p className={`text-xs ${templateStyles.isHeaderDark ? 'text-gray-200' : 'text-gray-500'}`}>Total</p>
                  <p className={`text-xl font-bold tabular-nums ${templateStyles.isHeaderDark ? 'text-white' : 'text-gray-900'}`}>
                    {formatNZD(quote.total)}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Quote To + Quote Meta */}
          <div className={`relative z-10 ${templateStyles.layoutType === 'compact' ? 'px-6 pb-4' : 'px-8 pb-6'}`}>
            <div className="flex items-start justify-between gap-8">
              {/* Quote To */}
              <div className="flex-1">
                {quote.customer_name ? (
                  <div className="rounded-lg p-4 border" style={{ backgroundColor: templateStyles.accentColour + '10', borderColor: templateStyles.accentColour + '30' }}>
                    <p className="text-xs font-semibold uppercase tracking-wider mb-1.5" style={{ color: templateStyles.accentColour }}>Quote To</p>
                    <p className="font-semibold text-gray-900">{quote.customer_name}</p>
                    {quote.customer_email && (
                      <p className="text-sm text-gray-600 mt-0.5">{quote.customer_email}</p>
                    )}
                  </div>
                ) : (
                  <div className="bg-gray-50 rounded-lg p-4 border border-gray-100">
                    <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Quote To</p>
                    <p className="text-sm text-gray-400">No customer assigned</p>
                  </div>
                )}
              </div>

              {/* Quote meta */}
              <div className="w-56 shrink-0">
                <dl className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Quote Date :</dt>
                    <dd className="text-gray-900 font-medium">{formatDate(quote.created_at)}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Valid Until :</dt>
                    <dd className="text-gray-900 font-medium">{formatDate(quote.valid_until)}</dd>
                  </div>
                  {quote.terms && (
                    <div className="flex justify-between">
                      <dt className="text-gray-500">Terms :</dt>
                      <dd className="text-gray-900 truncate max-w-[120px]">{quote.terms.split('\n')[0]}</dd>
                    </div>
                  )}
                  {quote.org_gst_number && (
                    <div className="flex justify-between">
                      <dt className="text-gray-500">GST No :</dt>
                      <dd className="text-gray-900 font-mono text-xs">{quote.org_gst_number}</dd>
                    </div>
                  )}
                </dl>
              </div>
            </div>
          </div>

          {/* Vehicle info bar (automotive only) */}
          {isAutomotive && quote.vehicle_rego && (
            <div className="relative z-10 px-8 pb-4">
              <div className="bg-slate-50 rounded-lg border border-slate-200 px-5 py-3">
                <div className="flex items-center gap-6 text-sm flex-wrap">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-gray-400 uppercase tracking-wider">Rego</span>
                    <span className="font-mono font-bold text-gray-900 bg-yellow-100 px-2 py-0.5 rounded text-xs">{quote.vehicle_rego}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-gray-400 uppercase tracking-wider">Vehicle</span>
                    <span className="text-gray-900">{[quote.vehicle_year, quote.vehicle_make, quote.vehicle_model].filter(Boolean).join(' ') || '—'}</span>
                  </div>
                  {(quote.vehicle_odometer ?? 0) > 0 && (
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs text-gray-400 uppercase tracking-wider">Odometer</span>
                      <span className="text-gray-900">{Number(quote.vehicle_odometer ?? 0).toLocaleString()} km</span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Additional vehicles */}
          {isAutomotive && (quote.additional_vehicles ?? []).length > 0 && (
            <div className="relative z-10 px-8 pb-2">
              {(quote.additional_vehicles ?? []).map((av, idx) => (
                <div key={av.rego || idx} className="bg-slate-50 rounded-lg border border-slate-200 px-5 py-2 mt-1">
                  <div className="flex items-center gap-6 text-sm">
                    {av.rego && (
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs text-gray-400 uppercase tracking-wider">Rego</span>
                        <span className="font-mono font-bold text-gray-900 bg-yellow-100 px-2 py-0.5 rounded text-xs">{av.rego}</span>
                      </div>
                    )}
                    {(av.make || av.model) && (
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs text-gray-400 uppercase tracking-wider">Vehicle</span>
                        <span className="text-gray-900">{[av.year, av.make, av.model].filter(Boolean).join(' ') || '—'}</span>
                      </div>
                    )}
                    {(av.odometer ?? 0) > 0 && (
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs text-gray-400 uppercase tracking-wider">Odometer</span>
                        <span className="text-gray-900">{Number(av.odometer ?? 0).toLocaleString()} km</span>
                      </div>
                    )}
                    {av.wof_expiry && (
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs text-gray-400 uppercase tracking-wider">WOF Expiry</span>
                        <span className="text-gray-900">{formatDate(av.wof_expiry)}</span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Line items table */}
          <div className={`relative z-10 ${templateStyles.layoutType === 'compact' ? 'px-6 pb-4' : 'px-8 pb-6'}`}>
            <table className="w-full">
              <thead>
                <tr className="print-table-header" style={{ background: templateStyles.primaryColour, color: '#fff', WebkitPrintColorAdjust: 'exact', printColorAdjust: 'exact' } as React.CSSProperties}>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider rounded-tl-lg" style={{ color: '#fff' }}>#</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider" style={{ color: '#fff' }}>Description</th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wider" style={{ color: '#fff' }}>Qty</th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wider" style={{ color: '#fff' }}>Rate</th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wider" style={{ color: '#fff' }}>Tax</th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wider rounded-tr-lg" style={{ color: '#fff' }}>Amount</th>
                </tr>
              </thead>
              <tbody>
                {lineItems.map((item, idx) => (
                  <tr key={item.id || idx} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'}>
                    <td className={`px-4 ${templateStyles.layoutType === 'compact' ? 'py-1.5' : 'py-3'} text-sm text-gray-500`}>{idx + 1}</td>
                    <td className={`px-4 ${templateStyles.layoutType === 'compact' ? 'py-1.5' : 'py-3'} text-sm text-gray-900`}>
                      <div>{item.description?.split('\n')[0]}</div>
                      {item.description?.includes('\n') && (
                        <div className="text-xs text-gray-500 mt-0.5 whitespace-pre-line">{item.description.split('\n').slice(1).join('\n')}</div>
                      )}
                      {item.part_number && <span className="text-xs text-gray-400 ml-2">#{item.part_number}</span>}
                      {item.warranty_note && (
                        <p className="text-xs text-blue-500 mt-0.5">Warranty: {item.warranty_note}</p>
                      )}
                    </td>
                    <td className={`px-4 ${templateStyles.layoutType === 'compact' ? 'py-1.5' : 'py-3'} text-sm text-gray-900 text-right tabular-nums`}>
                      {item.item_type === 'labour' ? Number(item.hours ?? 0).toFixed(2) : Number(item.quantity ?? 0).toFixed(2)}
                    </td>
                    <td className={`px-4 ${templateStyles.layoutType === 'compact' ? 'py-1.5' : 'py-3'} text-sm text-gray-900 text-right tabular-nums`}>
                      {Number(item.item_type === 'labour' ? (item.hourly_rate ?? 0) : (item.unit_price ?? 0)).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </td>
                    <td className={`px-4 ${templateStyles.layoutType === 'compact' ? 'py-1.5' : 'py-3'} text-sm text-gray-700 text-right tabular-nums`}>
                      {item.is_gst_exempt
                        ? '0.00'
                        : (Number(item.line_total ?? 0) * 0.15).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </td>
                    <td className={`px-4 ${templateStyles.layoutType === 'compact' ? 'py-1.5' : 'py-3'} text-sm font-medium text-gray-900 text-right tabular-nums`}>
                      {item.is_gst_exempt
                        ? Number(item.line_total ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                        : (Number(item.line_total ?? 0) * 1.15).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </td>
                  </tr>
                ))}
                {lineItems.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-400">No line items</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Totals */}
          <div className={`relative z-10 ${templateStyles.layoutType === 'compact' ? 'px-6 pb-4' : 'px-8 pb-6'}`}>
            <div className="flex justify-end">
              <div className="w-72">
                <dl className="space-y-1.5 text-sm">
                  <div className="flex justify-between py-1">
                    <dt className="text-gray-500">Sub Total (Ex GST)</dt>
                    <dd className="text-gray-900 tabular-nums font-medium">
                      {Number(quote.subtotal ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </dd>
                  </div>
                  {Number(quote.discount_amount ?? 0) > 0 && (
                    <div className="flex justify-between py-1 text-emerald-600">
                      <dt>Discount{quote.discount_type === 'percentage' && Number(quote.discount_value ?? 0) > 0 ? ` (${quote.discount_value}%)` : ''}</dt>
                      <dd className="tabular-nums">
                        −{Number(quote.discount_amount ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2 })}
                      </dd>
                    </div>
                  )}
                  <div className="flex justify-between py-1">
                    <dt className="text-gray-500">GST (15%)</dt>
                    <dd className="text-gray-900 tabular-nums">
                      {Number(quote.gst_amount ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </dd>
                  </div>
                  <div className="flex justify-between py-2.5 mt-2 rounded-lg px-4 -mx-4 font-bold border-t border-gray-200 print-balance-bar" style={{ background: templateStyles.primaryColour, color: '#fff', WebkitPrintColorAdjust: 'exact', printColorAdjust: 'exact' } as React.CSSProperties}>
                    <dt style={{ color: '#fff' }}>Total</dt>
                    <dd className="tabular-nums" style={{ color: '#fff' }}>NZD{Number(quote.total ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</dd>
                  </div>
                </dl>
              </div>
            </div>
          </div>

          {/* Notes & Terms footer */}
          <div className="relative z-10 px-8 pb-8">
            {(quote.notes || quote.terms) && (
              <div className="border-t border-gray-100 pt-4 mb-4 grid grid-cols-1 md:grid-cols-2 gap-6">
                {quote.notes && (
                  <div>
                    <p className="text-xs text-gray-400 uppercase tracking-wider mb-1">Notes</p>
                    <p className="text-sm text-gray-600 whitespace-pre-wrap">{quote.notes}</p>
                  </div>
                )}
                {quote.terms && (
                  <div>
                    <p className="text-xs text-gray-400 uppercase tracking-wider mb-1">Terms & Conditions</p>
                    <p className="text-sm text-gray-600 whitespace-pre-wrap">{quote.terms}</p>
                  </div>
                )}
              </div>
            )}

            <div className="border-t border-gray-100 pt-4 text-xs text-gray-400">
              <p>Thank you for considering our quote.</p>
            </div>
          </div>
        </div>
      </div>

      {/* Attachments (below the preview card) */}
      {(quote.attachment_count ?? 0) > 0 && (
        <div className="max-w-3xl mx-auto mt-4">
          <QuoteAttachmentList quoteId={quote.id} isDraft={isDraft} />
        </div>
      )}
    </div>
  )
}
