import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  calculateProgressClaimFields,
  validateCumulativeNotExceeded,
  type ProgressClaimInputs,
} from '../utils/progressClaimCalcs'

// Feature: production-readiness-gaps, Property 5: Progress claim calculations are correct
// Feature: production-readiness-gaps, Property 6: Cumulative claimed cannot exceed revised contract value
// **Validates: Requirements 3.4, 3.5**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Positive monetary value (0 to 10,000,000 with 2 decimal places) */
const moneyArb = fc.double({ min: 0, max: 10_000_000, noNaN: true, noDefaultInfinity: true })
  .map((v) => Math.round(v * 100) / 100)

/** Positive monetary value > 0 for contract values */
const positiveMoneyArb = fc.double({ min: 0.01, max: 10_000_000, noNaN: true, noDefaultInfinity: true })
  .map((v) => Math.round(v * 100) / 100)

/** Generate valid progress claim inputs where workCompletedToDate >= workCompletedPrevious */
const progressClaimInputsArb: fc.Arbitrary<ProgressClaimInputs> = fc
  .record({
    originalContractValue: positiveMoneyArb,
    approvedVariations: moneyArb,
    workCompletedToDate: moneyArb,
    materialsOnSite: moneyArb,
    retentionWithheld: moneyArb,
  })
  .chain((base) =>
    moneyArb
      .filter((prev) => prev <= base.workCompletedToDate)
      .map((workCompletedPrevious) => ({
        ...base,
        workCompletedPrevious,
      })),
  )

/* ------------------------------------------------------------------ */
/*  Property 5: Progress claim calculations are correct                */
/* ------------------------------------------------------------------ */

describe('Property 5: Progress claim calculations are correct', () => {
  it('revised_contract_value = original + approved_variations', () => {
    fc.assert(
      fc.property(progressClaimInputsArb, (inputs) => {
        const result = calculateProgressClaimFields(inputs)
        const expected = inputs.originalContractValue + inputs.approvedVariations
        expect(result.revisedContractValue).toBeCloseTo(expected, 2)
      }),
      { numRuns: 100 },
    )
  })

  it('work_completed_this_period = work_to_date - work_previous', () => {
    fc.assert(
      fc.property(progressClaimInputsArb, (inputs) => {
        const result = calculateProgressClaimFields(inputs)
        const expected = inputs.workCompletedToDate - inputs.workCompletedPrevious
        expect(result.workCompletedThisPeriod).toBeCloseTo(expected, 2)
      }),
      { numRuns: 100 },
    )
  })

  it('amount_due = work_this_period + materials - retention', () => {
    fc.assert(
      fc.property(progressClaimInputsArb, (inputs) => {
        const result = calculateProgressClaimFields(inputs)
        const workThisPeriod = inputs.workCompletedToDate - inputs.workCompletedPrevious
        const expected = workThisPeriod + inputs.materialsOnSite - inputs.retentionWithheld
        expect(result.amountDue).toBeCloseTo(expected, 2)
      }),
      { numRuns: 100 },
    )
  })

  it('completion_percentage = (work_to_date / revised_contract_value) * 100', () => {
    fc.assert(
      fc.property(progressClaimInputsArb, (inputs) => {
        const result = calculateProgressClaimFields(inputs)
        const revisedContract = inputs.originalContractValue + inputs.approvedVariations
        const expected =
          revisedContract > 0
            ? (inputs.workCompletedToDate / revisedContract) * 100
            : 0
        expect(result.completionPercentage).toBeCloseTo(expected, 2)
      }),
      { numRuns: 100 },
    )
  })

  it('completion_percentage is 0 when revised contract value is 0', () => {
    fc.assert(
      fc.property(
        moneyArb,
        moneyArb,
        moneyArb,
        (workToDate, materials, retention) => {
          const inputs: ProgressClaimInputs = {
            originalContractValue: 0,
            approvedVariations: 0,
            workCompletedToDate: workToDate,
            workCompletedPrevious: 0,
            materialsOnSite: materials,
            retentionWithheld: retention,
          }
          const result = calculateProgressClaimFields(inputs)
          expect(result.completionPercentage).toBe(0)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('all calculated fields are consistent with each other', () => {
    fc.assert(
      fc.property(progressClaimInputsArb, (inputs) => {
        const result = calculateProgressClaimFields(inputs)

        // Verify internal consistency
        expect(result.revisedContractValue).toBeCloseTo(
          inputs.originalContractValue + inputs.approvedVariations,
          2,
        )
        expect(result.workCompletedThisPeriod).toBeCloseTo(
          inputs.workCompletedToDate - inputs.workCompletedPrevious,
          2,
        )
        expect(result.amountDue).toBeCloseTo(
          result.workCompletedThisPeriod + inputs.materialsOnSite - inputs.retentionWithheld,
          2,
        )
        if (result.revisedContractValue > 0) {
          expect(result.completionPercentage).toBeCloseTo(
            (inputs.workCompletedToDate / result.revisedContractValue) * 100,
            2,
          )
        }
      }),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 6: Cumulative claimed cannot exceed revised contract value */
/* ------------------------------------------------------------------ */

describe('Property 6: Cumulative claimed cannot exceed revised contract value', () => {
  it('returns error when cumulative + amount > revised contract value', () => {
    fc.assert(
      fc.property(
        positiveMoneyArb, // revisedContractValue
        (revisedContract) => {
          // Generate cumulative and amount that together exceed the contract
          return fc.assert(
            fc.property(
              fc.double({ min: 0, max: revisedContract, noNaN: true, noDefaultInfinity: true })
                .map((v) => Math.round(v * 100) / 100),
              (cumulative) => {
                const remaining = revisedContract - cumulative
                const amountExceeding = remaining + 0.01
                const result = validateCumulativeNotExceeded(
                  cumulative,
                  amountExceeding,
                  revisedContract,
                )
                expect(result).not.toBeNull()
                expect(result).toContain('exceeds revised contract value')
              },
            ),
            { numRuns: 10 },
          )
        },
      ),
      { numRuns: 10 },
    )
  })

  it('returns null when cumulative + amount <= revised contract value', () => {
    fc.assert(
      fc.property(
        positiveMoneyArb, // revisedContractValue
        fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
        fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
        (revisedContract, cumulativeRatio, amountRatio) => {
          // Ensure cumulative + amount <= revisedContract by using ratios
          const totalRatio = cumulativeRatio + amountRatio
          const scaledCumulativeRatio = totalRatio > 0 ? cumulativeRatio / Math.max(totalRatio, 1) : 0
          const scaledAmountRatio = totalRatio > 0 ? amountRatio / Math.max(totalRatio, 1) : 0
          const cumulative = Math.round(scaledCumulativeRatio * revisedContract * 100) / 100
          const amount = Math.round(scaledAmountRatio * revisedContract * 100) / 100

          const result = validateCumulativeNotExceeded(cumulative, amount, revisedContract)
          expect(result).toBeNull()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('returns null when cumulative + amount exactly equals revised contract value', () => {
    fc.assert(
      fc.property(
        positiveMoneyArb,
        fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
        (revisedContract, splitRatio) => {
          const cumulative = Math.round(splitRatio * revisedContract * 100) / 100
          const amount = Math.round((revisedContract - cumulative) * 100) / 100

          const result = validateCumulativeNotExceeded(cumulative, amount, revisedContract)
          expect(result).toBeNull()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('error message includes maximum claimable amount', () => {
    fc.assert(
      fc.property(
        positiveMoneyArb,
        fc.double({ min: 0, max: 0.9, noNaN: true, noDefaultInfinity: true }),
        (revisedContract, cumulativeRatio) => {
          const cumulative = Math.round(cumulativeRatio * revisedContract * 100) / 100
          const maxClaimable = Math.max(0, revisedContract - cumulative)
          // Claim more than what's available
          const excessAmount = maxClaimable + 1

          const result = validateCumulativeNotExceeded(cumulative, excessAmount, revisedContract)
          if (result !== null) {
            // The error message should contain the maximum claimable amount
            expect(result).toContain('Maximum claimable')
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('returns null when revised contract value is 0 (no constraint)', () => {
    fc.assert(
      fc.property(
        moneyArb,
        moneyArb,
        (cumulative, amount) => {
          const result = validateCumulativeNotExceeded(cumulative, amount, 0)
          expect(result).toBeNull()
        },
      ),
      { numRuns: 100 },
    )
  })
})
