import { useState, useCallback, useMemo } from 'react'
import { useApiList } from '@/hooks/useApiList'
import { MobileCard, MobileButton, MobileInput, MobileSpinner } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'
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

function formatDate(d: Date): string {
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
/* New Event Form                                                     */
/* ------------------------------------------------------------------ */

function NewEventForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const [title, setTitle] = useState('')
  const [date, setDate] = useState(formatDate(new Date()))
  const [startTime, setStartTime] = useState('09:00')
  const [staff, setStaff] = useState('')
  const [description, setDescription] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    if (!title.trim()) {
      setError('Title is required')
      return
    }
    setIsSubmitting(true)
    setError(null)
    try {
      await apiClient.post('/api/v1/scheduling/events', {
        title: title.trim(),
        date,
        start_time: startTime,
        staff_name: staff.trim() || null,
        description: description.trim() || null,
      })
      onCreated()
    } catch {
      setError('Failed to create event')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <MobileCard>
      <h3 className="mb-3 text-lg font-semibold text-gray-900 dark:text-gray-100">New Event</h3>
      <div className="flex flex-col gap-3">
        <MobileInput label="Title" value={title} onChange={(e) => setTitle(e.target.value)} error={error ?? undefined} placeholder="Event title" />
        <MobileInput label="Date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        <MobileInput label="Time" type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} />
        <MobileInput label="Staff" value={staff} onChange={(e) => setStaff(e.target.value)} placeholder="Assigned staff" />
        <MobileInput label="Description" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional description" />
        <div className="flex gap-3">
          <MobileButton variant="secondary" size="sm" onClick={onCancel} disabled={isSubmitting}>
            Cancel
          </MobileButton>
          <MobileButton variant="primary" size="sm" onClick={handleSubmit} isLoading={isSubmitting}>
            Create
          </MobileButton>
        </div>
      </div>
    </MobileCard>
  )
}

/* ------------------------------------------------------------------ */
/* Schedule Calendar Screen                                           */
/* ------------------------------------------------------------------ */

function ScheduleCalendarContent() {
  const today = new Date()
  const [currentYear, setCurrentYear] = useState(today.getFullYear())
  const [currentMonth, setCurrentMonth] = useState(today.getMonth())
  const [selectedDate, setSelectedDate] = useState<string>(formatDate(today))
  const [showNewEvent, setShowNewEvent] = useState(false)

  const { items: events, isLoading, isRefreshing, refresh } = useApiList<ScheduleEvent>({
    endpoint: '/api/v1/scheduling/events',
    dataKey: 'items',
    pageSize: 200,
    initialFilters: {
      month: String(currentMonth + 1),
      year: String(currentYear),
    },
  })

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
    if (currentMonth === 0) {
      setCurrentMonth(11)
      setCurrentYear((y) => y - 1)
    } else {
      setCurrentMonth((m) => m - 1)
    }
  }, [currentMonth])

  const nextMonth = useCallback(() => {
    if (currentMonth === 11) {
      setCurrentMonth(0)
      setCurrentYear((y) => y + 1)
    } else {
      setCurrentMonth((m) => m + 1)
    }
  }, [currentMonth])

  const monthLabel = new Date(currentYear, currentMonth).toLocaleDateString('en-NZ', {
    month: 'long',
    year: 'numeric',
  })

  // Padding for first day of month
  const firstDayOfWeek = days[0]?.getDay() ?? 0

  if (isLoading && events.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Schedule</h1>
        <MobileButton variant="primary" size="sm" onClick={() => setShowNewEvent(true)}>
          + New Event
        </MobileButton>
      </div>

      {showNewEvent && (
        <NewEventForm
          onCreated={() => {
            setShowNewEvent(false)
            refresh()
          }}
          onCancel={() => setShowNewEvent(false)}
        />
      )}

      <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
        {/* Month navigation */}
        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={prevMonth}
            className="flex min-h-[44px] min-w-[44px] items-center justify-center text-gray-600 dark:text-gray-400"
            aria-label="Previous month"
          >
            ‹
          </button>
          <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">{monthLabel}</span>
          <button
            type="button"
            onClick={nextMonth}
            className="flex min-h-[44px] min-w-[44px] items-center justify-center text-gray-600 dark:text-gray-400"
            aria-label="Next month"
          >
            ›
          </button>
        </div>

        {/* Weekday headers */}
        <div className="grid grid-cols-7 gap-1 text-center">
          {WEEKDAYS.map((d) => (
            <span key={d} className="text-xs font-medium text-gray-500 dark:text-gray-400">
              {d}
            </span>
          ))}
        </div>

        {/* Calendar grid */}
        <div className="grid grid-cols-7 gap-1">
          {Array.from({ length: firstDayOfWeek }).map((_, i) => (
            <div key={`pad-${i}`} />
          ))}
          {days.map((day) => {
            const dateStr = formatDate(day)
            const hasEvents = eventsByDate.has(dateStr)
            const isSelected = dateStr === selectedDate
            const isToday = dateStr === formatDate(today)

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
                  <span
                    className={`mt-0.5 h-1 w-1 rounded-full ${isSelected ? 'bg-white' : 'bg-blue-600 dark:bg-blue-400'}`}
                  />
                )}
              </button>
            )
          })}
        </div>

        {/* Selected day events */}
        <div className="mt-4">
          <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
            {new Date(selectedDate + 'T00:00:00').toLocaleDateString('en-NZ', {
              weekday: 'long',
              day: 'numeric',
              month: 'long',
            })}
          </h2>
          {selectedEvents.length === 0 ? (
            <p className="text-sm text-gray-500 dark:text-gray-400">No events</p>
          ) : (
            <div className="flex flex-col gap-2">
              {selectedEvents.map((event) => (
                <MobileCard key={event.id}>
                  <div className="flex items-start justify-between">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                        {event.title ?? 'Event'}
                      </p>
                      {event.start_time && (
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          {event.start_time}{event.end_time ? ` – ${event.end_time}` : ''}
                        </p>
                      )}
                      {event.staff_name && (
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          {event.staff_name}
                        </p>
                      )}
                    </div>
                  </div>
                  {event.description && (
                    <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
                      {event.description}
                    </p>
                  )}
                </MobileCard>
              ))}
            </div>
          )}
        </div>
      </PullRefresh>
    </div>
  )
}

/**
 * Schedule calendar screen — calendar view with events, appointments, staff assignments.
 *
 * Requirements: 37.1, 37.2, 37.3, 37.4
 */
export default function ScheduleCalendarScreen() {
  return (
    <ModuleGate moduleSlug="scheduling">
      <ScheduleCalendarContent />
    </ModuleGate>
  )
}
