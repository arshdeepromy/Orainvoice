import { useState, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Booking } from '@shared/types/booking'
import { useApiList } from '@/hooks/useApiList'
import { MobileCard, MobileButton, MobileListItem, MobileBadge, MobileSpinner } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatTime(timeStr: string): string {
  if (!timeStr) return ''
  // Handle both ISO datetime and HH:MM time strings
  try {
    if (timeStr.includes('T')) {
      return new Date(timeStr).toLocaleTimeString('en-NZ', {
        hour: '2-digit',
        minute: '2-digit',
      })
    }
    return timeStr
  } catch {
    return timeStr
  }
}

function formatDuration(minutes: number): string {
  if (!minutes) return ''
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return `${m}min`
  if (m === 0) return `${h}h`
  return `${h}h ${m}m`
}

const statusVariant: Record<Booking['status'], 'active' | 'info' | 'paid' | 'cancelled'> = {
  scheduled: 'info',
  confirmed: 'active',
  completed: 'paid',
  cancelled: 'cancelled',
}

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate()
}

function getFirstDayOfMonth(year: number, month: number): number {
  return new Date(year, month, 1).getDay()
}

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

const DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

/**
 * Booking calendar screen — calendar view with bookings.
 * Tap date to show day list. Pull-to-refresh.
 * Wrapped in ModuleGate at the route level.
 *
 * Requirements: 21.1, 21.2, 21.5
 */
export default function BookingCalendarScreen() {
  const navigate = useNavigate()
  const today = new Date()
  const [viewYear, setViewYear] = useState(today.getFullYear())
  const [viewMonth, setViewMonth] = useState(today.getMonth())
  const [selectedDate, setSelectedDate] = useState<string>(
    today.toISOString().split('T')[0],
  )

  const {
    items: bookings,
    isLoading,
    isRefreshing,
    refresh,
  } = useApiList<Booking>({
    endpoint: '/api/v1/bookings',
    dataKey: 'items',
    pageSize: 100,
  })

  // Group bookings by date
  const bookingsByDate = useMemo(() => {
    const map: Record<string, Booking[]> = {}
    for (const b of bookings) {
      const dateKey = (b.date ?? '').split('T')[0]
      if (!dateKey) continue
      if (!map[dateKey]) map[dateKey] = []
      map[dateKey].push(b)
    }
    return map
  }, [bookings])

  const selectedBookings = bookingsByDate[selectedDate] ?? []

  const handlePrevMonth = useCallback(() => {
    if (viewMonth === 0) {
      setViewMonth(11)
      setViewYear((y) => y - 1)
    } else {
      setViewMonth((m) => m - 1)
    }
  }, [viewMonth])

  const handleNextMonth = useCallback(() => {
    if (viewMonth === 11) {
      setViewMonth(0)
      setViewYear((y) => y + 1)
    } else {
      setViewMonth((m) => m + 1)
    }
  }, [viewMonth])

  // Build calendar grid
  const daysInMonth = getDaysInMonth(viewYear, viewMonth)
  const firstDay = getFirstDayOfMonth(viewYear, viewMonth)
  const todayStr = today.toISOString().split('T')[0]

  const calendarDays: (number | null)[] = []
  for (let i = 0; i < firstDay; i++) calendarDays.push(null)
  for (let d = 1; d <= daysInMonth; d++) calendarDays.push(d)

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col gap-4 p-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Bookings
          </h1>
          <MobileButton
            variant="primary"
            size="sm"
            onClick={() => navigate('/bookings/new')}
            icon={
              <svg
                className="h-4 w-4"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
            }
          >
            New
          </MobileButton>
        </div>

        {/* Month navigation */}
        <MobileCard>
          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={handlePrevMonth}
              className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-gray-600 active:bg-gray-100 dark:text-gray-400 dark:active:bg-gray-700"
              aria-label="Previous month"
            >
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="m15 18-6-6 6-6" />
              </svg>
            </button>
            <span className="text-base font-semibold text-gray-900 dark:text-gray-100">
              {MONTH_NAMES[viewMonth]} {viewYear}
            </span>
            <button
              type="button"
              onClick={handleNextMonth}
              className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-gray-600 active:bg-gray-100 dark:text-gray-400 dark:active:bg-gray-700"
              aria-label="Next month"
            >
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="m9 18 6-6-6-6" />
              </svg>
            </button>
          </div>

          {/* Day labels */}
          <div className="mt-3 grid grid-cols-7 gap-1 text-center">
            {DAY_LABELS.map((d) => (
              <span key={d} className="text-xs font-medium text-gray-500 dark:text-gray-400">
                {d}
              </span>
            ))}
          </div>

          {/* Calendar grid */}
          <div className="mt-1 grid grid-cols-7 gap-1">
            {calendarDays.map((day, idx) => {
              if (day === null) {
                return <div key={`empty-${idx}`} className="h-10" />
              }
              const dateStr = `${viewYear}-${String(viewMonth + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
              const hasBookings = !!bookingsByDate[dateStr]?.length
              const isSelected = dateStr === selectedDate
              const isToday = dateStr === todayStr

              return (
                <button
                  key={dateStr}
                  type="button"
                  onClick={() => setSelectedDate(dateStr)}
                  className={`flex h-10 flex-col items-center justify-center rounded-lg text-sm transition-colors ${
                    isSelected
                      ? 'bg-blue-600 text-white dark:bg-blue-500'
                      : isToday
                        ? 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400'
                        : 'text-gray-900 active:bg-gray-100 dark:text-gray-100 dark:active:bg-gray-700'
                  }`}
                  aria-label={`${day} ${MONTH_NAMES[viewMonth]}`}
                  aria-pressed={isSelected}
                >
                  {day}
                  {hasBookings && (
                    <span
                      className={`mt-0.5 h-1 w-1 rounded-full ${
                        isSelected ? 'bg-white' : 'bg-blue-500 dark:bg-blue-400'
                      }`}
                    />
                  )}
                </button>
              )
            })}
          </div>
        </MobileCard>

        {/* Selected day bookings */}
        <div>
          <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
            {selectedDate === todayStr ? 'Today' : selectedDate}
          </h2>
          {isLoading ? (
            <div className="flex justify-center py-4">
              <MobileSpinner size="sm" />
            </div>
          ) : selectedBookings.length === 0 ? (
            <p className="py-4 text-center text-sm text-gray-400 dark:text-gray-500">
              No bookings for this date
            </p>
          ) : (
            <div className="flex flex-col">
              {selectedBookings.map((booking) => (
                <MobileListItem
                  key={booking.id}
                  title={booking.customer_name ?? 'Unknown'}
                  subtitle={`${formatTime(booking.start_time)} · ${formatDuration(booking.duration_minutes)}${booking.service_type ? ` · ${booking.service_type}` : ''}`}
                  trailing={
                    <MobileBadge
                      label={booking.status ?? 'scheduled'}
                      variant={statusVariant[booking.status] ?? 'info'}
                    />
                  }
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </PullRefresh>
  )
}
