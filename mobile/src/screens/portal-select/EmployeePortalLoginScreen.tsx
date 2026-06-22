import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import axios from 'axios'
import { Page } from 'konsta/react'
import { MobileInput, MobileSpinner, MobileToast } from '@/components/ui'
import {
  usePortalSelection,
  type PortalSelection,
  type PortalType,
} from '@/contexts/PortalSelectionContext'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

/**
 * Branding fields returned by the Slug_Resolution_Endpoint
 * (`GET /api/v2/public/portal-resolve`) for the resolved organisation.
 * Every field is optional/nullable — an organisation may not have set a
 * logo or colours, in which case the neutral default presentation is used
 * without surfacing an error (R13.2).
 */
export interface PortalBranding {
  org_name?: string | null
  logo_url?: string | null
  primary_colour?: string | null
  secondary_colour?: string | null
}

/**
 * Navigation state handed to this screen by `OrgLookupScreen` (task 15.4)
 * after a successful resolve. Carries the resolved organisation identity,
 * the portal-aware API base, and the branding from the resolve response.
 */
export interface EmployeePortalLoginState {
  portal_type?: PortalType
  org_id?: string
  slug?: string
  api_base?: string
  org_name?: string
  /**
   * Branding from the resolve response. When the resolve returned a branding
   * object (even with all-null fields) this is present; when the resolve did
   * not return branding at all it is `undefined`/`null` and we fall back to
   * the neutral default + an error indication (R13.6).
   */
  branding?: PortalBranding | null
}

/** Neutral platform default colour used when an org has not set a primary colour. */
const DEFAULT_PRIMARY_COLOUR = '#2563eb' // blue-600
/** Max time (ms) we wait for branding before falling back to the neutral default (R13.6). */
const BRANDING_TIMEOUT_MS = 5_000

/* ------------------------------------------------------------------ */
/* Screen                                                             */
/* ------------------------------------------------------------------ */

/**
 * EmployeePortalLoginScreen — the org-branded employee portal login for the
 * mobile app.
 *
 * - Renders branding from the resolve response passed via route state (R13.5).
 * - Falls back to a neutral default presentation if branding is missing or
 *   slow to load (>5s) while keeping the login form fully usable (R13.6).
 * - On successful login, persists the portal selection so the selector is not
 *   shown again on the next app start (R11.1, R10.4).
 * - If persistence fails, the session still completes but the user is warned
 *   the selection could not be saved; because nothing was persisted, the
 *   selector is shown on the next start (R11.2).
 * - Calls `POST /e/api/auth/login` via the portal-aware base with
 *   `withCredentials: true` so the `emp_portal_session` + `emp_portal_csrf`
 *   cookies are established.
 *
 * Requirements: 10.4, 11.1, 11.2, 13.5, 13.6
 */
export default function EmployeePortalLoginScreen() {
  const navigate = useNavigate()
  const location = useLocation()
  const { save } = usePortalSelection()

  const state = (location.state ?? {}) as EmployeePortalLoginState
  const { org_id, slug, api_base } = state

  /* ---- branding state ------------------------------------------- */

  // When the resolve returned a branding object (even with null fields) we
  // have branding immediately. When it is absent we attempt a short fallback
  // fetch (≤5s) and otherwise render the neutral default + error indication.
  const initialBranding: PortalBranding | null = state.branding ?? null
  const canFetchBranding = !initialBranding && !!api_base && !!slug

  const [branding, setBranding] = useState<PortalBranding | null>(initialBranding)
  const [brandingLoading, setBrandingLoading] = useState<boolean>(canFetchBranding)
  const [brandingError, setBrandingError] = useState<boolean>(
    !initialBranding && !canFetchBranding,
  )
  const [logoFailed, setLogoFailed] = useState(false)

  useEffect(() => {
    if (!canFetchBranding) return

    const controller = new AbortController()
    // Treat a slow (>5s) branding response as "could not load" (R13.6).
    const timer = setTimeout(() => controller.abort(), BRANDING_TIMEOUT_MS)
    let cancelled = false

    async function loadBranding(signal: AbortSignal) {
      try {
        const res = await axios.get<PortalBranding>(
          `${api_base}/branding/${encodeURIComponent(slug ?? '')}`,
          { signal, timeout: BRANDING_TIMEOUT_MS, withCredentials: true },
        )
        if (cancelled) return
        setBranding(res.data ?? null)
        setBrandingError(!res.data)
      } catch {
        if (cancelled) return
        // Network error, timeout, or abort — render neutral default + warn.
        setBranding(null)
        setBrandingError(true)
      } finally {
        if (!cancelled) setBrandingLoading(false)
      }
    }

    void loadBranding(controller.signal)

    return () => {
      cancelled = true
      clearTimeout(timer)
      controller.abort()
    }
  }, [canFetchBranding, api_base, slug])

  const orgName = useMemo(
    () => branding?.org_name ?? state.org_name ?? slug ?? 'Employee Portal',
    [branding, state.org_name, slug],
  )
  const primaryColour = branding?.primary_colour ?? DEFAULT_PRIMARY_COLOUR
  const logoUrl = branding?.logo_url ?? null
  const showLogo = !!logoUrl && !logoFailed

  /* ---- form state ----------------------------------------------- */

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const dismissToast = useCallback(() => setToast(null), [])

  const emailError =
    email.length > 0 && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
      ? 'Please enter a valid email address'
      : undefined

  const canSubmit =
    email.length > 0 &&
    password.length > 0 &&
    !emailError &&
    !!api_base &&
    !!slug &&
    !isSubmitting

  // Keep a ref to the latest toast timer so navigation isn't blocked on it.
  const navTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => {
    if (navTimer.current) clearTimeout(navTimer.current)
  }, [])

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return
    setError(null)
    setIsSubmitting(true)

    try {
      // Establish the cookie session via the portal-aware base (R6.1, R6.2).
      await axios.post(
        `${api_base}/auth/login`,
        { slug, email: email.trim(), password },
        { withCredentials: true },
      )

      // Login succeeded — persist the selection so the selector is skipped on
      // the next start (R11.1, R10.4).
      const selection: PortalSelection = {
        portal_type: 'employee',
        api_base: api_base as string,
        ...(org_id ? { org_id } : {}),
        ...(slug ? { slug } : {}),
      }
      const saved = await save(selection)

      if (!saved) {
        // R11.2 — the session still completes, but warn the user; because the
        // selection was not persisted, the selector is shown on the next start.
        setToast(
          'Signed in, but your portal selection could not be saved. You may need to choose your portal again next time.',
        )
        navTimer.current = setTimeout(() => navigate('/', { replace: true }), 1500)
        return
      }

      navigate('/', { replace: true })
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response
        ?.data?.detail
      setError(detail ?? 'The email or password is invalid.')
      setIsSubmitting(false)
    }
  }, [canSubmit, api_base, slug, email, password, org_id, save, navigate])

  const handleFormSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      void handleSubmit()
    },
    [handleSubmit],
  )

  const goToSelector = useCallback(() => {
    navigate('/portal-select', { replace: true })
  }, [navigate])

  /* ---- missing navigation context (direct navigation) ----------- */

  if (!api_base || !slug) {
    return (
      <Page className="bg-white dark:bg-gray-900">
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
          <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            Portal not selected
          </h1>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            We couldn&apos;t determine which organisation to sign in to. Please
            look up your organisation again.
          </p>
          <button
            type="button"
            onClick={goToSelector}
            className="min-h-[44px] rounded-lg bg-blue-600 px-6 py-3 font-medium text-white active:bg-blue-700"
          >
            Choose portal
          </button>
        </div>
      </Page>
    )
  }

  /* ---- render --------------------------------------------------- */

  return (
    <Page className="bg-white dark:bg-gray-900">
      <MobileToast
        message={toast ?? ''}
        variant="error"
        isVisible={!!toast}
        onDismiss={dismissToast}
        duration={5000}
      />

      {/* Branded header — uses the org primary colour, neutral default otherwise */}
      <div
        className="px-6 pb-10 pt-16 text-center"
        style={{ backgroundColor: primaryColour }}
      >
        <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center overflow-hidden rounded-2xl bg-white/10 backdrop-blur-sm">
          {brandingLoading ? (
            <MobileSpinner size="sm" className="text-white" />
          ) : showLogo ? (
            <img
              src={logoUrl ?? undefined}
              alt={`${orgName} logo`}
              className="h-full w-full object-contain"
              onError={() => setLogoFailed(true)}
            />
          ) : (
            <DefaultPortalLogo />
          )}
        </div>
        <h1 className="text-2xl font-bold text-white">{orgName}</h1>
        <p className="mt-1 text-sm text-white/80">Employee portal sign in</p>
      </div>

      <div className="-mt-4 rounded-t-2xl bg-white px-4 pt-6 dark:bg-gray-900">
        {/* Branding-could-not-load indication (non-blocking — form stays usable, R13.6) */}
        {brandingError && (
          <div
            role="status"
            className="mb-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
          >
            Branding could not be loaded. You can still sign in below.
          </div>
        )}

        {/* Login error banner */}
        {error && (
          <div
            role="alert"
            className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
          >
            {error}
          </div>
        )}

        <form onSubmit={handleFormSubmit} noValidate>
          <div className="mb-4 flex flex-col gap-4">
            <MobileInput
              type="email"
              label="Email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              error={emailError}
              inputMode="email"
              autoComplete="email"
              autoCapitalize="none"
            />
            <MobileInput
              type="password"
              label="Password"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>

          <button
            type="submit"
            disabled={!canSubmit}
            aria-busy={isSubmitting || undefined}
            className="flex min-h-[44px] w-full items-center justify-center gap-2 rounded-lg px-4 py-3 text-base font-medium text-white transition-colors disabled:opacity-50"
            style={{ backgroundColor: primaryColour }}
          >
            {isSubmitting ? (
              <>
                <MobileSpinner size="sm" className="text-white" />
                Signing in…
              </>
            ) : (
              'Sign In'
            )}
          </button>
        </form>

        <div className="flex flex-col items-center gap-3 pb-8 pt-6">
          <button
            type="button"
            onClick={goToSelector}
            className="min-h-[44px] text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400 dark:active:text-blue-300"
          >
            Switch portal
          </button>
        </div>
      </div>
    </Page>
  )
}

/** Neutral platform default logo used when an org has not set a logo (R13.2). */
function DefaultPortalLogo() {
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
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  )
}
