import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { isValidThreshold } from '../ReminderConfigWidget'

// Feature: automotive-dashboard-widgets, Property 12: Reminder Config Validation Range
// **Validates: Requirements 12.6**

/* ------------------------------------------------------------------ */
/*  Property 12: Reminder Config Validation Range                      */
/* ------------------------------------------------------------------ */

describe('Property 12: Reminder Config Validation Range', () => {
  it('accepts only integers between 1 and 365 inclusive', () => {
    fc.assert(
      fc.property(fc.integer({ min: -1000, max: 1000 }), (value) => {
        const result = isValidThreshold(value)
        const expected = value >= 1 && value <= 365
        expect(result).toBe(expected)
      }),
      { numRuns: 100 },
    )
  })

  it('rejects zero', () => {
    fc.assert(
      fc.property(fc.constant(0), (value) => {
        expect(isValidThreshold(value)).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('rejects negative integers', () => {
    fc.assert(
      fc.property(fc.integer({ min: -10000, max: -1 }), (value) => {
        expect(isValidThreshold(value)).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('rejects integers above 365', () => {
    fc.assert(
      fc.property(fc.integer({ min: 366, max: 10000 }), (value) => {
        expect(isValidThreshold(value)).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('rejects non-integer numbers (floats)', () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0.01, max: 365.99, noNaN: true, noDefaultInfinity: true })
          .filter((v) => !Number.isInteger(v)),
        (value) => {
          expect(isValidThreshold(value)).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('accepts all valid values in the 1-365 range', () => {
    fc.assert(
      fc.property(fc.integer({ min: 1, max: 365 }), (value) => {
        expect(isValidThreshold(value)).toBe(true)
      }),
      { numRuns: 100 },
    )
  })
})
