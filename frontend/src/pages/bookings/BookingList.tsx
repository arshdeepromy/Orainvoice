/**
 * Booking list page with paginated table, status filter, and date filter.
 *
 * Validates: Requirement 19 — Booking Module — Task 26.9
 */

import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'
import { Pagination, PageSizeSelect } from '@/components/ui'

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

function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat('en-NZ', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso))
}

export default function BookingList() {
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
      setBookings(res.data.bookings)
      setTotal(res.data.total)
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

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Bookings</h1>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <select
          aria-label="Status filter"
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm"
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
          className="rounded-md border border-gray-300 px-3 py-2 text-sm"
        />
        <input
          type="date"
          aria-label="End date"
          value={endDate}
          onChange={(e) => { setEndDate(e.target.value); setPage(1) }}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm"
        />
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && (
        <div className="py-12 text-center text-sm text-gray-500" role="status" aria-label="Loading bookings">
          Loading bookings…
        </div>
      )}

      {!loading && bookings.length === 0 && (
        <div className="py-12 text-center text-sm text-gray-500">
          No bookings found.
        </div>
      )}

      {!loading && bookings.length > 0 && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="table">
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Customer</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Service</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Date/Time</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Status</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {bookings.map((b) => {
                  const badge = STATUS_BADGE[b.status] ?? STATUS_BADGE.pending
                  return (
                    <tr key={b.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm text-gray-900">
                        <div>{b.customer_name}</div>
                        {b.customer_email && <div className="text-xs text-gray-500">{b.customer_email}</div>}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700">{b.service_type ?? '—'}</td>
                      <td className="px-4 py-3 text-sm text-gray-700">{formatDateTime(b.start_time)}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                          badge.variant === 'success' ? 'bg-green-100 text-green-800' :
                          badge.variant === 'warning' ? 'bg-yellow-100 text-yellow-800' :
                          badge.variant === 'error' ? 'bg-red-100 text-red-800' :
                          'bg-gray-100 text-gray-800'
                        }`}>
                          {badge.label}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {(b.status === 'pending' || b.status === 'confirmed') && (
                          <button
                            onClick={() => handleCancel(b.id)}
                            className="text-xs text-red-600 hover:text-red-800 font-medium"
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

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between text-sm text-gray-600">
              <span>Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total} bookings</span>
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
