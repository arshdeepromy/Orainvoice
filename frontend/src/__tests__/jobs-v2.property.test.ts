import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  isValidStatusTransition,
  calculateJobProfitability,
} from '../utils/jobCalcs'

// Feature: production-readiness-gaps, Property 15: Job status transitions are validated
// Feature: production-readiness-gaps, Property 16: Job profitability calculation is correct
// **Validates: Requirements 8.3, 8.5**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** All valid job statuses */
const ALL_STATUSES = [
  'draft',
  'quoted',
  'accepted',
  'in_progress',
  'completed',
  'invoiced',
  'cancelled',
] as const

/** Valid transitions map matching the implementation */
const VALID_TRANSITIONS: Record<string, string[]> = {
  draft: ['quoted', 'cancelled'],
  quoted: ['accepted', 'cancelled'],
  accepted: ['in_progress', 'cancelled'],
  in_progress: ['completed'],
  completed: ['invoiced'],
  invoiced: [],
  cancelled: [],
}

const statusArb = fc.constantFrom(...ALL_STATUSES)

/** Arbitrary non-negative revenue */
const revenueArb = fc.float({ min: 0, max: 1_000_000, noNaN: true, noDefaultInfinity: true })

/** Arbitrary non-negative costs */
const costsArb = fc.float({ min: 0, max: 1_000_000, noNaN: true, noDefaultInfinity: true })

/* ------------------------------------------------------------------ */
/*  Property 15: Job status transitions are validated                  */
/* ------------------------------------------------------------------ */

describe('Property 15: Job status transitions are validated', () => {
  it('returns true only for allowed transitions', () => {
    fc.assert(
      fc.property(statusArb, statusArb, (from, to) => {
        const expected = (VALID_TRANSITIONS[from] ?? []).includes(to)
        expect(isValidStatusTransition(from, to)).toBe(expected)
      }),
      { numRuns: 100 },
    )
  })

  it('returns false for unknown source statuses', () => {
    const invalidStatuses = ['unknown', 'pending', 'active', 'closed', 'archived', 'deleted', 'paused', 'expired', 'new', 'open']
    fc.assert(
      fc.property(
        fc.constantFrom(...invalidStatuses),
        statusArb,
        (from, to) => {
          expect(isValidStatusTransition(from, to)).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('terminal statuses have no valid outgoing transitions', () => {
    const terminalStatuses = ['invoiced', 'cancelled']
    fc.assert(
      fc.property(
        fc.constantFrom(...terminalStatuses),
        statusArb,
        (from, to) => {
          expect(isValidStatusTransition(from, to)).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('every allowed transition pair returns true', () => {
    for (const [from, targets] of Object.entries(VALID_TRANSITIONS)) {
      for (const to of targets) {
        expect(isValidStatusTransition(from, to)).toBe(true)
      }
    }
  })
})

/* ------------------------------------------------------------------ */
/*  Property 16: Job profitability calculation is correct              */
/* ------------------------------------------------------------------ */

describe('Property 16: Job profitability calculation is correct', () => {
  it('margin equals revenue minus costs', () => {
    fc.assert(
      fc.property(revenueArb, costsArb, (revenue, costs) => {
        const result = calculateJobProfitability(revenue, costs)
        expect(result.margin).toBeCloseTo(revenue - costs, 5)
      }),
      { numRuns: 100 },
    )
  })

  it('marginPercentage = (margin / revenue) * 100 when revenue > 0', () => {
    fc.assert(
      fc.property(
        fc.float({ min: Math.fround(0.01), max: 1_000_000, noNaN: true, noDefaultInfinity: true }),
        costsArb,
        (revenue, costs) => {
          const result = calculateJobProfitability(revenue, costs)
          const expectedPct = ((revenue - costs) / revenue) * 100
          expect(result.marginPercentage).toBeCloseTo(expectedPct, 5)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('marginPercentage is 0 when revenue is 0', () => {
    fc.assert(
      fc.property(costsArb, (costs) => {
        const result = calculateJobProfitability(0, costs)
        expect(result.marginPercentage).toBe(0)
      }),
      { numRuns: 100 },
    )
  })

  it('result always contains margin and marginPercentage', () => {
    fc.assert(
      fc.property(revenueArb, costsArb, (revenue, costs) => {
        const result = calculateJobProfitability(revenue, costs)
        expect(result).toHaveProperty('margin')
        expect(result).toHaveProperty('marginPercentage')
        expect(typeof result.margin).toBe('number')
        expect(typeof result.marginPercentage).toBe('number')
      }),
      { numRuns: 100 },
    )
  })
})
