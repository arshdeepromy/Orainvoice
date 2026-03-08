import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  formatCurrencyAmount,
  isMissingExchangeRate,
  getCurrencyFormat,
  CURRENCY_REGISTRY,
} from '../utils/currencyCalcs'

// Feature: production-readiness-gaps, Property 27: Currency amount formatting follows ISO standard
// Feature: production-readiness-gaps, Property 28: Missing exchange rate blocks invoice creation
// **Validates: Requirements 13.6, 13.7**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** All known currency codes from the registry */
const knownCurrencyCodes = Object.keys(CURRENCY_REGISTRY)

/** Arbitrary known currency code */
const knownCurrencyArb = fc.constantFrom(...knownCurrencyCodes)

/** Arbitrary positive amount (reasonable invoice range) */
const amountArb = fc.double({ min: 0, max: 10_000_000, noNaN: true, noDefaultInfinity: true })

/** Arbitrary amount including negatives */
const signedAmountArb = fc.double({ min: -10_000_000, max: 10_000_000, noNaN: true, noDefaultInfinity: true })

/** Arbitrary 3-letter uppercase string for unknown currency codes */
const unknownCurrencyArb = fc
  .tuple(
    fc.constantFrom(...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')),
    fc.constantFrom(...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')),
    fc.constantFrom(...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')),
  )
  .map(([a, b, c]) => `${a}${b}${c}`)
  .filter((code) => !(code in CURRENCY_REGISTRY))

/** Arbitrary exchange rates map with positive rates */
const ratesArb = fc.dictionary(
  fc.constantFrom(...knownCurrencyCodes),
  fc.double({ min: 0.0001, max: 10_000, noNaN: true, noDefaultInfinity: true }),
)

/* ------------------------------------------------------------------ */
/*  Property 27: Currency amount formatting follows ISO standard       */
/* ------------------------------------------------------------------ */

describe('Property 27: Currency amount formatting follows ISO standard', () => {
  it('formatted string contains the currency symbol', () => {
    fc.assert(
      fc.property(amountArb, knownCurrencyArb, (amount, code) => {
        const result = formatCurrencyAmount(amount, code)
        const fmt = getCurrencyFormat(code)
        expect(result).toContain(fmt.symbol)
      }),
      { numRuns: 100 },
    )
  })

  it('uses correct number of decimal places', () => {
    fc.assert(
      fc.property(amountArb, knownCurrencyArb, (amount, code) => {
        const result = formatCurrencyAmount(amount, code)
        const fmt = getCurrencyFormat(code)

        if (fmt.decimalPlaces === 0) {
          // Should not contain a decimal separator in the numeric part
          // Strip the symbol to inspect the number portion
          const numericPart = fmt.symbolPosition === 'after'
            ? result.replace(` ${fmt.symbol}`, '')
            : result.replace(fmt.symbol, '')
          expect(numericPart).not.toContain(fmt.decimalSeparator)
        } else {
          // Should contain exactly decimalPlaces digits after the decimal separator
          const parts = result.split(fmt.decimalSeparator)
          // The last part (after decimal separator) should have the right length
          const decimalPart = parts[parts.length - 1].replace(/[^0-9]/g, '')
          expect(decimalPart.length).toBe(fmt.decimalPlaces)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('is deterministic — same input always produces same output', () => {
    fc.assert(
      fc.property(signedAmountArb, knownCurrencyArb, (amount, code) => {
        const result1 = formatCurrencyAmount(amount, code)
        const result2 = formatCurrencyAmount(amount, code)
        expect(result1).toBe(result2)
      }),
      { numRuns: 100 },
    )
  })

  it('negative amounts produce a leading minus sign', () => {
    fc.assert(
      fc.property(
        fc.double({ min: -10_000_000, max: -0.001, noNaN: true, noDefaultInfinity: true }),
        knownCurrencyArb,
        (amount, code) => {
          const result = formatCurrencyAmount(amount, code)
          expect(result.startsWith('-')).toBe(true)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('unknown currency codes fall back to 2 decimal places with code as symbol', () => {
    fc.assert(
      fc.property(amountArb, unknownCurrencyArb, (amount, code) => {
        const result = formatCurrencyAmount(amount, code)
        const fmt = getCurrencyFormat(code)
        expect(fmt.decimalPlaces).toBe(2)
        expect(fmt.symbol).toBe(code)
        expect(result).toContain(code)
      }),
      { numRuns: 100 },
    )
  })

  it('symbol position matches the format definition', () => {
    fc.assert(
      fc.property(amountArb, knownCurrencyArb, (amount, code) => {
        const result = formatCurrencyAmount(amount, code)
        const fmt = getCurrencyFormat(code)
        if (fmt.symbolPosition === 'after') {
          expect(result.endsWith(` ${fmt.symbol}`)).toBe(true)
        } else {
          // 'before' — symbol appears right after optional minus sign
          const withoutSign = result.startsWith('-') ? result.slice(1) : result
          expect(withoutSign.startsWith(fmt.symbol)).toBe(true)
        }
      }),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 28: Missing exchange rate blocks invoice creation         */
/* ------------------------------------------------------------------ */

describe('Property 28: Missing exchange rate blocks invoice creation', () => {
  it('base currency never has a missing rate', () => {
    fc.assert(
      fc.property(knownCurrencyArb, ratesArb, (baseCurrency, rates) => {
        // Base currency should always return false regardless of rates map
        expect(isMissingExchangeRate(baseCurrency, rates, baseCurrency)).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('non-base currency without a rate is flagged as missing', () => {
    fc.assert(
      fc.property(
        knownCurrencyArb,
        knownCurrencyArb.filter((c) => c !== 'NZD'),
        (baseCurrency, targetCurrency) => {
          // Empty rates map — non-base currency should be missing
          fc.pre(baseCurrency !== targetCurrency)
          const emptyRates: Record<string, number> = {}
          expect(isMissingExchangeRate(targetCurrency, emptyRates, baseCurrency)).toBe(true)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('non-base currency with a positive rate is not missing', () => {
    fc.assert(
      fc.property(
        knownCurrencyArb,
        knownCurrencyArb,
        fc.double({ min: 0.0001, max: 10_000, noNaN: true, noDefaultInfinity: true }),
        (baseCurrency, targetCurrency, rate) => {
          fc.pre(baseCurrency !== targetCurrency)
          const rates: Record<string, number> = { [targetCurrency]: rate }
          expect(isMissingExchangeRate(targetCurrency, rates, baseCurrency)).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('non-base currency with zero or negative rate is flagged as missing', () => {
    fc.assert(
      fc.property(
        knownCurrencyArb,
        knownCurrencyArb,
        fc.double({ min: -1000, max: 0, noNaN: true, noDefaultInfinity: true }),
        (baseCurrency, targetCurrency, badRate) => {
          fc.pre(baseCurrency !== targetCurrency)
          const rates: Record<string, number> = { [targetCurrency]: badRate }
          expect(isMissingExchangeRate(targetCurrency, rates, baseCurrency)).toBe(true)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('is case-insensitive for currency codes', () => {
    fc.assert(
      fc.property(knownCurrencyArb, ratesArb, (baseCurrency, rates) => {
        const resultUpper = isMissingExchangeRate(baseCurrency.toUpperCase(), rates, baseCurrency)
        const resultLower = isMissingExchangeRate(baseCurrency.toLowerCase(), rates, baseCurrency)
        expect(resultUpper).toBe(resultLower)
      }),
      { numRuns: 100 },
    )
  })
})
