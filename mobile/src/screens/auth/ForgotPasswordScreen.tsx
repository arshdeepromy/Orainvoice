import { useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import apiClient from '@/api/client'
import { MobileButton } from '@/components/ui/MobileButton'
import { MobileInput } from '@/components/ui/MobileInput'
import { MobileForm } from '@/components/ui/MobileForm'

/**
 * ForgotPasswordScreen — email input, submit, confirmation message.
 *
 * Sends a password reset request to the backend.
 * On success: displays confirmation that a reset link has been sent.
 * On error: displays error message.
 *
 * Requirements: 2.6, 2.7
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

  // Success state
  if (isSubmitted) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 px-6 dark:bg-gray-900">
        <div className="w-full max-w-sm text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/30">
            <svg
              className="h-8 w-8 text-green-600 dark:text-green-400"
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
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Check Your Email
          </h1>
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
            If an account exists for <strong className="text-gray-700 dark:text-gray-300">{email}</strong>,
            we&apos;ve sent a password reset link. Please check your inbox.
          </p>
          <div className="mt-8">
            <Link
              to="/login"
              className="text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400 dark:active:text-blue-300"
            >
              Back to login
            </Link>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 px-6 dark:bg-gray-900">
      <div className="w-full max-w-sm">
        {/* Header */}
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Forgot Password
          </h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Enter your email and we&apos;ll send you a reset link
          </p>
        </div>

        {/* Error banner */}
        {error && (
          <div
            role="alert"
            className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
          >
            {error}
          </div>
        )}

        <MobileForm onSubmit={handleSubmit}>
          <MobileInput
            label="Email"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            error={emailError}
            required
            autoComplete="email"
            autoCapitalize="none"
            inputMode="email"
            autoFocus
          />

          <MobileButton
            type="submit"
            fullWidth
            isLoading={isSubmitting}
            disabled={!canSubmit}
          >
            Send Reset Link
          </MobileButton>
        </MobileForm>

        {/* Back to login */}
        <div className="mt-6 text-center">
          <Link
            to="/login"
            className="text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400 dark:active:text-blue-300"
          >
            Back to login
          </Link>
        </div>
      </div>
    </div>
  )
}
