/**
 * Schedule calendar with day/week/month views, drag-and-drop reschedule,
 * staff and location filters, colour-coded by entry type.
 *
 * Validates: Requirement 18 — Scheduling Module
 */

import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type CalendarView = 'day' | 'week' | 'month'

export interface ScheduleEntry {
  id: string
  org_id: string
  staff_id: string | null
  job_id: string | null
  booking_id: string | null
  location_id: string | null
  title: string | null
  description: string | null
  start_time: string
  end_time: string
  entry_type: string
  status: string
  notes: string | null
}

interface ScheduleListResponse {
  entries: ScheduleEntry[]
  total: number
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const VIEW_OPTIONS: { value: CalendarView; label: string }[] = [
  { value: 'day', label: 'Day' },
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
]

const ENTRY_TYPE_COLOURS: Record<string, string> = {
  job: '#3b82f6',
  booking: '#10b981',
  break: '#f59e0b',
  other: '#8b5cf6',
}

const HOURS = Array.from({ length: 13 }, (_, i) => i + 7) // 7am–7pm

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function addDays(date: Date, days: number): Date {
  const d = new Date(date)
  d.setDate(d.getDate() + days)
  return d
}

function startOfWeek(date: Date): Date {
  const d = new Date(date)
  const day = d.getDay()
  const diff = day === 0 ? -6 : 1 - day
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
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

function formatDayHeader(date: Date): string {
  return new Intl.DateTimeFormat('en-NZ', {
    weekday: 'short', day: 'numeric', month: 'short',
  }).format(date)
}

function formatTime(dateStr: string): string {
  return new Intl.DateTimeFormat('en-NZ', {
    hour: '2-digit', minute: '2-digit', hour12: true,
  }).format(new Date(dateStr))
}

function getEntriesForSlot(
  entries: ScheduleEntry[], date: Date, hour: number,
): ScheduleEntry[] {
  return entries.filter((e) => {
    const d = new Date(e.start_time)
    return isSameDay(d, date) && d.getHours() === hour
  })
}

function getEntriesForDay(entries: ScheduleEntry[], date: Date): ScheduleEntry[] {
  return entries.filter((e) => isSameDay(new Date(e.start_time), date))
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export default function ScheduleCalendar() {
  const [view, setView] = useState<CalendarView>('week')
  const [currentDate, setCurrentDate] = useState(new Date())
  const [entries, setEntries] = useState<ScheduleEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [staffFilter, setStaffFilter] = useState('')
  const [locationFilter, setLocationFilter] = useState('')
  const [dragEntry, setDragEntry] = useState<string | null>(null)

  const fetchEntries = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      let rangeStart: Date
      let rangeEnd: Date

      if (view === 'day') {
        rangeStart = new Date(currentDate)
        rangeStart.setHours(0, 0, 0, 0)
        rangeEnd = addDays(rangeStart, 1)
      } else if (view === 'week') {
        rangeStart = startOfWeek(currentDate)
        rangeEnd = addDays(rangeStart, 7)
      } else {
        rangeStart = startOfMonth(currentDate)
        rangeEnd = addDays(endOfMonth(currentDate), 1)
      }

      params.set('start', rangeStart.toISOString())
      params.set('end', rangeEnd.toISOString())
      if (staffFilter) params.set('staff_id', staffFilter)
      if (locationFilter) params.set('location_id', locationFilter)

      const res = await apiClient.get(`/api/v2/schedule?${params}`)
      setEntries(res.data.entries)
    } catch {
      setEntries([])
    } finally {
      setLoading(false)
    }
  }, [view, currentDate, staffFilter, locationFilter])

  useEffect(() => { fetchEntries() }, [fetchEntries])

  const navigate = (direction: number) => {
    if (view === 'day') setCurrentDate(addDays(currentDate, direction))
    else if (view === 'week') setCurrentDate(addDays(currentDate, direction * 7))
    else {
      const d = new Date(currentDate)
      d.setMonth(d.getMonth() + direction)
      setCurrentDate(d)
    }
  }

  const handleDragStart = (entryId: string) => {
    setDragEntry(entryId)
  }

  const handleDrop = async (date: Date, hour: number) => {
    if (!dragEntry) return
    const entry = entries.find((e) => e.id === dragEntry)
    if (!entry) return

    const oldStart = new Date(entry.start_time)
    const oldEnd = new Date(entry.end_time)
    const durationMs = oldEnd.getTime() - oldStart.getTime()

    const newStart = new Date(date)
    newStart.setHours(hour, 0, 0, 0)
    const newEnd = new Date(newStart.getTime() + durationMs)

    try {
      await apiClient.put(`/api/v2/schedule/${dragEntry}/reschedule`, {
        start_time: newStart.toISOString(),
        end_time: newEnd.toISOString(),
      })
      await fetchEntries()
    } catch {
      // Reschedule failed — keep current state
    }
    setDragEntry(null)
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
  }

  if (loading) {
    return <div role="status" aria-label="Loading schedule">Loading schedule…</div>
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h1>Schedule</h1>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <button onClick={() => navigate(-1)} aria-label="Previous period">←</button>
          <button onClick={() => setCurrentDate(new Date())} aria-label="Go to today">Today</button>
          <button onClick={() => navigate(1)} aria-label="Next period">→</button>
        </div>
      </div>

      {/* Filters and view selector */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        <div>
          <label htmlFor="view-select">View</label>
          <select
            id="view-select"
            value={view}
            onChange={(e) => setView(e.target.value as CalendarView)}
          >
            {VIEW_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="staff-filter">Staff</label>
          <input
            id="staff-filter"
            type="text"
            placeholder="Staff ID"
            value={staffFilter}
            onChange={(e) => setStaffFilter(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="location-filter">Location</label>
          <input
            id="location-filter"
            type="text"
            placeholder="Location ID"
            value={locationFilter}
            onChange={(e) => setLocationFilter(e.target.value)}
          />
        </div>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }} aria-label="Entry type legend">
        {Object.entries(ENTRY_TYPE_COLOURS).map(([type, colour]) => (
          <span key={type} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
            <span style={{ width: 12, height: 12, borderRadius: 2, background: colour, display: 'inline-block' }} />
            {type}
          </span>
        ))}
      </div>

      {/* Calendar views */}
      {view === 'day' && (
        <DayView
          entries={entries}
          currentDate={currentDate}
          onDragStart={handleDragStart}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
        />
      )}
      {view === 'week' && (
        <WeekView
          entries={entries}
          currentDate={currentDate}
          onDragStart={handleDragStart}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
        />
      )}
      {view === 'month' && (
        <MonthView
          entries={entries}
          currentDate={currentDate}
          onDragStart={handleDragStart}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
        />
      )}
    </div>
  )
}


/* ------------------------------------------------------------------ */
/*  Entry card                                                         */
/* ------------------------------------------------------------------ */

function EntryCard({
  entry,
  compact = false,
  onDragStart,
}: {
  entry: ScheduleEntry
  compact?: boolean
  onDragStart: (id: string) => void
}) {
  const colour = ENTRY_TYPE_COLOURS[entry.entry_type] || ENTRY_TYPE_COLOURS.other

  return (
    <div
      draggable
      onDragStart={() => onDragStart(entry.id)}
      role="listitem"
      aria-label={`${entry.title || entry.entry_type} entry`}
      style={{
        background: colour + '22',
        borderLeft: `3px solid ${colour}`,
        padding: compact ? '2px 4px' : '4px 8px',
        borderRadius: 4,
        fontSize: compact ? '0.75rem' : '0.85rem',
        cursor: 'grab',
        marginBottom: 2,
      }}
    >
      <strong>{entry.title || entry.entry_type}</strong>
      {!compact && (
        <div style={{ fontSize: '0.75rem', opacity: 0.8 }}>
          {formatTime(entry.start_time)} – {formatTime(entry.end_time)}
        </div>
      )}
    </div>
  )
}


/* ------------------------------------------------------------------ */
/*  View props                                                         */
/* ------------------------------------------------------------------ */

interface ViewProps {
  entries: ScheduleEntry[]
  currentDate: Date
  onDragStart: (id: string) => void
  onDrop: (date: Date, hour: number) => void
  onDragOver: (e: React.DragEvent) => void
}

/* ------------------------------------------------------------------ */
/*  Day view                                                           */
/* ------------------------------------------------------------------ */

function DayView({ entries, currentDate, onDragStart, onDrop, onDragOver }: ViewProps) {
  return (
    <div role="grid" aria-label="Day schedule view">
      <h2>{formatDayHeader(currentDate)}</h2>
      {HOURS.map((hour) => {
        const slotEntries = getEntriesForSlot(entries, currentDate, hour)
        return (
          <div
            key={hour}
            role="row"
            style={{ display: 'flex', borderBottom: '1px solid #e5e7eb', minHeight: 48 }}
            onDragOver={onDragOver}
            onDrop={() => onDrop(currentDate, hour)}
          >
            <div style={{ width: 60, padding: '4px 8px', fontSize: '0.8rem', color: '#6b7280' }}>
              {hour}:00
            </div>
            <div style={{ flex: 1, padding: 2 }} role="gridcell">
              {slotEntries.map((e) => (
                <EntryCard key={e.id} entry={e} onDragStart={onDragStart} />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}


/* ------------------------------------------------------------------ */
/*  Week view                                                          */
/* ------------------------------------------------------------------ */

function WeekView({ entries, currentDate, onDragStart, onDrop, onDragOver }: ViewProps) {
  const weekStart = startOfWeek(currentDate)
  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i))

  return (
    <div role="grid" aria-label="Week schedule view" style={{ overflowX: 'auto' }}>
      {/* Header row */}
      <div style={{ display: 'flex' }} role="row">
        <div style={{ width: 60 }} />
        {days.map((day) => (
          <div
            key={day.toISOString()}
            role="columnheader"
            style={{ flex: 1, textAlign: 'center', fontWeight: 600, padding: 4, fontSize: '0.85rem' }}
          >
            {formatDayHeader(day)}
          </div>
        ))}
      </div>

      {/* Time slots */}
      {HOURS.map((hour) => (
        <div key={hour} style={{ display: 'flex', borderBottom: '1px solid #e5e7eb', minHeight: 48 }} role="row">
          <div style={{ width: 60, padding: '4px 8px', fontSize: '0.8rem', color: '#6b7280' }}>
            {hour}:00
          </div>
          {days.map((day) => {
            const slotEntries = getEntriesForSlot(entries, day, hour)
            return (
              <div
                key={day.toISOString()}
                role="gridcell"
                style={{ flex: 1, borderLeft: '1px solid #e5e7eb', padding: 2 }}
                onDragOver={onDragOver}
                onDrop={() => onDrop(day, hour)}
              >
                {slotEntries.map((e) => (
                  <EntryCard key={e.id} entry={e} compact onDragStart={onDragStart} />
                ))}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}


/* ------------------------------------------------------------------ */
/*  Month view                                                         */
/* ------------------------------------------------------------------ */

function MonthView({ entries, currentDate, onDragStart, onDrop, onDragOver }: ViewProps) {
  const monthStart = startOfMonth(currentDate)
  const monthEnd = endOfMonth(currentDate)
  const calStart = startOfWeek(monthStart)

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
    if (cursor > monthEnd && cursor.getDay() === 1) break
  }

  return (
    <div role="grid" aria-label="Month schedule view">
      {/* Day-of-week headers */}
      <div style={{ display: 'flex' }} role="row">
        {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => (
          <div key={d} role="columnheader" style={{ flex: 1, textAlign: 'center', fontWeight: 600, padding: 4 }}>
            {d}
          </div>
        ))}
      </div>

      {weeks.map((week, wi) => (
        <div key={wi} style={{ display: 'flex', borderBottom: '1px solid #e5e7eb' }} role="row">
          {week.map((day) => {
            const dayEntries = getEntriesForDay(entries, day)
            const isCurrentMonth = day.getMonth() === currentDate.getMonth()
            return (
              <div
                key={day.toISOString()}
                role="gridcell"
                style={{
                  flex: 1,
                  minHeight: 80,
                  padding: 4,
                  borderLeft: '1px solid #e5e7eb',
                  opacity: isCurrentMonth ? 1 : 0.4,
                }}
                onDragOver={onDragOver}
                onDrop={() => onDrop(day, 9)}
              >
                <div style={{ fontSize: '0.8rem', fontWeight: 500, marginBottom: 2 }}>
                  {day.getDate()}
                </div>
                {dayEntries.slice(0, 3).map((e) => (
                  <EntryCard key={e.id} entry={e} compact onDragStart={onDragStart} />
                ))}
                {dayEntries.length > 3 && (
                  <div style={{ fontSize: '0.7rem', color: '#6b7280' }}>
                    +{dayEntries.length - 3} more
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}
