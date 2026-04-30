import { useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Page, Block, List, ListInput, Button } from 'konsta/react'
import apiClient from '@/api/client'

/**
 * ForgotPasswordScreen — Konsta UI redesign with hero gradient header,
 * email ListInput, and primary "Send Reset Link" button.
 *
 * Business logic is preserved unchanged:
 * - On submit: POSTs to /auth/forgot-password
 * - On success (or 404): shows confirmation to prevent email enumeration
 * - On network error: shows error message
 *
 * Requirements: 14.1
 */
export default function ForgotPasswordScreen() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSubmitted, setIsSubmitted] = useState(false)

  const emailError =
    email.length > 0 && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
      ? 'Please enter a valid email address'
      : undefined

  const canSubmit = email.length > 0 && !emailError && !isSubmitting

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return
    setError(null)
    setIsSubmitting(true)

    try {
      await apiClient.post('/auth/forgot-password', { email })
      setIsSubmitted(true)
    } catch (err: unknown) {
      // Always show success to prevent email enumeration,
      // but handle network errors
      const isNetworkError = (err as { code?: string })?.code === 'ERR_NETWORK'
      if (isNetworkError) {
        setError('Unable to connect. Please check your internet connection.')
      } else {
        // Show success even on 404 to prevent email enumeration
        setIsSubmitted(true)
      }
    } finally {
      setIsSubmitting(false)
    }
  }, [canSubmit, email])

  const handleFormSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      void handleSubmit()
    },
    [handleSubmit],
  )

  // Success state
  if (isSubmitted) {
    return (
      <Page className="bg-white dark:bg-gray-900">
        {/* Hero gradient header */}
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
          <h1 className="text-2xl font-bold text-white">Check Your Email</h1>
          <p className="mt-1 text-sm text-indigo-200">
            We&apos;ve sent a password reset link
          </p>
        </div>

        <Block className="-mt-4 rounded-t-2xl bg-white pt-6 dark:bg-gray-900">
          <p className="mb-6 text-center text-sm text-gray-500 dark:text-gray-400">
            If an account exists for{' '}
            <strong className="text-gray-700 dark:text-gray-300">{email}</strong>,
            we&apos;ve sent a password reset link. Please check your inbox.
          </p>
          <div className="text-center">
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

  return (
    <Page className="bg-white dark:bg-gray-900">
      {/* Hero gradient header */}
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
            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
            <polyline points="22,6 12,13 2,6" />
          </svg>
        </div>
        <h1 className="text-2xl font-bold text-white">Forgot Password</h1>
        <p className="mt-1 text-sm text-indigo-200">
          Enter your email and we&apos;ll send you a reset link
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
              type="email"
              label="Email"
              placeholder="you@example.com"
              value={email}
              onInput={(e: React.ChangeEvent<HTMLInputElement>) =>
                setEmail(e.target.value)
              }
              error={emailError}
              inputMode="email"
              autoComplete="email"
              autoCapitalize="none"
              autoFocus
            />
          </List>

          <Button
            type="submit"
            large
            className="mb-3"
            disabled={!canSubmit}
          >
            {isSubmitting ? 'Sending…' : 'Send Reset Link'}
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
