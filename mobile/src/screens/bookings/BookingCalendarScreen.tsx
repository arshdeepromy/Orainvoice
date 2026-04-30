import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Block,
  BlockTitle,
  Card,
  List,
  ListItem,
  ListInput,
  Button,
  Preloader,
  Sheet,
} from 'konsta/react'
import type { Booking } from '@shared/types/booking'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import StatusBadge from '@/components/konsta/StatusBadge'
import KonstaFAB from '@/components/konsta/KonstaFAB'
import HapticButton from '@/components/konsta/HapticButton'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatTime(timeStr: string): string {
  if (!timeStr) return ''
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

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */

/**
 * Booking calendar screen — calendar view + list of bookings for selected date.
 * FAB for "+ New Booking". Tap booking opens edit sheet.
 * "Create Job from Booking" action. Long-press menu for rescheduling.
 *
 * Requirements: 30.1, 30.2, 30.3, 30.4, 30.5, 30.6
 */
export default function BookingCalendarScreen() {
  const navigate = useNavigate()
  const today = new Date()
  const [viewYear, setViewYear] = useState(today.getFullYear())
  const [viewMonth, setViewMonth] = useState(today.getMonth())
  const [selectedDate, setSelectedDate] = useState<string>(
    today.toISOString().split('T')[0],
  )

  const [bookings, setBookings] = useState<Booking[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Edit sheet state
  const [editBooking, setEditBooking] = useState<Booking | null>(null)
  const [showEditSheet, setShowEditSheet] = useState(false)
  const [rescheduleDate, setRescheduleDate] = useState('')
  const [isActionLoading, setIsActionLoading] = useState(false)
  const [toast, setToast] = useState<{ message: string; variant: 'success' | 'error' } | null>(null)

  // Long-press state
  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  // ── Fetch bookings ─────────────────────────────────────────────────
  const fetchBookings = useCallback(
    async (signal: AbortSignal, refresh = false) => {
      if (refresh) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        const res = await apiClient.get<{ items?: Booking[]; total?: number }>(
          '/api/v1/bookings',
          { params: { limit: 200 }, signal },
        )
        setBookings(res.data?.items ?? [])
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load bookings')
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [],
  )

  useEffect(() => {
    const controller = new AbortController()
    abortRef.current = controller
    fetchBookings(controller.signal)
    return () => controller.abort()
  }, [fetchBookings])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchBookings(controller.signal, true)
  }, [fetchBookings])

  // ── Group bookings by date ─────────────────────────────────────────
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

  // ── Month navigation ───────────────────────────────────────────────
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

  // ── Calendar grid ──────────────────────────────────────────────────
  const daysInMonth = getDaysInMonth(viewYear, viewMonth)
  const firstDay = getFirstDayOfMonth(viewYear, viewMonth)
  const todayStr = today.toISOString().split('T')[0]

  const calendarDays: (number | null)[] = []
  for (let i = 0; i < firstDay; i++) calendarDays.push(null)
  for (let d = 1; d <= daysInMonth; d++) calendarDays.push(d)

  // ── Booking actions ────────────────────────────────────────────────
  const handleBookingTap = useCallback((booking: Booking) => {
    setEditBooking(booking)
    setRescheduleDate(booking.date?.split('T')[0] ?? '')
    setShowEditSheet(true)
  }, [])

  const handleLongPress = useCallback((booking: Booking) => {
    setEditBooking(booking)
    setRescheduleDate(booking.date?.split('T')[0] ?? '')
    setShowEditSheet(true)
  }, [])

  const handleReschedule = useCallback(async () => {
    if (!editBooking || !rescheduleDate) return
    setIsActionLoading(true)
    try {
      await apiClient.put(`/api/v1/bookings/${editBooking.id}`, {
        ...editBooking,
        date: rescheduleDate,
      })
      setToast({ message: 'Booking rescheduled', variant: 'success' })
      setShowEditSheet(false)
      await handleRefresh()
    } catch {
      setToast({ message: 'Failed to reschedule', variant: 'error' })
    } finally {
      setIsActionLoading(false)
    }
  }, [editBooking, rescheduleDate, handleRefresh])

  const handleCreateJobFromBooking = useCallback(async () => {
    if (!editBooking) return
    setIsActionLoading(true)
    try {
      const res = await apiClient.post('/api/v1/job-cards', {
        customer_id: editBooking.customer_id,
        description: editBooking.service_type ?? `Booking on ${editBooking.date}`,
      })
      const jobId = res.data?.id
      setShowEditSheet(false)
      if (jobId) navigate(`/job-cards/${jobId}`)
    } catch {
      setToast({ message: 'Failed to create job', variant: 'error' })
    } finally {
      setIsActionLoading(false)
    }
  }, [editBooking, navigate])

  const handleDeleteBooking = useCallback(async () => {
    if (!editBooking) return
    setIsActionLoading(true)
    try {
      await apiClient.delete(`/api/v1/bookings/${editBooking.id}`)
      setToast({ message: 'Booking deleted', variant: 'success' })
      setShowEditSheet(false)
      await handleRefresh()
    } catch {
      setToast({ message: 'Failed to delete booking', variant: 'error' })
    } finally {
      setIsActionLoading(false)
    }
  }, [editBooking, handleRefresh])

  return (
    <ModuleGate moduleSlug="bookings">
      <Page data-testid="booking-calendar-page">
        <KonstaNavbar title="Bookings" />

        <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
          <div className="flex flex-col pb-24">
            {/* Toast */}
            {toast && (
              <Block>
                <div
                  className={`rounded-lg p-3 text-sm ${
                    toast.variant === 'success'
                      ? 'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300'
                      : 'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300'
                  }`}
                  role="alert"
                >
                  {toast.message}
                  <button type="button" className="ml-2 text-xs underline" onClick={() => setToast(null)}>
                    Dismiss
                  </button>
                </div>
              </Block>
            )}

            {/* Error */}
            {error && (
              <Block>
                <div
                  role="alert"
                  className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
                >
                  {error}
                  <button type="button" onClick={() => handleRefresh()} className="ml-2 font-medium underline">
                    Retry
                  </button>
                </div>
              </Block>
            )}

            {/* ── Calendar ──────────────────────────────────────────── */}
            <Card className="mx-4 mt-2" data-testid="booking-calendar">
              {/* Month navigation */}
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
                          ? 'bg-primary text-white'
                          : isToday
                            ? 'bg-primary/10 text-primary'
                            : 'text-gray-900 active:bg-gray-100 dark:text-gray-100 dark:active:bg-gray-700'
                      }`}
                      aria-label={`${day} ${MONTH_NAMES[viewMonth]}`}
                      aria-pressed={isSelected}
                    >
                      {day}
                      {hasBookings && (
                        <span
                          className={`mt-0.5 h-1 w-1 rounded-full ${
                            isSelected ? 'bg-white' : 'bg-primary'
                          }`}
                        />
                      )}
                    </button>
                  )
                })}
              </div>
            </Card>

            {/* ── Selected day bookings ──────────────────────────────── */}
            <BlockTitle>
              {selectedDate === todayStr ? 'Today' : selectedDate}
            </BlockTitle>

            {isLoading ? (
              <div className="flex justify-center py-4">
                <Preloader />
              </div>
            ) : selectedBookings.length === 0 ? (
              <Block>
                <p className="text-center text-sm text-gray-400 dark:text-gray-500">
                  No bookings for this date
                </p>
              </Block>
            ) : (
              <List strongIos outlineIos dividersIos data-testid="booking-list">
                {selectedBookings.map((booking) => (
                  <ListItem
                    key={booking.id}
                    link
                    onClick={() => handleBookingTap(booking)}
                    onMouseDown={() => {
                      longPressTimerRef.current = setTimeout(() => {
                        handleLongPress(booking)
                      }, 500)
                    }}
                    onMouseUp={() => {
                      if (longPressTimerRef.current) {
                        clearTimeout(longPressTimerRef.current)
                        longPressTimerRef.current = null
                      }
                    }}
                    onTouchStart={() => {
                      longPressTimerRef.current = setTimeout(() => {
                        handleLongPress(booking)
                      }, 500)
                    }}
                    onTouchEnd={() => {
                      if (longPressTimerRef.current) {
                        clearTimeout(longPressTimerRef.current)
                        longPressTimerRef.current = null
                      }
                    }}
                    title={
                      <span className="font-medium text-gray-900 dark:text-gray-100">
                        {booking.customer_name ?? 'Unknown'}
                      </span>
                    }
                    subtitle={
                      <span className="text-xs text-gray-500 dark:text-gray-400">
                        {formatTime(booking.start_time)} · {formatDuration(booking.duration_minutes)}
                        {booking.service_type ? ` · ${booking.service_type}` : ''}
                      </span>
                    }
                    after={
                      <StatusBadge status={booking.status ?? 'scheduled'} size="sm" />
                    }
                  />
                ))}
              </List>
            )}
          </div>
        </PullRefresh>

        {/* ── FAB: + New Booking ─────────────────────────────────────── */}
        <KonstaFAB
          label="+ New Booking"
          onClick={() => navigate('/bookings/new')}
        />

        {/* ── Edit/Reschedule Sheet ──────────────────────────────────── */}
        <Sheet
          opened={showEditSheet}
          onBackdropClick={() => setShowEditSheet(false)}
          data-testid="booking-edit-sheet"
        >
          <div className="p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                Booking Details
              </h3>
              <Button clear small onClick={() => setShowEditSheet(false)}>
                Close
              </Button>
            </div>

            {editBooking && (
              <div className="mt-3 flex flex-col gap-3">
                <div className="text-sm">
                  <p className="font-medium text-gray-900 dark:text-gray-100">
                    {editBooking.customer_name ?? 'Unknown'}
                  </p>
                  <p className="text-gray-500 dark:text-gray-400">
                    {formatTime(editBooking.start_time)} · {formatDuration(editBooking.duration_minutes)}
                  </p>
                  {editBooking.service_type && (
                    <p className="text-gray-500 dark:text-gray-400">{editBooking.service_type}</p>
                  )}
                  {editBooking.notes && (
                    <p className="mt-1 text-gray-500 dark:text-gray-400">{editBooking.notes}</p>
                  )}
                </div>

                {/* Reschedule date picker */}
                <BlockTitle className="mt-2">Reschedule</BlockTitle>
                <List strongIos outlineIos>
                  <ListInput
                    label="New Date"
                    type="date"
                    value={rescheduleDate}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                      setRescheduleDate(e.target.value)
                    }
                  />
                </List>

                <div className="flex flex-col gap-2">
                  <HapticButton
                    large
                    onClick={handleReschedule}
                    disabled={isActionLoading}
                    className="w-full"
                  >
                    {isActionLoading ? 'Saving…' : 'Reschedule'}
                  </HapticButton>
                  <Button
                    outline
                    large
                    onClick={handleCreateJobFromBooking}
                    disabled={isActionLoading}
                    className="w-full"
                  >
                    Create Job from Booking
                  </Button>
                  <Button
                    outline
                    large
                    onClick={handleDeleteBooking}
                    disabled={isActionLoading}
                    className="w-full text-red-500 border-red-500"
                  >
                    Delete Booking
                  </Button>
                </div>
              </div>
            )}
          </div>
        </Sheet>
      </Page>
    </ModuleGate>
  )
}
