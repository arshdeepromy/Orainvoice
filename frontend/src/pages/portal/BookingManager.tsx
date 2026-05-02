import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { usePortalLocale } from './PortalLocaleContext'
import { formatDateTime, formatTime } from './portalFormatters'

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
  const locale = usePortalLocale()
  const [bookings, setBookings] = useState<PortalBooking[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showNewBooking, setShowNewBooking] = useState(false)
  const [selectedDate, setSelectedDate] = useState('')
  const [slots, setSlots] = useState<TimeSlot[]>([])
  const [slotsLoading, setSlotsLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [cancellingId, setCancellingId] = useState<string | null>(null)
  const [serviceType, setServiceType] = useState('')
  const [notes, setNotes] = useState('')

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
        service_type: serviceType || undefined,
        notes: notes || undefined,
      })
      setShowNewBooking(false)
      setSlots([])
      setSelectedDate('')
      setServiceType('')
      setNotes('')
      await fetchBookings()
    } catch {
      setError('Failed to create booking.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleCancelBooking = async (bookingId: string) => {
    setCancellingId(bookingId)
    setError('')
    try {
      await apiClient.patch(`/portal/${token}/bookings/${bookingId}/cancel`)
      await fetchBookings()
    } catch {
      setError('Failed to cancel booking.')
    } finally {
      setCancellingId(null)
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
          <div className="mb-4">
            <label htmlFor="service-type" className="block text-sm font-semibold text-gray-700 mb-1">
              Service Type
            </label>
            <input
              id="service-type"
              type="text"
              value={serviceType}
              onChange={(e) => setServiceType(e.target.value)}
              placeholder="e.g. Oil Change, WOF, Full Service"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>

          <div className="mb-4">
            <label htmlFor="booking-notes" className="block text-sm font-semibold text-gray-700 mb-1">
              Notes
            </label>
            <textarea
              id="booking-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Any additional details or requests…"
              rows={3}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm resize-y"
            />
          </div>

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
                  {formatTime(slot.start_time, locale)}
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
            const isCancellable = b.status === 'pending' || b.status === 'confirmed'
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
                      {formatDateTime(b.start_time, locale)} — {formatTime(b.end_time, locale)}
                    </p>
                    {b.notes && <p className="mt-1 text-xs text-gray-400">{b.notes}</p>}
                  </div>
                  {isCancellable && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => handleCancelBooking(b.id)}
                      disabled={cancellingId === b.id}
                    >
                      {cancellingId === b.id ? 'Cancelling…' : 'Cancel'}
                    </Button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
