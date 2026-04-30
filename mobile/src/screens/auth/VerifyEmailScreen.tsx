import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { Page, Block, List, ListInput, Button } from 'konsta/react'
import apiClient from '@/api/client'
import { setAccessToken } from '@/api/client'

/**
 * VerifyEmailScreen — Konsta UI status page with auto-verify for invited users.
 *
 * Reads the token and type from the URL query string (?token=...&type=signup).
 * - For signup type: auto-verifies immediately (no password needed — already set
 *   during signup).
 * - For invitation type: shows a password form so the invited user can set their
 *   password while verifying their email.
 *
 * On success: stores the access token and navigates to /.
 * On error: displays error message with link to login.
 *
 * API: POST /auth/verify-email with { token, password }
 *
 * Requirements: 14.3
 */
export default function VerifyEmailScreen() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''
  const type = searchParams.get('type') ?? ''

  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isVerified, setIsVerified] = useState(false)
  const [autoVerifying, setAutoVerifying] = useState(false)

  const isSignup = type === 'signup'

  const passwordError =
    password.length > 0 && password.length < 8
      ? 'Password must be at least 8 characters'
      : undefined

  const confirmError =
    confirmPassword.length > 0 && confirmPassword !== password
      ? 'Passwords do not match'
      : undefined

  const canSubmit =
    token.length > 0 &&
    password.length >= 8 &&
    confirmPassword === password &&
    !isSubmitting

  // Auto-verify for signup type (password was already set during registration)
  useEffect(() => {
    if (!isSignup || !token || autoVerifying || isVerified) return

    const controller = new AbortController()
    setAutoVerifying(true)

    ;(async () => {
      try {
        const res = await apiClient.post<{
          access_token?: string
          message?: string
        }>(
          '/auth/verify-email',
          { token, password: '' },
          { signal: controller.signal },
        )
        const accessToken = res.data?.access_token
        if (accessToken) {
          setAccessToken(accessToken)
        }
        setIsVerified(true)
      } catch (err: unknown) {
        if (controller.signal.aborted) return
        const message =
          (err as { response?: { data?: { detail?: string } } })?.response
            ?.data?.detail ?? 'Email verification failed. The link may have expired.'
        setError(message)
      } finally {
        if (!controller.signal.aborted) {
          setAutoVerifying(false)
        }
      }
    })()

    return () => controller.abort()
  }, [isSignup, token, autoVerifying, isVerified])

  // Manual submit for invitation type (user needs to set password)
  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return
    setError(null)
    setIsSubmitting(true)

    try {
      const res = await apiClient.post<{
        access_token?: string
        message?: string
      }>('/auth/verify-email', { token, password })
      const accessToken = res.data?.access_token
      if (accessToken) {
        setAccessToken(accessToken)
      }
      setIsVerified(true)
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response
          ?.data?.detail ?? 'Verification failed. Please try again.'
      setError(message)
    } finally {
      setIsSubmitting(false)
    }
  }, [canSubmit, token, password])

  const handleFormSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      void handleSubmit()
    },
    [handleSubmit],
  )

  // No token — show error
  if (!token) {
    return (
      <Page className="bg-white dark:bg-gray-900">
        <div className="bg-gradient-to-b from-slate-900 to-indigo-900 px-6 pb-10 pt-16 text-center">
          <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-white/10 backdrop-blur-sm">
            <MailIcon />
          </div>
          <h1 className="text-2xl font-bold text-white">Verify Email</h1>
          <p className="mt-1 text-sm text-indigo-200">
            Complete your account setup
          </p>
        </div>

        <Block className="-mt-4 rounded-t-2xl bg-white pt-6 dark:bg-gray-900">
          <div
            role="alert"
            className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
          >
            Invalid or missing verification token. Please check your email for
            the correct link.
          </div>
          <div className="text-center">
            <Link
              to="/login"
              className="text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400 dark:active:text-blue-300"
            >
              Go to login
            </Link>
          </div>
        </Block>
      </Page>
    )
  }

  // Auto-verifying state (signup flow)
  if (autoVerifying) {
    return (
      <Page className="bg-white dark:bg-gray-900">
        <div className="bg-gradient-to-b from-slate-900 to-indigo-900 px-6 pb-10 pt-16 text-center">
          <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-white/10 backdrop-blur-sm">
            <MailIcon />
          </div>
          <h1 className="text-2xl font-bold text-white">Verifying Email</h1>
          <p className="mt-1 text-sm text-indigo-200">
            Please wait while we verify your email
          </p>
        </div>

        <Block className="-mt-4 rounded-t-2xl bg-white pt-6 dark:bg-gray-900">
          <div className="flex flex-col items-center py-8">
            <div className="mb-4 h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Verifying your email address…
            </p>
          </div>
        </Block>
      </Page>
    )
  }

  // Verified success state
  if (isVerified) {
    return (
      <Page className="bg-white dark:bg-gray-900">
        <div className="bg-gradient-to-b from-slate-900 to-indigo-900 px-6 pb-10 pt-16 text-center">
          <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-white/10 backdrop-blur-sm">
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
              <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
              <polyline points="22 4 12 14.01 9 11.01" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-white">Email Verified</h1>
          <p className="mt-1 text-sm text-indigo-200">
            Your account is ready to use
          </p>
        </div>

        <Block className="-mt-4 rounded-t-2xl bg-white pt-6 dark:bg-gray-900">
          <p className="mb-6 text-center text-sm text-gray-500 dark:text-gray-400">
            Your email has been verified successfully.
            {isSignup
              ? ' You can now sign in to your account.'
              : ' Your password has been set and you are ready to go.'}
          </p>
          <Button
            large
            onClick={() => navigate('/', { replace: true })}
          >
            {isSignup ? 'Go to Dashboard' : 'Get Started'}
          </Button>
        </Block>
      </Page>
    )
  }

  // Invitation flow — show password form (with possible error from auto-verify)
  return (
    <Page className="bg-white dark:bg-gray-900">
      {/* Hero gradient header */}
      <div className="bg-gradient-to-b from-slate-900 to-indigo-900 px-6 pb-10 pt-16 text-center">
        <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-white/10 backdrop-blur-sm">
          <MailIcon />
        </div>
        <h1 className="text-2xl font-bold text-white">Verify Email</h1>
        <p className="mt-1 text-sm text-indigo-200">
          Set your password to complete account setup
        </p>
      </div>

      <Block className="-mt-4 rounded-t-2xl bg-white pt-6 dark:bg-gray-900">
        {/* Error banner */}
        {error && (
          <div
            role="alert"
            className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
          >
            {error}
          </div>
        )}

        <form onSubmit={handleFormSubmit} noValidate>
          <List strongIos outlineIos className="-mx-4 mb-4">
            <ListInput
              type="password"
              label="Password"
              placeholder="Create a password"
              value={password}
              onInput={(e: React.ChangeEvent<HTMLInputElement>) =>
                setPassword(e.target.value)
              }
              error={passwordError}
              autoComplete="new-password"
              autoFocus
            />
            <ListInput
              type="password"
              label="Confirm Password"
              placeholder="Confirm your password"
              value={confirmPassword}
              onInput={(e: React.ChangeEvent<HTMLInputElement>) =>
                setConfirmPassword(e.target.value)
              }
              error={confirmError}
              autoComplete="new-password"
            />
          </List>

          <Button
            type="submit"
            large
            className="mb-3"
            disabled={!canSubmit}
          >
            {isSubmitting ? 'Verifying…' : 'Verify & Set Password'}
          </Button>
        </form>

        {/* Back to login */}
        <div className="mt-4 text-center">
          <Link
            to="/login"
            className="text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400 dark:active:text-blue-300"
          >
            Back to login
          </Link>
        </div>
      </Block>
    </Page>
  )
}

/** Mail icon for the hero section */
function MailIcon() {
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
      <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
      <polyline points="22,6 12,13 2,6" />
    </svg>
  )
}
