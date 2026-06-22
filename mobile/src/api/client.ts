import axios from 'axios'
import { Capacitor } from '@capacitor/core'
import type { PortalSelection, PortalType } from '@/contexts/PortalSelectionContext'

let accessToken: string | null = null

/**
 * Global refresh mutex — ensures only ONE refresh request is in-flight
 * across the entire app (AuthContext restore + 401 interceptor).
 */
let refreshPromise: Promise<string | null> | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function getAccessToken(): string | null {
  return accessToken
}

/** Check if the current access token is still valid (not expired). */
export function isAccessTokenValid(): boolean {
  if (!accessToken) return false
  try {
    const base64 = accessToken.split('.')[1]
    const payload = JSON.parse(atob(base64.replace(/-/g, '+').replace(/_/g, '/')))
    // Consider expired if less than 60 seconds remaining
    return payload.exp * 1000 > Date.now() + 60_000
  } catch {
    return false
  }
}

// On native Capacitor, API calls go to the production backend origin.
// On web (served behind nginx), relative paths work via the reverse proxy.
const NATIVE_API_ORIGIN = 'https://devin.oraflow.co.nz'

/**
 * The API origin (scheme + host, no path) to target. Native builds hit the
 * production backend directly; web builds use relative paths so nginx proxies.
 *
 * Exported for the portal selector screens, which compute and persist the
 * resolved `api_base` into the PortalSelection at selection time.
 */
export function defaultApiOrigin(): string {
  return Capacitor.isNativePlatform() ? NATIVE_API_ORIGIN : ''
}

/**
 * Pure, deterministic resolution of the API base/origin for a portal type.
 *
 * - `org`      → `…/api/v1`   (JWT auth, unchanged)
 * - `employee` → `…/e/api`    (cookie session + double-submit CSRF)
 * - `fleet`    → `…/fleet/api` (cookie session + double-submit CSRF)
 *
 * Given the same `(portalType, origin)` it always returns the same base, so a
 * persisted selection resolves to the same backend surface on every restart
 * (R11.8). Exported for property testing (Property 23) and the selector screens.
 *
 * **Validates: Requirements 11.8**
 */
export function resolveApiBase(
  portalType: PortalType,
  origin: string = defaultApiOrigin(),
): string {
  switch (portalType) {
    case 'employee':
      return `${origin}/e/api`
    case 'fleet':
      return `${origin}/fleet/api`
    case 'org':
    default:
      return `${origin}/api/v1`
  }
}

/** True for portal types that authenticate via cookies + CSRF rather than a JWT. */
export function isCookiePortal(portalType: PortalType | undefined | null): boolean {
  return portalType === 'employee' || portalType === 'fleet'
}

/**
 * The readable (non-HttpOnly) double-submit CSRF cookie name for a cookie
 * portal, echoed back as the `X-CSRF-Token` header on state-changing requests.
 * Returns `null` for the org portal (JWT, no CSRF cookie).
 */
export function csrfCookieName(portalType: PortalType | undefined | null): string | null {
  if (portalType === 'employee') return 'emp_portal_csrf'
  if (portalType === 'fleet') return 'fleet_portal_csrf'
  return null
}

/** Read a cookie value by name from `document.cookie`. Returns null if absent. */
function readCookie(name: string): string | null {
  if (typeof document === 'undefined' || !document.cookie) return null
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = document.cookie.match(new RegExp('(?:^|;\\s*)' + escaped + '=([^;]*)'))
  return match?.[1] ? decodeURIComponent(match[1]) : null
}

/* ------------------------------------------------------------------ */
/* Active portal selection (drives base + auth-model resolution)       */
/* ------------------------------------------------------------------ */

/**
 * The currently active portal selection, kept in memory so the request
 * interceptor can deterministically target the right backend surface and pick
 * the right auth model (Bearer JWT for `org`; cookies + CSRF for cookie
 * portals). `null` defaults to the org portal so the existing org-user flow is
 * unchanged when no portal has been selected (R17.4).
 */
let activePortal: PortalSelection | null = null

export function setActivePortal(sel: PortalSelection | null): void {
  activePortal = sel
}

export function getActivePortal(): PortalSelection | null {
  return activePortal
}

function activePortalType(): PortalType {
  return activePortal?.portal_type ?? 'org'
}

/* ------------------------------------------------------------------ */
/* Portal session-rejection handler (R11.9, R12.5, R12.6)              */
/* ------------------------------------------------------------------ */

/** Reason a cookie-portal request was rejected, surfaced to AuthContext. */
export type PortalRejectionReason = 'session_invalid' | 'portal_unavailable' | 'unreachable'

export type PortalRejectionHandler = (
  reason: PortalRejectionReason,
  selection: PortalSelection | null,
) => void

let portalRejectionHandler: PortalRejectionHandler | null = null

/**
 * Register a callback invoked when an authenticated cookie-portal request is
 * rejected, so AuthContext can route appropriately:
 * - `session_invalid` (401) → branded login for the persisted org (R12.5)
 * - `portal_unavailable` (403) → "portal unavailable" + switch-portal (R11.6/R11.7/R12.6)
 * - `unreachable` (network/base error) → clear selection, error, selector (R11.9)
 */
export function setPortalRejectionHandler(fn: PortalRejectionHandler | null): void {
  portalRejectionHandler = fn
}

const apiBaseURL = resolveApiBase('org')

const apiClient = axios.create({
  baseURL: apiBaseURL,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true, // send httpOnly refresh / portal session cookie
})

/**
 * Pure function that determines whether the X-Branch-Id header should be
 * injected and what value it should have.
 *
 * Returns the branch ID string when a specific branch is selected,
 * or null when "All Branches" (null / "all") is selected.
 *
 * Exported for property-based testing.
 *
 * **Validates: Requirements 13.4, 44.2, 44.3**
 */
export function resolveBranchHeader(branchId: string | null): string | null {
  if (!branchId || branchId === 'all') return null
  return branchId
}

apiClient.interceptors.request.use((config) => {
  const portalType = activePortalType()

  // Cookie-auth portals (employee / fleet): no Bearer token. Target the
  // portal's API base deterministically from the persisted selection and rely
  // on `withCredentials` cookies. State-changing requests echo the readable
  // CSRF cookie as the X-CSRF-Token header (double-submit, R6.7/R6.8).
  if (isCookiePortal(portalType)) {
    const base = activePortal?.api_base
    if (base) {
      config.baseURL = base
    }
    config.withCredentials = true

    const method = (config.method ?? 'get').toLowerCase()
    const isStateChanging =
      method !== 'get' && method !== 'head' && method !== 'options'
    if (isStateChanging) {
      const cookieName = csrfCookieName(portalType)
      const csrf = cookieName ? readCookie(cookieName) : null
      if (csrf) {
        config.headers['X-CSRF-Token'] = csrf
      }
    }
    return config
  }

  // Org portal — existing JWT flow, unchanged.
  // Inject Bearer token from in-memory store
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }

  // Inject X-Branch-Id header from localStorage when a specific branch is selected.
  // If the value is null or "all", omit the header so the backend returns all-branch data.
  const branchId = localStorage.getItem('selected_branch_id')
  const resolved = resolveBranchHeader(branchId)
  if (resolved) {
    config.headers['X-Branch-Id'] = resolved
  }

  // Fix v2 URL paths: calls using `/api/v2/...` would get double-prefixed
  // as `/api/v1/api/v2/...` because baseURL is `/api/v1`.
  // Strip the baseURL for absolute API paths so they resolve correctly.
  const url = config.url ?? ''
  if (url.startsWith('/api/')) {
    config.baseURL = ''
  }

  return config
})

/**
 * Perform a single refresh-token exchange.
 * Uses raw axios (NOT apiClient) to avoid triggering the 401 interceptor
 * recursively if the refresh itself returns 401.
 *
 * Deduplicates concurrent callers via `refreshPromise` — if a refresh is
 * already in-flight, every subsequent caller gets back the same promise.
 *
 * The resolved promise is kept for a short grace period (10s) so that
 * React StrictMode's unmount→remount cycle reuses the result instead of
 * firing a second HTTP request.
 */
export function doTokenRefresh(): Promise<string | null> {
  if (refreshPromise) return refreshPromise

  refreshPromise = (async () => {
    try {
      const refreshURL = Capacitor.isNativePlatform()
        ? 'https://devin.oraflow.co.nz/api/v1/auth/token/refresh'
        : '/api/v1/auth/token/refresh'
      const res = await axios.post<{ access_token: string }>(
        refreshURL,
        {},
        { withCredentials: true },
      )
      const newToken = res.data.access_token
      setAccessToken(newToken)
      return newToken
    } catch {
      setAccessToken(null)
      return null
    }
  })()

  refreshPromise.finally(() => {
    setTimeout(() => {
      refreshPromise = null
    }, 10_000)
  })

  return refreshPromise
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    const portalType = activePortalType()
    const status = error.response?.status

    // Cookie-auth portals: never attempt a JWT refresh or redirect to the
    // org login. Hand the rejection to AuthContext so it can route per the
    // portal rules (branded login on 401, portal-unavailable on 403, or
    // selector when the base is unreachable).
    if (isCookiePortal(portalType)) {
      if (original && !original._portalHandled) {
        original._portalHandled = true
        if (status === 401) {
          portalRejectionHandler?.('session_invalid', activePortal)
        } else if (status === 403) {
          portalRejectionHandler?.('portal_unavailable', activePortal)
        } else if (status === undefined) {
          // No response → network / unresolvable base (R11.9)
          portalRejectionHandler?.('unreachable', activePortal)
        }
      }
      return Promise.reject(error)
    }

    // Don't intercept 401 from the refresh endpoint itself
    const url = original?.url ?? ''
    const isRefreshCall =
      url.includes('/auth/token/refresh') ||
      url.includes('auth/token/refresh')

    // Don't intercept 401 from MFA endpoints
    const isMfaCall =
      url.includes('/auth/mfa/') ||
      url.includes('/auth/passkey/login/')

    if (status === 401 && !original._retry && !isRefreshCall && !isMfaCall) {
      original._retry = true

      const newToken = await doTokenRefresh()
      if (newToken) {
        original.headers.Authorization = `Bearer ${newToken}`
        return apiClient(original)
      }

      // Refresh failed — clear token and redirect to login
      setAccessToken(null)
      const path = window.location.pathname
      const isAlreadyOnLogin =
        path === '/login' ||
        path === '/forgot-password' ||
        path === '/mobile/login' ||
        path === '/mobile/forgot-password'
      if (!isAlreadyOnLogin) {
        // On native Capacitor, basename is / so navigate to /login
        // On web, basename is /mobile so navigate to /mobile/login
        const loginPath = Capacitor.isNativePlatform() ? '/login' : '/mobile/login'
        window.location.replace(loginPath)
      }
    }
    return Promise.reject(error)
  },
)

export default apiClient
