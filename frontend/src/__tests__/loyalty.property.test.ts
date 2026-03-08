import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  areTiersAscending,
  calculatePointsToNextTier,
  validatePointsAdjustment,
} from '../utils/loyaltyCalcs'

// Feature: production-readiness-gaps, Property 19: Loyalty tier thresholds are strictly ascending
// Feature: production-readiness-gaps, Property 20: Loyalty points to next tier calculation
// Feature: production-readiness-gaps, Property 21: Loyalty points adjustment requires reason
// **Validates: Requirements 10.3, 10.4, 10.6**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Generate a single tier with a positive threshold */
const tierArb = fc.nat({ max: 100_000 }).map((threshold) => ({ threshold }))

/** Generate a list of tiers (unsorted, may have duplicates) */
const tiersArb = fc.array(tierArb, { minLength: 0, maxLength: 20 })

/** Generate a strictly ascending list of tiers */
const ascendingTiersArb = fc
  .array(fc.integer({ min: 1, max: 10_000 }), { minLength: 1, maxLength: 10 })
  .map((deltas) => {
    const tiers: { threshold: number }[] = []
    let cumulative = 0
    for (const d of deltas) {
      cumulative += d
      tiers.push({ threshold: cumulative })
    }
    return tiers
  })

/** Generate a non-zero integer for points adjustment amount */
const nonZeroAmountArb = fc
  .integer({ min: -10_000, max: 10_000 })
  .filter((n) => n !== 0)

/** Generate a non-empty trimmed reason string */
const validReasonArb = fc
  .string({ minLength: 1, maxLength: 100 })
  .filter((s) => s.trim().length > 0)

/** Generate a whitespace-only or empty reason string */
const emptyReasonArb = fc.constantFrom('', ' ', '  ', '\t', '\n', '  \t\n  ')

/* ------------------------------------------------------------------ */
/*  Property 19: Loyalty tier thresholds are strictly ascending        */
/* ------------------------------------------------------------------ */

describe('Property 19: Loyalty tier thresholds are strictly ascending', () => {
  it('accepts strictly ascending tiers', () => {
    fc.assert(
      fc.property(ascendingTiersArb, (tiers) => {
        expect(areTiersAscending(tiers)).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('rejects tiers with duplicate thresholds', () => {
    fc.assert(
      fc.property(fc.nat({ max: 100_000 }), (threshold) => {
        const tiers = [{ threshold }, { threshold }]
        expect(areTiersAscending(tiers)).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('rejects tiers in descending order', () => {
    fc.assert(
      fc.property(
        fc.nat({ max: 50_000 }),
        fc.integer({ min: 1, max: 50_000 }),
        (base, delta) => {
          const tiers = [{ threshold: base + delta }, { threshold: base }]
          expect(areTiersAscending(tiers)).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('accepts empty and single-element tier lists', () => {
    expect(areTiersAscending([])).toBe(true)
    fc.assert(
      fc.property(tierArb, (tier) => {
        expect(areTiersAscending([tier])).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('is consistent: sorted unique thresholds always pass', () => {
    fc.assert(
      fc.property(tiersArb, (tiers) => {
        const unique = [...new Set(tiers.map((t) => t.threshold))].sort((a, b) => a - b)
        const sorted = unique.map((threshold) => ({ threshold }))
        if (sorted.length > 1) {
          expect(areTiersAscending(sorted)).toBe(true)
        }
      }),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 20: Loyalty points to next tier calculation               */
/* ------------------------------------------------------------------ */

describe('Property 20: Loyalty points to next tier calculation', () => {
  it('returns correct gap to next tier for ascending tiers', () => {
    fc.assert(
      fc.property(ascendingTiersArb, fc.nat({ max: 200_000 }), (tiers, currentPoints) => {
        const result = calculatePointsToNextTier(currentPoints, tiers)
        const sorted = [...tiers].sort((a, b) => a.threshold - b.threshold)
        const nextTier = sorted.find((t) => t.threshold > currentPoints)

        if (nextTier) {
          expect(result).toBe(nextTier.threshold - currentPoints)
        } else {
          // Already at or above highest tier
          expect(result).toBeNull()
        }
      }),
      { numRuns: 100 },
    )
  })

  it('returns null for empty tiers', () => {
    fc.assert(
      fc.property(fc.nat({ max: 100_000 }), (points) => {
        expect(calculatePointsToNextTier(points, [])).toBeNull()
      }),
      { numRuns: 100 },
    )
  })

  it('returns null when points >= highest tier threshold', () => {
    fc.assert(
      fc.property(ascendingTiersArb, (tiers) => {
        const maxThreshold = Math.max(...tiers.map((t) => t.threshold))
        expect(calculatePointsToNextTier(maxThreshold, tiers)).toBeNull()
        expect(calculatePointsToNextTier(maxThreshold + 1, tiers)).toBeNull()
      }),
      { numRuns: 100 },
    )
  })

  it('always returns a positive number when a next tier exists', () => {
    fc.assert(
      fc.property(ascendingTiersArb, fc.nat({ max: 200_000 }), (tiers, currentPoints) => {
        const result = calculatePointsToNextTier(currentPoints, tiers)
        if (result !== null) {
          expect(result).toBeGreaterThan(0)
        }
      }),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 21: Loyalty points adjustment requires reason             */
/* ------------------------------------------------------------------ */

describe('Property 21: Loyalty points adjustment requires reason', () => {
  it('accepts non-zero amount with non-empty reason', () => {
    fc.assert(
      fc.property(nonZeroAmountArb, validReasonArb, (amount, reason) => {
        const result = validatePointsAdjustment(amount, reason)
        expect(result.valid).toBe(true)
        expect(result.error).toBeUndefined()
      }),
      { numRuns: 100 },
    )
  })

  it('rejects empty or whitespace-only reason', () => {
    fc.assert(
      fc.property(nonZeroAmountArb, emptyReasonArb, (amount, reason) => {
        const result = validatePointsAdjustment(amount, reason)
        expect(result.valid).toBe(false)
        expect(result.error).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  it('rejects zero amount regardless of reason', () => {
    fc.assert(
      fc.property(validReasonArb, (reason) => {
        const result = validatePointsAdjustment(0, reason)
        expect(result.valid).toBe(false)
        expect(result.error).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  it('rejects zero amount with empty reason', () => {
    const result = validatePointsAdjustment(0, '')
    expect(result.valid).toBe(false)
    expect(result.error).toBeDefined()
  })
})
