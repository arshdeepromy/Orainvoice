import { useState, useEffect, useCallback, useMemo, FormEvent } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Page, Block, List, ListInput, Button } from 'konsta/react'
import { loadStripe, type Stripe } from '@stripe/stripe-js'
import { Elements, CardElement, useStripe, useElements } from '@stripe/react-stripe-js'
import apiClient from '@/api/client'

/**
 * SignupScreen — Konsta UI multi-step signup wizard with progress dots.
 *
 * Step 1: Account (first name, last name, email, password, confirm password, business name)
 * Step 2: Plan selection (fetched from GET /auth/plans)
 * Step 3: Stripe Elements card form (shown only when payment required)
 * Step 4: Confirmation (check your email)
 *
 * Business logic is preserved unchanged from the frontend SignupWizard:
 * - POST /auth/signup with form data
 * - If requires_payment + stripe_client_secret → show Stripe card form
 * - POST /auth/signup/confirm-payment after successful Stripe payment
 * - If no payment required → show confirmation directly
 *
 * Requirements: 13.1, 13.2, 13.3, 13.4
 */

// ---------------------------------------------------------------------------
// Types (mirrored from frontend/src/pages/auth/signup-types.ts)
// ---------------------------------------------------------------------------

interface IntervalPricing {
  interval: string
  enabled: boolean
  discount_percent: number
  effective_price: number
  savings_amount: number
  equivalent_monthly: number
}

interface PublicPlan {
  id: string
  name: string
  monthly_price_nzd: number
  trial_duration: number
  trial_duration_unit: string
  intervals: IntervalPricing[]
}

interface SignupResponse {
  message: string
  requires_payment: boolean
  payment_amount_cents: number
  admin_email: string
  plan_amount_cents?: number
  gst_amount_cents?: number
  gst_percentage?: number
  processing_fee_cents?: number
  pending_signup_id?: string
  stripe_client_secret?: string
  plan_name?: string
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function validatePassword(password: string): string | undefined {
  if (!password || password.length < 8) return 'Password must be at least 8 characters'
  if (!/[A-Z]/.test(password)) return 'Must include an uppercase letter'
  if (!/[a-z]/.test(password)) return 'Must include a lowercase letter'
  if (!/\d/.test(password)) return 'Must include a number'
  if (!/[^A-Za-z0-9]/.test(password)) return 'Must include a special character'
  return undefined
}

// ---------------------------------------------------------------------------
// Step labels and progress dots
// ---------------------------------------------------------------------------

const STEPS = [
  { key: 'account', label: 'Account' },
  { key: 'plan', label: 'Plan' },
  { key: 'payment', label: 'Payment' },
  { key: 'done', label: 'Done' },
] as const

function ProgressDots({ current, total }: { current: number; total: number }) {
  return (
    <div
      className="flex items-center justify-center gap-2 py-4"
      role="navigation"
      aria-label="Signup progress"
    >
      {Array.from({ length: total }, (_, i) => {
        const done = i < current
        const active = i === current
        return (
          <div key={i} className="flex items-center gap-2">
            <div className="flex flex-col items-center">
              <div
                className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold transition-all ${
                  active
                    ? 'bg-blue-600 text-white scale-110 shadow-md'
                    : done
                      ? 'bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-300'
                      : 'bg-gray-200 text-gray-400 dark:bg-gray-700 dark:text-gray-500'
                }`}
                aria-current={active ? 'step' : undefined}
              >
                {done ? '✓' : i + 1}
              </div>
              <span
                className={`mt-1 text-[10px] ${
                  active
                    ? 'font-semibold text-blue-600 dark:text-blue-400'
                    : 'text-gray-400 dark:text-gray-500'
                }`}
              >
                {STEPS[i].label}
              </span>
            </div>
            {i < total - 1 && (
              <div
                className={`h-0.5 w-6 rounded ${
                  i < current
                    ? 'bg-blue-400 dark:bg-blue-600'
                    : 'bg-gray-200 dark:bg-gray-700'
                }`}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Stripe Card Form (Step 3 inner component)
// ---------------------------------------------------------------------------

interface StripeCardFormProps {
  clientSecret: string
  pendingSignupId: string
  planName: string
  paymentAmountCents: number
  planAmountCents?: number
  gstAmountCents?: number
  gstPercentage?: number
  processingFeeCents?: number
  onComplete: () => void
  onSessionExpired: (msg: string) => void
}

function StripeCardForm({
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
}: StripeCardFormProps) {
  const stripe = useStripe()
  const elements = useElements()
  const [processing, setProcessing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const amountDisplay = `$${((paymentAmountCents ?? 0) / 100).toFixed(2)} NZD`
  const hasBreakdown =
    planAmountCents !== undefined && gstAmountCents !== undefined

  async function callConfirmPayment(paymentIntentId: string) {
    try {
      await apiClient.post('/auth/signup/confirm-payment', {
        payment_intent_id: paymentIntentId,
        pending_signup_id: pendingSignupId,
      })
      onComplete()
    } catch (err: unknown) {
      const detail = (
        err as { response?: { data?: { detail?: string } } }
      )?.response?.data?.detail
      const message = detail ?? 'Failed to confirm payment. Please try again.'
      if (message.toLowerCase().includes('invalid or expired signup session')) {
        onSessionExpired(message)
        return
      }
      setError(message)
    }
  }

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

    const { error: stripeError, paymentIntent } =
      await stripe.confirmCardPayment(clientSecret, {
        payment_method: { card: cardElement },
      })

    if (stripeError) {
      setError(stripeError.message ?? 'Payment failed')
      setProcessing(false)
      return
    }

    if (paymentIntent?.status === 'succeeded') {
      await callConfirmPayment(paymentIntent.id)
    } else {
      setError('Payment was not completed. Please try again.')
    }
    setProcessing(false)
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      {error && (
        <div
          role="alert"
          className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
        >
          {error}
        </div>
      )}

      {/* Billing breakdown */}
      {hasBreakdown ? (
        <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm dark:border-gray-700 dark:bg-gray-800">
          <div className="flex justify-between text-gray-700 dark:text-gray-300">
            <span>{planName} plan</span>
            <span>${((planAmountCents ?? 0) / 100).toFixed(2)}</span>
          </div>
          <div className="mt-1 flex justify-between text-gray-700 dark:text-gray-300">
            <span>GST ({gstPercentage ?? 15}%)</span>
            <span>${((gstAmountCents ?? 0) / 100).toFixed(2)}</span>
          </div>
          {(processingFeeCents ?? 0) > 0 && (
            <div className="mt-1 flex justify-between text-gray-700 dark:text-gray-300">
              <span>Processing fee</span>
              <span>${((processingFeeCents ?? 0) / 100).toFixed(2)}</span>
            </div>
          )}
          <div className="mt-2 flex justify-between border-t border-gray-300 pt-2 font-semibold text-gray-900 dark:border-gray-600 dark:text-white">
            <span>Total</span>
            <span>{amountDisplay}</span>
          </div>
        </div>
      ) : (
        <p className="mb-4 text-sm text-gray-600 dark:text-gray-400">
          You will be charged <span className="font-semibold">{amountDisplay}</span>{' '}
          for the <span className="font-semibold">{planName}</span> plan.
        </p>
      )}

      {/* Stripe Card Element */}
      <div className="mb-4 rounded-lg border border-gray-300 bg-white p-3 dark:border-gray-600 dark:bg-gray-800">
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

      <p className="mb-4 text-xs text-gray-500 dark:text-gray-400">
        Your card will be charged immediately. You can cancel anytime from
        billing settings.
      </p>

      <Button
        type="submit"
        large
        disabled={!stripe || processing}
      >
        {processing ? 'Processing…' : `Pay ${amountDisplay}`}
      </Button>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Main SignupScreen component
// ---------------------------------------------------------------------------

export default function SignupScreen() {
  const navigate = useNavigate()

  // Current wizard step: 0=Account, 1=Plan, 2=Payment, 3=Done
  const [step, setStep] = useState(0)

  // Form data
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [orgName, setOrgName] = useState('')

  // Plan selection
  const [plans, setPlans] = useState<PublicPlan[]>([])
  const [plansLoading, setPlansLoading] = useState(true)
  const [plansError, setPlansError] = useState<string | null>(null)
  const [selectedPlanId, setSelectedPlanId] = useState('')

  // Stripe
  const [stripePromise, setStripePromise] = useState<Promise<Stripe | null> | null>(null)
  const [signupResult, setSignupResult] = useState<SignupResponse | null>(null)

  // CAPTCHA
  const [captchaUrl, setCaptchaUrl] = useState('')
  const [captchaCode, setCaptchaCode] = useState('')
  const [captchaVerified, setCaptchaVerified] = useState(false)
  const [captchaVerifying, setCaptchaVerifying] = useState(false)
  const [captchaError, setCaptchaError] = useState<string | null>(null)

  // General state
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Load Stripe publishable key and plans on mount
  useEffect(() => {
    const controller = new AbortController()

    async function init() {
      // Load Stripe key
      try {
        const res = await apiClient.get<{ publishable_key: string }>(
          '/auth/stripe-publishable-key',
          { signal: controller.signal },
        )
        if (res.data?.publishable_key) {
          setStripePromise(loadStripe(res.data.publishable_key))
        }
      } catch {
        /* Stripe not configured — payment step will show error */
      }

      // Load plans
      try {
        setPlansLoading(true)
        const res = await apiClient.get<{ plans: PublicPlan[] }>(
          '/auth/plans',
          { signal: controller.signal },
        )
        setPlans(res.data?.plans ?? [])
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          const status = (err as { response?: { status?: number } })?.response?.status
          setPlansError(
            status === 429
              ? 'Too many requests. Please wait and try again.'
              : 'Unable to load plans. Please try again later.',
          )
        }
      } finally {
        if (!controller.signal.aborted) setPlansLoading(false)
      }

      // Load CAPTCHA
      setCaptchaUrl(`/api/v1/auth/captcha?t=${Date.now()}`)
    }

    init()
    return () => controller.abort()
  }, [])

  function refreshCaptcha() {
    setCaptchaCode('')
    setCaptchaVerified(false)
    setCaptchaError(null)
    setCaptchaUrl(`/api/v1/auth/captcha?t=${Date.now()}`)
  }

  const verifyCaptcha = useCallback(async () => {
    if (captchaCode.length !== 6) {
      setCaptchaError('Please enter the 6-character code')
      return
    }
    setCaptchaVerifying(true)
    setCaptchaError(null)
    try {
      await apiClient.post('/auth/verify-captcha', { captcha_code: captchaCode })
      setCaptchaVerified(true)
    } catch (err: unknown) {
      setCaptchaVerified(false)
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setCaptchaError(detail ?? 'Failed to verify CAPTCHA. Please try again.')
      setTimeout(() => refreshCaptcha(), 2000)
    } finally {
      setCaptchaVerifying(false)
    }
  }, [captchaCode])

  const selectedPlan = useMemo(
    () => plans.find((p) => p.id === selectedPlanId) ?? null,
    [plans, selectedPlanId],
  )

  // Clear field error on change
  function clearError(field: string) {
    if (errors[field]) {
      setErrors((prev) => {
        const next = { ...prev }
        delete next[field]
        return next
      })
    }
  }

  // Step 1 validation
  function validateAccountStep(): boolean {
    const e: Record<string, string> = {}
    if (!firstName.trim()) e.firstName = 'First name is required'
    if (!lastName.trim()) e.lastName = 'Last name is required'
    if (!email.trim() || !EMAIL_REGEX.test(email)) e.email = 'Valid email is required'
    if (!orgName.trim()) e.orgName = 'Business name is required'
    const pwErr = validatePassword(password)
    if (pwErr) e.password = pwErr
    if (password !== confirmPassword) e.confirmPassword = 'Passwords do not match'
    if (!captchaVerified) e.captcha = 'Please verify the CAPTCHA first'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  // Step 2 validation
  function validatePlanStep(): boolean {
    const e: Record<string, string> = {}
    if (!selectedPlanId) e.plan = 'Please select a plan'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  function handleNext() {
    setApiError(null)
    if (step === 0) {
      if (validateAccountStep()) setStep(1)
    } else if (step === 1) {
      if (validatePlanStep()) handleSignup()
    }
  }

  function handleBack() {
    if (step > 0 && step < 3) {
      setStep((s) => s - 1)
      setErrors({})
      setApiError(null)
    }
  }

  // Submit signup to backend
  async function handleSignup() {
    setApiError(null)
    setIsSubmitting(true)

    try {
      const res = await apiClient.post<SignupResponse>('/auth/signup', {
        org_name: orgName.trim(),
        admin_email: email.trim(),
        admin_first_name: firstName.trim(),
        admin_last_name: lastName.trim(),
        password,
        plan_id: selectedPlanId,
        billing_interval: 'monthly',
        captcha_code: captchaCode,
        country_code: 'NZ',
      })

      setSignupResult(res.data ?? null)

      if (res.data?.requires_payment && res.data?.stripe_client_secret) {
        // Go to payment step
        setStep(2)
      } else if (res.data?.requires_payment && !res.data?.stripe_client_secret) {
        setApiError(
          'Payment is required but Stripe is not configured. Please contact support.',
        )
      } else {
        // No payment required (trial) — go to confirmation
        setStep(3)
      }
    } catch (err: unknown) {
      const detail = (
        err as { response?: { data?: { detail?: string } } }
      )?.response?.data?.detail
      setApiError(detail ?? 'Signup failed. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  function handlePaymentComplete() {
    setStep(3)
  }

  function handleSessionExpired(message: string) {
    setApiError(message)
    setStep(0)
    setSignupResult(null)
    refreshCaptcha()
  }

  return (
    <Page className="bg-white dark:bg-gray-900">
      {/* Hero gradient header */}
      <div className="bg-gradient-to-b from-slate-900 to-indigo-900 px-6 pb-8 pt-14 text-center">
        <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-white/10 backdrop-blur-sm">
          <SignupIcon />
        </div>
        <h1 className="text-2xl font-bold text-white">
          {step === 3 ? 'You\'re all set!' : 'Create Account'}
        </h1>
        <p className="mt-1 text-sm text-indigo-200">
          {step === 0 && 'Enter your details to get started'}
          {step === 1 && 'Choose the plan that works for you'}
          {step === 2 && 'Complete your payment'}
          {step === 3 && 'Check your email to verify'}
        </p>
      </div>

      <Block className="-mt-4 rounded-t-2xl bg-white pt-2 dark:bg-gray-900">
        {/* Progress dots */}
        <ProgressDots current={step} total={STEPS.length} />

        {/* API error banner */}
        {apiError && (
          <div
            role="alert"
            className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
          >
            {apiError}
          </div>
        )}

        {/* ── Step 1: Account ── */}
        {step === 0 && (
          <div>
            <List strongIos outlineIos className="-mx-4 mb-4">
              <ListInput
                label="First Name"
                type="text"
                placeholder="John"
                value={firstName}
                onInput={(e: React.ChangeEvent<HTMLInputElement>) => {
                  setFirstName(e.target.value)
                  clearError('firstName')
                }}
                error={errors.firstName}
                required
              />
              <ListInput
                label="Last Name"
                type="text"
                placeholder="Smith"
                value={lastName}
                onInput={(e: React.ChangeEvent<HTMLInputElement>) => {
                  setLastName(e.target.value)
                  clearError('lastName')
                }}
                error={errors.lastName}
                required
              />
              <ListInput
                label="Email"
                type="email"
                placeholder="you@example.com"
                value={email}
                onInput={(e: React.ChangeEvent<HTMLInputElement>) => {
                  setEmail(e.target.value)
                  clearError('email')
                }}
                error={errors.email}
                inputMode="email"
                autoComplete="email"
                autoCapitalize="none"
                required
              />
              <ListInput
                label="Password"
                type="password"
                placeholder="Min 8 characters"
                value={password}
                onInput={(e: React.ChangeEvent<HTMLInputElement>) => {
                  setPassword(e.target.value)
                  clearError('password')
                }}
                error={errors.password}
                autoComplete="new-password"
                required
              />
              <ListInput
                label="Confirm Password"
                type="password"
                placeholder="Re-enter password"
                value={confirmPassword}
                onInput={(e: React.ChangeEvent<HTMLInputElement>) => {
                  setConfirmPassword(e.target.value)
                  clearError('confirmPassword')
                }}
                error={errors.confirmPassword}
                autoComplete="new-password"
                required
              />
              <ListInput
                label="Business Name"
                type="text"
                placeholder="Your company name"
                value={orgName}
                onInput={(e: React.ChangeEvent<HTMLInputElement>) => {
                  setOrgName(e.target.value)
                  clearError('orgName')
                }}
                error={errors.orgName}
                required
              />
            </List>

            {/* CAPTCHA section */}
            <div className="mb-4 px-1">
              <p className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-300">
                Verification
              </p>
              <div className="flex items-start gap-3">
                <div className="flex-shrink-0">
                  {captchaUrl ? (
                    <img
                      src={captchaUrl}
                      alt="CAPTCHA"
                      className="h-12 cursor-pointer rounded-lg border border-gray-300 dark:border-gray-600"
                      onClick={refreshCaptcha}
                    />
                  ) : (
                    <div className="h-12 w-32 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
                  )}
                </div>
                <div className="flex-1 space-y-1">
                  <div className="flex gap-2">
                    <input
                      type="text"
                      maxLength={6}
                      value={captchaCode}
                      onChange={(e) => {
                        setCaptchaCode(e.target.value)
                        clearError('captcha')
                      }}
                      placeholder="Enter code"
                      disabled={captchaVerified}
                      className="w-28 rounded-lg border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
                    />
                    {!captchaVerified ? (
                      <Button
                        small
                        outline
                        onClick={verifyCaptcha}
                        disabled={captchaVerifying}
                      >
                        {captchaVerifying ? '…' : 'Verify'}
                      </Button>
                    ) : (
                      <span className="flex items-center text-sm font-medium text-green-600 dark:text-green-400">
                        ✓ Verified
                      </span>
                    )}
                  </div>
                  {captchaError && (
                    <p className="text-xs text-red-600 dark:text-red-400">{captchaError}</p>
                  )}
                  {errors.captcha && (
                    <p className="text-xs text-red-600 dark:text-red-400">{errors.captcha}</p>
                  )}
                  <button
                    type="button"
                    onClick={refreshCaptcha}
                    className="text-xs text-gray-500 active:text-gray-700 dark:text-gray-400"
                  >
                    Refresh image
                  </button>
                </div>
              </div>
            </div>

            <Button large onClick={handleNext} className="mb-3">
              Next
            </Button>
          </div>
        )}

        {/* ── Step 2: Plan Selection ── */}
        {step === 1 && (
          <div>
            {plansLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
              </div>
            ) : plansError ? (
              <div className="py-8 text-center">
                <p className="text-sm text-red-600 dark:text-red-400">{plansError}</p>
                <button
                  type="button"
                  onClick={() => window.location.reload()}
                  className="mt-2 text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400"
                >
                  Retry
                </button>
              </div>
            ) : (
              <div className="space-y-3 mb-4">
                {(plans ?? []).map((plan) => {
                  const isSelected = selectedPlanId === plan.id
                  const hasTrial = (plan.trial_duration ?? 0) > 0
                  const monthlyInterval = (plan.intervals ?? []).find(
                    (iv) => iv.interval === 'monthly' && iv.enabled,
                  )
                  const price = monthlyInterval
                    ? (monthlyInterval.effective_price ?? 0)
                    : Number(plan.monthly_price_nzd ?? 0)

                  return (
                    <button
                      key={plan.id}
                      type="button"
                      onClick={() => {
                        setSelectedPlanId(plan.id)
                        clearError('plan')
                      }}
                      className={`w-full rounded-xl border p-4 text-left transition-all ${
                        isSelected
                          ? 'border-blue-500 bg-blue-50 shadow-sm dark:border-blue-400 dark:bg-blue-900/30'
                          : 'border-gray-200 dark:border-gray-700'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div>
                          <span
                            className={`font-semibold ${
                              isSelected
                                ? 'text-blue-800 dark:text-blue-200'
                                : 'text-gray-900 dark:text-white'
                            }`}
                          >
                            {plan.name}
                          </span>
                          {hasTrial && (
                            <span className="ml-2 text-xs font-medium text-green-600 dark:text-green-400">
                              {plan.trial_duration} {plan.trial_duration_unit} free trial
                            </span>
                          )}
                          {!hasTrial && (
                            <span className="ml-2 text-xs font-medium text-amber-600 dark:text-amber-400">
                              Payment required upfront
                            </span>
                          )}
                        </div>
                        <div className="text-right">
                          <span className="text-sm font-semibold text-gray-900 dark:text-white">
                            ${(price ?? 0).toFixed(2)}/mo
                          </span>
                          {price > 0 && (
                            <span className="block text-xs text-gray-500 dark:text-gray-400">
                              excl. GST
                            </span>
                          )}
                        </div>
                      </div>
                    </button>
                  )
                })}
                {errors.plan && (
                  <p className="text-sm text-red-600 dark:text-red-400">{errors.plan}</p>
                )}
              </div>
            )}

            <div className="flex gap-3">
              <Button large outline onClick={handleBack} className="flex-1">
                Back
              </Button>
              <Button
                large
                onClick={handleNext}
                disabled={isSubmitting}
                className="flex-1"
              >
                {isSubmitting
                  ? 'Creating…'
                  : selectedPlan && (selectedPlan.trial_duration ?? 0) > 0
                    ? 'Start Free Trial'
                    : 'Sign Up'}
              </Button>
            </div>
          </div>
        )}

        {/* ── Step 3: Stripe Payment ── */}
        {step === 2 && signupResult && (
          <div>
            {!stripePromise ? (
              <div
                role="alert"
                className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
              >
                Stripe is not configured. Please contact support.
              </div>
            ) : signupResult.stripe_client_secret ? (
              <Elements
                stripe={stripePromise}
                options={{ clientSecret: signupResult.stripe_client_secret }}
              >
                <StripeCardForm
                  clientSecret={signupResult.stripe_client_secret}
                  pendingSignupId={signupResult.pending_signup_id ?? ''}
                  planName={
                    signupResult.plan_name ?? selectedPlan?.name ?? 'Selected'
                  }
                  paymentAmountCents={signupResult.payment_amount_cents ?? 0}
                  planAmountCents={signupResult.plan_amount_cents}
                  gstAmountCents={signupResult.gst_amount_cents}
                  gstPercentage={signupResult.gst_percentage}
                  processingFeeCents={signupResult.processing_fee_cents}
                  onComplete={handlePaymentComplete}
                  onSessionExpired={handleSessionExpired}
                />
              </Elements>
            ) : null}

            <div className="mt-4">
              <Button large outline onClick={handleBack}>
                Back
              </Button>
            </div>
          </div>
        )}

        {/* ── Step 4: Confirmation ── */}
        {step === 3 && (
          <div className="text-center">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-blue-100 dark:bg-blue-900/40">
              <svg
                className="h-8 w-8 text-blue-500"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                />
              </svg>
            </div>
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
              Check your email
            </h2>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
              We've sent a verification link to{' '}
              <span className="font-semibold">
                {signupResult?.admin_email ?? email}
              </span>
              . Click the link to verify your email and activate your account.
            </p>
            <p className="mt-2 text-xs text-gray-500 dark:text-gray-500">
              The link expires in 48 hours. Check your spam folder if you don't
              see it.
            </p>
            <Button
              large
              className="mt-6"
              onClick={() => navigate('/login')}
            >
              Go to Login
            </Button>
          </div>
        )}

        {/* Footer link */}
        {step < 3 && (
          <div className="mt-4 pb-8 text-center">
            <Link
              to="/login"
              className="text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400 dark:active:text-blue-300"
            >
              Already have an account? Log in
            </Link>
          </div>
        )}
      </Block>
    </Page>
  )
}

/** Signup icon for the hero section */
function SignupIcon() {
  return (
    <svg
      className="h-8 w-8 text-white"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="8.5" cy="7" r="4" />
      <line x1="20" y1="8" x2="20" y2="14" />
      <line x1="23" y1="11" x2="17" y2="11" />
    </svg>
  )
}
