import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Capacitor } from '@capacitor/core'
import { Page } from 'konsta/react'
import apiClient from '@/api/client'
import { MobileInput, MobileSpinner } from '@/components/ui'
import { usePortalSelection, type PortalType } from '@/contexts/PortalSelectionContext'
import type {
  EmployeePortalLoginState,
  PortalBranding,
} from './EmployeePortalLoginScreen'
import { useOffline } from '@/contexts/OfflineContext'

/* ------------------------------------------------------------------ */
/* Constants                                                          */
/* ------------------------------------------------------------------ */

/** Route the branded employee-portal login lives at (registered in StackRoutes). */
const EMPLOYEE_LOGIN_PATH = '/portal-select/employee-login'
/** Route the first-run portal-type selector lives at. */
const SELECTOR_PATH = '/portal-select'
/** The public Slug_Resolution_Endpoint (mobile lookup). */
const RESOLVE_PATH = '/api/v2/public/portal-resolve'
/** Max time we wait for a resolve before treating it as failed (R10.7, R12.3). */
const RESOLVE_TIMEOUT_MS = 10_000
/** Max length of the name-or-slug input (R10.3). */
const MAX_QUERY_LEN = 100

const NOT_FOUND_MSG =
  'We couldn’t find an organisation with that name or code, or its portal isn’t enabled. Check the spelling and try again.'
const TIMEOUT_MSG =
  'The lookup took too long to complete. Check your connection and try again.'
const FAILURE_MSG =
  'The lookup could not be completed. Check your connection and try again.'
const OFFLINE_MSG =
  'A network connection is required to look up your organisation. Reconnect and try again.'

/* ------------------------------------------------------------------ */
/* API response types (consumed safely — typed generics, no `as any`) */
/* ------------------------------------------------------------------ */

interface ResolveBranding {
  logo_url?: string | null
  primary_colour?: string | null
  secondary_colour?: string | null
}

interface ResolveMatch {
  org_id?: string
  org_name?: string
  branding?: ResolveBranding | null
}

interface ResolveCandidate {
  org_name?: string
  branding?: ResolveBranding | null
}

interface ResolveResponse {
  match?: ResolveMatch | null
  candidates?: ResolveCandidate[] | null
}

type LookupState = 'idle' | 'loading' | 'candidates' | 'error'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

/**
 * Resolve the API base/origin for the chosen cookie-auth portal, mirroring the
 * base resolution in `api/client.ts`: native targets the production backend,
 * web uses the nginx reverse-proxy relative path. The employee portal API is
 * mounted at `/e/api`, the fleet portal at `/fleet/api` (R11.8).
 */
export function resolvePortalApiBase(portalType: PortalType): string {
  const origin = Capacitor.isNativePlatform() ? 'https://devin.oraflow.co.nz' : ''
  return portalType === 'fleet' ? `${origin}/fleet/api` : `${origin}/e/api`
}

/** Normalise a candidate slug the same way the backend does — trim + lowercase. */
function normaliseSlug(raw: string): string {
  return raw.trim().toLowerCase()
}

/* ------------------------------------------------------------------ */
/* Screen                                                             */
/* ------------------------------------------------------------------ */

/**
 * OrgLookupScreen — the mobile org lookup for the Employee/Staff and Fleet
 * portals (reached from `PortalTypeSelector`, which carries the chosen
 * `portal_type` in route state).
 *
 * - Name-or-slug input, 1..100 characters (R10.3).
 * - On submit, calls `GET /api/v2/public/portal-resolve?q=&portal_type=` with a
 *   10-second timeout while showing a spinner and disabling the submit control
 *   (R10.5). The request runs inside an effect that uses an `AbortController`
 *   so it is cancelled on unmount / re-submit / timeout.
 * - Exactly one match → routes to the branded login with the resolved org +
 *   branding (R10.4).
 * - More than one name match → a disambiguation list; tapping a candidate
 *   re-resolves by that organisation's name (R9.4 — never auto-resolve).
 * - None / portal disabled → a visible inline error that retains the entered
 *   input and allows re-entry (R10.6, R12.1, R12.2).
 * - Timeout or network/server failure → a visible error with a retry action
 *   that re-runs the lookup with the same input, retaining it (R10.7, R12.3).
 * - Offline with no persisted selection → a "network required" message; the
 *   screen never renders blank (R12.4).
 *
 * Requirements: 10.3, 10.5, 10.6, 10.7, 12.1, 12.2, 12.3, 12.4
 */
export default function OrgLookupScreen() {
  const navigate = useNavigate()
  const location = useLocation()
  const { isOnline } = useOffline()
  const { selection } = usePortalSelection()

  const navState = (location.state ?? {}) as { portal_type?: PortalType }
  // The selector only routes Employee/Staff and Fleet here; default to
  // employee if the screen is reached without explicit state.
  const portalType: PortalType =
    navState.portal_type === 'fleet' ? 'fleet' : 'employee'
  const resolvePortalType: 'employee' | 'fleet' =
    portalType === 'fleet' ? 'fleet' : 'employee'

  const portalLabel = portalType === 'fleet' ? 'fleet' : 'staff'

  /* ---- input + lookup state ------------------------------------- */

  const [query, setQuery] = useState('')
  const [lookupState, setLookupState] = useState<LookupState>('idle')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [candidates, setCandidates] = useState<ResolveCandidate[]>([])

  // The query value captured at submit time, and a monotonically increasing
  // trigger the resolve effect keys off. Bumping `runId` (re-)runs the lookup;
  // `activeQuery` keeps the exact value being resolved so retry re-uses it
  // (R10.7, R12.2) even if the user keeps typing.
  const [activeQuery, setActiveQuery] = useState('')
  const [runId, setRunId] = useState(0)

  const trimmed = query.trim()
  const offlineBlocked = !isOnline && !selection
  const canSubmit =
    trimmed.length >= 1 &&
    trimmed.length <= MAX_QUERY_LEN &&
    lookupState !== 'loading' &&
    !offlineBlocked

  /* ---- navigation to the branded login -------------------------- */

  const goToLogin = useCallback(
    (match: ResolveMatch, slugQuery: string) => {
      const branding: PortalBranding = {
        org_name: match.org_name ?? null,
        logo_url: match.branding?.logo_url ?? null,
        primary_colour: match.branding?.primary_colour ?? null,
        secondary_colour: match.branding?.secondary_colour ?? null,
      }
      const loginState: EmployeePortalLoginState = {
        portal_type: portalType,
        api_base: resolvePortalApiBase(portalType),
        // The resolve endpoint returns the org name + branding (and org_id for
        // a single match) but not the slug; the slug the branded login needs is
        // the value the user entered (the dominant case is entering the slug).
        slug: normaliseSlug(slugQuery),
        ...(match.org_id ? { org_id: match.org_id } : {}),
        org_name: match.org_name ?? undefined,
        branding,
      }
      navigate(EMPLOYEE_LOGIN_PATH, { state: loginState })
    },
    [navigate, portalType],
  )

  /* ---- resolve effect (AbortController-driven) ------------------ */

  // Keep the active query in a ref so the effect (keyed only on runId) always
  // resolves the latest captured value without re-subscribing on every keystroke.
  const activeQueryRef = useRef(activeQuery)
  activeQueryRef.current = activeQuery

  useEffect(() => {
    if (runId === 0) return // no lookup requested yet

    const q = activeQueryRef.current
    const controller = new AbortController()
    let timedOut = false

    const timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, RESOLVE_TIMEOUT_MS)

    async function run() {
      setLookupState('loading')
      setErrorMsg(null)
      setCandidates([])
      try {
        const res = await apiClient.get<ResolveResponse>(RESOLVE_PATH, {
          params: { q, portal_type: resolvePortalType },
          signal: controller.signal,
        })
        if (controller.signal.aborted) return

        const match = res.data?.match ?? null
        const found = res.data?.candidates ?? []

        if (match) {
          // Exactly one organisation matched + enabled → branded login (R10.4).
          goToLogin(match, q)
          return
        }
        if (found.length > 0) {
          // More than one NAME match → disambiguation; never auto-resolve (R9.4).
          setCandidates(found)
          setLookupState('candidates')
          return
        }
        // Defensive: a 200 with neither shape — treat as not found (R10.6).
        setErrorMsg(NOT_FOUND_MSG)
        setLookupState('error')
      } catch (err: unknown) {
        // Cleanup abort (unmount / re-submit) — ignore, never touch state.
        if (controller.signal.aborted && !timedOut) return

        const status = (
          err as { response?: { status?: number } } | undefined
        )?.response?.status

        if (status === 404) {
          // None matched, or the portal type is disabled (R10.6, R12.1).
          setErrorMsg(NOT_FOUND_MSG)
        } else if (timedOut) {
          // No response within 10s (R10.7, R12.3).
          setErrorMsg(TIMEOUT_MSG)
        } else {
          // Network or server error (R12.1).
          setErrorMsg(FAILURE_MSG)
        }
        setLookupState('error')
      } finally {
        clearTimeout(timer)
      }
    }

    void run()

    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [runId, resolvePortalType, goToLogin])

  /* ---- handlers -------------------------------------------------- */

  const submit = useCallback(() => {
    if (!canSubmit) return
    setActiveQuery(trimmed)
    setRunId((r) => r + 1)
  }, [canSubmit, trimmed])

  const handleFormSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      submit()
    },
    [submit],
  )

  // Retry re-runs the lookup with the SAME captured input (R10.7, R12.2).
  const retry = useCallback(() => {
    if (lookupState === 'loading' || offlineBlocked) return
    setRunId((r) => r + 1)
  }, [lookupState, offlineBlocked])

  // Re-resolve by the chosen organisation's name (disambiguation, R9.4).
  const pickCandidate = useCallback(
    (name: string | undefined | null) => {
      const value = (name ?? '').slice(0, MAX_QUERY_LEN)
      if (!value.trim()) return
      setQuery(value)
      setActiveQuery(value.trim())
      setRunId((r) => r + 1)
    },
    [],
  )

  const goToSelector = useCallback(() => {
    navigate(SELECTOR_PATH, { replace: true })
  }, [navigate])

  /* ---- render ---------------------------------------------------- */

  const isLoading = lookupState === 'loading'

  return (
    <Page className="bg-white dark:bg-gray-900">
      {/* Header */}
      <div
        className="bg-gradient-to-b from-slate-900 to-indigo-900 px-6 pb-10 text-center"
        style={{ paddingTop: 'calc(env(safe-area-inset-top, 0px) + 3.5rem)' }}
      >
        <h1 className="text-2xl font-bold text-white">Find your organisation</h1>
        <p className="mt-1 text-sm text-indigo-200">
          Enter your organisation’s name or portal code to reach your{' '}
          {portalLabel} sign-in.
        </p>
      </div>

      <div className="-mt-4 rounded-t-2xl bg-white px-4 pt-6 dark:bg-gray-900">
        {/* Offline + no persisted selection — never blank (R12.4) */}
        {offlineBlocked && (
          <div
            role="status"
            className="mb-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
          >
            {OFFLINE_MSG}
          </div>
        )}

        {/* Error banner with retry (R10.6, R10.7, R12.1–R12.3) */}
        {lookupState === 'error' && errorMsg && (
          <div
            role="alert"
            className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
          >
            <p>{errorMsg}</p>
            <button
              type="button"
              onClick={retry}
              disabled={offlineBlocked}
              className="mt-2 inline-flex min-h-[44px] items-center rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white active:bg-red-700 disabled:opacity-50 dark:bg-red-500 dark:active:bg-red-600"
            >
              Try again
            </button>
          </div>
        )}

        <form onSubmit={handleFormSubmit} noValidate>
          <MobileInput
            label="Organisation name or code"
            placeholder="e.g. acme or Acme Auto"
            value={query}
            onChange={(e) => setQuery(e.target.value.slice(0, MAX_QUERY_LEN))}
            maxLength={MAX_QUERY_LEN}
            autoCapitalize="none"
            autoCorrect="off"
            autoComplete="off"
            enterKeyHint="search"
            disabled={isLoading}
          />

          <button
            type="submit"
            disabled={!canSubmit}
            aria-busy={isLoading || undefined}
            className="mt-4 flex min-h-[44px] w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-3 text-base font-medium text-white transition-colors active:bg-blue-700 disabled:opacity-50 dark:bg-blue-500 dark:active:bg-blue-600"
          >
            {isLoading ? (
              <>
                <MobileSpinner size="sm" className="text-white" />
                Searching…
              </>
            ) : (
              'Continue'
            )}
          </button>
        </form>

        {/* Disambiguation list (R9.4) */}
        {lookupState === 'candidates' && candidates.length > 0 && (
          <div className="mt-6">
            <p className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-300">
              Multiple organisations match. Choose yours:
            </p>
            <ul className="flex flex-col gap-2" role="list">
              {candidates.map((c, i) => (
                <li key={`${c.org_name ?? 'org'}-${i}`}>
                  <button
                    type="button"
                    onClick={() => pickCandidate(c.org_name)}
                    className="flex min-h-[44px] w-full items-center gap-3 rounded-xl border border-gray-200 bg-white px-4 py-3 text-left active:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:active:bg-gray-700"
                  >
                    <span
                      className="flex h-10 w-10 flex-shrink-0 items-center justify-center overflow-hidden rounded-lg bg-indigo-50 dark:bg-indigo-900/30"
                      aria-hidden="true"
                    >
                      {c.branding?.logo_url ? (
                        <img
                          src={c.branding.logo_url}
                          alt=""
                          className="h-full w-full object-contain"
                        />
                      ) : (
                        <BuildingIcon />
                      )}
                    </span>
                    <span className="flex-1 text-base font-medium text-gray-900 dark:text-white">
                      {c.org_name ?? 'Organisation'}
                    </span>
                    <ChevronRightIcon />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-col items-center gap-3 pb-8 pt-6">
          <button
            type="button"
            onClick={goToSelector}
            className="min-h-[44px] text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400 dark:active:text-blue-300"
          >
            Back to portal selection
          </button>
        </div>
      </div>
    </Page>
  )
}

/* ------------------------------------------------------------------ */
/* Icons                                                              */
/* ------------------------------------------------------------------ */

function BuildingIcon() {
  return (
    <svg
      className="h-5 w-5 text-indigo-600 dark:text-indigo-400"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3 21h18" />
      <path d="M5 21V7l8-4v18" />
      <path d="M19 21V11l-6-4" />
    </svg>
  )
}

function ChevronRightIcon() {
  return (
    <svg
      className="h-5 w-5 flex-shrink-0 text-gray-400 dark:text-gray-500"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="9 18 15 12 9 6" />
    </svg>
  )
}
