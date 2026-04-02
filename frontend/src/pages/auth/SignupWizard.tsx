import { useState, useEffect, useMemo, FormEvent, useRef } from 'react'
import { loadStripe, type Stripe } from '@stripe/stripe-js'
import apiClient from '@/api/client'
import { Button, Input, AlertBanner, Spinner } from '@/components/ui'
import { CountrySelect } from '@/components/ui/CountrySelect'
import { IntervalSelector } from '@/components/billing/IntervalSelector'
import { validateSignupForm } from './signup-validation'
import { PasswordRequirements, PasswordMatch } from '@/components/auth/PasswordRequirements'
import { PaymentStep } from './PaymentStep'
import { ConfirmationStep } from './ConfirmationStep'
import { usePlatformBranding } from '@/contexts/PlatformBrandingContext'
import type {
  SignupFormData, SignupResponse, PublicPlan, PublicPlanListResponse,
  IntervalPricing, TradeFamily,
} from './signup-types'

export type WizardStep = 'form' | 'payment' | 'done'

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

/* ── Step labels for the progress indicator ── */
const FORM_STEPS = [
  { key: 'welcome', label: 'Welcome' },
  { key: 'business', label: 'Business' },
  { key: 'plan', label: 'Plan' },
  { key: 'security', label: 'Security' },
] as const
type FormCard = (typeof FORM_STEPS)[number]['key']

function StepDots({ steps, current }: { steps: readonly { key: string; label: string }[]; current: number; total: number }) {
  return (
    <div className="flex items-center justify-center gap-2 mb-6" role="navigation" aria-label="Signup progress">
      {steps.map((s, i) => {
        const done = i < current
        const active = i === current
        return (
          <div key={s.key} className="flex items-center gap-2">
            <div className="flex flex-col items-center">
              <div
                className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold transition-all duration-300 ${
                  active ? 'bg-blue-600 text-white scale-110 shadow-md' : done ? 'bg-blue-100 text-blue-600' : 'bg-gray-200 text-gray-400'
                }`}
                aria-current={active ? 'step' : undefined}
              >
                {done ? '✓' : i + 1}
              </div>
              <span className={`mt-1 text-[10px] transition-colors duration-200 ${active ? 'font-semibold text-blue-600' : 'text-gray-400'}`}>
                {s.label}
              </span>
            </div>
            {i < steps.length - 1 && (
              <div className={`h-0.5 w-8 rounded transition-colors duration-300 ${i < current ? 'bg-blue-400' : 'bg-gray-200'}`} />
            )}
          </div>
        )
      })}
    </div>
  )
}

export function SignupWizard() {
  const { branding } = usePlatformBranding()

  /* ── Wizard-level state ── */
  const [wizardStep, setWizardStep] = useState<WizardStep>('form')
  const [cardIndex, setCardIndex] = useState(0)
  const [slideDir, setSlideDir] = useState<'left' | 'right'>('left')
  const [animating, setAnimating] = useState(false)
  const cardRef = useRef<HTMLDivElement>(null)

  const [signupResult, setSignupResult] = useState<SignupResponse | null>(null)
  const [selectedPlanObj, setSelectedPlanObj] = useState<PublicPlan | null>(null)
  const [resetMessage, setResetMessage] = useState<string | null>(null)

  /* ── Stripe ── */
  const [stripePromise, setStripePromise] = useState<Promise<Stripe | null> | null>(null)

  /* ── Form data (declared early so functions below can reference it) ── */
  const [formData, setFormData] = useState<SignupFormData>({
    org_name: '', admin_email: '', admin_first_name: '', admin_last_name: '',
    password: '', confirm_password: '', plan_id: '', billing_interval: 'monthly',
    captcha_code: '', coupon_code: '', country_code: 'NZ', trade_family_slug: '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    async function loadStripeKey() {
      try {
        const res = await apiClient.get<{ publishable_key: string }>('/auth/stripe-publishable-key')
        if (res.data.publishable_key) setStripePromise(loadStripe(res.data.publishable_key))
      } catch { /* Stripe not configured */ }
    }
    loadStripeKey()
    fetchPlans()
    fetchTradeFamilies()
    loadCaptcha()
  }, [])

  /* ── Plans ── */
  const [plans, setPlans] = useState<PublicPlan[]>([])
  const [plansLoading, setPlansLoading] = useState(true)
  const [plansError, setPlansError] = useState<string | null>(null)
  const [selectedInterval, setSelectedInterval] = useState('monthly')

  const availableIntervals = useMemo<IntervalPricing[]>(() => {
    const map = new Map<string, IntervalPricing>()
    for (const p of plans) for (const iv of p.intervals ?? []) if (iv.enabled && !map.has(iv.interval)) map.set(iv.interval, iv)
    return Array.from(map.values())
  }, [plans])

  async function fetchPlans() {
    setPlansLoading(true); setPlansError(null)
    try {
      const res = await apiClient.get<PublicPlanListResponse>('/auth/plans')
      setPlans(res.data?.plans ?? [])
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      setPlansError(status === 429 ? 'Too many requests. Please wait a moment and try again.' : 'Unable to load plans. Please try again later.')
    } finally { setPlansLoading(false) }
  }

  /* ── Trade families ── */
  const [tradeFamilies, setTradeFamilies] = useState<TradeFamily[]>([])
  const [tradeFamiliesLoading, setTradeFamiliesLoading] = useState(true)

  async function fetchTradeFamilies() {
    setTradeFamiliesLoading(true)
    try {
      const countryParam = formData.country_code ? `?country_code=${formData.country_code}` : ''
      const res = await apiClient.get<{ families: TradeFamily[] } | TradeFamily[]>(`/api/v2/trade-families${countryParam}`)
      const data = res.data
      const families = Array.isArray(data) ? data : (data?.families ?? [])
      setTradeFamilies(families)
      if (formData.trade_family_slug && !families.some(f => f.slug === formData.trade_family_slug))
        setFormData(prev => ({ ...prev, trade_family_slug: '' }))
    } catch { setTradeFamilies([]) }
    finally { setTradeFamiliesLoading(false) }
  }

  useEffect(() => { fetchTradeFamilies() }, [formData.country_code])

  /* ── Coupon ── */
  const [couponCode, setCouponCode] = useState('')
  const [couponApplied, setCouponApplied] = useState<CouponResponse | null>(null)
  const [couponError, setCouponError] = useState<string | null>(null)
  const [couponValidating, setCouponValidating] = useState(false)
  const [showCouponInput, setShowCouponInput] = useState(false)

  async function handleApplyCoupon() {
    if (!couponCode.trim()) return
    setCouponError(null); setCouponValidating(true)
    try {
      const res = await apiClient.post<{ valid: boolean; coupon?: CouponResponse; error?: string }>('/coupons/validate', { code: couponCode.trim() })
      if (res.data.valid && res.data.coupon) setCouponApplied(res.data.coupon)
      else { setCouponError(res.data.error || 'Invalid coupon code'); setCouponApplied(null) }
    } catch { setCouponError('Network error. Please try again.'); setCouponApplied(null) }
    finally { setCouponValidating(false) }
  }
  function handleRemoveCoupon() { setCouponApplied(null); setCouponCode(''); setCouponError(null) }
  function formatDiscountLabel(c: CouponResponse): string {
    const dur = c.duration_months ? ` for ${c.duration_months} month${c.duration_months > 1 ? 's' : ''}` : ''
    const dv = Number(c.discount_value)
    if (c.discount_type === 'percentage') return `${dv}% off${dur}`
    if (c.discount_type === 'fixed_amount') return `${dv.toFixed(2)} off/mo${dur}`
    return `+${dv} days free trial`
  }
  function calculateEffectivePrice(price: number, c: CouponResponse): number {
    const dv = Number(c.discount_value)
    if (c.discount_type === 'percentage') return Math.round(price * (1 - dv / 100) * 100) / 100
    if (c.discount_type === 'fixed_amount') return Math.round(Math.max(0, price - dv) * 100) / 100
    return price
  }

  /* ── CAPTCHA ── */
  const [captchaUrl, setCaptchaUrl] = useState('')
  const [captchaLoading, setCaptchaLoading] = useState(false)
  const [captchaVerified, setCaptchaVerified] = useState(false)
  const [captchaVerifying, setCaptchaVerifying] = useState(false)
  const [captchaError, setCaptchaError] = useState<string | null>(null)

  function loadCaptcha() {
    setCaptchaLoading(true)
    setCaptchaUrl(`/api/v1/auth/captcha?t=${Date.now()}`)
    setCaptchaLoading(false)
  }
  function refreshCaptcha() {
    setFormData(prev => ({ ...prev, captcha_code: '' }))
    setCaptchaVerified(false); setCaptchaError(null)
    if (errors.captcha_code) setErrors(prev => { const n = { ...prev }; delete n.captcha_code; return n })
    loadCaptcha()
  }
  async function verifyCaptcha() {
    if (formData.captcha_code.length !== 6) { setCaptchaError('Please enter the 6-character code'); return }
    setCaptchaVerifying(true); setCaptchaError(null)
    try {
      await apiClient.post('/auth/verify-captcha', { captcha_code: formData.captcha_code })
      setCaptchaVerified(true); setCaptchaError(null)
    } catch (err: unknown) {
      setCaptchaVerified(false)
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setCaptchaError(detail ?? 'Failed to verify CAPTCHA. Please try again.')
      setTimeout(() => refreshCaptcha(), 2000)
    } finally { setCaptchaVerifying(false) }
  }

  const selectedPlan = plans.find(p => p.id === formData.plan_id) ?? null

  function handleFieldChange(field: keyof SignupFormData, value: string) {
    setFormData(prev => ({ ...prev, [field]: value }))
    if (errors[field]) setErrors(prev => { const n = { ...prev }; delete n[field]; return n })
  }
  function handleIntervalChange(interval: string) {
    setSelectedInterval(interval)
    setFormData(prev => ({ ...prev, billing_interval: interval }))
  }

  /* ── Card navigation ── */
  function goNext() {
    if (animating) return
    setSlideDir('left'); setAnimating(true)
    setTimeout(() => { setCardIndex(i => i + 1); setAnimating(false) }, 300)
  }
  function goBack() {
    if (animating || cardIndex === 0) return
    setSlideDir('right'); setAnimating(true)
    setTimeout(() => { setCardIndex(i => i - 1); setAnimating(false) }, 300)
  }

  /* ── Per-card validation ── */
  function validateCard(card: FormCard): boolean {
    const e: Record<string, string> = {}
    if (card === 'welcome') {
      if (!formData.country_code) e.country_code = 'Please select a country'
    }
    if (card === 'business') {
      if (!formData.org_name || formData.org_name.length < 1) e.org_name = 'Organisation name is required'
      if (!formData.admin_first_name) e.admin_first_name = 'First name is required'
      if (!formData.admin_last_name) e.admin_last_name = 'Last name is required'
      if (!formData.admin_email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.admin_email)) e.admin_email = 'Valid email is required'
    }
    if (card === 'plan') {
      if (!formData.plan_id) e.plan_id = 'Please select a plan'
    }
    setErrors(e)
    return Object.keys(e).length === 0
  }

  function handleNext() {
    const card = FORM_STEPS[cardIndex].key
    if (!validateCard(card)) return
    goNext()
  }

  /* ── Submit ── */
  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setApiError(null)
    const validationErrors = validateSignupForm(formData)
    if (Object.keys(validationErrors).length > 0) { setErrors(validationErrors); return }
    if (!captchaVerified) { setErrors({ captcha_code: 'Please verify the CAPTCHA first' }); return }

    setSubmitting(true)
    try {
      const res = await apiClient.post<SignupResponse>('/auth/signup', {
        ...formData, confirm_password: undefined,
        coupon_code: couponApplied?.code || undefined,
        country_code: formData.country_code || undefined,
        trade_family_slug: formData.trade_family_slug || undefined,
      })
      setSignupResult(res.data)
      setSelectedPlanObj(selectedPlan)
      if (res.data.requires_payment && res.data.stripe_client_secret) setWizardStep('payment')
      else if (res.data.requires_payment && !res.data.stripe_client_secret) setApiError('Payment is required but Stripe is not configured. Please contact support.')
      else setWizardStep('done')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setApiError(detail ?? 'Signup failed. Please try again.')
    } finally { setSubmitting(false) }
  }

  function handlePaymentComplete() { setWizardStep('done') }
  function handleResetToForm(message?: string) { setWizardStep('form'); setSignupResult(null); setCardIndex(0); setResetMessage(message ?? null) }

  /* ── Animation class ── */
  const animClass = animating
    ? slideDir === 'left'
      ? 'translate-x-[-100%] opacity-0'
      : 'translate-x-[100%] opacity-0'
    : 'translate-x-0 opacity-100'

  /* ── Payment step ── */
  if (wizardStep === 'payment' && signupResult) {
    return (
      <div className="mx-auto max-w-lg py-12 px-4">
        {branding.logo_url && <img src={branding.logo_url} alt={branding.platform_name} className="mx-auto h-12 mb-4 object-contain" />}
        <div className="bg-white rounded-2xl shadow-lg border border-gray-100 p-8">
          {signupResult.stripe_client_secret && signupResult.pending_signup_id && (
            <PaymentStep
              pendingSignupId={signupResult.pending_signup_id}
              clientSecret={signupResult.stripe_client_secret}
              planName={signupResult.plan_name ?? selectedPlanObj?.name ?? 'Selected'}
              paymentAmountCents={signupResult.payment_amount_cents}
              planAmountCents={signupResult.plan_amount_cents}
              gstAmountCents={signupResult.gst_amount_cents}
              gstPercentage={signupResult.gst_percentage}
              processingFeeCents={signupResult.processing_fee_cents}
              stripePromise={stripePromise}
              onComplete={handlePaymentComplete}
              onSessionExpired={(msg) => handleResetToForm(msg)}
            />
          )}
        </div>
      </div>
    )
  }

  /* ── Confirmation step ── */
  if (wizardStep === 'done') {
    return (
      <div className="mx-auto max-w-lg py-12 px-4">
        {branding.logo_url && <img src={branding.logo_url} alt={branding.platform_name} className="mx-auto h-12 mb-4 object-contain" />}
        <ConfirmationStep email={signupResult?.admin_email ?? ''} />
      </div>
    )
  }

  /* ── Form cards ── */
  return (
    <div className="mx-auto max-w-lg py-12 px-4">
      {branding.logo_url && <img src={branding.logo_url} alt={branding.platform_name} className="mx-auto h-12 mb-6 object-contain" />}

      <StepDots steps={FORM_STEPS} current={cardIndex} total={FORM_STEPS.length} />

      {resetMessage && (
        <AlertBanner variant="warning" onDismiss={() => setResetMessage(null)} className="mb-4">
          {resetMessage}
        </AlertBanner>
      )}
      {apiError && <div className="mb-4"><AlertBanner variant="error">{apiError}</AlertBanner></div>}

      <div className="overflow-hidden">
        <div ref={cardRef} className={`transition-all duration-300 ease-in-out ${animClass}`}>
          <div className="bg-white rounded-2xl shadow-lg border border-gray-100 p-8">

            {/* ── Card 1: Welcome — Country & Trade Family ── */}
            {cardIndex === 0 && (
              <div>
                <div className="text-center mb-6">
                  <h1 className="text-2xl font-bold text-gray-900">Welcome 👋</h1>
                  <p className="mt-1 text-sm text-gray-500">Let's get you set up. Where is your business based?</p>
                </div>

                <div className="space-y-5">
                  <CountrySelect
                    label="Country"
                    value={formData.country_code}
                    onChange={code => handleFieldChange('country_code', code)}
                    error={errors.country_code}
                  />

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">What type of business do you run?</label>
                    {tradeFamiliesLoading ? (
                      <div className="h-[42px] flex items-center"><Spinner size="sm" label="Loading..." /></div>
                    ) : tradeFamilies.length === 0 ? (
                      <p className="text-sm text-gray-400">No business types available for this country</p>
                    ) : (
                      <div className="grid grid-cols-2 gap-2 max-h-64 overflow-y-auto p-1">
                        {tradeFamilies.map(family => {
                          const icon = FAMILY_ICONS[family.slug] || '📦'
                          const sel = formData.trade_family_slug === family.slug
                          return (
                            <button key={family.slug} type="button"
                              onClick={() => handleFieldChange('trade_family_slug', sel ? '' : family.slug)}
                              className={`flex items-center gap-2 rounded-lg border px-3 py-2.5 text-left text-sm transition-all duration-150
                                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
                                ${sel ? 'border-blue-500 bg-blue-50 text-blue-800 shadow-sm' : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50 text-gray-700'}`}
                            >
                              <span className="text-lg flex-shrink-0" aria-hidden="true">{icon}</span>
                              <span className="text-xs font-medium leading-tight">{family.display_name}</span>
                            </button>
                          )
                        })}
                      </div>
                    )}
                    {errors.trade_family_slug && <p className="mt-1 text-sm text-red-600">{errors.trade_family_slug}</p>}
                  </div>
                </div>

                <div className="mt-8 flex justify-end">
                  <Button onClick={handleNext} className="px-8">Next →</Button>
                </div>
              </div>
            )}

            {/* ── Card 2: Business Details ── */}
            {cardIndex === 1 && (
              <div>
                <div className="text-center mb-6">
                  <h1 className="text-2xl font-bold text-gray-900">Business details</h1>
                  <p className="mt-1 text-sm text-gray-500">Tell us about your organisation</p>
                </div>

                <div className="space-y-4">
                  <Input label="Organisation name" value={formData.org_name}
                    onChange={e => handleFieldChange('org_name', e.target.value)} error={errors.org_name} required />
                  <div className="grid grid-cols-2 gap-3">
                    <Input label="First name" value={formData.admin_first_name}
                      onChange={e => handleFieldChange('admin_first_name', e.target.value)} error={errors.admin_first_name} required />
                    <Input label="Last name" value={formData.admin_last_name}
                      onChange={e => handleFieldChange('admin_last_name', e.target.value)} error={errors.admin_last_name} required />
                  </div>
                  <Input label="Email" type="email" value={formData.admin_email}
                    onChange={e => handleFieldChange('admin_email', e.target.value)} error={errors.admin_email} required />
                </div>

                <div className="mt-8 flex justify-between">
                  <Button variant="secondary" onClick={goBack}>← Back</Button>
                  <Button onClick={handleNext} className="px-8">Next →</Button>
                </div>
              </div>
            )}

            {/* ── Card 3: Plan Selection & Coupon ── */}
            {cardIndex === 2 && (
              <div>
                <div className="text-center mb-6">
                  <h1 className="text-2xl font-bold text-gray-900">Choose your plan</h1>
                  <p className="mt-1 text-sm text-gray-500">Select the plan that works for you</p>
                </div>

                {plansLoading ? (
                  <div className="py-8 text-center"><Spinner size="sm" label="Loading plans..." /></div>
                ) : plansError ? (
                  <div className="text-sm text-red-600">{plansError}
                    <button type="button" onClick={fetchPlans} className="ml-2 text-blue-600 underline">Retry</button>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {availableIntervals.length > 1 && (
                      <div className="flex justify-center">
                        <IntervalSelector intervals={availableIntervals} selected={selectedInterval}
                          onChange={handleIntervalChange} recommendedInterval="monthly" />
                      </div>
                    )}
                    <div className="space-y-2">
                      {plans.map(plan => {
                        const isSelected = formData.plan_id === plan.id
                        const hasTrial = plan.trial_duration > 0
                        const planIntervals = plan.intervals ?? []
                        const intervalPricing = planIntervals.find(iv => iv.interval === selectedInterval && iv.enabled)
                        const isUnavailable = !intervalPricing
                        const displayPrice = intervalPricing ? (intervalPricing.effective_price ?? 0) : Number(plan.monthly_price_nzd ?? 0)
                        const discountPercent = intervalPricing?.discount_percent ?? 0
                        const savingsAmount = intervalPricing?.savings_amount ?? 0
                        const equivalentMonthly = intervalPricing?.equivalent_monthly ?? 0
                        const effectivePrice = couponApplied ? calculateEffectivePrice(displayPrice, couponApplied) : displayPrice
                        const PERIODS: Record<string, number> = { weekly: 52, fortnightly: 26, monthly: 12, annual: 1 }
                        const couponEquivMonthly = couponApplied && effectivePrice !== displayPrice
                          ? Math.round((effectivePrice * (PERIODS[selectedInterval] ?? 12) / 12) * 100) / 100 : equivalentMonthly
                        const suffix: Record<string, string> = { weekly: '/wk', fortnightly: '/2wk', monthly: '/mo', annual: '/yr' }
                        const priceSuffix = suffix[selectedInterval] ?? '/mo'

                        return (
                          <label key={plan.id}
                            className={`flex items-center justify-between rounded-lg border p-4 transition-all duration-150 ${
                              isUnavailable ? 'border-gray-200 bg-gray-50 opacity-60 cursor-not-allowed'
                                : isSelected ? 'border-blue-500 bg-blue-50 shadow-sm cursor-pointer'
                                : 'border-gray-200 hover:border-gray-300 hover:shadow-sm cursor-pointer'
                            }`}>
                            <div className="flex items-center gap-3">
                              <input type="radio" name="plan_id" value={plan.id} checked={isSelected} disabled={isUnavailable}
                                onChange={() => handleFieldChange('plan_id', plan.id)} className="h-4 w-4 text-blue-600" />
                              <div>
                                <span className={`font-medium ${isUnavailable ? 'text-gray-400' : 'text-gray-900'}`}>{plan.name}</span>
                                {hasTrial && !isUnavailable && <span className="ml-2 text-xs text-green-600 font-medium">{plan.trial_duration} {plan.trial_duration_unit} free trial</span>}
                                {!hasTrial && !isUnavailable && <span className="ml-2 text-xs text-amber-600 font-medium">Payment required upfront</span>}
                                {isUnavailable && <span className="ml-2 text-xs text-gray-400">Not available for {selectedInterval} billing</span>}
                              </div>
                            </div>
                            {!isUnavailable && (
                              <div className="text-right">
                                {discountPercent > 0 && <span className="inline-block mb-0.5 rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-semibold text-green-700">Save {discountPercent}%</span>}
                                {couponApplied && effectivePrice !== displayPrice ? (
                                  <>
                                    <span className="text-sm text-gray-400 line-through">${(displayPrice ?? 0).toFixed(2)}</span>
                                    <span className="ml-1 text-sm font-semibold text-gray-900">${(effectivePrice ?? 0).toFixed(2)}{priceSuffix}</span>
                                    <span className="block text-xs text-gray-500">excl. GST</span>
                                  </>
                                ) : (
                                  <>
                                    <span className="text-sm font-semibold text-gray-900">${(displayPrice ?? 0).toFixed(2)}{priceSuffix}</span>
                                    {displayPrice > 0 && <span className="block text-xs text-gray-500">excl. GST</span>}
                                  </>
                                )}
                                {savingsAmount > 0 && <span className="block text-xs text-green-600">You save ${(savingsAmount ?? 0).toFixed(2)}{priceSuffix}</span>}
                                {selectedInterval !== 'monthly' && couponEquivMonthly > 0 && <span className="block text-xs text-gray-400">${(couponEquivMonthly ?? 0).toFixed(2)}/mo equivalent</span>}
                              </div>
                            )}
                          </label>
                        )
                      })}
                    </div>
                    {errors.plan_id && <p className="mt-1 text-sm text-red-600">{errors.plan_id}</p>}

                    {/* Coupon */}
                    <div className="pt-2">
                      {!showCouponInput ? (
                        <button type="button" onClick={() => setShowCouponInput(true)} className="text-sm text-blue-600 hover:underline">Have a coupon code?</button>
                      ) : (
                        <div className="space-y-2">
                          <label className="block text-sm font-medium text-gray-700">Coupon code</label>
                          {couponApplied ? (
                            <div className="flex items-center justify-between rounded-lg border border-green-300 bg-green-50 p-3">
                              <span className="text-sm text-green-700">{couponApplied.code} — {formatDiscountLabel(couponApplied)}</span>
                              <button type="button" onClick={handleRemoveCoupon} className="text-sm text-red-600 hover:underline">Remove</button>
                            </div>
                          ) : (
                            <div className="flex gap-2">
                              <input type="text" value={couponCode} onChange={e => setCouponCode(e.target.value.toUpperCase())}
                                placeholder="Enter code" className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm" />
                              <Button type="button" variant="secondary" size="sm" onClick={handleApplyCoupon} loading={couponValidating}>Apply</Button>
                            </div>
                          )}
                          {couponError && <p className="text-sm text-red-600">{couponError}</p>}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                <div className="mt-8 flex justify-between">
                  <Button variant="secondary" onClick={goBack}>← Back</Button>
                  <Button onClick={handleNext} className="px-8">Next →</Button>
                </div>
              </div>
            )}

            {/* ── Card 4: Password, CAPTCHA & Sign Up ── */}
            {cardIndex === 3 && (
              <form onSubmit={handleSubmit}>
                <div className="text-center mb-6">
                  <h1 className="text-2xl font-bold text-gray-900">Secure your account</h1>
                  <p className="mt-1 text-sm text-gray-500">Set a strong password and verify you're human</p>
                </div>

                <div className="space-y-4">
                  <div>
                    <Input label="Password" type="password" value={formData.password}
                      onChange={e => handleFieldChange('password', e.target.value)} error={errors.password} required />
                    <PasswordRequirements password={formData.password} />
                  </div>
                  <div>
                    <Input label="Confirm password" type="password" value={formData.confirm_password}
                      onChange={e => handleFieldChange('confirm_password', e.target.value)} error={errors.confirm_password} required />
                    <PasswordMatch password={formData.password} confirmPassword={formData.confirm_password} />
                  </div>

                  {/* CAPTCHA */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Verification</label>
                    <div className="flex items-start gap-3">
                      <div className="flex-shrink-0">
                        {captchaLoading ? (
                          <div className="h-12 w-32 animate-pulse rounded bg-gray-200" />
                        ) : (
                          <img src={captchaUrl} alt="CAPTCHA" className="h-12 rounded-lg border border-gray-300 cursor-pointer"
                            onClick={refreshCaptcha} />
                        )}
                      </div>
                      <div className="flex-1 space-y-1">
                        <div className="flex gap-2">
                          <input type="text" maxLength={6} value={formData.captcha_code}
                            onChange={e => handleFieldChange('captcha_code', e.target.value)}
                            placeholder="Enter code" className="w-28 rounded-lg border border-gray-300 px-3 py-1.5 text-sm"
                            disabled={captchaVerified} />
                          {!captchaVerified ? (
                            <Button type="button" variant="secondary" size="sm" onClick={verifyCaptcha} loading={captchaVerifying}>Verify</Button>
                          ) : (
                            <span className="flex items-center text-sm text-green-600 font-medium">✓ Verified</span>
                          )}
                        </div>
                        {captchaError && <p className="text-xs text-red-600">{captchaError}</p>}
                        {errors.captcha_code && <p className="text-xs text-red-600">{errors.captcha_code}</p>}
                        <button type="button" onClick={refreshCaptcha} className="text-xs text-gray-500 hover:underline">Refresh image</button>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="mt-8 flex justify-between">
                  <Button type="button" variant="secondary" onClick={goBack}>← Back</Button>
                  <Button type="submit" loading={submitting} className="px-8">
                    {selectedPlan && selectedPlan.trial_duration > 0 ? 'Start free trial' : 'Sign up'}
                  </Button>
                </div>
              </form>
            )}

          </div>{/* end card */}
        </div>{/* end animation wrapper */}
      </div>{/* end overflow-hidden */}

      <p className="text-center text-sm text-gray-500 mt-6">
        Already have an account?{' '}
        <a href="/login" className="text-blue-600 hover:underline font-medium">Log in</a>
      </p>
    </div>
  )
}
