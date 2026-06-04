import { useState, useEffect, FormEvent } from 'react'
import { loadStripe, type Stripe } from '@stripe/stripe-js'
import { Elements, CardElement, useStripe, useElements } from '@stripe/react-stripe-js'
import apiClient from '@/api/client'
import { Button, Input, AlertBanner, Spinner } from '@/components/ui'
import { CountrySelect } from '@/components/ui/CountrySelect'
import { validateSignupForm } from './signup-validation'
import { PasswordRequirements, PasswordMatch } from '@/components/auth/PasswordRequirements'
import type { SignupFormData, SignupResponse, PublicPlan, PublicPlanListResponse, TradeFamily } from './signup-types'

/**
 * Signup — single-page signup variant (Task 13 port of
 * frontend/src/pages/auth/Signup).
 *
 * ALL logic is copied verbatim from the original: the form/payment/done step
 * machine, deferred Stripe key load, plans + trade-families fetch (refetch on
 * country change), coupon validate/apply/remove + effective-price maths, the
 * CAPTCHA load/verify/refresh flow, the /auth/signup submit →
 * requires_payment branch, and the inline PaymentForm (Stripe
 * confirmCardPayment → /auth/signup/confirm-payment with organisation_id).
 * Styling is remapped to the design system; the page renders into the
 * AuthLayout `<Outlet/>` (the redundant per-page branding logo is dropped — the
 * layout owns the brand lockup). The routed /signup page is SignupWizard; this
 * variant is ported for parity per the task.
 */

// Trade family icons
const FAMILY_ICONS: Record<string, string> = {
  'automotive-transport': '🚗',
  'electrical-mechanical': '⚡',
  'plumbing-gas': '🔧',
  'building-construction': '🏗️',
  'landscaping-outdoor': '🌿',
  'cleaning-facilities': '🧹',
  'it-technology': '💻',
  'creative-professional': '🎨',
  'accounting-legal-financial': '📊',
  'health-wellness': '❤️',
  'food-hospitality': '🍽️',
  'retail': '🛍️',
  'hair-beauty-personal-care': '💇',
  'trades-support-hire': '🔨',
  'freelancing-contracting': '📋',
}

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
      <p className="text-[13.5px] text-muted">
        You will be charged <span className="font-semibold text-text">{amountDisplay}</span> for your first month on the <span className="font-semibold text-text">{planName}</span> plan.
      </p>
      <p className="text-[12px] text-muted-2">
        Your card will be charged immediately. You can cancel anytime from your billing settings.
      </p>
      <Button type="submit" loading={processing} disabled={!stripe} fullWidth>
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

  // Trade families state
  const [tradeFamilies, setTradeFamilies] = useState<TradeFamily[]>([])
  const [tradeFamiliesLoading, setTradeFamiliesLoading] = useState(true)

  const [formData, setFormData] = useState<SignupFormData>({
    org_name: '',
    admin_email: '',
    admin_first_name: '',
    admin_last_name: '',
    password: '',
    confirm_password: '',
    plan_id: '',
    billing_interval: 'monthly',
    captcha_code: '',
    coupon_code: '',
    country_code: 'NZ',
    trade_family_slug: '',
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
    fetchTradeFamilies()
    loadCaptcha()
  }, [])

  // Refetch trade families when country changes
  useEffect(() => {
    fetchTradeFamilies()
  }, [formData.country_code])

  async function fetchTradeFamilies() {
    setTradeFamiliesLoading(true)
    try {
      const countryParam = formData.country_code ? `?country_code=${formData.country_code}` : ''
      const res = await apiClient.get<{ families: TradeFamily[] } | TradeFamily[]>(`/api/v2/trade-families${countryParam}`)
      const data = res.data
      const families = Array.isArray(data) ? data : (data?.families ?? [])
      setTradeFamilies(families)
      if (formData.trade_family_slug && !families.some(f => f.slug === formData.trade_family_slug)) {
        setFormData(prev => ({ ...prev, trade_family_slug: '' }))
      }
    } catch {
      setTradeFamilies([])
    } finally {
      setTradeFamiliesLoading(false)
    }
  }

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
      setPlans(res.data?.plans ?? [])
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
    if (coupon.discount_type === 'fixed_amount') return `${dv.toFixed(2)} off/mo${duration}`
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
        country_code: formData.country_code || undefined,
        trade_family_slug: formData.trade_family_slug || undefined,
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
    return `${(cents / 100).toFixed(2)} NZD`
  }

  // ── Render ──

  // Done step
  if (step === 'done') {
    return (
      <div className="mx-auto w-full max-w-md py-12">
        <div className="rounded-card border border-accent/20 bg-accent-soft p-6 text-center">
          <svg className="mx-auto h-12 w-12 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
          <h2 className="mt-4 text-xl font-semibold text-text">
            Check your email
          </h2>
          <p className="mt-2 text-[13.5px] text-muted">
            We've sent a verification link to <span className="font-semibold text-text">{signupResult?.admin_email}</span>.
            Please click the link to verify your email and activate your account.
          </p>
          <p className="mt-3 text-[12px] text-muted-2">
            The link expires in 48 hours. Check your spam folder if you don't see it.
          </p>
          <a
            href="/login"
            className="mt-4 inline-block rounded-ctl bg-accent px-4 py-2 text-[13.5px] font-medium text-white hover:bg-accent-press"
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
        <div className="mx-auto w-full max-w-md py-12 text-center">
          <Spinner label="Loading payment..." />
        </div>
      )
    }

    if (!stripePromise) {
      return (
        <div className="mx-auto w-full max-w-md py-12">
          <AlertBanner variant="error">
            Stripe is not configured. Please contact support to complete your signup.
          </AlertBanner>
        </div>
      )
    }

    return (
      <div className="mx-auto w-full max-w-md py-12">
        <h1 className="text-2xl font-bold text-text">Complete payment</h1>
        <p className="mt-1 text-[13.5px] text-muted">
          Enter your card details to activate your <span className="font-semibold text-text">{pName}</span> plan.
        </p>
        <div className="mt-6">
          <Elements stripe={stripePromise} options={{ clientSecret: signupResult.stripe_client_secret! }}>
            <PaymentForm
              clientSecret={signupResult.stripe_client_secret!}
              organisationId={signupResult.organisation_id ?? signupResult.pending_signup_id ?? ''}
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
    <div className="mx-auto w-full max-w-lg py-12">
      <h1 className="text-2xl font-bold text-text">Create your account</h1>
      <p className="mt-1 text-[13.5px] text-muted">{subtitle}</p>

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

        {/* Country */}
        <CountrySelect
          label="Country"
          value={formData.country_code}
          onChange={code => handleFieldChange('country_code', code)}
          error={errors.country_code}
        />

        {/* Business Type / Trade Family */}
        <div>
          <label className="mb-1 block text-[12.5px] font-medium text-text">Business type</label>
          {tradeFamiliesLoading ? (
            <div className="flex h-[42px] items-center">
              <Spinner size="sm" label="Loading..." />
            </div>
          ) : tradeFamilies.length === 0 ? (
            <p className="text-[13.5px] text-muted-2">No business types available for this country</p>
          ) : (
            <div className="grid max-h-48 grid-cols-2 gap-2 overflow-y-auto p-1 sm:grid-cols-3">
              {tradeFamilies.map(family => {
                const icon = FAMILY_ICONS[family.slug] || '📦'
                const isSelected = formData.trade_family_slug === family.slug
                return (
                  <button
                    key={family.slug}
                    type="button"
                    onClick={() => handleFieldChange('trade_family_slug', isSelected ? '' : family.slug)}
                    className={`flex items-center gap-2 rounded-ctl border px-2 py-1.5 text-left text-[13px] transition-colors
                      focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent
                      ${isSelected
                        ? 'border-accent bg-accent-soft text-accent'
                        : 'border-border text-text hover:border-border-strong hover:bg-canvas'
                      }`}
                  >
                    <span className="text-base" aria-hidden="true">{icon}</span>
                    <span className="truncate text-[12px]">{family.display_name}</span>
                  </button>
                )
              })}
            </div>
          )}
          {errors.trade_family_slug && <p className="mt-1 text-[12.5px] text-danger">{errors.trade_family_slug}</p>}
        </div>

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
          <label className="mb-1 block text-[12.5px] font-medium text-text">Plan</label>
          {plansLoading ? (
            <Spinner size="sm" label="Loading plans..." />
          ) : plansError ? (
            <div className="text-[13.5px] text-danger">{plansError}
              <button type="button" onClick={fetchPlans} className="ml-2 text-accent underline">Retry</button>
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
                    className={`flex cursor-pointer items-center justify-between rounded-ctl border p-3 transition-colors ${
                      isSelected ? 'border-accent bg-accent-soft' : 'border-border hover:border-border-strong'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <input
                        type="radio"
                        name="plan_id"
                        value={plan.id}
                        checked={isSelected}
                        onChange={() => handleFieldChange('plan_id', plan.id)}
                        className="h-4 w-4 accent-accent"
                      />
                      <div>
                        <span className="font-medium text-text">{plan.name}</span>
                        {hasTrial && (
                          <span className="ml-2 text-[12px] font-medium text-ok">
                            {plan.trial_duration} {plan.trial_duration_unit} free trial
                          </span>
                        )}
                        {!hasTrial && (
                          <span className="ml-2 text-[12px] font-medium text-warn">
                            Payment required upfront
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="text-right">
                      {couponApplied && effectivePrice !== price ? (
                        <>
                          <span className="mono text-[13px] text-muted-2 line-through">${price.toFixed(2)}</span>
                          <span className="mono ml-1 text-[13px] font-semibold text-text">${effectivePrice.toFixed(2)}/mo</span>
                        </>
                      ) : (
                        <span className="mono text-[13px] font-semibold text-text">${price.toFixed(2)}/mo</span>
                      )}
                    </div>
                  </label>
                )
              })}
            </div>
          )}
          {errors.plan_id && <p className="mt-1 text-[12.5px] text-danger">{errors.plan_id}</p>}
        </div>

        {/* Coupon */}
        <div>
          {!showCouponInput ? (
            <button
              type="button"
              onClick={() => setShowCouponInput(true)}
              className="text-[13px] text-accent hover:underline"
            >
              Have a coupon code?
            </button>
          ) : (
            <div className="space-y-2">
              <label className="block text-[12.5px] font-medium text-text">Coupon code</label>
              {couponApplied ? (
                <div className="flex items-center justify-between rounded-ctl border border-ok/40 bg-ok-soft p-2">
                  <span className="text-[13px] text-ok">
                    {couponApplied.code} — {formatDiscountLabel(couponApplied)}
                  </span>
                  <button type="button" onClick={handleRemoveCoupon} className="text-[13px] text-danger hover:underline">
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
                    className="flex-1 rounded-ctl border border-border px-3 py-2 text-[13px] focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={handleApplyCoupon}
                    loading={couponValidating}
                  >
                    Apply
                  </Button>
                </div>
              )}
              {couponError && <p className="text-[13px] text-danger">{couponError}</p>}
            </div>
          )}
        </div>

        {/* CAPTCHA */}
        <div>
          <label className="mb-1 block text-[12.5px] font-medium text-text">Verification</label>
          <div className="flex items-start gap-3">
            <div className="flex-shrink-0">
              {captchaLoading ? (
                <div className="h-12 w-32 animate-pulse rounded bg-canvas" />
              ) : (
                <img
                  src={captchaUrl}
                  alt="CAPTCHA"
                  className="h-12 rounded-ctl border border-border"
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
                  className="w-28 rounded-ctl border border-border px-3 py-1.5 text-[13px] focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                  disabled={captchaVerified}
                />
                {!captchaVerified ? (
                  <Button type="button" variant="ghost" size="sm" onClick={verifyCaptcha} loading={captchaVerifying}>
                    Verify
                  </Button>
                ) : (
                  <span className="flex items-center text-[13px] text-ok">✓ Verified</span>
                )}
              </div>
              {captchaError && <p className="text-[12px] text-danger">{captchaError}</p>}
              {errors.captcha_code && <p className="text-[12px] text-danger">{errors.captcha_code}</p>}
              <button type="button" onClick={refreshCaptcha} className="text-[12px] text-muted hover:underline">
                Refresh image
              </button>
            </div>
          </div>
        </div>

        {/* Submit */}
        <Button type="submit" loading={submitting} fullWidth>
          {selectedPlan && selectedPlan.trial_duration > 0
            ? 'Start free trial'
            : 'Sign up'}
        </Button>

        <p className="text-center text-[13px] text-muted">
          Already have an account?{' '}
          <a href="/login" className="text-accent hover:underline">Log in</a>
        </p>
      </form>
    </div>
  )
}
