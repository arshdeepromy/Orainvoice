import { useState, useEffect, useRef, useCallback, useMemo, Fragment } from 'react'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import apiClient from '../../api/client'
import { Button, Spinner, Modal, Badge } from '../../components/ui'
import { useTenant } from '@/contexts/TenantContext'
import { useBranch } from '@/contexts/BranchContext'
import { CreditNoteModal } from '../../components/invoices/CreditNoteModal'
import { RefundModal } from '../../components/invoices/RefundModal'
import InvoiceCreate from './InvoiceCreate'
import {
  computeCreditableAmount,
  computePaymentSummary,
  isCreditNoteButtonVisible,
  isRefundButtonVisible,
  getPaymentBadgeType,
  shouldShowRefundNote,
  formatNZD as formatNZDUtil,
} from '../../components/invoices/refund-credit-note.utils'
import POSReceiptPreview from '../../components/pos/POSReceiptPreview'
import { invoiceToReceiptData } from '../../utils/invoiceReceiptMapper'
import { resolveTemplateStyles } from '@/utils/invoiceTemplateStyles'
import AttachmentList from '@/components/invoices/AttachmentList'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type InvoiceStatus = 'draft' | 'issued' | 'partially_paid' | 'paid' | 'overdue' | 'voided' | 'refunded' | 'partially_refunded'
type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

interface InvoiceSummary {
  id: string
  invoice_number: string | null
  customer_name: string
  customer_id?: string
  rego?: string
  vehicle_rego?: string
  total: number | string
  balance_due?: number
  status: InvoiceStatus
  issue_date: string | null
  due_date?: string | null
  created_at?: string
  branch_id?: string | null
  has_stripe_payment?: boolean
  attachment_count?: number
}

interface InvoiceListResponse {
  items: InvoiceSummary[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

interface Customer {
  id: string
  first_name: string
  last_name: string
  email: string
  phone: string
  address?: string
  display_name?: string
  company_name?: string
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
  odometer: number | null
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

interface PaymentRecord {
  id: string
  date: string
  amount: number
  method: 'cash' | 'stripe' | 'eftpos' | 'bank_transfer' | 'card' | 'cheque'
  recorded_by: string
  note?: string
  is_refund?: boolean
  refund_note?: string
}

interface CreditNote {
  id: string
  reference_number: string
  amount: number
  reason: string
  created_at: string
}

interface InvoiceDetailData {
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
  additional_vehicles?: { rego: string; make?: string; model?: string; year?: number; wof_expiry?: string; odometer?: number }[]
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
  payments?: PaymentRecord[]
  credit_notes?: CreditNote[]
  org_name?: string
  org_logo_url?: string
  org_address?: string
  org_address_unit?: string
  org_address_street?: string
  org_address_city?: string
  org_address_state?: string
  org_address_country?: string
  org_address_postcode?: string
  org_phone?: string
  org_email?: string
  org_website?: string
  invoice_template_id?: string | null
  invoice_template_colours?: { primary_colour?: string; accent_colour?: string; header_bg_colour?: string } | null
  org_gst_number?: string
  payment_terms?: string
  salesperson_name?: string
  attachment_count?: number
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(amount: number | string | null | undefined): string {
  if (amount == null || isNaN(Number(amount))) return 'NZD0.00'
  return `NZD${Number(amount).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(dateStr))
}

function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: true,
  }).format(new Date(dateStr))
}

const PAYMENT_TERMS_LABELS: Record<string, string> = {
  due_on_receipt: 'Due on Receipt', net_7: 'Net 7', net_15: 'Net 15',
  net_30: 'Net 30', net_45: 'Net 45', net_60: 'Net 60', net_90: 'Net 90',
}

function formatPaymentTerms(terms: string | null | undefined): string {
  if (!terms) return 'Due on Receipt'
  return PAYMENT_TERMS_LABELS[terms] || terms.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function formatDateShort(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(dateStr))
}

const STATUS_CONFIG: Record<InvoiceStatus, { label: string; variant: BadgeVariant; color: string }> = {
  draft: { label: 'DRAFT', variant: 'neutral', color: 'text-gray-500' },
  issued: { label: 'ISSUED', variant: 'info', color: 'text-blue-600' },
  partially_paid: { label: 'PARTIALLY PAID', variant: 'warning', color: 'text-amber-600' },
  paid: { label: 'PAID', variant: 'success', color: 'text-emerald-600' },
  overdue: { label: 'OVERDUE', variant: 'error', color: 'text-red-600' },
  voided: { label: 'VOIDED', variant: 'neutral', color: 'text-gray-400' },
  refunded: { label: 'REFUNDED', variant: 'warning', color: 'text-orange-600' },
  partially_refunded: { label: 'PARTIALLY REFUNDED', variant: 'warning', color: 'text-orange-600' },
}

const STATUS_OPTIONS = [
  { value: '', label: 'All Invoices' },
  { value: 'draft', label: 'Draft' },
  { value: 'issued', label: 'Issued' },
  { value: 'partially_paid', label: 'Partially Paid' },
  { value: 'paid', label: 'Paid' },
  { value: 'overdue', label: 'Overdue' },
  { value: 'voided', label: 'Voided' },
  { value: 'refunded', label: 'Refunded' },
  { value: 'partially_refunded', label: 'Partially Refunded' },
]

const PAGE_SIZE = 25

function getDueDateLabel(inv: InvoiceSummary): { text: string; className: string } | null {
  if (inv.status === 'paid' || inv.status === 'voided' || inv.status === 'draft' || inv.status === 'refunded' || inv.status === 'partially_refunded') return null
  if (!inv.due_date) return null
  const now = new Date()
  const due = new Date(inv.due_date)
  const diffDays = Math.ceil((due.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))
  if (diffDays < 0) return { text: `${Math.abs(diffDays)} day${Math.abs(diffDays) !== 1 ? 's' : ''} overdue`, className: 'text-red-500 text-[10px] font-semibold' }
  if (diffDays <= 7) return { text: `Due in ${diffDays} day${diffDays !== 1 ? 's' : ''}`, className: 'text-amber-500 text-[10px] font-semibold' }
  return null
}

/* ------------------------------------------------------------------ */
/*  Print styles                                                       */
/* ------------------------------------------------------------------ */

const PRINT_STYLES = `
@media print {
  /* Hide everything except the invoice preview */
  nav, aside, header, footer, [data-print-hide], .no-print { display: none !important; }

  /* Reset page */
  html, body {
    margin: 0 !important;
    padding: 0 !important;
    background: white !important;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
    overflow: visible !important;
    height: auto !important;
    width: auto !important;
  }

  /* Break out of the app shell layout constraints */
  .flex.h-screen, .flex.h-screen.overflow-hidden,
  .flex-1.flex-col.overflow-hidden,
  main.flex-1.overflow-y-auto,
  .flex.h-full.overflow-hidden {
    display: block !important;
    height: auto !important;
    overflow: visible !important;
    margin: 0 !important;
    padding: 0 !important;
    background: white !important;
    min-height: 0 !important;
    width: 100% !important;
    max-width: 100% !important;
  }

  /* The right panel (data-print-content) — full width, no overflow */
  [data-print-content] {
    display: block !important;
    width: 100% !important;
    max-width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: visible !important;
    height: auto !important;
  }

  /* The scrollable invoice area inside the panel */
  [data-print-content] .overflow-y-auto {
    overflow: visible !important;
    height: auto !important;
    padding: 10px 0 !important;
  }

  /* The invoice card — keep styling, remove shadow, fill width nicely */
  [data-print-content] .max-w-3xl {
    max-width: 100% !important;
    margin: 0 auto !important;
    box-shadow: none !important;
    border: none !important;
    border-radius: 0 !important;
  }

  /* Balance Due bar: grey background + dark text for print */
  .print-balance-bar,
  .print-balance-bar dt,
  .print-balance-bar dd {
    background: #e5e7eb !important;
    color: #1a1a1a !important;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }

  /* Table header: grey background + dark text for print */
  .print-table-header,
  .print-table-header th {
    background: #e5e7eb !important;
    color: #1a1a1a !important;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }

  /* Preserve other background colours */
  [class*="bg-yellow-"],
  [class*="bg-gray-50"] {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }

  /* Tables don't break across pages */
  table { page-break-inside: avoid; }
  tr { page-break-inside: avoid; }

  /* Hide payment history and credit notes cards below the invoice for cleaner print */
  [data-print-content] .overflow-y-auto > .max-w-3xl.mt-4 {
    display: none !important;
  }

  /* Page setup */
  @page {
    margin: 10mm;
    size: A4;
  }

  /* Hide POS receipt column in normal invoice print */
  [data-preview="receipt"] {
    display: none !important;
  }

  /* Remove selection ring in print */
  [data-preview] {
    box-shadow: none !important;
    outline: none !important;
  }
}
`

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function InvoiceList() {
  const navigate = useNavigate()
  const location = useLocation()
  const { id: routeId } = useParams<{ id: string }>()
  const isCreating = location.pathname === '/invoices/new'
  const { tradeFamily } = useTenant()
  const { branches: branchList, selectedBranchId } = useBranch()
  // Null tradeFamily treated as automotive for backward compat
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'

  /* --- List state --- */
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<InvoiceListResponse | null>(null)
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState('')

  /* --- Detail state --- */
  const [selectedId, setSelectedId] = useState<string | null>(routeId || null)
  const [invoice, setInvoice] = useState<InvoiceDetailData | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')

  // Sync selectedId when route param changes (e.g. navigating from /invoices/new to /invoices/:id)
  useEffect(() => {
    if (routeId && routeId !== selectedId) {
      setSelectedId(routeId)
    }
  }, [routeId])

  /* --- Action states --- */
  const [actionLoading, setActionLoading] = useState('')
  const [actionMessage, setActionMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null)

  /* --- Modals --- */
  const [voidModalOpen, setVoidModalOpen] = useState(false)
  const [voidReason, setVoidReason] = useState('')
  const [paymentModalOpen, setPaymentModalOpen] = useState(false)
  const [paymentAmount, setPaymentAmount] = useState('')
  const [paymentMethod, setPaymentMethod] = useState('cash')
  const [paymentNote, setPaymentNote] = useState('')
  const [sendMenuOpen, setSendMenuOpen] = useState(false)
  const [pdfMenuOpen, setPdfMenuOpen] = useState(false)
  const [moreMenuOpen, setMoreMenuOpen] = useState(false)
  const [reminderMenuOpen, setReminderMenuOpen] = useState(false)
  const [selectedPreview, setSelectedPreview] = useState<'invoice' | 'receipt'>('invoice')
  const [shareModalOpen, setShareModalOpen] = useState(false)
  const [shareUrl, setShareUrl] = useState('')
  const [shareCopied, setShareCopied] = useState(false)

  /* Credit Note & Refund modals */
  const [creditNoteModalOpen, setCreditNoteModalOpen] = useState(false)
  const [refundModalOpen, setRefundModalOpen] = useState(false)
  const [deleteModalOpen, setDeleteModalOpen] = useState(false)
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null)
  const [deleteTargetNumber, setDeleteTargetNumber] = useState('')

  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const abortRef = useRef<AbortController>(undefined)
  const sendMenuRef = useRef<HTMLDivElement>(null)
  const pdfMenuRef = useRef<HTMLDivElement>(null)
  const moreMenuRef = useRef<HTMLDivElement>(null)
  const reminderMenuRef = useRef<HTMLDivElement>(null)

  /* --- Inject print styles --- */
  useEffect(() => {
    const style = document.createElement('style')
    style.setAttribute('data-invoice-print', 'true')
    style.textContent = PRINT_STYLES
    document.head.appendChild(style)
    return () => { style.remove() }
  }, [])

  /* --- Close menus on outside click --- */
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (sendMenuRef.current && !sendMenuRef.current.contains(e.target as Node)) setSendMenuOpen(false)
      if (pdfMenuRef.current && !pdfMenuRef.current.contains(e.target as Node)) setPdfMenuOpen(false)
      if (moreMenuRef.current && !moreMenuRef.current.contains(e.target as Node)) setMoreMenuOpen(false)
      if (reminderMenuRef.current && !reminderMenuRef.current.contains(e.target as Node)) setReminderMenuOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  /* --- Fetch invoice list --- */
  const fetchInvoices = useCallback(async (search: string, status: string, pg: number) => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setListLoading(true)
    setListError('')
    try {
      const params: Record<string, string | number> = { page: pg, page_size: PAGE_SIZE }
      if (search.trim()) params.search = search.trim()
      if (status) params.status = status
      const res = await apiClient.get<InvoiceListResponse>('/invoices', { params, signal: controller.signal })
      const invoices = res.data?.items ?? (res.data as any)?.invoices ?? []
      setData({
        items: invoices,
        total: res.data?.total ?? 0,
        page: res.data?.page ?? pg,
        page_size: res.data?.page_size ?? PAGE_SIZE,
        total_pages: res.data?.total_pages ?? Math.ceil((res.data?.total ?? 0) / PAGE_SIZE),
      })
      // Auto-select first invoice if none selected
      if (!selectedId && invoices.length > 0) {
        setSelectedId(invoices[0].id)
      }
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setListError('Failed to load invoices.')
      setData({ items: [], total: 0, page: pg, page_size: PAGE_SIZE, total_pages: 0 })
    } finally {
      setListLoading(false)
    }
  }, [selectedId, selectedBranchId])

  /* --- Fetch invoice detail --- */
  const fetchDetail = useCallback(async (invoiceId: string, showSpinner = true) => {
    if (showSpinner) setDetailLoading(true)
    setDetailError('')
    try {
      const res = await apiClient.get(`/invoices/${invoiceId}`)
      const d = (res.data as any)?.invoice || res.data
      setInvoice(d)
    } catch {
      if (showSpinner) setDetailError('Failed to load invoice details.')
      if (showSpinner) setInvoice(null)
    } finally {
      if (showSpinner) setDetailLoading(false)
    }
  }, [])

  /* --- Debounced search --- */
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setPage(1)
      fetchInvoices(searchQuery, statusFilter, 1)
    }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [searchQuery, statusFilter, fetchInvoices])

  useEffect(() => {
    fetchInvoices(searchQuery, statusFilter, page)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, selectedBranchId, location.key])

  /* --- Load detail when selection changes --- */
  useEffect(() => {
    if (!selectedId) return
    // Use router state for instant display when navigating from create/edit
    const passedInvoice = (location.state as { invoice?: Record<string, unknown> } | null)?.invoice
    if (passedInvoice && String((passedInvoice as any)?.id) === selectedId) {
      setInvoice(passedInvoice as any)
      setDetailLoading(false)
      // Clear state so back/forward doesn't reuse stale data
      window.history.replaceState({}, '')
      // Silent background refresh for server-side updates
      fetchDetail(selectedId, false)
    } else {
      fetchDetail(selectedId)
    }
  }, [selectedId, fetchDetail, location.state])

  /* --- Clear action message after 4s --- */
  useEffect(() => {
    if (!actionMessage) return
    const t = setTimeout(() => setActionMessage(null), 4000)
    return () => clearTimeout(t)
  }, [actionMessage])

  /* ---------------------------------------------------------------- */
  /*  Resolved template styles                                         */
  /* ---------------------------------------------------------------- */

  const templateStyles = useMemo(
    () => resolveTemplateStyles(
      invoice?.invoice_template_id,
      invoice?.invoice_template_colours,
    ),
    [invoice?.invoice_template_id, invoice?.invoice_template_colours],
  )
  // templateStyles is consumed by tasks 4.2–4.5 (colour/layout application)

  /* ---------------------------------------------------------------- */
  /*  Actions                                                          */
  /* ---------------------------------------------------------------- */

  const showMsg = (text: string, type: 'success' | 'error' = 'success') => setActionMessage({ text, type })

  const handleSendInvoice = async () => {
    if (!invoice) return
    setActionLoading('send')
    try {
      await apiClient.post(`/invoices/${invoice.id}/email`)
      showMsg('Invoice sent to customer.')
      fetchDetail(invoice.id)
      fetchInvoices(searchQuery, statusFilter, page)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showMsg(detail || 'Failed to send invoice.', 'error')
    }
    finally { setActionLoading(''); setSendMenuOpen(false) }
  }

  const handleMarkAsSent = async () => {
    if (!invoice || invoice.status !== 'draft') return
    setActionLoading('markSent')
    try {
      await apiClient.put(`/invoices/${invoice.id}/issue`)
      showMsg('Invoice marked as sent.')
      fetchDetail(invoice.id)
      fetchInvoices(searchQuery, statusFilter, page)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showMsg(detail || 'Failed to mark as sent.', 'error')
    }
    finally { setActionLoading(''); setSendMenuOpen(false) }
  }

  const handleVoid = async () => {
    if (!invoice || !voidReason.trim()) return
    setActionLoading('void')
    try {
      await apiClient.put(`/invoices/${invoice.id}/void`, { reason: voidReason.trim() })
      showMsg('Invoice voided.')
      setVoidModalOpen(false)
      setVoidReason('')
      fetchDetail(invoice.id)
      fetchInvoices(searchQuery, statusFilter, page)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showMsg(detail || 'Failed to void invoice.', 'error')
    }
    finally { setActionLoading('') }
  }

  const handleDuplicate = async () => {
    if (!invoice) return
    setActionLoading('duplicate')
    try {
      const res = await apiClient.post<{ id: string }>(`/invoices/${invoice.id}/duplicate`)
      const newId = (res.data as any)?.id || (res.data as any)?.invoice?.id
      showMsg('Invoice duplicated.')
      fetchInvoices(searchQuery, statusFilter, page)
      if (newId) setSelectedId(newId)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showMsg(detail || 'Failed to duplicate.', 'error')
    }
    finally { setActionLoading(''); setMoreMenuOpen(false) }
  }

  const handleDownloadPDF = async () => {
    if (!invoice) return
    setActionLoading('pdf')
    try {
      const res = await apiClient.get(`/invoices/${invoice.id}/pdf`, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${invoice.invoice_number || 'draft'}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showMsg(detail || 'Failed to download PDF.', 'error')
    }
    finally { setActionLoading(''); setPdfMenuOpen(false) }
  }

  const handlePrint = () => {
    setPdfMenuOpen(false)
    window.print()
  }

  const handlePrintReceipt = () => {
    setPdfMenuOpen(false)
    if (!invoice) return
    const d = invoiceToReceiptData(invoice)
    const fmt = (n: number | string | null | undefined) => '$' + Number(n ?? 0).toFixed(2)

    let html = `<!DOCTYPE html><html><head><title>POS Receipt</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: white; font-family: 'Courier New', monospace; font-size: 12px; line-height: 1.6; color: #111; width: 72mm; margin: 0 auto; padding: 4mm 0; }
  .center { text-align: center; }
  .bold { font-weight: bold; }
  .text-sm { font-size: 14px; }
  .row { display: flex; justify-content: space-between; }
  .sep { border-top: 1px dashed #9ca3af; margin: 4px 0; }
  .sep-double { border-top: 2px double #9ca3af; margin: 4px 0; }
  .mt { margin-top: 12px; }
  @page { margin: 3mm; size: 80mm auto; }
</style></head><body>`

    html += `<div class="center"><div class="text-sm bold">${d.orgName}</div>`
    if (d.orgAddress) html += `<div>${d.orgAddress}</div>`
    if (d.orgPhone) html += `<div>${d.orgPhone}</div>`
    if (d.gstNumber) html += `<div>GST: ${d.gstNumber}</div>`
    html += `</div><div class="sep"></div>`
    if (d.receiptNumber) html += `<div class="row"><span>Receipt #:</span><span>${d.receiptNumber}</span></div>`
    html += `<div class="row"><span>Date:</span><span>${d.date}</span></div>`
    if (d.customerName) html += `<div class="row"><span>Customer:</span><span>${d.customerName}</span></div>`
    html += `<div class="sep"></div>`
    for (const item of d.items ?? []) {
      html += `<div>${item.name}</div><div class="row"><span>&nbsp;&nbsp;${item.quantity} x ${fmt(item.unitPrice)}</span><span>${fmt(item.total)}</span></div>`
    }
    html += `<div class="sep"></div>`
    html += `<div class="row"><span>Subtotal:</span><span>${fmt(d.subtotal)}</span></div>`
    if (d.discountAmount && d.discountAmount > 0) html += `<div class="row"><span>Discount:</span><span>-${fmt(d.discountAmount)}</span></div>`
    html += `<div class="row"><span>${d.taxLabel ?? 'Tax:'}</span><span>${fmt(d.taxAmount)}</span></div>`
    html += `<div class="sep-double"></div><div class="row bold"><span>TOTAL:</span><span>${fmt(d.total)}</span></div><div class="sep-double"></div>`
    html += `<div class="row"><span>Payment:</span><span>${(d.paymentMethod ?? '').toUpperCase()}</span></div>`
    if (d.amountPaid != null) html += `<div class="row"><span>Amount Paid:</span><span>${fmt(d.amountPaid)}</span></div>`
    if (d.totalRefunded && d.totalRefunded > 0) html += `<div class="row"><span>Refunded:</span><span>${fmt(d.totalRefunded)}</span></div>`
    if (d.balanceDue && d.balanceDue > 0) html += `<div class="row bold"><span>BALANCE DUE:</span><span>${fmt(d.balanceDue)}</span></div>`
    html += `<div class="center mt">${d.footer ?? 'Thank you for your business!'}</div>`
    html += `</body></html>`

    // Use a hidden iframe — no popup window
    const iframe = document.createElement('iframe')
    iframe.style.cssText = 'position:fixed;top:-9999px;left:-9999px;width:0;height:0;border:none;'
    document.body.appendChild(iframe)
    const doc = iframe.contentDocument || iframe.contentWindow?.document
    if (!doc) { document.body.removeChild(iframe); return }
    doc.open()
    doc.write(html)
    doc.close()
    setTimeout(() => {
      iframe.contentWindow?.print()
      setTimeout(() => document.body.removeChild(iframe), 1000)
    }, 200)
  }

  const handleSendReminder = async (channel: 'email' | 'sms') => {
    if (!invoice) return
    setReminderMenuOpen(false)
    setActionLoading('reminder')
    try {
      await apiClient.post(`/invoices/${invoice.id}/send-reminder`, { channel })
      showMsg(`Payment reminder sent via ${channel === 'email' ? 'email' : 'SMS'}.`, 'success')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showMsg(msg || `Failed to send ${channel} reminder.`, 'error')
    } finally {
      setActionLoading('')
    }
  }

  const handleRecordPayment = async () => {
    if (!invoice || !paymentAmount) return
    setActionLoading('payment')
    try {
      await apiClient.post('/payments/cash', {
        invoice_id: invoice.id,
        amount: parseFloat(paymentAmount),
        method: paymentMethod,
        note: paymentNote || undefined,
      })
      showMsg('Payment recorded.')
      setPaymentModalOpen(false)
      setPaymentAmount('')
      setPaymentNote('')
      fetchDetail(invoice.id)
      fetchInvoices(searchQuery, statusFilter, page)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showMsg(detail || 'Failed to record payment.', 'error')
    }
    finally { setActionLoading('') }
  }

  const handleShareLink = async () => {
    if (!invoice) return
    setActionLoading('share')
    try {
      const res = await apiClient.post(`/invoices/${invoice.id}/share`)
      const token = (res.data as any)?.share_token
      if (!token) throw new Error('No share token returned')
      const url = `${window.location.origin}/api/v1/public/invoice/${token}`
      setShareUrl(url)
      setShareCopied(false)
      setShareModalOpen(true)
    } catch (err) {
      console.error('Share link error:', err)
      showMsg('Failed to generate share link.', 'error')
    } finally {
      setActionLoading('')
      setMoreMenuOpen(false)
    }
  }

  const handleCopyShareUrl = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = shareUrl
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setShareCopied(true)
    setTimeout(() => setShareCopied(false), 2000)
  }

  const handleDeleteInvoice = async () => {
    if (!deleteTargetId) return
    setActionLoading('delete')
    try {
      await apiClient.post('/invoices/bulk-delete', { invoice_ids: [deleteTargetId], confirm: true })
      showMsg('Invoice deleted.')
      setDeleteModalOpen(false)
      setDeleteTargetId(null)
      // If we deleted the selected invoice, clear selection
      if (selectedId === deleteTargetId) {
        setSelectedId(null)
        setInvoice(null)
      }
      fetchInvoices(searchQuery, statusFilter, page)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showMsg(detail || 'Failed to delete invoice.', 'error')
    }
    finally { setActionLoading('') }
  }

  /* ---------------------------------------------------------------- */
  /*  Render                                                           */
  /* ---------------------------------------------------------------- */

  const isDraft = invoice?.status === 'draft'
  const isVoided = invoice?.status === 'voided'
  const canVoid = invoice && !isVoided && !isDraft
  const canRecordPayment = invoice && !isVoided && invoice.status !== 'draft' && invoice.status !== 'refunded' && invoice.status !== 'partially_refunded' && (invoice.balance_due ?? 0) > 0

  /* Computed values for credit notes and refunds */
  const creditableAmount = invoice ? computeCreditableAmount(
    invoice.total,
    (invoice.credit_notes || []).map(cn => cn.amount)
  ) : 0
  const paymentSummary = invoice ? computePaymentSummary(invoice.payments || []) : { totalPaid: 0, totalRefunded: 0, netPaid: 0 }
  const refundableAmount = paymentSummary.netPaid

  return (
    <div className="flex h-full overflow-hidden bg-gray-50 -m-4 lg:-m-6">
      {/* ============================================================ */}
      {/*  LEFT SIDEBAR — Invoice List                                  */}
      {/* ============================================================ */}
      <div className="w-80 min-w-[320px] flex flex-col border-r border-gray-200 bg-white" data-print-hide>
        {/* Sidebar header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="text-sm font-semibold text-gray-800 bg-transparent border-none focus:ring-0 cursor-pointer pr-6 -ml-1"
              aria-label="Filter by status"
            >
              {STATUS_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => navigate('/invoices/new')}
              className="flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 transition-colors"
              aria-label="Create new invoice"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              New
            </button>
            <button
              className="p-1.5 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              onClick={() => fetchInvoices(searchQuery, statusFilter, page)}
              aria-label="Refresh list"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
              </svg>
            </button>
          </div>
        </div>

        {/* Search */}
        <div className="px-3 py-2 border-b border-gray-100">
          <div className="flex items-center gap-2 border border-gray-200 rounded-md bg-gray-50 px-2.5 focus-within:bg-white focus-within:border-blue-400 focus-within:ring-1 focus-within:ring-blue-400 transition-colors">
            <svg className="w-4 h-4 text-gray-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
            <input
              type="text"
              placeholder="Search in Invoices ( / )"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full py-1.5 text-sm bg-transparent outline-none placeholder:text-gray-400"
              aria-label="Search invoices"
            />
          </div>
        </div>

        {/* Invoice list */}
        <div className="flex-1 overflow-y-auto">
          {listLoading && !data && (
            <div className="flex items-center justify-center py-12">
              <Spinner label="Loading" />
            </div>
          )}
          {listError && (
            <div className="px-4 py-3 text-sm text-red-600">{listError}</div>
          )}
          {data && data.items.length === 0 && (
            <div className="px-4 py-12 text-center text-sm text-gray-500">
              {searchQuery || statusFilter ? 'No invoices match.' : 'No invoices yet.'}
            </div>
          )}
          {data && data.items.map((inv) => {
            const cfg = STATUS_CONFIG[inv.status] ?? STATUS_CONFIG.draft
            const isActive = inv.id === selectedId
            const dueLabel = getDueDateLabel(inv)
            return (
              <button
                key={inv.id}
                onClick={() => setSelectedId(inv.id)}
                className={`w-full text-left px-4 py-3 border-b border-gray-50 transition-colors ${
                  isActive
                    ? 'bg-blue-50 border-l-[3px] border-l-blue-500'
                    : 'hover:bg-gray-50 border-l-[3px] border-l-transparent'
                }`}
                aria-current={isActive ? 'true' : undefined}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className={`text-sm font-medium truncate ${isActive ? 'text-blue-700' : 'text-gray-900'}`}>
                      {inv.customer_name || 'No customer'}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {inv.invoice_number || 'Draft'} · {formatDateShort(inv.issue_date ?? inv.created_at)}
                    </p>
                    {inv.branch_id && (() => {
                      const branch = (branchList ?? []).find(b => b.id === inv.branch_id)
                      return branch ? (
                        <p className="text-[10px] text-gray-400 mt-0.5 truncate">{branch.name}</p>
                      ) : null
                    })()}
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <p className="text-sm font-semibold tabular-nums text-gray-900">
                      {formatNZD(inv.total)}
                    </p>
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={(e) => { e.stopPropagation(); setDeleteTargetId(inv.id); setDeleteTargetNumber(inv.invoice_number || 'Draft'); setDeleteModalOpen(true) }}
                      onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); setDeleteTargetId(inv.id); setDeleteTargetNumber(inv.invoice_number || 'Draft'); setDeleteModalOpen(true) } }}
                      className="p-1 rounded text-gray-300 hover:text-red-500 hover:bg-red-50 transition-colors"
                      title="Delete invoice"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                      </svg>
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-2 mt-1.5">
                  <span className={`text-[10px] font-bold uppercase tracking-wider ${cfg.color}`}>
                    {cfg.label}
                  </span>
                  {inv.status === 'paid' && (
                    <svg className="w-3 h-3 text-emerald-500" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  )}
                  {inv.has_stripe_payment && (
                    <span title="Paid online" className="inline-flex items-center">
                      <svg className="w-3.5 h-3.5 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3m-3.75 3h15a2.25 2.25 0 002.25-2.25V6.75A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25v10.5A2.25 2.25 0 004.5 19.5z" />
                      </svg>
                    </span>
                  )}
                  {dueLabel && <span className={dueLabel.className}>{dueLabel.text}</span>}
                  {(inv.attachment_count ?? 0) > 0 && (
                    <span className="text-gray-400 text-xs">📎 {inv.attachment_count}</span>
                  )}
                </div>
              </button>
            )
          })}
        </div>

        {/* Pagination footer */}
        {data && data.total_pages > 1 && (
          <div className="flex items-center justify-between px-4 py-2 border-t border-gray-100 text-xs text-gray-500">
            <span>{data.total} invoice{data.total !== 1 ? 's' : ''}</span>
            <div className="flex items-center gap-1">
              <button
                disabled={page <= 1}
                onClick={() => setPage(p => Math.max(1, p - 1))}
                className="px-2 py-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                ‹
              </button>
              <span>{page}/{data.total_pages}</span>
              <button
                disabled={page >= data.total_pages}
                onClick={() => setPage(p => p + 1)}
                className="px-2 py-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                ›
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ============================================================ */}
      {/*  RIGHT PANEL — Invoice Detail or Create                       */}
      {/* ============================================================ */}
      <div className="flex-1 flex flex-col overflow-hidden" data-print-content>
        {isCreating && (
          <div className="flex-1 overflow-y-auto">
            <InvoiceCreate />
          </div>
        )}

        {!isCreating && !selectedId && !detailLoading && (
          <div className="flex-1 flex items-center justify-center text-gray-400">
            <div className="text-center">
              <svg className="w-16 h-16 mx-auto mb-4 text-gray-200" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
              </svg>
              <p className="text-sm">Select an invoice to view details</p>
            </div>
          </div>
        )}

        {!isCreating && detailLoading && (
          <div className="flex-1 flex items-center justify-center">
            <Spinner label="Loading invoice" />
          </div>
        )}

        {!isCreating && detailError && !detailLoading && (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <p className="text-sm text-red-600 mb-2">{detailError}</p>
              <Button size="sm" variant="secondary" onClick={() => selectedId && fetchDetail(selectedId)}>Retry</Button>
            </div>
          </div>
        )}

        {!isCreating && invoice && !detailLoading && (
          <>
            {/* ---- Top toolbar ---- */}
            <div className="flex items-center justify-between px-6 py-3 border-b border-gray-200 bg-white" data-print-hide>
              <div className="flex items-center gap-3">
                <h2 className="text-lg font-semibold text-gray-900">
                  {invoice.invoice_number || 'Draft Invoice'}
                </h2>
              </div>

              <div className="flex items-center gap-2">
                {/* Edit button */}
                {isDraft && (
                  <button
                    onClick={() => navigate(`/invoices/${invoice.id}/edit`)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                    </svg>
                    Edit
                  </button>
                )}

                {/* Send dropdown */}
                <div className="relative" ref={sendMenuRef}>
                  <button
                    onClick={() => { setSendMenuOpen(!sendMenuOpen); setPdfMenuOpen(false); setMoreMenuOpen(false); setReminderMenuOpen(false) }}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
                    </svg>
                    Send
                    <svg className="w-3 h-3 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                    </svg>
                  </button>
                  {sendMenuOpen && (
                    <div className="absolute right-0 mt-1 w-48 bg-white border border-gray-200 rounded-lg shadow-lg z-50 py-1">
                      <button
                        onClick={handleSendInvoice}
                        disabled={actionLoading === 'send'}
                        className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                      >
                        {actionLoading === 'send' ? 'Sending…' : 'Send Invoice'}
                      </button>
                      {isDraft && (
                        <button
                          onClick={handleMarkAsSent}
                          disabled={actionLoading === 'markSent'}
                          className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                        >
                          {actionLoading === 'markSent' ? 'Processing…' : 'Mark as Sent'}
                        </button>
                      )}
                    </div>
                  )}
                </div>

                {/* Send Reminder dropdown — only for non-draft, non-voided invoices with balance due */}
                {canRecordPayment && (
                  <div className="relative" ref={reminderMenuRef}>
                    <button
                      onClick={() => { setReminderMenuOpen(!reminderMenuOpen); setSendMenuOpen(false); setPdfMenuOpen(false); setMoreMenuOpen(false) }}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
                      </svg>
                      Reminder
                      <svg className="w-3 h-3 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                      </svg>
                    </button>
                    {reminderMenuOpen && (
                      <div className="absolute right-0 mt-1 w-48 bg-white border border-gray-200 rounded-lg shadow-lg z-50 py-1">
                        <button
                          onClick={() => handleSendReminder('email')}
                          disabled={actionLoading === 'reminder'}
                          className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                        >
                          {actionLoading === 'reminder' ? 'Sending…' : '📧 Send Email'}
                        </button>
                        <button
                          onClick={() => handleSendReminder('sms')}
                          disabled={actionLoading === 'reminder'}
                          className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50 border-t border-gray-100"
                        >
                          {actionLoading === 'reminder' ? 'Sending…' : '💬 Send SMS'}
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {/* Share button */}
                <button
                  onClick={handleShareLink}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244" />
                  </svg>
                  Share
                </button>

                {/* PDF/Print dropdown */}
                <div className="relative" ref={pdfMenuRef}>
                  <button
                    onClick={() => { setPdfMenuOpen(!pdfMenuOpen); setSendMenuOpen(false); setMoreMenuOpen(false); setReminderMenuOpen(false) }}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6.72 13.829c-.24.03-.48.062-.72.096m.72-.096a42.415 42.415 0 0110.56 0m-10.56 0L6.34 18m10.94-4.171c.24.03.48.062.72.096m-.72-.096L17.66 18m0 0l.229 2.523a1.125 1.125 0 01-1.12 1.227H7.231c-.662 0-1.18-.568-1.12-1.227L6.34 18m11.318 0h1.091A2.25 2.25 0 0021 15.75V9.456c0-1.081-.768-2.015-1.837-2.175a48.055 48.055 0 00-1.913-.247M6.34 18H5.25A2.25 2.25 0 013 15.75V9.456c0-1.081.768-2.015 1.837-2.175a48.041 48.041 0 011.913-.247m10.5 0a48.536 48.536 0 00-10.5 0m10.5 0V3.375c0-.621-.504-1.125-1.125-1.125h-8.25c-.621 0-1.125.504-1.125 1.125v3.659M18 10.5h.008v.008H18V10.5zm-3 0h.008v.008H15V10.5z" />
                    </svg>
                    PDF/Print
                    <svg className="w-3 h-3 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                    </svg>
                  </button>
                  {pdfMenuOpen && (
                    <div className="absolute right-0 mt-1 w-44 bg-white border border-gray-200 rounded-lg shadow-lg z-50 py-1">
                      <button
                        onClick={handleDownloadPDF}
                        disabled={actionLoading === 'pdf'}
                        className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                      >
                        {actionLoading === 'pdf' ? 'Downloading…' : 'Download PDF'}
                      </button>
                      <button
                        onClick={handlePrint}
                        className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                      >
                        Print Invoice
                      </button>
                      <button
                        onClick={handlePrintReceipt}
                        className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                      >
                        Print POS Receipt
                      </button>
                    </div>
                  )}
                </div>

                {/* Record Payment */}
                {canRecordPayment && (
                  <button
                    onClick={() => { setPaymentAmount(String(invoice.balance_due ?? 0)); setPaymentModalOpen(true) }}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-white bg-emerald-600 rounded-md hover:bg-emerald-700 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z" />
                    </svg>
                    Record Payment
                  </button>
                )}

                {/* More menu */}
                <div className="relative" ref={moreMenuRef}>
                  <button
                    onClick={() => { setMoreMenuOpen(!moreMenuOpen); setSendMenuOpen(false); setPdfMenuOpen(false); setReminderMenuOpen(false) }}
                    className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-md transition-colors"
                    aria-label="More actions"
                  >
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 12a.75.75 0 11-1.5 0 .75.75 0 011.5 0zM12.75 12a.75.75 0 11-1.5 0 .75.75 0 011.5 0zM18.75 12a.75.75 0 11-1.5 0 .75.75 0 011.5 0z" />
                    </svg>
                  </button>
                  {moreMenuOpen && (
                    <div className="absolute right-0 mt-1 w-48 bg-white border border-gray-200 rounded-lg shadow-lg z-50 py-1">
                      <button
                        onClick={handleDuplicate}
                        disabled={actionLoading === 'duplicate'}
                        className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                      >
                        {actionLoading === 'duplicate' ? 'Duplicating…' : 'Duplicate'}
                      </button>
                      <button
                        onClick={handleShareLink}
                        className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                      >
                        Copy Link
                      </button>
                      {invoice && isCreditNoteButtonVisible(invoice.status) && (
                        <button
                          onClick={() => { setCreditNoteModalOpen(true); setMoreMenuOpen(false) }}
                          className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                        >
                          Create Credit Note
                        </button>
                      )}
                      {invoice && isRefundButtonVisible(invoice.amount_paid) && (
                        <button
                          onClick={() => { setRefundModalOpen(true); setMoreMenuOpen(false) }}
                          className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                        >
                          Process Refund
                        </button>
                      )}
                      {canVoid && (
                        <>
                          <div className="border-t border-gray-100 my-1" />
                          <button
                            onClick={() => { setVoidModalOpen(true); setMoreMenuOpen(false) }}
                            className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50"
                          >
                            Void Invoice
                          </button>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Action feedback toast */}
            {actionMessage && (
              <div className={`mx-6 mt-3 rounded-lg px-4 py-2.5 text-sm font-medium ${
                actionMessage.type === 'success'
                  ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                  : 'bg-red-50 text-red-700 border border-red-200'
              }`} role="status">
                {actionMessage.text}
              </div>
            )}

            {/* Draft banner */}
            {isDraft && (
              <div className="mx-6 mt-3 flex items-center gap-3 rounded-lg bg-amber-50 border border-amber-200 px-4 py-2.5">
                <svg className="w-5 h-5 text-amber-500 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
                </svg>
                <span className="text-sm text-amber-800">
                  WHAT'S NEXT? Send this invoice to your customer or mark it as Sent.
                </span>
                <div className="ml-auto flex items-center gap-2">
                  <button
                    onClick={handleSendInvoice}
                    disabled={actionLoading === 'send'}
                    className="px-3 py-1 text-xs font-semibold text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50 transition-colors"
                  >
                    {actionLoading === 'send' ? 'Sending…' : 'Send Invoice'}
                  </button>
                  <button
                    onClick={handleMarkAsSent}
                    disabled={actionLoading === 'markSent'}
                    className="px-3 py-1 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 transition-colors"
                  >
                    Mark As Sent
                  </button>
                </div>
              </div>
            )}

            {/* Voided banner */}
            {isVoided && (
              <div className="mx-6 mt-3 rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
                This invoice has been voided.{invoice.void_reason && <> Reason: {invoice.void_reason}</>}
              </div>
            )}



            {/* ---- Invoice Preview + POS Receipt Side by Side ---- */}
            <div className="flex-1 overflow-y-auto px-6 py-4">
              <div className="flex gap-4 max-w-6xl mx-auto items-start">
              {/* Left: Invoice Preview Card */}
              <div className="flex-1 min-w-0" data-preview="invoice">
              <div
                onClick={() => setSelectedPreview('invoice')}
                className={`max-w-3xl bg-white rounded-xl shadow-sm overflow-hidden cursor-pointer transition-all ${selectedPreview === 'invoice' ? 'ring-2 ring-blue-500 border border-blue-300' : 'border border-gray-200 hover:border-gray-300'}`}
              >
                {/* Watermark for draft */}
                <div className="relative">
                  {isDraft && (
                    <div className="absolute top-8 left-8 -rotate-12 text-gray-100 text-6xl font-black tracking-widest pointer-events-none select-none z-0 opacity-60">
                      DRAFT
                    </div>
                  )}

                  {/* Invoice header */}
                  <div className={`relative z-10 ${templateStyles.layoutType === 'compact' ? 'px-6 pt-6 pb-4' : 'px-8 pt-8 pb-6'}`} style={{ backgroundColor: templateStyles.headerBgColour }}>
                    <div className={`flex ${templateStyles.logoPosition === 'center' ? 'flex-col items-center text-center' : 'items-start justify-between'}`}>
                      {/* Org info */}
                      <div style={templateStyles.logoPosition === 'side' ? { order: 2 } : undefined}>
                        {invoice.org_logo_url ? (
                          <img src={invoice.org_logo_url} alt={invoice.org_name || 'Company'} className="h-12 mb-3" />
                        ) : (
                          <div className="flex items-center gap-2 mb-3">
                            <div className="w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold text-lg" style={{ background: templateStyles.primaryColour }}>
                              {(invoice.org_name || 'O')[0]}
                            </div>
                            <span className={`text-lg font-bold ${templateStyles.isHeaderDark ? 'text-white' : 'text-gray-900'}`}>{invoice.org_name || 'Your Company'}</span>
                          </div>
                        )}
                        <div className={`text-xs ${templateStyles.isHeaderDark ? 'text-gray-200' : 'text-gray-500'} space-y-0.5`}>
                          {(invoice.org_address_street || invoice.org_address) && (
                            <>
                              {invoice.org_address_unit && <p>{invoice.org_address_unit}</p>}
                              {invoice.org_address_street ? (
                                <p>{invoice.org_address_street}</p>
                              ) : invoice.org_address && (
                                <p>{invoice.org_address}</p>
                              )}
                              {(invoice.org_address_city || invoice.org_address_state || invoice.org_address_postcode) && (
                                <p>{[invoice.org_address_city, invoice.org_address_state, invoice.org_address_postcode].filter(Boolean).join(', ')}</p>
                              )}
                              {invoice.org_address_country && <p>{invoice.org_address_country}</p>}
                            </>
                          )}
                          {invoice.org_phone && <p>{invoice.org_phone}</p>}
                          {invoice.org_email && <p>{invoice.org_email}</p>}
                          {invoice.org_website && <p>{invoice.org_website}</p>}
                        </div>
                      </div>

                      {/* Invoice title + balance */}
                      <div className={templateStyles.logoPosition === 'left' ? 'text-right' : ''} style={templateStyles.logoPosition === 'side' ? { order: 1 } : undefined}>
                        <h1 className={`text-2xl font-bold tracking-tight ${templateStyles.isHeaderDark ? 'text-white' : 'text-gray-900'}`}>INVOICE</h1>
                        <p className={`text-sm ${templateStyles.isHeaderDark ? 'text-gray-200' : 'text-gray-500'} mt-0.5`}># {invoice.invoice_number || 'DRAFT'}</p>
                        <div className={`mt-3 rounded-lg px-4 py-2 border ${templateStyles.isHeaderDark ? 'bg-white/10 border-white/20' : 'bg-gray-50 border-gray-100'}`}>
                          <p className={`text-xs ${templateStyles.isHeaderDark ? 'text-gray-200' : 'text-gray-500'}`}>Balance Due</p>
                          <p className={`text-xl font-bold tabular-nums ${templateStyles.isHeaderDark ? 'text-white' : (invoice.balance_due ?? 0) > 0 ? 'text-gray-900' : 'text-emerald-600'}`}>
                            {formatNZD(invoice.balance_due)}
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Bill To + Invoice Meta */}
                  <div className={`relative z-10 ${templateStyles.layoutType === 'compact' ? 'px-6 pb-4' : 'px-8 pb-6'}`}>
                    <div className="flex items-start justify-between gap-8">
                      {/* Bill To */}
                      <div className="flex-1">
                        {invoice.customer ? (
                          <div className="rounded-lg p-4 border" style={{ backgroundColor: templateStyles.accentColour + '10', borderColor: templateStyles.accentColour + '30' }}>
                            <p className="text-xs font-semibold uppercase tracking-wider mb-1.5" style={{ color: templateStyles.accentColour }}>Bill To</p>
                            <p className="font-semibold text-gray-900">
                              {invoice.customer.display_name || `${invoice.customer.first_name} ${invoice.customer.last_name}`}
                            </p>
                            {invoice.customer.company_name && (
                              <p className="text-sm text-gray-700 font-medium">{invoice.customer.company_name}</p>
                            )}
                            {invoice.customer.address && (
                              <p className="text-sm text-gray-600 mt-0.5 whitespace-pre-line">{invoice.customer.address}</p>
                            )}
                            {invoice.customer.email && (
                              <p className="text-sm text-gray-600 mt-0.5">{invoice.customer.email}</p>
                            )}
                            {invoice.customer.phone && (
                              <p className="text-sm text-gray-600">{invoice.customer.phone}</p>
                            )}
                          </div>
                        ) : (
                          <div className="bg-gray-50 rounded-lg p-4 border border-gray-100">
                            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Bill To</p>
                            <p className="text-sm text-gray-400">No customer assigned</p>
                          </div>
                        )}
                      </div>

                      {/* Invoice meta */}
                      <div className="w-56 shrink-0">
                        <dl className="space-y-2 text-sm">
                          <div className="flex justify-between">
                            <dt className="text-gray-500">Invoice Date :</dt>
                            <dd className="text-gray-900 font-medium">{formatDate(invoice.issue_date)}</dd>
                          </div>
                          <div className="flex justify-between">
                            <dt className="text-gray-500">Terms :</dt>
                            <dd className="text-gray-900">{formatPaymentTerms(invoice.payment_terms)}</dd>
                          </div>
                          <div className="flex justify-between">
                            <dt className="text-gray-500">Due Date :</dt>
                            <dd className="text-gray-900 font-medium">{formatDate(invoice.due_date)}</dd>
                          </div>
                          {invoice.org_gst_number && (
                            <div className="flex justify-between">
                              <dt className="text-gray-500">GST No :</dt>
                              <dd className="text-gray-900 font-mono text-xs">{invoice.org_gst_number}</dd>
                            </div>
                          )}
                        </dl>
                      </div>
                    </div>
                  </div>

                  {/* Vehicle info (inside invoice card) */}
                  {isAutomotive && (
                  <>
                  {(invoice.vehicle || invoice.vehicle_rego) && (
                    <div className="relative z-10 px-8 pb-4">
                      <div className="bg-slate-50 rounded-lg border border-slate-200 px-5 py-3">
                        <div className="flex items-center gap-6 text-sm">
                          <div className="flex items-center gap-1.5">
                            <span className="text-xs text-gray-400 uppercase tracking-wider">Rego</span>
                            <span className="font-mono font-bold text-gray-900 bg-yellow-100 px-2 py-0.5 rounded text-xs">{invoice.vehicle?.rego || invoice.vehicle_rego}</span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <span className="text-xs text-gray-400 uppercase tracking-wider">Vehicle</span>
                            <span className="text-gray-900">{[invoice.vehicle?.year || invoice.vehicle_year, invoice.vehicle?.make || invoice.vehicle_make, invoice.vehicle?.model || invoice.vehicle_model].filter(Boolean).join(' ') || '—'}</span>
                          </div>
                          {(invoice.vehicle?.odometer || invoice.vehicle_odometer) ? (
                            <div className="flex items-center gap-1.5">
                              <span className="text-xs text-gray-400 uppercase tracking-wider">Odometer</span>
                              <span className="text-gray-900">{Number(invoice.vehicle?.odometer || invoice.vehicle_odometer).toLocaleString()} km</span>
                            </div>
                          ) : null}
                          {invoice.vehicle?.wof_expiry && (
                            <div className="flex items-center gap-1.5">
                              <span className="text-xs text-gray-400 uppercase tracking-wider">WOF Expiry</span>
                              <span className="text-gray-900">{formatDate(invoice.vehicle.wof_expiry)}</span>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                  {/* Additional vehicles */}
                  {invoice.additional_vehicles && invoice.additional_vehicles.length > 0 && (
                    <div className="relative z-10 px-8 pb-2">
                      {invoice.additional_vehicles.map((av, idx) => (
                        <div key={av.rego || idx} className="bg-slate-50 rounded-lg border border-slate-200 px-5 py-2 mt-1">
                          <div className="flex items-center gap-6 text-sm">
                            <div className="flex items-center gap-1.5">
                              <span className="text-xs text-gray-400 uppercase tracking-wider">Rego</span>
                              <span className="font-mono font-bold text-gray-900 bg-yellow-100 px-2 py-0.5 rounded text-xs">{av.rego}</span>
                            </div>
                            {(av.make || av.model) && (
                              <div className="flex items-center gap-1.5">
                                <span className="text-xs text-gray-400 uppercase tracking-wider">Vehicle</span>
                                <span className="text-gray-900">{[av.year, av.make, av.model].filter(Boolean).join(' ') || '—'}</span>
                              </div>
                            )}
                            {av.odometer ? (
                              <div className="flex items-center gap-1.5">
                                <span className="text-xs text-gray-400 uppercase tracking-wider">Odometer</span>
                                <span className="text-gray-900">{Number(av.odometer).toLocaleString()} km</span>
                              </div>
                            ) : null}
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
                  </>
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
                          <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wider rounded-tr-lg" style={{ color: '#fff' }}>Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(invoice.line_items || []).map((item, idx) => (
                          <tr key={item.id} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'}>
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
                              {(item.item_type || item.type) === 'labour' ? Number(item.hours ?? 0).toFixed(2) : Number(item.quantity).toFixed(2)}
                            </td>
                            <td className={`px-4 ${templateStyles.layoutType === 'compact' ? 'py-1.5' : 'py-3'} text-sm text-gray-900 text-right tabular-nums`}>
                              {Number((item.item_type || item.type) === 'labour' ? (item.hourly_rate ?? 0) : item.unit_price).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </td>
                            <td className={`px-4 ${templateStyles.layoutType === 'compact' ? 'py-1.5' : 'py-3'} text-sm font-medium text-gray-900 text-right tabular-nums`}>
                              {Number(item.line_total).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </td>
                          </tr>
                        ))}
                        {(invoice.line_items || []).length === 0 && (
                          <tr>
                            <td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-400">No line items</td>
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
                            <dt className="text-gray-500">Sub Total</dt>
                            <dd className="text-gray-900 tabular-nums font-medium">
                              {Number(invoice.subtotal_ex_gst ?? invoice.subtotal ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </dd>
                          </div>
                          {(invoice.discount_value ?? 0) > 0 && (
                            <div className="flex justify-between py-1 text-emerald-600">
                              <dt>Discount</dt>
                              <dd className="tabular-nums">
                                {invoice.discount_type === 'percentage'
                                  ? `−${invoice.discount_value}%`
                                  : `−${Number(invoice.discount_amount ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`}
                              </dd>
                            </div>
                          )}
                          <div className="flex justify-between py-1">
                            <dt className="text-gray-500">GST (15%)</dt>
                            <dd className="text-gray-900 tabular-nums">
                              {Number(invoice.gst_amount ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </dd>
                          </div>
                          <div className="flex justify-between py-2 border-t border-gray-200 font-bold text-base">
                            <dt className="text-gray-900">Total</dt>
                            <dd className="text-gray-900 tabular-nums">
                              {formatNZD(invoice.total_incl_gst ?? invoice.total)}
                            </dd>
                          </div>
                          {paymentSummary.totalPaid > 0 && (
                            <div className="flex justify-between py-1 text-emerald-600">
                              <dt>Payments</dt>
                              <dd className="tabular-nums">−{formatNZDUtil(paymentSummary.totalPaid)}</dd>
                            </div>
                          )}
                          {paymentSummary.totalRefunded > 0 && (
                            <div className="flex justify-between py-1 text-red-600">
                              <dt>Refunded</dt>
                              <dd className="tabular-nums">+{formatNZDUtil(paymentSummary.totalRefunded)}</dd>
                            </div>
                          )}
                          {paymentSummary.totalRefunded > 0 && (() => {
                            const netRetained = paymentSummary.netPaid
                            const netRetainedExGst = netRetained / 1.15
                            const netGst = netRetained - netRetainedExGst
                            return (
                              <div className="border-t border-orange-200 mt-1 pt-1 space-y-1">
                                <div className="flex justify-between py-0.5 text-xs text-gray-500 uppercase tracking-wider">
                                  <dt>Adjusted after refund</dt>
                                  <dd></dd>
                                </div>
                                <div className="flex justify-between py-0.5">
                                  <dt className="text-gray-500">Net Amount (ex-GST)</dt>
                                  <dd className="text-gray-900 tabular-nums">{formatNZDUtil(netRetainedExGst)}</dd>
                                </div>
                                <div className="flex justify-between py-0.5">
                                  <dt className="text-gray-500">GST Collected (15%)</dt>
                                  <dd className="text-gray-900 tabular-nums">{formatNZDUtil(netGst)}</dd>
                                </div>
                                <div className="flex justify-between py-0.5 font-semibold">
                                  <dt className="text-gray-900">Net Total (incl. GST)</dt>
                                  <dd className="text-gray-900 tabular-nums">{formatNZDUtil(netRetained)}</dd>
                                </div>
                              </div>
                            )
                          })()}
                          <div className="flex justify-between py-2.5 rounded-lg px-4 -mx-4 font-bold print-balance-bar" style={{ background: templateStyles.primaryColour, color: '#fff', WebkitPrintColorAdjust: 'exact', printColorAdjust: 'exact' } as React.CSSProperties}>
                            <dt style={{ color: '#fff' }}>Balance Due</dt>
                            <dd className="tabular-nums" style={{ color: '#fff' }}>{formatNZD(invoice.balance_due)}</dd>
                          </div>
                        </dl>
                      </div>
                    </div>
                  </div>

                  {/* Notes & footer */}
                  <div className="relative z-10 px-8 pb-8">
                    {(invoice.notes || invoice.notes_customer) && (
                      <div className="border-t border-gray-100 pt-4 mb-4">
                        <p className="text-xs text-gray-400 uppercase tracking-wider mb-1">Notes</p>
                        <p className="text-sm text-gray-600 whitespace-pre-wrap">{invoice.notes_customer || invoice.notes}</p>
                      </div>
                    )}

                    {/* Payment instructions */}
                    <div className="border-t border-gray-100 pt-4 text-xs text-gray-400">
                      <p>Thank you for your business.</p>
                      {invoice.org_gst_number && (
                        <p className="mt-1">
                          Payments can be paid by direct bank transfer. Please use your Invoice number as your ref number on your bank transfer.
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* Vehicle info is now inside the invoice card above */}

              {/* ---- Attachments ---- */}
              {(invoice?.attachment_count ?? 0) > 0 && (
                <AttachmentList invoiceId={invoice.id} isDraft={invoice?.status === 'draft'} />
              )}

              {/* ---- Payment History ---- */}
              {(invoice.payments || []).length > 0 && (
                <div className="mt-4 bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Payment History</h3>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100">
                        <th className="text-left py-2 text-xs text-gray-500 font-medium">Date</th>
                        <th className="text-left py-2 text-xs text-gray-500 font-medium">Type</th>
                        <th className="text-right py-2 text-xs text-gray-500 font-medium">Amount</th>
                        <th className="text-left py-2 text-xs text-gray-500 font-medium">Method</th>
                        <th className="text-left py-2 text-xs text-gray-500 font-medium">Recorded By</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(invoice.payments || []).map((p) => {
                        const badgeType = getPaymentBadgeType(!!p.is_refund)
                        return (
                          <Fragment key={p.id}>
                          <tr className="border-b border-gray-50">
                            <td className="py-2 text-gray-900">{formatDateTime(p.date)}</td>
                            <td className="py-2">
                              <Badge variant={badgeType.color === 'green' ? 'success' : 'error'}>{badgeType.label}</Badge>
                            </td>
                            <td className={`py-2 text-right tabular-nums font-medium ${p.is_refund ? 'text-red-600' : 'text-emerald-600'}`}>{formatNZD(p.amount)}</td>
                            <td className="py-2 text-gray-700 capitalize">{p.method}</td>
                            <td className="py-2 text-gray-700">{p.recorded_by}</td>
                          </tr>
                          {shouldShowRefundNote(!!p.is_refund, p.refund_note) && (
                            <tr>
                              <td colSpan={5} className="py-1 text-sm text-gray-500 italic">
                                Note: {p.refund_note}
                              </td>
                            </tr>
                          )}
                          </Fragment>
                        )
                      })}
                    </tbody>
                  </table>
                  <div className="mt-3 flex justify-end">
                    <dl className="w-56 space-y-1 text-sm">
                      <div className="flex justify-between">
                        <dt className="text-gray-500">Total Paid</dt>
                        <dd className="text-gray-900 tabular-nums">{formatNZDUtil(paymentSummary.totalPaid)}</dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="text-gray-500">Total Refunded</dt>
                        <dd className="text-red-600 tabular-nums">{formatNZDUtil(paymentSummary.totalRefunded)}</dd>
                      </div>
                      <div className="flex justify-between border-t border-gray-200 pt-1 font-semibold">
                        <dt className="text-gray-900">Net Paid</dt>
                        <dd className="text-gray-900 tabular-nums">{formatNZDUtil(paymentSummary.netPaid)}</dd>
                      </div>
                    </dl>
                  </div>
                </div>
              )}

              {/* ---- Credit Notes ---- */}
              {(invoice.credit_notes || []).length > 0 && (
                <div className="mt-4 bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Credit Notes</h3>
                    {isCreditNoteButtonVisible(invoice.status) && (
                      <button
                        onClick={() => setCreditNoteModalOpen(true)}
                        className="text-xs font-medium text-blue-600 hover:text-blue-700"
                      >
                        + Create Credit Note
                      </button>
                    )}
                  </div>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100">
                        <th className="text-left py-2 text-xs text-gray-500 font-medium">Reference</th>
                        <th className="text-right py-2 text-xs text-gray-500 font-medium">Amount</th>
                        <th className="text-left py-2 text-xs text-gray-500 font-medium">Reason</th>
                        <th className="text-left py-2 text-xs text-gray-500 font-medium">Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(invoice.credit_notes || []).map((cn) => (
                        <tr key={cn.id} className="border-b border-gray-50">
                          <td className="py-2 font-medium text-blue-600">{cn.reference_number}</td>
                          <td className="py-2 text-right tabular-nums font-medium text-red-600">−{formatNZD(cn.amount)}</td>
                          <td className="py-2 text-gray-700">{cn.reason}</td>
                          <td className="py-2 text-gray-700">{formatDateTime(cn.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t border-gray-200">
                        <td className="py-2 text-sm font-medium text-gray-900">Total</td>
                        <td className="py-2 text-right tabular-nums font-medium text-red-600">
                          −{formatNZDUtil((invoice.credit_notes || []).reduce((sum, cn) => sum + cn.amount, 0))}
                        </td>
                        <td colSpan={2}></td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}

              {/* Internal notes */}
              {invoice.notes_internal && (
                <div className="mt-4 bg-amber-50 rounded-xl border border-amber-200 p-5">
                  <h3 className="text-xs font-semibold text-amber-600 uppercase tracking-wider mb-2">Internal Note</h3>
                  <p className="text-sm text-gray-700 whitespace-pre-wrap">{invoice.notes_internal}</p>
                </div>
              )}
              </div>{/* end left column */}

              {/* Right: POS Receipt Preview */}
              <div
                data-preview="receipt"
                onClick={() => setSelectedPreview('receipt')}
                className={`w-[280px] shrink-0 sticky top-0 cursor-pointer rounded-xl p-3 transition-all ${selectedPreview === 'receipt' ? 'ring-2 ring-blue-500 bg-blue-50/30' : 'hover:bg-gray-50'}`}
              >
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">POS Receipt</h3>
                <POSReceiptPreview receiptData={invoiceToReceiptData(invoice)} paperWidth={80} />
              </div>
              </div>{/* end flex row */}

              {/* Bottom spacer */}
              <div className="h-8" />
            </div>
          </>
        )}
      </div>

      {/* ============================================================ */}
      {/*  MODALS                                                       */}
      {/* ============================================================ */}

      {/* Void Modal */}
      <Modal open={voidModalOpen} onClose={() => { setVoidModalOpen(false); setVoidReason('') }} title="Void Invoice">
        <p className="text-sm text-gray-600 mb-4">
          Voiding this invoice will retain its number but exclude it from revenue reporting. This cannot be undone.
        </p>
        <label className="block text-sm font-medium text-gray-700 mb-1" htmlFor="void-reason">
          Reason for voiding
        </label>
        <textarea
          id="void-reason"
          value={voidReason}
          onChange={(e) => setVoidReason(e.target.value)}
          rows={3}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          placeholder="e.g. Duplicate invoice, customer dispute…"
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => { setVoidModalOpen(false); setVoidReason('') }}>Cancel</Button>
          <Button variant="danger" size="sm" onClick={handleVoid} loading={actionLoading === 'void'} disabled={!voidReason.trim()}>
            Void Invoice
          </Button>
        </div>
      </Modal>

      {/* Record Payment Modal */}
      <Modal open={paymentModalOpen} onClose={() => setPaymentModalOpen(false)} title="Record Payment">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Amount</label>
            <div className="flex">
              <span className="inline-flex items-center px-3 rounded-l-md border border-r-0 border-gray-300 bg-gray-50 text-sm text-gray-500">NZD</span>
              <input
                type="number"
                step="0.01"
                min="0"
                value={paymentAmount}
                onChange={(e) => setPaymentAmount(e.target.value)}
                className="flex-1 min-w-0 rounded-r-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                placeholder="0.00"
              />
            </div>
            {invoice && (
              <p className="text-xs text-gray-500 mt-1">Balance due: {formatNZD(invoice.balance_due)}</p>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Payment Method</label>
            <select
              value={paymentMethod}
              onChange={(e) => setPaymentMethod(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            >
              <option value="cash">Cash</option>
              <option value="eftpos">EFTPOS</option>
              <option value="bank_transfer">Bank Transfer</option>
              <option value="card">Card</option>
              <option value="cheque">Cheque</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Note (optional)</label>
            <input
              type="text"
              value={paymentNote}
              onChange={(e) => setPaymentNote(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="Payment reference or note"
            />
          </div>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setPaymentModalOpen(false)}>Cancel</Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleRecordPayment}
            loading={actionLoading === 'payment'}
            disabled={!paymentAmount || parseFloat(paymentAmount) <= 0}
          >
            Record Payment
          </Button>
        </div>
      </Modal>

      {/* Share Link Modal */}
      <Modal open={shareModalOpen} onClose={() => setShareModalOpen(false)} title="Share Invoice">
        <p className="text-sm text-gray-600 mb-3">
          Anyone with this link can view the invoice, print it, or save it as PDF.
        </p>
        <div className="flex items-center gap-2">
          <input
            type="text"
            readOnly
            value={shareUrl}
            className="flex-1 rounded-md border border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-700 select-all focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            onClick={(e) => (e.target as HTMLInputElement).select()}
          />
          <button
            onClick={handleCopyShareUrl}
            className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium transition-colors whitespace-nowrap ${
              shareCopied
                ? 'bg-emerald-50 text-emerald-700 border border-emerald-300'
                : 'bg-blue-600 text-white hover:bg-blue-700 border border-blue-600'
            }`}
          >
            {shareCopied ? (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                </svg>
                Copied
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9.75a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
                </svg>
                Copy Link
              </>
            )}
          </button>
        </div>
        <div className="mt-3 flex justify-end">
          <a
            href={shareUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-blue-600 hover:text-blue-800 hover:underline"
          >
            Open in new tab →
          </a>
        </div>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal open={deleteModalOpen} onClose={() => { setDeleteModalOpen(false); setDeleteTargetId(null) }} title="Delete Invoice">
        <p className="text-sm text-gray-600 mb-1">
          Are you sure you want to permanently delete <span className="font-semibold text-gray-900">{deleteTargetNumber}</span>?
        </p>
        <p className="text-sm text-red-600 mb-4">
          This action cannot be undone. The invoice and all its line items, payments, and history will be permanently removed.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => { setDeleteModalOpen(false); setDeleteTargetId(null) }}>Cancel</Button>
          <Button variant="danger" size="sm" onClick={handleDeleteInvoice} loading={actionLoading === 'delete'}>
            Delete Permanently
          </Button>
        </div>
      </Modal>

      {/* Credit Note & Refund Modals */}
      {invoice && (
        <>
          <CreditNoteModal
            open={creditNoteModalOpen}
            onClose={() => setCreditNoteModalOpen(false)}
            onSuccess={() => { fetchDetail(invoice.id); fetchInvoices(searchQuery, statusFilter, page) }}
            invoiceId={invoice.id}
            creditableAmount={creditableAmount}
          />
          <RefundModal
            open={refundModalOpen}
            onClose={() => setRefundModalOpen(false)}
            onSuccess={() => { fetchDetail(invoice.id); fetchInvoices(searchQuery, statusFilter, page) }}
            invoiceId={invoice.id}
            refundableAmount={refundableAmount}
          />
        </>
      )}
    </div>
  )
}
