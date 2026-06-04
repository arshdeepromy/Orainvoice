/**
 * BookingList — Task 28 port of frontend/src/pages/bookings/BookingList.tsx.
 *
 * Standalone paginated booking list (status + date filters, cancel action). ALL
 * logic copied VERBATIM: the v2 bookings fetch (GET /api/v2/bookings with
 * skip/limit/status/start_date/end_date), pagination, cancel (PUT
 * /api/v2/bookings/:id/cancel). Presentation remapped onto the design tokens
 * (FR-2b); status pills mapped to ok/warn/danger/neutral. NOTE: the original
 * router does NOT route this page (BookingCalendarPage is the bookings entry);
 * ported for parity and routed at /bookings/list for reachability (FR-2b).
 */

import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'
import { Pagination, PageSizeSelect } from '@/components/ui'
import { useBranch } from '@/contexts/BranchContext'

interface BookingItem {
  id: string
  org_id: string
  customer_name: string
  customer_email: string | null
  customer_phone: string | null
  staff_id: string | null
  service_type: string | null
  start_time: string
  end_time: string
  status: string
  notes: string | null
  created_at: string
  branch_id?: string | null
}

type BadgeVariant = 'info' | 'success' | 'warning' | 'error' | 'neutral'

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'completed', label: 'Completed' },
]

const STATUS_BADGE: Record<string, { label: string; variant: BadgeVariant }> = {
  pending: { label: 'Pending', variant: 'warning' },
  confirmed: { label: 'Confirmed', variant: 'success' },
  cancelled: { label: 'Cancelled', variant: 'error' },
  completed: { label: 'Completed', variant: 'neutral' },
}

/** Map the original badge variants to token-based pill classes. */
const PILL_CLS: Record<BadgeVariant, string> = {
  success: 'bg-ok-soft text-ok',
  warning: 'bg-warn-soft text-warn',
  error: 'bg-danger-soft text-danger',
  neutral: 'bg-[#EEF0F4] text-muted',
  info: 'bg-accent-soft text-accent',
}

function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat('en-NZ', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso))
}

export default function BookingList() {
  const { branches: branchList } = useBranch()
  const [bookings, setBookings] = useState<BookingItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [statusFilter, setStatusFilter] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')

  const fetchBookings = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({
        skip: String((page - 1) * pageSize),
        limit: String(pageSize),
      })
      if (statusFilter) params.set('status', statusFilter)
      if (startDate) params.set('start_date', startDate)
      if (endDate) params.set('end_date', endDate)

      const res = await apiClient.get(`/api/v2/bookings?${params}`)
      setBookings(res.data?.bookings ?? [])
      setTotal(res.data?.total ?? 0)
    } catch {
      setError('Failed to load bookings.')
      setBookings([])
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, statusFilter, startDate, endDate])

  useEffect(() => { fetchBookings() }, [fetchBookings])

  const totalPages = Math.ceil(total / pageSize)

  const handleCancel = async (id: string) => {
    try {
      await apiClient.put(`/api/v2/bookings/${id}/cancel`)
      fetchBookings()
    } catch {
      setError('Failed to cancel booking.')
    }
  }

  const TH = 'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
  const FILTER_CLS = 'h-[42px] rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'

  return (
    <div className="page page-wide">
      <div className="page-head">
        <div>
          <div className="eyebrow">Work</div>
          <h1>Bookings</h1>
        </div>
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap gap-3">
        <select
          aria-label="Status filter"
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
          className={`${FILTER_CLS} appearance-none`}
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <input
          type="date"
          aria-label="Start date"
          value={startDate}
          onChange={(e) => { setStartDate(e.target.value); setPage(1) }}
          className={FILTER_CLS}
        />
        <input
          type="date"
          aria-label="End date"
          value={endDate}
          onChange={(e) => { setEndDate(e.target.value); setPage(1) }}
          className={FILTER_CLS}
        />
      </div>

      {error && (
        <div className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger" role="alert">
          {error}
        </div>
      )}

      {loading && (
        <div className="py-12 text-center text-[13px] text-muted" role="status" aria-label="Loading bookings">
          Loading bookings…
        </div>
      )}

      {!loading && bookings.length === 0 && (
        <div className="py-12 text-center text-[13px] text-muted">
          No bookings found.
        </div>
      )}

      {!loading && bookings.length > 0 && (
        <>
          <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <div className="overflow-x-auto">
              <table className="w-full border-collapse" role="table">
                <thead>
                  <tr>
                    <th scope="col" className={TH}>Customer</th>
                    <th scope="col" className={TH}>Branch</th>
                    <th scope="col" className={TH}>Service</th>
                    <th scope="col" className={TH}>Date/Time</th>
                    <th scope="col" className={TH}>Status</th>
                    <th scope="col" className={TH}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {bookings.map((b) => {
                    const badge = STATUS_BADGE[b.status] ?? STATUS_BADGE.pending
                    return (
                      <tr key={b.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                        <td className="px-4 py-3 text-[13.5px] text-text">
                          <div>{b.customer_name}</div>
                          {b.customer_email && <div className="text-[12px] text-muted">{b.customer_email}</div>}
                        </td>
                        <td className="px-4 py-3 text-[13.5px] text-muted">
                          {b.branch_id ? ((branchList ?? []).find(br => br.id === b.branch_id)?.name ?? '—') : '—'}
                        </td>
                        <td className="px-4 py-3 text-[13.5px] text-muted">{b.service_type ?? '—'}</td>
                        <td className="mono px-4 py-3 text-[13px] text-muted">{formatDateTime(b.start_time)}</td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex rounded-[20px] px-2.5 py-0.5 text-[11.5px] font-medium ${PILL_CLS[badge.variant]}`}>
                            {badge.label}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          {(b.status === 'pending' || b.status === 'confirmed') && (
                            <button
                              onClick={() => handleCancel(b.id)}
                              className="text-[12px] font-medium text-danger hover:brightness-90"
                            >
                              Cancel
                            </button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between text-[12.5px] text-muted">
              <span>Showing <span className="mono text-text">{(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)}</span> of <span className="mono text-text">{total}</span> bookings</span>
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
