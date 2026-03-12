import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { canActOnBooking } from '../pages/bookings/BookingListPanel'
import type { BookingListItem } from '../pages/bookings/BookingListPanel'

// Feature: booking-to-job-workflow, Property 3: Cancel button visibility
// Feature: booking-to-job-workflow, Property 5: Create Job button visibility

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

const ACTIONABLE_STATUSES = ['pending', 'scheduled', 'confirmed'] as const
const NON_ACTIONABLE_STATUSES = ['cancelled', 'completed', 'no_show'] as const
const ALL_STATUSES = [...ACTIONABLE_STATUSES, ...NON_ACTIONABLE_STATUSES] as const

/** Generate a random actionable status */
const actionableStatusArb = fc.constantFrom(...ACTIONABLE_STATUSES)

/** Generate a random non-actionable status */
const nonActionableStatusArb = fc.constantFrom(...NON_ACTIONABLE_STATUSES)

/** Generate any known status */
const anyStatusArb = fc.constantFrom(...ALL_STATUSES)

/** Generate a null or non-null converted_job_id */
const convertedJobIdArb = fc.oneof(fc.constant(null), fc.uuid())

/** Generate a full BookingListItem with the given status and converted_job_id */
function bookingArb(
  statusArb: fc.Arbitrary<string>,
  jobIdArb: fc.Arbitrary<string | null>,
): fc.Arbitrary<BookingListItem> {
  return fc.record({
    id: fc.uuid(),
    customer_name: fc.option(fc.string({ minLength: 1, maxLength: 30 }), { nil: null }),
    vehicle_rego: fc.option(fc.string({ minLength: 1, maxLength: 10 }), { nil: null }),
    service_type: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: null }),
    scheduled_at: fc.option(fc.constant('2026-03-15T10:00:00Z'), { nil: null }),
    start_time: fc.option(fc.constant('2026-03-15T10:00:00Z'), { nil: null }),
    end_time: fc.option(fc.constant('2026-03-15T11:00:00Z'), { nil: null }),
    duration_minutes: fc.nat({ max: 480 }),
    status: statusArb,
    notes: fc.option(fc.string({ maxLength: 50 }), { nil: null }),
    converted_job_id: jobIdArb,
  })
}

/** Generate a BookingListItem with any status and any converted_job_id */
const anyBookingArb = bookingArb(anyStatusArb, convertedJobIdArb)

/* ------------------------------------------------------------------ */
/*  Property 3: Cancel button visibility                               */
/*  **Validates: Requirements 2.1, 2.5**                               */
/* ------------------------------------------------------------------ */

describe('Property 3: Cancel button visibility', () => {
  it('Cancel button is visible when status is actionable and converted_job_id is null', () => {
    fc.assert(
      fc.property(bookingArb(actionableStatusArb, fc.constant(null)), (booking) => {
        expect(canActOnBooking(booking)).toBe(true)
      }),
      { numRuns: 5 },
    )
  })

  it('Cancel button is hidden when status is non-actionable regardless of converted_job_id', () => {
    fc.assert(
      fc.property(bookingArb(nonActionableStatusArb, convertedJobIdArb), (booking) => {
        expect(canActOnBooking(booking)).toBe(false)
      }),
      { numRuns: 5 },
    )
  })

  it('Cancel button is hidden when converted_job_id is set regardless of status', () => {
    fc.assert(
      fc.property(bookingArb(anyStatusArb, fc.uuid()), (booking) => {
        expect(canActOnBooking(booking)).toBe(false)
      }),
      { numRuns: 5 },
    )
  })

  it('Cancel button visibility matches status ∈ {pending, scheduled, confirmed} AND converted_job_id is null for any booking', () => {
    fc.assert(
      fc.property(anyBookingArb, (booking) => {
        const expected =
          ['pending', 'scheduled', 'confirmed'].includes(booking.status) &&
          booking.converted_job_id == null
        expect(canActOnBooking(booking)).toBe(expected)
      }),
      { numRuns: 5 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 5: Create Job button visibility                           */
/*  **Validates: Requirements 3.1, 3.9**                               */
/* ------------------------------------------------------------------ */

describe('Property 5: Create Job button visibility', () => {
  it('Create Job button is visible when status is actionable and converted_job_id is null', () => {
    fc.assert(
      fc.property(bookingArb(actionableStatusArb, fc.constant(null)), (booking) => {
        expect(canActOnBooking(booking)).toBe(true)
      }),
      { numRuns: 5 },
    )
  })

  it('Create Job button is hidden when converted_job_id is set (link to job shown instead)', () => {
    fc.assert(
      fc.property(bookingArb(anyStatusArb, fc.uuid()), (booking) => {
        // When converted_job_id is not null, canActOnBooking returns false
        // and the UI shows a "View Job" link instead
        expect(canActOnBooking(booking)).toBe(false)
        expect(booking.converted_job_id).not.toBeNull()
      }),
      { numRuns: 5 },
    )
  })

  it('Create Job button is hidden when status is non-actionable and no job exists', () => {
    fc.assert(
      fc.property(bookingArb(nonActionableStatusArb, fc.constant(null)), (booking) => {
        expect(canActOnBooking(booking)).toBe(false)
      }),
      { numRuns: 5 },
    )
  })

  it('Create Job button visibility matches status ∈ {pending, scheduled, confirmed} AND converted_job_id is null for any booking', () => {
    fc.assert(
      fc.property(anyBookingArb, (booking) => {
        const expected =
          ['pending', 'scheduled', 'confirmed'].includes(booking.status) &&
          booking.converted_job_id == null
        expect(canActOnBooking(booking)).toBe(expected)
      }),
      { numRuns: 5 },
    )
  })
})

// Feature: booking-to-job-workflow, Property 6: Job creation pre-populates from booking

import { mapBookingToJobPreFill } from '../pages/bookings/JobCreationModal'

/* ------------------------------------------------------------------ */
/*  Property 6: Job creation pre-populates from booking                */
/*  **Validates: Requirements 3.2**                                    */
/* ------------------------------------------------------------------ */

describe('Property 6: Job creation pre-populates from booking', () => {
  /** Generate a BookingListItem with arbitrary string fields */
  const bookingWithFieldsArb = fc.record({
    id: fc.uuid(),
    customer_name: fc.option(fc.string({ minLength: 1, maxLength: 30 }), { nil: null }),
    vehicle_rego: fc.option(fc.string({ minLength: 1, maxLength: 10 }), { nil: null }),
    service_type: fc.option(fc.string({ minLength: 1, maxLength: 40 }), { nil: null }),
    scheduled_at: fc.option(fc.constant('2026-03-15T10:00:00Z'), { nil: null }),
    start_time: fc.option(fc.constant('2026-03-15T10:00:00Z'), { nil: null }),
    end_time: fc.option(fc.constant('2026-03-15T11:00:00Z'), { nil: null }),
    duration_minutes: fc.nat({ max: 480 }),
    status: fc.constantFrom('pending', 'scheduled', 'confirmed'),
    notes: fc.option(fc.string({ maxLength: 100 }), { nil: null }),
    converted_job_id: fc.constant(null),
  })

  it('description equals booking service_type for any booking', () => {
    fc.assert(
      fc.property(bookingWithFieldsArb, (booking) => {
        const preFill = mapBookingToJobPreFill(booking)
        expect(preFill.description).toBe(booking.service_type)
      }),
      { numRuns: 5 },
    )
  })

  it('notes equals booking notes for any booking', () => {
    fc.assert(
      fc.property(bookingWithFieldsArb, (booking) => {
        const preFill = mapBookingToJobPreFill(booking)
        expect(preFill.notes).toBe(booking.notes)
      }),
      { numRuns: 5 },
    )
  })

  it('vehicle_rego equals booking vehicle_rego for any booking', () => {
    fc.assert(
      fc.property(bookingWithFieldsArb, (booking) => {
        const preFill = mapBookingToJobPreFill(booking)
        expect(preFill.vehicle_rego).toBe(booking.vehicle_rego)
      }),
      { numRuns: 5 },
    )
  })

  it('all three fields map correctly together for any booking', () => {
    fc.assert(
      fc.property(bookingWithFieldsArb, (booking) => {
        const preFill = mapBookingToJobPreFill(booking)
        expect(preFill.description).toBe(booking.service_type)
        expect(preFill.notes).toBe(booking.notes)
        expect(preFill.vehicle_rego).toBe(booking.vehicle_rego)
      }),
      { numRuns: 5 },
    )
  })
})
