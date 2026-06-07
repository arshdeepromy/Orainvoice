import { describe, it, expect } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import fc from 'fast-check'
import DayPips from './DayPips'

/**
 * DayPips property test — Property 8: Day pips reflect the availability schedule.
 *
 * Feature: staff-redesign, Property 8
 * Validates: Requirements 3.1, 3.2, 3.3, 3.4
 *
 * For any `availability_schedule`, DayPips renders exactly seven pips, one per
 * weekday ordered Monday → Sunday. A pip is ACTIVE (`data-active="true"`) iff a
 * (truthy) schedule entry exists for that day, and INACTIVE otherwise. The
 * empty schedule and the null/undefined schedule cases yield seven inactive
 * pips (R3.4).
 */

// The seven weekday keys in canonical Monday → Sunday order.
const WEEKDAYS = [
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday',
] as const

// A schedule entry value as produced by the backend availability_schedule.
const entryArb = fc.record({
  start: fc.stringMatching(/^[0-2][0-9]:[0-5][0-9]$/),
  end: fc.stringMatching(/^[0-2][0-9]:[0-5][0-9]$/),
})

/**
 * Generate an `availability_schedule`:
 *  - pick a subset of the seven weekday keys to be PRESENT (active),
 *  - map each present key to an { start, end } entry,
 *  - optionally sprinkle in some "junk" keys that must not affect the pips.
 */
const scheduleArb = fc
  .tuple(
    fc.subarray([...WEEKDAYS]),
    fc.array(
      fc.string().filter((s) => !WEEKDAYS.includes(s as (typeof WEEKDAYS)[number])),
      { maxLength: 3 },
    ),
    entryArb,
  )
  .map(([presentDays, junkKeys, entry]) => {
    const schedule: Record<string, { start: string; end: string }> = {}
    for (const day of presentDays) schedule[day] = entry
    for (const junk of junkKeys) schedule[junk] = entry
    return { schedule, presentDays: new Set(presentDays) }
  })

describe('DayPips — Property 8: pips reflect the availability schedule', () => {
  it('renders seven Mon→Sun pips, active iff a schedule entry exists', () => {
    fc.assert(
      fc.property(scheduleArb, ({ schedule, presentDays }) => {
        const { container } = render(<DayPips schedule={schedule} />)
        try {
          const pips = container.querySelectorAll('[data-day]')

          // Exactly seven pips.
          expect(pips).toHaveLength(7)

          // Ordered Monday → Sunday, each active iff present in the schedule.
          WEEKDAYS.forEach((day, index) => {
            const pip = pips[index]
            expect(pip.getAttribute('data-day')).toBe(day)
            expect(pip.getAttribute('data-active')).toBe(
              presentDays.has(day) ? 'true' : 'false',
            )
          })
        } finally {
          cleanup()
        }
      }),
      { numRuns: 100 },
    )
  })

  it('renders seven inactive pips for empty / null / undefined schedules (R3.4)', () => {
    fc.assert(
      fc.property(
        fc.constantFrom<Record<string, { start: string; end: string }> | null | undefined>(
          {},
          null,
          undefined,
        ),
        (schedule) => {
          const { container } = render(<DayPips schedule={schedule} />)
          try {
            const pips = container.querySelectorAll('[data-day]')
            expect(pips).toHaveLength(7)
            WEEKDAYS.forEach((day, index) => {
              const pip = pips[index]
              expect(pip.getAttribute('data-day')).toBe(day)
              expect(pip.getAttribute('data-active')).toBe('false')
            })
          } finally {
            cleanup()
          }
        },
      ),
      { numRuns: 100 },
    )
  })
})
