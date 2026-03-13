import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import apiClient from '../../api/client'
import { Button, Badge, Spinner, Modal } from '../../components/ui'
import { ModuleGate } from '../../components/common/ModuleGate'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type InvoiceStatus = 'draft' | 'issued' | 'partially_paid' | 'paid' | 'overdue' | 'voided'
type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

interface Customer {
  id: string
  first_name: string
  last_name: string
  email: string
  phone: string
  address?: string
}

interface Vehicle {
  rego: string
  make: string
  model: string
  year: number | null
  colour: string
  body_type: string
  fuel_type: string
  engine_size: string
  wof_expiry: string | null
  registration_expiry: string | null
}

interface LineItem {
  id: string
  item_type: string
  type?: string
  description: string
  part_number?: string
  quantity: number
  unit_price: number
  hours?: number
  hourly_rate?: number
  is_gst_exempt?: boolean
  gst_exempt?: boolean
  discount_type: 'percentage' | 'fixed' | null
  discount_value: number | null
  warranty_note?: string
  line_total: number
  gst_amount?: number
}

interface Payment {
  id: string
  date: string
  amount: number
  method: 'cash' | 'stripe'
  recorded_by: string
  note?: string
}

interface CreditNote {
  id: string
  reference_number: string
  amount: number
  reason: string
  created_at: string
}

interface InvoiceDetail {
  id: string
  invoice_number: string | null
  status: InvoiceStatus
  customer_id: string
  customer?: Customer | null
  vehicle?: Vehicle | null
  vehicle_rego?: string | null
  vehicle_make?: string | null
  vehicle_model?: string | null
  vehicle_year?: number | null
  vehicle_odometer?: number | null
  line_items: LineItem[]
  subtotal: number
  subtotal_ex_gst?: number
  gst_amount: number
  total: number
  total_incl_gst?: number
  discount_type: 'percentage' | 'fixed' | null
  discount_value: number | null
  discount_amount: number
  amount_paid: number
  balance_due: number
  notes_internal: string | null
  notes_customer: string | null
  notes?: string
  issue_date: string | null
  due_date: string | null
  created_at: string
  void_reason?: string
  payments?: Payment[]
  credit_notes?: CreditNote[]
  org_name?: string
  org_logo_url?: string
  org_address?: string
  org_phone?: string
  org_email?: string
  org_gst_number?: string
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(amount: number | null | undefined): string {
  if (amount == null || isNaN(Number(amount))) return '$0.00'
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(Number(amount))
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(dateStr))
}

const STATUS_CONFIG: Record<InvoiceStatus, { label: string; variant: BadgeVariant }> = {
  draft: { label: 'Draft', variant: 'neutral' },
  issued: { label: 'Issued', variant: 'info' },
  partially_paid: { label: 'Partially Paid', variant: 'warning' },
  paid: { label: 'Paid', variant: 'success' },
  overdue: { label: 'Overdue', variant: 'error' },
  voided: { label: 'Voided', variant: 'neutral' },
}

function lineItemTypeLabel(type: string): string {
  switch (type) {
    case 'service': return 'Service'
    case 'part': return 'Part'
    case 'labour': return 'Labour'
    default: return type
  }
}

/* ------------------------------------------------------------------ */
/*  Print-optimised CSS                                                */
/* ------------------------------------------------------------------ */

const PRINT_STYLES = `
@media print {
  /* Hide navigation, sidebar, and interactive controls */
  nav, aside, header, footer,
  [data-print-hide],
  .no-print {
    display: none !important;
  }

  /* Reset page layout */
  html, body {
    margin: 0 !important;
    padding: 0 !important;
    background: white !important;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
    overflow: visible !important;
    height: auto !important;
  }

  /* Break out of app shell layout */
  .flex.h-screen, .flex.h-screen.overflow-hidden,
  .flex-1.flex-col.overflow-hidden,
  main.flex-1.overflow-y-auto {
    display: block !important;
    height: auto !important;
    overflow: visible !important;
    margin: 0 !important;
    padding: 0 !important;
    width: 100% !important;
  }

  /* Clean branded layout */
  [data-print-content] {
    max-width: 100% !important;
    margin: 0 !important;
    padding: 20px !important;
    box-shadow: none !important;
    border: none !important;
    overflow: visible !important;
    height: auto !important;
  }

  /* Ensure tables don't break across pages */
  table { page-break-inside: avoid; }
  tr { page-break-inside: avoid; }

  /* Status badge prints with background */
  .badge-print {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }

  /* Page margins */
  @page {
    margin: 10mm;
    size: A4;
  }
}
`

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function InvoiceDetail() {
  const { id } = useParams<{ id: string }>()

  const [invoice, setInvoice] = useState<InvoiceDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* Action states */
  const [duplicating, setDuplicating] = useState(false)
  const [emailing, setEmailing] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [actionMessage, setActionMessage] = useState('')

  /* Void modal */
  const [voidModalOpen, setVoidModalOpen] = useState(false)
  const [voidReason, setVoidReason] = useState('')
  const [voiding, setVoiding] = useState(false)
  const [voidError, setVoidError] = useState('')

  /* ---- Inject print styles ---- */
  useEffect(() => {
    const style = document.createElement('style')
    style.setAttribute('data-invoice-print', 'true')
    style.textContent = PRINT_STYLES
    document.head.appendChild(style)
    return () => { style.remove() }
  }, [])

  /* ---- Fetch invoice ---- */
  const fetchInvoice = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get(`/invoices/${id}`)
      // API wraps response in { invoice: {...} }
      const data = res.data?.invoice || res.data
      setInvoice(data)
    } catch {
      setError('Failed to load invoice. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { fetchInvoice() }, [fetchInvoice])

  /* ---- Actions ---- */
  const handleDuplicate = async () => {
    if (!invoice) return
    setDuplicating(true)
    setActionMessage('')
    try {
      const res = await apiClient.post<{ id: string }>(`/invoices/${invoice.id}/duplicate`)
      window.location.href = `/invoices/${res.data.id}`
    } catch {
      setActionMessage('Failed to duplicate invoice.')
    } finally {
      setDuplicating(false)
    }
  }

  const handleVoid = async () => {
    if (!invoice || !voidReason.trim()) {
      setVoidError('Please provide a reason for voiding.')
      return
    }
    setVoiding(true)
    setVoidError('')
    try {
      await apiClient.post(`/invoices/${invoice.id}/void`, { reason: voidReason.trim() })
      setVoidModalOpen(false)
      setVoidReason('')
      fetchInvoice()
      setActionMessage('Invoice voided successfully.')
    } catch {
      setVoidError('Failed to void invoice. Please try again.')
    } finally {
      setVoiding(false)
    }
  }

  const handleEmail = async () => {
    if (!invoice) return
    setEmailing(true)
    setActionMessage('')
    try {
      await apiClient.post(`/invoices/${invoice.id}/email`)
      setActionMessage('Invoice emailed to customer.')
    } catch {
      setActionMessage('Failed to email invoice.')
    } finally {
      setEmailing(false)
    }
  }

  const handlePrint = () => {
    window.print()
  }

  const handleDownloadPDF = async () => {
    if (!invoice) return
    setDownloading(true)
    setActionMessage('')
    try {
      const res = await apiClient.get(`/invoices/${invoice.id}/pdf`, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${invoice.invoice_number || 'draft'}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      setActionMessage('Failed to download PDF.')
    } finally {
      setDownloading(false)
    }
  }

  /* ---- Loading / Error states ---- */
  if (loading) {
    return (
      <div className="py-16">
        <Spinner label="Loading invoice" />
      </div>
    )
  }

  if (error || !invoice) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-6">
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error || 'Invoice not found.'}
        </div>
        <Button variant="secondary" className="mt-4" onClick={() => { window.location.href = '/invoices' }}>
          ← Back to Invoices
        </Button>
      </div>
    )
  }

  const statusCfg = STATUS_CONFIG[invoice.status] ?? STATUS_CONFIG.draft
  const isVoided = invoice.status === 'voided'
  const isDraft = invoice.status === 'draft'
  const canVoid = !isVoided && !isDraft

  return (
    <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6 lg:px-8" data-print-content>
      {/* ---- Header with status and actions ---- */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6" data-print-hide>
        <div className="flex items-center gap-3">
          <button
            onClick={() => { window.location.href = '/invoices' }}
            className="rounded p-1 text-gray-400 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label="Back to invoices"
          >
            ←
          </button>
          <h1 className="text-2xl font-semibold text-gray-900">
            {invoice.invoice_number || 'Draft Invoice'}
          </h1>
          <Badge variant={statusCfg.variant} data-status-badge className="badge-print">
            {statusCfg.label}
          </Badge>
        </div>

        {/* Action buttons */}
        <div className="flex flex-wrap items-center gap-2">
          {isDraft && (
            <Button size="sm" variant="primary" onClick={() => { window.location.href = `/invoices/${invoice.id}/edit` }}>
              Edit
            </Button>
          )}
          <Button size="sm" variant="secondary" onClick={handleDuplicate} loading={duplicating}>
            Duplicate
          </Button>
          {canVoid && (
            <Button size="sm" variant="danger" onClick={() => setVoidModalOpen(true)}>
              Void
            </Button>
          )}
          <Button size="sm" variant="secondary" onClick={handleEmail} loading={emailing}>
            Email
          </Button>
          <Button size="sm" variant="secondary" onClick={handlePrint}>
            Print
          </Button>
          <Button size="sm" variant="primary" onClick={handleDownloadPDF} loading={downloading}>
            Download PDF
          </Button>
        </div>
      </div>

      {/* Action feedback */}
      {actionMessage && (
        <div className="mb-4 rounded-md border border-gray-200 bg-gray-50 px-4 py-2 text-sm text-gray-700 no-print" role="status">
          {actionMessage}
        </div>
      )}

      {/* Voided banner */}
      {isVoided && (
        <div className="mb-6 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="status">
          This invoice has been voided.{invoice.void_reason && <> Reason: {invoice.void_reason}</>}
        </div>
      )}

      {/* ---- Print header (visible only in print) ---- */}
      <div className="hidden print:block mb-8">
        <div className="flex items-start justify-between">
          <div>
            {invoice.org_logo_url && (
              <img src={invoice.org_logo_url} alt={invoice.org_name} className="h-12 mb-2" />
            )}
            <h2 className="text-xl font-bold">{invoice.org_name}</h2>
            {invoice.org_address && <p className="text-sm">{invoice.org_address}</p>}
            {invoice.org_phone && <p className="text-sm">{invoice.org_phone}</p>}
            {invoice.org_email && <p className="text-sm">{invoice.org_email}</p>}
            {invoice.org_gst_number && <p className="text-sm">GST: {invoice.org_gst_number}</p>}
          </div>
          <div className="text-right">
            <h1 className="text-2xl font-bold">TAX INVOICE</h1>
            <p className="text-lg font-semibold">{invoice.invoice_number || 'DRAFT'}</p>
            <p className="text-sm mt-1">Date: {formatDate(invoice.issue_date)}</p>
            <p className="text-sm">Due: {formatDate(invoice.due_date)}</p>
            <Badge variant={statusCfg.variant} data-status-badge className="badge-print mt-1">
              {statusCfg.label}
            </Badge>
          </div>
        </div>
      </div>

      {/* ---- Invoice meta (screen) ---- */}
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 mb-6 print:hidden">
        <div>
          <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-1">Invoice Details</h2>
          <dl className="space-y-1 text-sm">
            <div className="flex gap-2">
              <dt className="text-gray-500 w-24">Number:</dt>
              <dd className="text-gray-900 font-medium">{invoice.invoice_number || 'Not assigned'}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-gray-500 w-24">Issued:</dt>
              <dd className="text-gray-900">{formatDate(invoice.issue_date)}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-gray-500 w-24">Due:</dt>
              <dd className="text-gray-900">{formatDate(invoice.due_date)}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-gray-500 w-24">Created:</dt>
              <dd className="text-gray-900">{formatDate(invoice.created_at)}</dd>
            </div>
          </dl>
        </div>
      </div>

      {/* ---- Customer & Vehicle ---- */}
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 mb-6">
        {/* Customer */}
        <section className="rounded-lg border border-gray-200 p-4">
          <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-2">Customer</h2>
          {invoice.customer ? (
            <>
              <p className="font-medium text-gray-900">
                {invoice.customer.first_name} {invoice.customer.last_name}
              </p>
              {invoice.customer.email && <p className="text-sm text-gray-600">{invoice.customer.email}</p>}
              {invoice.customer.phone && <p className="text-sm text-gray-600">{invoice.customer.phone}</p>}
              {invoice.customer.address && <p className="text-sm text-gray-600 mt-1">{invoice.customer.address}</p>}
            </>
          ) : (
            <p className="text-sm text-gray-500">No customer information</p>
          )}
        </section>

        {/* Vehicle */}
        <ModuleGate module="vehicles">
        <section className="rounded-lg border border-gray-200 p-4">
          <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-2">Vehicle</h2>
          {invoice.vehicle ? (
            <dl className="space-y-1.5">
              <div>
                <dt className="text-xs text-gray-500">Registration</dt>
                <dd className="font-semibold text-gray-900 font-mono text-lg">{invoice.vehicle.rego}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">Vehicle Details</dt>
                <dd className="text-sm text-gray-900">
                  {[invoice.vehicle.year, invoice.vehicle.make, invoice.vehicle.model].filter(Boolean).join(' ') || '—'}
                </dd>
              </div>
              {invoice.vehicle_odometer != null && invoice.vehicle_odometer > 0 && (
                <div>
                  <dt className="text-xs text-gray-500">Odometer</dt>
                  <dd className="text-sm text-gray-900">{invoice.vehicle_odometer.toLocaleString()} Kms</dd>
                </div>
              )}
              {invoice.vehicle.colour && (
                <div>
                  <dt className="text-xs text-gray-500">Colour</dt>
                  <dd className="text-sm text-gray-600">{invoice.vehicle.colour}</dd>
                </div>
              )}
            </dl>
          ) : invoice.vehicle_rego ? (
            <dl className="space-y-1.5">
              <div>
                <dt className="text-xs text-gray-500">Registration</dt>
                <dd className="font-semibold text-gray-900 font-mono text-lg">{invoice.vehicle_rego}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">Vehicle Details</dt>
                <dd className="text-sm text-gray-900">
                  {[invoice.vehicle_year, invoice.vehicle_make, invoice.vehicle_model].filter(Boolean).join(' ') || '—'}
                </dd>
              </div>
              {invoice.vehicle_odometer != null && invoice.vehicle_odometer > 0 && (
                <div>
                  <dt className="text-xs text-gray-500">Odometer</dt>
                  <dd className="text-sm text-gray-900">{invoice.vehicle_odometer.toLocaleString()} Kms</dd>
                </div>
              )}
            </dl>
          ) : (
            <p className="text-sm text-gray-500">No vehicle linked</p>
          )}
        </section>
        </ModuleGate>
      </div>

      {/* ---- Line Items ---- */}
      <section className="mb-6">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-3">Line Items</h2>
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <caption className="sr-only">Invoice line items</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Description</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Qty/Hrs</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Rate</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">GST</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {(invoice.line_items || []).map((item) => (
                <tr key={item.id}>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">{lineItemTypeLabel(item.item_type || item.type || 'service')}</td>
                  <td className="px-4 py-3 text-sm text-gray-900">
                    <div>{item.description?.split('\n')[0]}</div>
                    {item.description?.includes('\n') && (
                      <div className="text-xs text-gray-500 mt-0.5 whitespace-pre-line">{item.description.split('\n').slice(1).join('\n')}</div>
                    )}
                    {item.part_number && <div className="text-xs text-gray-500">Part #: {item.part_number}</div>}
                    {item.warranty_note && (
                      <div className="text-xs text-blue-600 mt-0.5">Warranty: {item.warranty_note}</div>
                    )}
                    {(item.discount_value ?? 0) > 0 && (
                      <div className="text-xs text-green-600 mt-0.5">
                        Discount: {item.discount_type === 'percentage' ? `${item.discount_value}%` : formatNZD(item.discount_value)}
                      </div>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums">
                    {(item.item_type || item.type) === 'labour' ? (item.hours ?? 0) : item.quantity}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums">
                    {(item.item_type || item.type) === 'labour' ? formatNZD(item.hourly_rate ?? 0) : formatNZD(item.unit_price)}
                    {(item.item_type || item.type) === 'labour' && <span className="text-gray-500">/hr</span>}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums">
                    {(item.is_gst_exempt ?? item.gst_exempt) ? (
                      <span className="text-gray-400">Exempt</span>
                    ) : (
                      <span className="text-gray-700">{item.gst_amount != null ? formatNZD(item.gst_amount) : '—'}</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900 text-right tabular-nums">
                    {formatNZD(item.line_total)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Totals */}
        <div className="mt-4 flex justify-end">
          <dl className="w-64 space-y-1 text-sm">
            <div className="flex justify-between">
              <dt className="text-gray-500">Subtotal (ex-GST)</dt>
              <dd className="text-gray-900 tabular-nums">{formatNZD(invoice.subtotal_ex_gst ?? invoice.subtotal)}</dd>
            </div>
            {(invoice.discount_value ?? 0) > 0 && (
              <div className="flex justify-between text-green-700">
                <dt>Discount</dt>
                <dd className="tabular-nums">
                  {invoice.discount_type === 'percentage'
                    ? `−${invoice.discount_value}%`
                    : `−${formatNZD(invoice.discount_value)}`}
                </dd>
              </div>
            )}
            <div className="flex justify-between">
              <dt className="text-gray-500">GST (15%)</dt>
              <dd className="text-gray-900 tabular-nums">{formatNZD(invoice.gst_amount)}</dd>
            </div>
            <div className="flex justify-between border-t border-gray-200 pt-1 font-semibold">
              <dt className="text-gray-900">Total (incl. GST)</dt>
              <dd className="text-gray-900 tabular-nums">{formatNZD(invoice.total_incl_gst ?? invoice.total)}</dd>
            </div>
            <div className="flex justify-between border-t border-gray-200 pt-1 font-semibold text-lg">
              <dt className="text-gray-900">Balance Due</dt>
              <dd className={`tabular-nums ${(invoice.balance_due ?? 0) > 0 ? 'text-red-600' : 'text-green-600'}`}>
                {formatNZD(invoice.balance_due)}
              </dd>
            </div>
          </dl>
        </div>
      </section>

      {/* ---- Notes ---- */}
      {(invoice.notes || invoice.notes_customer || invoice.notes_internal) && (
        <section className="mb-6">
          <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-2">Notes</h2>
          {(invoice.notes_customer || invoice.notes) && (
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-700 whitespace-pre-wrap mb-2">
              {invoice.notes_customer || invoice.notes}
            </div>
          )}
          {invoice.notes_internal && (
            <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4 text-sm text-gray-700 whitespace-pre-wrap">
              <span className="text-xs font-medium text-yellow-700 uppercase">Internal Note</span>
              <div className="mt-1">{invoice.notes_internal}</div>
            </div>
          )}
        </section>
      )}

      {/* ---- Payment History ---- */}
      <section className="mb-6">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-3">Payment History</h2>
        {(invoice.payments || []).length === 0 ? (
          <p className="text-sm text-gray-500">No payments recorded.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200">
              <caption className="sr-only">Payment history</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Amount</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Method</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Recorded By</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {(invoice.payments || []).map((payment) => (
                  <tr key={payment.id}>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">{formatDate(payment.date)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums font-medium">
                      {formatNZD(payment.amount)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700 capitalize">{payment.method}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{payment.recorded_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ---- Credit Notes ---- */}
      <section className="mb-6">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-3">Credit Notes</h2>
        {(invoice.credit_notes || []).length === 0 ? (
          <p className="text-sm text-gray-500">No credit notes.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200">
              <caption className="sr-only">Credit notes</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Reference</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Amount</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Reason</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {(invoice.credit_notes || []).map((cn) => (
                  <tr key={cn.id}>
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-blue-600">{cn.reference_number}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-red-600 text-right tabular-nums font-medium">
                      −{formatNZD(cn.amount)}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700">{cn.reason}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{formatDate(cn.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ---- Void Modal ---- */}
      <Modal open={voidModalOpen} onClose={() => { setVoidModalOpen(false); setVoidError('') }} title="Void Invoice">
        <p className="text-sm text-gray-600 mb-4">
          Voiding this invoice will retain its number in sequence but exclude it from revenue reporting.
          This action cannot be undone.
        </p>
        <label className="block text-sm font-medium text-gray-700 mb-1" htmlFor="void-reason">
          Reason for voiding
        </label>
        <textarea
          id="void-reason"
          value={voidReason}
          onChange={(e) => setVoidReason(e.target.value)}
          rows={3}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm
            placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          placeholder="e.g. Duplicate invoice, customer dispute…"
        />
        {voidError && (
          <p className="mt-2 text-sm text-red-600" role="alert">{voidError}</p>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => { setVoidModalOpen(false); setVoidError('') }}>
            Cancel
          </Button>
          <Button variant="danger" size="sm" onClick={handleVoid} loading={voiding}>
            Void Invoice
          </Button>
        </div>
      </Modal>
    </div>
  )
}
