import { useState, useEffect, FormEvent } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import apiClient, { setAccessToken } from '@/api/client'
import { Button, Input, AlertBanner, Spinner } from '@/components/ui'
import { validateVerifyEmailForm } from './signup-validation'
import { PasswordRequirements, PasswordMatch } from '@/components/auth/PasswordRequirements'
import type { VerifyEmailResponse } from './signup-types'

export function VerifyEmail() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token')
  const type = searchParams.get('type') // 'signup' for signup verification

  // Signup verification state
  const [verifying, setVerifying] = useState(false)
  const [verified, setVerified] = useState(false)
  const [apiError, setApiError] = useState<string | null>(null)

  // Resend verification state
  const [resendEmail, setResendEmail] = useState('')
  const [resending, setResending] = useState(false)
  const [resendSuccess, setResendSuccess] = useState(false)
  const [resendError, setResendError] = useState<string | null>(null)

  // Invitation verification state (set password flow)
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)

  // Auto-verify for signup flow
  useEffect(() => {
    if (!token) return
    // If type=signup or no type specified, try signup verification first
    if (type === 'signup' || !type) {
      verifySignupEmail()
    }
  }, [token, type])

  async function verifySignupEmail() {
    setVerifying(true)
    setApiError(null)
    try {
      const res = await apiClient.post('/auth/verify-signup-email', { token })
      setAccessToken(res.data.access_token)
      setVerified(true)
      // Redirect to dashboard after a short delay
      setTimeout(() => navigate('/dashboard'), 2000)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail

      if (status === 400 && detail?.includes('already been verified')) {
        // Already verified — just redirect to login
        setVerified(true)
        setTimeout(() => navigate('/login'), 2000)
        return
      }

      // If signup verification fails, it might be an invitation token
      // Fall through to the password-setting form
      if (type === 'signup') {
        setApiError(detail ?? 'Verification failed. The link may have expired.')
      }
      // If no type specified, don't show error — let the password form show
    } finally {
      setVerifying(false)
    }
  }

  async function handleInviteSubmit(e: FormEvent) {
    e.preventDefault()
    setApiError(null)

    const validationErrors = validateVerifyEmailForm(password, confirmPassword)
    setErrors(validationErrors)
    if (Object.keys(validationErrors).length > 0) return

    setSubmitting(true)
    try {
      const res = await apiClient.post<VerifyEmailResponse>('/auth/verify-email', {
        token,
        password,
      })
      setAccessToken(res.data.access_token)
      navigate('/setup')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setApiError(detail ?? 'Verification failed. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  if (!token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg">
          <AlertBanner variant="error">This verification link is invalid.</AlertBanner>
        </div>
      </div>
    )
  }

  // Loading state for signup verification
  if (verifying) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg text-center">
          <Spinner size="lg" label="Verifying your email..." />
          <p className="text-sm text-gray-500">Please wait while we verify your email address.</p>
        </div>
      </div>
    )
  }

  // Success state
  if (verified) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg text-center">
          <svg className="mx-auto h-12 w-12 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          <h1 className="text-2xl font-bold text-gray-900">Email verified</h1>
          <p className="text-sm text-gray-500">
            Your email has been verified. Redirecting you now...
          </p>
        </div>
      </div>
    )
  }

  async function handleResendVerification(e: FormEvent) {
    e.preventDefault()
    const email = resendEmail.trim().toLowerCase()
    if (!email) {
      setResendError('Please enter your email address.')
      return
    }
    setResending(true)
    setResendError(null)
    setResendSuccess(false)
    try {
      await apiClient.post('/auth/resend-verification', { email })
      setResendSuccess(true)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setResendError(detail ?? 'Failed to resend verification email. Please try again.')
    } finally {
      setResending(false)
    }
  }

  // Signup verification error — show error with resend option
  if (type === 'signup' && apiError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg">
          <div className="text-center">
            <AlertBanner variant="error">{apiError}</AlertBanner>
          </div>
          <p className="text-sm text-gray-600 text-center">
            The verification link may have expired. Enter your email below to receive a new one.
          </p>

          {resendSuccess ? (
            <div className="text-center space-y-4">
              <AlertBanner variant="success">
                If an account exists with that email, a new verification link has been sent.
              </AlertBanner>
              <a
                href="/login"
                className="inline-block rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
              >
                Go to login
              </a>
            </div>
          ) : (
            <form onSubmit={handleResendVerification} className="space-y-4">
              {resendError && (
                <AlertBanner variant="error" onDismiss={() => setResendError(null)}>
                  {resendError}
                </AlertBanner>
              )}
              <Input
                label="Email address"
                type="email"
                autoComplete="email"
                required
                value={resendEmail}
                onChange={(e) => setResendEmail(e.target.value)}
                placeholder="you@example.com"
              />
              <Button type="submit" loading={resending} className="w-full">
                Resend verification email
              </Button>
              <div className="text-center">
                <a
                  href="/login"
                  className="text-sm text-blue-600 hover:text-blue-700"
                >
                  Back to login
                </a>
              </div>
            </form>
          )}
        </div>
      </div>
    )
  }

  // Invitation flow — set password form
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900">Set your password</h1>
          <p className="mt-1 text-sm text-gray-500">
            Choose a password to complete your account setup
          </p>
        </div>

        {apiError && (
          <AlertBanner variant="error" onDismiss={() => setApiError(null)}>
            {apiError}
          </AlertBanner>
        )}

        <form onSubmit={handleInviteSubmit} className="space-y-4" noValidate>
          <div>
            <Input
              label="Password"
              type="password"
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => {
                setPassword(e.target.value)
                if (errors.password) {
                  setErrors((prev) => { const next = { ...prev }; delete next.password; return next })
                }
              }}
              error={errors.password}
              placeholder="••••••••••••"
            />
            <PasswordRequirements password={password} />
          </div>

          <div>
            <Input
              label="Confirm password"
              type="password"
              autoComplete="new-password"
              required
              value={confirmPassword}
              onChange={(e) => {
                setConfirmPassword(e.target.value)
                if (errors.confirmPassword) {
                  setErrors((prev) => { const next = { ...prev }; delete next.confirmPassword; return next })
                }
              }}
              error={errors.confirmPassword}
              placeholder="••••••••••••"
            />
            <PasswordMatch password={password} confirmPassword={confirmPassword} />
          </div>

          <Button type="submit" loading={submitting} className="w-full">
            Set password
          </Button>
        </form>
      </div>
    </div>
  )
}
