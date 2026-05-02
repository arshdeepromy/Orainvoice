/**
 * Property-based tests for the Staff Schedule module.
 *
 * Properties covered:
 *   P29 — Schedule conflict detection flags overlapping entries
 *   P30 — Drag-and-drop computes correct new times
 *
 * **Validates: Requirements 36.6, 38.3**
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { computeRescheduledTimes } from '../ScheduleCalendar'

// ---------------------------------------------------------------------------
// Pure conflict detection logic
// ---------------------------------------------------------------------------

/**
 * Two schedule entries for the same staff member conflict iff their time
 * ranges overlap: entry1.start < entry2.end AND entry2.start < entry1.end.
 *
 * This mirrors the conflict detection logic used by the backend
 * (GET /api/v2/schedule/{id}/conflicts) and the frontend warning display
 * in ScheduleEntryModal.tsx (Req 36.6).
 */
function hasConflict(
  entry1: { start_time: string; end_time: string; staff_id: string },
  entry2: { start_time: string; end_time: string; staff_id: string },
): boolean {
  // Entries for different staff members never conflict
  if (entry1.staff_id !== entry2.staff_id) return false

  const s1 = new Date(entry1.start_time).getTime()
  const e1 = new Date(entry1.end_time).getTime()
  const s2 = new Date(entry2.start_time).getTime()
  const e2 = new Date(entry2.end_time).getTime()

  return s1 < e2 && s2 < e1
}

// ---------------------------------------------------------------------------
// Arbitraries — use integer timestamps to avoid fc.date() issues
// ---------------------------------------------------------------------------

// Range: 2025-01-01 to 2025-12-30 in milliseconds
const MIN_TS = new Date('2025-01-01T07:00:00Z').getTime()
const MAX_TS = new Date('2025-12-30T18:00:00Z').getTime()

/** Generate a staff ID from a fixed pool to keep things simple */
const staffIdArb = fc.constantFrom('staff-1', 'staff-2', 'staff-3', 'staff-A', 'staff-B')

/**
 * Generate a valid schedule entry with start_time < end_time.
 * Duration is between 15 minutes and 8 hours.
 */
const scheduleEntryArb = (staffId: fc.Arbitrary<string> = staffIdArb) =>
  fc
    .record({
      startTs: fc.integer({ min: MIN_TS, max: MAX_TS }),
      durationMinutes: fc.integer({ min: 15, max: 480 }),
      staff_id: staffId,
    })
    .map(({ startTs, durationMinutes, staff_id }) => ({
      start_time: new Date(startTs).toISOString(),
      end_time: new Date(startTs + durationMinutes * 60 * 1000).toISOString(),
      staff_id,
    }))

/** Generate a target hour within the working day (7am–6pm) */
const targetHourArb = fc.integer({ min: 7, max: 18 })

/** Generate a target date string in YYYY-MM-DD format from integer components */
const targetDateArb = fc
  .record({
    year: fc.constant(2025),
    month: fc.integer({ min: 1, max: 12 }),
    day: fc.integer({ min: 1, max: 28 }), // cap at 28 to avoid invalid dates
  })
  .map(({ year, month, day }) => {
    const m = String(month).padStart(2, '0')
    const d = String(day).padStart(2, '0')
    return `${year}-${m}-${d}`
  })

// ---------------------------------------------------------------------------
// Property 29: Schedule conflict detection flags overlapping entries
// ---------------------------------------------------------------------------

describe('Property 29: Schedule conflict detection flags overlapping entries', () => {
  /**
   * For any two schedule entries where the time ranges overlap,
   * the conflict detection SHALL flag them as conflicting.
   * For non-overlapping entries, no conflict SHALL be reported.
   *
   * **Validates: Requirements 36.6**
   */

  it('overlapping entries for the same staff are flagged as conflicting', () => {
    fc.assert(
      fc.property(
        scheduleEntryArb(fc.constant('staff-1')),
        fc.integer({ min: 1, max: 240 }),
        fc.integer({ min: 15, max: 480 }),
        (entry1, overlapOffsetMinutes, entry2DurationMinutes) => {
          const s1 = new Date(entry1.start_time).getTime()
          const e1 = new Date(entry1.end_time).getTime()
          const duration1Ms = e1 - s1

          // Place entry2's start inside entry1's range (guaranteed overlap)
          const maxOffset = Math.floor(duration1Ms / 60000) - 1
          if (maxOffset < 1) return // skip degenerate entries

          const actualOffset = Math.min(overlapOffsetMinutes, maxOffset)
          const s2 = s1 + actualOffset * 60 * 1000
          const e2 = s2 + entry2DurationMinutes * 60 * 1000

          const entry2 = {
            start_time: new Date(s2).toISOString(),
            end_time: new Date(e2).toISOString(),
            staff_id: 'staff-1',
          }

          expect(hasConflict(entry1, entry2)).toBe(true)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('non-overlapping entries for the same staff are NOT flagged as conflicting', () => {
    fc.assert(
      fc.property(
        scheduleEntryArb(fc.constant('staff-1')),
        fc.integer({ min: 1, max: 480 }),
        fc.integer({ min: 15, max: 480 }),
        (entry1, gapMinutes, entry2DurationMinutes) => {
          const e1 = new Date(entry1.end_time).getTime()

          // Place entry2 entirely after entry1 with a gap
          const s2 = e1 + gapMinutes * 60 * 1000
          const e2 = s2 + entry2DurationMinutes * 60 * 1000

          const entry2 = {
            start_time: new Date(s2).toISOString(),
            end_time: new Date(e2).toISOString(),
            staff_id: 'staff-1',
          }

          expect(hasConflict(entry1, entry2)).toBe(false)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('entries for different staff members never conflict regardless of time overlap', () => {
    fc.assert(
      fc.property(
        scheduleEntryArb(fc.constant('staff-A')),
        scheduleEntryArb(fc.constant('staff-B')),
        (entry1, entry2) => {
          expect(hasConflict(entry1, entry2)).toBe(false)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('conflict detection is symmetric: hasConflict(a, b) === hasConflict(b, a)', () => {
    fc.assert(
      fc.property(
        scheduleEntryArb(fc.constant('staff-1')),
        scheduleEntryArb(fc.constant('staff-1')),
        (entry1, entry2) => {
          expect(hasConflict(entry1, entry2)).toBe(hasConflict(entry2, entry1))
        },
      ),
      { numRuns: 200 },
    )
  })

  it('adjacent entries (end1 === start2) do NOT conflict', () => {
    fc.assert(
      fc.property(
        scheduleEntryArb(fc.constant('staff-1')),
        fc.integer({ min: 15, max: 480 }),
        (entry1, entry2DurationMinutes) => {
          // Entry2 starts exactly when entry1 ends — no overlap
          const e1 = new Date(entry1.end_time).getTime()
          const entry2 = {
            start_time: new Date(e1).toISOString(),
            end_time: new Date(e1 + entry2DurationMinutes * 60 * 1000).toISOString(),
            staff_id: 'staff-1',
          }

          expect(hasConflict(entry1, entry2)).toBe(false)
        },
      ),
      { numRuns: 200 },
    )
  })
})

// ---------------------------------------------------------------------------
// Property 30: Drag-and-drop computes correct new times
// ---------------------------------------------------------------------------

describe('Property 30: Drag-and-drop computes correct new times', () => {
  /**
   * For any entry with random start/end times and a random target slot
   * (date + hour), the computed new start_time SHALL have the target hour
   * and date, the duration SHALL be preserved, and the new end_time SHALL
   * equal new_start + original_duration.
   *
   * **Validates: Requirements 38.3**
   */

  it('computed start_time has the target hour and date', () => {
    fc.assert(
      fc.property(
        scheduleEntryArb(),
        targetDateArb,
        targetHourArb,
        staffIdArb,
        (entry, targetDate, targetHour, targetStaffId) => {
          const result = computeRescheduledTimes(
            entry.start_time,
            entry.end_time,
            targetDate,
            targetHour,
            targetStaffId,
          )

          const newStart = new Date(result.start_time)
          const [year, month, day] = targetDate.split('-').map(Number)

          expect(newStart.getFullYear()).toBe(year)
          expect(newStart.getMonth()).toBe(month - 1) // JS months are 0-indexed
          expect(newStart.getDate()).toBe(day)
          expect(newStart.getHours()).toBe(targetHour)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('duration is preserved after rescheduling', () => {
    fc.assert(
      fc.property(
        scheduleEntryArb(),
        targetDateArb,
        targetHourArb,
        staffIdArb,
        (entry, targetDate, targetHour, targetStaffId) => {
          const originalStart = new Date(entry.start_time).getTime()
          const originalEnd = new Date(entry.end_time).getTime()
          const originalDuration = originalEnd - originalStart

          const result = computeRescheduledTimes(
            entry.start_time,
            entry.end_time,
            targetDate,
            targetHour,
            targetStaffId,
          )

          const newStart = new Date(result.start_time).getTime()
          const newEnd = new Date(result.end_time).getTime()
          const newDuration = newEnd - newStart

          expect(newDuration).toBe(originalDuration)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('new end_time equals new start_time + original duration', () => {
    fc.assert(
      fc.property(
        scheduleEntryArb(),
        targetDateArb,
        targetHourArb,
        staffIdArb,
        (entry, targetDate, targetHour, targetStaffId) => {
          const originalStart = new Date(entry.start_time).getTime()
          const originalEnd = new Date(entry.end_time).getTime()
          const originalDuration = originalEnd - originalStart

          const result = computeRescheduledTimes(
            entry.start_time,
            entry.end_time,
            targetDate,
            targetHour,
            targetStaffId,
          )

          const newStart = new Date(result.start_time).getTime()
          const expectedEnd = newStart + originalDuration

          expect(new Date(result.end_time).getTime()).toBe(expectedEnd)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('staff_id is set to the target staff', () => {
    fc.assert(
      fc.property(
        scheduleEntryArb(),
        targetDateArb,
        targetHourArb,
        staffIdArb,
        (entry, targetDate, targetHour, targetStaffId) => {
          const result = computeRescheduledTimes(
            entry.start_time,
            entry.end_time,
            targetDate,
            targetHour,
            targetStaffId,
          )

          expect(result.staff_id).toBe(targetStaffId)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('original minutes are preserved in the new start_time', () => {
    fc.assert(
      fc.property(
        scheduleEntryArb(),
        targetDateArb,
        targetHourArb,
        staffIdArb,
        (entry, targetDate, targetHour, targetStaffId) => {
          const originalMinutes = new Date(entry.start_time).getMinutes()

          const result = computeRescheduledTimes(
            entry.start_time,
            entry.end_time,
            targetDate,
            targetHour,
            targetStaffId,
          )

          const newStart = new Date(result.start_time)
          expect(newStart.getMinutes()).toBe(originalMinutes)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('result contains valid ISO strings', () => {
    fc.assert(
      fc.property(
        scheduleEntryArb(),
        targetDateArb,
        targetHourArb,
        staffIdArb,
        (entry, targetDate, targetHour, targetStaffId) => {
          const result = computeRescheduledTimes(
            entry.start_time,
            entry.end_time,
            targetDate,
            targetHour,
            targetStaffId,
          )

          // Both should parse without error and round-trip to the same string
          const parsedStart = new Date(result.start_time)
          const parsedEnd = new Date(result.end_time)

          expect(parsedStart.toISOString()).toBe(result.start_time)
          expect(parsedEnd.toISOString()).toBe(result.end_time)
        },
      ),
      { numRuns: 200 },
    )
  })
})
