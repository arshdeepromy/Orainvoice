import { useState, useCallback } from 'react'
import apiClient from '../../api/client'
import { useToast } from '../../components/ui'
import BookingCalendar from './BookingCalendar'
import BookingForm from './BookingForm'
import type { BookingSearchResult } from './BookingCalendar'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ConvertResponse {
  booking_id: string
  target: string
  created_id: string
  message: string
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

/**
 * Booking calendar page — calendar view (day/week/month), appointment
 * create/edit, and conversion to job card or invoice.
 *
 * Requirements: 64.1-64.5
 */
export default function BookingCalendarPage() {
  const [formOpen, setFormOpen] = useState(false)
  const [editBooking, setEditBooking] = useState<BookingSearchResult | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const { addToast } = useToast()

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), [])

  const handleCreate = () => {
    setEditBooking(null)
    setFormOpen(true)
  }

  const handleEdit = (booking: BookingSearchResult) => {
    setEditBooking(booking)
    setFormOpen(true)
  }

  const handleSaved = () => {
    addToast('success', editBooking ? 'Booking updated.' : 'Booking created.')
    refresh()
  }

  const handleConvert = async (booking: BookingSearchResult, target: 'job_card' | 'invoice') => {
    const label = target === 'job_card' ? 'Job Card' : 'Draft Invoice'
    if (!window.confirm(`Convert this booking to a ${label}? The booking will be marked as completed.`)) return

    try {
      const res = await apiClient.post<ConvertResponse>(
        `/bookings/${booking.id}/convert`,
        null,
        { params: { target } },
      )
      addToast('success', res.data.message || `Converted to ${label}.`)
      refresh()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', detail ?? `Failed to convert to ${label}.`)
    }
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-gray-900 mb-4">Bookings</h1>

      <BookingCalendar
        onCreateBooking={handleCreate}
        onEditBooking={handleEdit}
        onConvertBooking={handleConvert}
        refreshKey={refreshKey}
      />

      <BookingForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onSaved={handleSaved}
        editBooking={editBooking}
      />
    </div>
  )
}
