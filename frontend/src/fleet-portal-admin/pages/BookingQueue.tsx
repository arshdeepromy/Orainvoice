/**
 * Workshop Admin — Fleet booking queue.
 *
 * Lists pending booking requests. Accept opens an inline modal with a
 * datetime picker (and creates a draft Booking on the backend). Decline
 * captures a reason via a textarea modal.
 *
 * Implements: B2B Fleet Portal — Req 16.2, 11.4, 11.5.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { FormEvent } from 'react'

import apiClient from '../../api/client'

interface BookingRequest {
  id: string
  customer_vehicle_id: string
  rego: string | null
  requested_by_name: string | null
  preferred_date: string
  preferred_slot: string
  service_description: string
  notes: string | null
  status: string
  decline_reason: string | null
  booking_id: string | null
  created_at: string
}

export default function BookingQueue() {
  const [bookings, setBookings] = useState<BookingRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [acceptingId, setAcceptingId] = useState<string | null>(null)
  const [decliningId, setDecliningId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchBookings = async () => {
    setError(null)
    try {
      const res = await apiClient.get<{ items: BookingRequest[]; total: number }>(
        '/api/v2/fleet-portal/admin/bookings',
        { params: { limit: 50 } },
      )
      setBookings(res.data?.items ?? [])
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to load bookings.'
      setError(detail)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchBookings()
  }, [])

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Fleet Booking Requests</h1>
        <Link
          to="/fleet-portal-admin"
          className="text-sm text-indigo-600 hover:underline"
        >
          ← Fleet Portal
        </Link>
      </div>

      {error ? (
        <p className="rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
          {error}
        </p>
      ) : null}

      {(bookings ?? []).length === 0 ? (
        <p className="text-sm text-gray-500">No pending booking requests.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-800 text-sm">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Customer</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Vehicle</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Service</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Date</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Slot</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Status</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-800 bg-white dark:bg-gray-950">
              {(bookings ?? []).map((b) => (
                <tr key={b.id}>
                  <td className="px-3 py-2">{b.requested_by_name ?? '—'}</td>
                  <td className="px-3 py-2 font-medium">{b.rego ?? '—'}</td>
                  <td className="px-3 py-2 max-w-[260px] truncate" title={b.service_description}>
                    {b.service_description}
                  </td>
                  <td className="px-3 py-2">{b.preferred_date}</td>
                  <td className="px-3 py-2 capitalize">{b.preferred_slot?.replace('_', ' ')}</td>
                  <td className="px-3 py-2">
                    <span
                      className={
                        'rounded-full px-2 py-0.5 text-xs font-medium ' +
                        (b.status === 'pending'
                          ? 'bg-blue-100 text-blue-800'
                          : b.status === 'accepted'
                            ? 'bg-green-100 text-green-800'
                            : b.status === 'declined'
                              ? 'bg-red-100 text-red-800'
                              : 'bg-gray-100 text-gray-600')
                      }
                    >
                      {b.status}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {b.status === 'pending' ? (
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => setAcceptingId(b.id)}
                          className="text-xs text-green-700 hover:underline min-h-[36px]"
                        >
                          Accept
                        </button>
                        <button
                          type="button"
                          onClick={() => setDecliningId(b.id)}
                          className="text-xs text-red-700 hover:underline min-h-[36px]"
                        >
                          Decline
                        </button>
                      </div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {acceptingId ? (
        <AcceptBookingModal
          booking={bookings.find((b) => b.id === acceptingId)!}
          onClose={() => setAcceptingId(null)}
          onAccepted={() => {
            setAcceptingId(null)
            void fetchBookings()
          }}
        />
      ) : null}
      {decliningId ? (
        <DeclineBookingModal
          booking={bookings.find((b) => b.id === decliningId)!}
          onClose={() => setDecliningId(null)}
          onDeclined={() => {
            setDecliningId(null)
            void fetchBookings()
          }}
        />
      ) : null}
    </div>
  )
}

function AcceptBookingModal({
  booking,
  onClose,
  onAccepted,
}: {
  booking: BookingRequest
  onClose: () => void
  onAccepted: () => void
}) {
  // Default the datetime to noon on the requested preferred_date so the
  // value is always parseable, regardless of the user's locale prompt.
  const defaultIso =
    booking.preferred_slot === 'morning'
      ? `${booking.preferred_date}T08:30`
      : booking.preferred_slot === 'afternoon'
        ? `${booking.preferred_date}T13:00`
        : `${booking.preferred_date}T09:00`
  const [refined, setRefined] = useState(defaultIso)
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setErr(null)
    try {
      const dt = new Date(refined)
      if (Number.isNaN(dt.getTime())) {
        setErr('Pick a valid date and time.')
        setSubmitting(false)
        return
      }
      await apiClient.post(
        `/api/v2/fleet-portal/admin/bookings/${booking.id}/accept`,
        {
          refined_date_time: dt.toISOString(),
          notes: notes.trim() || null,
        },
      )
      onAccepted()
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to accept booking.'
      setErr(detail)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <form
        onSubmit={submit}
        className="w-full max-w-md rounded-lg bg-white p-4 shadow-lg dark:bg-gray-900"
      >
        <h2 className="mb-2 text-base font-semibold">Accept booking</h2>
        <p className="mb-3 text-xs text-gray-500">
          {booking.rego ? `${booking.rego} — ` : ''}
          {booking.service_description}
        </p>
        {err ? <p className="mb-2 text-xs text-red-600">{err}</p> : null}
        <label className="mb-1 block text-xs font-medium text-gray-500">
          Confirmed date &amp; time
        </label>
        <input
          type="datetime-local"
          value={refined}
          onChange={(e) => setRefined(e.target.value)}
          required
          className="mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-800 dark:text-white"
        />
        <label className="mb-1 block text-xs font-medium text-gray-500">
          Internal notes (optional)
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          className="mb-4 w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-800 dark:text-white"
        />
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] hover:bg-gray-50 dark:border-gray-700"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-green-700 disabled:opacity-50"
          >
            {submitting ? 'Accepting…' : 'Accept'}
          </button>
        </div>
      </form>
    </div>
  )
}

function DeclineBookingModal({
  booking,
  onClose,
  onDeclined,
}: {
  booking: BookingRequest
  onClose: () => void
  onDeclined: () => void
}) {
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!reason.trim()) {
      setErr('Please give the customer a reason.')
      return
    }
    setSubmitting(true)
    setErr(null)
    try {
      await apiClient.post(
        `/api/v2/fleet-portal/admin/bookings/${booking.id}/decline`,
        { decline_reason: reason.trim() },
      )
      onDeclined()
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to decline booking.'
      setErr(detail)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <form
        onSubmit={submit}
        className="w-full max-w-md rounded-lg bg-white p-4 shadow-lg dark:bg-gray-900"
      >
        <h2 className="mb-2 text-base font-semibold">Decline booking</h2>
        <p className="mb-3 text-xs text-gray-500">
          {booking.rego ? `${booking.rego} — ` : ''}
          {booking.service_description}
        </p>
        {err ? <p className="mb-2 text-xs text-red-600">{err}</p> : null}
        <label className="mb-1 block text-xs font-medium text-gray-500">
          Reason (sent to the customer)
        </label>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={4}
          className="mb-4 w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-800 dark:text-white"
          required
        />
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] hover:bg-gray-50 dark:border-gray-700"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-red-700 disabled:opacity-50"
          >
            {submitting ? 'Declining…' : 'Decline'}
          </button>
        </div>
      </form>
    </div>
  )
}
