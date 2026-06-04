/**
 * BookingCalendar — Task 28 port of frontend/src/pages/bookings/BookingCalendar.tsx.
 *
 * Day/week/month calendar of scheduled appointments. ALL logic copied VERBATIM:
 * the fetch (GET /bookings ?view&date&status), public-holiday overlay (GET
 * /org/holidays), navigation (prev/today/next per view), status filter, the
 * 30-min slot grid (7am–7pm) with past-slot disabling, slot-click → create, and
 * the shared BookingCard (with → Job Card / → Invoice convert actions). Day /
 * Week / Month view sub-components preserved. Presentation remapped onto the
 * design tokens (FR-2b): accent for today/hover, warn for holidays, Badge
 * `warning`/`error`→`warn`/`danger`, Button `secondary`→`ghost`, `.mono` rego.
 *
 * Requirements: 64.1
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import apiClient from '@/api/client'
import { Button, Select, Badge, Spinner } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { useTenant } from '@/contexts/TenantContext'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export type CalendarView = 'day' | 'week' | 'month'
type BookingStatus = 'scheduled' | 'confirmed' | 'completed' | 'cancelled' | 'no_show'

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
  onSlotClick?: (date: Date, hour: number, minute: number) => void
  refreshKey: number
  onViewChange?: (view: CalendarView) => void
  onDateChange?: (date: Date) => void
}

interface PublicHoliday {
  id: string
  date: string
  name: string
  local_name: string | null
  year: number
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const STATUS_CONFIG: Record<BookingStatus, { label: string; variant: BadgeVariant }> = {
  scheduled: { label: 'Scheduled', variant: 'info' },
  confirmed: { label: 'Confirmed', variant: 'success' },
  completed: { label: 'Completed', variant: 'neutral' },
  cancelled: { label: 'Cancelled', variant: 'danger' },
  no_show: { label: 'No Show', variant: 'warn' },
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

/** Each slot is { hour, minute } — 30-minute intervals from 7 AM to 7 PM */
const SLOTS: { hour: number; minute: number }[] = []
for (let h = 7; h <= 19; h++) {
  SLOTS.push({ hour: h, minute: 0 })
  if (h < 19) SLOTS.push({ hour: h, minute: 30 })
}

function formatSlotLabel(hour: number, minute: number): string {
  const h12 = hour === 0 ? 12 : hour > 12 ? hour - 12 : hour
  const ampm = hour < 12 ? 'AM' : 'PM'
  return `${h12}:${minute.toString().padStart(2, '0')} ${ampm}`
}

function getBookingsForSlot(bookings: BookingSearchResult[], date: Date, hour: number, minute: number): BookingSearchResult[] {
  return bookings.filter((b) => {
    const d = new Date(b.scheduled_at)
    const bMin = d.getMinutes()
    // Bucket into the matching 30-min slot
    const slotMin = bMin < 30 ? 0 : 30
    return isSameDay(d, date) && d.getHours() === hour && slotMin === minute
  })
}

function getHolidayForDate(holidays: PublicHoliday[], date: Date): PublicHoliday | undefined {
  const iso = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
  return holidays.find((h) => h.date === iso)
}

function isPastSlot(date: Date, hour: number, minute: number): boolean {
  const now = new Date()
  const slot = new Date(date)
  slot.setHours(hour, minute, 0, 0)
  return slot < now
}

function isPastDay(date: Date): boolean {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const d = new Date(date)
  d.setHours(0, 0, 0, 0)
  return d < today
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

/**
 * Calendar view (day/week/month) showing all scheduled appointments.
 * Requirements: 64.1
 */
export default function BookingCalendar({ onCreateBooking, onEditBooking, onConvertBooking, onSlotClick, refreshKey, onViewChange, onDateChange }: BookingCalendarProps) {
  const [view, setView] = useState<CalendarView>('week')
  const [currentDate, setCurrentDate] = useState(new Date())
  const [statusFilter, setStatusFilter] = useState('')
  const [bookings, setBookings] = useState<BookingSearchResult[]>([])
  const [holidays, setHolidays] = useState<PublicHoliday[]>([])
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
      setBookings(res.data?.bookings ?? [])
    } catch {
      setError('Failed to load bookings.')
    } finally {
      setLoading(false)
    }
  }, [view, currentDate, statusFilter])

  // Fetch public holidays for the current year visible on calendar
  const currentYear = currentDate.getFullYear()
  useEffect(() => {
    apiClient
      .get<{ holidays: PublicHoliday[] }>('/org/holidays', { params: { year: currentYear } })
      .then(({ data }) => setHolidays(data?.holidays ?? []))
      .catch(() => setHolidays([]))
  }, [currentYear])

  useEffect(() => { fetchBookings() }, [fetchBookings, refreshKey])

  /* Notify parent of view/date changes */
  useEffect(() => { onViewChange?.(view) }, [view, onViewChange])
  useEffect(() => { onDateChange?.(currentDate) }, [currentDate, onDateChange])

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
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" onClick={() => navigate(-1)} aria-label="Previous">
            ‹
          </Button>
          <Button size="sm" variant="ghost" onClick={goToToday}>
            Today
          </Button>
          <Button size="sm" variant="ghost" onClick={() => navigate(1)} aria-label="Next">
            ›
          </Button>
          <span className="ml-2 text-[13px] font-medium text-text">{rangeLabel}</span>
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
        <div className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger" role="alert">{error}</div>
      )}

      {loading && bookings.length === 0 && (
        <div className="py-16"><Spinner label="Loading bookings" /></div>
      )}

      {!loading && view === 'month' && <MonthView bookings={bookings} currentDate={currentDate} onEdit={onEditBooking} onConvert={onConvertBooking} onSlotClick={onSlotClick} holidays={holidays} />}
      {!loading && view === 'week' && <WeekView bookings={bookings} currentDate={currentDate} onEdit={onEditBooking} onConvert={onConvertBooking} onSlotClick={onSlotClick} holidays={holidays} />}
      {!loading && view === 'day' && <DayView bookings={bookings} currentDate={currentDate} onEdit={onEditBooking} onConvert={onConvertBooking} onSlotClick={onSlotClick} holidays={holidays} />}

      {!loading && bookings.length === 0 && (
        <div className="py-12 text-center text-[13px] text-muted">
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
  const { tradeFamily } = useTenant()
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
  const cfg = STATUS_CONFIG[booking.status as BookingStatus] ?? STATUS_CONFIG.scheduled
  const canConvert = booking.status === 'completed' || booking.status === 'confirmed'

  return (
    <div
      className={`cursor-pointer rounded-ctl border border-border bg-card p-2 shadow-card transition-shadow hover:shadow-pop ${compact ? 'text-[12px]' : 'text-[13px]'}`}
      onClick={() => onEdit(booking)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onEdit(booking) } }}
      aria-label={`Booking: ${booking.customer_name ?? 'Unknown'} at ${formatTime(booking.scheduled_at)}`}
    >
      <div className="flex items-start justify-between gap-1">
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-text">{booking.customer_name ?? 'Walk-in'}</p>
          {!compact && (
            <>
              <p className="text-muted">{formatTime(booking.scheduled_at)} · {booking.duration_minutes}min</p>
              {isAutomotive && booking.vehicle_rego && <p className="mono text-muted">{booking.vehicle_rego}</p>}
              {booking.service_type && <p className="text-muted">{booking.service_type}</p>}
            </>
          )}
          {compact && (
            <p className="text-muted">{formatTime(booking.scheduled_at)}</p>
          )}
        </div>
        <Badge variant={cfg.variant}>{cfg.label}</Badge>
      </div>
      {canConvert && !compact && (
        <div className="mt-2 flex gap-1 border-t border-border pt-2">
          <button
            className="rounded px-2 py-1 text-[12px] font-medium text-accent hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            onClick={(e) => { e.stopPropagation(); onConvert(booking, 'job_card') }}
          >
            → Job Card
          </button>
          <button
            className="rounded px-2 py-1 text-[12px] font-medium text-accent hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
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
  onSlotClick?: (date: Date, hour: number, minute: number) => void
  holidays: PublicHoliday[]
}

const CAL_TH = 'mono px-3 py-2 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

function DayView({ bookings, currentDate, onEdit, onConvert, onSlotClick, holidays }: ViewProps) {
  const holiday = getHolidayForDate(holidays, currentDate)
  return (
    <div className="overflow-x-auto rounded-card border border-border">
      {holiday && (
        <div className="flex items-center gap-2 border-b border-warn/30 bg-warn-soft px-4 py-2 text-[13px] text-warn">
          <span>🎉</span>
          <span className="font-medium">{holiday.name}</span>
          <span className="opacity-80">— Public Holiday</span>
        </div>
      )}
      <table className="w-full border-collapse" role="grid" aria-label="Day view calendar">
        <thead>
          <tr>
            <th scope="col" className={`${CAL_TH} w-20 border-b border-border`}>Time</th>
            <th scope="col" className={`${CAL_TH} border-b border-border`}>
              {formatDayHeader(currentDate)}
            </th>
          </tr>
        </thead>
        <tbody>
          {SLOTS.map(({ hour, minute }) => {
            const slotBookings = getBookingsForSlot(bookings, currentDate, hour, minute)
            const label = formatSlotLabel(hour, minute)
            const past = isPastSlot(currentDate, hour, minute)
            return (
              <tr key={`${hour}-${minute}`} className={`group border-b border-border last:border-b-0 ${past ? 'opacity-50' : 'hover:bg-accent-soft/40'}`}>
                <td className="mono whitespace-nowrap px-3 py-3 align-top text-[12px] text-muted">
                  {label}
                </td>
                <td
                  className={`relative px-3 py-2 align-top ${past ? 'cursor-not-allowed' : 'cursor-pointer'}`}
                  onClick={() => !past && onSlotClick?.(currentDate, hour, minute)}
                  role="button"
                  tabIndex={past ? -1 : 0}
                  onKeyDown={(e) => { if (!past && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onSlotClick?.(currentDate, hour, minute) } }}
                  aria-label={past ? `Past slot: ${label}` : `Create booking at ${label} on ${formatDayHeader(currentDate)}`}
                  aria-disabled={past}
                >
                  <div className="flex flex-col gap-1">
                    {slotBookings.map((b) => (
                      <BookingCard key={b.id} booking={b} onEdit={onEdit} onConvert={onConvert} />
                    ))}
                  </div>
                  {slotBookings.length === 0 && !past && (
                    <div className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover:opacity-100">
                      <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-3 py-1 text-[12px] font-medium text-accent">
                        + New Booking
                      </span>
                    </div>
                  )}
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

function WeekView({ bookings, currentDate, onEdit, onConvert, onSlotClick, holidays }: ViewProps) {
  const weekStart = startOfWeek(currentDate)
  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i))
  const today = new Date()

  return (
    <div className="overflow-x-auto rounded-card border border-border">
      <table className="w-full border-collapse" role="grid" aria-label="Week view calendar">
        <thead>
          <tr>
            <th scope="col" className={`${CAL_TH} w-20 border-b border-border`}>Time</th>
            {days.map((d) => {
              const hol = getHolidayForDate(holidays, d)
              return (
                <th
                  key={d.toISOString()}
                  scope="col"
                  className={`mono border-b border-l border-border px-2 py-2 text-center text-[10.5px] font-medium uppercase tracking-[0.08em] ${isSameDay(d, today) ? 'bg-accent-soft text-accent' : hol ? 'bg-warn-soft text-warn' : 'text-muted-2'}`}
                  title={hol ? hol.name : undefined}
                >
                  <div>{formatDayHeader(d)}</div>
                  {hol && <div className="truncate text-[10px] font-normal normal-case text-warn">🎉 {hol.name}</div>}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {SLOTS.map(({ hour, minute }) => {
            const label = formatSlotLabel(hour, minute)
            return (
            <tr key={`${hour}-${minute}`} className="border-b border-border last:border-b-0">
              <td className="mono whitespace-nowrap px-3 py-2 align-top text-[12px] text-muted">
                {label}
              </td>
              {days.map((d) => {
                const slotBookings = getBookingsForSlot(bookings, d, hour, minute)
                const hol = getHolidayForDate(holidays, d)
                const past = isPastSlot(d, hour, minute)
                return (
                  <td
                    key={d.toISOString()}
                    className={`group relative min-w-[120px] border-l border-border px-1 py-1 align-top ${past ? 'cursor-not-allowed opacity-50' : 'cursor-pointer hover:bg-accent-soft/40'} ${isSameDay(d, today) ? 'bg-accent-soft/30' : hol ? 'bg-warn-soft/30' : ''}`}
                    onClick={() => !past && onSlotClick?.(d, hour, minute)}
                    role="button"
                    tabIndex={past ? -1 : 0}
                    onKeyDown={(e) => { if (!past && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onSlotClick?.(d, hour, minute) } }}
                    aria-label={past ? `Past slot: ${label}` : `Create booking at ${label} on ${formatDayHeader(d)}`}
                    aria-disabled={past}
                  >
                    <div className="flex flex-col gap-1">
                      {slotBookings.map((b) => (
                        <BookingCard key={b.id} booking={b} compact onEdit={onEdit} onConvert={onConvert} />
                      ))}
                    </div>
                    {slotBookings.length === 0 && !past && (
                      <div className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover:opacity-100">
                        <span className="text-lg leading-none text-accent/60">+</span>
                      </div>
                    )}
                  </td>
                )
              })}
            </tr>
          )})}
        </tbody>
      </table>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Month View                                                         */
/* ------------------------------------------------------------------ */

function MonthView({ bookings, currentDate, onEdit, onConvert, onSlotClick, holidays }: ViewProps) {
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
    <div className="overflow-hidden rounded-card border border-border">
      {/* Day name headers */}
      <div className="grid grid-cols-7 border-b border-border bg-canvas">
        {dayNames.map((name) => (
          <div key={name} className="mono px-2 py-2 text-center text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
            {name}
          </div>
        ))}
      </div>

      {/* Calendar grid */}
      {weeks.map((week, wi) => (
        <div key={wi} className="grid grid-cols-7 divide-x divide-border border-b border-border last:border-b-0">
          {week.map((day) => {
            const isCurrentMonth = day.getMonth() === currentDate.getMonth()
            const isToday = isSameDay(day, today)
            const dayBookings = bookings.filter((b) => isSameDay(new Date(b.scheduled_at), day))
            const holiday = getHolidayForDate(holidays, day)

            return (
              <div
                key={day.toISOString()}
                className={`group min-h-[100px] p-1 transition-colors ${isPastDay(day) ? 'cursor-not-allowed opacity-50' : 'cursor-pointer hover:bg-accent-soft/40'} ${isCurrentMonth ? (holiday ? 'bg-warn-soft/50' : 'bg-card') : 'bg-canvas'} ${isToday ? 'ring-2 ring-inset ring-accent' : ''}`}
                onClick={() => !isPastDay(day) && onSlotClick?.(day, 9, 0)}
                role="button"
                tabIndex={isPastDay(day) ? -1 : 0}
                onKeyDown={(e) => { if (!isPastDay(day) && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onSlotClick?.(day, 9, 0) } }}
                aria-label={isPastDay(day) ? `Past date: ${formatDayHeader(day)}` : `Create booking on ${formatDayHeader(day)}${holiday ? ` (${holiday.name})` : ''}`}
                aria-disabled={isPastDay(day)}
              >
                <div className={`mb-1 text-[12px] font-medium ${isCurrentMonth ? 'text-text' : 'text-muted-2'} ${isToday ? 'text-accent' : ''}`}>
                  {day.getDate()}
                </div>
                {holiday && (
                  <div className="mb-1 truncate rounded bg-warn-soft px-1 py-0.5 text-[10px] text-warn" title={holiday.name}>
                    🎉 {holiday.name}
                  </div>
                )}
                <div className="flex flex-col gap-0.5">
                  {dayBookings.slice(0, 3).map((b) => (
                    <BookingCard key={b.id} booking={b} compact onEdit={onEdit} onConvert={onConvert} />
                  ))}
                  {dayBookings.length > 3 && (
                    <p className="pl-1 text-[12px] text-muted">+{dayBookings.length - 3} more</p>
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
