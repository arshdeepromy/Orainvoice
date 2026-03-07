import { useState } from 'react'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/Button'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Spinner } from '@/components/ui/Spinner'
import type { PortalInvoice } from './InvoiceHistory'

interface PaymentPageProps {
  token: string
  invoice: PortalInvoice
  primaryColor: string
  onBack: () => void
}

interface StripePaymentResponse {
  checkout_url: string
}

export function PaymentPage({ token, invoice, primaryColor, onBack }: PaymentPageProps) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [redirecting, setRedirecting] = useState(false)

  const handlePay = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.post<StripePaymentResponse>(
        `/portal/${token}/pay/${invoice.id}`,
      )
      setRedirecting(true)
      window.location.href = res.data.checkout_url
    } catch {
      setError('Unable to start payment. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (redirecting) {
    return (
      <div className="py-16 text-center">
        <Spinner label="Redirecting to payment" />
        <p className="mt-4 text-sm text-gray-500">Redirecting to secure payment…</p>
      </div>
    )
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
            <span className="font-medium text-gray-900 tabular-nums">{formatNZD(invoice.total)}</span>
          </div>
          {invoice.total !== invoice.balance_due && (
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">Already Paid</span>
              <span className="text-gray-600 tabular-nums">
                {formatNZD(invoice.total - invoice.balance_due)}
              </span>
            </div>
          )}
          <div className="flex justify-between text-sm font-semibold">
            <span className="text-gray-700">Amount Due</span>
            <span className="text-gray-900 tabular-nums">{formatNZD(invoice.balance_due)}</span>
          </div>
        </div>

        {/* Payment info */}
        <p className="mt-4 text-sm text-gray-500">
          You will be redirected to Stripe's secure checkout to complete your payment.
        </p>

        {error && (
          <AlertBanner variant="error" className="mt-4">
            {error}
          </AlertBanner>
        )}

        <div className="mt-6 flex gap-3">
          <Button
            onClick={handlePay}
            loading={loading}
            style={{ backgroundColor: primaryColor }}
            className="flex-1 !bg-[var(--btn-color)] hover:opacity-90"
          >
            Pay {formatNZD(invoice.balance_due)}
          </Button>
          <Button variant="secondary" onClick={onBack} disabled={loading}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  )
}

function formatNZD(amount: number): string {
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(amount)
}
