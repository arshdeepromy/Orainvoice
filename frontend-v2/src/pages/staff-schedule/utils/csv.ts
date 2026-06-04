/**
 * RFC 4180 CSV export of the visible roster grid
 * (Workstream B / task B15).
 *
 * Header row: `staff_name, position, YYYY-MM-DD (Mon), ..., YYYY-MM-DD (Sun)`
 * for 14 columns.
 *
 * Cell value:
 *   - Empty cell → empty string.
 *   - Leave-shaded cell → `LEAVE: <leave_type_label>`.
 *   - Otherwise: comma-free, semicolon-separated `HH:MM-HH:MM Title`
 *     strings sorted by start_time.
 *
 * Embedded `"` are doubled and any field containing `,`, `\n`, or `"`
 * is wrapped in double-quotes per RFC 4180.
 *
 * Validates: R15.2, R15.3, R15.4.
 */

import type { ScheduleEntryResponse } from '@/types/schedule'
import type {
  LeaveOverlay,
  StaffMember,
} from '../hooks/useRosterGridData'
import { toIsoDate } from './time'

const DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

/** RFC 4180 escape — wrap in `"` and double inner `"` if needed. */
export function rfc4180Escape(s: string): string {
  if (s === '') return ''
  if (s.includes('"') || s.includes(',') || s.includes('\n') || s.includes('\r')) {
    return `"${s.replace(/"/g, '""')}"`
  }
  return s
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  return `${h}:${m}`
}

/**
 * Build the day header for column `i` of the visible window starting
 * at `start`. Format: `YYYY-MM-DD (Mon)`.
 */
function dayHeaderLabel(start: Date, i: number): string {
  const d = new Date(start)
  d.setDate(d.getDate() + i)
  const dow = DAY_LABELS[d.getDay()]
  return `${toIsoDate(d)} (${dow})`
}

/** Compose the value for a single (staff, date) cell. */
function cellValue(
  staffId: string,
  date: Date,
  entries: ScheduleEntryResponse[],
  leaveByStaffDate: Map<string, Map<string, LeaveOverlay>>,
): string {
  const dateKey = toIsoDate(date)
  const leave = leaveByStaffDate.get(staffId)?.get(dateKey)
  if (leave) return `LEAVE: ${leave.leave_type_label}`
  const cellEntries = entries
    .filter((e) => {
      if (e.staff_id !== staffId) return false
      const start = new Date(e.start_time)
      if (Number.isNaN(start.getTime())) return false
      return toIsoDate(start) === dateKey
    })
    .sort((a, b) => a.start_time.localeCompare(b.start_time))
  if (cellEntries.length === 0) return ''
  return cellEntries
    .map((e) => {
      const start = formatTime(e.start_time)
      const end = formatTime(e.end_time)
      // Strip embedded commas — title gets wrapped if needed via
      // `rfc4180Escape` at row-join time.
      const title = (e.title ?? e.entry_type ?? '').replace(/,/g, ' ')
      return `${start}-${end} ${title}`.trim()
    })
    .join('; ')
}

/**
 * Generate the full CSV string for the visible window.
 */
export function generateRosterGridCSV(
  visibleWindow: { start: Date; end: Date },
  staff: StaffMember[],
  entries: ScheduleEntryResponse[],
  leaveByStaffDate: Map<string, Map<string, LeaveOverlay>>,
): string {
  const headerCols = ['staff_name', 'position']
  for (let i = 0; i < 14; i += 1) {
    headerCols.push(dayHeaderLabel(visibleWindow.start, i))
  }
  const rows: string[] = []
  rows.push(headerCols.map(rfc4180Escape).join(','))
  for (const s of staff ?? []) {
    const cols: string[] = []
    cols.push(s.name ?? `${s.first_name ?? ''} ${s.last_name ?? ''}`.trim())
    cols.push(s.position ?? '')
    for (let i = 0; i < 14; i += 1) {
      const date = new Date(visibleWindow.start)
      date.setDate(date.getDate() + i)
      cols.push(cellValue(s.id, date, entries, leaveByStaffDate))
    }
    rows.push(cols.map(rfc4180Escape).join(','))
  }
  return rows.join('\n')
}

/**
 * Trigger a CSV blob download in the browser.
 */
export function downloadRosterGridCSV(
  filename: string,
  csv: string,
): void {
  if (typeof document === 'undefined') return
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

/* ----------------------------------------------------------------- */
/*  RFC 4180 parser — used by the property test to round-trip the     */
/*  generated CSV.                                                    */
/* ----------------------------------------------------------------- */

export function parseCSV(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let inQuotes = false
  let i = 0
  while (i < text.length) {
    const c = text[i]
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          cell += '"'
          i += 2
          continue
        }
        inQuotes = false
        i += 1
        continue
      }
      cell += c
      i += 1
      continue
    }
    if (c === '"') {
      inQuotes = true
      i += 1
      continue
    }
    if (c === ',') {
      row.push(cell)
      cell = ''
      i += 1
      continue
    }
    if (c === '\n') {
      row.push(cell)
      rows.push(row)
      row = []
      cell = ''
      i += 1
      continue
    }
    if (c === '\r') {
      // Skip — pair with following \n if present.
      i += 1
      continue
    }
    cell += c
    i += 1
  }
  // Final cell + row.
  row.push(cell)
  rows.push(row)
  return rows
}
