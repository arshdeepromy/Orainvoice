/**
 * Pure helper for the multi-select Apply-template flow
 * (Workstream B / task B10).
 *
 * `computeApplyMatrix(staffIds, days, template, existingEntries)` returns
 * the cartesian product of `staffIds × days`, filtered for idempotence
 * against existing entries with the same template.name on the same
 * (staff_id, date) key.
 *
 * Validates: R7.6, R7.7, R7.9.
 */

import type {
  ScheduleEntryResponse,
  ShiftTemplateResponse,
} from '@/types/schedule'
import {
  paintIdempotenceFilter,
  type ResolvedCell,
  BULK_CELL_CAP,
} from './paint'

export interface ApplyMatrixResult {
  cells: ResolvedCell[]
  /** Total cell pairs before idempotence filtering. */
  rawCount: number
  /** Cells removed because they already contain a same-template entry. */
  skippedExisting: number
  /** Indicates the raw count exceeded the 200-cell cap. */
  exceedsCap: boolean
}

export function computeApplyMatrix(
  staffIds: string[],
  days: Date[],
  template: Pick<ShiftTemplateResponse, 'name'>,
  existingEntries: ScheduleEntryResponse[],
): ApplyMatrixResult {
  const raw: ResolvedCell[] = []
  for (const staffId of staffIds ?? []) {
    for (const day of days ?? []) {
      raw.push({ staff_id: staffId, date: day })
    }
  }
  const rawCount = raw.length
  const exceedsCap = rawCount > BULK_CELL_CAP
  const filtered = paintIdempotenceFilter(raw, existingEntries, template)
  return {
    cells: filtered,
    rawCount,
    skippedExisting: rawCount - filtered.length,
    exceedsCap,
  }
}
