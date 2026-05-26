/**
 * Accept-invite page — user sets their password after clicking the
 * invite link from the email.
 *
 * Implements: B2B Fleet Portal — Requirements 4.4, 4.5, 4.6.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import axios from 'axios'

import { acceptInvite } from '../api/endpoints'

interface PlatformBranding {
  app_name: string
  logo_url: string | null
  favicon_url: string | null
  primary_colour: string | null
}

export default function AcceptInvite() {
  const { token } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState(false)
  const [tokenUsed, setTokenUsed] = useState(false)
  const [branding, setBranding] = useState<PlatformBranding | null>(null)

  // Fetch platform branding on mount
  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        const res = await axios.get<PlatformBranding>('/api/v1/public/branding', {
          signal: controller.signal,
        })
        setBranding(res.data ?? null)
      } catch {
        // Non-critical — page works without branding
      }
    }
    void load()
    return () => controller.abort()
  }, [])

  // Validate the token on mount — check if it's still valid by calling
  // a GET endpoint that returns the token status without consuming it.
  useEffect(() => {
    if (!token) {
      setTokenUsed(true)
      return
    }
    const controller = new AbortController()
    const validate = async () => {
      try {
        const res = await axios.get(
          `/fleet/api/auth/invite-status/${encodeURIComponent(token)}`,
          { signal: controller.signal },
        )
        const status = (res.data as { status?: string })?.status
        if (status === 'used' || status === 'expired' || status === 'not_found') {
          setTokenUsed(true)
        }
      } catch {
        // If the endpoint returns 404 or any error, the token is invalid
        setTokenUsed(true)
      }
    }
    void validate()
    return () => controller.abort()
  }, [token])

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
      setError('Invalid invite link.')
      return
    }

    setSubmitting(true)
    try {
      await acceptInvite(token, password, email.trim().toLowerCase())
      setSuccess(true)
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to set password. The invite link may have expired.'
      // If the token is expired/used, show the dedicated state
      if (
        detail.includes('expired') ||
        detail.includes('already been used') ||
        detail.includes('no longer valid')
      ) {
        setTokenUsed(true)
      } else {
        setError(detail)
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (tokenUsed) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 px-4 dark:bg-gray-900">
        <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-950">
          {branding?.logo_url && (
            <img src={branding.logo_url} alt="" className="mx-auto mb-4 h-10 w-auto" />
          )}
          <h1 className="mb-3 text-xl font-semibold text-gray-900 dark:text-white">
            Invitation already used
          </h1>
          <p className="mb-6 text-sm text-gray-600 dark:text-gray-400">
            This invitation link has already been used to set up your account.
            You can sign in with the password you created.
          </p>
          <Link
            to="/fleet/login"
            className="block w-full rounded-md bg-indigo-600 px-4 py-2 text-center text-sm font-medium text-white min-h-[44px] leading-[44px] hover:bg-indigo-700"
          >
            Go to sign in
          </Link>
          <div className="mt-3 text-center">
            <Link to="/fleet/forgot-password" className="text-sm text-indigo-600 hover:underline dark:text-indigo-400">
              Forgot your password?
            </Link>
          </div>
        </div>
        <PoweredByFooter branding={branding} />
      </div>
    )
  }

  if (success) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 px-4 dark:bg-gray-900">
        <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-950">
          {branding?.logo_url && (
            <img src={branding.logo_url} alt="" className="mx-auto mb-4 h-10 w-auto" />
          )}
          <h1 className="mb-4 text-xl font-semibold text-green-700 dark:text-green-400">
            ✓ Account set up successfully
          </h1>
          <p className="mb-6 text-sm text-gray-600 dark:text-gray-400">
            Your password has been set. You can now sign in to the Fleet Portal.
          </p>
          <Link
            to="/fleet/login"
            className="block w-full rounded-md bg-indigo-600 px-4 py-2 text-center text-sm font-medium text-white min-h-[44px] leading-[44px] hover:bg-indigo-700"
          >
            Sign in
          </Link>
        </div>
        <PoweredByFooter branding={branding} />
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 px-4 dark:bg-gray-900">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-950"
        noValidate
      >
        {/* Org / platform branding */}
        {branding?.logo_url && (
          <div className="mb-4 flex justify-center">
            <img src={branding.logo_url} alt={branding?.app_name ?? ''} className="h-10 w-auto" />
          </div>
        )}

        <h1 className="mb-2 text-xl font-semibold text-gray-900 dark:text-white">
          Set up your Fleet Portal account
        </h1>
        <p className="mb-6 text-sm text-gray-600 dark:text-gray-400">
          Create a password to access the Fleet Portal. Your password must be at least 8 characters.
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
            placeholder="Enter the email your invite was sent to"
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
            placeholder="At least 8 characters"
          />
        </div>

        <div className="mb-6">
          <label htmlFor="confirm" className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
            Confirm password
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
          className="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] disabled:opacity-50 hover:bg-indigo-700"
        >
          {submitting ? 'Setting up…' : 'Set password & continue'}
        </button>

        <div className="mt-4 text-center text-sm text-gray-500">
          Already have an account?{' '}
          <Link to="/fleet/login" className="text-indigo-600 hover:underline dark:text-indigo-400">
            Sign in
          </Link>
        </div>
      </form>
      <PoweredByFooter branding={branding} />
    </div>
  )
}

function PoweredByFooter({ branding }: { branding: PlatformBranding | null }) {
  const name = branding?.app_name || 'OraInvoice'
  return (
    <footer className="mt-6 text-center text-xs text-gray-400">
      <p>
        Powered by{' '}
        <span className="font-medium text-gray-500">{name}</span>
      </p>
    </footer>
  )
}
