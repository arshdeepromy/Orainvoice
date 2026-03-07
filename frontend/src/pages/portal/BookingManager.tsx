import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'

export interface PortalBooking {
  id: string
  service_type: string | null
  start_time: string
  end_time: string
  status: string
  notes: string | null
  created_at: string
}

interface TimeSlot {
  start_time: string
  end_time: string
  available: boolean
}

interface BookingManagerProps {
  token: string
}

const BOOKING_STATUS: Record<string, { label: string; variant: 'success' | 'warning' | 'error' | 'info' | 'neutral' }> = {
  confirmed: { label: 'Confirmed', variant: 'success' },
  pending: { label: 'Pending', variant: 'warning' },
  cancelled: { label: 'Cancelled', variant: 'error' },
  completed: { label: 'Completed', variant: 'neutral' },
}

export function BookingManager({ token }: BookingManagerProps) {
  const [bookings, setBookings] = useState<PortalBooking[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showNewBooking, setShowNewBooking] = useState(false)
  const [selectedDate, setSelectedDate] = useState('')
  const [slots, setSlots] = useState<TimeSlot[]>([])
  const [slotsLoading, setSlotsLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const fetchBookings = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get(`/portal/${token}/bookings`)
      setBookings(res.data.bookings ?? res.data)
    } catch {
      setError('Failed to load bookings.')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { fetchBookings() }, [fetchBookings])

  const fetchSlots = async (date: string) => {
    setSlotsLoading(true)
    try {
      const res = await apiClient.get(`/portal/${token}/bookings/slots`, { params: { date } })
      setSlots(res.data.slots ?? [])
    } catch {
      setError('Failed to load available slots.')
    } finally {
      setSlotsLoading(false)
    }
  }

  const handleDateChange = (date: string) => {
    setSelectedDate(date)
    if (date) fetchSlots(date)
  }

  const handleBookSlot = async (slot: TimeSlot) => {
    setSubmitting(true)
    setError('')
    try {
      await apiClient.post(`/portal/${token}/bookings`, {
        start_time: slot.start_time,
      })
      setShowNewBooking(false)
      setSlots([])
      setSelectedDate('')
      await fetchBookings()
    } catch {
      setError('Failed to create booking.')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <div className="py-8"><Spinner label="Loading bookings" /></div>
  if (error && !showNewBooking) return <AlertBanner variant="error">{error}</AlertBanner>

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-medium text-gray-900">Bookings</h3>
        <Button size="sm" onClick={() => setShowNewBooking(!showNewBooking)}>
          {showNewBooking ? 'Cancel' : 'New Booking'}
        </Button>
      </div>

      {error && <AlertBanner variant="error" className="mb-4">{error}</AlertBanner>}

      {showNewBooking && (
        <div className="mb-6 rounded-lg border border-blue-200 bg-blue-50 p-4">
          <h4 className="text-sm font-semibold text-gray-700 mb-3">Select a date</h4>
          <input
            type="date"
            value={selectedDate}
            onChange={(e) => handleDateChange(e.target.value)}
            min={new Date().toISOString().split('T')[0]}
            className="rounded border border-gray-300 px-3 py-2 text-sm"
          />
          {slotsLoading && <div className="mt-3"><Spinner label="Loading slots" /></div>}
          {slots.length > 0 && (
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {slots.filter(s => s.available).map((slot) => (
                <Button
                  key={slot.start_time}
                  size="sm"
                  variant="secondary"
                  onClick={() => handleBookSlot(slot)}
                  disabled={submitting}
                >
                  {formatTime(slot.start_time)}
                </Button>
              ))}
            </div>
          )}
          {!slotsLoading && selectedDate && slots.filter(s => s.available).length === 0 && (
            <p className="mt-3 text-sm text-gray-500">No available slots for this date.</p>
          )}
        </div>
      )}

      {bookings.length === 0 ? (
        <p className="py-8 text-center text-sm text-gray-500">No bookings found.</p>
      ) : (
        <div className="space-y-3">
          {bookings.map((b) => {
            const cfg = BOOKING_STATUS[b.status] ?? { label: b.status, variant: 'neutral' as const }
            return (
              <div key={b.id} className="rounded-lg border border-gray-200 bg-white p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-gray-900">
                        {b.service_type || 'Appointment'}
                      </span>
                      <Badge variant={cfg.variant}>{cfg.label}</Badge>
                    </div>
                    <p className="mt-1 text-sm text-gray-500">
                      {formatDateTime(b.start_time)} — {formatTime(b.end_time)}
                    </p>
                    {b.notes && <p className="mt-1 text-xs text-gray-400">{b.notes}</p>}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function formatDateTime(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-NZ', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function formatTime(dateStr: string): string {
  return new Date(dateStr).toLocaleTimeString('en-NZ', {
    hour: '2-digit', minute: '2-digit',
  })
}
