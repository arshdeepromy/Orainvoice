import { useState, useEffect, useRef, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Badge, Spinner, Pagination } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type JobCardStatus = 'open' | 'in_progress' | 'completed' | 'invoiced'

interface JobCardSummary {
  id: string
  job_card_number: string | null
  customer_name: string
  customer_id: string
  rego: string
  status: JobCardStatus
  description: string
  created_at: string
  updated_at: string
}

interface JobCardListResponse {
  items: JobCardSummary[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(dateStr))
}

const STATUS_CONFIG: Record<JobCardStatus, { label: string; variant: BadgeVariant }> = {
  open: { label: 'Open', variant: 'info' },
  in_progress: { label: 'In Progress', variant: 'warning' },
  completed: { label: 'Completed', variant: 'success' },
  invoiced: { label: 'Invoiced', variant: 'neutral' },
}

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'open', label: 'Open' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'completed', label: 'Completed' },
  { value: 'invoiced', label: 'Invoiced' },
]

const PAGE_SIZE = 20

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function JobCardList() {
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(1)

  const [data, setData] = useState<JobCardListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const debounceRef = useRef<ReturnType<typeof setTimeout>>()
  const abortRef = useRef<AbortController>()

  const fetchJobCards = useCallback(async (search: string, status: string, pg: number) => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError('')
    try {
      const params: Record<string, string | number> = { page: pg, page_size: PAGE_SIZE }
      if (search.trim()) params.search = search.trim()
      if (status) params.status = status

      const res = await apiClient.get<JobCardListResponse>('/job-cards', {
        params,
        signal: controller.signal,
      })
      setData(res.data)
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setError('Failed to load job cards. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setPage(1)
      fetchJobCards(searchQuery, statusFilter, 1)
    }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [searchQuery, statusFilter, fetchJobCards])

  useEffect(() => {
    fetchJobCards(searchQuery, statusFilter, page)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page])

  const hasFilters = searchQuery || statusFilter
  const clearFilters = () => {
    setSearchQuery('')
    setStatusFilter('')
    setPage(1)
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Job Cards</h1>
        <Button onClick={() => { window.location.href = '/job-cards/new' }}>
          + New Job Card
        </Button>
      </div>

      {/* Search & Filters */}
      <div className="mb-4 space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Input
            label="Search"
            placeholder="Customer name, rego, description…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Search job cards"
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

      {/* Error */}
      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && !data && (
        <div className="py-16">
          <Spinner label="Loading job cards" />
        </div>
      )}

      {/* Table */}
      {data && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Job card list</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Job Card #</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Customer</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Rego</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Description</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {data.items.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-500">
                      {hasFilters ? 'No job cards match your filters.' : 'No job cards yet. Create your first job card to get started.'}
                    </td>
                  </tr>
                ) : (
                  data.items.map((jc) => {
                    const cfg = STATUS_CONFIG[jc.status] ?? STATUS_CONFIG.open
                    return (
                      <tr
                        key={jc.id}
                        className="hover:bg-gray-50 cursor-pointer"
                        onClick={() => { window.location.href = `/job-cards/${jc.id}` }}
                      >
                        <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-blue-600">
                          {jc.job_card_number || <span className="text-gray-400 italic">—</span>}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">{jc.customer_name}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700 font-mono">{jc.rego || '—'}</td>
                        <td className="px-4 py-3 text-sm text-gray-700 max-w-xs truncate">{jc.description || '—'}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm">
                          <Badge variant={cfg.variant}>{cfg.label}</Badge>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{formatDate(jc.created_at)}</td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>

          {data.total_pages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <p className="text-sm text-gray-500">
                Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, data.total)} of {data.total}
              </p>
              <Pagination currentPage={page} totalPages={data.total_pages} onPageChange={setPage} />
            </div>
          )}
        </>
      )}
    </div>
  )
}
