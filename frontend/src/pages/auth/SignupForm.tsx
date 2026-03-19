import { useState, useEffect, FormEvent } from 'react'
import apiClient from '@/api/client'
import { Button, Input, AlertBanner, Spinner } from '@/components/ui'
import { validateSignupForm } from './signup-validation'
import { PasswordRequirements, PasswordMatch } from '@/components/auth/PasswordRequirements'
import type { SignupFormData, SignupResponse, PublicPlan, PublicPlanListResponse, SignupBillingConfig } from './signup-types'

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
  const [billingConfig, setBillingConfig] = useState<SignupBillingConfig | null>(null)

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

  // Get selected plan for display
  const selectedPlan = plans.find(p => p.id === formData.plan_id) ?? null

  // CAPTCHA state
  const [captchaUrl, setCaptchaUrl] = useState<string>('')
  const [captchaLoading, setCaptchaLoading] = useState(false)
  const [captchaVerified, setCaptchaVerified] = useState(false)
  const [captchaVerifying, setCaptchaVerifying] = useState(false)
  const [captchaError, setCaptchaError] = useState<string | null>(null)

  useEffect(() => {
    fetchPlans()
    loadCaptcha()
    apiClient.get('/auth/signup-config').then(res => setBillingConfig(res.data)).catch(() => {})
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
                          <span className="block text-xs text-gray-500">excl. GST</span>
                        </>
                      ) : (
                        <>
                          <span className="text-sm font-semibold text-gray-900">${price.toFixed(2)}/mo</span>
                          {price > 0 && <span className="block text-xs text-gray-500">excl. GST</span>}
                        </>
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
