/**
 * Fleet Portal API client.
 *
 * Separate axios instance scoped to /fleet/api/* — uses cookie auth
 * (no Bearer token) and the double-submit CSRF pattern (read the
 * fleet_portal_csrf cookie, send as X-CSRF-Token header).
 *
 * Implements: B2B Fleet Portal task 14.1 — Requirements 19.1, 19.4, 19.5.
 */
import axios, { AxiosError, AxiosInstance, InternalAxiosRequestConfig } from 'axios'

const SESSION_COOKIE = 'fleet_portal_session'
const CSRF_COOKIE = 'fleet_portal_csrf'
const CSRF_HEADER = 'X-CSRF-Token'

const STATE_CHANGING = new Set(['post', 'put', 'patch', 'delete'])

/**
 * Read a cookie value by name. Returns null when the cookie is missing.
 *
 * Mirrors the existing `getPortalCsrfCookie` pattern in
 * `frontend/src/api/client.ts` so the auth UX feels identical between
 * the legacy customer portal and the fleet portal.
 */
export function getFleetPortalCookie(name: string): string | null {
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${name.replace(/[.$?*|{}()[\\]\\\\+]/g, '\\$&')}=([^;]*)`),
  )
  return match ? decodeURIComponent(match[1]) : null
}

/**
 * Inject the CSRF header on state-changing requests.
 *
 * GET / HEAD / OPTIONS are exempt — the backend dependency
 * (`validate_fleet_portal_csrf`) skips them too.
 */
function injectCsrfHeader(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  const method = (config.method ?? 'get').toLowerCase()
  if (!STATE_CHANGING.has(method)) return config
  const token = getFleetPortalCookie(CSRF_COOKIE)
  if (token) {
    config.headers = config.headers ?? {}
    ;(config.headers as Record<string, string>)[CSRF_HEADER] = token
  }
  return config
}

/**
 * Returns the configured axios instance for `/fleet/api/*` calls.
 *
 * `withCredentials: true` sends the HttpOnly session cookie on
 * cross-origin XHRs (required for `fleet.<domain>` deployments).
 */
export const fleetClient: AxiosInstance = axios.create({
  baseURL: '/fleet/api',
  withCredentials: true,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

fleetClient.interceptors.request.use(injectCsrfHeader)

/**
 * On 401 from any fleet API call, clear local session state and let the
 * router redirect to /fleet/login. The actual navigation is performed
 * by the FleetSessionContext consumer when it sees `null` for the
 * current user.
 */
fleetClient.interceptors.response.use(
  (res) => res,
  (err: AxiosError) => {
    if (err.response?.status === 401) {
      // Bubble up; FleetSessionContext clears its state on 401.
      window.dispatchEvent(new CustomEvent('fleet:session-expired'))
    }
    return Promise.reject(err)
  },
)

export { SESSION_COOKIE, CSRF_COOKIE, CSRF_HEADER }
