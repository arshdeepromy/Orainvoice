import { useState } from 'react'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/Button'
import type { PortalInvoice } from './InvoiceHistory'
import { usePortalLocale } from './PortalLocaleContext'
import { formatCurrency } from './portalFormatters'

interface PaymentPageProps {
  token: string
  invoice: PortalInvoice
  primaryColor: string
  onBack: () => void
}

interface PaymentResponse {
  payment_url: string
}

export function PaymentPage({ token, invoice, primaryColor, onBack }: PaymentPageProps) {
  const locale = usePortalLocale()
  const balanceDue = invoice.balance_due ?? 0
  const [payAmount, setPayAmount] = useState<string>(balanceDue.toFixed(2))
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [validationError, setValidationError] = useState('')

  const parsedAmount = parseFloat(payAmount)
  const isValidAmount =
    !isNaN(parsedAmount) && parsedAmount >= 0.01 && parsedAmount <= balanceDue

  const handleAmountChange = (value: string) => {
    setPayAmount(value)
    setValidationError('')

    const num = parseFloat(value)
    if (value === '') {
      setValidationError('')
    } else if (isNaN(num)) {
      setValidationError('Please enter a valid number.')
    } else if (num < 0.01) {
      setValidationError('Minimum payment is $0.01.')
    } else if (num > balanceDue) {
      setValidationError(`Amount cannot exceed the balance due of ${formatCurrency(balanceDue, locale)}.`)
    }
  }

  const handlePay = async () => {
    if (!isValidAmount || submitting) return

    setSubmitting(true)
    setError('')
    try {
      const res = await apiClient.post<PaymentResponse>(
        `/portal/${token}/pay/${invoice.id}`,
        { amount: parsedAmount },
      )
      const paymentUrl = res.data?.payment_url
      if (paymentUrl) {
        window.location.href = paymentUrl
      } else {
        setError('No payment URL returned. Please try again.')
      }
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(
        axiosErr?.response?.data?.detail ?? 'Payment failed. Please try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <button
        onClick={onBack}
        className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
      >
        ← Back to invoices
      </button>

      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="text-lg font-semibold text-gray-900">
          Pay Invoice {invoice.invoice_number}
        </h2>

        {/* Invoice summary */}
        <div className="mt-4 space-y-2 border-b border-gray-100 pb-4">
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">Invoice Total</span>
            <span className="font-medium text-gray-900 tabular-nums">
              {formatCurrency(invoice.total ?? 0, locale)}
            </span>
          </div>
          {(invoice.total ?? 0) !== balanceDue && (
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">Already Paid</span>
              <span className="text-gray-600 tabular-nums">
                {formatCurrency((invoice.total ?? 0) - balanceDue, locale)}
              </span>
            </div>
          )}
          <div className="flex justify-between text-sm font-semibold">
            <span className="text-gray-700">Amount Due</span>
            <span className="text-gray-900 tabular-nums">{formatCurrency(balanceDue, locale)}</span>
          </div>
        </div>

        {/* Amount input for partial payments */}
        <div className="mt-4">
          <label htmlFor="pay-amount" className="block text-sm font-medium text-gray-700">
            Payment Amount
          </label>
          <div className="relative mt-1">
            <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-gray-500 text-sm">
              $
            </span>
            <input
              id="pay-amount"
              type="number"
              min="0.01"
              max={balanceDue}
              step="0.01"
              value={payAmount}
              onChange={(e) => handleAmountChange(e.target.value)}
              disabled={submitting}
              className="block w-full rounded-md border border-gray-300 py-2 pl-7 pr-3 text-sm text-gray-900 tabular-nums placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-50 disabled:text-gray-500"
              aria-describedby={validationError ? 'amount-error' : undefined}
              aria-invalid={!!validationError}
            />
          </div>
          {validationError && (
            <p id="amount-error" className="mt-1 text-sm text-red-600" role="alert">
              {validationError}
            </p>
          )}
          <p className="mt-1 text-xs text-gray-400">
            Enter any amount between $0.01 and {formatCurrency(balanceDue, locale)}
          </p>
        </div>

        {/* Error from backend */}
        {error && (
          <div className="mt-4 rounded-md border border-red-200 bg-red-50 px-4 py-3" role="alert">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        <div className="mt-6 flex gap-3">
          <Button variant="secondary" onClick={onBack} disabled={submitting}>
            Back to invoices
          </Button>
          <Button
            onClick={handlePay}
            disabled={!isValidAmount || submitting}
            style={{ backgroundColor: isValidAmount && !submitting ? primaryColor : undefined }}
            className={
              isValidAmount && !submitting
                ? '!bg-[var(--btn-color)] hover:opacity-90'
                : ''
            }
          >
            {submitting ? 'Processing…' : `Pay ${isValidAmount ? formatCurrency(parsedAmount, locale) : ''}`}
          </Button>
        </div>
      </div>
    </div>
  )
}
