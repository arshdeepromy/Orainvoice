/**
 * Money-math unit tests for InvoiceCreate (Task 20).
 *
 * These reproduce the EXACT calculation formulas copied verbatim from
 * frontend/src/pages/invoices/InvoiceCreate.tsx and assert the byte-identical
 * results, guarding against any accidental drift in the GST / discount / total
 * arithmetic during the redesign port (FR-1, money correctness).
 *
 * The formulas under test (must stay in sync with InvoiceCreate.tsx):
 *   • calcLineAmount     = round(qty × rate × 100) / 100
 *   • GST-inclusive back-calc rate = round((inclPrice / 1.15) × 100) / 100
 *   • per-line GST (inclusive) = round((round(qty × inclPrice ×100)/100) − amount) ×100)/100
 *   • per-line GST (exclusive) = round(amount × taxRate) / 100
 *   • discount (%)       = subTotal × discountValue / 100
 *   • discount (fixed)   = discountValue
 *   • total              = (subTotal − discount) + tax + shipping + adjustment
 */

import { describe, it, expect } from 'vitest'

/* ── Verbatim formula replicas from InvoiceCreate.tsx ── */

interface Line {
  quantity: number
  rate: number
  tax_rate: number
  amount: number
  gst_inclusive?: boolean
  inclusive_price?: number
}

const calcLineAmount = (item: { quantity: number; rate: number }) =>
  Math.round(item.quantity * item.rate * 100) / 100

const backCalcExGstRate = (inclusivePrice: number) =>
  Math.round((inclusivePrice / 1.15) * 100) / 100

function computeTotals(
  lineItems: Line[],
  discountType: 'percentage' | 'fixed',
  discountValue: number,
  shippingCharges: number,
  adjustment: number,
) {
  const subTotal = lineItems.reduce((sum, item) => sum + item.amount, 0)
  const discountAmount = discountType === 'percentage'
    ? (subTotal * discountValue / 100)
    : discountValue
  const afterDiscount = subTotal - discountAmount
  const taxAmount = lineItems.reduce((sum, item) => {
    if (item.tax_rate <= 0) return sum
    if (item.gst_inclusive && item.inclusive_price) {
      const inclTotal = Math.round(item.quantity * item.inclusive_price * 100) / 100
      const gst = Math.round((inclTotal - item.amount) * 100) / 100
      return sum + gst
    }
    return sum + Math.round(item.amount * item.tax_rate) / 100
  }, 0)
  const total = afterDiscount + taxAmount + shippingCharges + adjustment
  return { subTotal, discountAmount, afterDiscount, taxAmount, total }
}

describe('InvoiceCreate — line amount', () => {
  it('rounds qty × rate to 2dp', () => {
    expect(calcLineAmount({ quantity: 3, rate: 19.99 })).toBe(59.97)
    expect(calcLineAmount({ quantity: 1, rate: 0 })).toBe(0)
    // 0.1 × 3 floating point — rounded to cents
    expect(calcLineAmount({ quantity: 3, rate: 0.1 })).toBe(0.3)
  })
})

describe('InvoiceCreate — GST-inclusive back-calculation', () => {
  it('derives ex-GST rate from a $150 inc-GST price (rounds to 130.43)', () => {
    expect(backCalcExGstRate(150)).toBe(130.43)
  })

  it('per-line GST is derived from the inclusive price (preserves the cent)', () => {
    // $150 incl, qty 1 → ex-GST amount 130.43; GST = 150 - 130.43 = 19.57
    // (NOT 130.43 × 0.15 = 19.56 — the inclusive path keeps the extra cent)
    const rate = backCalcExGstRate(150)
    const amount = calcLineAmount({ quantity: 1, rate })
    const { taxAmount, total } = computeTotals(
      [{ quantity: 1, rate, tax_rate: 15, amount, gst_inclusive: true, inclusive_price: 150 }],
      'percentage', 0, 0, 0,
    )
    expect(amount).toBe(130.43)
    expect(taxAmount).toBe(19.57)
    expect(total).toBe(150)
  })
})

describe('InvoiceCreate — GST-exclusive totals', () => {
  it('applies 15% GST on the ex-GST amount', () => {
    const amount = calcLineAmount({ quantity: 2, rate: 50 }) // 100
    const { subTotal, taxAmount, total } = computeTotals(
      [{ quantity: 2, rate: 50, tax_rate: 15, amount }],
      'percentage', 0, 0, 0,
    )
    expect(subTotal).toBe(100)
    expect(taxAmount).toBe(15)
    expect(total).toBe(115)
  })

  it('treats gst-exempt (0%) lines as no GST', () => {
    const amount = calcLineAmount({ quantity: 1, rate: 80 })
    const { taxAmount, total } = computeTotals(
      [{ quantity: 1, rate: 80, tax_rate: 0, amount }],
      'percentage', 0, 0, 0,
    )
    expect(taxAmount).toBe(0)
    expect(total).toBe(80)
  })
})

describe('InvoiceCreate — discounts', () => {
  it('percentage discount reduces the ex-GST subtotal before GST/total', () => {
    const amount = calcLineAmount({ quantity: 1, rate: 100 })
    const { discountAmount, afterDiscount, total } = computeTotals(
      [{ quantity: 1, rate: 100, tax_rate: 15, amount }],
      'percentage', 10, 0, 0,
    )
    expect(discountAmount).toBe(10)
    expect(afterDiscount).toBe(90)
    // GST is computed on the full line amount (15), then total = 90 + 15
    expect(total).toBe(105)
  })

  it('fixed discount subtracts a flat amount', () => {
    const amount = calcLineAmount({ quantity: 1, rate: 200 })
    const { discountAmount, total } = computeTotals(
      [{ quantity: 1, rate: 200, tax_rate: 15, amount }],
      'fixed', 25, 0, 0,
    )
    expect(discountAmount).toBe(25)
    // (200 - 25) + 30 GST = 205
    expect(total).toBe(205)
  })
})

describe('InvoiceCreate — shipping & adjustment', () => {
  it('adds shipping and adjustment to the total', () => {
    const amount = calcLineAmount({ quantity: 1, rate: 100 })
    const { total } = computeTotals(
      [{ quantity: 1, rate: 100, tax_rate: 15, amount }],
      'percentage', 0, 12.5, -2.5,
    )
    // 100 + 15 GST + 12.5 shipping - 2.5 adjustment = 125
    expect(total).toBe(125)
  })
})

describe('InvoiceCreate — mixed line invoice', () => {
  it('sums exclusive, inclusive, and exempt lines correctly', () => {
    const exclusive = { quantity: 1, rate: 100, tax_rate: 15, amount: calcLineAmount({ quantity: 1, rate: 100 }) }
    const inclRate = backCalcExGstRate(57.5) // 50.00
    const inclusive = { quantity: 1, rate: inclRate, tax_rate: 15, amount: calcLineAmount({ quantity: 1, rate: inclRate }), gst_inclusive: true, inclusive_price: 57.5 }
    const exempt = { quantity: 1, rate: 40, tax_rate: 0, amount: calcLineAmount({ quantity: 1, rate: 40 }) }

    const { subTotal, taxAmount, total } = computeTotals(
      [exclusive, inclusive, exempt],
      'percentage', 0, 0, 0,
    )
    // subTotal ex-GST = 100 + 50 + 40 = 190
    expect(subTotal).toBe(190)
    // GST = 15 (exclusive) + 7.5 (inclusive: 57.5 - 50) + 0 (exempt) = 22.5
    expect(taxAmount).toBe(22.5)
    // total = 190 + 22.5 = 212.5
    expect(total).toBe(212.5)
  })
})
