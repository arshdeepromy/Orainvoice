import { useState, useEffect, useCallback, useMemo } from 'react'
import apiClient from '../../api/client'
import { Button, Select, Badge, Spinner } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type CalendarView = 'day' | 'week' | 'month'
type BookingStatus = 'scheduled' | 'confirmed' | 'completed' | 'cancelled' | 'no_show'
type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

export interface BookingSearchResult {
  id: string
  customer_name: string | null
  vehicle_rego: string | null
  service_type: string | null
  scheduled_at: string
  duration_minutes: number
  status: string
}

interface BookingListResponse {
  bookings: BookingSearchResult[]
  total: number
  view: string
  start_date: string
  end_date: string
}

interface BookingCalendarProps {
  onCreateBooking: () => void
  onEditBooking: (booking: BookingSearchResult) => void
  onConvertBooking: (booking: BookingSearchResult, target: 'job_card' | 'invoice') => void
  refreshKey: number
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const STATUS_CONFIG: Record<BookingStatus, { label: string; variant: BadgeVariant }> = {
  scheduled: { label: 'Scheduled', variant: 'info' },
  confirmed: { label: 'Confirmed', variant: 'success' },
  completed: { label: 'Completed', variant: 'neutral' },
  cancelled: { label: 'Cancelled', variant: 'error' },
  no_show: { label: 'No Show', variant: 'warning' },
}

const VIEW_OPTIONS = [
  { value: 'day', label: 'Day' },
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
]

const STATUS_FILTER_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'scheduled', label: 'Scheduled' },
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'completed', label: 'Completed' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'no_show', label: 'No Show' },
]

function formatTime(dateStr: string): string {
  return new Intl.DateTimeFormat('en-NZ', { hour: '2-digit', minute: '2-digit', hour12: true }).format(new Date(dateStr))
}


function formatDayHeader(date: Date): string {
  return new Intl.DateTimeFormat('en-NZ', { weekday: 'short', day: 'numeric', month: 'short' }).format(date)
}

function addDays(date: Date, days: number): Date {
  const d = new Date(date)
  d.setDate(d.getDate() + days)
  return d
}

function startOfWeek(date: Date): Date {
  const d = new Date(date)
  const day = d.getDay()
  const diff = day === 0 ? -6 : 1 - day // Monday start
  d.setDate(d.getDate() + diff)
  d.setHours(0, 0, 0, 0)
  return d
}

function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

function endOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth() + 1, 0)
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

/* ------------------------------------------------------------------ */
/*  Time slots for day/week views                                      */
/* ------------------------------------------------------------------ */

const HOURS = Array.from({ length: 13 }, (_, i) => i + 7) // 7am to 7pm

function getBookingsForSlot(bookings: BookingSearchResult[], date: Date, hour: number): BookingSearchResult[] {
  return bookings.filter((b) => {
    const d = new Date(b.scheduled_at)
    return isSameDay(d, date) && d.getHours() === hour
  })
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

/**
 * Calendar view (day/week/month) showing all scheduled appointments.
 * Supports navigation, status filtering, and actions on bookings.
 *
 * Requirements: 64.1
 */
export default function BookingCalendar({ onCreateBooking, onEditBooking, onConvertBooking, refreshKey }: BookingCalendarProps) {
  const [view, setView] = useState<CalendarView>('week')
  const [currentDate, setCurrentDate] = useState(new Date())
  const [statusFilter, setStatusFilter] = useState('')
  const [bookings, setBookings] = useState<BookingSearchResult[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchBookings = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string> = {
        view,
        date: currentDate.toISOString(),
      }
      if (statusFilter) params.status = statusFilter

      const res = await apiClient.get<BookingListResponse>('/bookings', { params })
      setBookings(res.data.bookings)
    } catch {
      setError('Failed to load bookings.')
    } finally {
      setLoading(false)
    }
  }, [view, currentDate, statusFilter])

  useEffect(() => { fetchBookings() }, [fetchBookings, refreshKey])

  /* Navigation */
  const navigate = (direction: -1 | 1) => {
    const d = new Date(currentDate)
    if (view === 'day') d.setDate(d.getDate() + direction)
    else if (view === 'week') d.setDate(d.getDate() + 7 * direction)
    else d.setMonth(d.getMonth() + direction)
    setCurrentDate(d)
  }

  const goToToday = () => setCurrentDate(new Date())

  /* Date range label */
  const rangeLabel = useMemo(() => {
    if (view === 'day') {
      return new Intl.DateTimeFormat('en-NZ', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(currentDate)
    }
    if (view === 'week') {
      const ws = startOfWeek(currentDate)
      const we = addDays(ws, 6)
      const fmt = new Intl.DateTimeFormat('en-NZ', { day: 'numeric', month: 'short' })
      return `${fmt.format(ws)} – ${fmt.format(we)} ${we.getFullYear()}`
    }
    return new Intl.DateTimeFormat('en-NZ', { month: 'long', year: 'numeric' }).format(currentDate)
  }, [view, currentDate])

  return (
    <div>
      {/* Toolbar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-4">
        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" onClick={() => navigate(-1)} aria-label="Previous">
            ‹
          </Button>
          <Button size="sm" variant="secondary" onClick={goToToday}>
            Today
          </Button>
          <Button size="sm" variant="secondary" onClick={() => navigate(1)} aria-label="Next">
            ›
          </Button>
          <span className="ml-2 text-sm font-medium text-gray-900">{rangeLabel}</span>
        </div>
        <div className="flex items-center gap-3">
          <Select
            label="View"
            options={VIEW_OPTIONS}
            value={view}
            onChange={(e) => setView(e.target.value as CalendarView)}
          />
          <Select
            label="Status"
            options={STATUS_FILTER_OPTIONS}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          />
          <Button onClick={onCreateBooking}>+ New Booking</Button>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && bookings.length === 0 && (
        <div className="py-16"><Spinner label="Loading bookings" /></div>
      )}

      {!loading && view === 'month' && <MonthView bookings={bookings} currentDate={currentDate} onEdit={onEditBooking} onConvert={onConvertBooking} />}
      {!loading && view === 'week' && <WeekView bookings={bookings} currentDate={currentDate} onEdit={onEditBooking} onConvert={onConvertBooking} />}
      {!loading && view === 'day' && <DayView bookings={bookings} currentDate={currentDate} onEdit={onEditBooking} onConvert={onConvertBooking} />}

      {!loading && bookings.length === 0 && (
        <div className="py-12 text-center text-sm text-gray-500">
          No bookings for this period. Click "+ New Booking" to schedule an appointment.
        </div>
      )}
    </div>
  )
}


/* ------------------------------------------------------------------ */
/*  Booking Card (shared across views)                                 */
/* ------------------------------------------------------------------ */

interface BookingCardProps {
  booking: BookingSearchResult
  compact?: boolean
  onEdit: (b: BookingSearchResult) => void
  onConvert: (b: BookingSearchResult, target: 'job_card' | 'invoice') => void
}

function BookingCard({ booking, compact = false, onEdit, onConvert }: BookingCardProps) {
  const cfg = STATUS_CONFIG[booking.status as BookingStatus] ?? STATUS_CONFIG.scheduled
  const canConvert = booking.status === 'completed' || booking.status === 'confirmed'

  return (
    <div
      className={`rounded-md border border-gray-200 bg-white p-2 shadow-sm hover:shadow-md transition-shadow cursor-pointer ${compact ? 'text-xs' : 'text-sm'}`}
      onClick={() => onEdit(booking)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onEdit(booking) } }}
      aria-label={`Booking: ${booking.customer_name ?? 'Unknown'} at ${formatTime(booking.scheduled_at)}`}
    >
      <div className="flex items-start justify-between gap-1">
        <div className="min-w-0 flex-1">
          <p className="font-medium text-gray-900 truncate">{booking.customer_name ?? 'Walk-in'}</p>
          {!compact && (
            <>
              <p className="text-gray-500">{formatTime(booking.scheduled_at)} · {booking.duration_minutes}min</p>
              {booking.vehicle_rego && <p className="text-gray-500 font-mono">{booking.vehicle_rego}</p>}
              {booking.service_type && <p className="text-gray-500">{booking.service_type}</p>}
            </>
          )}
          {compact && (
            <p className="text-gray-500">{formatTime(booking.scheduled_at)}</p>
          )}
        </div>
        <Badge variant={cfg.variant}>{cfg.label}</Badge>
      </div>
      {canConvert && !compact && (
        <div className="mt-2 flex gap-1 border-t border-gray-100 pt-2">
          <button
            className="rounded px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            onClick={(e) => { e.stopPropagation(); onConvert(booking, 'job_card') }}
          >
            → Job Card
          </button>
          <button
            className="rounded px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            onClick={(e) => { e.stopPropagation(); onConvert(booking, 'invoice') }}
          >
            → Invoice
          </button>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Day View                                                           */
/* ------------------------------------------------------------------ */

interface ViewProps {
  bookings: BookingSearchResult[]
  currentDate: Date
  onEdit: (b: BookingSearchResult) => void
  onConvert: (b: BookingSearchResult, target: 'job_card' | 'invoice') => void
}

function DayView({ bookings, currentDate, onEdit, onConvert }: ViewProps) {
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full divide-y divide-gray-200" role="grid" aria-label="Day view calendar">
        <thead className="bg-gray-50">
          <tr>
            <th scope="col" className="w-20 px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Time</th>
            <th scope="col" className="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
              {formatDayHeader(currentDate)}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {HOURS.map((hour) => {
            const slotBookings = getBookingsForSlot(bookings, currentDate, hour)
            return (
              <tr key={hour} className="hover:bg-gray-50">
                <td className="whitespace-nowrap px-3 py-3 text-xs text-gray-500 align-top tabular-nums">
                  {hour.toString().padStart(2, '0')}:00
                </td>
                <td className="px-3 py-2 align-top">
                  <div className="flex flex-col gap-1">
                    {slotBookings.map((b) => (
                      <BookingCard key={b.id} booking={b} onEdit={onEdit} onConvert={onConvert} />
                    ))}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Week View                                                          */
/* ------------------------------------------------------------------ */

function WeekView({ bookings, currentDate, onEdit, onConvert }: ViewProps) {
  const weekStart = startOfWeek(currentDate)
  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i))
  const today = new Date()

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full divide-y divide-gray-200" role="grid" aria-label="Week view calendar">
        <thead className="bg-gray-50">
          <tr>
            <th scope="col" className="w-20 px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Time</th>
            {days.map((d) => (
              <th
                key={d.toISOString()}
                scope="col"
                className={`px-2 py-2 text-left text-xs font-medium uppercase tracking-wider ${isSameDay(d, today) ? 'text-blue-600 bg-blue-50' : 'text-gray-500'}`}
              >
                {formatDayHeader(d)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {HOURS.map((hour) => (
            <tr key={hour} className="hover:bg-gray-50">
              <td className="whitespace-nowrap px-3 py-2 text-xs text-gray-500 align-top tabular-nums">
                {hour.toString().padStart(2, '0')}:00
              </td>
              {days.map((d) => {
                const slotBookings = getBookingsForSlot(bookings, d, hour)
                return (
                  <td key={d.toISOString()} className={`px-1 py-1 align-top min-w-[120px] ${isSameDay(d, today) ? 'bg-blue-50/30' : ''}`}>
                    <div className="flex flex-col gap-1">
                      {slotBookings.map((b) => (
                        <BookingCard key={b.id} booking={b} compact onEdit={onEdit} onConvert={onConvert} />
                      ))}
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Month View                                                         */
/* ------------------------------------------------------------------ */

function MonthView({ bookings, currentDate, onEdit, onConvert }: ViewProps) {
  const monthStart = startOfMonth(currentDate)
  const monthEnd = endOfMonth(currentDate)
  const calStart = startOfWeek(monthStart)
  const today = new Date()

  // Build 6 weeks of days
  const weeks: Date[][] = []
  let cursor = new Date(calStart)
  for (let w = 0; w < 6; w++) {
    const week: Date[] = []
    for (let d = 0; d < 7; d++) {
      week.push(new Date(cursor))
      cursor = addDays(cursor, 1)
    }
    weeks.push(week)
    // Stop if we've passed the month end
    if (cursor > monthEnd && w >= 3) break
  }

  const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

  return (
    <div className="rounded-lg border border-gray-200 overflow-hidden">
      {/* Day name headers */}
      <div className="grid grid-cols-7 bg-gray-50 border-b border-gray-200">
        {dayNames.map((name) => (
          <div key={name} className="px-2 py-2 text-center text-xs font-medium uppercase tracking-wider text-gray-500">
            {name}
          </div>
        ))}
      </div>

      {/* Calendar grid */}
      {weeks.map((week, wi) => (
        <div key={wi} className="grid grid-cols-7 divide-x divide-gray-100 border-b border-gray-100 last:border-b-0">
          {week.map((day) => {
            const isCurrentMonth = day.getMonth() === currentDate.getMonth()
            const isToday = isSameDay(day, today)
            const dayBookings = bookings.filter((b) => isSameDay(new Date(b.scheduled_at), day))

            return (
              <div
                key={day.toISOString()}
                className={`min-h-[100px] p-1 ${isCurrentMonth ? 'bg-white' : 'bg-gray-50'} ${isToday ? 'ring-2 ring-inset ring-blue-500' : ''}`}
              >
                <div className={`text-xs font-medium mb-1 ${isCurrentMonth ? 'text-gray-900' : 'text-gray-400'} ${isToday ? 'text-blue-600' : ''}`}>
                  {day.getDate()}
                </div>
                <div className="flex flex-col gap-0.5">
                  {dayBookings.slice(0, 3).map((b) => (
                    <BookingCard key={b.id} booking={b} compact onEdit={onEdit} onConvert={onConvert} />
                  ))}
                  {dayBookings.length > 3 && (
                    <p className="text-xs text-gray-500 pl-1">+{dayBookings.length - 3} more</p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}
