/**
 * Portal token recovery page — "Forgot your link?"
 *
 * Allows a customer to enter their email address to receive their
 * portal access link(s). The backend always returns 200 with a
 * generic message to prevent email enumeration.
 *
 * Requirements: 52.1, 52.2, 52.3, 52.4
 */

import { useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import apiClient from '@/api/client'

export function PortalRecover() {
  const [email, setEmail] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      if (!email.trim()) return

      setSubmitting(true)
      setError('')
      try {
        await apiClient.post('/portal/recover', { email: email.trim() })
        setSubmitted(true)
      } catch {
        setError('Something went wrong. Please try again later.')
      } finally {
        setSubmitting(false)
      }
    },
    [email],
  )

  if (submitted) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center px-4">
        <div className="max-w-md text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-blue-100">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-8 w-8 text-blue-600"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
              />
            </svg>
          </div>
          <h1 className="text-2xl font-semibold text-gray-900">Check your email</h1>
          <p className="mt-3 text-sm text-gray-500">
            If an account exists with that email, a portal link has been sent.
            Please check your inbox (and spam folder) for the link.
          </p>
          <button
            type="button"
            onClick={() => {
              setSubmitted(false)
              setEmail('')
            }}
            className="mt-6 inline-flex items-center rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 min-h-[44px]"
          >
            Try another email
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-blue-100">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-8 w-8 text-blue-600"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"
              />
            </svg>
          </div>
          <h1 className="text-2xl font-semibold text-gray-900">Forgot your portal link?</h1>
          <p className="mt-2 text-sm text-gray-500">
            Enter the email address associated with your account and we'll send you a new portal
            access link.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="mt-8 space-y-4">
          <div>
            <label htmlFor="recover-email" className="block text-sm font-medium text-gray-700">
              Email address
            </label>
            <input
              id="recover-email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 min-h-[44px]"
            />
          </div>

          {error && (
            <p className="text-sm text-red-600" role="alert">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting || !email.trim()}
            className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 min-h-[44px]"
          >
            {submitting ? 'Sending…' : 'Send portal link'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-gray-500">
          Already have your link?{' '}
          <Link to="/" className="font-medium text-blue-600 hover:text-blue-500">
            Go to login
          </Link>
        </p>
      </div>
    </div>
  )
}
