/**
 * Staff Roster View — shows each staff member as a column with their
 * jobs, bookings, breaks, and availability overlaid on a time grid.
 *
 * "Who's doing what today/this week?"
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type CalendarView = 'day' | 'week'

interface StaffMember {
  id: string
  name: string
  first_name: string
  last_name: string | null
  position: string | null
  is_active: boolean
  shift_start: string | null
  shift_end: string | null
  availability_schedule: Record<string, { start: string; end: string }>
}

export interface ScheduleEntry {
  id: string
  staff_id: string | null
  job_id: string | null
  booking_id: string | null
  title: string | null
  description: string | null
  start_time: string
  end_time: string
  entry_type: string
  status: string
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const ENTRY_COLOURS: Record<string, { bg: string; border: string; text: string }> = {
  job:     { bg: 'bg-blue-100',   border: 'border-blue-400',   text: 'text-blue-800' },
  booking: { bg: 'bg-emerald-100', border: 'border-emerald-400', text: 'text-emerald-800' },
  break:   { bg: 'bg-amber-100',  border: 'border-amber-400',  text: 'text-amber-800' },
  other:   { bg: 'bg-purple-100', border: 'border-purple-400', text: 'text-purple-800' },
}

const HOURS = Array.from({ length: 12 }, (_, i) => i + 7) // 7am–6pm

const DAY_KEYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

/* ------------------------------------------------------------------ */
/*  Date helpers                                                       */
/* ------------------------------------------------------------------ */

function addDays(date: Date, days: number): Date {
  const d = new Date(date)
  d.setDate(d.getDate() + days)
  return d
}

function startOfWeek(date: Date): Date {
  const d = new Date(date)
  const day = d.getDay()
  d.setDate(d.getDate() - (day === 0 ? 6 : day - 1)) // Monday start
  d.setHours(0, 0, 0, 0)
  return d
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
}

function formatDayShort(date: Date): string {
  return new Intl.DateTimeFormat('en-NZ', { weekday: 'short', day: 'numeric', month: 'short' }).format(date)
}

function formatTime(dateStr: string): string {
  return new Intl.DateTimeFormat('en-NZ', { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(dateStr))
}

function getDayKey(date: Date): string {
  return DAY_KEYS[date.getDay() === 0 ? 6 : date.getDay() - 1]
}


/* ------------------------------------------------------------------ */
/*  Entry card                                                         */
/* ------------------------------------------------------------------ */

function EntryCard({ entry }: { entry: ScheduleEntry }) {
  const colours = ENTRY_COLOURS[entry.entry_type] || ENTRY_COLOURS.other
  return (
    <div
      className={`${colours.bg} ${colours.text} border-l-2 ${colours.border} rounded px-1.5 py-0.5 text-xs leading-tight mb-0.5 truncate`}
      title={`${entry.title || entry.entry_type}\n${formatTime(entry.start_time)} – ${formatTime(entry.end_time)}${entry.description ? '\n' + entry.description : ''}`}
    >
      <span className="font-medium">{entry.title || entry.entry_type}</span>
      <span className="opacity-70 ml-1">{formatTime(entry.start_time)}</span>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Availability indicator                                             */
/* ------------------------------------------------------------------ */

function isStaffAvailable(
  staff: StaffMember,
  date: Date,
  hour: number,
): boolean {
  const dayKey = getDayKey(date)
  const sched = staff.availability_schedule?.[dayKey]
  if (!sched) return false
  const startHour = parseInt(sched.start?.split(':')[0] || '0', 10)
  const endHour = parseInt(sched.end?.split(':')[0] || '0', 10)
  return hour >= startHour && hour < endHour
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export default function ScheduleCalendar() {
  const [view, setView] = useState<CalendarView>('day')
  const [currentDate, setCurrentDate] = useState(new Date())
  const [staff, setStaff] = useState<StaffMember[]>([])
  const [entries, setEntries] = useState<ScheduleEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedStaffId, setSelectedStaffId] = useState<string>('')

  // Fetch active staff
  const fetchStaff = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/staff', { params: { is_active: true, page_size: 100 } })
      setStaff(res.data.staff || [])
    } catch {
      setStaff([])
    }
  }, [])

  // Fetch schedule entries for the visible range
  const fetchEntries = useCallback(async () => {
    setLoading(true)
    try {
      let rangeStart: Date
      let rangeEnd: Date
      if (view === 'day') {
        rangeStart = new Date(currentDate)
        rangeStart.setHours(0, 0, 0, 0)
        rangeEnd = addDays(rangeStart, 1)
      } else {
        rangeStart = startOfWeek(currentDate)
        rangeEnd = addDays(rangeStart, 7)
      }
      const params: Record<string, string> = {
        start: rangeStart.toISOString(),
        end: rangeEnd.toISOString(),
      }
      if (selectedStaffId) params.staff_id = selectedStaffId
      const res = await apiClient.get('/api/v2/schedule', { params })
      setEntries(res.data.entries || [])
    } catch {
      setEntries([])
    } finally {
      setLoading(false)
    }
  }, [view, currentDate, selectedStaffId])

  useEffect(() => { fetchStaff() }, [fetchStaff])
  useEffect(() => { fetchEntries() }, [fetchEntries])

  const navigate = (dir: number) => {
    if (view === 'day') setCurrentDate(addDays(currentDate, dir))
    else setCurrentDate(addDays(currentDate, dir * 7))
  }

  // Filter staff to show
  const visibleStaff = useMemo(() => {
    if (selectedStaffId) return staff.filter(s => s.id === selectedStaffId)
    return staff
  }, [staff, selectedStaffId])

  // Get entries for a specific staff + day + hour
  const getSlotEntries = useCallback((staffId: string, date: Date, hour: number) => {
    return entries.filter(e => {
      if (e.staff_id !== staffId) return false
      const d = new Date(e.start_time)
      return isSameDay(d, date) && d.getHours() === hour
    })
  }, [entries])

  const today = new Date()
  const isToday = (d: Date) => isSameDay(d, today)

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between mb-3">
          <h1 className="text-xl font-semibold text-gray-900">Staff Roster</h1>
          <div className="flex items-center gap-2">
            <button
              onClick={() => navigate(-1)}
              className="p-1.5 rounded hover:bg-gray-100 text-gray-600"
              aria-label="Previous"
            >
              ←
            </button>
            <button
              onClick={() => setCurrentDate(new Date())}
              className="px-3 py-1 text-sm rounded border border-gray-300 hover:bg-gray-50"
            >
              Today
            </button>
            <button
              onClick={() => navigate(1)}
              className="p-1.5 rounded hover:bg-gray-100 text-gray-600"
              aria-label="Next"
            >
              →
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-4">
          {/* View toggle */}
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-600">View</label>
            <select
              value={view}
              onChange={e => setView(e.target.value as CalendarView)}
              className="rounded border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="day">Day</option>
              <option value="week">Week</option>
            </select>
          </div>

          {/* Staff filter */}
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-600">Staff</label>
            <select
              value={selectedStaffId}
              onChange={e => setSelectedStaffId(e.target.value)}
              className="rounded border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="">All Staff</option>
              {staff.map(s => (
                <option key={s.id} value={s.id}>{s.name}{s.position ? ` — ${s.position}` : ''}</option>
              ))}
            </select>
          </div>

          {/* Legend */}
          <div className="flex items-center gap-3 ml-auto">
            {Object.entries(ENTRY_COLOURS).map(([type, c]) => (
              <span key={type} className="flex items-center gap-1 text-xs text-gray-600">
                <span className={`w-2.5 h-2.5 rounded-sm ${c.bg} border ${c.border}`} />
                {type}
              </span>
            ))}
            <span className="flex items-center gap-1 text-xs text-gray-600">
              <span className="w-2.5 h-2.5 rounded-sm bg-green-50 border border-green-200" />
              available
            </span>
          </div>
        </div>
      </div>

      {/* Grid */}
      <div className="flex-1 overflow-auto px-6 py-4">
        {loading && entries.length === 0 ? (
          <div className="py-16 text-center text-gray-500">Loading roster…</div>
        ) : visibleStaff.length === 0 ? (
          <div className="py-16 text-center">
            <p className="text-gray-500">No staff members found.</p>
            <p className="text-sm text-gray-400 mt-1">Add staff in the Staff page first.</p>
          </div>
        ) : view === 'day' ? (
          <DayRoster
            staff={visibleStaff}
            date={currentDate}
            getSlotEntries={getSlotEntries}
            isToday={isToday}
            isStaffAvailable={isStaffAvailable}
          />
        ) : (
          <WeekRoster
            staff={visibleStaff}
            currentDate={currentDate}
            getSlotEntries={getSlotEntries}
            isToday={isToday}
            isStaffAvailable={isStaffAvailable}
          />
        )}
      </div>
    </div>
  )
}


/* ------------------------------------------------------------------ */
/*  Day Roster — staff as columns, hours as rows                       */
/* ------------------------------------------------------------------ */

interface RosterProps {
  staff: StaffMember[]
  getSlotEntries: (staffId: string, date: Date, hour: number) => ScheduleEntry[]
  isToday: (d: Date) => boolean
  isStaffAvailable: (staff: StaffMember, date: Date, hour: number) => boolean
}

function DayRoster({
  staff, date, getSlotEntries, isToday, isStaffAvailable,
}: RosterProps & { date: Date }) {
  return (
    <div className="overflow-x-auto">
      <div className="text-sm font-medium text-gray-700 mb-3">
        {formatDayShort(date)}
        {isToday(date) && <span className="ml-2 text-xs text-blue-600 font-normal">(Today)</span>}
      </div>
      <table className="min-w-full border-collapse">
        <thead>
          <tr>
            <th className="w-16 px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase border-b border-gray-200">
              Time
            </th>
            {staff.map(s => (
              <th
                key={s.id}
                className="px-2 py-2 text-left text-xs font-medium text-gray-700 border-b border-gray-200 min-w-[140px]"
              >
                <div>{s.name}</div>
                {s.position && <div className="font-normal text-gray-400">{s.position}</div>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {HOURS.map(hour => (
            <tr key={hour} className="border-b border-gray-100">
              <td className="px-2 py-1 text-xs text-gray-400 align-top whitespace-nowrap">
                {String(hour).padStart(2, '0')}:00
              </td>
              {staff.map(s => {
                const slotEntries = getSlotEntries(s.id, date, hour)
                const available = isStaffAvailable(s, date, hour)
                return (
                  <td
                    key={s.id}
                    className={`px-1 py-1 align-top border-l border-gray-100 min-h-[40px] ${
                      available ? 'bg-green-50/50' : ''
                    }`}
                  >
                    {slotEntries.map(e => (
                      <EntryCard key={e.id} entry={e} />
                    ))}
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
/*  Week Roster — one day per row, staff as columns                    */
/* ------------------------------------------------------------------ */

function WeekRoster({
  staff, currentDate, getSlotEntries, isToday,
}: RosterProps & { currentDate: Date }) {
  const weekStart = startOfWeek(currentDate)
  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i))

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-collapse">
        <thead>
          <tr>
            <th className="w-28 px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase border-b border-gray-200">
              Day
            </th>
            {staff.map(s => (
              <th
                key={s.id}
                className="px-2 py-2 text-left text-xs font-medium text-gray-700 border-b border-gray-200 min-w-[160px]"
              >
                <div>{s.name}</div>
                {s.position && <div className="font-normal text-gray-400">{s.position}</div>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {days.map(day => {
            const dayKey = getDayKey(day)
            return (
              <tr
                key={day.toISOString()}
                className={`border-b border-gray-100 ${isToday(day) ? 'bg-blue-50/40' : ''}`}
              >
                <td className="px-2 py-2 text-sm text-gray-700 align-top whitespace-nowrap">
                  <div className="font-medium">{formatDayShort(day)}</div>
                  {isToday(day) && <span className="text-xs text-blue-600">Today</span>}
                </td>
                {staff.map(s => {
                  const sched = s.availability_schedule?.[dayKey]
                  // Collect all entries for this staff on this day
                  const dayEntries = HOURS.flatMap(h => getSlotEntries(s.id, day, h))
                  // Deduplicate (an entry might span hours)
                  const seen = new Set<string>()
                  const unique = dayEntries.filter(e => {
                    if (seen.has(e.id)) return false
                    seen.add(e.id)
                    return true
                  })

                  return (
                    <td
                      key={s.id}
                      className={`px-2 py-2 align-top border-l border-gray-100 ${
                        sched ? 'bg-green-50/30' : 'bg-gray-50/50'
                      }`}
                    >
                      {/* Shift hours */}
                      {sched && (
                        <div className="text-xs text-gray-400 mb-1">
                          {sched.start} – {sched.end}
                        </div>
                      )}
                      {!sched && (
                        <div className="text-xs text-gray-300 italic mb-1">Off</div>
                      )}
                      {/* Entries */}
                      {unique.map(e => (
                        <EntryCard key={e.id} entry={e} />
                      ))}
                      {unique.length === 0 && sched && (
                        <div className="text-xs text-gray-300 italic">No entries</div>
                      )}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
