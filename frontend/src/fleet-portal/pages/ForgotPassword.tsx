/**
 * Forgot-password page — anti-enumerating per Property 8.
 *
 * Implements: B2B Fleet Portal task 14.2 — Requirement 3.9.
 */
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { forgotPassword } from '../api/endpoints'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    try {
      await forgotPassword(email.trim().toLowerCase())
    } catch {
      // Anti-enumeration — show success regardless of any error.
    } finally {
      setSubmitted(true)
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 dark:bg-gray-900">
      <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-950">
        <h1 className="mb-4 text-xl font-semibold text-gray-900 dark:text-white">
          Forgot password
        </h1>

        {submitted ? (
          <div className="space-y-4">
            <p className="text-sm text-gray-700 dark:text-gray-300">
              If we have an account on file for that email, we&apos;ve sent a reset link.
              Please check your inbox.
            </p>
            <Link
              to="/fleet/login"
              className="block w-full rounded-md bg-brand-600 px-4 py-2 text-center text-sm font-medium text-white min-h-[44px]"
            >
              Back to sign in
            </Link>
          </div>
        ) : (
          <form onSubmit={handleSubmit} noValidate>
            <p className="mb-4 text-sm text-gray-600 dark:text-gray-400">
              Enter your email address and we&apos;ll send a password reset link.
            </p>
            <label htmlFor="email" className="mb-1 block text-sm font-medium">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mb-4 w-full rounded-md border border-gray-300 px-3 py-2 min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white"
            />
            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] disabled:opacity-50"
            >
              {submitting ? 'Sending…' : 'Send reset link'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
