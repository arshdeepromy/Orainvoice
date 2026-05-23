/**
 * Reset-password page — user sets a new password via the reset link.
 *
 * Implements: B2B Fleet Portal — Requirements 3.11, 3.12.
 */
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { resetPassword } from '../api/endpoints'

export default function ResetPassword() {
  const { token } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!email.trim()) {
      setError('Please enter your email address.')
      return
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }
    if (!token) {
      setError('Invalid reset link.')
      return
    }

    setSubmitting(true)
    try {
      await resetPassword(token, password, email.trim().toLowerCase())
      setSuccess(true)
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'This password reset link is no longer valid.'
      setError(detail)
    } finally {
      setSubmitting(false)
    }
  }

  if (success) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 dark:bg-gray-900">
        <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-950">
          <h1 className="mb-4 text-xl font-semibold text-green-700 dark:text-green-400">
            ✓ Password reset successfully
          </h1>
          <p className="mb-6 text-sm text-gray-600 dark:text-gray-400">
            Your password has been updated. You can now sign in with your new password.
          </p>
          <Link
            to="/fleet/login"
            className="block w-full rounded-md bg-brand-600 px-4 py-2 text-center text-sm font-medium text-white min-h-[44px] leading-[44px]"
          >
            Sign in
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 dark:bg-gray-900">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-950"
        noValidate
      >
        <h1 className="mb-2 text-xl font-semibold text-gray-900 dark:text-white">
          Reset your password
        </h1>
        <p className="mb-6 text-sm text-gray-600 dark:text-gray-400">
          Enter your email and choose a new password (at least 8 characters).
        </p>

        {error ? (
          <div
            className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
            role="alert"
          >
            {error}
          </div>
        ) : null}

        <div className="mb-4">
          <label htmlFor="email" className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
            Email address
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white"
          />
        </div>

        <div className="mb-4">
          <label htmlFor="password" className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
            New password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white"
          />
        </div>

        <div className="mb-6">
          <label htmlFor="confirm" className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
            Confirm new password
          </label>
          <input
            id="confirm"
            type="password"
            autoComplete="new-password"
            required
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white"
          />
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] disabled:opacity-50"
        >
          {submitting ? 'Resetting…' : 'Reset password'}
        </button>

        <div className="mt-4 text-center">
          <Link to="/fleet/forgot-password" className="text-sm text-brand-600 hover:underline dark:text-brand-400">
            Request a new reset link
          </Link>
        </div>
      </form>
    </div>
  )
}
