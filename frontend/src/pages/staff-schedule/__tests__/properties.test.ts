/**
 * Centralised property suite (Workstream C / task C1).
 *
 * P1: `bulkCreateLocalShape(N)` — for N in [1, 200] returns N entries;
 *     outside the range it throws BulkCellCapError.
 * P2: `copyWeekShift(entry, +7d)` produces an entry with identical
 *     entry_type/title/description/notes and start/end shifted by 7 days.
 * P3: `paintIdempotenceFilter` is idempotent: running with the same
 *     args twice produces an empty array on the second call.
 * P4: `gridKeyboardReducer(state, key)` — for any sequence of arrow
 *     keys, focused (row, col) stays in `[0, R) × [0, C)` for any R in
 *     [1, 100] and C = 14.
 *
 * Validates: R14.1, R14.2, R14.3, R14.4 (Properties P1..P4).
 */

import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import {
  bulkCreateLocalShape,
  BulkCellCapError,
  buildEntriesForTemplate,
  copyWeekShift,
  paintIdempotenceFilter,
  type ResolvedCell,
} from '../utils/paint'
import {
  gridKeyboardReducer,
  type GridKeyboardKey,
} from '../utils/keyboard'
import type {
  ScheduleEntryResponse,
  ShiftTemplateResponse,
} from '@/types/schedule'

const KEYS: GridKeyboardKey[] = [
  'ArrowLeft',
  'ArrowRight',
  'ArrowUp',
  'ArrowDown',
]

const template: ShiftTemplateResponse = {
  id: 't',
  org_id: 'o',
  name: 'Test shift',
  start_time: '09:00:00',
  end_time: '17:00:00',
  entry_type: 'job',
  created_at: '',
}

describe('Property suite (C1)', () => {
  it('P1: bulkCreateLocalShape — bounded by 1..200', () => {
    fc.assert(
      fc.property(fc.integer({ min: 1, max: 200 }), (n) => {
        const out = bulkCreateLocalShape(n)
        expect(out).toHaveLength(n)
        for (const e of out) {
          expect(e.entry_type).toBe('job')
          expect(e.start_time).toBeTypeOf('string')
          expect(new Date(e.end_time).getTime()).toBeGreaterThan(
            new Date(e.start_time).getTime(),
          )
        }
      }),
      { numRuns: 50 },
    )
  })

  it('P1: bulkCreateLocalShape throws for N outside 1..200', () => {
    expect(() => bulkCreateLocalShape(0)).toThrow(BulkCellCapError)
    expect(() => bulkCreateLocalShape(201)).toThrow(BulkCellCapError)
    expect(() => bulkCreateLocalShape(-1)).toThrow(BulkCellCapError)
  })

  it('P2: copyWeekShift preserves metadata and shifts by exactly 7 days', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 23 }),
        fc.integer({ min: 30, max: 480 }),
        fc.string({ maxLength: 30 }),
        (hour, durMin, title) => {
          const start = new Date(2025, 5, 2, hour, 0, 0)
          const end = new Date(start.getTime() + durMin * 60 * 1000)
          const entry: ScheduleEntryResponse = {
            id: 'e1',
            org_id: 'o',
            staff_id: 's1',
            title,
            description: 'desc',
            start_time: start.toISOString(),
            end_time: end.toISOString(),
            entry_type: 'booking',
            status: 'scheduled',
            notes: null,
            recurrence_group_id: null,
            created_at: '',
            updated_at: '',
          }
          const shifted = copyWeekShift(entry, 7)
          expect(shifted.entry_type).toBe('booking')
          expect(shifted.title).toBe(title)
          expect(shifted.description).toBe('desc')
          const newStart = new Date(shifted.start_time)
          const newEnd = new Date(shifted.end_time)
          expect(newStart.getTime() - start.getTime()).toBe(
            7 * 24 * 60 * 60 * 1000,
          )
          expect(newEnd.getTime() - newStart.getTime()).toBe(
            durMin * 60 * 1000,
          )
        },
      ),
      { numRuns: 50 },
    )
  })

  it('P3: paintIdempotenceFilter — second run produces empty array', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 5 }),
        fc.integer({ min: 1, max: 5 }),
        (rows, cols) => {
          const cells: ResolvedCell[] = []
          for (let r = 0; r < rows; r += 1) {
            for (let c = 0; c < cols; c += 1) {
              cells.push({
                staff_id: `s${r}`,
                date: new Date(2025, 5, 2 + c),
              })
            }
          }
          const built = buildEntriesForTemplate(cells, template)
          const existing: ScheduleEntryResponse[] = built.map((b, i) => ({
            id: `b-${i}`,
            org_id: 'o',
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

  it('P4: gridKeyboardReducer keeps focus in bounds for any key sequence', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 100 }),
        fc.array(fc.constantFrom(...KEYS), { minLength: 0, maxLength: 50 }),
        fc.integer({ min: 0, max: 99 }),
        fc.integer({ min: 0, max: 13 }),
        (rows, keys, startRow, startCol) => {
          const r0 = Math.min(startRow, rows - 1)
          let state = {
            rows,
            cols: 14,
            focused: { row: r0, col: startCol },
            selectionAnchor: { row: r0, col: startCol },
          }
          for (const key of keys) {
            state = gridKeyboardReducer(state, { key, shift: false })
          }
          expect(state.focused.row).toBeGreaterThanOrEqual(0)
          expect(state.focused.row).toBeLessThan(rows)
          expect(state.focused.col).toBeGreaterThanOrEqual(0)
          expect(state.focused.col).toBeLessThan(14)
        },
      ),
      { numRuns: 200 },
    )
  })
})
