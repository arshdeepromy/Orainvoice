/**
 * Payment panel for POS with cash (change calculation), card (Stripe terminal),
 * and split payment support.
 *
 * Validates: Requirement 22.4 — POS payment methods
 */

import { useState } from 'react'
import type { PaymentMethod, PaymentInfo } from './types'

interface PaymentPanelProps {
  total: number
  onComplete: (payment: PaymentInfo) => void
  onCancel: () => void
}

export default function PaymentPanel({ total, onComplete, onCancel }: PaymentPanelProps) {
  const [method, setMethod] = useState<PaymentMethod>('cash')
  const [cashTendered, setCashTendered] = useState<string>('')
  const [splitCash, setSplitCash] = useState<string>('')
  const [processing, setProcessing] = useState(false)

  const cashAmount = parseFloat(cashTendered) || 0
  const changeGiven = Math.max(0, cashAmount - total)

  const splitCashAmount = parseFloat(splitCash) || 0
  const splitCardAmount = Math.max(0, total - splitCashAmount)

  const canCompleteCash = cashAmount >= total
  const canCompleteCard = true
  const canCompleteSplit = splitCashAmount > 0 && splitCashAmount < total

  const handleComplete = async () => {
    setProcessing(true)
    try {
      let payment: PaymentInfo
      if (method === 'cash') {
        payment = { method: 'cash', cashTendered: cashAmount, changeGiven }
      } else if (method === 'card') {
        payment = { method: 'card', cardAmount: total }
      } else {
        payment = {
          method: 'split',
          splitCash: splitCashAmount,
          splitCard: splitCardAmount,
        }
      }
      onComplete(payment)
    } finally {
      setProcessing(false)
    }
  }

  const isValid =
    (method === 'cash' && canCompleteCash) ||
    (method === 'card' && canCompleteCard) ||
    (method === 'split' && canCompleteSplit)

  // Quick cash buttons
  const quickAmounts = [
    Math.ceil(total),
    Math.ceil(total / 5) * 5,
    Math.ceil(total / 10) * 10,
    Math.ceil(total / 20) * 20,
    Math.ceil(total / 50) * 50,
  ].filter((v, i, arr) => v >= total && arr.indexOf(v) === i).slice(0, 4)

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" role="dialog" aria-label="Payment">
      <div className="bg-card rounded-card shadow-pop w-full max-w-md mx-4">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="text-lg font-semibold text-text">Payment</h2>
          <button onClick={onCancel} className="text-muted hover:text-text" aria-label="Cancel payment">✕</button>
        </div>

        <div className="px-6 py-4">
          {/* Total display */}
          <div className="text-center mb-6">
            <p className="text-sm text-muted">Amount Due</p>
            <p className="mono text-3xl font-bold text-text" data-testid="payment-total">${total.toFixed(2)}</p>
          </div>

          {/* Payment method tabs */}
          <div className="flex gap-2 mb-6" role="tablist" aria-label="Payment method">
            {(['cash', 'card', 'split'] as PaymentMethod[]).map((m) => (
              <button
                key={m}
                role="tab"
                aria-selected={method === m}
                onClick={() => setMethod(m)}
                className={`flex-1 py-2 rounded-ctl text-sm font-medium capitalize ${
                  method === m ? 'bg-accent text-white' : 'bg-canvas text-text hover:bg-border'
                }`}
              >
                {m}
              </button>
            ))}
          </div>

          {/* Cash payment */}
          {method === 'cash' && (
            <div role="tabpanel" aria-label="Cash payment">
              <label htmlFor="cash-tendered" className="block text-sm font-medium text-text mb-1">
                Cash Tendered
              </label>
              <input
                id="cash-tendered"
                type="number"
                inputMode="numeric"
                min={0}
                step={0.01}
                value={cashTendered}
                onChange={(e) => setCashTendered(e.target.value)}
                className="mono w-full rounded-ctl border border-border bg-card px-3 py-2 text-lg text-text mb-3 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                placeholder="0.00"
                autoFocus
              />
              {/* Quick amount buttons */}
              <div className="flex gap-2 mb-4">
                {quickAmounts.map((amt) => (
                  <button
                    key={amt}
                    type="button"
                    onClick={() => setCashTendered(String(amt))}
                    className="mono flex-1 py-2 rounded-ctl bg-canvas text-text hover:bg-border text-sm font-medium"
                  >
                    ${amt}
                  </button>
                ))}
              </div>
              {cashAmount >= total && (
                <div className="text-center py-2 bg-ok-soft rounded-ctl">
                  <p className="text-sm text-muted">Change</p>
                  <p className="mono text-2xl font-bold text-ok" data-testid="change-amount">${changeGiven.toFixed(2)}</p>
                </div>
              )}
            </div>
          )}

          {/* Card payment */}
          {method === 'card' && (
            <div role="tabpanel" aria-label="Card payment" className="text-center py-4">
              <p className="text-muted text-sm">Present card to terminal or enter card details.</p>
              <p className="mono text-lg font-semibold mt-2 text-text">${total.toFixed(2)}</p>
            </div>
          )}

          {/* Split payment */}
          {method === 'split' && (
            <div role="tabpanel" aria-label="Split payment">
              <label htmlFor="split-cash" className="block text-sm font-medium text-text mb-1">
                Cash Amount
              </label>
              <input
                id="split-cash"
                type="number"
                inputMode="numeric"
                min={0}
                max={total}
                step={0.01}
                value={splitCash}
                onChange={(e) => setSplitCash(e.target.value)}
                className="mono w-full rounded-ctl border border-border bg-card px-3 py-2 text-lg text-text mb-3 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                placeholder="0.00"
              />
              <div className="flex justify-between text-sm text-muted mb-2">
                <span>Card Amount</span>
                <span className="mono font-medium text-text">${splitCardAmount.toFixed(2)}</span>
              </div>
            </div>
          )}
        </div>

        {/* Action buttons */}
        <div className="px-6 py-4 border-t border-border flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 py-2.5 rounded-ctl border border-border text-text font-medium hover:bg-canvas"
          >
            Cancel
          </button>
          <button
            onClick={handleComplete}
            disabled={!isValid || processing}
            className="flex-1 py-2.5 rounded-ctl bg-ok text-white font-semibold hover:brightness-95 disabled:opacity-50"
            aria-label="Complete payment"
          >
            {processing ? 'Processing…' : 'Complete'}
          </button>
        </div>
      </div>
    </div>
  )
}
