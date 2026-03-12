import { useState, useCallback, useMemo, useRef } from 'react'
import apiClient from '../../api/client'
import { useToast } from '../../components/ui'
import BookingCalendar from './BookingCalendar'
import type { BookingSearchResult, CalendarView } from './BookingCalendar'
import BookingForm from './BookingForm'
import BookingListPanel from './BookingListPanel'
import type { BookingListItem } from './BookingListPanel'
import type { BookingListPanelHandle } from './BookingListPanel'
import JobCreationModal from './JobCreationModal'

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
  const [calendarView, setCalendarView] = useState<CalendarView>('week')
  const [calendarDate, setCalendarDate] = useState(new Date())
  const [jobModalBooking, setJobModalBooking] = useState<BookingListItem | null>(null)
  const { addToast } = useToast()
  const listPanelRef = useRef<BookingListPanelHandle>(null)

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), [])

  /** Compute the start/end dates for the current calendar view. */
  const { startDate, endDate } = useMemo(() => {
    const d = calendarDate
    if (calendarView === 'day') {
      const s = new Date(d.getFullYear(), d.getMonth(), d.getDate())
      const e = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 23, 59, 59, 999)
      return { startDate: s, endDate: e }
    }
    if (calendarView === 'week') {
      const day = d.getDay()
      const diff = day === 0 ? -6 : 1 - day // Monday start
      const ws = new Date(d)
      ws.setDate(ws.getDate() + diff)
      ws.setHours(0, 0, 0, 0)
      const we = new Date(ws)
      we.setDate(we.getDate() + 6)
      we.setHours(23, 59, 59, 999)
      return { startDate: ws, endDate: we }
    }
    // month
    const s = new Date(d.getFullYear(), d.getMonth(), 1)
    const e = new Date(d.getFullYear(), d.getMonth() + 1, 0, 23, 59, 59, 999)
    return { startDate: s, endDate: e }
  }, [calendarView, calendarDate])

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
        onViewChange={setCalendarView}
        onDateChange={setCalendarDate}
      />

      <BookingListPanel
        ref={listPanelRef}
        startDate={startDate}
        endDate={endDate}
        calendarDate={calendarDate}
        view={calendarView}
        refreshKey={refreshKey}
        onRefresh={refresh}
        onCreateJob={(booking) => setJobModalBooking(booking)}
      />

      <BookingForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onSaved={handleSaved}
        editBooking={editBooking}
      />

      {jobModalBooking && (
        <JobCreationModal
          booking={jobModalBooking}
          isOpen={!!jobModalBooking}
          onClose={() => setJobModalBooking(null)}
          onSuccess={(jobCardId) => {
            const bookingId = jobModalBooking.id
            setJobModalBooking(null)
            // Update the row in-place with a green flash instead of full refresh
            listPanelRef.current?.markConverted(bookingId, jobCardId)
          }}
        />
      )}
    </div>
  )
}
