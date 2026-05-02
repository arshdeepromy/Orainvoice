import axios from 'axios'
import { Capacitor } from '@capacitor/core'

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

// On native Capacitor, API calls go to the production backend.
// On web (served behind nginx), relative paths work via the reverse proxy.
const apiBaseURL = Capacitor.isNativePlatform()
  ? 'https://devin.oraflow.co.nz/api/v1'
  : '/api/v1'

const apiClient = axios.create({
  baseURL: apiBaseURL,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true, // send httpOnly refresh cookie
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

    // Don't intercept 401 from the refresh endpoint itself
    const url = original?.url ?? ''
    const isRefreshCall =
      url.includes('/auth/token/refresh') ||
      url.includes('auth/token/refresh')

    // Don't intercept 401 from MFA endpoints
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
