import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  calculateOutstandingRetention,
  validateReleaseAmount,
  calculateRetentionPercentage,
} from '../utils/retentionCalcs'

// Feature: production-readiness-gaps, Property 9: Retention release cannot exceed outstanding balance
// **Validates: Requirements 5.5**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Non-negative currency value */
const currencyArb = fc
  .float({ min: 0, max: 1e9, noNaN: true, noDefaultInfinity: true })
  .map((v) => Math.round(v * 100) / 100)

/** Strictly positive currency value */
const positiveCurrencyArb = fc
  .float({ min: Math.fround(0.01), max: 1e9, noNaN: true, noDefaultInfinity: true })
  .map((v) => Math.round(v * 100) / 100)

/**
 * Generate a valid retained/released pair where totalReleased <= totalRetained,
 * ensuring outstanding >= 0.
 */
const retainedReleasedArb = currencyArb.chain((retained) =>
  fc
    .float({ min: 0, max: Math.fround(Math.max(retained, 0)), noNaN: true, noDefaultInfinity: true })
    .map((released) => ({
      totalRetained: retained,
      totalReleased: Math.round(released * 100) / 100,
    })),
)

/* ------------------------------------------------------------------ */
/*  Property 9: Retention release cannot exceed outstanding balance    */
/* ------------------------------------------------------------------ */

describe('Property 9: Retention release cannot exceed outstanding balance', () => {
  it('outstanding = totalRetained - totalReleased', () => {
    fc.assert(
      fc.property(currencyArb, currencyArb, (retained, released) => {
        const result = calculateOutstandingRetention(retained, released)
        expect(result).toBeCloseTo(retained - released, 2)
      }),
      { numRuns: 100 },
    )
  })

  it('release amount > outstanding is invalid', () => {
    fc.assert(
      fc.property(
        retainedReleasedArb,
        positiveCurrencyArb,
        ({ totalRetained, totalReleased }, extra) => {
          const outstanding = calculateOutstandingRetention(totalRetained, totalReleased)
          const releaseAmount = outstanding + extra // always exceeds outstanding
          const result = validateReleaseAmount(releaseAmount, outstanding)
          expect(result.valid).toBe(false)
          expect(result.error).toBeDefined()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('0 < release amount <= outstanding is valid', () => {
    fc.assert(
      fc.property(
        retainedReleasedArb.filter(
          ({ totalRetained, totalReleased }) => totalRetained - totalReleased > 0,
        ),
        fc.float({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
        ({ totalRetained, totalReleased }, fraction) => {
          const outstanding = calculateOutstandingRetention(totalRetained, totalReleased)
          // Scale fraction to (0, outstanding] range
          const releaseAmount = Math.round((0.01 + fraction * (outstanding - 0.01)) * 100) / 100
          if (releaseAmount > 0 && releaseAmount <= outstanding) {
            const result = validateReleaseAmount(releaseAmount, outstanding)
            expect(result.valid).toBe(true)
            expect(result.error).toBeUndefined()
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('release amount exactly equal to outstanding is valid', () => {
    fc.assert(
      fc.property(positiveCurrencyArb, (outstanding) => {
        const result = validateReleaseAmount(outstanding, outstanding)
        expect(result.valid).toBe(true)
        expect(result.error).toBeUndefined()
      }),
      { numRuns: 100 },
    )
  })

  it('release amount of zero is invalid', () => {
    fc.assert(
      fc.property(positiveCurrencyArb, (outstanding) => {
        const result = validateReleaseAmount(0, outstanding)
        expect(result.valid).toBe(false)
        expect(result.error).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  it('negative release amount is invalid', () => {
    fc.assert(
      fc.property(
        positiveCurrencyArb,
        fc.float({ min: -1e9, max: Math.fround(-0.01), noNaN: true, noDefaultInfinity: true }),
        (outstanding, negativeAmount) => {
          const result = validateReleaseAmount(negativeAmount, outstanding)
          expect(result.valid).toBe(false)
          expect(result.error).toBeDefined()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('zero outstanding means any positive release is invalid', () => {
    fc.assert(
      fc.property(positiveCurrencyArb, (releaseAmount) => {
        const result = validateReleaseAmount(releaseAmount, 0)
        expect(result.valid).toBe(false)
        expect(result.error).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  it('retention percentage is calculated correctly', () => {
    fc.assert(
      fc.property(currencyArb, positiveCurrencyArb, (retained, contractValue) => {
        const result = calculateRetentionPercentage(retained, contractValue)
        expect(result).toBeCloseTo((retained / contractValue) * 100, 2)
      }),
      { numRuns: 100 },
    )
  })

  it('retention percentage is 0 when contract value is 0', () => {
    fc.assert(
      fc.property(currencyArb, (retained) => {
        const result = calculateRetentionPercentage(retained, 0)
        expect(result).toBe(0)
      }),
      { numRuns: 100 },
    )
  })
})
