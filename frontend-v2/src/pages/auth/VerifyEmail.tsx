import { useState, useEffect } from 'react'
import type { FormEvent } from 'react'
import { Link, useSearchParams, useNavigate } from 'react-router-dom'
import apiClient, { setAccessToken } from '@/api/client'
import { Button, Input, AlertBanner, Spinner } from '@/components/ui'
import { validateVerifyEmailForm } from './signup-validation'
import { PasswordRequirements, PasswordMatch } from '@/components/auth/PasswordRequirements'
import type { VerifyEmailResponse } from './signup-types'

/**
 * VerifyEmail — dual-purpose email verification page (Task 14 port of
 * frontend/src/pages/auth/VerifyEmail).
 *
 * ALL logic is copied verbatim from the original:
 *  • token + type read from the URL query (`?token=`, `?type=`).
 *  • Auto-verify effect: when type=signup or no type, calls
 *    verifySignupEmail() → POST /auth/verify-signup-email { token }, sets the
 *    access token, shows the verified state, and redirects to /dashboard after
 *    2s. A 400 "already been verified" instead redirects to /login after 2s.
 *    On other signup failures it surfaces apiError (only when type === 'signup');
 *    with no type it falls through to the password form (invitation token).
 *  • Invitation flow: handleInviteSubmit() validates via validateVerifyEmailForm,
 *    POSTs /auth/verify-email { token, password }, sets the access token, and
 *    navigates to /setup.
 *  • Resend flow: handleResendVerification() → POST /auth/resend-verification
 *    { email } with its own success / error state.
 *  • The missing-token, verifying (spinner), and verified states are preserved.
 *
 * The page renders ONLY its card content into the AuthLayout `<Outlet/>`
 * (Task 12). The invitation set-password form follows
 * OraInvoice_Handoff/app/VerifyEmail.html (`.auth-head` + password fields), and
 * REUSES the already-ported PasswordRequirements/PasswordMatch live feedback
 * (Task 13) exactly as the original did. The auto-verify spinner, verified
 * panel and resend form are designed on the fly in the same language (FR-2b):
 * the ok-soft success circle and the token-styled email field + alerts.
 *
 * The original's resend / "Back to login" navigations used hard `<a href>`s;
 * here they are react-router <Link>s so they stay inside the `/new/` mount
 * (FR-3) — the destination (/login) is unchanged.
 */
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
  }, [token, type]) // eslint-disable-line react-hooks/exhaustive-deps

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
      <div className="w-full max-w-[400px]">
        <AlertBanner variant="error">This verification link is invalid.</AlertBanner>
      </div>
    )
  }

  // Loading state for signup verification
  if (verifying) {
    return (
      <div className="w-full max-w-[400px] space-y-4 text-center">
        <Spinner size="lg" label="Verifying your email..." className="mx-auto" />
        <p className="text-[14px] text-muted">Please wait while we verify your email address.</p>
      </div>
    )
  }

  // Success state
  if (verified) {
    return (
      <div className="w-full max-w-[400px] text-center">
        <div className="mx-auto mb-5 grid h-[60px] w-[60px] place-items-center rounded-full bg-ok-soft">
          <svg className="h-7 w-7 text-ok" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h1 className="text-[23px] font-bold tracking-[-0.02em] text-text">Email verified</h1>
        <p className="mt-2 text-[14px] text-muted">
          Your email has been verified. Redirecting you now...
        </p>
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
      <div className="w-full max-w-[400px] space-y-6">
        <AlertBanner variant="error">{apiError}</AlertBanner>
        <p className="text-center text-[14px] text-muted">
          The verification link may have expired. Enter your email below to receive a new one.
        </p>

        {resendSuccess ? (
          <div className="space-y-4 text-center">
            <AlertBanner variant="success">
              If an account exists with that email, a new verification link has been sent.
            </AlertBanner>
            <Button href="/login" fullWidth className="h-[46px] text-[14.5px]">
              Go to login
            </Button>
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
            <Button type="submit" loading={resending} fullWidth className="h-[46px] text-[14.5px]">
              Resend verification email
            </Button>
            <p className="text-center">
              <Link to="/login" className="text-[13px] font-semibold text-accent hover:text-accent-press">
                Back to login
              </Link>
            </p>
          </form>
        )}
      </div>
    )
  }

  // Invitation flow — set password form
  return (
    <div className="w-full max-w-[400px]">
      <div className="mb-[26px]">
        <h1 className="text-[25px] font-bold tracking-[-0.02em] text-text">Set your password</h1>
        <p className="mt-[7px] text-[14px] text-muted">
          Choose a password to complete your account setup
        </p>
      </div>

      {apiError && (
        <div className="mb-4">
          <AlertBanner variant="error" onDismiss={() => setApiError(null)}>
            {apiError}
          </AlertBanner>
        </div>
      )}

      <form onSubmit={handleInviteSubmit} className="flex flex-col gap-4" noValidate>
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

        <Button type="submit" loading={submitting} fullWidth className="h-[46px] text-[14.5px]">
          Set password
        </Button>
      </form>

      <p className="mt-6 text-center text-[13.5px] text-muted">
        Wrong account?{' '}
        <Link to="/login" className="font-semibold text-accent hover:text-accent-press">
          Sign in instead
        </Link>
      </p>
    </div>
  )
}
