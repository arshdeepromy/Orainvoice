/**
 * Invoice calculation utilities.
 *
 * Computes subtotal, discount, tax, and total from line items.
 * Handles inclusive, exclusive, and exempt tax modes per line.
 * All amounts are rounded to 2 decimal places.
 *
 * Requirements: 20.8, 56.1
 */

export interface LineItemInput {
  quantity: number
  unit_price: number
  tax_rate: number
  tax_mode?: string
  discount_percent?: number
}

export interface InvoiceTotals {
  subtotal: number
  discountAmount: number
  taxAmount: number
  shipping: number
  adjustment: number
  total: number
}

/**
 * Calculate invoice totals from line items, discount, shipping, and adjustment.
 *
 * - subtotal = sum of line amounts (after per-line discounts)
 * - discountAmount = percentage of subtotal or fixed amount
 * - taxAmount handles inclusive/exclusive/exempt per line
 * - total = (subtotal - discountAmount) + taxAmount + shipping + adjustment
 *
 * For inclusive tax: price includes tax, so tax is extracted from the amount.
 * For exclusive tax: tax is added on top of the amount.
 * For exempt: no tax.
 */
export function calculateInvoiceTotals(
  items: ReadonlyArray<LineItemInput>,
  discountType: 'percentage' | 'fixed',
  discountValue: number,
  shippingCharges: number,
  adjustment: number,
): InvoiceTotals {
  let subtotal = 0
  let taxAmount = 0

  for (const item of items) {
    const qty = item.quantity ?? 0
    const price = item.unit_price ?? 0
    const rate = item.tax_rate ?? 0
    const mode = item.tax_mode ?? 'exclusive'
    const lineDiscount = item.discount_percent ?? 0

    let lineAmount = qty * price
    // Apply per-line discount
    if (lineDiscount > 0) {
      lineAmount = lineAmount * (1 - lineDiscount / 100)
    }

    if (mode === 'inclusive') {
      // Price includes tax — extract tax from the amount
      const taxPortion = lineAmount - lineAmount / (1 + rate)
      taxAmount += Math.round(taxPortion * 100) / 100
      subtotal += Math.round((lineAmount - taxPortion) * 100) / 100
    } else if (mode === 'exempt') {
      // No tax
      subtotal += Math.round(lineAmount * 100) / 100
    } else {
      // exclusive (default)
      subtotal += Math.round(lineAmount * 100) / 100
      taxAmount += Math.round(lineAmount * rate * 100) / 100
    }
  }

  const discountAmount =
    discountType === 'percentage'
      ? Math.round(subtotal * (discountValue / 100) * 100) / 100
      : Math.round((discountValue ?? 0) * 100) / 100

  const total =
    Math.round(
      (subtotal - discountAmount + taxAmount + shippingCharges + adjustment) *
        100,
    ) / 100

  return {
    subtotal: Math.round(subtotal * 100) / 100,
    discountAmount,
    taxAmount: Math.round(taxAmount * 100) / 100,
    shipping: Math.round(shippingCharges * 100) / 100,
    adjustment: Math.round(adjustment * 100) / 100,
    total,
  }
}
