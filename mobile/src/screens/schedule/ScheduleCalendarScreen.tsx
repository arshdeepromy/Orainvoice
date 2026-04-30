import { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import {
  Page,
  Block,
  List,
  ListItem,
  Preloader,
} from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import KonstaFAB from '@/components/konsta/KonstaFAB'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface ScheduleEvent {
  id: string
  title: string
  date: string
  start_time: string | null
  end_time: string | null
  staff_name: string | null
  description: string | null
  type: string | null
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDateStr(d: Date): string {
  return d.toISOString().split('T')[0]
}

function getDaysInMonth(year: number, month: number): Date[] {
  const days: Date[] = []
  const date = new Date(year, month, 1)
  while (date.getMonth() === month) {
    days.push(new Date(date))
    date.setDate(date.getDate() + 1)
  }
  return days
}

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

function ScheduleContent() {
  const today = new Date()
  const [currentYear, setCurrentYear] = useState(today.getFullYear())
  const [currentMonth, setCurrentMonth] = useState(today.getMonth())
  const [selectedDate, setSelectedDate] = useState<string>(formatDateStr(today))

  const [events, setEvents] = useState<ScheduleEvent[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const fetchEvents = useCallback(
    async (isRefresh: boolean, signal: AbortSignal) => {
      if (isRefresh) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        const res = await apiClient.get<{ items?: ScheduleEvent[]; total?: number }>(
          '/api/v2/schedule',
          {
            params: {
              offset: 0,
              limit: 200,
              month: String(currentMonth + 1),
              year: String(currentYear),
            },
            signal,
          },
        )
        setEvents(res.data?.items ?? [])
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load schedule')
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [currentMonth, currentYear],
  )

  useEffect(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    fetchEvents(false, controller.signal)
    return () => controller.abort()
  }, [fetchEvents])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchEvents(true, controller.signal)
  }, [fetchEvents])

  const days = useMemo(() => getDaysInMonth(currentYear, currentMonth), [currentYear, currentMonth])

  const eventsByDate = useMemo(() => {
    const map = new Map<string, ScheduleEvent[]>()
    for (const event of events) {
      const d = event.date?.split('T')[0] ?? ''
      if (!map.has(d)) map.set(d, [])
      map.get(d)!.push(event)
    }
    return map
  }, [events])

  const selectedEvents = useMemo(
    () => eventsByDate.get(selectedDate) ?? [],
    [eventsByDate, selectedDate],
  )

  const prevMonth = useCallback(() => {
    if (currentMonth === 0) { setCurrentMonth(11); setCurrentYear((y) => y - 1) }
    else setCurrentMonth((m) => m - 1)
  }, [currentMonth])

  const nextMonth = useCallback(() => {
    if (currentMonth === 11) { setCurrentMonth(0); setCurrentYear((y) => y + 1) }
    else setCurrentMonth((m) => m + 1)
  }, [currentMonth])

  const monthLabel = new Date(currentYear, currentMonth).toLocaleDateString('en-NZ', {
    month: 'long',
    year: 'numeric',
  })

  const firstDayOfWeek = days[0]?.getDay() ?? 0

  if (isLoading && events.length === 0) {
    return (
      <Page data-testid="schedule-page">
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page data-testid="schedule-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          {/* Month navigation */}
          <div className="flex items-center justify-between px-4 pt-3">

          {error && (
            <Block><div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">{error}</div></Block>
          )}
            <button type="button" onClick={prevMonth} className="flex min-h-[44px] min-w-[44px] items-center justify-center text-gray-600 dark:text-gray-400" aria-label="Previous month">
              ‹
            </button>
            <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">{monthLabel}</span>
            <button type="button" onClick={nextMonth} className="flex min-h-[44px] min-w-[44px] items-center justify-center text-gray-600 dark:text-gray-400" aria-label="Next month">
              ›
            </button>
          </div>

          {/* Weekday headers */}
          <div className="grid grid-cols-7 gap-1 px-4 text-center">
            {WEEKDAYS.map((d) => (
              <span key={d} className="text-xs font-medium text-gray-500 dark:text-gray-400">{d}</span>
            ))}
          </div>

          {/* Calendar grid */}
          <div className="grid grid-cols-7 gap-1 px-4">
            {Array.from({ length: firstDayOfWeek }).map((_, i) => (
              <div key={`pad-${i}`} />
            ))}
            {days.map((day) => {
              const dateStr = formatDateStr(day)
              const hasEvents = eventsByDate.has(dateStr)
              const isSelected = dateStr === selectedDate
              const isToday = dateStr === formatDateStr(today)

              return (
                <button
                  key={dateStr}
                  type="button"
                  onClick={() => setSelectedDate(dateStr)}
                  className={`flex min-h-[40px] flex-col items-center justify-center rounded-lg text-sm transition-colors ${
                    isSelected
                      ? 'bg-blue-600 text-white'
                      : isToday
                        ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
                        : 'text-gray-900 active:bg-gray-100 dark:text-gray-100 dark:active:bg-gray-700'
                  }`}
                >
                  {day.getDate()}
                  {hasEvents && (
                    <span className={`mt-0.5 h-1 w-1 rounded-full ${isSelected ? 'bg-white' : 'bg-blue-600 dark:bg-blue-400'}`} />
                  )}
                </button>
              )
            })}
          </div>

          {/* Selected day events */}
          <Block>
            <p className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
              {new Date(selectedDate + 'T00:00:00').toLocaleDateString('en-NZ', {
                weekday: 'long',
                day: 'numeric',
                month: 'long',
              })}
            </p>
          </Block>

          {selectedEvents.length === 0 ? (
            <Block className="text-center">
              <p className="text-sm text-gray-400 dark:text-gray-500">No events</p>
            </Block>
          ) : (
            <List strongIos outlineIos dividersIos data-testid="schedule-events-list">
              {selectedEvents.map((event) => (
                <ListItem
                  key={event.id}
                  title={
                    <span className="font-medium text-gray-900 dark:text-gray-100">
                      {event.title ?? 'Event'}
                    </span>
                  }
                  subtitle={
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {event.start_time ?? ''}{event.end_time ? ` – ${event.end_time}` : ''}
                      {event.staff_name ? ` · ${event.staff_name}` : ''}
                    </span>
                  }
                  text={event.description ?? undefined}
                  data-testid={`schedule-event-${event.id}`}
                />
              ))}
            </List>
          )}
        </div>
      </PullRefresh>

      <KonstaFAB label="+ New Event" onClick={() => {/* open create sheet */}} />
    </Page>
  )
}

/**
 * Schedule screen — calendar view. ModuleGate `scheduling`.
 *
 * Requirements: 37.1, 37.2, 37.3, 55.1
 */
export default function ScheduleCalendarScreen() {
  return (
    <ModuleGate moduleSlug="scheduling">
      <ScheduleContent />
    </ModuleGate>
  )
}
