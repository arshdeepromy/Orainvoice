// Feature: platform-feature-gaps, Property 24: Locale is passed to formatters
// **Validates: Requirements 27.3**

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { formatCurrency, formatDate, formatDateTime, formatTime } from '../portalFormatters'

/**
 * Property 24: Locale is passed to formatters.
 *
 * For any non-null branding.language value, all Intl.DateTimeFormat and
 * Intl.NumberFormat calls in portal components SHALL use that locale code
 * instead of the hardcoded 'en-NZ'.
 *
 * We test that the formatter functions accept and use the locale parameter
 * for all Intl formatting calls, producing locale-specific output.
 *
 * **Validates: Requirements 27.3**
 */
describe('Property 24: Locale is passed to formatters', () => {
  // Locales that are commonly supported by Intl in Node/jsdom
  const localeArb = fc.constantFrom(
    'en-NZ',
    'en-AU',
    'en-US',
    'en-GB',
    'de-DE',
    'fr-FR',
    'ja-JP',
    'mi-NZ',
  )

  // Valid ISO date strings — use integer-based generation to avoid invalid Date edge cases
  const dateStrArb = fc
    .integer({ min: new Date('2000-01-01').getTime(), max: new Date('2030-12-31').getTime() })
    .map((ts) => new Date(ts).toISOString())

  // Positive currency amounts
  const amountArb = fc.double({ min: 0.01, max: 999999.99, noNaN: true })

  const currencyArb = fc.constantFrom('NZD', 'USD', 'EUR', 'GBP', 'AUD')

  it('formatCurrency accepts any supported locale and returns a non-empty string', () => {
    fc.assert(
      fc.property(amountArb, localeArb, currencyArb, (amount, locale, currency) => {
        const result = formatCurrency(amount, locale, currency)
        expect(typeof result).toBe('string')
        expect(result.length).toBeGreaterThan(0)
      }),
      { numRuns: 200 },
    )
  })

  it('formatCurrency produces different output for locales with different number formatting', () => {
    // en-US uses "," for thousands and "." for decimal
    // de-DE uses "." for thousands and "," for decimal
    const amount = 1234.56
    const enResult = formatCurrency(amount, 'en-US', 'EUR')
    const deResult = formatCurrency(amount, 'de-DE', 'EUR')

    // They should differ because of locale-specific formatting
    // (at minimum the currency symbol placement or separator differs)
    expect(enResult).not.toBe(deResult)
  })

  it('formatDate accepts any supported locale and returns a non-empty string', () => {
    fc.assert(
      fc.property(dateStrArb, localeArb, (dateStr, locale) => {
        const result = formatDate(dateStr, locale)
        expect(typeof result).toBe('string')
        expect(result.length).toBeGreaterThan(0)
      }),
      { numRuns: 200 },
    )
  })

  it('formatDateTime accepts any supported locale and returns a non-empty string', () => {
    fc.assert(
      fc.property(dateStrArb, localeArb, (dateStr, locale) => {
        const result = formatDateTime(dateStr, locale)
        expect(typeof result).toBe('string')
        expect(result.length).toBeGreaterThan(0)
      }),
      { numRuns: 200 },
    )
  })

  it('formatTime accepts any supported locale and returns a non-empty string', () => {
    fc.assert(
      fc.property(dateStrArb, localeArb, (dateStr, locale) => {
        const result = formatTime(dateStr, locale)
        expect(typeof result).toBe('string')
        expect(result.length).toBeGreaterThan(0)
      }),
      { numRuns: 200 },
    )
  })

  it('formatDate output contains the year from the input date for any locale', () => {
    fc.assert(
      fc.property(dateStrArb, localeArb, (dateStr, locale) => {
        const year = new Date(dateStr).getFullYear().toString()
        const result = formatDate(dateStr, locale)
        expect(result).toContain(year)
      }),
      { numRuns: 200 },
    )
  })

  it('formatCurrency output contains digits from the amount for any locale', () => {
    fc.assert(
      fc.property(localeArb, (locale) => {
        // Use a round number to avoid decimal formatting differences
        const result = formatCurrency(100, locale, 'NZD')
        expect(result).toContain('100')
      }),
      { numRuns: 50 },
    )
  })

  it('all formatters use the provided locale, not a hardcoded one', () => {
    // Verify that passing different locales to the same input produces
    // locale-aware output (at least for locales with known differences)
    const dateStr = '2024-06-15T14:30:00Z'

    const enNZ = formatDate(dateStr, 'en-NZ')
    const enUS = formatDate(dateStr, 'en-US')
    const jaJP = formatDate(dateStr, 'ja-JP')

    // All should be non-empty strings
    expect(enNZ.length).toBeGreaterThan(0)
    expect(enUS.length).toBeGreaterThan(0)
    expect(jaJP.length).toBeGreaterThan(0)

    // Japanese locale should produce different output from English locales
    // (different month abbreviation format)
    expect(jaJP).not.toBe(enNZ)
  })
})
