/**
 * Tests for the paint-mode helpers (B9):
 *   - `computePaintRectangle` is order-invariant and bounded.
 *   - `paintIdempotenceFilter` removes cells already filled.
 *
 * Validates: R6.3, R6.4, R6.7, R14.3, R14.4.
 */

import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import {
  computePaintRectangle,
  paintIdempotenceFilter,
  buildEntriesForTemplate,
} from '../utils/paint'
import type {
  ScheduleEntryResponse,
  ShiftTemplateResponse,
} from '@/types/schedule'

const template: ShiftTemplateResponse = {
  id: 't1',
  org_id: 'o1',
  name: 'Morning shift',
  start_time: '09:00:00',
  end_time: '17:00:00',
  entry_type: 'job',
  created_at: '2025-06-01T00:00:00Z',
}

describe('computePaintRectangle', () => {
  it('property: anchor + current order does not matter', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 49 }),
        fc.integer({ min: 0, max: 13 }),
        fc.integer({ min: 0, max: 49 }),
        fc.integer({ min: 0, max: 13 }),
        (r1, c1, r2, c2) => {
          const a = computePaintRectangle({ row: r1, col: c1 }, { row: r2, col: c2 })
          const b = computePaintRectangle({ row: r2, col: c2 }, { row: r1, col: c1 })
          expect(a.cells).toEqual(b.cells)
          expect(a.count).toBe((Math.abs(r1 - r2) + 1) * (Math.abs(c1 - c2) + 1))
          expect(a.rowStart).toBeGreaterThanOrEqual(0)
          expect(a.rowEnd).toBeLessThanOrEqual(49)
          expect(a.colStart).toBeGreaterThanOrEqual(0)
          expect(a.colEnd).toBeLessThanOrEqual(13)
        },
      ),
      { numRuns: 100 },
    )
  })
})

describe('paintIdempotenceFilter', () => {
  it('removes cells that already contain entry from same template', () => {
    const date = new Date(2025, 5, 2)
    const cell = { staff_id: 's1', date }
    const existing: ScheduleEntryResponse[] = [
      {
        id: 'e1',
        org_id: 'o1',
        staff_id: 's1',
        title: 'Morning shift',
        start_time: new Date(2025, 5, 2, 9, 0, 0).toISOString(),
        end_time: new Date(2025, 5, 2, 17, 0, 0).toISOString(),
        entry_type: 'job',
        status: 'scheduled',
        created_at: '',
        updated_at: '',
      },
    ]
    expect(paintIdempotenceFilter([cell], existing, template)).toEqual([])
  })

  it('keeps cells with no matching entry', () => {
    const cells = [{ staff_id: 's2', date: new Date(2025, 5, 2) }]
    expect(paintIdempotenceFilter(cells, [], template)).toEqual(cells)
  })

  it('property: applying twice yields zero cells on second pass', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 5 }),
        fc.integer({ min: 1, max: 5 }),
        (rows, cols) => {
          const cells = []
          for (let r = 0; r < rows; r += 1) {
            for (let c = 0; c < cols; c += 1) {
              const d = new Date(2025, 5, 2 + c)
              cells.push({ staff_id: `s${r}`, date: d })
            }
          }
          // Build entries from those cells using the template.
          const built = buildEntriesForTemplate(cells, template)
          const existing: ScheduleEntryResponse[] = built.map((b, idx) => ({
            id: `built-${idx}`,
            org_id: 'o1',
            staff_id: b.staff_id ?? null,
            title: b.title ?? null,
            start_time: b.start_time,
            end_time: b.end_time,
            entry_type: b.entry_type,
            status: 'scheduled',
            created_at: '',
            updated_at: '',
          }))
          expect(paintIdempotenceFilter(cells, existing, template)).toEqual([])
        },
      ),
      { numRuns: 25 },
    )
  })
})
