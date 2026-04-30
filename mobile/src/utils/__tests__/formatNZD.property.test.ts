// Feature: mobile-konsta-redesign, Property 5: Currency formatting correctness
// **Validates: Requirements 56.4**

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { formatNZD } from '@/utils/formatNZD'

/**
 * Property 5: Currency formatting correctness.
 *
 * For any numeric value (including 0, negative numbers, and large numbers
 * up to 1e12), formatNZD(value) SHALL return a string that starts with "NZD"
 * followed by a locale-formatted number with exactly 2 decimal places.
 * Additionally, formatNZD(null) and formatNZD(undefined) SHALL both return
 * "NZD0.00".
 */
describe('Property 5: Currency formatting correctness', () => {
  // Arbitrary for numeric values including 0, negatives, and large numbers
  const numericArb = fc.oneof(
    fc.constant(0),
    fc.integer({ min: -1000000, max: 1000000 }),
    fc.double({ min: -1e9, max: 1e9, noNaN: true, noDefaultInfinity: true }),
  )

  it('output always starts with "NZD"', () => {
    fc.assert(
      fc.property(numericArb, (value) => {
        const result = formatNZD(value)
        expect(result.startsWith('NZD')).toBe(true)
      }),
      { numRuns: 200 },
    )
  })

  it('output has exactly 2 decimal places', () => {
    fc.assert(
      fc.property(numericArb, (value) => {
        const result = formatNZD(value)
        // Extract the part after "NZD"
        const numPart = result.slice(3)
        // The number part should end with .XX (exactly 2 decimal digits)
        const match = numPart.match(/\.(\d+)$/)
        expect(match).not.toBeNull()
        expect(match![1]).toHaveLength(2)
      }),
      { numRuns: 200 },
    )
  })

  it('formatNZD(null) returns "NZD0.00"', () => {
    expect(formatNZD(null)).toBe('NZD0.00')
  })

  it('formatNZD(undefined) returns "NZD0.00"', () => {
    expect(formatNZD(undefined)).toBe('NZD0.00')
  })

  it('formatNZD(0) returns "NZD0.00"', () => {
    expect(formatNZD(0)).toBe('NZD0.00')
  })

  it('output is a non-empty string for any numeric input', () => {
    fc.assert(
      fc.property(numericArb, (value) => {
        const result = formatNZD(value)
        expect(result.length).toBeGreaterThan(3) // At least "NZD" + some digits
      }),
      { numRuns: 200 },
    )
  })
})
