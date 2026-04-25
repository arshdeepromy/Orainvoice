import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  safeExtractItems,
  safeExtractTotal,
  safeExtractDetail,
} from '@/hooks/useApiList'

/**
 * **Validates: Requirements 13.1**
 *
 * Property 4: Safe API response handling never throws on malformed responses
 *
 * For any API response shape — including responses with missing fields, null
 * values, empty objects {}, or unexpected types — the API consumption hooks
 * SHALL not throw exceptions and SHALL fall back to safe defaults (empty
 * arrays [] for lists, 0 for numbers, null for objects).
 */

// ---------------------------------------------------------------------------
// Generators
// ---------------------------------------------------------------------------

/** Arbitrary for any JSON-like value (including malformed shapes). */
const anyJsonArb: fc.Arbitrary<unknown> = fc.oneof(
  fc.constant(null),
  fc.constant(undefined),
  fc.constant({}),
  fc.constant([]),
  fc.string(),
  fc.integer(),
  fc.double(),
  fc.boolean(),
  fc.constant({ items: null }),
  fc.constant({ items: 'not-an-array' }),
  fc.constant({ items: 42 }),
  fc.constant({ total: 'not-a-number' }),
  fc.constant({ total: null }),
  fc.constant({ total: NaN }),
  fc.constant({ total: undefined }),
  fc.constant({ items: [], total: 10 }),
  fc.constant({ invoices: [{ id: '1' }], total: 1 }),
  fc.record({
    items: fc.oneof(fc.constant(null), fc.constant(undefined), fc.array(fc.anything())),
    total: fc.oneof(fc.constant(null), fc.constant(undefined), fc.integer(), fc.string()),
  }),
  fc.anything(),
)

/** Arbitrary for data key names. */
const dataKeyArb = fc.oneof(
  fc.constant('items'),
  fc.constant('invoices'),
  fc.constant('quotes'),
  fc.constant('jobs'),
  fc.constant('customers'),
  fc.string({ minLength: 1, maxLength: 20 }),
)

// ---------------------------------------------------------------------------
// Property tests
// ---------------------------------------------------------------------------

describe('Safe API response handling', () => {
  it('Property 4: safeExtractItems never throws on any input', () => {
    fc.assert(
      fc.property(anyJsonArb, dataKeyArb, (responseData, dataKey) => {
        // Must not throw
        const result = safeExtractItems(responseData, dataKey)

        // Must always return an array
        expect(Array.isArray(result)).toBe(true)
      }),
      { numRuns: 500 },
    )
  })

  it('Property 4a: safeExtractTotal never throws on any input', () => {
    fc.assert(
      fc.property(anyJsonArb, (responseData) => {
        // Must not throw
        const result = safeExtractTotal(responseData)

        // Must always return a number
        expect(typeof result).toBe('number')
        // Must never be NaN
        expect(isNaN(result)).toBe(false)
      }),
      { numRuns: 500 },
    )
  })

  it('Property 4b: safeExtractDetail never throws on any input', () => {
    fc.assert(
      fc.property(anyJsonArb, (responseData) => {
        // Must not throw
        const result = safeExtractDetail(responseData)

        // For null/undefined input, must return null
        if (responseData === null || responseData === undefined) {
          expect(result).toBeNull()
        }
      }),
      { numRuns: 500 },
    )
  })

  it('Property 4c: safeExtractItems returns correct array when data key exists with valid array', () => {
    fc.assert(
      fc.property(
        dataKeyArb,
        fc.array(fc.record({ id: fc.uuid() })),
        fc.nat(),
        (dataKey, items, total) => {
          const responseData = { [dataKey]: items, total }
          const result = safeExtractItems(responseData, dataKey)
          expect(result).toEqual(items)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('Property 4d: safeExtractTotal returns correct number when total is a valid number', () => {
    fc.assert(
      fc.property(fc.nat(), (total) => {
        const responseData = { items: [], total }
        const result = safeExtractTotal(responseData)
        expect(result).toBe(total)
      }),
      { numRuns: 200 },
    )
  })

  it('Property 4e: safeExtractItems falls back to items key when primary key is missing', () => {
    fc.assert(
      fc.property(
        fc.array(fc.record({ id: fc.uuid() })),
        (items) => {
          const responseData = { items }
          const result = safeExtractItems(responseData, 'nonexistent_key')
          expect(result).toEqual(items)
        },
      ),
      { numRuns: 100 },
    )
  })
})
