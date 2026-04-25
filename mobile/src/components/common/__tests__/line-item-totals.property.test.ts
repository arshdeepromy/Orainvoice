import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { calculateTotals } from '../LineItemEditor'

/**
 * Property 2: Line item total calculation is mathematically correct
 *
 * For any set of line items where each item has a quantity (≥ 0),
 * unit price (≥ 0), and tax rate (0–1), the calculated subtotal SHALL
 * equal the sum of (quantity × unit price) for all items, the calculated
 * tax amount SHALL equal the sum of (quantity × unit price × tax rate)
 * for all items, and the calculated total SHALL equal subtotal + tax − discount.
 *
 * **Validates: Requirements 15.2, 16.2**
 */

// ---------------------------------------------------------------------------
// Arbitraries
// ---------------------------------------------------------------------------

const lineItemArb = fc.record({
  quantity: fc.double({ min: 0, max: 10000, noNaN: true, noDefaultInfinity: true }),
  unit_price: fc.double({ min: 0, max: 100000, noNaN: true, noDefaultInfinity: true }),
  tax_rate: fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
})

const discountArb = fc.double({ min: 0, max: 100000, noNaN: true, noDefaultInfinity: true })

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Line item total calculation', () => {
  it('Property 2: subtotal equals sum of qty × price for all items', () => {
    fc.assert(
      fc.property(fc.array(lineItemArb, { minLength: 0, maxLength: 50 }), (items) => {
        const result = calculateTotals(items)
        const expectedSubtotal = items.reduce(
          (sum, item) => sum + item.quantity * item.unit_price,
          0,
        )
        expect(result.subtotal).toBeCloseTo(expectedSubtotal, 6)
      }),
      { numRuns: 200 },
    )
  })

  it('Property 2: tax equals sum of qty × price × tax_rate for all items', () => {
    fc.assert(
      fc.property(fc.array(lineItemArb, { minLength: 0, maxLength: 50 }), (items) => {
        const result = calculateTotals(items)
        const expectedTax = items.reduce(
          (sum, item) => sum + item.quantity * item.unit_price * item.tax_rate,
          0,
        )
        expect(result.tax).toBeCloseTo(expectedTax, 6)
      }),
      { numRuns: 200 },
    )
  })

  it('Property 2: total equals subtotal + tax − discount', () => {
    fc.assert(
      fc.property(
        fc.array(lineItemArb, { minLength: 0, maxLength: 50 }),
        discountArb,
        (items, discount) => {
          const result = calculateTotals(items, discount)
          const expectedTotal = result.subtotal + result.tax - discount
          expect(result.total).toBeCloseTo(expectedTotal, 6)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('Property 2: empty items produce zero subtotal, tax, and total (minus discount)', () => {
    fc.assert(
      fc.property(discountArb, (discount) => {
        const result = calculateTotals([], discount)
        expect(result.subtotal).toBe(0)
        expect(result.tax).toBe(0)
        expect(result.total).toBeCloseTo(-discount, 6)
      }),
      { numRuns: 100 },
    )
  })

  it('Property 2: zero discount means total equals subtotal + tax', () => {
    fc.assert(
      fc.property(fc.array(lineItemArb, { minLength: 1, maxLength: 50 }), (items) => {
        const result = calculateTotals(items, 0)
        expect(result.total).toBeCloseTo(result.subtotal + result.tax, 6)
      }),
      { numRuns: 200 },
    )
  })

  it('Property 2: subtotal and tax are non-negative for non-negative inputs', () => {
    fc.assert(
      fc.property(fc.array(lineItemArb, { minLength: 0, maxLength: 50 }), (items) => {
        const result = calculateTotals(items)
        expect(result.subtotal).toBeGreaterThanOrEqual(0)
        expect(result.tax).toBeGreaterThanOrEqual(0)
      }),
      { numRuns: 200 },
    )
  })
})
