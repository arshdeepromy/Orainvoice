import { useState, useEffect } from 'react'
import { Modal, Button } from '@/components/ui'

/**
 * IssueInvoiceModal — Task 20 port of frontend/src/pages/invoices/IssueInvoiceModal.tsx.
 *
 * All logic (payment-method radio group with Stripe gating, "email invoice to
 * customer" checkbox defaulting to the customer's email presence, reset-on-open,
 * confirm → onConfirm(method, shouldEmail)) is copied VERBATIM. Styling is
 * remapped onto the design-system tokens (FR-2b — no prototype for this dialog):
 * accent-selected radio rows, 44px touch targets preserved, danger error text.
 */
export interface IssueInvoiceModalProps {
  open: boolean
  onClose: () => void
  onConfirm: (paymentMethod: string, shouldEmail: boolean) => void
  customerEmail: string | null
  loading: boolean
  stripeConnected: boolean
  error?: string | null
}

const PAYMENT_METHODS = [
  { value: 'cash', label: 'Cash' },
  { value: 'eftpos', label: 'EFTPOS' },
  { value: 'bank_transfer', label: 'Bank Transfer' },
  { value: 'stripe', label: 'Online Payment' },
] as const

export function IssueInvoiceModal({
  open,
  onClose,
  onConfirm,
  customerEmail,
  loading,
  stripeConnected,
  error,
}: IssueInvoiceModalProps) {
  const [paymentMethod, setPaymentMethod] = useState<string>('cash')
  const [emailInvoice, setEmailInvoice] = useState<boolean>(!!customerEmail)

  // Sync emailInvoice default when customerEmail prop changes
  useEffect(() => {
    setEmailInvoice(!!customerEmail)
  }, [customerEmail])

  // Reset state when modal opens
  useEffect(() => {
    if (open) {
      setPaymentMethod('cash')
      setEmailInvoice(!!customerEmail)
    }
  }, [open, customerEmail])

  const handleConfirm = () => {
    onConfirm(paymentMethod, emailInvoice)
  }

  return (
    <Modal open={open} onClose={onClose} title="Issue Invoice">
      <div className="space-y-6">
        {/* Payment Method */}
        <fieldset>
          <legend className="text-sm font-medium text-text mb-3">
            Payment Method
          </legend>
          <div className="space-y-2" role="radiogroup" aria-label="Payment method">
            {PAYMENT_METHODS.map((method) => {
              const isStripe = method.value === 'stripe'
              const isDisabled = isStripe && !stripeConnected

              return (
                <label
                  key={method.value}
                  className={`flex min-h-[44px] items-center gap-3 rounded-ctl border px-4 py-3 transition-colors ${
                    isDisabled
                      ? 'cursor-not-allowed border-border bg-canvas opacity-60'
                      : paymentMethod === method.value
                        ? 'cursor-pointer border-accent bg-accent-soft'
                        : 'cursor-pointer border-border bg-card hover:bg-canvas'
                  }`}
                >
                  <input
                    type="radio"
                    name="payment-method"
                    value={method.value}
                    checked={paymentMethod === method.value}
                    onChange={() => setPaymentMethod(method.value)}
                    disabled={isDisabled}
                    className="h-5 w-5 text-accent focus:ring-accent"
                  />
                  <span className="flex-1 text-sm font-medium text-text">
                    {method.label}
                    {isStripe && !stripeConnected && (
                      <span className="ml-2 text-xs text-muted">(not configured)</span>
                    )}
                  </span>
                </label>
              )
            })}
          </div>
        </fieldset>

        {/* Email Invoice Checkbox */}
        <div>
          <label className="flex min-h-[44px] items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={emailInvoice}
              onChange={(e) => setEmailInvoice(e.target.checked)}
              className="h-5 w-5 rounded border-border text-accent focus:ring-accent"
            />
            <span className="text-sm font-medium text-text">
              Email invoice to customer
            </span>
          </label>
          {emailInvoice && customerEmail && (
            <p className="ml-8 mt-1 text-sm text-muted">
              {customerEmail}
            </p>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex items-center justify-end gap-3 pt-2">
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={loading}
            className="min-h-[44px]"
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleConfirm}
            loading={loading}
            disabled={loading}
            className="min-h-[44px]"
          >
            Issue Invoice
          </Button>
        </div>

        {/* Error Message */}
        {error && (
          <p className="text-sm text-danger" role="alert">
            {error}
          </p>
        )}
      </div>
    </Modal>
  )
}

export default IssueInvoiceModal
