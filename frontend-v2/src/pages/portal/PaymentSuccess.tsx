import { useParams, Link } from 'react-router-dom'

/**
 * Confirmation page shown after a successful Stripe Checkout payment.
 * Stripe redirects the customer here via the `success_url` configured
 * on the Checkout session.
 */
export function PaymentSuccess() {
  const { token } = useParams<{ token: string }>()

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-md rounded-card border border-border bg-card p-8 text-center shadow-card">
        {/* Success icon */}
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-ok-soft">
          <svg
            className="h-7 w-7 text-ok"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={2}
            stroke="currentColor"
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
        </div>

        <h1 className="text-xl font-semibold text-text">Payment received</h1>
        <p className="mt-2 text-sm text-muted">
          Thank you — your payment has been processed successfully.
        </p>

        <Link
          to={`/portal/${token ?? ''}`}
          className="mt-6 inline-block rounded-ctl bg-accent px-5 py-2.5 text-sm font-medium text-white hover:bg-accent-press focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
        >
          Back to invoices
        </Link>
      </div>
    </div>
  )
}

export default PaymentSuccess
