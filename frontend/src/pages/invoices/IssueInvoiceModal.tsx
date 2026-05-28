import { useState, useEffect } from 'react'
import { Modal } from '../../components/ui/Modal'
import { Button } from '../../components/ui/Button'

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
          <legend className="text-sm font-medium text-gray-900 mb-3">
            Payment Method
          </legend>
          <div className="space-y-2" role="radiogroup" aria-label="Payment method">
            {PAYMENT_METHODS.map((method) => {
              const isStripe = method.value === 'stripe'
              const isDisabled = isStripe && !stripeConnected

              return (
                <label
                  key={method.value}
                  className={`flex min-h-[44px] items-center gap-3 rounded-lg border px-4 py-3 transition-colors ${
                    isDisabled
                      ? 'cursor-not-allowed border-gray-200 bg-gray-50 opacity-60'
                      : paymentMethod === method.value
                        ? 'cursor-pointer border-indigo-500 bg-indigo-50'
                        : 'cursor-pointer border-gray-200 bg-white hover:bg-gray-50'
                  }`}
                >
                  <input
                    type="radio"
                    name="payment-method"
                    value={method.value}
                    checked={paymentMethod === method.value}
                    onChange={() => setPaymentMethod(method.value)}
                    disabled={isDisabled}
                    className="h-5 w-5 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span className="flex-1 text-sm font-medium text-gray-900">
                    {method.label}
                    {isStripe && !stripeConnected && (
                      <span className="ml-2 text-xs text-gray-500">(not configured)</span>
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
              className="h-5 w-5 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
            />
            <span className="text-sm font-medium text-gray-900">
              Email invoice to customer
            </span>
          </label>
          {emailInvoice && customerEmail && (
            <p className="ml-8 mt-1 text-sm text-gray-500">
              {customerEmail}
            </p>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex items-center justify-end gap-3 pt-2">
          <Button
            variant="secondary"
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
          <p className="text-sm text-red-600" role="alert">
            {error}
          </p>
        )}
      </div>
    </Modal>
  )
}

export default IssueInvoiceModal
