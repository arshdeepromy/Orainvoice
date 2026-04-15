/**
 * BlockingPaymentModal
 *
 * Non-dismissible modal that forces an org_admin to add a payment method
 * before they can use the application. Embeds the Stripe CardElement flow
 * (same pattern as CardForm in Billing.tsx).
 *
 * The modal auto-dismisses when the parent's `onSuccess` callback triggers
 * a refetch and `has_payment_method` becomes true.
 *
 * Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
 */

import { useState, useEffect, FormEvent } from 'react'
import { loadStripe, type Stripe } from '@stripe/stripe-js'
import { Elements, CardElement, useStripe, useElements } from '@stripe/react-stripe-js'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import apiClient from '@/api/client'

/* ── Types ── */

interface BlockingPaymentModalProps {
  open: boolean
  onSuccess: () => void
}

interface SetupIntentResponse {
  client_secret: string
  setup_intent_id: string
}

/* ── Inner form (must be inside <Elements>) ── */

function BlockingCardForm({ onSuccess }: { onSuccess: () => void }) {
  const stripe = useStripe()
  const elements = useElements()
  const [processing, setProcessing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!stripe || !elements) return

    setProcessing(true)
    setError(null)

    const cardElement = elements.getElement(CardElement)
    if (!cardElement) {
      setError('Card element not found')
      setProcessing(false)
      return
    }

    try {
      // Step 1: Create a SetupIntent on the backend
      const { data } = await apiClient.post<SetupIntentResponse>('/billing/setup-intent')

      // Step 2: Confirm the SetupIntent with Stripe
      const { error: stripeError } = await stripe.confirmCardSetup(data.client_secret, {
        payment_method: { card: cardElement },
      })

      if (stripeError) {
        setError(stripeError.message ?? 'Card setup failed. Please try again.')
        setProcessing(false)
        return
      }

      // Step 3: Success — wait briefly for webhook/sync, then notify parent
      // The status endpoint will sync from Stripe if local DB has no methods,
      // but we add a small delay to give the Stripe API time to register the card.
      await new Promise((resolve) => setTimeout(resolve, 1500))
      onSuccess()
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr?.response?.data?.detail ?? 'Failed to set up card. Please try again.')
      setProcessing(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="rounded-md border border-gray-300 p-3">
        <CardElement
          options={{
            hidePostalCode: true,
            style: {
              base: {
                fontSize: '16px',
                color: '#1f2937',
                '::placeholder': { color: '#9ca3af' },
              },
            },
          }}
        />
      </div>

      {error && (
        <AlertBanner variant="error">{error}</AlertBanner>
      )}

      <Button
        type="submit"
        size="sm"
        loading={processing}
        disabled={!stripe || processing}
        className="w-full"
      >
        {processing ? 'Saving card…' : 'Add payment method'}
      </Button>
    </form>
  )
}

/* ── Main component ── */

export function BlockingPaymentModal({ open, onSuccess }: BlockingPaymentModalProps) {
  const [stripePromise, setStripePromise] = useState<Promise<Stripe | null> | null>(null)
  const [stripeLoading, setStripeLoading] = useState(true)

  // Load Stripe publishable key when the modal opens
  useEffect(() => {
    if (!open) return

    const controller = new AbortController()

    async function loadStripeKey() {
      setStripeLoading(true)
      try {
        const res = await apiClient.get<{ publishable_key: string }>(
          '/auth/stripe-publishable-key',
          { signal: controller.signal },
        )
        if (res.data?.publishable_key) {
          setStripePromise(loadStripe(res.data.publishable_key))
        }
      } catch {
        // Stripe key load failed — form will show disabled state
      } finally {
        if (!controller.signal.aborted) {
          setStripeLoading(false)
        }
      }
    }

    loadStripeKey()
    return () => controller.abort()
  }, [open])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="blocking-payment-title"
    >
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-2xl">
        <div className="mb-4 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-red-100">
            <svg
              className="h-6 w-6 text-red-600"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3m-3.75 3h15a2.25 2.25 0 002.25-2.25V6.75A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25v10.5A2.25 2.25 0 004.5 19.5z"
              />
            </svg>
          </div>
          <h2
            id="blocking-payment-title"
            className="text-lg font-semibold text-gray-900"
          >
            Payment method required
          </h2>
          <p className="mt-1 text-sm text-gray-600">
            Please add a payment method to continue using the application.
          </p>
        </div>

        {stripeLoading ? (
          <div className="flex justify-center py-6">
            <Spinner label="Loading payment form…" />
          </div>
        ) : stripePromise ? (
          <Elements stripe={stripePromise}>
            <BlockingCardForm onSuccess={onSuccess} />
          </Elements>
        ) : (
          <AlertBanner variant="error">
            Unable to load the payment form. Please refresh the page and try again.
          </AlertBanner>
        )}
      </div>
    </div>
  )
}
