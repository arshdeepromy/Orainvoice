import { useState, FormEvent } from 'react'
import { Elements, CardElement, useStripe, useElements } from '@stripe/react-stripe-js'
import type { Stripe } from '@stripe/stripe-js'
import apiClient from '@/api/client'
import { Button, AlertBanner } from '@/components/ui'

/**
 * PaymentStep — Stripe Elements card-payment step of the signup wizard (Task 13
 * port of frontend/src/pages/auth/PaymentStep).
 *
 * ALL logic is copied verbatim: the Stripe `confirmCardPayment` flow, the
 * POST /auth/signup/confirm-payment call (with payment_intent_id +
 * pending_signup_id), the "invalid or expired signup session" → onSessionExpired
 * branch, the confirm-retry state machine, the billing breakdown maths, and the
 * Elements wrapper that gates on a configured stripePromise. The publishable key
 * still comes from the backend (loaded by the parent SignupWizard via
 * /auth/stripe-publishable-key) — there is no env var to change. Only the
 * breakdown card / CardElement border / hint copy are remapped to design tokens.
 */
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

  const amountDisplay = `${(paymentAmountCents / 100).toFixed(2)} NZD`
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
      <h2 className="text-[22px] font-bold text-text">Complete payment</h2>
      <p className="mt-1 text-[13.5px] text-muted">
        Enter your card details to activate your{' '}
        <span className="font-semibold text-text">{planName}</span> plan.
      </p>

      <form onSubmit={handleSubmit} className="mt-6 space-y-4" data-testid="payment-form">
        {error && (
          <AlertBanner variant="error">
            {error}
          </AlertBanner>
        )}

        {/* Billing breakdown */}
        {hasBreakdown ? (
          <div className="space-y-2 rounded-ctl border border-border bg-canvas p-4 text-[13.5px]">
            <div className="flex justify-between text-text">
              <span>{planName} plan (monthly)</span>
              <span className="mono">${((planAmountCents ?? 0) / 100).toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-text">
              <span>GST ({gstPercentage ?? 15}%)</span>
              <span className="mono">${((gstAmountCents ?? 0) / 100).toFixed(2)}</span>
            </div>
            {(processingFeeCents ?? 0) > 0 && (
              <div className="flex justify-between text-text">
                <span>Payment processing fee</span>
                <span className="mono">${((processingFeeCents ?? 0) / 100).toFixed(2)}</span>
              </div>
            )}
            <div className="flex justify-between border-t border-border-strong pt-2 font-semibold text-text">
              <span>Total</span>
              <span className="mono">{amountDisplay}</span>
            </div>
          </div>
        ) : (
          <p className="text-[13.5px] text-muted">
            You will be charged{' '}
            <span className="font-semibold text-text">{amountDisplay}</span> for your first
            month on the <span className="font-semibold text-text">{planName}</span> plan.
          </p>
        )}

        <div className="rounded-ctl border border-border p-3">
          <CardElement
            options={{
              hidePostalCode: true,
              style: {
                base: {
                  fontSize: '16px',
                  color: '#111722',
                  '::placeholder': { color: '#97A0AE' },
                },
              },
            }}
          />
        </div>

        <p className="text-[12px] text-muted-2">
          Your card will be charged immediately. You can cancel anytime from
          your billing settings.
        </p>

        {confirmRetry ? (
          <Button
            type="button"
            onClick={handleRetry}
            loading={processing}
            disabled={processing}
            fullWidth
          >
            Retry
          </Button>
        ) : (
          <Button
            type="submit"
            loading={processing}
            disabled={!stripe || processing}
            fullWidth
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
