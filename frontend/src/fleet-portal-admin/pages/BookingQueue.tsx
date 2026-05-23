/**
 * Workshop Admin — Fleet booking queue.
 * Shows pending booking requests with accept/decline actions.
 *
 * Implements: B2B Fleet Portal — Requirement 16.2.
 */
import { useEffect, useState } from 'react'

import apiClient from '../../api/client'

interface BookingRequest {
  id: string
  customer_vehicle_id: string
  rego: string | null
  requested_by_name: string | null
  preferred_date: string
  preferred_slot: string
  service_description: string
  status: string
  created_at: string
}

export default function BookingQueue() {
  const [bookings, setBookings] = useState<BookingRequest[]>([])
  const [loading, setLoading] = useState(true)

  const fetchBookings = async () => {
    try {
      const res = await apiClient.get<{ items: BookingRequest[]; total: number }>(
        '/api/v2/fleet-portal/admin/bookings',
        { params: { limit: 50 } },
      )
      setBookings(res.data?.items ?? [])
    } catch {} finally { setLoading(false) }
  }

  useEffect(() => { fetchBookings() }, [])

  const acceptBooking = async (id: string) => {
    const dateTime = prompt('Enter confirmed date/time (YYYY-MM-DD HH:MM):')
    if (!dateTime) return
    try {
      await apiClient.post(`/api/v2/fleet-portal/admin/bookings/${id}/accept`, {
        refined_date_time: new Date(dateTime).toISOString(),
      })
      await fetchBookings()
    } catch { alert('Failed to accept booking.') }
  }

  const declineBooking = async (id: string) => {
    const reason = prompt('Decline reason:')
    if (!reason) return
    try {
      await apiClient.post(`/api/v2/fleet-portal/admin/bookings/${id}/decline`, {
        decline_reason: reason,
      })
      await fetchBookings()
    } catch { alert('Failed to decline booking.') }
  }

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Fleet Booking Requests</h1>
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
              {(bookings ?? []).map(b => (
                <tr key={b.id}>
                  <td className="px-3 py-2">{b.requested_by_name ?? '—'}</td>
                  <td className="px-3 py-2 font-medium">{b.rego ?? '—'}</td>
                  <td className="px-3 py-2 max-w-[200px] truncate">{b.service_description}</td>
                  <td className="px-3 py-2">{b.preferred_date}</td>
                  <td className="px-3 py-2 capitalize">{b.preferred_slot?.replace('_', ' ')}</td>
                  <td className="px-3 py-2">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${b.status === 'pending' ? 'bg-blue-100 text-blue-800' : b.status === 'accepted' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'}`}>
                      {b.status}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {b.status === 'pending' && (
                      <div className="flex gap-1">
                        <button onClick={() => acceptBooking(b.id)} className="text-xs text-green-700 hover:underline min-h-[36px]">Accept</button>
                        <button onClick={() => declineBooking(b.id)} className="text-xs text-red-700 hover:underline min-h-[36px]">Decline</button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
