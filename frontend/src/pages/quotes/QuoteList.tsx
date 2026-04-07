/**
 * Quote list view with search, status filter, actions, and expiry column.
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Input, Select, Spinner, Pagination, PageSizeSelect } from '../../components/ui'
import { useBranch } from '@/contexts/BranchContext'

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
}

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

const DEFAULT_PAGE_SIZE = 10

function formatNZD(amount: number | string | null | undefined): string {
  if (amount == null || isNaN(Number(amount))) return 'NZD 0.00'
  return `NZD ${Number(amount).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(dateStr))
}

function expiresInLabel(validUntil: string | null | undefined, status: string): string {
  if (!validUntil) return '—'
  if (['expired', 'declined', 'converted', 'accepted'].includes(status)) return '—'
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

export default function QuoteList() {
  const navigate = useNavigate()
  const { branches: branchList, selectedBranchId } = useBranch()
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [quotes, setQuotes] = useState<Quote[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  const debounceRef = useRef<ReturnType<typeof setTimeout>>()
  const abortRef = useRef<AbortController>()

  const fetchQuotes = useCallback(async (search: string, status: string, pg: number) => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError('')
    try {
      const params: Record<string, string | number> = {
        limit: pageSize,
        offset: (pg - 1) * pageSize,
      }
      if (search.trim()) params.search = search.trim()
      if (status) params.status = status

      const res = await apiClient.get('/quotes', { params, signal: controller.signal })
      const data = res.data as any
      setQuotes(data?.quotes ?? data?.items ?? [])
      setTotal(data?.total ?? 0)
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setError('Failed to load quotes. Please try again.')
      setQuotes([])
    } finally {
      setLoading(false)
    }
  }, [selectedBranchId])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setPage(1)
      fetchQuotes(searchQuery, statusFilter, 1)
    }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [searchQuery, statusFilter, fetchQuotes])

  useEffect(() => {
    fetchQuotes(searchQuery, statusFilter, page)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, selectedBranchId])

  const handleDelete = async (quoteId: string) => {
    setDeleting(true)
    try {
      await apiClient.delete(`/quotes/${quoteId}`)
      setDeleteConfirm(null)
      fetchQuotes(searchQuery, statusFilter, page)
    } catch (err: unknown) {
      const detail = (err as any)?.response?.data?.detail
      setError(detail || 'Failed to delete quote')
      setDeleteConfirm(null)
    } finally {
      setDeleting(false)
    }
  }

  const handleRequote = async (e: React.MouseEvent, quoteId: string) => {
    e.stopPropagation()
    // Revert sent quote to draft, then navigate to edit
    try {
      await apiClient.put(`/quotes/${quoteId}`, { status: 'draft' })
      navigate(`/quotes/${quoteId}/edit`)
    } catch (err: unknown) {
      const detail = (err as any)?.response?.data?.detail
      setError(detail || 'Failed to requote')
    }
  }

  const totalPages = Math.ceil(total / pageSize) || 1
  const hasFilters = searchQuery || statusFilter
  const clearFilters = () => { setSearchQuery(''); setStatusFilter(''); setPage(1) }
  const canDelete = (status: string) => ['draft', 'declined', 'expired'].includes(status)
  const canRequote = (status: string) => status === 'sent'
  const canEdit = (status: string) => status === 'draft'

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">All Quotes</h1>
        <Button onClick={() => navigate('/quotes/new')}>+ New</Button>
      </div>

      {/* Search & Filters */}
      <div className="mb-4 space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Input
            label="Search"
            placeholder="Quote number, customer, rego…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Search quotes"
          />
          <Select
            label="Status"
            options={STATUS_OPTIONS}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          />
        </div>
        {hasFilters && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-500">
              {total} result{total !== 1 ? 's' : ''}
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

      {/* Error */}
      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
          <button onClick={() => setError('')} className="ml-2 text-red-500 hover:text-red-700">✕</button>
        </div>
      )}

      {/* Delete confirmation */}
      {deleteConfirm && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 flex items-center justify-between">
          <span>Are you sure you want to delete this quote? This cannot be undone.</span>
          <div className="flex items-center gap-2 ml-4">
            <button
              onClick={() => handleDelete(deleteConfirm)}
              disabled={deleting}
              className="rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
            >
              {deleting ? 'Deleting…' : 'Delete'}
            </button>
            <button
              onClick={() => setDeleteConfirm(null)}
              className="rounded bg-gray-200 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-300"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Loading */}
      {loading && quotes.length === 0 && (
        <div className="py-16">
          <Spinner label="Loading quotes" />
        </div>
      )}

      {/* Table */}
      {(!loading || quotes.length > 0) && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Quotes list</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Quote Number</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Customer Name</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Branch</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                  <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Expires In</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Amount</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {quotes.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-sm text-gray-500">
                      {hasFilters ? 'No quotes match your filters.' : 'No quotes yet. Create your first quote to get started.'}
                    </td>
                  </tr>
                ) : (
                  quotes.map((q) => (
                    <tr
                      key={q.id}
                      className="hover:bg-gray-50 cursor-pointer"
                      onClick={() => navigate(`/quotes/${q.id}`)}
                    >
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                        {formatDate(q.created_at)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-blue-600 hover:text-blue-800">
                        {q.quote_number}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">
                        {q.customer_name || '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                        {q.branch_id ? ((branchList ?? []).find(b => b.id === q.branch_id)?.name ?? '—') : '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <span className={`font-medium uppercase text-xs ${STATUS_COLOR[q.status] ?? 'text-gray-500'}`}>
                          {q.status.toUpperCase()}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                        <span className={`text-xs font-medium ${expiresInColor(q.valid_until, q.status)}`}>
                          {expiresInLabel(q.valid_until, q.status)}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right font-medium">
                        {formatNZD(q.total)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                        <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                          {canEdit(q.status) && (
                            <button
                              onClick={() => navigate(`/quotes/${q.id}/edit`)}
                              className="rounded px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50"
                              title="Edit quote"
                            >
                              Edit
                            </button>
                          )}
                          {canRequote(q.status) && (
                            <button
                              onClick={(e) => handleRequote(e, q.id)}
                              className="rounded px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50"
                              title="Revert to draft and edit"
                            >
                              Requote
                            </button>
                          )}
                          {canDelete(q.status) && (
                            <button
                              onClick={() => setDeleteConfirm(q.id)}
                              className="rounded px-2 py-1 text-xs font-medium text-red-500 hover:bg-red-50"
                              title="Delete quote"
                            >
                              Delete
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <p className="text-sm text-gray-500">
                Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total}
              </p>
              <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
            </div>
          )}
          <div className="mt-3 flex justify-end">
            <PageSizeSelect value={pageSize} onChange={(size) => { setPageSize(size); setPage(1) }} />
          </div>
        </>
      )}
    </div>
  )
}
