/**
 * BookingListPanel — table of bookings for the selected calendar date range.
 * Rendered below the BookingCalendar on the BookingCalendarPage.
 *
 * Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.9
 */

import { useEffect, useState, useCallback, useImperativeHandle, forwardRef } from 'react'
import apiClient from '../../api/client'
import { Badge, Button, Spinner, useToast } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface BookingListItem {
  id: string
  customer_name: string | null
  vehicle_rego: string | null
  service_type: string | null
  scheduled_at: string | null
  start_time: string | null
  end_time: string | null
  duration_minutes: number
  status: string
  notes: string | null
  converted_job_id: string | null
}

interface BookingListResponse {
  bookings: BookingListItem[]
  total: number
  view: string
  start_date: string
  end_date: string
}

export interface BookingListPanelProps {
  startDate: Date
  endDate: Date
  /** Raw calendar reference date — sent to the backend which computes the
   *  actual range from `view` + `date`. Falls back to `startDate` when not
   *  provided (backward-compat). */
  calendarDate?: Date
  view: 'day' | 'week' | 'month'
  refreshKey: number
  onRefresh: () => void
  onCreateJob?: (booking: BookingListItem) => void
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

const STATUS_BADGE: Record<string, { label: string; variant: BadgeVariant }> = {
  pending: { label: 'Pending', variant: 'warning' },
  scheduled: { label: 'Scheduled', variant: 'info' },
  confirmed: { label: 'Confirmed', variant: 'success' },
  completed: { label: 'Completed', variant: 'neutral' },
  cancelled: { label: 'Cancelled', variant: 'error' },
  no_show: { label: 'No Show', variant: 'warning' },
}

/** Statuses that allow cancel / create-job actions. */
const ACTIONABLE_STATUSES = new Set(['pending', 'scheduled', 'confirmed'])

function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat('en-NZ', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso))
}

/** True when the row should be visually muted. */
function isMuted(status: string): boolean {
  return status === 'cancelled' || status === 'completed'
}

/** True when Cancel / Create Job buttons should show. */
export function canActOnBooking(booking: BookingListItem): boolean {
  return ACTIONABLE_STATUSES.has(booking.status) && booking.converted_job_id == null
}

/** Sort key for a booking — prefers start_time, falls back to scheduled_at. */
export function bookingSortKey(booking: BookingListItem): string {
  return booking.start_time ?? booking.scheduled_at ?? ''
}

/** Sort bookings by start_time ascending (pure function). */
export function sortBookingsByStartTime(bookings: BookingListItem[]): BookingListItem[] {
  return [...bookings].sort((a, b) => bookingSortKey(a).localeCompare(bookingSortKey(b)))
}

/** Filter bookings whose start_time (or scheduled_at) falls within [start, end] inclusive. */
export function filterBookingsByDateRange(
  bookings: BookingListItem[],
  start: string,
  end: string,
): BookingListItem[] {
  return bookings.filter((b) => {
    const t = b.start_time ?? b.scheduled_at
    if (t == null) return false
    return t >= start && t <= end
  })
}

/* ------------------------------------------------------------------ */
/*  Ref handle for parent to update a single row in-place              */
/* ------------------------------------------------------------------ */

export interface BookingListPanelHandle {
  /** Mark a booking as converted without re-fetching the full list. */
  markConverted: (bookingId: string, jobCardId: string) => void
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

const BookingListPanel = forwardRef<BookingListPanelHandle, BookingListPanelProps>(function BookingListPanel({
  startDate,
  endDate: _endDate,
  calendarDate,
  view,
  refreshKey,
  onRefresh,
  onCreateJob,
}, ref) {
  // The backend derives the date range from `view` + `date`, so we send the
  // raw calendar reference date (avoids timezone-shift issues when the
  // pre-computed startDate crosses a day boundary in UTC).
  const apiDate = calendarDate ?? startDate
  const [bookings, setBookings] = useState<BookingListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [cancellingId, setCancellingId] = useState<string | null>(null)
  const [flashId, setFlashId] = useState<string | null>(null)
  const { addToast } = useToast()

  /** Expose markConverted to parent via ref */
  useImperativeHandle(ref, () => ({
    markConverted(bookingId: string, jobCardId: string) {
      setBookings((prev) =>
        prev.map((b) =>
          b.id === bookingId
            ? { ...b, converted_job_id: jobCardId, status: 'confirmed' }
            : b,
        ),
      )
      // Flash the row green briefly
      setFlashId(bookingId)
      setTimeout(() => setFlashId(null), 1500)
    },
  }))

  /* ---- Fetch bookings ---- */
  const fetchBookings = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<BookingListResponse>('/bookings', {
        params: {
          view,
          date: apiDate.toISOString(),
        },
      })
      // Sort by start_time ascending (backend should already do this, but ensure)
      const sorted = sortBookingsByStartTime(res.data.bookings)
      setBookings(sorted)
    } catch {
      setError('Failed to load bookings.')
    } finally {
      setLoading(false)
    }
  }, [view, apiDate])

  useEffect(() => {
    fetchBookings()
  }, [fetchBookings, refreshKey])

  /* ---- Cancel action ---- */
  const handleCancel = async (booking: BookingListItem) => {
    if (!window.confirm(`Cancel booking for ${booking.customer_name ?? 'this customer'}?`)) {
      return
    }
    setCancellingId(booking.id)
    try {
      await apiClient.put(`/bookings/${booking.id}`, { status: 'cancelled' })
      addToast('success', 'Booking cancelled.')
      onRefresh()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', detail ?? 'Failed to cancel booking.')
    } finally {
      setCancellingId(null)
    }
  }

  /* ---- Render ---- */

  if (loading) {
    return (
      <div className="mt-6 py-8 text-center" role="status" aria-label="Loading bookings">
        <Spinner />
        <p className="mt-2 text-sm text-gray-500">Loading bookings…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="mt-6 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
        {error}
      </div>
    )
  }

  if (bookings.length === 0) {
    return (
      <div className="mt-6 py-8 text-center text-sm text-gray-500">
        No bookings for this period.
      </div>
    )
  }

  return (
    <div className="mt-6">
      <h2 className="text-lg font-medium text-gray-900 mb-3">Bookings</h2>

      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200" role="table">
          <thead className="bg-gray-50">
            <tr>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Customer</th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Service</th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Date/Time</th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Vehicle Rego</th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Status</th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {bookings.map((b) => {
              const badge = STATUS_BADGE[b.status] ?? STATUS_BADGE.pending
              const muted = isMuted(b.status)
              const actionable = canActOnBooking(b)
              const dateStr = b.start_time ?? b.scheduled_at

              return (
                <tr
                  key={b.id}
                  className={`transition-colors duration-700 ${
                    flashId === b.id
                      ? 'bg-green-100'
                      : muted
                        ? 'opacity-50'
                        : 'hover:bg-gray-50'
                  }`}
                >
                  <td className="px-4 py-3 text-sm text-gray-900">{b.customer_name ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-700">{b.service_type ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-700">{dateStr ? formatDateTime(dateStr) : '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-700">{b.vehicle_rego ?? '—'}</td>
                  <td className="px-4 py-3">
                    <Badge variant={badge.variant}>{badge.label}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {actionable && (
                        <>
                          <Button
                            size="sm"
                            variant="danger"
                            onClick={() => handleCancel(b)}
                            loading={cancellingId === b.id}
                            disabled={cancellingId === b.id}
                          >
                            Cancel
                          </Button>
                          <Button
                            size="sm"
                            variant="primary"
                            onClick={() => onCreateJob?.(b)}
                          >
                            Create Job
                          </Button>
                        </>
                      )}
                      {b.converted_job_id != null && (
                        <a
                          href={`/jobs/${b.converted_job_id}`}
                          className="text-sm font-medium text-blue-600 hover:text-blue-800"
                        >
                          View Job
                        </a>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
})

export default BookingListPanel