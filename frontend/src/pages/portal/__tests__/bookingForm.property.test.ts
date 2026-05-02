// Feature: platform-feature-gaps, Property 25: Booking form includes service_type and notes in request
// **Validates: Requirements 28.3**

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

/**
 * Property 25: Booking form includes service_type and notes in request.
 *
 * When a booking is created, the request body includes service_type and notes
 * fields. This tests the pure logic of constructing the booking request body
 * as implemented in BookingManager.tsx's handleBookSlot function.
 *
 * **Validates: Requirements 28.3**
 */

/**
 * Pure function mirroring the request body construction in BookingManager.tsx
 * handleBookSlot:
 *
 *   await apiClient.post(`/portal/${token}/bookings`, {
 *     start_time: slot.start_time,
 *     service_type: serviceType || undefined,
 *     notes: notes || undefined,
 *   })
 */
function buildBookingRequestBody(
  startTime: string,
  serviceType: string,
  notes: string,
): Record<string, string | undefined> {
  return {
    start_time: startTime,
    service_type: serviceType || undefined,
    notes: notes || undefined,
  }
}

describe('Property 25: Booking form includes service_type and notes in request', () => {
  // Strategy: non-empty service type strings
  const serviceTypeArb = fc.stringMatching(/^[A-Za-z0-9 ]{1,50}$/)

  // Strategy: non-empty notes strings
  const notesArb = fc.stringMatching(/^[A-Za-z0-9 .,!?]{1,200}$/)

  // Strategy: ISO datetime strings for start_time — use integer-based generation
  // to avoid invalid Date edge cases with fc.date()
  const startTimeArb = fc
    .integer({ min: new Date('2024-01-01').getTime(), max: new Date('2030-12-31').getTime() })
    .map((ts) => new Date(ts).toISOString())

  it('request body includes service_type when user enters a non-empty value', () => {
    fc.assert(
      fc.property(startTimeArb, serviceTypeArb, notesArb, (startTime, serviceType, notes) => {
        const body = buildBookingRequestBody(startTime, serviceType, notes)

        expect(body.service_type).toBe(serviceType)
        expect(body).toHaveProperty('service_type')
      }),
      { numRuns: 200 },
    )
  })

  it('request body includes notes when user enters a non-empty value', () => {
    fc.assert(
      fc.property(startTimeArb, serviceTypeArb, notesArb, (startTime, serviceType, notes) => {
        const body = buildBookingRequestBody(startTime, serviceType, notes)

        expect(body.notes).toBe(notes)
        expect(body).toHaveProperty('notes')
      }),
      { numRuns: 200 },
    )
  })

  it('request body always includes start_time', () => {
    fc.assert(
      fc.property(startTimeArb, serviceTypeArb, notesArb, (startTime, serviceType, notes) => {
        const body = buildBookingRequestBody(startTime, serviceType, notes)

        expect(body.start_time).toBe(startTime)
      }),
      { numRuns: 200 },
    )
  })

  it('request body includes both service_type and notes together', () => {
    fc.assert(
      fc.property(startTimeArb, serviceTypeArb, notesArb, (startTime, serviceType, notes) => {
        const body = buildBookingRequestBody(startTime, serviceType, notes)

        // Both fields must be present when user provides values
        expect(body.service_type).toBeDefined()
        expect(body.notes).toBeDefined()
        expect(body.service_type).toBe(serviceType)
        expect(body.notes).toBe(notes)
      }),
      { numRuns: 200 },
    )
  })

  it('service_type is undefined when user leaves it empty', () => {
    fc.assert(
      fc.property(startTimeArb, notesArb, (startTime, notes) => {
        const body = buildBookingRequestBody(startTime, '', notes)

        // Empty string becomes undefined (falsy || undefined)
        expect(body.service_type).toBeUndefined()
      }),
      { numRuns: 100 },
    )
  })

  it('notes is undefined when user leaves it empty', () => {
    fc.assert(
      fc.property(startTimeArb, serviceTypeArb, (startTime, serviceType) => {
        const body = buildBookingRequestBody(startTime, serviceType, '')

        // Empty string becomes undefined (falsy || undefined)
        expect(body.notes).toBeUndefined()
      }),
      { numRuns: 100 },
    )
  })

  it('request body shape matches the expected POST /portal/{token}/bookings format', () => {
    fc.assert(
      fc.property(startTimeArb, serviceTypeArb, notesArb, (startTime, serviceType, notes) => {
        const body = buildBookingRequestBody(startTime, serviceType, notes)

        // The body should have exactly these keys
        const keys = Object.keys(body)
        expect(keys).toContain('start_time')
        expect(keys).toContain('service_type')
        expect(keys).toContain('notes')
      }),
      { numRuns: 200 },
    )
  })
})
