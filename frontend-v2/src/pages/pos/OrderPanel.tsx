/**
 * Order panel for POS with line items, quantity +/- buttons,
 * per-item and order-level discounts, and running totals.
 *
 * Validates: Requirement 22.2, 22.3 — POS order panel
 */

import type { POSLineItem } from './types'

interface OrderPanelProps {
  lineItems: POSLineItem[]
  orderDiscountPercent: number
  orderDiscountAmount: number
  onUpdateQuantity: (itemId: string, delta: number) => void
  onRemoveItem: (itemId: string) => void
  onSetItemDiscount: (itemId: string, percent: number) => void
  onSetOrderDiscount: (percent: number, amount: number) => void
  onCheckout: () => void
}

function calcLineTotal(item: POSLineItem): number {
  const base = item.unitPrice * item.quantity
  const discAmt = item.discountPercent > 0 ? base * (item.discountPercent / 100) : item.discountAmount
  return Math.max(0, base - discAmt)
}

export function calculateOrderTotals(
  lineItems: POSLineItem[],
  orderDiscountPercent: number,
  orderDiscountAmount: number,
  taxRate = 0.15,
) {
  const subtotal = lineItems.reduce((sum, item) => sum + calcLineTotal(item), 0)
  const orderDisc = orderDiscountPercent > 0
    ? subtotal * (orderDiscountPercent / 100)
    : orderDiscountAmount
  const afterDiscount = Math.max(0, subtotal - orderDisc)
  const taxAmount = afterDiscount * taxRate
  const total = afterDiscount + taxAmount
  return { subtotal, orderDisc, taxAmount, total }
}

export default function OrderPanel({
  lineItems,
  orderDiscountPercent,
  orderDiscountAmount,
  onUpdateQuantity,
  onRemoveItem,
  onSetOrderDiscount,
  onCheckout,
}: OrderPanelProps) {
  const { subtotal, orderDisc, taxAmount, total } = calculateOrderTotals(
    lineItems, orderDiscountPercent, orderDiscountAmount,
  )

  return (
    <div className="flex flex-col h-full bg-card">
      <h2 className="text-lg font-semibold px-4 py-3 border-b border-border text-text">Current Order</h2>

      {/* Line items */}
      <div className="flex-1 overflow-y-auto px-4 py-2" role="list" aria-label="Order items">
        {lineItems.length === 0 && (
          <p className="text-muted-2 text-center py-8 text-sm">No items added yet.</p>
        )}
        {lineItems.map((item) => (
          <div key={item.id} className="flex items-center gap-2 py-2 border-b border-border" role="listitem">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-text truncate">{item.product.name}</p>
              <p className="mono text-xs text-muted">${item.unitPrice.toFixed(2)} each</p>
              {item.discountPercent > 0 && (
                <p className="text-xs text-ok">-{item.discountPercent}% discount</p>
              )}
            </div>

            {/* Quantity controls */}
            <div className="flex items-center gap-1">
              <button
                onClick={() => onUpdateQuantity(item.id, -1)}
                className="w-8 h-8 rounded-ctl bg-canvas hover:bg-border text-text font-bold text-lg flex items-center justify-center"
                aria-label={`Decrease ${item.product.name} quantity`}
              >
                −
              </button>
              <span className="mono w-8 text-center text-sm font-medium text-text" aria-label={`${item.product.name} quantity`}>
                {item.quantity}
              </span>
              <button
                onClick={() => onUpdateQuantity(item.id, 1)}
                className="w-8 h-8 rounded-ctl bg-canvas hover:bg-border text-text font-bold text-lg flex items-center justify-center"
                aria-label={`Increase ${item.product.name} quantity`}
              >
                +
              </button>
            </div>

            {/* Line total */}
            <span className="mono text-sm font-semibold text-text w-16 text-right">
              ${calcLineTotal(item).toFixed(2)}
            </span>

            {/* Remove */}
            <button
              onClick={() => onRemoveItem(item.id)}
              className="text-danger hover:brightness-90 text-sm ml-1"
              aria-label={`Remove ${item.product.name}`}
            >
              ✕
            </button>
          </div>
        ))}
      </div>

      {/* Order discount */}
      <div className="px-4 py-2 border-t border-border">
        <label htmlFor="order-discount" className="text-xs text-muted">Order Discount %</label>
        <input
          id="order-discount"
          type="number"
          min={0}
          max={100}
          step={1}
          value={orderDiscountPercent}
          onChange={(e) => onSetOrderDiscount(Number(e.target.value), 0)}
          className="w-full rounded-ctl border border-border bg-card px-2 py-1 text-sm text-text mt-1 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          aria-label="Order discount percentage"
        />
      </div>

      {/* Totals */}
      <div className="px-4 py-3 border-t border-border space-y-1">
        <div className="flex justify-between text-sm text-muted">
          <span>Subtotal</span>
          <span className="mono">${subtotal.toFixed(2)}</span>
        </div>
        {orderDisc > 0 && (
          <div className="flex justify-between text-sm text-ok">
            <span>Discount</span>
            <span className="mono">-${orderDisc.toFixed(2)}</span>
          </div>
        )}
        <div className="flex justify-between text-sm text-muted">
          <span>Tax (GST)</span>
          <span className="mono">${taxAmount.toFixed(2)}</span>
        </div>
        <div className="flex justify-between text-base font-bold text-text pt-1 border-t border-border">
          <span>Total</span>
          <span className="mono" data-testid="order-total">${total.toFixed(2)}</span>
        </div>
      </div>

      {/* Checkout button */}
      <div className="px-4 pb-4">
        <button
          onClick={onCheckout}
          disabled={lineItems.length === 0}
          className="w-full py-3 rounded-ctl bg-accent text-white font-semibold text-base hover:bg-accent-press disabled:opacity-50 disabled:cursor-not-allowed"
          aria-label="Proceed to payment"
        >
          Pay ${total.toFixed(2)}
        </button>
      </div>
    </div>
  )
}
