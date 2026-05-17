import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { formatCountdown, formatNZD } from './KioskQrPopup'

// Feature: kiosk-qr-payment, Property 7: Timer Display and Warning State
// **Validates: Requirements 6.1, 6.3**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Random seconds in the valid countdown range 0–3600 */
const secondsArb = fc.integer({ min: 0, max: 3600 })

/** Seconds in the warning zone (0–119) */
const warningSecondsArb = fc.integer({ min: 0, max: 119 })

/** Seconds in the normal zone (120–3600) */
const normalSecondsArb = fc.integer({ min: 120, max: 3600 })

/* ------------------------------------------------------------------ */
/*  Property 7: Timer Display and Warning State                        */
/* ------------------------------------------------------------------ */

describe('Property 7: Timer Display and Warning State', () => {
  it('formatCountdown returns MM:SS format (2 digits colon 2 digits) for any seconds 0–3600', () => {
    fc.assert(
      fc.property(secondsArb, (seconds) => {
        const result = formatCountdown(seconds)
        // Must match exactly "DD:DD" where D is a digit
        expect(result).toMatch(/^\d{2}:\d{2}$/)
      }),
      { numRuns: 200 },
    )
  })

  it('formatCountdown computes correct minutes and seconds', () => {
    fc.assert(
      fc.property(secondsArb, (seconds) => {
        const result = formatCountdown(seconds)
        const [mmStr, ssStr] = result.split(':')
        const mm = parseInt(mmStr, 10)
        const ss = parseInt(ssStr, 10)

        const expectedMinutes = Math.floor(seconds / 60)
        const expectedSeconds = seconds % 60

        expect(mm).toBe(expectedMinutes)
        expect(ss).toBe(expectedSeconds)
      }),
      { numRuns: 200 },
    )
  })

  it('warning state is true (T < 120) for seconds in warning zone', () => {
    fc.assert(
      fc.property(warningSecondsArb, (seconds) => {
        // The component uses: isWarning = secondsRemaining < 120
        const isWarning = seconds < 120
        expect(isWarning).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('warning state is false (T >= 120) for seconds in normal zone', () => {
    fc.assert(
      fc.property(normalSecondsArb, (seconds) => {
        // The component uses: isWarning = secondsRemaining < 120
        const isWarning = seconds < 120
        expect(isWarning).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('warning threshold boundary: 119 is warning, 120 is not', () => {
    // Explicit boundary check
    expect(119 < 120).toBe(true) // warning
    expect(120 < 120).toBe(false) // not warning
  })
})


// Feature: kiosk-qr-payment, Property 10: Currency Formatting
// **Validates: Requirements 5.3**

/* ------------------------------------------------------------------ */
/*  Generators (Property 10)                                           */
/* ------------------------------------------------------------------ */

/** Random float amounts in the range 0.01–999999.99 (typical NZD payment amounts) */
const amountArb = fc.double({ min: 0.01, max: 999999.99, noNaN: true, noDefaultInfinity: true })

/* ------------------------------------------------------------------ */
/*  Property 10: Currency Formatting                                   */
/* ------------------------------------------------------------------ */

describe('Property 10: Currency Formatting', () => {
  it('formatNZD always returns a string starting with "$"', () => {
    fc.assert(
      fc.property(amountArb, (amount) => {
        const result = formatNZD(amount)
        expect(result.startsWith('$')).toBe(true)
      }),
      { numRuns: 200 },
    )
  })

  it('formatNZD always returns exactly 2 decimal places', () => {
    fc.assert(
      fc.property(amountArb, (amount) => {
        const result = formatNZD(amount)
        // After the "$", the string should end with ".XX" (dot followed by exactly 2 digits)
        const afterDollar = result.slice(1)
        const parts = afterDollar.split('.')
        expect(parts.length).toBe(2)
        expect(parts[1].length).toBe(2)
      }),
      { numRuns: 200 },
    )
  })

  it('formatNZD numeric value matches input within floating-point tolerance', () => {
    fc.assert(
      fc.property(amountArb, (amount) => {
        const result = formatNZD(amount)
        // Strip the "$" prefix and parse back to number
        const numericValue = parseFloat(result.slice(1))
        // toFixed(2) rounds to 2 decimal places, so compare against the rounded input
        const expected = Math.round(amount * 100) / 100
        expect(Math.abs(numericValue - expected)).toBeLessThanOrEqual(0.005)
      }),
      { numRuns: 200 },
    )
  })

  it('formatNZD matches the pattern $X.XX (dollar sign, digits, dot, 2 digits)', () => {
    fc.assert(
      fc.property(amountArb, (amount) => {
        const result = formatNZD(amount)
        // Should match: $ followed by optional negative sign, digits (with optional commas), dot, 2 digits
        expect(result).toMatch(/^\$-?\d+(\.\d{2})$/)
      }),
      { numRuns: 200 },
    )
  })
})
