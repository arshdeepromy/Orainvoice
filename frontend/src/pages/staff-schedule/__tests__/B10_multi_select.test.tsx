/**
 * Tests for the multi-select Apply-template helper (B10):
 *   - `computeApplyMatrix` returns the cartesian product, filtered by
 *     idempotence against existing entries with the same template name.
 *   - Result length is bounded by `selectedStaff.size × selectedDays.size`.
 *
 * Validates: R7.6, R7.7, R7.9.
 */

import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import { computeApplyMatrix } from '../utils/apply'
import { BULK_CELL_CAP } from '../utils/paint'
import type { ScheduleEntryResponse, ShiftTemplateResponse } from '@/types/schedule'

const template: ShiftTemplateResponse = {
  id: 't1',
  org_id: 'o1',
  name: 'Morning shift',
  start_time: '09:00:00',
  end_time: '17:00:00',
  entry_type: 'job',
  created_at: '2025-06-01T00:00:00Z',
}

describe('computeApplyMatrix', () => {
  it('returns cartesian product of staff × days', () => {
    const staff = ['s1', 's2', 's3']
    const days = [
      new Date(2025, 5, 2),
      new Date(2025, 5, 3),
    ]
    const result = computeApplyMatrix(staff, days, template, [])
    expect(result.cells).toHaveLength(6)
    expect(result.rawCount).toBe(6)
    expect(result.exceedsCap).toBe(false)
  })

  it('filters out cells with same-template entry', () => {
    const staff = ['s1', 's2']
    const days = [new Date(2025, 5, 2)]
    const existing: ScheduleEntryResponse[] = [
      {
        id: 'e1',
        org_id: 'o1',
        staff_id: 's1',
        title: 'Morning shift',
        start_time: new Date(2025, 5, 2, 9).toISOString(),
        end_time: new Date(2025, 5, 2, 17).toISOString(),
        entry_type: 'job',
        status: 'scheduled',
        created_at: '',
        updated_at: '',
      },
    ]
    const result = computeApplyMatrix(staff, days, template, existing)
    expect(result.cells).toHaveLength(1)
    expect(result.cells[0].staff_id).toBe('s2')
    expect(result.skippedExisting).toBe(1)
  })

  it('property: result.cells.length <= staff.length * days.length', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 20 }),
        fc.integer({ min: 0, max: 14 }),
        (staffCount, dayCount) => {
          const staff = Array.from({ length: staffCount }, (_, i) => `s${i}`)
          const days = Array.from(
            { length: dayCount },
            (_, i) => new Date(2025, 5, 2 + i),
          )
          const result = computeApplyMatrix(staff, days, template, [])
          expect(result.cells.length).toBeLessThanOrEqual(
            staffCount * dayCount,
          )
          expect(result.rawCount).toBe(staffCount * dayCount)
          expect(result.exceedsCap).toBe(staffCount * dayCount > BULK_CELL_CAP)
        },
      ),
      { numRuns: 50 },
    )
  })
})
