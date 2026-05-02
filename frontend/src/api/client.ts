import axios from 'axios'

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

const apiClient = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true, // send httpOnly refresh cookie
})

/**
 * Read the portal_csrf cookie value set by the backend on portal
 * session creation.  The cookie is non-HttpOnly so JavaScript can
 * read it for the double-submit CSRF pattern (Req 41.1, 41.2).
 */
function getPortalCsrfCookie(): string | null {
  const match = document.cookie
    .split('; ')
    .find((row) => row.startsWith('portal_csrf='))
  return match ? decodeURIComponent(match.split('=')[1]) : null
}

apiClient.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }

  // Inject X-Branch-Id header from localStorage when a specific branch is selected.
  // If the value is null or "all", omit the header so the backend returns all-branch data.
  const branchId = localStorage.getItem('selected_branch_id')
  if (branchId && branchId !== 'all') {
    config.headers['X-Branch-Id'] = branchId
  }

  // Portal CSRF double-submit: read the portal_csrf cookie and send it
  // as X-CSRF-Token header on state-changing requests (Req 41.1, 41.2).
  const method = (config.method ?? '').toUpperCase()
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    const csrfToken = getPortalCsrfCookie()
    if (csrfToken) {
      config.headers['X-CSRF-Token'] = csrfToken
    }
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
 * This is the ONLY function that should call /auth/token/refresh.
 * It deduplicates concurrent callers via `refreshPromise` — if a refresh is
 * already in-flight, every subsequent caller gets back the same promise
 * instead of starting a new HTTP request.
 *
 * The resolved promise is kept for a short grace period (2s) so that
 * React StrictMode's unmount→remount cycle reuses the result instead of
 * firing a second HTTP request.
 */
export function doTokenRefresh(): Promise<string | null> {
  // If a refresh is already in-flight (or recently resolved), reuse it.
  if (refreshPromise) return refreshPromise

  refreshPromise = (async () => {
    try {
      const res = await axios.post<{ access_token: string }>(
        '/api/v1/auth/token/refresh',
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

  // Keep the promise cached for 10 seconds after it settles so that
  // StrictMode's second mount AND Vite HMR invalidation cascades
  // (which can remount the entire component tree multiple times in
  // quick succession) reuse the result instead of firing a new request
  // with the already-rotated (now-revoked) cookie — which would trigger
  // reuse detection and kill the entire session family.
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

    // Don't intercept 401 from the refresh endpoint itself — that means
    // the refresh token is truly gone. Let it bubble up normally.
    const url = original?.url ?? ''
    const isRefreshCall =
      url.includes('/auth/token/refresh') ||
      url.includes('auth/token/refresh')

    // Don't intercept 401 from MFA endpoints — those use mfa_token (not JWT)
    // and should be handled by the MfaVerify component directly.
    const isMfaCall =
      url.includes('/auth/mfa/') ||
      url.includes('/auth/passkey/login/')

    if (error.response?.status === 401 && !original._retry && !isRefreshCall && !isMfaCall) {
      original._retry = true

      const newToken = await doTokenRefresh()
      if (newToken) {
        original.headers.Authorization = `Bearer ${newToken}`
        return apiClient(original)
      }

      // Refresh failed — clear token and redirect to login to avoid
      // a white/blank page when the session is truly gone (e.g. org deleted).
      setAccessToken(null)
      const path = window.location.pathname
      if (path !== '/login' && path !== '/signup' && path !== '/forgot-password') {
        window.location.replace('/login')
      }
    }
    return Promise.reject(error)
  },
)

export default apiClient
