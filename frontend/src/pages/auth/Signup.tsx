import { useState, useEffect, FormEvent } from 'react'
import { loadStripe } from '@stripe/stripe-js'
import { Elements, CardElement, useStripe, useElements } from '@stripe/react-stripe-js'
import apiClient from '@/api/client'
import { Button, Input, AlertBanner, Spinner } from '@/components/ui'
import { validateSignupForm } from './signup-validation'
import type { SignupFormData, SignupResponse, PublicPlan, PublicPlanListResponse } from './signup-types'

type Step = 'form' | 'stripe' | 'done'

const stripePromise = import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY
  ? loadStripe(import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY)
  : null

function StripeCardForm({
  clientSecret,
  onSuccess,
  onError,
}: {
  clientSecret: string
  onSuccess: () => void
  onError: (msg: string) => void
}) {
  const stripe = useStripe()
  const elements = useElements()
  const [confirming, setConfirming] = useState(false)
  const [stripeError, setStripeError] = useState<string | null>(null)

  async function handleConfirm(e: FormEvent) {
    e.preventDefault()
    if (!stripe || !elements) return

    setStripeError(null)
    setConfirming(true)

    const cardElement = elements.getElement(CardElement)
    if (!cardElement) {
      setConfirming(false)
      return
    }

    const { error } = await stripe.confirmCardSetup(clientSecret, {
      payment_method: { card: cardElement },
    })

    setConfirming(false)

    if (error) {
      const msg = error.message ?? 'Card setup failed. Please try again.'
      setStripeError(msg)
      onError(msg)
    } else {
      onSuccess()
    }
  }

  return (
    <form onSubmit={handleConfirm} className="space-y-4">
      {stripeError && (
        <AlertBanner variant="error" onDismiss={() => setStripeError(null)}>
          {stripeError}
        </AlertBanner>
      )}
      <div>
        <label className="text-sm font-medium text-gray-700">Card details</label>
        <div className="mt-1 rounded-md border border-gray-300 p-3">
          <CardElement
            options={{
              style: {
                base: { fontSize: '16px', color: '#1f2937' },
                invalid: { color: '#dc2626' },
              },
            }}
          />
        </div>
      </div>
      <Button type="submit" loading={confirming} disabled={!stripe} className="w-full">
        Confirm card
      </Button>
    </form>
  )
}

export function Signup() {
  const [step, setStep] = useState<Step>('form')
  const [plans, setPlans] = useState<PublicPlan[]>([])
  const [plansLoading, setPlansLoading] = useState(true)
  const [plansError, setPlansError] = useState<string | null>(null)

  const [formData, setFormData] = useState<SignupFormData>({
    org_name: '',
    admin_email: '',
    admin_first_name: '',
    admin_last_name: '',
    plan_id: '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const [stripeClientSecret, setStripeClientSecret] = useState<string | null>(null)
  // signup_token stored for potential future use (e.g. resuming signup)
  const [_signupToken, setSignupToken] = useState<string | null>(null)

  useEffect(() => {
    fetchPlans()
  }, [])

  async function fetchPlans() {
    setPlansLoading(true)
    setPlansError(null)
    try {
      const res = await apiClient.get<PublicPlanListResponse>('/auth/plans')
      setPlans(res.data.plans)
    } catch {
      setPlansError('Unable to load plans. Please try again later.')
    } finally {
      setPlansLoading(false)
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setApiError(null)

    const validationErrors = validateSignupForm(formData)
    setErrors(validationErrors)
    if (Object.keys(validationErrors).length > 0) return

    setSubmitting(true)
    try {
      const res = await apiClient.post<SignupResponse>('/auth/signup', formData)
      setSignupToken(res.data.signup_token)
      setStripeClientSecret(res.data.stripe_setup_intent_client_secret)
      setStep('stripe')
    } catch (err: unknown) {
      if (
        err &&
        typeof err === 'object' &&
        'response' in err &&
        (err as { response?: { status?: number; data?: { detail?: string } } }).response?.status === 400
      ) {
        const detail = (err as { response: { data: { detail?: string } } }).response.data.detail
        setApiError(detail ?? 'Signup failed. Please check your details.')
      } else {
        setApiError('Something went wrong. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  function handleFieldChange(field: keyof SignupFormData, value: string) {
    setFormData((prev) => ({ ...prev, [field]: value }))
    if (errors[field]) {
      setErrors((prev) => {
        const next = { ...prev }
        delete next[field]
        return next
      })
    }
  }

  if (step === 'done') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
            <span className="text-2xl" aria-hidden="true">✓</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">You're almost there!</h1>
          <p className="text-gray-600">
            We've sent a verification email to your inbox. Please check your email and click the
            verification link to set your password and get started.
          </p>
        </div>
      </div>
    )
  }

  if (step === 'stripe' && stripeClientSecret) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg">
          <div className="text-center">
            <h1 className="text-2xl font-bold text-gray-900">Payment details</h1>
            <p className="mt-1 text-sm text-gray-500">
              Add your card to start your 14-day free trial
            </p>
          </div>
          <Elements stripe={stripePromise} options={{ clientSecret: stripeClientSecret }}>
            <StripeCardForm
              clientSecret={stripeClientSecret}
              onSuccess={() => setStep('done')}
              onError={() => {}}
            />
          </Elements>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900">Create your account</h1>
          <p className="mt-1 text-sm text-gray-500">
            Start your 14-day free trial
          </p>
        </div>

        {plansLoading && (
          <div className="flex justify-center">
            <Spinner size="md" label="Loading plans" />
          </div>
        )}

        {plansError && (
          <div className="space-y-3">
            <AlertBanner variant="error">{plansError}</AlertBanner>
            <Button type="button" variant="secondary" onClick={fetchPlans} className="w-full">
              Retry
            </Button>
          </div>
        )}

        {!plansLoading && !plansError && plans.length === 0 && (
          <AlertBanner variant="warning">
            Signup is temporarily unavailable. Please try again later.
          </AlertBanner>
        )}

        {!plansLoading && !plansError && plans.length > 0 && (
          <>
            {apiError && (
              <AlertBanner variant="error" onDismiss={() => setApiError(null)}>
                {apiError}
              </AlertBanner>
            )}

            <form onSubmit={handleSubmit} className="space-y-4" noValidate>
              <Input
                label="Organisation name"
                type="text"
                required
                value={formData.org_name}
                onChange={(e) => handleFieldChange('org_name', e.target.value)}
                error={errors.org_name}
                placeholder="My Business Ltd"
              />

              <Input
                label="Email address"
                type="email"
                autoComplete="email"
                required
                value={formData.admin_email}
                onChange={(e) => handleFieldChange('admin_email', e.target.value)}
                error={errors.admin_email}
                placeholder="you@example.com"
              />

              <div className="grid grid-cols-2 gap-3">
                <Input
                  label="First name"
                  type="text"
                  required
                  value={formData.admin_first_name}
                  onChange={(e) => handleFieldChange('admin_first_name', e.target.value)}
                  error={errors.admin_first_name}
                  placeholder="Jane"
                />
                <Input
                  label="Last name"
                  type="text"
                  required
                  value={formData.admin_last_name}
                  onChange={(e) => handleFieldChange('admin_last_name', e.target.value)}
                  error={errors.admin_last_name}
                  placeholder="Smith"
                />
              </div>

              <div className="flex flex-col gap-1">
                <label htmlFor="plan-selector" className="text-sm font-medium text-gray-700">
                  Plan
                </label>
                <select
                  id="plan-selector"
                  value={formData.plan_id}
                  onChange={(e) => handleFieldChange('plan_id', e.target.value)}
                  className={`rounded-md border px-3 py-2 text-gray-900 shadow-sm transition-colors
                    focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2
                    ${errors.plan_id ? 'border-red-500' : 'border-gray-300'}`}
                  aria-invalid={errors.plan_id ? 'true' : undefined}
                  aria-describedby={errors.plan_id ? 'plan-selector-error' : undefined}
                >
                  <option value="">Select a plan</option>
                  {plans.map((plan) => (
                    <option key={plan.id} value={plan.id}>
                      {plan.name} — ${plan.monthly_price_nzd}/mo
                    </option>
                  ))}
                </select>
                {errors.plan_id && (
                  <p id="plan-selector-error" className="text-sm text-red-600" role="alert">
                    {errors.plan_id}
                  </p>
                )}
              </div>

              <Button type="submit" loading={submitting} className="w-full">
                Sign up
              </Button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
