import { useState, useCallback } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { Page, Block, List, ListInput, Button } from 'konsta/react'
import apiClient from '@/api/client'

/**
 * ResetPasswordScreen — Konsta UI single-form page with new password input.
 *
 * Reads the reset token from the URL query string (?token=...).
 * On submit: POSTs to /auth/password/reset with { token, new_password }.
 * On success: shows confirmation and link to login.
 * On error: displays backend error message.
 *
 * Requirements: 14.2
 */
export default function ResetPasswordScreen() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSubmitted, setIsSubmitted] = useState(false)

  const passwordError =
    newPassword.length > 0 && newPassword.length < 8
      ? 'Password must be at least 8 characters'
      : undefined

  const confirmError =
    confirmPassword.length > 0 && confirmPassword !== newPassword
      ? 'Passwords do not match'
      : undefined

  const canSubmit =
    token.length > 0 &&
    newPassword.length >= 8 &&
    confirmPassword === newPassword &&
    !isSubmitting

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return
    setError(null)
    setIsSubmitting(true)

    try {
      await apiClient.post('/auth/password/reset', {
        token,
        new_password: newPassword,
      })
      setIsSubmitted(true)
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? err.message
          : (err as { response?: { data?: { detail?: string } } })?.response
                ?.data?.detail ?? 'Password reset failed. Please try again.'
      setError(message)
    } finally {
      setIsSubmitting(false)
    }
  }, [canSubmit, token, newPassword])

  const handleFormSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      void handleSubmit()
    },
    [handleSubmit],
  )

  // No token — show error state
  if (!token) {
    return (
      <Page className="bg-white dark:bg-gray-900">
        <div className="bg-gradient-to-b from-slate-900 to-indigo-900 px-6 pb-10 pt-16 text-center">
          <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-white/10 backdrop-blur-sm">
            <LockIcon />
          </div>
          <h1 className="text-2xl font-bold text-white">Reset Password</h1>
          <p className="mt-1 text-sm text-indigo-200">
            Set a new password for your account
          </p>
        </div>

        <Block className="-mt-4 rounded-t-2xl bg-white pt-6 dark:bg-gray-900">
          <div
            role="alert"
            className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
          >
            Invalid or missing reset token. Please request a new password reset
            link.
          </div>
          <div className="text-center">
            <Link
              to="/forgot-password"
              className="text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400 dark:active:text-blue-300"
            >
              Request new reset link
            </Link>
          </div>
        </Block>
      </Page>
    )
  }

  // Success state
  if (isSubmitted) {
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
          <h1 className="text-2xl font-bold text-white">Password Reset</h1>
          <p className="mt-1 text-sm text-indigo-200">
            Your password has been updated
          </p>
        </div>

        <Block className="-mt-4 rounded-t-2xl bg-white pt-6 dark:bg-gray-900">
          <p className="mb-6 text-center text-sm text-gray-500 dark:text-gray-400">
            Your password has been successfully reset. You can now sign in with
            your new password.
          </p>
          <Button
            large
            onClick={() => navigate('/login', { replace: true })}
          >
            Sign In
          </Button>
        </Block>
      </Page>
    )
  }

  return (
    <Page className="bg-white dark:bg-gray-900">
      {/* Hero gradient header */}
      <div className="bg-gradient-to-b from-slate-900 to-indigo-900 px-6 pb-10 pt-16 text-center">
        <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-white/10 backdrop-blur-sm">
          <LockIcon />
        </div>
        <h1 className="text-2xl font-bold text-white">Reset Password</h1>
        <p className="mt-1 text-sm text-indigo-200">
          Set a new password for your account
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
              label="New Password"
              placeholder="Enter new password"
              value={newPassword}
              onInput={(e: React.ChangeEvent<HTMLInputElement>) =>
                setNewPassword(e.target.value)
              }
              error={passwordError}
              autoComplete="new-password"
              autoFocus
            />
            <ListInput
              type="password"
              label="Confirm Password"
              placeholder="Confirm new password"
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
            {isSubmitting ? 'Resetting…' : 'Reset Password'}
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

/** Lock icon for the hero section */
function LockIcon() {
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
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0110 0v4" />
    </svg>
  )
}
