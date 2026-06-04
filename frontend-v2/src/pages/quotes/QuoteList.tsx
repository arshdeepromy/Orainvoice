/**
 * QuoteList — Task 21 port of frontend/src/pages/quotes/QuoteList.tsx.
 *
 * Split-panel quote list view matching the InvoiceList layout:
 *   Left sidebar  — scrollable list of quotes with status filter + search.
 *   Right panel   — QuoteDetail or QuoteCreate.
 *
 * ALL logic is copied VERBATIM from the original (fetch with offset/limit +
 * search/status params, debounced search, AbortController cleanup, auto-select
 * first quote, delete with confirm modal, expiry labels/colours, pagination).
 * The presentation is reframed onto the design-system tokens (canvas/card/
 * border/accent/muted) exactly as Task 19 did for InvoiceList, and `.mono` is
 * applied to quote numbers / amounts / dates per FR-2 / FR-2b. The original
 * STATUS_COLOR Tailwind text colours are mapped onto the matching status tokens.
 */

import { useEffect, useState, useCallback, useRef, lazy, Suspense } from 'react'
import { useNavigate, useLocation, useParams } from 'react-router-dom'
import apiClient from '@/api/client'
import { Spinner } from '@/components/ui'
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

/* Status → design-system text-colour token (mapped from the original
   STATUS_COLOR Tailwind classes onto ds.css status tokens). */
const STATUS_COLOR: Record<string, string> = {
  draft: 'text-muted-2',
  issued: 'text-accent',
  sent: 'text-accent',
  accepted: 'text-ok',
  declined: 'text-danger',
  expired: 'text-muted-2',
  converted: 'text-ok',
  invoiced: 'text-ok',
  cancelled: 'text-danger',
}

const STATUS_OPTIONS = [
  { value: '', label: 'All Quotes' },
  { value: 'draft', label: 'Draft' },
  { value: 'issued', label: 'Issued' },
  { value: 'sent', label: 'Sent' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'declined', label: 'Declined' },
  { value: 'expired', label: 'Expired' },
  { value: 'converted', label: 'Converted' },
  { value: 'cancelled', label: 'Cancelled' },
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
  if (!validUntil || ['expired', 'declined', 'converted', 'accepted'].includes(status)) return 'text-muted-2'
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  const expiry = new Date(validUntil)
  expiry.setHours(0, 0, 0, 0)
  const days = Math.ceil((expiry.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))
  if (days < 0) return 'text-danger'
  if (days <= 3) return 'text-warn'
  if (days <= 7) return 'text-warn'
  return 'text-muted'
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
  }, [routeId]) // eslint-disable-line react-hooks/exhaustive-deps

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
    <div className="flex h-full overflow-hidden bg-canvas" data-testid="quote-list">
      {/* ============================================================ */}
      {/*  LEFT SIDEBAR — Quote List                                    */}
      {/* ============================================================ */}
      <div className="w-80 min-w-[320px] flex flex-col border-r border-border bg-card" data-print-hide>
        {/* Sidebar header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="text-sm font-semibold text-text bg-transparent border-none focus:ring-0 cursor-pointer pr-6 -ml-1"
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
              className="flex items-center gap-1 rounded-ctl bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-press transition-colors"
              aria-label="Create new quote"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              New
            </button>
            <button
              className="p-1.5 rounded text-muted-2 hover:text-text hover:bg-canvas transition-colors"
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
        <div className="px-3 py-2 border-b border-border">
          <div className="flex items-center gap-2 border border-border rounded-ctl bg-canvas px-2.5 focus-within:bg-card focus-within:border-accent focus-within:ring-1 focus-within:ring-accent transition-colors">
            <svg className="w-4 h-4 text-muted-2 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
            <input
              type="text"
              placeholder="Search in Quotes ( / )"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full py-1.5 text-sm bg-transparent outline-none placeholder:text-muted-2"
              aria-label="Search quotes"
            />
          </div>
        </div>

        {/* Quote list */}
        <div className="flex-1 overflow-y-auto">
          {listLoading && quotes.length === 0 && (
            <div className="flex items-center justify-center py-12">
              <Spinner label="Loading quotes" />
            </div>
          )}
          {listError && (
            <div className="px-4 py-3 text-sm text-danger">{listError}</div>
          )}
          {!listLoading && quotes.length === 0 && !listError && (
            <div className="px-4 py-12 text-center text-sm text-muted">
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
                className={`w-full text-left px-4 py-3 border-b border-border transition-colors ${
                  isActive
                    ? 'bg-accent-soft border-l-[3px] border-l-accent'
                    : 'hover:bg-canvas border-l-[3px] border-l-transparent'
                }`}
                aria-current={isActive ? 'true' : undefined}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className={`text-sm font-medium truncate ${isActive ? 'text-accent' : 'text-text'}`}>
                      {q.customer_name || 'No customer'}
                    </p>
                    <p className="text-xs text-muted mt-0.5 mono">
                      {q.quote_number || 'Draft'} · {formatDate(q.created_at)}
                    </p>
                    {q.branch_id && (() => {
                      const branch = (branchList ?? []).find(b => b.id === q.branch_id)
                      return branch ? (
                        <p className="text-[10px] text-muted-2 mt-0.5 truncate">{branch.name}</p>
                      ) : null
                    })()}
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <p className="text-sm font-semibold mono text-text">
                      {formatNZD(q.total)}
                    </p>
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={(e) => { e.stopPropagation(); setDeleteTargetId(q.id) }}
                      onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); setDeleteTargetId(q.id) } }}
                      className="p-1 rounded text-muted-2 hover:text-danger hover:bg-danger-soft transition-colors"
                      title="Delete quote"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                      </svg>
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-2 mt-1.5">
                  <span className={`text-[10px] font-bold uppercase tracking-wider ${STATUS_COLOR[q.status] ?? 'text-muted-2'}`}>
                    {q.status.toUpperCase()}
                  </span>
                  {expLabel && (
                    <span className={`text-[10px] font-medium ${expColor}`}>
                      ⏱ {expLabel}
                    </span>
                  )}
                  {(q.attachment_count ?? 0) > 0 && (
                    <span className="text-muted-2 text-xs">📎 {q.attachment_count}</span>
                  )}
                </div>
              </button>
            )
          })}
        </div>

        {/* Pagination footer */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-2 border-t border-border text-xs text-muted">
            <span><span className="mono">{total}</span> quote{total !== 1 ? 's' : ''}</span>
            <div className="flex items-center gap-1">
              <button
                disabled={page <= 1}
                onClick={() => setPage(p => Math.max(1, p - 1))}
                className="px-2 py-1 rounded hover:bg-canvas disabled:opacity-30 disabled:cursor-not-allowed"
              >
                ‹
              </button>
              <span className="mono">{page}/{totalPages}</span>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage(p => p + 1)}
                className="px-2 py-1 rounded hover:bg-canvas disabled:opacity-30 disabled:cursor-not-allowed"
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
          <div className="flex-1 flex items-center justify-center text-muted-2">
            <div className="text-center">
              <svg className="w-16 h-16 mx-auto mb-4 text-border-strong" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40">
          <div className="bg-card rounded-card shadow-pop p-6 max-w-sm w-full mx-4">
            <h3 className="text-sm font-semibold text-text mb-2">Delete Quote</h3>
            <p className="text-sm text-muted mb-4">Are you sure you want to delete this quote? This cannot be undone.</p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDeleteTargetId(null)}
                className="rounded-ctl border border-border px-3 py-1.5 text-sm font-medium text-text hover:bg-canvas"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDelete(deleteTargetId)}
                disabled={deleting}
                className="rounded-ctl bg-danger px-3 py-1.5 text-sm font-medium text-white hover:brightness-95 disabled:opacity-50"
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
