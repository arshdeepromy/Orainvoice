import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  computeSmsOverage,
  getEffectiveSmsQuota,
  computeOverageCharge,
} from '../utils/smsCalcs'

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Non-negative integer for SMS counts and quotas */
const nonNegIntArb = fc.integer({ min: 0, max: 100_000 })

/** Positive per-SMS cost in NZD (0.0001 – 1.00) */
const perSmsCostArb = fc
  .integer({ min: 0, max: 10_000 })
  .map((v) => v / 10_000)

/** Non-negative package credits remaining */
const packageCreditsArb = fc.integer({ min: 0, max: 50_000 })

/* ------------------------------------------------------------------ */
/*  Feature: sms-pricing-packages, Property 1:                         */
/*  SMS overage computation is max(0, total_sent - included_quota)     */
/* ------------------------------------------------------------------ */

// **Validates: Requirements 3.1, 3.5, 3.6**

describe('Property 1: SMS overage computation is max(0, total_sent - included_quota)', () => {
  it('returns max(0, total_sent - included_quota) for any non-negative inputs', () => {
    fc.assert(
      fc.property(nonNegIntArb, nonNegIntArb, (totalSent, includedQuota) => {
        const result = computeSmsOverage(totalSent, includedQuota)
        expect(result).toBe(Math.max(0, totalSent - includedQuota))
      }),
      { numRuns: 100 },
    )
  })

  it('result is always non-negative', () => {
    fc.assert(
      fc.property(nonNegIntArb, nonNegIntArb, (totalSent, includedQuota) => {
        expect(computeSmsOverage(totalSent, includedQuota)).toBeGreaterThanOrEqual(0)
      }),
      { numRuns: 100 },
    )
  })

  it('returns 0 when total_sent <= included_quota', () => {
    fc.assert(
      fc.property(nonNegIntArb, (includedQuota) => {
        const totalSent = fc.sample(fc.integer({ min: 0, max: includedQuota }), 1)[0]
        expect(computeSmsOverage(totalSent, includedQuota)).toBe(0)
      }),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Feature: sms-pricing-packages, Property 4:                         */
/*  When sms_included is false, effective quota is 0                   */
/* ------------------------------------------------------------------ */

// **Validates: Requirements 1.7, 3.4**

describe('Property 4: When sms_included is false, effective quota is 0', () => {
  it('effective quota is 0 regardless of plan quota and package credits', () => {
    fc.assert(
      fc.property(nonNegIntArb, packageCreditsArb, (planQuota, packageCredits) => {
        const result = getEffectiveSmsQuota(false, planQuota, packageCredits)
        expect(result).toBe(0)
      }),
      { numRuns: 100 },
    )
  })

  it('effective quota includes plan quota + package credits when sms_included is true', () => {
    fc.assert(
      fc.property(nonNegIntArb, packageCreditsArb, (planQuota, packageCredits) => {
        const result = getEffectiveSmsQuota(true, planQuota, packageCredits)
        expect(result).toBe(planQuota + packageCredits)
      }),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Feature: sms-pricing-packages, Property 8:                         */
/*  Overage charge equals overage count times per-SMS cost             */
/* ------------------------------------------------------------------ */

// **Validates: Requirements 3.2**

describe('Property 8: Overage charge equals overage count times per-SMS cost', () => {
  it('charge equals overageCount × perSmsCost', () => {
    fc.assert(
      fc.property(nonNegIntArb, perSmsCostArb, (overageCount, perSmsCost) => {
        const result = computeOverageCharge(overageCount, perSmsCost)
        expect(result).toBeCloseTo(overageCount * perSmsCost, 8)
      }),
      { numRuns: 100 },
    )
  })

  it('charge is 0 when overage count is 0', () => {
    fc.assert(
      fc.property(perSmsCostArb, (perSmsCost) => {
        expect(computeOverageCharge(0, perSmsCost)).toBe(0)
      }),
      { numRuns: 100 },
    )
  })

  it('charge is 0 when per-SMS cost is 0', () => {
    fc.assert(
      fc.property(nonNegIntArb, (overageCount) => {
        expect(computeOverageCharge(overageCount, 0)).toBe(0)
      }),
      { numRuns: 100 },
    )
  })
})
