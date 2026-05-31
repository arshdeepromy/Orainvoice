/**
 * Tests for the cell clipboard helpers (B12).
 *
 * Validates: R9.2, R9.5, R14.2-style.
 */

import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import {
  clipboardFromCell,
  shiftClipboardToFocusCell,
} from '../utils/clipboard'
import type { ScheduleEntryResponse } from '@/types/schedule'

function makeEntry(
  start: Date,
  durationMin: number,
  partial: Partial<ScheduleEntryResponse> = {},
): ScheduleEntryResponse {
  const end = new Date(start.getTime() + durationMin * 60 * 1000)
  return {
    id: partial.id ?? `e-${start.getTime()}`,
    org_id: 'o1',
    staff_id: 's1',
    title: 'Test',
    description: null,
    start_time: start.toISOString(),
    end_time: end.toISOString(),
    entry_type: 'job',
    status: 'scheduled',
    notes: null,
    recurrence_group_id: null,
    created_at: '',
    updated_at: '',
    ...partial,
  }
}

describe('shiftClipboardToFocusCell', () => {
  it('preserves entry_type, title, description, and duration', () => {
    const entry = makeEntry(new Date(2025, 5, 2, 9, 0), 60, {
      title: 'Morning',
      description: 'Notes',
      entry_type: 'booking',
    })
    const clipboard = clipboardFromCell([entry])
    const focusDate = new Date(2025, 5, 5)
    const out = shiftClipboardToFocusCell(
      clipboard,
      { staffIndex: 0, staff_id: 's2', date: focusDate },
      () => 's2',
    )
    expect(out).toHaveLength(1)
    const result = out[0]
    expect(result.staff_id).toBe('s2')
    expect(result.title).toBe('Morning')
    expect(result.description).toBe('Notes')
    expect(result.entry_type).toBe('booking')
    const newDur =
      new Date(result.end_time).getTime() -
      new Date(result.start_time).getTime()
    expect(newDur).toBe(60 * 60 * 1000)
  })

  it('property: preserves duration for any clipboard size and focus cell', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 5 }),
        fc.integer({ min: 0, max: 23 }),
        fc.integer({ min: 15, max: 480 }),
        fc.integer({ min: 1, max: 30 }),
        (count, hour, dur, daysAhead) => {
          const clipboard = clipboardFromCell(
            Array.from({ length: count }, (_, i) =>
              makeEntry(new Date(2025, 5, 2, hour, 0), dur, {
                id: `e-${i}`,
              }),
            ),
          )
          const focusDate = new Date(2025, 5, 2 + daysAhead)
          const out = shiftClipboardToFocusCell(
            clipboard,
            { staffIndex: 0, staff_id: 's2', date: focusDate },
            () => 's2',
          )
          expect(out).toHaveLength(count)
          for (const r of out) {
            const newDur =
              new Date(r.end_time).getTime() -
              new Date(r.start_time).getTime()
            expect(newDur).toBe(dur * 60 * 1000)
            expect(r.staff_id).toBe('s2')
          }
        },
      ),
      { numRuns: 50 },
    )
  })
})
