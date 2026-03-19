import { useState, FormEvent } from 'react'
import { CardElement, useStripe, useElements } from '@stripe/react-stripe-js'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/Button'
import { AlertBanner } from '@/components/ui/AlertBanner'

/* ── Types ── */

interface SetupIntentResponse {
  client_secret: string
  setup_intent_id: string
}

export interface CardFormProps {
  onSuccess: () => void
  onCancel?: () => void
}

/* ── Component ── */

export function CardForm({ onSuccess, onCancel }: CardFormProps) {
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

      // Step 3: Success — notify parent to refresh the list
      onSuccess()
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr?.response?.data?.detail ?? 'Failed to set up card. Please try again.')
      setProcessing(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 rounded-lg border border-gray-200 bg-white p-5">
      <h3 className="text-sm font-semibold text-gray-900">Add a new card</h3>

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

      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" loading={processing} disabled={!stripe || processing}>
          {processing ? 'Saving card…' : 'Save card'}
        </Button>
        {onCancel && (
          <Button type="button" variant="secondary" size="sm" onClick={onCancel} disabled={processing}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  )
}
