/**
 * Pure helpers for paint-mode rectangle drag (Workstream B / task B9).
 *
 * `computePaintRectangle(anchor, current)` takes two grid coords and
 * returns the bounding rectangle. Order-invariant: anchor at
 * top-left or bottom-right gives the same rectangle.
 *
 * `paintIdempotenceFilter(cells, existingEntries, template)` removes
 * cells that already contain an entry created from the same template
 * on the same date for the same staff (R6.7 — idempotence).
 *
 * Validates: R6.3, R6.4, R6.7, R14.3, R14.4.
 */

import type {
  ScheduleEntryCreate,
  ScheduleEntryResponse,
  ShiftTemplateResponse,
} from '@/types/schedule'
import { combineDateAndTime, toIsoDate } from './time'

export interface CellCoord {
  row: number
  col: number
}

export interface PaintRectangle {
  rowStart: number
  rowEnd: number
  colStart: number
  colEnd: number
  count: number
  cells: CellCoord[]
}

/**
 * Compute the inclusive bounding rectangle between `anchor` and
 * `current`. Order-invariant.
 */
export function computePaintRectangle(
  anchor: CellCoord,
  current: CellCoord,
): PaintRectangle {
  const rowStart = Math.min(anchor.row, current.row)
  const rowEnd = Math.max(anchor.row, current.row)
  const colStart = Math.min(anchor.col, current.col)
  const colEnd = Math.max(anchor.col, current.col)
  const cells: CellCoord[] = []
  for (let r = rowStart; r <= rowEnd; r += 1) {
    for (let c = colStart; c <= colEnd; c += 1) {
      cells.push({ row: r, col: c })
    }
  }
  return {
    rowStart,
    rowEnd,
    colStart,
    colEnd,
    count: cells.length,
    cells,
  }
}

export interface ResolvedCell {
  staff_id: string
  date: Date
}

/**
 * Build `ScheduleEntryCreate` objects by applying `template`'s
 * start_time/end_time/entry_type to each cell's date. Cells with a
 * malformed template time are skipped.
 */
export function buildEntriesForTemplate(
  cells: ResolvedCell[],
  template: Pick<
    ShiftTemplateResponse,
    'start_time' | 'end_time' | 'entry_type' | 'name'
  >,
): ScheduleEntryCreate[] {
  const out: ScheduleEntryCreate[] = []
  for (const cell of cells) {
    const start = combineDateAndTime(cell.date, template.start_time)
    const end = combineDateAndTime(cell.date, template.end_time)
    if (!start || !end) continue
    out.push({
      staff_id: cell.staff_id,
      title: template.name,
      start_time: start,
      end_time: end,
      entry_type: template.entry_type,
      recurrence: 'none',
    })
  }
  return out
}

/**
 * Remove cells that already contain a schedule_entry whose `title`
 * matches the template `name` on the same staff + date. Used for
 * paint idempotence (R6.7) and apply-template idempotence (R7.7).
 */
export function paintIdempotenceFilter(
  cells: ResolvedCell[],
  existingEntries: ScheduleEntryResponse[],
  template: Pick<ShiftTemplateResponse, 'name'>,
): ResolvedCell[] {
  const have = new Set<string>()
  for (const e of existingEntries ?? []) {
    if (!e.staff_id) continue
    const start = new Date(e.start_time)
    if (Number.isNaN(start.getTime())) continue
    if ((e.title ?? '') === template.name) {
      have.add(`${e.staff_id}|${toIsoDate(start)}`)
    }
  }
  return cells.filter(
    (c) => !have.has(`${c.staff_id}|${toIsoDate(c.date)}`),
  )
}

export class BulkCellCapError extends Error {
  constructor(count: number) {
    super(
      `Maximum 200 cells per paint action. Reduce the rectangle and try again. Got ${count}.`,
    )
    this.name = 'BulkCellCapError'
  }
}

export const BULK_CELL_CAP = 200

/**
 * Produce a bulkCreate-shaped entries array for property test P1 in
 * the C1 suite. Throws if `count` is outside [1, 200].
 */
export function bulkCreateLocalShape(count: number): ScheduleEntryCreate[] {
  if (!Number.isInteger(count) || count < 1 || count > BULK_CELL_CAP) {
    throw new BulkCellCapError(count)
  }
  const out: ScheduleEntryCreate[] = []
  const base = Date.UTC(2025, 5, 2, 9, 0, 0)
  for (let i = 0; i < count; i += 1) {
    const start = new Date(base + i * 60 * 60 * 1000)
    const end = new Date(start.getTime() + 60 * 60 * 1000)
    out.push({
      staff_id: '00000000-0000-0000-0000-000000000000',
      title: `Test ${i}`,
      start_time: start.toISOString(),
      end_time: end.toISOString(),
      entry_type: 'job',
      recurrence: 'none',
    })
  }
  return out
}

/**
 * Apply a +N-day shift to a `ScheduleEntryResponse` (used for the
 * copy-week local shape / property P2). Returns a new
 * `ScheduleEntryCreate` with `start_time`/`end_time` shifted by
 * `daysOffset` calendar days.
 */
export function copyWeekShift(
  entry: ScheduleEntryResponse,
  daysOffset: number,
): ScheduleEntryCreate {
  const offsetMs = daysOffset * 24 * 60 * 60 * 1000
  return {
    staff_id: entry.staff_id ?? null,
    job_id: entry.job_id ?? null,
    booking_id: entry.booking_id ?? null,
    location_id: entry.location_id ?? null,
    title: entry.title ?? null,
    description: entry.description ?? null,
    start_time: new Date(
      new Date(entry.start_time).getTime() + offsetMs,
    ).toISOString(),
    end_time: new Date(
      new Date(entry.end_time).getTime() + offsetMs,
    ).toISOString(),
    entry_type: entry.entry_type,
    notes: null,
    recurrence: 'none',
  }
}
