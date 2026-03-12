import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { formatElapsedTime, calculateAccumulatedMinutes } from '../pages/jobs/JobTimer'
import type { TimeEntry } from '../pages/jobs/JobTimer'

// Feature: booking-to-job-workflow, Property 11: Elapsed time calculation
// Feature: booking-to-job-workflow, Property 12: Accumulated time is sum of durations

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Generate a past timestamp (ms since epoch) within a reasonable range */
const pastTimestampMsArb = fc.integer({ min: 0, max: 1_700_000_000_000 })

/** Generate a positive elapsed duration in milliseconds (0 to ~24 hours) */
const elapsedMsArb = fc.integer({ min: 0, max: 86_400_000 })

/** Generate a completed TimeEntry with a non-negative duration_minutes */
const completedTimeEntryArb: fc.Arbitrary<TimeEntry> = fc.record({
  id: fc.uuid(),
  started_at: fc.constant('2026-01-01T00:00:00Z'),
  stopped_at: fc.constant('2026-01-01T01:00:00Z'),
  duration_minutes: fc.nat({ max: 600 }),
})

/** Generate an active (in-progress) TimeEntry with stopped_at = null */
const activeTimeEntryArb: fc.Arbitrary<TimeEntry> = fc.record({
  id: fc.uuid(),
  started_at: fc.constant('2026-01-01T00:00:00Z'),
  stopped_at: fc.constant(null),
  duration_minutes: fc.constant(null),
})

/** Generate a mixed array of completed and active entries */
const mixedEntriesArb = fc.tuple(
  fc.array(completedTimeEntryArb, { minLength: 0, maxLength: 10 }),
  fc.array(activeTimeEntryArb, { minLength: 0, maxLength: 2 }),
).map(([completed, active]) => [...completed, ...active])

/* ------------------------------------------------------------------ */
/*  Property 11: Elapsed time calculation                              */
/*  **Validates: Requirements 4.7**                                    */
/* ------------------------------------------------------------------ */

describe('Property 11: Elapsed time calculation', () => {
  it('returns HH:MM:SS matching the difference between now and started_at', () => {
    fc.assert(
      fc.property(pastTimestampMsArb, elapsedMsArb, (startMs, elapsedMs) => {
        const startedAt = new Date(startMs).toISOString()
        const now = new Date(startMs + elapsedMs)

        const result = formatElapsedTime(startedAt, now)

        const totalSeconds = Math.floor(elapsedMs / 1000)
        const h = Math.floor(totalSeconds / 3600)
        const m = Math.floor((totalSeconds % 3600) / 60)
        const s = totalSeconds % 60
        const expected = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`

        expect(result).toBe(expected)
      }),
      { numRuns: 5 },
    )
  })

  it('output always matches HH:MM:SS format', () => {
    fc.assert(
      fc.property(pastTimestampMsArb, elapsedMsArb, (startMs, elapsedMs) => {
        const startedAt = new Date(startMs).toISOString()
        const now = new Date(startMs + elapsedMs)

        const result = formatElapsedTime(startedAt, now)

        expect(result).toMatch(/^\d{2,}:\d{2}:\d{2}$/)
      }),
      { numRuns: 5 },
    )
  })

  it('returns 00:00:00 when now equals started_at', () => {
    fc.assert(
      fc.property(pastTimestampMsArb, (startMs) => {
        const startedAt = new Date(startMs).toISOString()
        const now = new Date(startMs)

        expect(formatElapsedTime(startedAt, now)).toBe('00:00:00')
      }),
      { numRuns: 5 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 12: Accumulated time is sum of durations                  */
/*  **Validates: Requirements 4.10, 4.11**                             */
/* ------------------------------------------------------------------ */

describe('Property 12: Accumulated time is sum of durations', () => {
  it('total equals sum of duration_minutes for completed entries', () => {
    fc.assert(
      fc.property(fc.array(completedTimeEntryArb, { minLength: 0, maxLength: 10 }), (entries) => {
        const expected = entries.reduce((sum, e) => sum + (e.duration_minutes ?? 0), 0)
        expect(calculateAccumulatedMinutes(entries)).toBe(expected)
      }),
      { numRuns: 5 },
    )
  })

  it('active entries (stopped_at == null) are excluded from the sum', () => {
    fc.assert(
      fc.property(mixedEntriesArb, (entries) => {
        const completedOnly = entries.filter((e) => e.stopped_at != null)
        const expectedSum = completedOnly.reduce((sum, e) => sum + (e.duration_minutes ?? 0), 0)
        expect(calculateAccumulatedMinutes(entries)).toBe(expectedSum)
      }),
      { numRuns: 5 },
    )
  })

  it('returns 0 for an empty entries array', () => {
    expect(calculateAccumulatedMinutes([])).toBe(0)
  })

  it('returns 0 when all entries are active (no completed entries)', () => {
    fc.assert(
      fc.property(fc.array(activeTimeEntryArb, { minLength: 1, maxLength: 5 }), (entries) => {
        expect(calculateAccumulatedMinutes(entries)).toBe(0)
      }),
      { numRuns: 5 },
    )
  })
})
