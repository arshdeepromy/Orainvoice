/**
 * Split-panel quote list view matching the InvoiceList layout.
 * Left sidebar: scrollable list of quotes with search/filter.
 * Right panel: QuoteDetail or QuoteCreate.
 */

import { useEffect, useState, useCallback, useRef, lazy, Suspense } from 'react'
import { useNavigate, useLocation, useParams } from 'react-router-dom'
import apiClient from '@/api/client'
import { Spinner } from '../../components/ui'
import { useBranch } from '@/contexts/BranchContext'
import QuoteDetail from './QuoteDetail'

const QuoteCreate = lazy(() => import('./QuoteCreate'))

/* ------------------------------------------------------------------ */
/*  Types & Constants                                                   */
/* ------------------------------------------------------------------ */

interface Quote {
  id: string
  quote_number: string
  customer_name: string | null
  vehicle_rego: string | null
  status: string
  total: string | number
  valid_until: string | null
  created_at: string | null
  branch_id?: string | null
  attachment_count?: number
}

const PAGE_SIZE = 20

const STATUS_COLOR: Record<string, string> = {
  draft: 'text-gray-500',
  sent: 'text-blue-600',
  accepted: 'text-emerald-600',
  declined: 'text-red-500',
  expired: 'text-gray-400',
  converted: 'text-emerald-600',
  invoiced: 'text-emerald-600',
}

const STATUS_OPTIONS = [
  { value: '', label: 'All Quotes' },
  { value: 'draft', label: 'Draft' },
  { value: 'sent', label: 'Sent' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'declined', label: 'Declined' },
  { value: 'expired', label: 'Expired' },
  { value: 'converted', label: 'Converted' },
]

/* ------------------------------------------------------------------ */
/*  Helpers                                                             */
/* ------------------------------------------------------------------ */

function formatNZD(amount: number | string | null | undefined): string {
  if (amount == null || isNaN(Number(amount))) return 'NZD 0.00'
  return `NZD ${Number(amount).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(dateStr))
}

function expiresInLabel(validUntil: string | null | undefined, status: string): string {
  if (!validUntil) return ''
  if (['expired', 'declined', 'converted', 'accepted'].includes(status)) return ''
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  const expiry = new Date(validUntil)
  expiry.setHours(0, 0, 0, 0)
  const diffMs = expiry.getTime() - now.getTime()
  const days = Math.ceil(diffMs / (1000 * 60 * 60 * 24))
  if (days < 0) return 'Expired'
  if (days === 0) return 'Today'
  if (days === 1) return '1 day'
  return `${days} days`
}

function expiresInColor(validUntil: string | null | undefined, status: string): string {
  if (!validUntil || ['expired', 'declined', 'converted', 'accepted'].includes(status)) return 'text-gray-400'
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  const expiry = new Date(validUntil)
  expiry.setHours(0, 0, 0, 0)
  const days = Math.ceil((expiry.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))
  if (days < 0) return 'text-red-500'
  if (days <= 3) return 'text-orange-500'
  if (days <= 7) return 'text-yellow-600'
  return 'text-gray-600'
}

/* ------------------------------------------------------------------ */
/*  Component                                                           */
/* ------------------------------------------------------------------ */

export default function QuoteList() {
  const navigate = useNavigate()
  const location = useLocation()
  const { id: routeId } = useParams<{ id: string }>()
  const isCreating = location.pathname === '/quotes/new'
  const { branches: branchList, selectedBranchId } = useBranch()

  /* --- List state --- */
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(1)
  const [quotes, setQuotes] = useState<Quote[]>([])
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState('')

  /* --- Detail state --- */
  const [selectedId, setSelectedId] = useState<string | null>(routeId || null)

  /* --- Delete state --- */
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const abortRef = useRef<AbortController>(undefined)

  // Sync selectedId when route param changes
  useEffect(() => {
    if (routeId && routeId !== selectedId) {
      setSelectedId(routeId)
    }
  }, [routeId])

  /* --- Fetch quote list --- */
  const fetchQuotes = useCallback(async (search: string, status: string, pg: number) => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setListLoading(true)
    setListError('')
    try {
      const params: Record<string, string | number> = {
        limit: PAGE_SIZE,
        offset: (pg - 1) * PAGE_SIZE,
      }
      if (search.trim()) params.search = search.trim()
      if (status) params.status = status

      const res = await apiClient.get('/quotes', { params, signal: controller.signal })
      const data = res.data as Record<string, unknown> | undefined
      const items = (data?.quotes ?? data?.items ?? []) as Quote[]
      const totalCount = (data?.total ?? 0) as number
      setQuotes(items)
      setTotal(totalCount)
      setTotalPages(Math.ceil(totalCount / PAGE_SIZE) || 1)

      // Auto-select first quote if none selected and not creating
      if (!selectedId && !isCreating && items.length > 0) {
        setSelectedId(items[0].id)
        navigate(`/quotes/${items[0].id}`, { replace: true })
      }
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setListError('Failed to load quotes.')
      setQuotes([])
    } finally {
      setListLoading(false)
    }
  }, [selectedId, isCreating, navigate, selectedBranchId])

  // Debounced search/filter
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setPage(1)
      fetchQuotes(searchQuery, statusFilter, 1)
    }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [searchQuery, statusFilter, fetchQuotes])

  // Page change
  useEffect(() => {
    fetchQuotes(searchQuery, statusFilter, page)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, selectedBranchId])

  // Cleanup abort on unmount
  useEffect(() => {
    return () => { if (abortRef.current) abortRef.current.abort() }
  }, [])

  /* --- Delete handler --- */
  const handleDelete = async (quoteId: string) => {
    setDeleting(true)
    try {
      await apiClient.delete(`/quotes/${quoteId}`)
      setDeleteTargetId(null)
      // If we deleted the selected quote, clear selection
      if (selectedId === quoteId) {
        setSelectedId(null)
        navigate('/quotes', { replace: true })
      }
      fetchQuotes(searchQuery, statusFilter, page)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setListError(detail || 'Failed to delete quote')
      setDeleteTargetId(null)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="flex h-full overflow-hidden bg-gray-50 -m-4 lg:-m-6">
      {/* ============================================================ */}
      {/*  LEFT SIDEBAR — Quote List                                    */}
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
              onClick={() => navigate('/quotes/new')}
              className="flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 transition-colors"
              aria-label="Create new quote"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              New
            </button>
            <button
              className="p-1.5 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              onClick={() => fetchQuotes(searchQuery, statusFilter, page)}
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
              placeholder="Search quotes…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full py-1.5 text-sm bg-transparent outline-none placeholder:text-gray-400"
              aria-label="Search quotes"
            />
          </div>
        </div>

        {/* Quote list */}
        <div className="flex-1 overflow-y-auto">
          {listLoading && quotes.length === 0 && (
            <div className="flex items-center justify-center py-12">
              <Spinner label="Loading" />
            </div>
          )}
          {listError && (
            <div className="px-4 py-3 text-sm text-red-600">{listError}</div>
          )}
          {!listLoading && quotes.length === 0 && !listError && (
            <div className="px-4 py-12 text-center text-sm text-gray-500">
              {searchQuery || statusFilter ? 'No quotes match.' : 'No quotes yet.'}
            </div>
          )}
          {quotes.map((q) => {
            const isActive = q.id === selectedId
            const expLabel = expiresInLabel(q.valid_until, q.status)
            const expColor = expiresInColor(q.valid_until, q.status)
            return (
              <button
                key={q.id}
                onClick={() => {
                  setSelectedId(q.id)
                  navigate(`/quotes/${q.id}`, { replace: true })
                }}
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
                      {q.customer_name || 'No customer'}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {q.quote_number || 'Draft'} · {formatDate(q.created_at)}
                    </p>
                    {q.branch_id && (() => {
                      const branch = (branchList ?? []).find(b => b.id === q.branch_id)
                      return branch ? (
                        <p className="text-[10px] text-gray-400 mt-0.5 truncate">{branch.name}</p>
                      ) : null
                    })()}
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <p className="text-sm font-semibold tabular-nums text-gray-900">
                      {formatNZD(q.total)}
                    </p>
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={(e) => { e.stopPropagation(); setDeleteTargetId(q.id) }}
                      onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); setDeleteTargetId(q.id) } }}
                      className="p-1 rounded text-gray-300 hover:text-red-500 hover:bg-red-50 transition-colors"
                      title="Delete quote"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                      </svg>
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-2 mt-1.5">
                  <span className={`text-[10px] font-bold uppercase tracking-wider ${STATUS_COLOR[q.status] ?? 'text-gray-500'}`}>
                    {q.status.toUpperCase()}
                  </span>
                  {expLabel && (
                    <span className={`text-[10px] font-medium ${expColor}`}>
                      ⏱ {expLabel}
                    </span>
                  )}
                  {(q.attachment_count ?? 0) > 0 && (
                    <span className="text-gray-400 text-xs">📎 {q.attachment_count}</span>
                  )}
                </div>
              </button>
            )
          })}
        </div>

        {/* Pagination footer */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-2 border-t border-gray-100 text-xs text-gray-500">
            <span>{total} quote{total !== 1 ? 's' : ''}</span>
            <div className="flex items-center gap-1">
              <button
                disabled={page <= 1}
                onClick={() => setPage(p => Math.max(1, p - 1))}
                className="px-2 py-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                ‹
              </button>
              <span>{page}/{totalPages}</span>
              <button
                disabled={page >= totalPages}
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
      {/*  RIGHT PANEL — Quote Detail or Create                         */}
      {/* ============================================================ */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {isCreating && (
          <div className="flex-1 overflow-y-auto">
            <Suspense fallback={<div className="flex items-center justify-center py-12"><Spinner label="Loading" /></div>}>
              <QuoteCreate />
            </Suspense>
          </div>
        )}

        {!isCreating && !selectedId && (
          <div className="flex-1 flex items-center justify-center text-gray-400">
            <div className="text-center">
              <svg className="w-16 h-16 mx-auto mb-4 text-gray-200" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
              </svg>
              <p className="text-sm">Select a quote to view details</p>
            </div>
          </div>
        )}

        {!isCreating && selectedId && (
          <div className="flex-1 overflow-y-auto">
            <QuoteDetail key={selectedId} quoteId={selectedId} />
          </div>
        )}
      </div>

      {/* Delete confirmation modal */}
      {deleteTargetId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-sm w-full mx-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-2">Delete Quote</h3>
            <p className="text-sm text-gray-600 mb-4">Are you sure you want to delete this quote? This cannot be undone.</p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDeleteTargetId(null)}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDelete(deleteTargetId)}
                disabled={deleting}
                className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
