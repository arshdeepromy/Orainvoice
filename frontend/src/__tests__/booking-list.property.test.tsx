import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  sortBookingsByStartTime,
  filterBookingsByDateRange,
  bookingSortKey,
} from '../pages/bookings/BookingListPanel'
import type { BookingListItem } from '../pages/bookings/BookingListPanel'

// Feature: booking-to-job-workflow, Property 1: Booking date range filtering
// Feature: booking-to-job-workflow, Property 2: Booking list sort order

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Generate an ISO datetime string within a reasonable range (2026-01 to 2026-12). */
const isoDateTimeArb = fc
  .integer({
    min: new Date('2026-01-01T00:00:00Z').getTime(),
    max: new Date('2026-12-31T23:59:59Z').getTime(),
  })
  .map((ms) => new Date(ms).toISOString())

/** Generate a BookingListItem with a given start_time arbitrary. */
function bookingWithTimeArb(
  startTimeArb: fc.Arbitrary<string | null>,
): fc.Arbitrary<BookingListItem> {
  return fc.record({
    id: fc.uuid(),
    customer_name: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: null }),
    vehicle_rego: fc.option(fc.string({ minLength: 1, maxLength: 10 }), { nil: null }),
    service_type: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: null }),
    scheduled_at: fc.option(isoDateTimeArb, { nil: null }),
    start_time: startTimeArb,
    end_time: fc.option(isoDateTimeArb, { nil: null }),
    duration_minutes: fc.nat({ max: 480 }),
    status: fc.constantFrom('pending', 'scheduled', 'confirmed', 'cancelled', 'completed'),
    notes: fc.option(fc.string({ maxLength: 50 }), { nil: null }),
    converted_job_id: fc.option(fc.uuid(), { nil: null }),
  })
}

/** Booking with a non-null start_time. */
const bookingWithStartTimeArb = bookingWithTimeArb(isoDateTimeArb)

/** Booking with start_time that may be null (falls back to scheduled_at). */
const bookingWithOptionalTimeArb = bookingWithTimeArb(
  fc.option(isoDateTimeArb, { nil: null }),
)

/** Generate a sorted pair of ISO date strings [start, end] for a date range. */
const dateRangeArb = fc
  .tuple(isoDateTimeArb, isoDateTimeArb)
  .map(([a, b]) => (a <= b ? [a, b] : [b, a]) as [string, string])

/* ------------------------------------------------------------------ */
/*  Property 1: Booking date range filtering                           */
/*  **Validates: Requirements 1.3**                                    */
/* ------------------------------------------------------------------ */

describe('Property 1: Booking date range filtering', () => {
  it('returns exactly those bookings whose start_time falls within [start, end]', () => {
    fc.assert(
      fc.property(
        fc.array(bookingWithStartTimeArb, { minLength: 0, maxLength: 10 }),
        dateRangeArb,
        (bookings, [start, end]) => {
          const filtered = filterBookingsByDateRange(bookings, start, end)

          // Every returned booking must have start_time within [start, end]
          for (const b of filtered) {
            const t = b.start_time ?? b.scheduled_at
            expect(t).not.toBeNull()
            expect(t! >= start && t! <= end).toBe(true)
          }

          // Every booking NOT returned must have start_time outside [start, end]
          const filteredIds = new Set(filtered.map((b) => b.id))
          for (const b of bookings) {
            if (!filteredIds.has(b.id)) {
              const t = b.start_time ?? b.scheduled_at
              if (t != null) {
                expect(t < start || t > end).toBe(true)
              }
            }
          }
        },
      ),
      { numRuns: 5 },
    )
  })

  it('bookings with null start_time and null scheduled_at are excluded', () => {
    fc.assert(
      fc.property(
        fc.array(bookingWithOptionalTimeArb, { minLength: 1, maxLength: 10 }),
        dateRangeArb,
        (bookings, [start, end]) => {
          const filtered = filterBookingsByDateRange(bookings, start, end)

          for (const b of filtered) {
            const t = b.start_time ?? b.scheduled_at
            expect(t).not.toBeNull()
          }
        },
      ),
      { numRuns: 5 },
    )
  })

  it('filtering with a range that covers all bookings returns all bookings with times', () => {
    fc.assert(
      fc.property(
        fc.array(bookingWithStartTimeArb, { minLength: 1, maxLength: 10 }),
        (bookings) => {
          // Use the widest possible range
          const filtered = filterBookingsByDateRange(
            bookings,
            '2025-01-01T00:00:00.000Z',
            '2027-12-31T23:59:59.999Z',
          )
          // All bookings with a start_time should be included
          const withTime = bookings.filter((b) => (b.start_time ?? b.scheduled_at) != null)
          expect(filtered.length).toBe(withTime.length)
        },
      ),
      { numRuns: 5 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 2: Booking list sort order                                */
/*  **Validates: Requirements 1.4**                                    */
/* ------------------------------------------------------------------ */

describe('Property 2: Booking list sort order', () => {
  it('for every consecutive pair, booking[i].start_time <= booking[i+1].start_time', () => {
    fc.assert(
      fc.property(
        fc.array(bookingWithOptionalTimeArb, { minLength: 0, maxLength: 15 }),
        (bookings) => {
          const sorted = sortBookingsByStartTime(bookings)

          for (let i = 0; i < sorted.length - 1; i++) {
            const keyA = bookingSortKey(sorted[i])
            const keyB = bookingSortKey(sorted[i + 1])
            expect(keyA <= keyB).toBe(true)
          }
        },
      ),
      { numRuns: 5 },
    )
  })

  it('sorting preserves all original bookings (same length, same ids)', () => {
    fc.assert(
      fc.property(
        fc.array(bookingWithOptionalTimeArb, { minLength: 0, maxLength: 15 }),
        (bookings) => {
          const sorted = sortBookingsByStartTime(bookings)

          expect(sorted.length).toBe(bookings.length)

          const originalIds = new Set(bookings.map((b) => b.id))
          const sortedIds = new Set(sorted.map((b) => b.id))
          expect(sortedIds).toEqual(originalIds)
        },
      ),
      { numRuns: 5 },
    )
  })

  it('sorting does not mutate the original array', () => {
    fc.assert(
      fc.property(
        fc.array(bookingWithOptionalTimeArb, { minLength: 1, maxLength: 10 }),
        (bookings) => {
          const originalOrder = bookings.map((b) => b.id)
          sortBookingsByStartTime(bookings)
          const afterOrder = bookings.map((b) => b.id)
          expect(afterOrder).toEqual(originalOrder)
        },
      ),
      { numRuns: 5 },
    )
  })

  it('sorting is idempotent — sorting twice gives the same result', () => {
    fc.assert(
      fc.property(
        fc.array(bookingWithOptionalTimeArb, { minLength: 0, maxLength: 10 }),
        (bookings) => {
          const once = sortBookingsByStartTime(bookings)
          const twice = sortBookingsByStartTime(once)
          expect(twice.map((b) => b.id)).toEqual(once.map((b) => b.id))
        },
      ),
      { numRuns: 5 },
    )
  })
})
