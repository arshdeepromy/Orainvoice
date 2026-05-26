/**
 * Fleet Portal login page with MFA challenge support.
 *
 * Implements: B2B Fleet Portal task 14.2 — Requirements 3.1, 3.2, 21.13.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import axios from 'axios'

import { MfaChallengeRequired } from '../api/endpoints'
import { useFleetSession } from '../contexts/FleetSessionContext'

interface LocationState {
  from?: string
}

interface PlatformBranding {
  app_name: string
  logo_url: string | null
  primary_colour: string | null
}

export default function Login() {
  const { login, verifyMfaCode, clearMfaChallenge, mfaChallenge, user } = useFleetSession()
  const location = useLocation()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mfaCode, setMfaCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [branding, setBranding] = useState<PlatformBranding | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    axios.get<PlatformBranding>('/api/v1/public/branding', { signal: controller.signal })
      .then(res => setBranding(res.data ?? null))
      .catch(() => {})
    return () => controller.abort()
  }, [])

  if (user) {
    const target = (location.state as LocationState | null)?.from ?? '/fleet/dashboard'
    return <Navigate to={target} replace />
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(email.trim().toLowerCase(), password)
      navigate('/fleet/dashboard', { replace: true })
    } catch (err: unknown) {
      if (err instanceof MfaChallengeRequired) {
        // MFA challenge — show the code input (don't navigate yet)
        setError(null)
      } else {
        const detail =
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          ((err as any)?.response?.data?.detail as string | undefined) ??
          'Sign-in failed. Please try again.'
        setError(detail)
      }
    } finally {
      setSubmitting(false)
    }
  }

  const handleMfaSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!mfaCode || mfaCode.length < 6) {
      setError('Enter the 6-digit code from your authenticator app.')
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      await verifyMfaCode(mfaCode, mfaChallenge?.default_method ?? 'totp')
      navigate('/fleet/dashboard', { replace: true })
    } catch (err: unknown) {
      const detail =
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        ((err as any)?.response?.data?.detail as string | undefined) ??
        'Invalid code. Please try again.'
      setError(detail)
    } finally {
      setSubmitting(false)
    }
  }

  const handleBackToLogin = () => {
    clearMfaChallenge()
    setMfaCode('')
    setError(null)
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 px-4 dark:bg-gray-900">
      {/* MFA Challenge Screen */}
      {mfaChallenge ? (
        <form
          onSubmit={handleMfaSubmit}
          className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-950"
          noValidate
        >
          {branding?.logo_url && (
            <div className="mb-4 flex justify-center">
              <img src={branding.logo_url} alt={branding?.app_name ?? ''} className="h-10 w-auto" />
            </div>
          )}

          <h1 className="mb-2 text-xl font-semibold text-gray-900 dark:text-white">
            Two-Factor Authentication
          </h1>
          <p className="mb-6 text-sm text-gray-600 dark:text-gray-400">
            Enter the 6-digit code from your authenticator app to complete sign-in.
          </p>

          {error ? (
            <div
              className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
              role="alert"
            >
              {error}
            </div>
          ) : null}

          <div className="mb-6">
            <label
              htmlFor="mfa-code"
              className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              Verification Code
            </label>
            <input
              id="mfa-code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              required
              value={mfaCode}
              onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              placeholder="000000"
              className="w-full rounded-md border border-gray-300 px-3 py-2 min-h-[44px] text-center text-lg tracking-widest font-mono dark:border-gray-700 dark:bg-gray-900 dark:text-white"
              autoFocus
            />
          </div>

          <button
            type="submit"
            disabled={submitting || mfaCode.length < 6}
            className="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] disabled:opacity-50 hover:bg-indigo-700"
          >
            {submitting ? 'Verifying…' : 'Verify'}
          </button>

          {/* Backup code option */}
          {(mfaChallenge.mfa_methods ?? []).includes('backup_codes') && (
            <p className="mt-3 text-center text-xs text-gray-500">
              Lost your authenticator? Use a{' '}
              <button
                type="button"
                onClick={() => {
                  // Switch to backup code mode — just change the placeholder text
                  setError(null)
                }}
                className="text-indigo-600 hover:underline dark:text-indigo-400"
              >
                backup code
              </button>
            </p>
          )}

          <div className="mt-4 text-center">
            <button
              type="button"
              onClick={handleBackToLogin}
              className="text-sm text-gray-500 hover:underline"
            >
              ← Back to login
            </button>
          </div>
        </form>
      ) : (
        /* Standard Login Form */
        <form
          onSubmit={handleSubmit}
          className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-950"
          noValidate
        >
          {branding?.logo_url && (
            <div className="mb-4 flex justify-center">
              <img src={branding.logo_url} alt={branding?.app_name ?? ''} className="h-10 w-auto" />
            </div>
          )}

          <h1 className="mb-4 text-xl font-semibold text-gray-900 dark:text-white">
            Fleet Portal
          </h1>
          <p className="mb-6 text-sm text-gray-600 dark:text-gray-400">
            Sign in with your fleet portal credentials.
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
            <label
              htmlFor="email"
              className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              Email
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

          <div className="mb-6">
            <label
              htmlFor="password"
              className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white"
            />
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] disabled:opacity-50 hover:bg-indigo-700"
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>

          <div className="mt-4 text-center text-sm">
            <Link
              to="/fleet/forgot-password"
              className="text-indigo-600 hover:underline dark:text-indigo-400"
            >
              Forgot password?
            </Link>
          </div>
        </form>
      )}

      {/* Powered by footer */}
      <footer className="mt-6 text-center text-xs text-gray-400">
        <p>
          Powered by{' '}
          <span className="font-medium text-gray-500">{branding?.app_name || 'OraInvoice'}</span>
        </p>
      </footer>
    </div>
  )
}
