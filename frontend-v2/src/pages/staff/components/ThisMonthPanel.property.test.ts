import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import { formatHours, formatCount, formatPercent } from './ThisMonthPanel'
import type { StaffMetric } from '@/api/staff'

/**
 * Feature: staff-redesign, Property 9
 * Property 9: Metric rendering honours has_data and formatting rules.
 * **Validates: Requirements 8.3, 8.4, 8.5, 12.5**
 *
 * For any `StaffMetric`, each metric cell renders "—" when `has_data` is
 * false (R8.3). Otherwise:
 *   - Hours_Logged → `value.toFixed(1) + 'h'` (one decimal, R8.4)
 *   - Billable_Ratio / On_Time_Rate → `Math.round(value) + '%'` (whole
 *     percent, R8.5)
 *   - Jobs_Completed → integer count `String(Math.round(value))`.
 *
 * The references below mirror the EXACT operations the implementation uses
 * (`.toFixed(1)`, `Math.round`, and the `value ?? 0` guard) so the property
 * stays aligned with the formatters rather than asserting an independent
 * (and possibly divergent) notion of rounding/formatting (R12.5).
 */

// Arbitrary finite metric values: cover negatives, zero, decimals, and large
// values within a sensible range. noNaN/noDefaultInfinity keep them finite.
const metricValue = fc.double({
  min: -1000,
  max: 100000,
  noNaN: true,
  noDefaultInfinity: true,
})

describe('Feature: staff-redesign, Property 9 — metric rendering', () => {
  it('renders "—" when has_data is false (R8.3)', () => {
    fc.assert(
      fc.property(metricValue, (value) => {
        const metric: StaffMetric = { value, has_data: false }
        expect(formatHours(metric)).toBe('—')
        expect(formatCount(metric)).toBe('—')
        expect(formatPercent(metric)).toBe('—')
      }),
      { numRuns: 100 },
    )
  })

  it('formats values per the design rules when has_data is true (R8.4, R8.5, R12.5)', () => {
    fc.assert(
      fc.property(metricValue, (value) => {
        const metric: StaffMetric = { value, has_data: true }
        // Hours: one decimal place suffixed with "h".
        expect(formatHours(metric)).toBe(`${value.toFixed(1)}h`)
        // Jobs: integer count.
        expect(formatCount(metric)).toBe(String(Math.round(value)))
        // Percentages: whole number with "%".
        expect(formatPercent(metric)).toBe(`${Math.round(value)}%`)
      }),
      { numRuns: 100 },
    )
  })

  it('renders "—" for undefined / missing metrics (R8.3)', () => {
    expect(formatHours(undefined)).toBe('—')
    expect(formatCount(undefined)).toBe('—')
    expect(formatPercent(undefined)).toBe('—')
  })
})
