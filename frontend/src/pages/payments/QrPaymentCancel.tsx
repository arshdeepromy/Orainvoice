import { useSearchParams } from 'react-router-dom'

/**
 * QR Payment Cancel Page
 *
 * Displayed on the customer's phone after they cancel on the Stripe Checkout page.
 * No authentication required — this is a public page.
 *
 * Validates: Requirements 2.6
 */
export default function QrPaymentCancel() {
  const [searchParams] = useSearchParams()
  const invoiceId = searchParams.get('invoice_id')

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="flex flex-col items-center gap-6 rounded-2xl bg-white p-10 text-center shadow-lg max-w-sm w-full">
        {/* Orange/yellow warning icon */}
        <div className="flex h-20 w-20 items-center justify-center rounded-full bg-orange-100">
          <svg
            className="h-12 w-12 text-orange-500"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={2.5}
            stroke="currentColor"
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </div>

        {/* Heading */}
        <h1 className="text-2xl font-bold text-gray-900">Payment cancelled</h1>

        {/* Subtext */}
        <p className="text-base text-gray-500">You can close this page or try again</p>

        {/* Reference info (optional display) */}
        {invoiceId && (
          <div className="mt-2 w-full rounded-lg bg-gray-50 px-4 py-3 text-left text-sm text-gray-400">
            <p className="truncate">
              <span className="font-medium text-gray-500">Invoice:</span> {invoiceId}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
