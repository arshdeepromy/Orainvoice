import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  calculateRevisedContractValue,
  isVariationImmutable,
} from '../utils/variationCalcs'

// Feature: production-readiness-gaps, Property 7: Approved variation updates revised contract value
// Feature: production-readiness-gaps, Property 8: Approved variations are immutable
// **Validates: Requirements 4.4, 4.6**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Positive contract value */
const positiveContractArb = fc
  .float({ min: 0, max: 1e9, noNaN: true, noDefaultInfinity: true })
  .map((v) => Math.round(v * 100) / 100)

/** Cost impact for a single variation (positive addition or negative deduction) */
const costImpactArb = fc
  .float({ min: -1e6, max: 1e6, noNaN: true, noDefaultInfinity: true })
  .map((v) => Math.round(v * 100) / 100)

/** A list of approved variations with cost impacts */
const approvedVariationsArb = fc.array(
  fc.record({ cost_impact: costImpactArb }),
  { minLength: 0, maxLength: 20 },
)

/** Valid variation statuses */
const variationStatusArb = fc.constantFrom('draft', 'submitted', 'approved', 'rejected')

/* ------------------------------------------------------------------ */
/*  Property 7: Approved variation updates revised contract value      */
/* ------------------------------------------------------------------ */

describe('Property 7: Approved variation updates revised contract value', () => {
  it('revised_contract = original + sum of approved cost impacts', () => {
    fc.assert(
      fc.property(
        positiveContractArb,
        approvedVariationsArb,
        (original, variations) => {
          const result = calculateRevisedContractValue(original, variations)
          const expectedSum = variations.reduce((sum, v) => sum + v.cost_impact, 0)
          expect(result).toBeCloseTo(original + expectedSum, 2)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('returns original value when no variations exist', () => {
    fc.assert(
      fc.property(positiveContractArb, (original) => {
        const result = calculateRevisedContractValue(original, [])
        expect(result).toBeCloseTo(original, 2)
      }),
      { numRuns: 100 },
    )
  })

  it('handles a single variation correctly', () => {
    fc.assert(
      fc.property(
        positiveContractArb,
        costImpactArb,
        (original, impact) => {
          const result = calculateRevisedContractValue(original, [{ cost_impact: impact }])
          expect(result).toBeCloseTo(original + impact, 2)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('supports negative cost impacts (deductions)', () => {
    fc.assert(
      fc.property(
        positiveContractArb,
        fc.array(
          fc.float({ min: -1e6, max: Math.fround(-0.01), noNaN: true, noDefaultInfinity: true })
            .map((v) => ({ cost_impact: Math.round(v * 100) / 100 })),
          { minLength: 1, maxLength: 10 },
        ),
        (original, negativeVariations) => {
          const result = calculateRevisedContractValue(original, negativeVariations)
          const totalImpact = negativeVariations.reduce((s, v) => s + v.cost_impact, 0)
          expect(result).toBeCloseTo(original + totalImpact, 2)
          expect(result).toBeLessThan(original)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('order of variations does not affect result', () => {
    fc.assert(
      fc.property(
        positiveContractArb,
        approvedVariationsArb.filter((v) => v.length >= 2),
        (original, variations) => {
          const reversed = [...variations].reverse()
          const result1 = calculateRevisedContractValue(original, variations)
          const result2 = calculateRevisedContractValue(original, reversed)
          expect(result1).toBeCloseTo(result2, 2)
        },
      ),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 8: Approved variations are immutable                      */
/* ------------------------------------------------------------------ */

describe('Property 8: Approved variations are immutable', () => {
  it('approved and rejected variations are immutable', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('approved', 'rejected'),
        (status) => {
          expect(isVariationImmutable(status)).toBe(true)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('draft and submitted variations are mutable', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('draft', 'submitted'),
        (status) => {
          expect(isVariationImmutable(status)).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('immutability is deterministic for any valid status', () => {
    fc.assert(
      fc.property(variationStatusArb, (status) => {
        const result1 = isVariationImmutable(status)
        const result2 = isVariationImmutable(status)
        expect(result1).toBe(result2)
      }),
      { numRuns: 100 },
    )
  })

  it('unknown statuses are treated as mutable', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 20 }).filter(
          (s) => !['approved', 'rejected', 'draft', 'submitted'].includes(s),
        ),
        (unknownStatus) => {
          expect(isVariationImmutable(unknownStatus)).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })
})
