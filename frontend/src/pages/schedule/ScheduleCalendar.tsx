/**
 * Staff Roster View — shows each staff member as a column with their
 * jobs, bookings, breaks, and availability overlaid on a time grid.
 *
 * Supports drag-and-drop rescheduling of entries between time slots
 * and staff columns using @dnd-kit/core.
 *
 * "Who's doing what today/this week?"
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  useDraggable,
  useDroppable,
} from '@dnd-kit/core'
import type { DragEndEvent } from '@dnd-kit/core'
import apiClient from '@/api/client'
import ScheduleEntryModal from './ScheduleEntryModal'
import ShiftTemplates from './ShiftTemplates'

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
  recurrence_group_id: string | null
}

/** Data encoded in each droppable slot ID */
interface SlotData {
  staffId: string
  date: string // ISO date string (YYYY-MM-DD)
  hour: number
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const ENTRY_COLOURS: Record<string, { bg: string; border: string; text: string }> = {
  job:     { bg: 'bg-blue-100',   border: 'border-blue-400',   text: 'text-blue-800' },
  booking: { bg: 'bg-emerald-100', border: 'border-emerald-400', text: 'text-emerald-800' },
  break:   { bg: 'bg-amber-100',  border: 'border-amber-400',  text: 'text-amber-800' },
  leave:   { bg: 'bg-gray-200',   border: 'border-gray-400',   text: 'text-gray-600' },
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

/** Format a Date as YYYY-MM-DD for slot ID encoding */
function toDateKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

/* ------------------------------------------------------------------ */
/*  Slot ID encoding / decoding                                        */
/* ------------------------------------------------------------------ */

/** Encode a droppable slot ID: "slot:{staffId}:{dateKey}:{hour}" */
function encodeSlotId(staffId: string, date: Date, hour: number): string {
  return `slot:${staffId}:${toDateKey(date)}:${hour}`
}

/** Decode a droppable slot ID back to its parts */
function decodeSlotId(slotId: string): SlotData | null {
  const parts = slotId.split(':')
  if (parts.length !== 4 || parts[0] !== 'slot') return null
  const hour = parseInt(parts[3], 10)
  if (isNaN(hour)) return null
  return { staffId: parts[1], date: parts[2], hour }
}

/* ------------------------------------------------------------------ */
/*  Reschedule time computation (exported for testing)                 */
/* ------------------------------------------------------------------ */

/**
 * Given an entry's original start/end and a target slot (date + hour),
 * compute the new start_time and end_time preserving the original duration.
 */
export function computeRescheduledTimes(
  originalStart: string,
  originalEnd: string,
  targetDate: string,
  targetHour: number,
  targetStaffId: string,
): { start_time: string; end_time: string; staff_id: string } {
  const origStart = new Date(originalStart)
  const origEnd = new Date(originalEnd)
  const durationMs = origEnd.getTime() - origStart.getTime()

  // Parse target date parts
  const [year, month, day] = targetDate.split('-').map(Number)

  // Build new start at the target slot's hour, preserving original minutes/seconds
  const newStart = new Date(origStart)
  newStart.setFullYear(year, month - 1, day)
  newStart.setHours(targetHour, origStart.getMinutes(), origStart.getSeconds(), origStart.getMilliseconds())

  const newEnd = new Date(newStart.getTime() + durationMs)

  return {
    start_time: newStart.toISOString(),
    end_time: newEnd.toISOString(),
    staff_id: targetStaffId,
  }
}

/* ------------------------------------------------------------------ */
/*  CSV Export helper (Req 59.2)                                       */
/* ------------------------------------------------------------------ */

/**
 * Generate a CSV string from schedule entries and staff list.
 * Columns: Staff Name, Date, Start Time, End Time, Entry Type, Title, Notes
 */
export function generateScheduleCSV(
  entries: ScheduleEntry[],
  staffMap: Map<string, string>,
): string {
  const header = 'Staff Name,Date,Start Time,End Time,Entry Type,Title,Notes'
  const rows = entries.map((e) => {
    const staffName = (e.staff_id ? staffMap.get(e.staff_id) : '') ?? 'Unassigned'
    const start = new Date(e.start_time)
    const end = new Date(e.end_time)
    const date = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`
    const startStr = `${String(start.getHours()).padStart(2, '0')}:${String(start.getMinutes()).padStart(2, '0')}`
    const endStr = `${String(end.getHours()).padStart(2, '0')}:${String(end.getMinutes()).padStart(2, '0')}`
    // Escape CSV fields that may contain commas or quotes
    const esc = (s: string) => {
      if (s.includes(',') || s.includes('"') || s.includes('\n')) {
        return `"${s.replace(/"/g, '""')}"`
      }
      return s
    }
    return [
      esc(staffName),
      date,
      startStr,
      endStr,
      e.entry_type,
      esc(e.title ?? ''),
      esc(e.description ?? ''),
    ].join(',')
  })
  return [header, ...rows].join('\n')
}

/** Trigger a CSV file download in the browser */
function downloadCSV(csv: string, filename: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

/* ------------------------------------------------------------------ */
/*  Draggable entry card                                               */
/* ------------------------------------------------------------------ */

function DraggableEntryCard({
  entry,
  onClick,
}: {
  entry: ScheduleEntry
  onClick?: (entry: ScheduleEntry) => void
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: entry.id,
    data: { entry },
  })

  const colours = ENTRY_COLOURS[entry.entry_type] || ENTRY_COLOURS.other
  const isRecurring = !!entry.recurrence_group_id
  const isLeave = entry.entry_type === 'leave'

  const style: React.CSSProperties = transform
    ? {
        transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
        zIndex: 50,
        opacity: isDragging ? 0.8 : 1,
      }
    : undefined as unknown as React.CSSProperties

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={() => { if (!isDragging) onClick?.(entry) }}
      onKeyDown={(e) => { if (onClick && !isDragging && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onClick(entry) } }}
      className={`${colours.bg} ${colours.text} border-l-2 ${colours.border} rounded px-1.5 py-0.5 text-xs leading-tight mb-0.5 truncate ${onClick ? 'cursor-grab hover:opacity-80' : ''} ${isDragging ? 'shadow-lg ring-2 ring-blue-400' : ''} ${isLeave ? 'bg-stripes-gray' : ''}`}
      title={`${entry.title || entry.entry_type}${isRecurring ? ' (recurring)' : ''}\n${formatTime(entry.start_time)} – ${formatTime(entry.end_time)}${entry.description ? '\n' + entry.description : ''}`}
    >
      {isRecurring && <span className="mr-0.5" aria-label="Recurring">🔁</span>}
      <span className={`font-medium ${isLeave ? 'line-through' : ''}`}>{entry.title || entry.entry_type}</span>
      <span className="opacity-70 ml-1">{formatTime(entry.start_time)}</span>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Non-draggable entry card (for week view summary)                   */
/* ------------------------------------------------------------------ */

function EntryCard({ entry, onClick }: { entry: ScheduleEntry; onClick?: (entry: ScheduleEntry) => void }) {
  const colours = ENTRY_COLOURS[entry.entry_type] || ENTRY_COLOURS.other
  const isRecurring = !!entry.recurrence_group_id
  const isLeave = entry.entry_type === 'leave'
  return (
    <div
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={() => onClick?.(entry)}
      onKeyDown={(e) => { if (onClick && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onClick(entry) } }}
      className={`${colours.bg} ${colours.text} border-l-2 ${colours.border} rounded px-1.5 py-0.5 text-xs leading-tight mb-0.5 truncate ${onClick ? 'cursor-pointer hover:opacity-80' : ''} ${isLeave ? 'bg-stripes-gray' : ''}`}
      title={`${entry.title || entry.entry_type}${isRecurring ? ' (recurring)' : ''}\n${formatTime(entry.start_time)} – ${formatTime(entry.end_time)}${entry.description ? '\n' + entry.description : ''}`}
    >
      {isRecurring && <span className="mr-0.5" aria-label="Recurring">🔁</span>}
      <span className={`font-medium ${isLeave ? 'line-through' : ''}`}>{entry.title || entry.entry_type}</span>
      <span className="opacity-70 ml-1">{formatTime(entry.start_time)}</span>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Droppable slot wrapper                                             */
/* ------------------------------------------------------------------ */

function DroppableSlot({
  slotId,
  className,
  children,
}: {
  slotId: string
  className?: string
  children: React.ReactNode
}) {
  const { isOver, setNodeRef } = useDroppable({ id: slotId })

  return (
    <td
      ref={setNodeRef}
      className={`${className ?? ''} ${isOver ? 'bg-blue-100/60 ring-1 ring-inset ring-blue-300' : ''}`}
    >
      {children}
    </td>
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
/*  Mobile viewport detection (Req 60.1)                               */
/* ------------------------------------------------------------------ */

function useIsMobile(breakpoint = 768): boolean {
  const [isMobile, setIsMobile] = useState(
    typeof window !== 'undefined' ? window.innerWidth < breakpoint : false,
  )

  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${breakpoint - 1}px)`)
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    setIsMobile(mql.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [breakpoint])

  return isMobile
}


/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export default function ScheduleCalendar() {
  const isMobile = useIsMobile()
  const [view, setView] = useState<CalendarView>('day')
  const [currentDate, setCurrentDate] = useState(new Date())
  const [staff, setStaff] = useState<StaffMember[]>([])
  const [entries, setEntries] = useState<ScheduleEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedStaffId, setSelectedStaffId] = useState<string>('')

  // Schedule entry modal state
  const [modalOpen, setModalOpen] = useState(false)
  const [editingEntry, setEditingEntry] = useState<ScheduleEntry | null>(null)

  // Templates panel visibility
  const [showTemplates, setShowTemplates] = useState(false)

  // Leave mode — pre-selects "leave" entry type in modal
  const [leaveMode, setLeaveMode] = useState(false)

  // Mobile staff selection — shows one staff member at a time on mobile (Req 60.2)
  const [mobileStaffId, setMobileStaffId] = useState<string>('')

  // Drag-and-drop conflict warning
  const [conflictWarning, setConflictWarning] = useState<string | null>(null)

  // DnD sensors — require 8px drag distance to distinguish from clicks
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 8 },
    }),
  )

  // Fetch active staff
  const fetchStaff = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/staff', { params: { is_active: true, page_size: 100 } })
      setStaff(res.data?.staff ?? [])
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
      setEntries(res.data?.entries ?? [])
    } catch {
      setEntries([])
    } finally {
      setLoading(false)
    }
  }, [view, currentDate, selectedStaffId])

  useEffect(() => { fetchStaff() }, [fetchStaff])
  useEffect(() => { fetchEntries() }, [fetchEntries])

  // Auto-select first staff member on mobile if none selected (Req 60.2)
  useEffect(() => {
    if (isMobile && !mobileStaffId && staff.length > 0) {
      setMobileStaffId(staff[0].id)
    }
  }, [isMobile, mobileStaffId, staff])

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

  // Modal handlers
  const handleNewEntry = () => {
    setEditingEntry(null)
    setModalOpen(true)
  }

  const handleNewLeave = () => {
    // Open modal in create mode with leave pre-selected
    setEditingEntry(null)
    setModalOpen(true)
    // We'll pass a flag via a ref or state to pre-select leave type
    setLeaveMode(true)
  }

  const handleEntryClick = useCallback((entry: ScheduleEntry) => {
    setEditingEntry(entry)
    setModalOpen(true)
  }, [])

  const handleModalClose = () => {
    setModalOpen(false)
    setEditingEntry(null)
    setLeaveMode(false)
  }

  const handleModalSave = () => {
    fetchEntries()
  }

  // Print handler (Req 59.1)
  const handlePrint = useCallback(() => {
    window.print()
  }, [])

  // Export CSV handler (Req 59.2)
  const handleExportCSV = useCallback(() => {
    const staffMap = new Map(staff.map((s) => [s.id, s.name]))
    const csv = generateScheduleCSV(entries, staffMap)
    const dateStr = toDateKey(currentDate)
    downloadCSV(csv, `schedule-${view}-${dateStr}.csv`)
  }, [entries, staff, currentDate, view])

  // Drag-and-drop handler — reschedule entry on drop
  const handleDragEnd = useCallback(async (event: DragEndEvent) => {
    const { active, over } = event
    if (!over) return

    const overId = String(over.id)
    const slotData = decodeSlotId(overId)
    if (!slotData) return

    const entry = active.data?.current?.entry as ScheduleEntry | undefined
    if (!entry) return

    // Compute new times preserving original duration
    const newTimes = computeRescheduledTimes(
      entry.start_time,
      entry.end_time,
      slotData.date,
      slotData.hour,
      slotData.staffId,
    )

    // Skip if dropped in the same slot
    const origStart = new Date(entry.start_time)
    const newStart = new Date(newTimes.start_time)
    if (
      entry.staff_id === slotData.staffId &&
      origStart.getFullYear() === newStart.getFullYear() &&
      origStart.getMonth() === newStart.getMonth() &&
      origStart.getDate() === newStart.getDate() &&
      origStart.getHours() === newStart.getHours()
    ) {
      return
    }

    // Call reschedule API
    try {
      const res = await apiClient.put(`/api/v2/schedule/${entry.id}/reschedule`, {
        start_time: newTimes.start_time,
        end_time: newTimes.end_time,
        staff_id: newTimes.staff_id,
      })

      // Check for conflict warning from the API response
      const hasConflict = res.data?.has_conflict ?? res.data?.conflict ?? false
      const conflictMsg = res.data?.conflict_message ?? null

      if (hasConflict) {
        setConflictWarning(
          conflictMsg || 'This entry overlaps with another scheduled entry.'
        )
        // Auto-dismiss after 5 seconds
        setTimeout(() => setConflictWarning(null), 5000)
      }

      // Refresh entries to reflect the move
      fetchEntries()
    } catch (err: unknown) {
      // If the API returns a conflict warning in a 409 but still completes,
      // or if it returns a 200 with conflict info, handle both cases
      const axiosErr = err as { response?: { status?: number; data?: { detail?: string; has_conflict?: boolean } } }
      if (axiosErr?.response?.status === 409) {
        // Conflict detected — show warning but the move may have completed
        setConflictWarning(
          axiosErr.response?.data?.detail ?? 'This entry overlaps with another scheduled entry.'
        )
        setTimeout(() => setConflictWarning(null), 5000)
        fetchEntries()
      }
      // For other errors, silently fail (entry stays in original position)
    }
  }, [fetchEntries])

  // Dismiss conflict warning
  const dismissWarning = useCallback(() => setConflictWarning(null), [])

  return (
    <div className="h-full flex flex-col">
      {/* Conflict warning banner */}
      {conflictWarning && (
        <div className="bg-amber-50 border-b border-amber-200 px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-amber-600 text-sm font-medium">⚠ Schedule Conflict</span>
            <span className="text-amber-700 text-sm">{conflictWarning}</span>
          </div>
          <button
            onClick={dismissWarning}
            className="text-amber-600 hover:text-amber-800 text-sm font-medium"
            aria-label="Dismiss warning"
          >
            ✕
          </button>
        </div>
      )}

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-4 md:px-6 py-3 md:py-4">
        <div className="flex items-center justify-between mb-2 md:mb-3">
          <h1 className="text-lg md:text-xl font-semibold text-gray-900">Staff Roster</h1>
          <div className="flex items-center gap-1 md:gap-2 flex-wrap">
            <button
              onClick={handleNewEntry}
              className="px-2 md:px-3 py-1.5 text-xs md:text-sm font-medium rounded bg-blue-600 text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 min-h-[44px] md:min-h-0"
            >
              + New Entry
            </button>
            <button
              onClick={handleNewLeave}
              className="px-2 md:px-3 py-1.5 text-xs md:text-sm font-medium rounded border border-gray-400 text-gray-700 bg-gray-100 hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-gray-400 min-h-[44px] md:min-h-0"
            >
              + Add Leave
            </button>
            <button
              onClick={() => setShowTemplates(!showTemplates)}
              className="hidden md:inline-flex px-3 py-1.5 text-sm font-medium rounded border border-gray-300 text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              Templates
            </button>
            <button
              onClick={() => navigate(-1)}
              className="p-1.5 rounded hover:bg-gray-100 text-gray-600 min-h-[44px] min-w-[44px] flex items-center justify-center"
              aria-label="Previous"
            >
              ←
            </button>
            <button
              onClick={() => setCurrentDate(new Date())}
              className="px-2 md:px-3 py-1 text-xs md:text-sm rounded border border-gray-300 hover:bg-gray-50 min-h-[44px] md:min-h-0"
            >
              Today
            </button>
            <button
              onClick={() => navigate(1)}
              className="p-1.5 rounded hover:bg-gray-100 text-gray-600 min-h-[44px] min-w-[44px] flex items-center justify-center"
              aria-label="Next"
            >
              →
            </button>
          </div>
        </div>

        {/* Desktop-only controls row */}
        <div className="hidden md:flex flex-wrap items-center gap-4">
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
            <button
              onClick={handlePrint}
              className="px-2 py-1 text-xs font-medium rounded border border-gray-300 text-gray-600 hover:bg-gray-50 no-print"
              data-print-hide
            >
              🖨 Print
            </button>
            <button
              onClick={handleExportCSV}
              className="px-2 py-1 text-xs font-medium rounded border border-gray-300 text-gray-600 hover:bg-gray-50 no-print"
              data-print-hide
            >
              📥 Export CSV
            </button>
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

      {/* Templates panel */}
      {showTemplates && (
        <div className="border-b border-gray-200 px-6 py-4 no-print" data-print-hide>
          <ShiftTemplates />
        </div>
      )}

      {/* Grid */}
      <div className="flex-1 overflow-auto px-6 py-4 schedule-print-area">
        {isMobile ? (
          /* Mobile single-column day view (Req 60.1, 60.2, 60.3) */
          <MobileDayView
            staff={staff}
            date={currentDate}
            entries={entries}
            selectedStaffId={mobileStaffId}
            onStaffChange={setMobileStaffId}
            onEntryClick={handleEntryClick}
            loading={loading}
          />
        ) : (
          <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
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
                onEntryClick={handleEntryClick}
              />
            ) : (
              <WeekRoster
                staff={visibleStaff}
                currentDate={currentDate}
                getSlotEntries={getSlotEntries}
                isToday={isToday}
                isStaffAvailable={isStaffAvailable}
                onEntryClick={handleEntryClick}
              />
            )}
          </DndContext>
        )}
      </div>

      {/* Schedule entry modal (create / edit) */}
      <ScheduleEntryModal
        open={modalOpen}
        onClose={handleModalClose}
        onSave={handleModalSave}
        entry={editingEntry}
        defaultEntryType={leaveMode ? 'leave' : undefined}
      />
    </div>
  )
}


/* ------------------------------------------------------------------ */
/*  Day Roster — staff as columns, hours as rows (with DnD)            */
/* ------------------------------------------------------------------ */

interface RosterProps {
  staff: StaffMember[]
  getSlotEntries: (staffId: string, date: Date, hour: number) => ScheduleEntry[]
  isToday: (d: Date) => boolean
  isStaffAvailable: (staff: StaffMember, date: Date, hour: number) => boolean
  onEntryClick: (entry: ScheduleEntry) => void
}

function DayRoster({
  staff, date, getSlotEntries, isToday, isStaffAvailable, onEntryClick,
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
                const slotId = encodeSlotId(s.id, date, hour)
                return (
                  <DroppableSlot
                    key={s.id}
                    slotId={slotId}
                    className={`px-1 py-1 align-top border-l border-gray-100 min-h-[40px] ${
                      available ? 'bg-green-50/50' : ''
                    }`}
                  >
                    {slotEntries.map(e => (
                      <DraggableEntryCard key={e.id} entry={e} onClick={onEntryClick} />
                    ))}
                  </DroppableSlot>
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
  staff, currentDate, getSlotEntries, isToday, onEntryClick,
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
                        <EntryCard key={e.id} entry={e} onClick={onEntryClick} />
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


/* ------------------------------------------------------------------ */
/*  Mobile Day View — single-column layout (Req 60.1, 60.2, 60.3)     */
/* ------------------------------------------------------------------ */

interface MobileDayViewProps {
  staff: StaffMember[]
  date: Date
  entries: ScheduleEntry[]
  selectedStaffId: string
  onStaffChange: (staffId: string) => void
  onEntryClick: (entry: ScheduleEntry) => void
  loading: boolean
}

function MobileDayView({
  staff,
  date,
  entries,
  selectedStaffId,
  onStaffChange,
  onEntryClick,
  loading,
}: MobileDayViewProps) {
  // Filter entries for the selected staff member on the current day
  const dayEntries = useMemo(() => {
    if (!selectedStaffId) return []
    return entries
      .filter((e) => {
        if (e.staff_id !== selectedStaffId) return false
        const d = new Date(e.start_time)
        return isSameDay(d, date)
      })
      .sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime())
  }, [entries, selectedStaffId, date])

  const selectedStaff = staff.find((s) => s.id === selectedStaffId)

  return (
    <div className="space-y-4">
      {/* Staff switcher dropdown (Req 60.3) */}
      <div>
        <label htmlFor="mobile-staff-select" className="block text-sm font-medium text-gray-700 mb-1">
          Staff Member
        </label>
        <select
          id="mobile-staff-select"
          value={selectedStaffId}
          onChange={(e) => onStaffChange(e.target.value)}
          className="block w-full rounded border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 min-h-[44px]"
        >
          {staff.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
              {s.position ? ` — ${s.position}` : ''}
            </option>
          ))}
        </select>
      </div>

      {/* Day header */}
      <div className="text-sm font-medium text-gray-700">
        {formatDayShort(date)}
        {isSameDay(date, new Date()) && (
          <span className="ml-2 text-xs text-blue-600 font-normal">(Today)</span>
        )}
        {selectedStaff?.position && (
          <span className="ml-2 text-xs text-gray-400">{selectedStaff.position}</span>
        )}
      </div>

      {/* Time slots — vertical single column */}
      {loading ? (
        <div className="py-8 text-center text-gray-500 text-sm">Loading…</div>
      ) : (
        <div className="space-y-1">
          {HOURS.map((hour) => {
            const slotEntries = dayEntries.filter(
              (e) => new Date(e.start_time).getHours() === hour,
            )
            const available = selectedStaff
              ? isStaffAvailable(selectedStaff, date, hour)
              : false

            return (
              <div
                key={hour}
                className={`flex gap-2 rounded px-2 py-2 min-h-[44px] ${
                  available ? 'bg-green-50/50' : 'bg-gray-50/30'
                }`}
              >
                <div className="w-12 flex-shrink-0 text-xs text-gray-400 pt-0.5">
                  {String(hour).padStart(2, '0')}:00
                </div>
                <div className="flex-1 space-y-0.5">
                  {slotEntries.length > 0 ? (
                    slotEntries.map((e) => (
                      <EntryCard key={e.id} entry={e} onClick={onEntryClick} />
                    ))
                  ) : (
                    <div className="text-xs text-gray-300 italic pt-0.5">—</div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Summary */}
      {!loading && (
        <div className="text-xs text-gray-400 text-center pt-2">
          {dayEntries.length} {dayEntries.length === 1 ? 'entry' : 'entries'} for{' '}
          {selectedStaff?.name ?? 'selected staff'}
        </div>
      )}
    </div>
  )
}
