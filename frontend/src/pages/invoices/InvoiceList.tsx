import { useState, useEffect, useRef, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Badge, Spinner, Pagination } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type InvoiceStatus = 'draft' | 'issued' | 'partially_paid' | 'paid' | 'overdue' | 'voided'

interface InvoiceSummary {
  id: string
  invoice_number: string | null
  customer_name: string
  customer_id: string
  rego: string
  total: number
  balance_due: number
  status: InvoiceStatus
  issue_date: string | null
  due_date: string | null
  created_at: string
}

interface InvoiceListResponse {
  items: InvoiceSummary[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(amount: number): string {
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(amount)
}

function formatDate(dateStr: string | null): string {
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

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'draft', label: 'Draft' },
  { value: 'issued', label: 'Issued' },
  { value: 'partially_paid', label: 'Partially Paid' },
  { value: 'paid', label: 'Paid' },
  { value: 'overdue', label: 'Overdue' },
  { value: 'voided', label: 'Voided' },
]

const PAGE_SIZE = 20

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function InvoiceList() {
  /* --- Search & filter state --- */
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(1)

  /* --- Data state --- */
  const [data, setData] = useState<InvoiceListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* --- Batch selection --- */
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [batchLoading, setBatchLoading] = useState(false)
  const [batchMessage, setBatchMessage] = useState('')

  const debounceRef = useRef<ReturnType<typeof setTimeout>>()
  const abortRef = useRef<AbortController>()

  /* --- Fetch invoices --- */
  const fetchInvoices = useCallback(async (
    search: string,
    status: string,
    from: string,
    to: string,
    pg: number,
  ) => {
    // Cancel any in-flight request
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError('')
    try {
      const params: Record<string, string | number> = {
        page: pg,
        page_size: PAGE_SIZE,
      }
      if (search.trim()) params.search = search.trim()
      if (status) params.status = status
      if (from) params.date_from = from
      if (to) params.date_to = to

      const res = await apiClient.get<InvoiceListResponse>('/invoices', {
        params,
        signal: controller.signal,
      })
      setData(res.data)
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setError('Failed to load invoices. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [])

  /* --- Debounced search --- */
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setPage(1)
      fetchInvoices(searchQuery, statusFilter, dateFrom, dateTo, 1)
    }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [searchQuery, statusFilter, dateFrom, dateTo, fetchInvoices])

  /* --- Page change (immediate) --- */
  useEffect(() => {
    fetchInvoices(searchQuery, statusFilter, dateFrom, dateTo, page)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page])

  /* --- Selection helpers --- */
  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    if (!data) return
    if (selectedIds.size === data.items.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(data.items.map((inv) => inv.id)))
    }
  }

  const clearSelection = () => setSelectedIds(new Set())

  const hasSelection = selectedIds.size > 0
  const allSelected = data ? selectedIds.size === data.items.length && data.items.length > 0 : false

  /* --- Batch actions --- */
  const handleBatchMarkPaid = async () => {
    if (!hasSelection) return
    setBatchLoading(true)
    setBatchMessage('')
    try {
      const ids = Array.from(selectedIds)
      const res = await apiClient.post<{ success: number; failed: number }>('/invoices/batch/mark-paid', { invoice_ids: ids })
      setBatchMessage(`Marked ${res.data.success} invoice(s) as paid. ${res.data.failed ? `${res.data.failed} failed.` : ''}`)
      clearSelection()
      fetchInvoices(searchQuery, statusFilter, dateFrom, dateTo, page)
    } catch {
      setBatchMessage('Failed to mark invoices as paid.')
    } finally {
      setBatchLoading(false)
    }
  }

  const handleBatchSendReminders = async () => {
    if (!hasSelection) return
    setBatchLoading(true)
    setBatchMessage('')
    try {
      const ids = Array.from(selectedIds)
      const res = await apiClient.post<{ sent: number; skipped: number }>('/invoices/batch/send-reminders', { invoice_ids: ids })
      setBatchMessage(`Sent ${res.data.sent} reminder(s). ${res.data.skipped ? `${res.data.skipped} skipped.` : ''}`)
      clearSelection()
    } catch {
      setBatchMessage('Failed to send reminders.')
    } finally {
      setBatchLoading(false)
    }
  }

  const handleBatchExportPDF = async () => {
    if (!hasSelection) return
    setBatchLoading(true)
    setBatchMessage('')
    try {
      const ids = Array.from(selectedIds)
      const res = await apiClient.post('/invoices/batch/export-pdf', { invoice_ids: ids }, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'invoices.zip'
      a.click()
      URL.revokeObjectURL(url)
      setBatchMessage(`Exported ${ids.length} invoice(s) as PDF ZIP.`)
      clearSelection()
    } catch {
      setBatchMessage('Failed to export PDFs.')
    } finally {
      setBatchLoading(false)
    }
  }

  const handleBatchExportCSV = async () => {
    if (!hasSelection) return
    setBatchLoading(true)
    setBatchMessage('')
    try {
      const ids = Array.from(selectedIds)
      const res = await apiClient.post('/invoices/batch/export-csv', { invoice_ids: ids }, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'invoices.csv'
      a.click()
      URL.revokeObjectURL(url)
      setBatchMessage(`Exported ${ids.length} invoice(s) as CSV.`)
      clearSelection()
    } catch {
      setBatchMessage('Failed to export CSV.')
    } finally {
      setBatchLoading(false)
    }
  }

  /* --- Clear filters --- */
  const hasFilters = searchQuery || statusFilter || dateFrom || dateTo
  const clearFilters = () => {
    setSearchQuery('')
    setStatusFilter('')
    setDateFrom('')
    setDateTo('')
    setPage(1)
  }

  /* --- Render --- */
  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Invoices</h1>
        <Button onClick={() => { window.location.href = '/invoices/new' }}>
          + New Invoice
        </Button>
      </div>

      {/* Search & Filters */}
      <div className="mb-4 space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Input
            label="Search"
            placeholder="Invoice #, rego, customer name, phone, email…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Search invoices"
          />
          <Select
            label="Status"
            options={STATUS_OPTIONS}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          />
          <Input
            label="From date"
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
          <Input
            label="To date"
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </div>

        {hasFilters && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-500">
              {data ? `${data.total} result${data.total !== 1 ? 's' : ''}` : 'Filtering…'}
            </span>
            <button
              onClick={clearFilters}
              className="text-sm text-blue-600 hover:text-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
            >
              Clear filters
            </button>
          </div>
        )}
      </div>

      {/* Batch actions bar */}
      {hasSelection && (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3">
          <span className="text-sm font-medium text-blue-800">
            {selectedIds.size} selected
          </span>
          <div className="flex flex-wrap gap-2 ml-auto">
            <Button size="sm" variant="primary" onClick={handleBatchMarkPaid} loading={batchLoading}>
              Mark as Paid
            </Button>
            <Button size="sm" variant="secondary" onClick={handleBatchSendReminders} loading={batchLoading}>
              Send Reminders
            </Button>
            <Button size="sm" variant="secondary" onClick={handleBatchExportPDF} loading={batchLoading}>
              Export PDF ZIP
            </Button>
            <Button size="sm" variant="secondary" onClick={handleBatchExportCSV} loading={batchLoading}>
              Export CSV
            </Button>
            <Button size="sm" variant="secondary" onClick={clearSelection}>
              Deselect All
            </Button>
          </div>
        </div>
      )}

      {/* Batch result message */}
      {batchMessage && (
        <div className="mb-4 rounded-md border border-gray-200 bg-gray-50 px-4 py-2 text-sm text-gray-700" role="status">
          {batchMessage}
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {/* Loading state */}
      {loading && !data && (
        <div className="py-16">
          <Spinner label="Loading invoices" />
        </div>
      )}

      {/* Invoice table */}
      {data && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Invoice list</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="w-10 px-4 py-3">
                    <label className="sr-only">Select all invoices</label>
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleSelectAll}
                      className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                      aria-label="Select all invoices"
                    />
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    Invoice #
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    Customer
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    Rego
                  </th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                    Total
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    Date
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {data.items.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-sm text-gray-500">
                      {hasFilters ? 'No invoices match your filters.' : 'No invoices yet. Create your first invoice to get started.'}
                    </td>
                  </tr>
                ) : (
                  data.items.map((inv) => {
                    const cfg = STATUS_CONFIG[inv.status] ?? STATUS_CONFIG.draft
                    const isSelected = selectedIds.has(inv.id)
                    return (
                      <tr
                        key={inv.id}
                        className={`hover:bg-gray-50 cursor-pointer ${isSelected ? 'bg-blue-50' : ''}`}
                        onClick={() => { window.location.href = `/invoices/${inv.id}` }}
                      >
                        <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelect(inv.id)}
                            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                            aria-label={`Select invoice ${inv.invoice_number || 'draft'}`}
                          />
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-blue-600">
                          {inv.invoice_number || <span className="text-gray-400 italic">Draft</span>}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">
                          {inv.customer_name}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700 font-mono">
                          {inv.rego || '—'}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums">
                          {formatNZD(inv.total)}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm">
                          <Badge variant={cfg.variant}>{cfg.label}</Badge>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                          {formatDate(inv.issue_date ?? inv.created_at)}
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {data.total_pages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <p className="text-sm text-gray-500">
                Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, data.total)} of {data.total}
              </p>
              <Pagination
                currentPage={page}
                totalPages={data.total_pages}
                onPageChange={setPage}
              />
            </div>
          )}
        </>
      )}
    </div>
  )
}
