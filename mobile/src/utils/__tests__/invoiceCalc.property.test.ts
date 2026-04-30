// Feature: mobile-konsta-redesign, Property 3: Invoice calculation correctness
// **Validates: Requirements 20.8, 56.1**

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { calculateInvoiceTotals } from '@/utils/invoiceCalc'

/**
 * Property 3: Invoice calculation correctness.
 *
 * For any valid set of line items (each with non-negative quantity,
 * non-negative unit_price, tax_rate in [0, 1], tax_mode, and optional
 * discount_percent), discount type ('percentage' or 'fixed') with
 * non-negative value, non-negative shipping charges, and adjustment value,
 * the invoice total calculation SHALL satisfy:
 *   total = (subtotal - discountAmount) + taxAmount + shippingCharges + adjustment
 * where all amounts are rounded to 2 decimal places.
 */
describe('Property 3: Invoice calculation correctness', () => {
  // Arbitrary for a single line item
  const lineItemArb = fc.record({
    quantity: fc.integer({ min: 0, max: 100 }),
    unit_price: fc.float({ min: 0, max: 10000, noNaN: true }),
    tax_rate: fc.float({ min: 0, max: 1, noNaN: true }),
    tax_mode: fc.constantFrom('exclusive', 'inclusive', 'exempt'),
    discount_percent: fc.oneof(
      fc.constant(0),
      fc.float({ min: 0, max: 100, noNaN: true }),
    ),
  })

  const lineItemsArb = fc.array(lineItemArb, { minLength: 0, maxLength: 10 })

  const discountTypeArb = fc.constantFrom(
    'percentage' as const,
    'fixed' as const,
  )
  const discountValueArb = fc.float({ min: 0, max: 1000, noNaN: true })
  const shippingArb = fc.float({ min: 0, max: 500, noNaN: true })
  const adjustmentArb = fc.float({ min: -500, max: 500, noNaN: true })

  it('total equals (subtotal - discount) + tax + shipping + adjustment', () => {
    fc.assert(
      fc.property(
        lineItemsArb,
        discountTypeArb,
        discountValueArb,
        shippingArb,
        adjustmentArb,
        (items, discountType, discountValue, shipping, adjustment) => {
          const result = calculateInvoiceTotals(
            items,
            discountType,
            discountValue,
            shipping,
            adjustment,
          )

          // Verify the total formula — allow for floating point rounding
          // The function rounds each component independently, so we verify
          // the total matches the sum of the already-rounded components
          const expectedTotal =
            Math.round(
              (result.subtotal -
                result.discountAmount +
                result.taxAmount +
                result.shipping +
                result.adjustment) *
                100,
            ) / 100

          // Allow 1 cent tolerance due to independent rounding of components
          // Use a small epsilon for floating point comparison
          expect(Math.abs(result.total - expectedTotal)).toBeLessThan(0.011)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('subtotal is non-negative for non-negative inputs', () => {
    fc.assert(
      fc.property(lineItemsArb, (items) => {
        const result = calculateInvoiceTotals(
          items,
          'fixed',
          0,
          0,
          0,
        )
        expect(result.subtotal).toBeGreaterThanOrEqual(0)
      }),
      { numRuns: 200 },
    )
  })

  it('taxAmount is non-negative for non-negative inputs', () => {
    fc.assert(
      fc.property(lineItemsArb, (items) => {
        const result = calculateInvoiceTotals(
          items,
          'fixed',
          0,
          0,
          0,
        )
        expect(result.taxAmount).toBeGreaterThanOrEqual(0)
      }),
      { numRuns: 200 },
    )
  })

  it('all amounts are rounded to 2 decimal places', () => {
    fc.assert(
      fc.property(
        lineItemsArb,
        discountTypeArb,
        discountValueArb,
        shippingArb,
        adjustmentArb,
        (items, discountType, discountValue, shipping, adjustment) => {
          const result = calculateInvoiceTotals(
            items,
            discountType,
            discountValue,
            shipping,
            adjustment,
          )

          // Check each amount has at most 2 decimal places
          const check2dp = (n: number) => {
            const rounded = Math.round(n * 100) / 100
            expect(n).toBeCloseTo(rounded, 10)
          }

          check2dp(result.subtotal)
          check2dp(result.discountAmount)
          check2dp(result.taxAmount)
          check2dp(result.shipping)
          check2dp(result.adjustment)
          check2dp(result.total)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('empty line items produce zero totals', () => {
    fc.assert(
      fc.property(
        discountTypeArb,
        shippingArb,
        adjustmentArb,
        (discountType, shipping, adjustment) => {
          const result = calculateInvoiceTotals(
            [],
            discountType,
            0,
            shipping,
            adjustment,
          )

          expect(result.subtotal).toBe(0)
          expect(result.taxAmount).toBe(0)
        },
      ),
      { numRuns: 100 },
    )
  })
})
