/**
 * Organisation Employee Portal — branded login page.
 *
 * Route: ``/e/:slug`` (no auth — sits OUTSIDE RequireAuth/GuestOnly, exactly
 * like ``/public/staff-roster/:token`` and ``/onboard/:token``). Route
 * registration lives in ``App.tsx`` (task 14.3).
 *
 * API (cookie-auth portal surface, no JWT):
 *   - GET  /e/api/branding/{slug}   → { org_name, logo_url|null,
 *                                       primary_colour|null, secondary_colour|null }
 *                                     200 when the slug resolves AND the portal
 *                                     is enabled; neutral 404
 *                                     { code: "portal_unavailable" } otherwise.
 *   - POST /e/api/auth/login        → body { slug, email, password };
 *                                     200 sets the session + CSRF cookies;
 *                                     401/403/404 carry { message, code }.
 *
 * TRANSPORT — raw ``axios``, never the shared ``apiClient`` (which has a
 * ``/api/v1`` baseURL, a 401 interceptor that redirects to ``/login`` and
 * injects staff auth/branch headers — all wrong for a logged-out portal
 * visitor). We mirror ``StaffRosterPublicView`` / ``OnboardingFormPage`` and
 * use raw ``axios`` with ``withCredentials: true`` for the login POST so the
 * ``emp_portal_session`` / ``emp_portal_csrf`` cookies are stored.
 *
 * Behaviour:
 *   - Branded presentation from the branding payload (R8.1, R13.1).
 *   - Neutral "portal unavailable" page on a 404 — no login form, no
 *     existence leak (R8.3).
 *   - ``noindex`` robots meta injected on the page (R8.7).
 *   - Falls back to a neutral default presentation if branding is missing or
 *     slow (>2s) while keeping the login form usable (R13.2, R13.3).
 *   - On a successful login, routes into the authenticated app at
 *     ``/e/:slug/`` (R6.1).
 *
 * **Validates: Requirements 8.1, 8.3, 8.7, 13.1, 13.2, 13.3**
 */

import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import axios from 'axios'
import usePageMeta from '../../hooks/usePageMeta'

// ---------------------------------------------------------------------------
// Wire types — mirror app/modules/employee_portal/router.py.
// ---------------------------------------------------------------------------

interface BrandingResponse {
  org_name: string
  logo_url: string | null
  primary_colour: string | null
  secondary_colour: string | null
}

interface LoginSuccess {
  portal_user_id: string
  email: string
  first_name: string | null
  staff_id: string | null
}

/** Branding fetch lifecycle. ``available`` keeps the form usable even before
 *  (or without) branding; ``unavailable`` is the neutral 404 dead-end. */
type BrandingStatus = 'loading' | 'available' | 'unavailable'

// How long we wait for branding before showing the form with neutral defaults
// (R13.3 — "slow (>2s)" fallback while keeping the form usable).
const BRANDING_SLOW_FALLBACK_MS = 2000

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------

/**
 * Map a login failure to a friendly, anti-enumeration message. The backend
 * already returns identical 401 text regardless of whether the email exists
 * (R6.4); we surface its ``{message, code}`` when present and fall back to a
 * generic string otherwise.
 */
function mapLoginError(err: unknown): string {
  if (!axios.isAxiosError(err)) {
    return 'Something went wrong signing you in. Please try again.'
  }
  const status = err.response?.status
  const detail = (err.response?.data as { detail?: { message?: string; code?: string } } | undefined)
    ?.detail
  // Some endpoints return the body flat rather than under ``detail``.
  const flat = err.response?.data as { message?: string; code?: string } | undefined
  const message = detail?.message ?? flat?.message
  const code = detail?.code ?? flat?.code

  if (status === 429) {
    return 'Too many attempts. Please wait a moment and try again.'
  }
  if (status === 403) {
    return (
      message ??
      'This account is temporarily locked or the portal is unavailable. Please try again later.'
    )
  }
  if (status === 404) {
    return message ?? 'This portal is unavailable.'
  }
  if (code === 'invalid_credentials' || status === 401) {
    return message ?? 'Invalid email or password.'
  }
  return message ?? 'Something went wrong signing you in. Please try again.'
}

/** Validate that a colour string is a safe CSS colour before applying it as an
 *  inline style (defends against an unexpected payload injecting CSS). */
function safeColour(value: string | null | undefined): string | null {
  if (!value) return null
  const v = value.trim()
  // Accept #rgb / #rrggbb / #rrggbbaa and simple rgb()/rgba()/hsl() forms.
  if (/^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(v)) return v
  if (/^(?:rgb|rgba|hsl|hsla)\([0-9.,%\s/]+\)$/.test(v)) return v
  return null
}

export default function EmployeePortalLogin() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()

  const [branding, setBranding] = useState<BrandingResponse | null>(null)
  const [brandingStatus, setBrandingStatus] = useState<BrandingStatus>('loading')
  // Set true once the slow-branding timer elapses so the form renders with
  // neutral defaults while a slow fetch is still in flight (R13.3).
  const [slowFallback, setSlowFallback] = useState(false)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [loginError, setLoginError] = useState<string | null>(null)

  const slowTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Search engines must never index a tenant login page (R8.7).
  usePageMeta({
    title: branding?.org_name ? `${branding.org_name} — Employee Portal` : 'Employee Portal',
    noindex: true,
  })

  // ------------------------------------------------------------------
  // Mount-time branding fetch (R8.1, R8.3, R13.1–R13.3).
  // ------------------------------------------------------------------
  useEffect(() => {
    const controller = new AbortController()

    // Start the slow-branding fallback timer: if branding has not resolved
    // within 2s, reveal the form with neutral defaults (R13.3). We do NOT flip
    // to unavailable here — only a genuine 404 does that (R8.3).
    slowTimer.current = setTimeout(() => {
      setSlowFallback(true)
    }, BRANDING_SLOW_FALLBACK_MS)

    const fetchBranding = async () => {
      if (!slug) {
        setBrandingStatus('unavailable')
        return
      }

      setBrandingStatus('loading')
      try {
        const res = await axios.get<BrandingResponse>(
          `/e/api/branding/${encodeURIComponent(slug)}`,
          { signal: controller.signal },
        )
        if (controller.signal.aborted) return
        setBranding(res.data ?? null)
        setBrandingStatus('available')
      } catch (err) {
        if (controller.signal.aborted) return
        const status = axios.isAxiosError(err) ? err.response?.status : undefined
        if (status === 404) {
          // Neutral dead-end — slug unknown OR portal disabled. No form, no
          // existence leak (R8.3).
          setBrandingStatus('unavailable')
        } else {
          // Network / transient error: keep the form usable with neutral
          // defaults rather than blocking login (R13.2).
          setBranding(null)
          setBrandingStatus('available')
        }
      } finally {
        if (!controller.signal.aborted && slowTimer.current) {
          clearTimeout(slowTimer.current)
          slowTimer.current = null
        }
      }
    }

    void fetchBranding()
    return () => {
      controller.abort()
      if (slowTimer.current) {
        clearTimeout(slowTimer.current)
        slowTimer.current = null
      }
    }
  }, [slug])

  // ------------------------------------------------------------------
  // Login submit — raw axios POST with credentials so the session + CSRF
  // cookies are stored (R6.1). On success, route into the authenticated app.
  // ------------------------------------------------------------------
  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!slug || submitting) return

    setLoginError(null)
    setSubmitting(true)
    try {
      await axios.post<LoginSuccess>(
        '/e/api/auth/login',
        { slug, email: email.trim(), password },
        { withCredentials: true },
      )
      // Cookies are set by the response; route into the authenticated portal.
      navigate(`/e/${encodeURIComponent(slug)}/`, { replace: true })
    } catch (err) {
      setLoginError(mapLoginError(err))
    } finally {
      setSubmitting(false)
    }
  }

  // ------------------------------------------------------------------
  // Render.
  // ------------------------------------------------------------------

  /* ── Loading skeleton (branding in flight, slow-fallback not yet elapsed) ── */
  if (brandingStatus === 'loading' && !slowFallback) {
    return (
      <div
        className="flex items-center justify-center bg-gray-50 px-4"
        style={{ minHeight: '100vh' }}
        role="status"
        aria-label="Loading portal"
      >
        <div className="w-full max-w-sm animate-pulse space-y-4" aria-hidden="true">
          <div className="mx-auto h-12 w-12 rounded-full bg-gray-200" />
          <div className="mx-auto h-4 w-32 rounded bg-gray-200" />
          <div className="mt-6 h-10 rounded bg-gray-200" />
          <div className="h-10 rounded bg-gray-200" />
          <div className="h-10 rounded bg-gray-300" />
        </div>
        <span className="sr-only">Loading…</span>
      </div>
    )
  }

  /* ── Neutral unavailable page — no login form, no existence leak (R8.3) ── */
  if (brandingStatus === 'unavailable') {
    return (
      <div
        className="flex items-center justify-center bg-gray-50 px-4 py-8"
        style={{ minHeight: '100vh' }}
      >
        <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 text-center shadow-sm">
          <h1 className="text-lg font-semibold text-gray-900">This portal is unavailable</h1>
          <p className="mt-2 text-sm text-gray-600">
            We couldn&apos;t find a portal at this address. Please check the link, or contact your
            employer for the correct one.
          </p>
        </div>
      </div>
    )
  }

  /* ── Branded login form (branded when available, neutral default otherwise) ── */
  const orgName = branding?.org_name ?? null
  const logoUrl = branding?.logo_url ?? null
  const primary = safeColour(branding?.primary_colour)
  const secondary = safeColour(branding?.secondary_colour)

  const buttonStyle: CSSProperties = primary
    ? { backgroundColor: primary, borderColor: primary }
    : {}

  const inputCls =
    'mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500'
  const labelCls = 'block text-sm font-medium text-gray-700'

  return (
    <div
      className="flex items-center justify-center bg-gray-50 px-4 py-8"
      style={{ minHeight: '100vh' }}
    >
      <div className="w-full max-w-sm">
        <header className="mb-6 text-center">
          {logoUrl ? (
            <img
              src={logoUrl}
              alt={orgName ? `${orgName} logo` : 'Organisation logo'}
              className="mx-auto h-14 w-auto object-contain"
            />
          ) : (
            <div
              className="mx-auto flex h-14 w-14 items-center justify-center rounded-full text-xl font-semibold text-white"
              style={{ backgroundColor: primary ?? '#4f46e5' }}
              aria-hidden="true"
            >
              {(orgName ?? 'E').charAt(0).toUpperCase()}
            </div>
          )}
          <h1 className="mt-4 text-xl font-semibold text-gray-900">
            {orgName ? `Sign in to ${orgName}` : 'Employee portal sign in'}
          </h1>
          <p className="mt-1 text-sm text-gray-600">
            Use the credentials your employer issued for the staff portal.
          </p>
        </header>

        <form
          onSubmit={handleSubmit}
          className="space-y-4 rounded-lg border border-gray-200 bg-white p-6 shadow-sm"
          noValidate
        >
          {loginError && (
            <div
              role="alert"
              className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
            >
              {loginError}
            </div>
          )}

          <div>
            <label htmlFor="emp-portal-email" className={labelCls}>
              Email
            </label>
            <input
              id="emp-portal-email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputCls}
              disabled={submitting}
            />
          </div>

          <div>
            <label htmlFor="emp-portal-password" className={labelCls}>
              Password
            </label>
            <input
              id="emp-portal-password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputCls}
              disabled={submitting}
            />
          </div>

          <button
            type="submit"
            disabled={submitting || !email.trim() || !password}
            style={buttonStyle}
            className="flex w-full items-center justify-center rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>

          <div className="text-center">
            <a
              href={slug ? `/e/${encodeURIComponent(slug)}/forgot-password` : '#'}
              className="text-xs font-medium text-gray-500 hover:text-gray-700"
              style={secondary ? { color: secondary } : undefined}
            >
              Forgot your password?
            </a>
          </div>
        </form>

        <footer className="mt-6 text-center text-xs text-gray-400">
          {orgName ? `${orgName} staff portal` : 'Staff portal'}
        </footer>
      </div>
    </div>
  )
}
