import { useState, useEffect, useMemo, type FormEvent } from 'react'
import apiClient from '@/api/client'
import { Button, Input, AlertBanner, Spinner } from '@/components/ui'
import { CountrySelect } from '@/components/ui/CountrySelect'
import { validateSignupForm } from './signup-validation'
import { PasswordRequirements, PasswordMatch } from '@/components/auth/PasswordRequirements'
import { IntervalSelector } from '@/components/billing/IntervalSelector'
import type { SignupFormData, SignupResponse, PublicPlan, PublicPlanListResponse, SignupBillingConfig, IntervalPricing, TradeFamily } from './signup-types'

/**
 * SignupForm — reusable signup form component (Task 13 port of
 * frontend/src/pages/auth/SignupForm).
 *
 * ALL logic is copied verbatim from the original: the plans + trade-families +
 * signup-config fetch (refetch trade families on country change), the
 * IntervalSelector wiring + per-interval pricing/savings maths, coupon
 * validate/apply/remove, the CAPTCHA load/verify/refresh flow, validation and
 * the /auth/signup submit that delegates to `onComplete(result, plan)`. Styling
 * is remapped to the design tokens.
 */

// Trade family icons (same as TradeStep.tsx)
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

interface SignupFormProps {
  onComplete: (result: SignupResponse, plan: PublicPlan | null) => void
}

export function SignupForm({ onComplete }: SignupFormProps) {
  const [plans, setPlans] = useState<PublicPlan[]>([])
  const [plansLoading, setPlansLoading] = useState(true)
  const [plansError, setPlansError] = useState<string | null>(null)
  const [, setBillingConfig] = useState<SignupBillingConfig | null>(null)

  // Trade families state
  const [tradeFamilies, setTradeFamilies] = useState<TradeFamily[]>([])
  const [tradeFamiliesLoading, setTradeFamiliesLoading] = useState(true)

  // Coupon state
  const [couponCode, setCouponCode] = useState('')
  const [couponApplied, setCouponApplied] = useState<CouponResponse | null>(null)
  const [couponError, setCouponError] = useState<string | null>(null)
  const [couponValidating, setCouponValidating] = useState(false)
  const [showCouponInput, setShowCouponInput] = useState(false)

  const [selectedInterval, setSelectedInterval] = useState('monthly')

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

  // Get selected plan for display
  const selectedPlan = plans.find(p => p.id === formData.plan_id) ?? null

  // Collect all unique enabled intervals across all plans for the IntervalSelector
  const availableIntervals = useMemo<IntervalPricing[]>(() => {
    const intervalMap = new Map<string, IntervalPricing>()
    for (const plan of plans) {
      for (const iv of plan.intervals ?? []) {
        if (iv.enabled && !intervalMap.has(iv.interval)) {
          intervalMap.set(iv.interval, iv)
        }
      }
    }
    return Array.from(intervalMap.values())
  }, [plans])

  // CAPTCHA state
  const [captchaUrl, setCaptchaUrl] = useState<string>('')
  const [captchaLoading, setCaptchaLoading] = useState(false)
  const [captchaVerified, setCaptchaVerified] = useState(false)
  const [captchaVerifying, setCaptchaVerifying] = useState(false)
  const [captchaError, setCaptchaError] = useState<string | null>(null)

  useEffect(() => {
    fetchPlans()
    fetchTradeFamilies()
    loadCaptcha()
    apiClient.get('/auth/signup-config').then(res => setBillingConfig(res.data)).catch(() => {})
  }, [])

  // Refetch trade families when country changes
  useEffect(() => {
    fetchTradeFamilies()
  }, [formData.country_code])

  async function fetchTradeFamilies() {
    setTradeFamiliesLoading(true)
    try {
      // Fetch trade families filtered by selected country
      const countryParam = formData.country_code ? `?country_code=${formData.country_code}` : ''
      const res = await apiClient.get<{ families: TradeFamily[] } | TradeFamily[]>(`/api/v2/trade-families${countryParam}`)
      const data = res.data
      const families = Array.isArray(data) ? data : (data?.families ?? [])
      setTradeFamilies(families)
      // Clear selection if current selection is no longer available
      if (formData.trade_family_slug && !families.some(f => f.slug === formData.trade_family_slug)) {
        setFormData(prev => ({ ...prev, trade_family_slug: '' }))
      }
    } catch {
      // Non-critical, just leave empty
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

  function handleIntervalChange(interval: string) {
    setSelectedInterval(interval)
    setFormData(prev => ({ ...prev, billing_interval: interval }))
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
      onComplete(res.data, selectedPlan)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setApiError(detail ?? 'Signup failed. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const subtitle = selectedPlan && selectedPlan.trial_duration > 0
    ? 'Start your free trial'
    : 'Get started'

  return (
    <div>
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
            <div className="space-y-3">
              {/* Interval selector above plan cards */}
              {availableIntervals.length > 1 && (
                <div className="flex justify-center">
                  <IntervalSelector
                    intervals={availableIntervals}
                    selected={selectedInterval}
                    onChange={handleIntervalChange}
                    recommendedInterval="monthly"
                  />
                </div>
              )}

              <div className="space-y-2">
                {plans.map(plan => {
                  const isSelected = formData.plan_id === plan.id
                  const hasTrial = plan.trial_duration > 0
                  const planIntervals = plan.intervals ?? []
                  const intervalPricing = planIntervals.find(
                    (iv) => iv.interval === selectedInterval && iv.enabled
                  )
                  const isUnavailable = !intervalPricing

                  // Use interval effective_price if available, otherwise fall back to monthly_price_nzd
                  const displayPrice = intervalPricing
                    ? (intervalPricing.effective_price ?? 0)
                    : Number(plan.monthly_price_nzd ?? 0)
                  const discountPercent = intervalPricing?.discount_percent ?? 0
                  const savingsAmount = intervalPricing?.savings_amount ?? 0
                  const equivalentMonthly = intervalPricing?.equivalent_monthly ?? 0

                  // Apply coupon on top of interval price
                  const effectivePrice = couponApplied
                    ? calculateEffectivePrice(displayPrice, couponApplied)
                    : displayPrice

                  // Compute coupon-adjusted equivalent monthly for non-monthly intervals
                  const PERIODS_PER_YEAR: Record<string, number> = {
                    weekly: 52,
                    fortnightly: 26,
                    monthly: 12,
                    annual: 1,
                  }
                  const couponAdjustedEquivMonthly = couponApplied && effectivePrice !== displayPrice
                    ? Math.round((effectivePrice * (PERIODS_PER_YEAR[selectedInterval] ?? 12) / 12) * 100) / 100
                    : equivalentMonthly

                  // Interval label suffix
                  const intervalSuffix: Record<string, string> = {
                    weekly: '/wk',
                    fortnightly: '/2wk',
                    monthly: '/mo',
                    annual: '/yr',
                  }
                  const priceSuffix = intervalSuffix[selectedInterval] ?? '/mo'

                  return (
                    <label
                      key={plan.id}
                      className={`flex items-center justify-between rounded-ctl border p-3 transition-colors ${
                        isUnavailable
                          ? 'cursor-not-allowed border-border bg-canvas opacity-60'
                          : isSelected
                            ? 'cursor-pointer border-accent bg-accent-soft'
                            : 'cursor-pointer border-border hover:border-border-strong'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <input
                          type="radio"
                          name="plan_id"
                          value={plan.id}
                          checked={isSelected}
                          disabled={isUnavailable}
                          onChange={() => handleFieldChange('plan_id', plan.id)}
                          className="h-4 w-4 accent-accent"
                        />
                        <div>
                          <span className={`font-medium ${isUnavailable ? 'text-muted-2' : 'text-text'}`}>
                            {plan.name}
                          </span>
                          {hasTrial && !isUnavailable && (
                            <span className="ml-2 text-[12px] font-medium text-ok">
                              {plan.trial_duration} {plan.trial_duration_unit} free trial
                            </span>
                          )}
                          {!hasTrial && !isUnavailable && (
                            <span className="ml-2 text-[12px] font-medium text-warn">
                              Payment required upfront
                            </span>
                          )}
                          {isUnavailable && (
                            <span className="ml-2 text-[12px] text-muted-2">
                              Not available for {selectedInterval} billing
                            </span>
                          )}
                        </div>
                      </div>
                      {!isUnavailable && (
                        <div className="text-right">
                          {/* Savings badge */}
                          {discountPercent > 0 && (
                            <span className="mb-0.5 inline-block rounded-full bg-ok-soft px-2 py-0.5 text-[10px] font-semibold text-ok">
                              Save {discountPercent}%
                            </span>
                          )}

                          {couponApplied && effectivePrice !== displayPrice ? (
                            <>
                              <span className="mono text-[13px] text-muted-2 line-through">
                                ${(displayPrice ?? 0).toFixed(2)}
                              </span>
                              <span className="mono ml-1 text-[13px] font-semibold text-text">
                                ${(effectivePrice ?? 0).toFixed(2)}{priceSuffix}
                              </span>
                              <span className="block text-[12px] text-muted">excl. GST</span>
                            </>
                          ) : (
                            <>
                              <span className="mono text-[13px] font-semibold text-text">
                                ${(displayPrice ?? 0).toFixed(2)}{priceSuffix}
                              </span>
                              {displayPrice > 0 && (
                                <span className="block text-[12px] text-muted">excl. GST</span>
                              )}
                            </>
                          )}

                          {/* Savings amount */}
                          {savingsAmount > 0 && (
                            <span className="block text-[12px] text-ok">
                              You save ${(savingsAmount ?? 0).toFixed(2)}{priceSuffix}
                            </span>
                          )}

                          {/* Equivalent monthly cost for non-monthly intervals */}
                          {selectedInterval !== 'monthly' && couponAdjustedEquivMonthly > 0 && (
                            <span className="block text-[12px] text-muted-2">
                              ${(couponAdjustedEquivMonthly ?? 0).toFixed(2)}/mo equivalent
                            </span>
                          )}
                        </div>
                      )}
                    </label>
                  )
                })}
              </div>
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
