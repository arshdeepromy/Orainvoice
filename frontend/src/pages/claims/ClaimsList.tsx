/**
 * Claims List page — paginated table with filters.
 *
 * Requirements: 6.1-6.4
 */

import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge, Spinner, Pagination, Button } from '../../components/ui'
import { useClaimsList, type ClaimFilters } from '../../hooks/useClaims'

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

const STATUS_CONFIG: Record<string, { label: string; variant: BadgeVariant }> = {
  open: { label: 'Open', variant: 'info' },
  investigating: { label: 'Investigating', variant: 'warning' },
  approved: { label: 'Approved', variant: 'success' },
  rejected: { label: 'Rejected', variant: 'error' },
  resolved: { label: 'Resolved', variant: 'neutral' },
}

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'open', label: 'Open' },
  { value: 'investigating', label: 'Investigating' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'resolved', label: 'Resolved' },
]

const TYPE_OPTIONS = [
  { value: '', label: 'All Types' },
  { value: 'warranty', label: 'Warranty' },
  { value: 'defect', label: 'Defect' },
  { value: 'service_redo', label: 'Service Redo' },
  { value: 'exchange', label: 'Exchange' },
  { value: 'refund_request', label: 'Refund Request' },
]

const PAGE_SIZE = 25

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(dateStr))
}

function formatCost(amount: number | string | null | undefined): string {
  const num = Number(amount ?? 0)
  if (isNaN(num)) return '$0.00'
  return `$${num.toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatClaimType(type: string): string {
  return type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ClaimsList() {
  const navigate = useNavigate()

  /* Filter state */
  const [statusFilter, setStatusFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [search, setSearch] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(1)

  const filters: ClaimFilters = useMemo(() => ({
    status: statusFilter || undefined,
    claim_type: typeFilter || undefined,
    search: search.trim() || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  }), [statusFilter, typeFilter, search, dateFrom, dateTo])

  const offset = (page - 1) * PAGE_SIZE
  const { data, loading, error } = useClaimsList(filters, PAGE_SIZE, offset)

  const totalPages = Math.ceil((data?.total ?? 0) / PAGE_SIZE)

  const handlePageChange = (newPage: number) => {
    setPage(newPage)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Claims</h1>
        <Button onClick={() => navigate('/claims/new')} size="sm">
          + New Claim
        </Button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex-1 min-w-[200px]">
          <label htmlFor="claims-search" className="block text-xs font-medium text-gray-600 mb-1">Search</label>
          <input
            id="claims-search"
            type="text"
            placeholder="Customer, invoice, description…"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
            className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none"
          />
        </div>
        <div>
          <label htmlFor="claims-status" className="block text-xs font-medium text-gray-600 mb-1">Status</label>
          <select
            id="claims-status"
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(1) }}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none"
          >
            {STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="claims-type" className="block text-xs font-medium text-gray-600 mb-1">Type</label>
          <select
            id="claims-type"
            value={typeFilter}
            onChange={e => { setTypeFilter(e.target.value); setPage(1) }}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none"
          >
            {TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="claims-date-from" className="block text-xs font-medium text-gray-600 mb-1">From</label>
          <input
            id="claims-date-from"
            type="date"
            value={dateFrom}
            onChange={e => { setDateFrom(e.target.value); setPage(1) }}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none"
          />
        </div>
        <div>
          <label htmlFor="claims-date-to" className="block text-xs font-medium text-gray-600 mb-1">To</label>
          <input
            id="claims-date-to"
            type="date"
            value={dateTo}
            onChange={e => { setDateTo(e.target.value); setPage(1) }}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none"
          />
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        {loading && !data && (
          <div className="flex items-center justify-center py-16">
            <Spinner label="Loading claims" />
          </div>
        )}

        {error && (
          <div className="px-4 py-8 text-center text-sm text-red-600">{error}</div>
        )}

        {data && (data.items ?? []).length === 0 && !loading && (
          <div className="px-4 py-12 text-center text-sm text-gray-500">
            {search || statusFilter || typeFilter || dateFrom || dateTo
              ? 'No claims match your filters.'
              : 'No claims yet. Create your first claim to get started.'}
          </div>
        )}

        {data && (data.items ?? []).length > 0 && (
          <table className="w-full text-sm" role="table">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3">Customer</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3 text-right">Cost</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(data.items ?? []).map(claim => {
                const cfg = STATUS_CONFIG[claim.status] ?? { label: claim.status, variant: 'neutral' as BadgeVariant }
                return (
                  <tr
                    key={claim.id}
                    onClick={() => navigate(`/claims/${claim.id}`)}
                    className="cursor-pointer hover:bg-gray-50 transition-colors"
                    role="row"
                    tabIndex={0}
                    onKeyDown={e => { if (e.key === 'Enter') navigate(`/claims/${claim.id}`) }}
                  >
                    <td className="px-4 py-3 font-mono text-xs text-gray-500">
                      {claim.id.slice(0, 8)}…
                    </td>
                    <td className="px-4 py-3 font-medium text-gray-900">
                      {claim.customer_name ?? '—'}
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      {formatClaimType(claim.claim_type)}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={cfg.variant}>{cfg.label}</Badge>
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {formatDate(claim.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-700">
                      {formatCost(claim.cost_to_business)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-gray-500">
            Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, data?.total ?? 0)} of {(data?.total ?? 0).toLocaleString()} claims
          </p>
          <Pagination currentPage={page} totalPages={totalPages} onPageChange={handlePageChange} />
        </div>
      )}
    </div>
  )
}
