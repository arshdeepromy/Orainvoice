import { Button } from '@/components/ui/Button'
import type { PortalInvoice } from './InvoiceHistory'

interface PaymentPageProps {
  token: string
  invoice: PortalInvoice
  primaryColor: string
  onBack: () => void
}

export function PaymentPage({ invoice, onBack }: PaymentPageProps) {

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
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-sm font-medium text-amber-800">Online payments coming soon</p>
          <p className="text-sm text-amber-700 mt-1">
            Online payment processing is not yet available. Please contact us directly to arrange payment.
          </p>
        </div>

        <div className="mt-6 flex gap-3">
          <Button variant="secondary" onClick={onBack}>
            Back to invoices
          </Button>
        </div>
      </div>
    </div>
  )
}

function formatNZD(amount: number): string {
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(amount)
}
