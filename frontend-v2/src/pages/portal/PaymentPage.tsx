import { useState } from 'react'
import apiClient from '@/api/client'
import { Button } from '@/components/ui'
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
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded"
      >
        ← Back to invoices
      </button>

      <div className="rounded-card border border-border bg-card shadow-card p-6">
        <h2 className="text-lg font-semibold text-text">
          Pay Invoice {invoice.invoice_number}
        </h2>

        {/* Invoice summary */}
        <div className="mt-4 space-y-2 border-b border-border pb-4">
          <div className="flex justify-between text-sm">
            <span className="text-muted">Invoice Total</span>
            <span className="mono font-medium text-text tabular-nums">
              {formatCurrency(invoice.total ?? 0, locale)}
            </span>
          </div>
          {(invoice.total ?? 0) !== balanceDue && (
            <div className="flex justify-between text-sm">
              <span className="text-muted">Already Paid</span>
              <span className="mono text-muted tabular-nums">
                {formatCurrency((invoice.total ?? 0) - balanceDue, locale)}
              </span>
            </div>
          )}
          <div className="flex justify-between text-sm font-semibold">
            <span className="text-text">Amount Due</span>
            <span className="mono text-text tabular-nums">{formatCurrency(balanceDue, locale)}</span>
          </div>
        </div>

        {/* Amount input for partial payments */}
        <div className="mt-4">
          <label htmlFor="pay-amount" className="block text-sm font-medium text-text">
            Payment Amount
          </label>
          <div className="relative mt-1">
            <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-muted text-sm">
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
              className="block w-full rounded-ctl border border-border py-2 pl-7 pr-3 text-sm text-text tabular-nums placeholder:text-muted-2 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:bg-canvas disabled:text-muted"
              aria-describedby={validationError ? 'amount-error' : undefined}
              aria-invalid={!!validationError}
            />
          </div>
          {validationError && (
            <p id="amount-error" className="mt-1 text-sm text-danger" role="alert">
              {validationError}
            </p>
          )}
          <p className="mt-1 text-xs text-muted-2">
            Enter any amount between $0.01 and {formatCurrency(balanceDue, locale)}
          </p>
        </div>

        {/* Error from backend */}
        {error && (
          <div className="mt-4 rounded-ctl border border-danger bg-danger-soft px-4 py-3" role="alert">
            <p className="text-sm text-danger">{error}</p>
          </div>
        )}

        <div className="mt-6 flex gap-3">
          <Button variant="ghost" onClick={onBack} disabled={submitting}>
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
