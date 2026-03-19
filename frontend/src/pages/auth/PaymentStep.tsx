import { useState, FormEvent } from 'react'
import { Elements, CardElement, useStripe, useElements } from '@stripe/react-stripe-js'
import type { Stripe } from '@stripe/stripe-js'
import apiClient from '@/api/client'
import { Button, AlertBanner } from '@/components/ui'

export interface PaymentStepProps {
  pendingSignupId: string
  clientSecret: string
  planName: string
  paymentAmountCents: number
  planAmountCents?: number
  gstAmountCents?: number
  gstPercentage?: number
  processingFeeCents?: number
  stripePromise: Promise<Stripe | null> | null
  onComplete: () => void
  onSessionExpired: (message: string) => void
}

function PaymentCardForm({
  clientSecret,
  pendingSignupId,
  planName,
  paymentAmountCents,
  planAmountCents,
  gstAmountCents,
  gstPercentage,
  processingFeeCents,
  onComplete,
  onSessionExpired,
}: Omit<PaymentStepProps, 'stripePromise'>) {
  const stripe = useStripe()
  const elements = useElements()
  const [processing, setProcessing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmRetry, setConfirmRetry] = useState<{
    paymentIntentId: string
  } | null>(null)

  const amountDisplay = `$${(paymentAmountCents / 100).toFixed(2)} NZD`
  const hasBreakdown = planAmountCents !== undefined && gstAmountCents !== undefined

  async function callConfirmPayment(paymentIntentId: string) {
    try {
      await apiClient.post('/auth/signup/confirm-payment', {
        payment_intent_id: paymentIntentId,
        pending_signup_id: pendingSignupId,
      })
      setConfirmRetry(null)
      onComplete()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      const message = detail ?? 'Failed to confirm payment. Please try again.'

      if (message.toLowerCase().includes('invalid or expired signup session')) {
        onSessionExpired(message)
        return
      }

      setError(message)
      setConfirmRetry({ paymentIntentId })
    }
  }

  async function handleRetry() {
    if (!confirmRetry) return
    setProcessing(true)
    setError(null)
    await callConfirmPayment(confirmRetry.paymentIntentId)
    setProcessing(false)
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!stripe || !elements) return

    setProcessing(true)
    setError(null)
    setConfirmRetry(null)

    const cardElement = elements.getElement(CardElement)
    if (!cardElement) {
      setError('Card element not found')
      setProcessing(false)
      return
    }

    const { error: stripeError, paymentIntent } = await stripe.confirmCardPayment(
      clientSecret,
      { payment_method: { card: cardElement } },
    )

    if (stripeError) {
      setError(stripeError.message ?? 'Payment failed')
      setProcessing(false)
      return
    }

    if (paymentIntent?.status === 'succeeded') {
      await callConfirmPayment(paymentIntent.id)
      setProcessing(false)
    } else {
      setError('Payment was not completed. Please try again.')
      setProcessing(false)
    }
  }

  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-900">Complete payment</h2>
      <p className="mt-1 text-sm text-gray-600">
        Enter your card details to activate your{' '}
        <span className="font-semibold">{planName}</span> plan.
      </p>

      <form onSubmit={handleSubmit} className="mt-6 space-y-4" data-testid="payment-form">
        {error && (
          <AlertBanner variant="error">
            {error}
          </AlertBanner>
        )}

        {/* Billing breakdown */}
        {hasBreakdown ? (
          <div className="rounded-md border border-gray-200 bg-gray-50 p-4 space-y-2 text-sm">
            <div className="flex justify-between text-gray-700">
              <span>{planName} plan (monthly)</span>
              <span>${((planAmountCents ?? 0) / 100).toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-gray-700">
              <span>GST ({gstPercentage ?? 15}%)</span>
              <span>${((gstAmountCents ?? 0) / 100).toFixed(2)}</span>
            </div>
            {(processingFeeCents ?? 0) > 0 && (
              <div className="flex justify-between text-gray-700">
                <span>Payment processing fee</span>
                <span>${((processingFeeCents ?? 0) / 100).toFixed(2)}</span>
              </div>
            )}
            <div className="flex justify-between font-semibold text-gray-900 border-t border-gray-300 pt-2">
              <span>Total</span>
              <span>{amountDisplay}</span>
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-600">
            You will be charged{' '}
            <span className="font-semibold">{amountDisplay}</span> for your first
            month on the <span className="font-semibold">{planName}</span> plan.
          </p>
        )}

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

        <p className="text-xs text-gray-500">
          Your card will be charged immediately. You can cancel anytime from
          your billing settings.
        </p>

        {confirmRetry ? (
          <Button
            type="button"
            onClick={handleRetry}
            loading={processing}
            disabled={processing}
            className="w-full"
          >
            Retry
          </Button>
        ) : (
          <Button
            type="submit"
            loading={processing}
            disabled={!stripe || processing}
            className="w-full"
          >
            Pay {amountDisplay} and activate
          </Button>
        )}
      </form>
    </div>
  )
}

export function PaymentStep({
  pendingSignupId,
  clientSecret,
  planName,
  paymentAmountCents,
  planAmountCents,
  gstAmountCents,
  gstPercentage,
  processingFeeCents,
  stripePromise,
  onComplete,
  onSessionExpired,
}: PaymentStepProps) {
  if (!stripePromise) {
    return (
      <AlertBanner variant="error">
        Stripe is not configured. Please contact support to complete your signup.
      </AlertBanner>
    )
  }

  return (
    <Elements stripe={stripePromise} options={{ clientSecret }}>
      <PaymentCardForm
        clientSecret={clientSecret}
        pendingSignupId={pendingSignupId}
        planName={planName}
        paymentAmountCents={paymentAmountCents}
        planAmountCents={planAmountCents}
        gstAmountCents={gstAmountCents}
        gstPercentage={gstPercentage}
        processingFeeCents={processingFeeCents}
        onComplete={onComplete}
        onSessionExpired={onSessionExpired}
      />
    </Elements>
  )
}
