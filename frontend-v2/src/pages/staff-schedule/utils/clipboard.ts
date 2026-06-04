/**
 * Pure helpers for the Ctrl+C / Ctrl+V cell clipboard
 * (Workstream B / task B12).
 *
 * The clipboard preserves `(end_time - start_time)`, `entry_type`,
 * `title`, `description`, and the relative offsets between cells.
 * Pasting onto a focused cell shifts every clipboard item by the
 * focused cell's date offset and rebases the staff_id by the focus
 * row offset.
 *
 * Validates: R9.2, R9.5, R14.2-style.
 */

import type {
  ScheduleEntryCreate,
  ScheduleEntryResponse,
} from '@/types/schedule'

export interface ClipboardItem {
  entry: ScheduleEntryResponse
  /** Days from the rectangle's anchor cell to this item's cell. */
  dxDays: number
  /** Row offset (staff index) from anchor to this item's cell. */
  dyRows: number
}

export interface FocusCell {
  /** Index of the staff row. */
  staffIndex: number
  staff_id: string
  date: Date
}

/**
 * Build a clipboard from a single focused cell containing N entries.
 * All items share offset (0, 0) — the cell IS the anchor.
 */
export function clipboardFromCell(
  entries: ScheduleEntryResponse[],
): ClipboardItem[] {
  return (entries ?? []).map((entry) => ({
    entry,
    dxDays: 0,
    dyRows: 0,
  }))
}

/**
 * Build a clipboard from a multi-cell selection rectangle. The
 * top-left corner of the rectangle is the anchor (offset 0,0).
 *
 * `cells` is a list of `(staffIndex, date, entries)` triples; the
 * function picks the top-left (min staffIndex, min date) and computes
 * each entry's offset relative to it.
 */
export function clipboardFromRectangle(
  cells: Array<{
    staffIndex: number
    date: Date
    entries: ScheduleEntryResponse[]
  }>,
): ClipboardItem[] {
  if (cells.length === 0) return []
  const minRow = cells.reduce(
    (m, c) => Math.min(m, c.staffIndex),
    Number.POSITIVE_INFINITY,
  )
  const minDate = cells
    .map((c) => c.date.getTime())
    .reduce((m, d) => Math.min(m, d), Number.POSITIVE_INFINITY)
  const out: ClipboardItem[] = []
  for (const cell of cells) {
    const dxDays = Math.round(
      (cell.date.getTime() - minDate) / (24 * 60 * 60 * 1000),
    )
    const dyRows = cell.staffIndex - minRow
    for (const entry of cell.entries ?? []) {
      out.push({ entry, dxDays, dyRows })
    }
  }
  return out
}

/**
 * Shift every clipboard item to the focused cell's date.  Each result
 * preserves the original entry's duration, entry_type, title,
 * description; only `start_time`, `end_time`, and `staff_id` change.
 *
 * `staffIdAtRow(rowIndex)` resolves the destination staff_id for a
 * given row offset relative to the focus cell. If the resolver
 * returns null (out of bounds), the item is dropped.
 */
export function shiftClipboardToFocusCell(
  clipboard: ClipboardItem[],
  focus: FocusCell,
  staffIdAtRow: (rowIndex: number) => string | null,
): ScheduleEntryCreate[] {
  const out: ScheduleEntryCreate[] = []
  for (const item of clipboard ?? []) {
    const targetStaffId = staffIdAtRow(focus.staffIndex + item.dyRows)
    if (!targetStaffId) continue
    const start = new Date(item.entry.start_time)
    const end = new Date(item.entry.end_time)
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) continue
    const duration = end.getTime() - start.getTime()
    // Build the destination start: focus.date at the source's
    // hour/minute/second, plus dxDays.
    const newStart = new Date(focus.date)
    newStart.setHours(
      start.getHours(),
      start.getMinutes(),
      start.getSeconds(),
      start.getMilliseconds(),
    )
    newStart.setDate(newStart.getDate() + item.dxDays)
    const newEnd = new Date(newStart.getTime() + duration)
    out.push({
      staff_id: targetStaffId,
      title: item.entry.title ?? null,
      description: item.entry.description ?? null,
      start_time: newStart.toISOString(),
      end_time: newEnd.toISOString(),
      entry_type: item.entry.entry_type,
      recurrence: 'none',
    })
  }
  return out
}
