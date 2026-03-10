import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  shouldTriggerCustomerSearch,
  shouldShowAddNewOption,
  getPrePopulatedFirstName,
  filterActiveServicesWithPricing,
} from '../utils/bookingFormHelpers'
import type { ServiceCatalogueItem } from '../utils/bookingFormHelpers'

// Feature: booking-modal-enhancements, Property 1: Customer search triggers at minimum query length
// Feature: booking-modal-enhancements, Property 2: Empty search results show inline add option
// Feature: booking-modal-enhancements, Property 5: Search query pre-populates inline customer name

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Generate a non-empty string of length >= 2 (trimmed) for valid search queries */
const validSearchQueryArb = fc
  .string({ minLength: 2, maxLength: 100 })
  .filter((s) => s.trim().length >= 2)

/** Generate a string of length < 2 (trimmed) for short/invalid search queries */
const shortQueryArb = fc.oneof(
  fc.constant(''),
  fc.constant(' '),
  fc.constant('  '),
  fc.string({ minLength: 1, maxLength: 1 }),
).filter((s) => s.trim().length < 2)

/** Generate a string that looks like a name (alphabetic + spaces only, non-empty when trimmed) */
const namelikeQueryArb = fc
  .array(
    fc.oneof(
      fc.string({ minLength: 1, maxLength: 1 }).filter((c) => /[a-zA-Z]/.test(c)),
      fc.constant(' '),
    ),
    { minLength: 1, maxLength: 50 },
  )
  .map((chars) => chars.join(''))
  .filter((s) => s.trim().length > 0 && /^[a-zA-Z\s]+$/.test(s.trim()))

/** Generate a string that does NOT look like a name (contains digits, symbols, etc.) */
const nonNameQueryArb = fc
  .string({ minLength: 1, maxLength: 50 })
  .filter((s) => {
    const trimmed = s.trim()
    return trimmed.length > 0 && !/^[a-zA-Z\s]+$/.test(trimmed)
  })

/** Generate a non-negative integer for result counts */
const resultCountArb = fc.nat({ max: 100 })

/* ------------------------------------------------------------------ */
/*  Property 1: Customer search triggers at minimum query length       */
/*  **Validates: Requirements 1.1**                                    */
/* ------------------------------------------------------------------ */

describe('Property 1: Customer search triggers at minimum query length', () => {
  it('triggers search for any query with trimmed length >= 2', () => {
    fc.assert(
      fc.property(validSearchQueryArb, (query) => {
        expect(shouldTriggerCustomerSearch(query)).toBe(true)
      }),
      { numRuns: 20 },
    )
  })

  it('does not trigger search for any query with trimmed length < 2', () => {
    fc.assert(
      fc.property(shortQueryArb, (query) => {
        expect(shouldTriggerCustomerSearch(query)).toBe(false)
      }),
      { numRuns: 20 },
    )
  })

  it('search trigger matches trimmed length >= 2 for any string', () => {
    fc.assert(
      fc.property(fc.string({ maxLength: 100 }), (query) => {
        const expected = query.trim().length >= 2
        expect(shouldTriggerCustomerSearch(query)).toBe(expected)
      }),
      { numRuns: 20 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 2: Empty search results show inline add option            */
/*  **Validates: Requirements 1.2, 3.3**                               */
/* ------------------------------------------------------------------ */

describe('Property 2: Empty search results show inline add option', () => {
  it('shows "Add new" when results are empty and query >= 2 chars', () => {
    fc.assert(
      fc.property(validSearchQueryArb, (query) => {
        expect(shouldShowAddNewOption(query, 0)).toBe(true)
      }),
      { numRuns: 20 },
    )
  })

  it('does not show "Add new" when results are non-empty', () => {
    fc.assert(
      fc.property(
        validSearchQueryArb,
        fc.integer({ min: 1, max: 100 }),
        (query, count) => {
          expect(shouldShowAddNewOption(query, count)).toBe(false)
        },
      ),
      { numRuns: 20 },
    )
  })

  it('does not show "Add new" when query is too short regardless of result count', () => {
    fc.assert(
      fc.property(shortQueryArb, resultCountArb, (query, count) => {
        expect(shouldShowAddNewOption(query, count)).toBe(false)
      }),
      { numRuns: 20 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 5: Search query pre-populates inline customer name        */
/*  **Validates: Requirements 1.7**                                    */
/* ------------------------------------------------------------------ */

describe('Property 5: Search query pre-populates inline customer name', () => {
  it('pre-populates first name with trimmed query when query is name-like', () => {
    fc.assert(
      fc.property(namelikeQueryArb, (query) => {
        const result = getPrePopulatedFirstName(query)
        expect(result).toBe(query.trim())
      }),
      { numRuns: 20 },
    )
  })

  it('returns empty string when query contains non-alphabetic characters', () => {
    fc.assert(
      fc.property(nonNameQueryArb, (query) => {
        const result = getPrePopulatedFirstName(query)
        expect(result).toBe('')
      }),
      { numRuns: 20 },
    )
  })

  it('returns empty string for empty or whitespace-only queries', () => {
    fc.assert(
      fc.property(
        fc.array(fc.constant(' '), { minLength: 0, maxLength: 10 }).map((arr) => arr.join('')),
        (query) => {
          const result = getPrePopulatedFirstName(query)
          expect(result).toBe('')
        },
      ),
      { numRuns: 20 },
    )
  })
})


// Feature: booking-modal-enhancements, Property 7: Service selector returns only active services with pricing

/* ------------------------------------------------------------------ */
/*  Generators for Property 7                                          */
/* ------------------------------------------------------------------ */

/** Generate a random service catalogue item with mixed active/inactive and with/without pricing */
const serviceCatalogueItemArb: fc.Arbitrary<ServiceCatalogueItem> = fc.record({
  name: fc.string({ minLength: 1, maxLength: 50 }).filter((s) => s.trim().length > 0),
  is_active: fc.boolean(),
  default_price: fc.oneof(
    fc.constant(null),
    fc.constant(''),
    fc.constant('  '),
    fc
      .float({ min: Math.fround(0.01), max: Math.fround(99999), noNaN: true })
      .map((n) => n.toFixed(2)),
  ),
})

/** Generate an array of random service catalogue items */
const serviceCatalogueListArb = fc.array(serviceCatalogueItemArb, {
  minLength: 0,
  maxLength: 20,
})

/* ------------------------------------------------------------------ */
/*  Property 7: Service selector returns only active services with     */
/*  pricing                                                            */
/*  **Validates: Requirements 3.1**                                    */
/* ------------------------------------------------------------------ */

describe('Property 7: Service selector returns only active services with pricing', () => {
  it('returns only items where is_active is true and default_price is non-null/non-empty', () => {
    fc.assert(
      fc.property(serviceCatalogueListArb, (services) => {
        const result = filterActiveServicesWithPricing(services)

        // Every returned item must be active
        for (const item of result) {
          expect(item.is_active).toBe(true)
        }

        // Every returned item must have a non-null, non-empty default_price
        for (const item of result) {
          expect(item.default_price).not.toBeNull()
          expect(typeof item.default_price).toBe('string')
          expect(item.default_price!.trim().length).toBeGreaterThan(0)
        }
      }),
      { numRuns: 20 },
    )
  })

  it('every returned item has both a name and a default_price', () => {
    fc.assert(
      fc.property(serviceCatalogueListArb, (services) => {
        const result = filterActiveServicesWithPricing(services)

        for (const item of result) {
          expect(item.name).toBeDefined()
          expect(typeof item.name).toBe('string')
          expect(item.default_price).toBeDefined()
          expect(typeof item.default_price).toBe('string')
        }
      }),
      { numRuns: 20 },
    )
  })

  it('never includes inactive services regardless of pricing', () => {
    fc.assert(
      fc.property(serviceCatalogueListArb, (services) => {
        const result = filterActiveServicesWithPricing(services)
        const inactiveInResult = result.filter((s) => !s.is_active)
        expect(inactiveInResult).toHaveLength(0)
      }),
      { numRuns: 20 },
    )
  })

  it('never includes services without valid pricing regardless of active status', () => {
    fc.assert(
      fc.property(serviceCatalogueListArb, (services) => {
        const result = filterActiveServicesWithPricing(services)
        const noPriceInResult = result.filter(
          (s) => s.default_price == null || s.default_price.trim() === '',
        )
        expect(noPriceInResult).toHaveLength(0)
      }),
      { numRuns: 20 },
    )
  })
})
