import { useState, useEffect, FormEvent } from 'react'
import { loadStripe, type Stripe } from '@stripe/stripe-js'
import { Elements, CardElement, useStripe, useElements } from '@stripe/react-stripe-js'
import apiClient from '@/api/client'
import { Button, Input, AlertBanner, Spinner } from '@/components/ui'
import { validateSignupForm } from './signup-validation'
import { PasswordRequirements, PasswordMatch } from '@/components/auth/PasswordRequirements'
import type { SignupFormData, SignupResponse, PublicPlan, PublicPlanListResponse } from './signup-types'

interface CouponResponse {
  id: string
  code: string
  description: string | null
  discount_type: 'percentage' | 'fixed_amount' | 'trial_extension'
  discount_value: number
  duration_months: number | null
  usage_limit: number | null
  times_redeemed: number
  is_active: boolean
  starts_at: string | null
  expires_at: string | null
  created_at: string
  updated_at: string
}

type Step = 'form' | 'payment' | 'done'

/* ── Payment Form (Stripe Elements — PaymentIntent) ── */
function PaymentForm({
  clientSecret,
  organisationId,
  planName,
  amountDisplay,
  onSuccess,
}: {
  clientSecret: string
  organisationId: string
  planName: string
  amountDisplay: string
  onSuccess: () => void
}) {
  const stripe = useStripe()
  const elements = useElements()
  const [processing, setProcessing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handlePayment(e: FormEvent) {
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
      try {
        await apiClient.post('/auth/signup/confirm-payment', {
          payment_intent_id: paymentIntent.id,
          organisation_id: organisationId,
        })
      } catch {
        // Payment succeeded on Stripe side — org will be activated eventually
      }
      onSuccess()
    } else {
      setError('Payment was not completed. Please try again.')
      setProcessing(false)
    }
  }

  return (
    <form onSubmit={handlePayment} className="space-y-4">
      {error && <AlertBanner variant="error">{error}</AlertBanner>}
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
      <p className="text-sm text-gray-600">
        You will be charged <span className="font-semibold">{amountDisplay}</span> for your first month on the <span className="font-semibold">{planName}</span> plan.
      </p>
      <p className="text-xs text-gray-500">
        Your card will be charged immediately. You can cancel anytime from your billing settings.
      </p>
      <Button type="submit" loading={processing} disabled={!stripe} className="w-full">
        Pay {amountDisplay} and activate
      </Button>
    </form>
  )
}

/* ── Main Signup Component ── */
export function Signup() {
  const [step, setStep] = useState<Step>('form')
  const [plans, setPlans] = useState<PublicPlan[]>([])
  const [plansLoading, setPlansLoading] = useState(true)
  const [plansError, setPlansError] = useState<string | null>(null)

  // Stripe
  const [stripePromise, setStripePromise] = useState<Promise<Stripe | null> | null>(null)
  const [stripeLoading, setStripeLoading] = useState(true)

  // Coupon state
  const [couponCode, setCouponCode] = useState('')
  const [couponApplied, setCouponApplied] = useState<CouponResponse | null>(null)
  const [couponError, setCouponError] = useState<string | null>(null)
  const [couponValidating, setCouponValidating] = useState(false)
  const [showCouponInput, setShowCouponInput] = useState(false)

  const [formData, setFormData] = useState<SignupFormData>({
    org_name: '',
    admin_email: '',
    admin_first_name: '',
    admin_last_name: '',
    password: '',
    confirm_password: '',
    plan_id: '',
    captcha_code: '',
    coupon_code: '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const [signupResult, setSignupResult] = useState<SignupResponse | null>(null)

  // Get selected plan for display
  const selectedPlan = plans.find(p => p.id === formData.plan_id)

  // CAPTCHA state
  const [captchaUrl, setCaptchaUrl] = useState<string>('')
  const [captchaLoading, setCaptchaLoading] = useState(false)
  const [captchaVerified, setCaptchaVerified] = useState(false)
  const [captchaVerifying, setCaptchaVerifying] = useState(false)
  const [captchaError, setCaptchaError] = useState<string | null>(null)

  // Load Stripe publishable key from the backend on mount
  useEffect(() => {
    async function loadStripeKey() {
      try {
        const res = await apiClient.get<{ publishable_key: string }>('/auth/stripe-publishable-key')
        if (res.data.publishable_key) {
          setStripePromise(loadStripe(res.data.publishable_key))
        }
      } catch {
        // Stripe not configured — payment step will show a fallback
      } finally {
        setStripeLoading(false)
      }
    }
    loadStripeKey()
    fetchPlans()
    loadCaptcha()
  }, [])

  async function loadCaptcha() {
    setCaptchaLoading(true)
    try {
      const timestamp = new Date().getTime()
      setCaptchaUrl(`/api/v1/auth/captcha?t=${timestamp}`)
    } catch (error) {
      console.error('Failed to load CAPTCHA:', error)
    } finally {
      setCaptchaLoading(false)
    }
  }

  function refreshCaptcha() {
    setFormData(prev => ({ ...prev, captcha_code: '' }))
    setCaptchaVerified(false)
    setCaptchaError(null)
    if (errors.captcha_code) {
      setErrors(prev => { const next = { ...prev }; delete next.captcha_code; return next })
    }
    loadCaptcha()
  }

  async function verifyCaptcha() {
    if (formData.captcha_code.length !== 6) {
      setCaptchaError('Please enter the 6-character code')
      return
    }
    setCaptchaVerifying(true)
    setCaptchaError(null)
    try {
      await apiClient.post('/auth/verify-captcha', { captcha_code: formData.captcha_code })
      setCaptchaVerified(true)
      setCaptchaError(null)
    } catch (err: unknown) {
      setCaptchaVerified(false)
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setCaptchaError(detail ?? 'Failed to verify CAPTCHA. Please try again.')
      setTimeout(() => refreshCaptcha(), 2000)
    } finally {
      setCaptchaVerifying(false)
    }
  }

  async function fetchPlans() {
    setPlansLoading(true)
    setPlansError(null)
    try {
      const res = await apiClient.get<PublicPlanListResponse>('/auth/plans')
      setPlans(res.data.plans)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      setPlansError(status === 429
        ? 'Too many requests. Please wait a moment and try again.'
        : 'Unable to load plans. Please try again later.')
    } finally {
      setPlansLoading(false)
    }
  }

  async function handleApplyCoupon() {
    if (!couponCode.trim()) return
    setCouponError(null)
    setCouponValidating(true)
    try {
      const res = await apiClient.post<{ valid: boolean; coupon?: CouponResponse; error?: string }>(
        '/coupons/validate', { code: couponCode.trim() }
      )
      if (res.data.valid && res.data.coupon) {
        setCouponApplied(res.data.coupon)
      } else {
        setCouponError(res.data.error || 'Invalid coupon code')
        setCouponApplied(null)
      }
    } catch {
      setCouponError('Network error. Please try again.')
      setCouponApplied(null)
    } finally {
      setCouponValidating(false)
    }
  }

  function handleRemoveCoupon() {
    setCouponApplied(null)
    setCouponCode('')
    setCouponError(null)
  }

  function formatDiscountLabel(coupon: CouponResponse): string {
    const duration = coupon.duration_months
      ? ` for ${coupon.duration_months} month${coupon.duration_months > 1 ? 's' : ''}`
      : ''
    const dv = Number(coupon.discount_value)
    if (coupon.discount_type === 'percentage') return `${dv}% off${duration}`
    if (coupon.discount_type === 'fixed_amount') return `$${dv.toFixed(2)} off/mo${duration}`
    return `+${dv} days free trial`
  }

  function calculateEffectivePrice(planPrice: number, coupon: CouponResponse): number {
    const dv = Number(coupon.discount_value)
    if (coupon.discount_type === 'percentage') return Math.round(planPrice * (1 - dv / 100) * 100) / 100
    if (coupon.discount_type === 'fixed_amount') return Math.round(Math.max(0, planPrice - dv) * 100) / 100
    return planPrice
  }

  function handleFieldChange(field: keyof SignupFormData, value: string) {
    setFormData(prev => ({ ...prev, [field]: value }))
    if (errors[field]) {
      setErrors(prev => { const next = { ...prev }; delete next[field]; return next })
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setApiError(null)

    const validationErrors = validateSignupForm(formData)
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors)
      return
    }

    if (!captchaVerified) {
      setErrors({ captcha_code: 'Please verify the CAPTCHA first' })
      return
    }

    setSubmitting(true)
    try {
      const res = await apiClient.post<SignupResponse>('/auth/signup', {
        ...formData,
        confirm_password: undefined,
        coupon_code: couponApplied?.code || undefined,
      })
      setSignupResult(res.data)

      if (res.data.requires_payment && res.data.stripe_client_secret) {
        // No trial — go to payment step
        setStep('payment')
      } else if (res.data.requires_payment && !res.data.stripe_client_secret) {
        // Stripe not configured — show error
        setApiError('Payment is required but Stripe is not configured. Please contact support.')
      } else {
        // Trial plan — go straight to done
        setStep('done')
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setApiError(detail ?? 'Signup failed. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  function formatPrice(cents: number): string {
    return `$${(cents / 100).toFixed(2)} NZD`
  }

  // ── Render ──

  // Done step
  if (step === 'done') {
    return (
      <div className="mx-auto max-w-md py-12 px-4">
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-6 text-center">
          <svg className="mx-auto h-12 w-12 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
          <h2 className="mt-4 text-xl font-semibold text-gray-900">
            Check your email
          </h2>
          <p className="mt-2 text-sm text-gray-600">
            We've sent a verification link to <span className="font-semibold">{signupResult?.admin_email}</span>.
            Please click the link to verify your email and activate your account.
          </p>
          <p className="mt-3 text-xs text-gray-500">
            The link expires in 48 hours. Check your spam folder if you don't see it.
          </p>
          <a
            href="/login"
            className="mt-4 inline-block rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Go to login
          </a>
        </div>
      </div>
    )
  }

  // Payment step
  if (step === 'payment' && signupResult) {
    const amountDisplay = formatPrice(signupResult.payment_amount_cents)
    const pName = selectedPlan?.name ?? 'Selected'

    if (stripeLoading) {
      return (
        <div className="mx-auto max-w-md py-12 px-4 text-center">
          <Spinner label="Loading payment..." />
        </div>
      )
    }

    if (!stripePromise) {
      return (
        <div className="mx-auto max-w-md py-12 px-4">
          <AlertBanner variant="error">
            Stripe is not configured. Please contact support to complete your signup.
          </AlertBanner>
        </div>
      )
    }

    return (
      <div className="mx-auto max-w-md py-12 px-4">
        <h1 className="text-2xl font-bold text-gray-900">Complete payment</h1>
        <p className="mt-1 text-sm text-gray-600">
          Enter your card details to activate your <span className="font-semibold">{pName}</span> plan.
        </p>
        <div className="mt-6">
          <Elements stripe={stripePromise} options={{ clientSecret: signupResult.stripe_client_secret! }}>
            <PaymentForm
              clientSecret={signupResult.stripe_client_secret!}
              organisationId={signupResult.organisation_id}
              planName={pName}
              amountDisplay={amountDisplay}
              onSuccess={() => setStep('done')}
            />
          </Elements>
        </div>
      </div>
    )
  }

  // Form step
  const subtitle = selectedPlan && selectedPlan.trial_duration > 0
    ? 'Start your free trial'
    : 'Get started'

  return (
    <div className="mx-auto max-w-lg py-12 px-4">
      <h1 className="text-2xl font-bold text-gray-900">Create your account</h1>
      <p className="mt-1 text-sm text-gray-600">{subtitle}</p>

      {apiError && (
        <div className="mt-4">
          <AlertBanner variant="error">{apiError}</AlertBanner>
        </div>
      )}

      <form onSubmit={handleSubmit} className="mt-6 space-y-4">
        {/* Organisation name */}
        <Input
          label="Organisation name"
          value={formData.org_name}
          onChange={e => handleFieldChange('org_name', e.target.value)}
          error={errors.org_name}
          required
        />

        {/* Name row */}
        <div className="grid grid-cols-2 gap-3">
          <Input
            label="First name"
            value={formData.admin_first_name}
            onChange={e => handleFieldChange('admin_first_name', e.target.value)}
            error={errors.admin_first_name}
            required
          />
          <Input
            label="Last name"
            value={formData.admin_last_name}
            onChange={e => handleFieldChange('admin_last_name', e.target.value)}
            error={errors.admin_last_name}
            required
          />
        </div>

        {/* Email */}
        <Input
          label="Email"
          type="email"
          value={formData.admin_email}
          onChange={e => handleFieldChange('admin_email', e.target.value)}
          error={errors.admin_email}
          required
        />

        {/* Password */}
        <div>
          <Input
            label="Password"
            type="password"
            value={formData.password}
            onChange={e => handleFieldChange('password', e.target.value)}
            error={errors.password}
            required
          />
          <PasswordRequirements password={formData.password} />
        </div>

        {/* Confirm Password */}
        <div>
          <Input
            label="Confirm password"
            type="password"
            value={formData.confirm_password}
            onChange={e => handleFieldChange('confirm_password', e.target.value)}
            error={errors.confirm_password}
            required
          />
          <PasswordMatch password={formData.password} confirmPassword={formData.confirm_password} />
        </div>

        {/* Plan selector */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Plan</label>
          {plansLoading ? (
            <Spinner size="sm" label="Loading plans..." />
          ) : plansError ? (
            <div className="text-sm text-red-600">{plansError}
              <button type="button" onClick={fetchPlans} className="ml-2 text-blue-600 underline">Retry</button>
            </div>
          ) : (
            <div className="space-y-2">
              {plans.map(plan => {
                const isSelected = formData.plan_id === plan.id
                const hasTrial = plan.trial_duration > 0
                const price = Number(plan.monthly_price_nzd)
                const effectivePrice = couponApplied
                  ? calculateEffectivePrice(price, couponApplied)
                  : price
                return (
                  <label
                    key={plan.id}
                    className={`flex items-center justify-between rounded-md border p-3 cursor-pointer transition-colors ${
                      isSelected ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <input
                        type="radio"
                        name="plan_id"
                        value={plan.id}
                        checked={isSelected}
                        onChange={() => handleFieldChange('plan_id', plan.id)}
                        className="h-4 w-4 text-blue-600"
                      />
                      <div>
                        <span className="font-medium text-gray-900">{plan.name}</span>
                        {hasTrial && (
                          <span className="ml-2 text-xs text-green-600 font-medium">
                            {plan.trial_duration} {plan.trial_duration_unit} free trial
                          </span>
                        )}
                        {!hasTrial && (
                          <span className="ml-2 text-xs text-amber-600 font-medium">
                            Payment required upfront
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="text-right">
                      {couponApplied && effectivePrice !== price ? (
                        <>
                          <span className="text-sm text-gray-400 line-through">${price.toFixed(2)}</span>
                          <span className="ml-1 text-sm font-semibold text-gray-900">${effectivePrice.toFixed(2)}/mo</span>
                        </>
                      ) : (
                        <span className="text-sm font-semibold text-gray-900">${price.toFixed(2)}/mo</span>
                      )}
                    </div>
                  </label>
                )
              })}
            </div>
          )}
          {errors.plan_id && <p className="mt-1 text-sm text-red-600">{errors.plan_id}</p>}
        </div>

        {/* Coupon */}
        <div>
          {!showCouponInput ? (
            <button
              type="button"
              onClick={() => setShowCouponInput(true)}
              className="text-sm text-blue-600 hover:underline"
            >
              Have a coupon code?
            </button>
          ) : (
            <div className="space-y-2">
              <label className="block text-sm font-medium text-gray-700">Coupon code</label>
              {couponApplied ? (
                <div className="flex items-center justify-between rounded-md border border-green-300 bg-green-50 p-2">
                  <span className="text-sm text-green-700">
                    {couponApplied.code} — {formatDiscountLabel(couponApplied)}
                  </span>
                  <button type="button" onClick={handleRemoveCoupon} className="text-sm text-red-600 hover:underline">
                    Remove
                  </button>
                </div>
              ) : (
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={couponCode}
                    onChange={e => setCouponCode(e.target.value.toUpperCase())}
                    placeholder="Enter code"
                    className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm"
                  />
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={handleApplyCoupon}
                    loading={couponValidating}
                  >
                    Apply
                  </Button>
                </div>
              )}
              {couponError && <p className="text-sm text-red-600">{couponError}</p>}
            </div>
          )}
        </div>

        {/* CAPTCHA */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Verification</label>
          <div className="flex items-start gap-3">
            <div className="flex-shrink-0">
              {captchaLoading ? (
                <div className="h-12 w-32 animate-pulse rounded bg-gray-200" />
              ) : (
                <img
                  src={captchaUrl}
                  alt="CAPTCHA"
                  className="h-12 rounded border border-gray-300"
                  onClick={refreshCaptcha}
                  style={{ cursor: 'pointer' }}
                />
              )}
            </div>
            <div className="flex-1 space-y-1">
              <div className="flex gap-2">
                <input
                  type="text"
                  maxLength={6}
                  value={formData.captcha_code}
                  onChange={e => handleFieldChange('captcha_code', e.target.value)}
                  placeholder="Enter code"
                  className="w-28 rounded-md border border-gray-300 px-3 py-1.5 text-sm"
                  disabled={captchaVerified}
                />
                {!captchaVerified ? (
                  <Button type="button" variant="secondary" size="sm" onClick={verifyCaptcha} loading={captchaVerifying}>
                    Verify
                  </Button>
                ) : (
                  <span className="flex items-center text-sm text-green-600">✓ Verified</span>
                )}
              </div>
              {captchaError && <p className="text-xs text-red-600">{captchaError}</p>}
              {errors.captcha_code && <p className="text-xs text-red-600">{errors.captcha_code}</p>}
              <button type="button" onClick={refreshCaptcha} className="text-xs text-gray-500 hover:underline">
                Refresh image
              </button>
            </div>
          </div>
        </div>

        {/* Submit */}
        <Button type="submit" loading={submitting} className="w-full">
          {selectedPlan && selectedPlan.trial_duration > 0
            ? 'Start free trial'
            : 'Sign up'}
        </Button>

        <p className="text-center text-sm text-gray-500">
          Already have an account?{' '}
          <a href="/login" className="text-blue-600 hover:underline">Log in</a>
        </p>
      </form>
    </div>
  )
}
