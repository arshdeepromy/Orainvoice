/**
 * Organisation Employee Portal — accept-invite (set initial password) page.
 *
 * Route: ``/e/:slug/accept-invite/:token`` (no auth — sits OUTSIDE
 * RequireAuth/GuestOnly, like the branded login). Registered in App.tsx ABOVE
 * the ``/e/:slug/*`` authenticated-app route so the token URL doesn't fall
 * through to the app shell (which would bounce to login).
 *
 * API (cookie-auth portal surface, no JWT — token authenticates the POST):
 *   - GET  /e/api/auth/accept-invite/{token}
 *       → { status: not_found | used | expired | valid, org_name, email }
 *   - POST /e/api/auth/accept-invite/{token}  body { new_password }
 *       → 200 { ok: true }; 410 invite_expired / 422 password_length /
 *         404 invite_not_found carry { detail: { message, code } }.
 *
 * On success the user is routed to the branded login at ``/e/:slug`` to sign in
 * with their new password (acceptance does not mint a session).
 */
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import axios from 'axios'
import usePageMeta from '../../hooks/usePageMeta'

type InviteStatus = 'loading' | 'valid' | 'used' | 'expired' | 'not_found' | 'error'

interface InviteStatusResponse {
  status: 'valid' | 'used' | 'expired' | 'not_found'
  org_name: string | null
  email: string | null
}

function mapSubmitError(err: unknown): string {
  if (!axios.isAxiosError(err)) return 'Something went wrong. Please try again.'
  const detail = (err.response?.data as { detail?: { message?: string; code?: string } } | undefined)?.detail
  const flat = err.response?.data as { message?: string; code?: string } | undefined
  const message = detail?.message ?? flat?.message
  const code = detail?.code ?? flat?.code
  if (code === 'password_length') return message ?? 'Password must be between 8 and 128 characters.'
  if (code === 'invite_expired' || err.response?.status === 410) {
    return message ?? 'This invite has expired. Ask your administrator to send a new one.'
  }
  if (code === 'invite_not_found' || err.response?.status === 404) {
    return message ?? 'This invite link is no longer valid.'
  }
  return message ?? 'Could not set your password. Please try again.'
}

export default function EmployeePortalAcceptInvite() {
  const { slug, token } = useParams<{ slug: string; token: string }>()
  const navigate = useNavigate()

  const [status, setStatus] = useState<InviteStatus>('loading')
  const [orgName, setOrgName] = useState<string | null>(null)
  const [email, setEmail] = useState<string | null>(null)

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  usePageMeta({
    title: orgName ? `${orgName} — Set your password` : 'Set your password',
    noindex: true,
  })

  useEffect(() => {
    if (!token) {
      setStatus('not_found')
      return
    }
    const controller = new AbortController()
    axios
      .get<InviteStatusResponse>(`/e/api/auth/accept-invite/${encodeURIComponent(token)}`, {
        signal: controller.signal,
      })
      .then((res) => {
        const data = res.data
        setOrgName(data?.org_name ?? null)
        setEmail(data?.email ?? null)
        setStatus(data?.status ?? 'not_found')
      })
      .catch((err) => {
        if (axios.isCancel(err)) return
        setStatus('error')
      })
    return () => controller.abort()
  }, [token])

  const submit = useCallback(async (e: FormEvent) => {
    e.preventDefault()
    setSubmitError(null)
    if (password.length < 8 || password.length > 128) {
      setSubmitError('Password must be between 8 and 128 characters.')
      return
    }
    if (password !== confirm) {
      setSubmitError('Passwords do not match.')
      return
    }
    setSubmitting(true)
    try {
      await axios.post(`/e/api/auth/accept-invite/${encodeURIComponent(token ?? '')}`, {
        new_password: password,
      })
      setDone(true)
      // Route to the branded login to sign in with the new password.
      setTimeout(() => navigate(`/e/${encodeURIComponent(slug ?? '')}`, { replace: true }), 1500)
    } catch (err) {
      setSubmitError(mapSubmitError(err))
    } finally {
      setSubmitting(false)
    }
  }, [password, confirm, token, slug, navigate])

  const cardCls =
    'w-full max-w-md rounded-2xl border border-gray-200 bg-white p-8 shadow-sm'
  const inputCls =
    'mt-1 h-11 w-full rounded-lg border border-gray-300 px-3 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20'
  const labelCls = 'block text-sm font-medium text-gray-700'

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-10">
      {status === 'loading' ? (
        <div className={cardCls}>
          <div className="h-6 w-40 animate-pulse rounded bg-gray-100" />
          <div className="mt-4 h-11 animate-pulse rounded bg-gray-100" />
          <div className="mt-3 h-11 animate-pulse rounded bg-gray-100" />
        </div>
      ) : status === 'valid' ? (
        <div className={cardCls}>
          <h1 className="text-xl font-semibold text-gray-900">
            {orgName ? `Set your password — ${orgName}` : 'Set your password'}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {email ? <>Create a password for <span className="font-medium">{email}</span> to access your portal.</> : 'Create a password to access your portal.'}
          </p>

          {done ? (
            <div className="mt-6 rounded-lg bg-green-50 px-4 py-3 text-sm font-medium text-green-700">
              Password set. Taking you to sign in…
            </div>
          ) : (
            <form onSubmit={submit} className="mt-6 space-y-4">
              <div>
                <label htmlFor="ep-new-password" className={labelCls}>New password</label>
                <input
                  id="ep-new-password"
                  type="password"
                  autoComplete="new-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="At least 8 characters"
                  className={inputCls}
                  disabled={submitting}
                />
              </div>
              <div>
                <label htmlFor="ep-confirm-password" className={labelCls}>Confirm password</label>
                <input
                  id="ep-confirm-password"
                  type="password"
                  autoComplete="new-password"
                  required
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  placeholder="Re-enter your password"
                  className={inputCls}
                  disabled={submitting}
                />
              </div>

              {submitError && <p className="text-sm text-red-600">{submitError}</p>}

              <button
                type="submit"
                disabled={submitting}
                className="h-11 w-full rounded-lg bg-blue-600 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {submitting ? 'Setting password…' : 'Set password'}
              </button>
            </form>
          )}
        </div>
      ) : (
        <div className={cardCls}>
          <h1 className="text-xl font-semibold text-gray-900">
            {status === 'used' ? 'Invite already used' : status === 'expired' ? 'Invite expired' : 'Invite unavailable'}
          </h1>
          <p className="mt-2 text-sm text-gray-600">
            {status === 'used'
              ? 'This invite has already been used. You can sign in with the password you set.'
              : status === 'expired'
              ? 'This invite link has expired. Ask your administrator to send a new one.'
              : 'This invite link is not valid. Ask your administrator to send a new one.'}
          </p>
          <button
            onClick={() => navigate(`/e/${encodeURIComponent(slug ?? '')}`, { replace: true })}
            className="mt-6 h-11 w-full rounded-lg bg-blue-600 text-sm font-semibold text-white hover:opacity-90"
          >
            Go to sign in
          </button>
        </div>
      )}
    </div>
  )
}
