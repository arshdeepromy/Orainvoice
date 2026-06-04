/**
 * Claims List page — paginated table with filters.
 *
 * Requirements: 6.1-6.4
 */

import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge, Spinner, Pagination, Button } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { useClaimsList, type ClaimFilters } from '@/hooks/useClaims'

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const STATUS_CONFIG: Record<string, { label: string; variant: BadgeVariant }> = {
  open: { label: 'Open', variant: 'info' },
  investigating: { label: 'Investigating', variant: 'warn' },
  approved: { label: 'Approved', variant: 'success' },
  rejected: { label: 'Rejected', variant: 'danger' },
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
  return `${num.toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatClaimType(type: string): string {
  return type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

const fieldClass =
  'rounded-ctl border border-border bg-card px-3 py-1.5 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent'

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
    <div className="space-y-4 px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-text">Claims</h1>
        <Button onClick={() => navigate('/claims/new')} size="sm">
          + New Claim
        </Button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3 rounded-card border border-border bg-card p-4 shadow-card">
        <div className="min-w-[200px] flex-1">
          <label htmlFor="claims-search" className="mb-1 block text-xs font-medium text-muted">Search</label>
          <input
            id="claims-search"
            type="text"
            placeholder="Customer, invoice, description…"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
            className={`w-full ${fieldClass}`}
          />
        </div>
        <div>
          <label htmlFor="claims-status" className="mb-1 block text-xs font-medium text-muted">Status</label>
          <select
            id="claims-status"
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(1) }}
            className={fieldClass}
          >
            {STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="claims-type" className="mb-1 block text-xs font-medium text-muted">Type</label>
          <select
            id="claims-type"
            value={typeFilter}
            onChange={e => { setTypeFilter(e.target.value); setPage(1) }}
            className={fieldClass}
          >
            {TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="claims-date-from" className="mb-1 block text-xs font-medium text-muted">From</label>
          <input
            id="claims-date-from"
            type="date"
            value={dateFrom}
            onChange={e => { setDateFrom(e.target.value); setPage(1) }}
            className={fieldClass}
          />
        </div>
        <div>
          <label htmlFor="claims-date-to" className="mb-1 block text-xs font-medium text-muted">To</label>
          <input
            id="claims-date-to"
            type="date"
            value={dateTo}
            onChange={e => { setDateTo(e.target.value); setPage(1) }}
            className={fieldClass}
          />
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto overflow-hidden rounded-card border border-border bg-card shadow-card">
        {loading && !data && (
          <div className="flex items-center justify-center py-16">
            <Spinner label="Loading claims" />
          </div>
        )}

        {error && (
          <div className="px-4 py-8 text-center text-sm text-danger">{error}</div>
        )}

        {data && (data.items ?? []).length === 0 && !loading && (
          <div className="px-4 py-12 text-center text-sm text-muted">
            {search || statusFilter || typeFilter || dateFrom || dateTo
              ? 'No claims match your filters.'
              : 'No claims yet. Create your first claim to get started.'}
          </div>
        )}

        {data && (data.items ?? []).length > 0 && (
          <table className="w-full text-sm" role="table">
            <thead>
              <tr>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Ref</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Customer</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Type</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Created</th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Cost</th>
              </tr>
            </thead>
            <tbody>
              {(data.items ?? []).map(claim => {
                const cfg = STATUS_CONFIG[claim.status] ?? { label: claim.status, variant: 'neutral' as BadgeVariant }
                return (
                  <tr
                    key={claim.id}
                    onClick={() => navigate(`/claims/${claim.id}`)}
                    className="cursor-pointer border-b border-border transition-colors last:border-b-0 hover:bg-canvas"
                    role="row"
                    tabIndex={0}
                    onKeyDown={e => { if (e.key === 'Enter') navigate(`/claims/${claim.id}`) }}
                  >
                    <td className="mono px-4 py-3 text-xs text-muted">
                      {claim.claim_number ?? `CLM-${claim.id.slice(0, 6).toUpperCase()}`}
                    </td>
                    <td className="px-4 py-3 font-medium text-text">
                      {claim.customer_name ?? '—'}
                    </td>
                    <td className="px-4 py-3 text-muted">
                      {formatClaimType(claim.claim_type)}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={cfg.variant}>{cfg.label}</Badge>
                    </td>
                    <td className="mono px-4 py-3 text-muted">
                      {formatDate(claim.created_at)}
                    </td>
                    <td className="mono px-4 py-3 text-right text-text">
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
          <p className="text-sm text-muted">
            Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, data?.total ?? 0)} of {(data?.total ?? 0).toLocaleString()} claims
          </p>
          <Pagination currentPage={page} totalPages={totalPages} onPageChange={handlePageChange} />
        </div>
      )}
    </div>
  )
}
