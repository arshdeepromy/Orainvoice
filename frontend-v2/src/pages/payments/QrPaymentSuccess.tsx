import { useSearchParams } from 'react-router-dom'

/**
 * QR Payment Success Page
 *
 * Displayed on the customer's phone after Stripe redirects them following
 * a successful payment. No authentication required — this is a public page.
 *
 * Validates: Requirements 2.5
 */
export default function QrPaymentSuccess() {
  const [searchParams] = useSearchParams()
  const invoiceId = searchParams.get('invoice_id')
  const sessionId = searchParams.get('session_id')

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="flex flex-col items-center gap-6 rounded-2xl bg-white p-10 text-center shadow-lg max-w-sm w-full">
        {/* Green tick */}
        <div className="flex h-20 w-20 items-center justify-center rounded-full bg-green-100">
          <svg
            className="h-12 w-12 text-green-600"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={2.5}
            stroke="currentColor"
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
        </div>

        {/* Heading */}
        <h1 className="text-2xl font-bold text-gray-900">Payment successful</h1>

        {/* Subtext */}
        <p className="text-base text-gray-500">You can close this page</p>

        {/* Reference info (optional display) */}
        {(invoiceId || sessionId) && (
          <div className="mt-2 w-full rounded-lg bg-gray-50 px-4 py-3 text-left text-sm text-gray-400">
            {invoiceId && (
              <p className="truncate">
                <span className="font-medium text-gray-500">Invoice:</span> {invoiceId}
              </p>
            )}
            {sessionId && (
              <p className="truncate mt-1">
                <span className="font-medium text-gray-500">Session:</span> {sessionId}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
