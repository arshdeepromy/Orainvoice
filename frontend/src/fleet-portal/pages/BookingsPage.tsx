/**
 * Fleet Portal bookings page — list + create form.
 *
 * Implements: B2B Fleet Portal — Requirements 11.1–11.8.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import { fleetClient } from '../api/client'
import { listBookings, listVehicles } from '../api/endpoints'
import type { BookingRequest, VehicleListItem, PaginatedResponse } from '../api/types'

export default function BookingsPage() {
  const [bookings, setBookings] = useState<BookingRequest[]>([])
  const [vehicles, setVehicles] = useState<VehicleListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)

  const fetchData = async () => {
    try {
      const [b, v] = await Promise.all([listBookings(), listVehicles(0, 100)])
      setBookings(b.items ?? [])
      setVehicles(v.items ?? [])
    } catch {} finally { setLoading(false) }
  }

  useEffect(() => { const c = new AbortController(); fetchData(); return () => c.abort() }, [])

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Service Bookings</h1>
        <button onClick={() => setShowForm(true)} className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-indigo-700">
          + New Booking
        </button>
      </div>

      {showForm && <BookingForm vehicles={vehicles} onClose={() => setShowForm(false)} onCreated={() => { setShowForm(false); fetchData() }} />}

      {(bookings ?? []).length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center dark:border-gray-700">
          <p className="text-sm text-gray-500">No bookings yet. Request a service booking for any of your fleet vehicles.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {(bookings ?? []).map(b => (
            <div key={b.id} className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">{b.service_description}</p>
                  <p className="text-xs text-gray-500 mt-1">
                    {b.preferred_date} · {b.preferred_slot} · {b.rego || 'Vehicle'}
                  </p>
                </div>
                <StatusChip status={b.status} />
              </div>
              {b.status === 'pending' && (
                <button onClick={() => cancelBooking(b.id, fetchData)} className="mt-2 text-xs text-red-600 hover:underline min-h-[44px]">
                  Cancel
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function StatusChip({ status }: { status: string }) {
  const cls = status === 'accepted' ? 'bg-green-100 text-green-800' :
    status === 'declined' ? 'bg-red-100 text-red-800' :
    status === 'cancelled' ? 'bg-gray-100 text-gray-600' :
    'bg-blue-100 text-blue-800'
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>{status}</span>
}

async function cancelBooking(id: string, refresh: () => void) {
  if (!confirm('Cancel this booking request?')) return
  try { await fleetClient.post(`/bookings/${id}/cancel`); refresh() } catch {}
}

function BookingForm({ vehicles, onClose, onCreated }: { vehicles: VehicleListItem[]; onClose: () => void; onCreated: () => void }) {
  const [vehicleId, setVehicleId] = useState('')
  const [date, setDate] = useState('')
  const [slot, setSlot] = useState('morning')
  const [desc, setDesc] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!vehicleId || !date || desc.length < 10) { setError('Fill all required fields (description must be at least 10 characters).'); return }
    setSubmitting(true); setError(null)
    try {
      await fleetClient.post('/bookings', {
        customer_vehicle_id: vehicleId,
        preferred_date: date,
        preferred_slot: slot,
        service_description: desc,
        notes: notes || null,
      })
      onCreated()
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to create booking.')
    } finally { setSubmitting(false) }
  }

  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50/50 p-4 dark:border-indigo-900 dark:bg-indigo-950/20">
      <h2 className="text-sm font-medium mb-3">New Service Booking</h2>
      {error && <p className="text-xs text-red-600 mb-2">{error}</p>}
      <form onSubmit={handleSubmit} className="space-y-3">
        <select value={vehicleId} onChange={e => setVehicleId(e.target.value)} className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white">
          <option value="">Select vehicle…</option>
          {(vehicles ?? []).map(v => <option key={v.customer_vehicle_id} value={v.customer_vehicle_id}>{v.rego} — {v.make} {v.model}</option>)}
        </select>
        <div className="grid grid-cols-2 gap-2">
          <input type="date" value={date} onChange={e => setDate(e.target.value)} className="rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
          <select value={slot} onChange={e => setSlot(e.target.value)} className="rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white">
            <option value="morning">Morning</option>
            <option value="afternoon">Afternoon</option>
            <option value="all_day">All Day</option>
          </select>
        </div>
        <textarea value={desc} onChange={e => setDesc(e.target.value)} placeholder="Describe the service needed (min 10 chars)…" rows={3}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
        <input type="text" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Additional notes (optional)"
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
        <div className="flex gap-2">
          <button type="submit" disabled={submitting} className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] disabled:opacity-50 hover:bg-indigo-700">
            {submitting ? 'Submitting…' : 'Submit Booking Request'}
          </button>
          <button type="button" onClick={onClose} className="rounded-md border border-gray-300 px-4 py-2 text-sm min-h-[44px] hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-800">
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}
