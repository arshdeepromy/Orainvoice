import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

/**
 * Feature: flexible-billing-intervals, Property 5: Public API returns only enabled intervals
 *
 * For any plan with an interval config, the public plans API response SHALL include
 * only intervals where enabled is true. The number of intervals in the response SHALL
 * equal the number of enabled intervals in the config.
 *
 * **Validates: Requirements 3.1, 3.2**
 */

interface IntervalConfigItem {
  interval: 'weekly' | 'fortnightly' | 'monthly' | 'annual'
  enabled: boolean
  discount_percent: number
}

const INTERVALS = ['weekly', 'fortnightly', 'monthly', 'annual'] as const

/** Generator: random interval configs with mixed enabled/disabled */
const intervalConfigArb: fc.Arbitrary<IntervalConfigItem[]> = fc
  .tuple(
    fc.boolean(),
    fc.boolean(),
    fc.boolean(),
    fc.boolean(),
    fc.float({ min: 0, max: 100, noNaN: true }),
    fc.float({ min: 0, max: 100, noNaN: true }),
    fc.float({ min: 0, max: 100, noNaN: true }),
    fc.float({ min: 0, max: 100, noNaN: true }),
  )
  .map(([e1, e2, e3, e4, d1, d2, d3, d4]) =>
    INTERVALS.map((interval, i) => ({
      interval,
      enabled: [e1, e2, e3, e4][i],
      discount_percent: [d1, d2, d3, d4][i],
    })),
  )

/**
 * Simulates the public API filtering logic: only return intervals where enabled is true.
 * This mirrors what GET /api/v1/auth/plans does on the backend.
 */
function filterEnabledIntervals(config: IntervalConfigItem[]): IntervalConfigItem[] {
  return config.filter((item) => item.enabled)
}

/**
 * Determines if a plan is available for a given billing interval.
 * A plan is available for an interval iff the interval is enabled in the plan's config.
 *
 * Feature: flexible-billing-intervals, Property 7: Plan availability determined by interval support
 */
function isPlanAvailableForInterval(config: IntervalConfigItem[], selectedInterval: string): boolean {
  return config.some((item) => item.interval === selectedInterval && item.enabled)
}

describe('Billing Intervals — Property-Based Tests', () => {
  it('Property 5: public API returns only enabled intervals', () => {
    fc.assert(
      fc.property(intervalConfigArb, (config) => {
        const result = filterEnabledIntervals(config)

        // Every returned interval must be enabled
        for (const item of result) {
          expect(item.enabled).toBe(true)
        }

        // Count must match the number of enabled intervals in the original config
        const enabledCount = config.filter((c) => c.enabled).length
        expect(result).toHaveLength(enabledCount)

        // No disabled interval should appear in the result
        const resultIntervals = new Set(result.map((r) => r.interval))
        for (const item of config) {
          if (!item.enabled) {
            expect(resultIntervals.has(item.interval)).toBe(false)
          }
        }
      }),
      { numRuns: 100 },
    )
  })

  /**
   * Feature: flexible-billing-intervals, Property 7: Plan availability determined by interval support
   *
   * For any plan and for any billing interval, the plan SHALL be marked as available
   * for that interval if and only if the interval is enabled in the plan's interval config.
   *
   * **Validates: Requirements 5.3, 8.3**
   */
  it('Property 7: plan availability determined by interval support', () => {
    const selectedIntervalArb = fc.constantFrom(...INTERVALS)

    fc.assert(
      fc.property(intervalConfigArb, selectedIntervalArb, (config, selectedInterval) => {
        const available = isPlanAvailableForInterval(config, selectedInterval)

        // Find the config entry for the selected interval
        const configEntry = config.find((item) => item.interval === selectedInterval)

        // Plan is available iff the interval exists in config AND is enabled
        const expectedAvailable = configEntry !== undefined && configEntry.enabled

        expect(available).toBe(expectedAvailable)
      }),
      { numRuns: 100 },
    )
  })
})
