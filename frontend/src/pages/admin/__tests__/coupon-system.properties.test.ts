import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { validateDiscountValue } from '../coupon-utils'

describe('Coupon System — Property-Based Tests', () => {
  // Feature: coupon-system, Property 12: Coupon form validation — discount_value by type

  // **Validates: Requirements 8.3–8.5**

  it('Property 12a: percentage type accepts values 1–100', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 100 }),
        (value) => {
          const result = validateDiscountValue(String(value), 'percentage')
          expect(result).toBeNull()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 12b: percentage type rejects values outside 1–100', () => {
    fc.assert(
      fc.property(
        fc.oneof(
          fc.integer({ min: -1000, max: 0 }),
          fc.integer({ min: 101, max: 10000 }),
        ),
        (value) => {
          const result = validateDiscountValue(String(value), 'percentage')
          expect(result).toBe('Must be between 1 and 100')
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 12c: fixed_amount type accepts values > 0', () => {
    fc.assert(
      fc.property(
        fc.float({ min: Math.fround(0.01), max: 1e6, noNaN: true }),
        (value) => {
          const result = validateDiscountValue(String(value), 'fixed_amount')
          expect(result).toBeNull()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 12d: fixed_amount type rejects values <= 0', () => {
    fc.assert(
      fc.property(
        fc.float({ min: -1e6, max: 0, noNaN: true }),
        (value) => {
          const result = validateDiscountValue(String(value), 'fixed_amount')
          expect(result).not.toBeNull()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 12e: trial_extension type accepts whole numbers > 0', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 10000 }),
        (value) => {
          const result = validateDiscountValue(String(value), 'trial_extension')
          expect(result).toBeNull()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 12f: trial_extension type rejects non-integer values', () => {
    fc.assert(
      fc.property(
        fc.float({ min: Math.fround(0.01), max: 1e6, noNaN: true }).filter((v) => !Number.isInteger(v) && v > 0),
        (value) => {
          const result = validateDiscountValue(String(value), 'trial_extension')
          expect(result).toBe('Must be a whole number greater than 0')
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 12g: trial_extension type rejects values <= 0', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: -1000, max: 0 }),
        (value) => {
          const result = validateDiscountValue(String(value), 'trial_extension')
          expect(result).not.toBeNull()
        },
      ),
      { numRuns: 100 },
    )
  })
})
