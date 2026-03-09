import { useState, useEffect, FormEvent } from 'react'
import apiClient from '@/api/client'
import { Button, Input, AlertBanner, Spinner } from '@/components/ui'
import { validateSignupForm } from './signup-validation'
import type { SignupFormData, SignupResponse, PublicPlan, PublicPlanListResponse } from './signup-types'

type Step = 'form' | 'done'

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
    password: '',
    plan_id: '',
    captcha_code: '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // signup_token stored for potential future use (e.g. resuming signup)
  const [_signupToken, setSignupToken] = useState<string | null>(null)

  // Get selected plan for trial display
  const selectedPlan = plans.find(p => p.id === formData.plan_id)

  // CAPTCHA state
  const [captchaUrl, setCaptchaUrl] = useState<string>('')
  const [captchaLoading, setCaptchaLoading] = useState(false)
  const [captchaVerified, setCaptchaVerified] = useState(false)
  const [captchaVerifying, setCaptchaVerifying] = useState(false)
  const [captchaError, setCaptchaError] = useState<string | null>(null)

  useEffect(() => {
    fetchPlans()
    loadCaptcha()
  }, [])

  async function loadCaptcha() {
    setCaptchaLoading(true)
    try {
      // Add timestamp to prevent caching
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
      setErrors(prev => {
        const next = { ...prev }
        delete next.captcha_code
        return next
      })
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
      // Make a test request to verify CAPTCHA
      await apiClient.post('/auth/verify-captcha', {
        captcha_code: formData.captcha_code
      })
      
      // Success!
      setCaptchaVerified(true)
      setCaptchaError(null)
    } catch (err: unknown) {
      setCaptchaVerified(false)
      if (
        err &&
        typeof err === 'object' &&
        'response' in err &&
        (err as { response?: { status?: number; data?: { detail?: string } } }).response?.status === 400
      ) {
        const detail = (err as { response: { data: { detail?: string } } }).response.data.detail
        setCaptchaError(detail ?? 'Invalid CAPTCHA code')
      } else {
        setCaptchaError('Failed to verify CAPTCHA. Please try again.')
      }
      // Auto-refresh CAPTCHA on error
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
      console.error('Failed to fetch plans:', err)
      if (
        err &&
        typeof err === 'object' &&
        'response' in err &&
        (err as { response?: { status?: number } }).response?.status === 429
      ) {
        setPlansError('Too many requests. Please wait a moment and try again.')
      } else {
        setPlansError('Unable to load plans. Please try again later.')
      }
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
      // Signup complete - user can now login
      setStep('done')
    } catch (err: unknown) {
      if (
        err &&
        typeof err === 'object' &&
        'response' in err &&
        (err as { response?: { status?: number; data?: { detail?: string } } }).response?.status === 400
      ) {
        const detail = (err as { response: { data: { detail?: string } } }).response.data.detail
        
        // Check if it's a CAPTCHA error
        if (detail && detail.toLowerCase().includes('captcha')) {
          setApiError(detail)
          // Refresh CAPTCHA on error
          refreshCaptcha()
        } else {
          setApiError(detail ?? 'Signup failed. Please check your details.')
        }
      } else {
        setApiError('Something went wrong. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  function handleFieldChange(field: keyof SignupFormData, value: string) {
    setFormData((prev) => ({ ...prev, [field]: value }))
    
    // Reset CAPTCHA verification when code changes
    if (field === 'captcha_code') {
      setCaptchaVerified(false)
      setCaptchaError(null)
    }
    
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
          <h1 className="text-2xl font-bold text-gray-900">Account created successfully!</h1>
          <p className="text-gray-600">
            Your trial has started. You can now log in with your email and password.
          </p>
          <Button
            onClick={() => window.location.href = '/login'}
            className="w-full"
          >
            Go to login
          </Button>
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
            {selectedPlan && selectedPlan.trial_duration > 0
              ? `Start your ${selectedPlan.trial_duration}-${selectedPlan.trial_duration_unit} free trial`
              : 'Start your free trial'}
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

              <Input
                label="Password"
                type="password"
                autoComplete="new-password"
                required
                value={formData.password}
                onChange={(e) => handleFieldChange('password', e.target.value)}
                error={errors.password}
                placeholder="At least 8 characters"
              />

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

              {/* CAPTCHA */}
              <div className="flex flex-col gap-2">
                <label className="text-sm font-medium text-gray-700">
                  Verification code
                </label>
                <div className="flex items-start gap-3">
                  <div className="flex-shrink-0">
                    {captchaLoading ? (
                      <div className="flex h-20 w-48 items-center justify-center bg-gray-100 rounded border border-gray-300">
                        <Spinner size="sm" />
                      </div>
                    ) : captchaUrl ? (
                      <img
                        src={captchaUrl}
                        alt="CAPTCHA verification code"
                        className="h-20 w-48 rounded border border-gray-300 object-cover"
                        onError={() => {
                          console.error('Failed to load CAPTCHA image')
                          refreshCaptcha()
                        }}
                      />
                    ) : (
                      <div className="flex h-20 w-48 items-center justify-center bg-gray-100 rounded border border-gray-300 text-sm text-gray-500">
                        Loading...
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={refreshCaptcha}
                    className="text-sm text-blue-600 hover:text-blue-700 underline mt-1"
                    disabled={captchaLoading}
                  >
                    Refresh
                  </button>
                </div>
                
                {captchaVerified ? (
                  <div className="flex items-center gap-2 p-3 bg-green-50 border border-green-200 rounded-md animate-fadeIn">
                    <svg className="w-5 h-5 text-green-600 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                    </svg>
                    <span className="text-sm font-medium text-green-800">CAPTCHA verified successfully!</span>
                  </div>
                ) : (
                  <>
                    <div className="flex gap-2">
                      <Input
                        label=""
                        type="text"
                        required
                        value={formData.captcha_code}
                        onChange={(e) => handleFieldChange('captcha_code', e.target.value.toUpperCase())}
                        error={errors.captcha_code || captchaError || undefined}
                        placeholder="Enter 6-character code"
                        maxLength={6}
                        className="flex-1"
                      />
                      <Button
                        type="button"
                        onClick={verifyCaptcha}
                        loading={captchaVerifying}
                        disabled={formData.captcha_code.length !== 6 || captchaVerifying}
                        variant="secondary"
                        className="mt-0"
                      >
                        Verify
                      </Button>
                    </div>
                    {captchaError && (
                      <p className="text-sm text-red-600">{captchaError}</p>
                    )}
                  </>
                )}
              </div>

              <Button 
                type="submit" 
                loading={submitting} 
                disabled={!captchaVerified}
                className="w-full"
              >
                Sign up
              </Button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
