import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from 'react'
import type { ReactNode } from 'react'
import apiClient, {
  setAccessToken,
  isAccessTokenValid,
  getAccessToken,
  doTokenRefresh,
  setActivePortal,
  getActivePortal,
  isCookiePortal,
  setPortalRejectionHandler,
} from '@/api/client'
import type { PortalRejectionReason } from '@/api/client'
import {
  loadPortalSelection,
  clearPortalSelection,
} from '@/contexts/PortalSelectionContext'
import type { PortalSelection } from '@/contexts/PortalSelectionContext'
import type { UserRole } from '@shared/types/auth'

export interface AuthUser {
  id: string
  email: string
  name: string
  role: UserRole
  org_id: string | null
  branch_ids?: string[]
}

/**
 * An authenticated Employee/Fleet portal user (cookie-session auth), as
 * returned by `GET /e/api/auth/me`. Distinct from the org-user JWT identity:
 * portal users live in a separate identity store and never carry a JWT.
 */
export interface PortalUser {
  portal_user_id: string
  email: string
  first_name?: string
  staff_id?: string
  org_name?: string
  branding?: unknown
}

/**
 * Why a cookie-portal session/restore was rejected, surfaced to the UI:
 * - `session_invalid` → route to the org's branded login, keep selection (R12.5)
 * - `portal_unavailable` → show "portal unavailable" + switch-portal (R11.6/11.7/12.6)
 * - `unreachable` → selection cleared, show error + selector (R11.9)
 */
export type PortalAuthError = PortalRejectionReason

/** Decode a JWT payload (no signature verification — the server is trusted). */
function decodeJwtPayload(token: string): Record<string, unknown> {
  try {
    const base64 = token.split('.')[1]
    const json = atob(base64.replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(json)
  } catch {
    return {}
  }
}

function userFromToken(token: string): AuthUser | null {
  const payload = decodeJwtPayload(token)
  if (!payload.user_id || !payload.email) return null
  const email = payload.email as string
  return {
    id: payload.user_id as string,
    email,
    name: email.split('@')[0],
    role: (payload.role as UserRole) ?? 'salesperson',
    org_id: (payload.org_id as string) ?? null,
    branch_ids: (payload.branch_ids as string[] | undefined) ?? undefined,
  }
}

/** Map a `GET /e/api/auth/me` response into a PortalUser. Returns null if invalid. */
function portalUserFromResponse(data: unknown): PortalUser | null {
  if (typeof data !== 'object' || data === null) return null
  const d = data as Record<string, unknown>
  const id = d.portal_user_id
  const email = d.email
  if (typeof id !== 'string' || typeof email !== 'string') return null
  return {
    portal_user_id: id,
    email,
    first_name: typeof d.first_name === 'string' ? d.first_name : undefined,
    staff_id: typeof d.staff_id === 'string' ? d.staff_id : undefined,
    org_name: typeof d.org_name === 'string' ? d.org_name : undefined,
    branding: d.branding ?? undefined,
  }
}

interface LoginCredentials {
  email: string
  password: string
  remember?: boolean
}

interface AuthContextValue {
  user: AuthUser | null
  isAuthenticated: boolean
  isLoading: boolean
  /** True when MFA verification is required before full auth */
  mfaPending: boolean
  mfaSessionToken: string | null
  mfaMethods: string[]
  mfaDefaultMethod: string | null
  login: (creds: LoginCredentials) => Promise<{ mfaRequired: boolean }>
  loginWithGoogle: (idToken: string) => Promise<{ mfaRequired: boolean }>
  logout: () => Promise<void>
  completeMfa: (code: string, method: string) => Promise<void>
  completeFirebaseMfa: (firebaseIdToken: string) => Promise<void>
  refreshProfile: () => Promise<void>
  isGlobalAdmin: boolean
  isOrgAdmin: boolean
  isBranchAdmin: boolean
  isSalesperson: boolean
  isKiosk: boolean
  /* ---- Portal-aware state (employee / fleet cookie portals) ---- */
  /** The active persisted portal selection, or null (org / none). */
  portalSelection: PortalSelection | null
  /** The authenticated cookie-portal user, or null. */
  portalUser: PortalUser | null
  /** True when the active portal authenticates via cookies (employee/fleet). */
  isCookiePortalActive: boolean
  /** The current portal auth error, driving routing in the portal screens. */
  portalError: PortalAuthError | null
  /** Clear the current portal auth error (e.g. after the UI has handled it). */
  clearPortalError: () => void
  /**
   * Return to the Portal_Type_Selector: ends any active cookie-portal/org
   * session and clears the persisted selection (R11.6, R11.7).
   */
  switchPortal: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [mfaPending, setMfaPending] = useState(false)
  const [mfaSessionToken, setMfaSessionToken] = useState<string | null>(null)
  const [mfaMethods, setMfaMethods] = useState<string[]>([])
  const [mfaDefaultMethod, setMfaDefaultMethod] = useState<string | null>(null)
  const [portalSelection, setPortalSelection] = useState<PortalSelection | null>(null)
  const [portalUser, setPortalUser] = useState<PortalUser | null>(null)
  const [portalError, setPortalError] = useState<PortalAuthError | null>(null)

  // On mount, try to restore session via refresh token
  useEffect(() => {
    let cancelled = false

    // Validate a persisted cookie-portal session via GET <base>/auth/me.
    async function restoreCookiePortal(sel: PortalSelection) {
      // If the API base could not be resolved, we cannot reach the portal —
      // clear the selection, surface an error, and fall back to the selector.
      if (!sel.api_base) {
        await clearPortalSelection()
        if (cancelled) return
        setActivePortal(null)
        setPortalSelection(null)
        setPortalError('unreachable')
        setIsLoading(false)
        return
      }
      try {
        const res = await apiClient.get('/auth/me')
        if (cancelled) return
        const mapped = portalUserFromResponse(res.data)
        if (mapped) {
          setPortalUser(mapped)
          setPortalError(null)
        } else {
          // Unexpected shape — treat as an invalid session.
          setPortalError('session_invalid')
        }
      } catch (err: unknown) {
        if (cancelled) return
        const status = (err as { response?: { status?: number } })?.response?.status
        if (status === 401) {
          // Rejected/expired session → branded login, keep selection (R12.5).
          setPortalError('session_invalid')
        } else if (status === 403) {
          // Portal disabled → "portal unavailable" + switch portal (R12.6).
          setPortalError('portal_unavailable')
        } else {
          // Network / unresolvable base → clear + selector (R11.9).
          await clearPortalSelection()
          if (cancelled) return
          setActivePortal(null)
          setPortalSelection(null)
          setPortalError('unreachable')
        }
        setPortalUser(null)
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    async function restore() {
      // Determine the active portal first so the API client targets the right
      // backend surface and picks the right auth model on restart (R11.8).
      const sel = await loadPortalSelection()
      if (cancelled) return
      setActivePortal(sel)
      setPortalSelection(sel)

      // Cookie-auth portals (employee / fleet) restore via the session cookie,
      // not the org JWT refresh flow.
      if (sel && isCookiePortal(sel.portal_type)) {
        await restoreCookiePortal(sel)
        return
      }

      // If we already have a valid access token, just decode it
      if (isAccessTokenValid()) {
        const existing = getAccessToken()
        if (existing && !cancelled) {
          const decoded = userFromToken(existing)
          if (decoded) {
            setUser(decoded)
            // Fetch full profile name in background
            apiClient
              .get('/auth/me')
              .then((res) => {
                if (cancelled) return
                const p = res.data
                const fullName = [p.first_name, p.last_name]
                  .filter(Boolean)
                  .join(' ')
                setUser((prev) =>
                  prev ? { ...prev, name: fullName || prev.name } : prev,
                )
              })
              .catch(() => {})
            setIsLoading(false)
            return
          }
        }
      }

      // Skip refresh attempt on public auth pages
      const path = window.location.pathname
      const isAuthPage =
        path === '/login' ||
        path === '/forgot-password' ||
        path === '/mfa-verify' ||
        path === '/mobile/login' ||
        path === '/mobile/forgot-password' ||
        path === '/mobile/mfa-verify'
      if (isAuthPage) {
        if (!cancelled) setIsLoading(false)
        return
      }

      try {
        const newToken = await doTokenRefresh()
        if (!cancelled && newToken) {
          const decoded = userFromToken(newToken)
          if (decoded) {
            setUser(decoded)
            apiClient
              .get('/auth/me')
              .then((res) => {
                if (cancelled) return
                const p = res.data
                const fullName = [p.first_name, p.last_name]
                  .filter(Boolean)
                  .join(' ')
                setUser((prev) =>
                  prev ? { ...prev, name: fullName || prev.name } : prev,
                )
              })
              .catch(() => {})
          } else {
            setAccessToken(null)
          }
        } else if (!cancelled) {
          setAccessToken(null)
          setUser(null)
        }
      } catch {
        if (!cancelled) setAccessToken(null)
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    restore()

    return () => {
      cancelled = true
    }
  }, [])

  // Register a handler for mid-session cookie-portal rejections (after restore,
  // while the user is active). The API client invokes this from its response
  // interceptor on 401 / 403 / network errors for cookie portals.
  useEffect(() => {
    const handler = (reason: PortalRejectionReason, sel: PortalSelection | null) => {
      if (reason === 'unreachable') {
        // R11.9 — base unreachable: clear the persisted selection + selector.
        clearPortalSelection().catch(() => {})
        setActivePortal(null)
        setPortalSelection(null)
      } else if (sel) {
        // R12.5 / R12.6 — keep the selection so the branded login / unavailable
        // screen can render for the persisted org.
        setPortalSelection(sel)
      }
      setPortalUser(null)
      setPortalError(reason)
    }
    setPortalRejectionHandler(handler)
    return () => setPortalRejectionHandler(null)
  }, [])

  const handleAuthResponse = useCallback(
    (data: {
      access_token?: string
      mfa_required?: boolean
      mfa_session_token?: string
      mfa_token?: string
      mfa_methods?: string[]
      methods?: string[]
      default_method?: string | null
    }): { mfaRequired: boolean } => {
      if (data.mfa_required && (data.mfa_token || data.mfa_session_token)) {
        setMfaPending(true)
        setMfaSessionToken(data.mfa_token ?? data.mfa_session_token ?? null)
        setMfaMethods(data.methods ?? data.mfa_methods ?? [])
        setMfaDefaultMethod(data.default_method ?? null)
        return { mfaRequired: true }
      }
      if (data.access_token) {
        setAccessToken(data.access_token)
        const decoded = userFromToken(data.access_token)
        if (decoded) {
          setUser(decoded)
          apiClient
            .get('/auth/me')
            .then((res) => {
              const p = res.data
              const fullName = [p.first_name, p.last_name]
                .filter(Boolean)
                .join(' ')
              setUser((prev) =>
                prev ? { ...prev, name: fullName || prev.name } : prev,
              )
            })
            .catch(() => {})
        }
        setMfaPending(false)
        setMfaSessionToken(null)
        setMfaMethods([])
        setMfaDefaultMethod(null)
      }
      return { mfaRequired: false }
    },
    [],
  )

  const login = useCallback(
    async (creds: LoginCredentials): Promise<{ mfaRequired: boolean }> => {
      try {
        const res = await apiClient.post('/auth/login', {
          email: creds.email,
          password: creds.password,
          remember_me: creds.remember ?? false,
        })
        return handleAuthResponse(res.data)
      } catch (err: unknown) {
        const detail = (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail
        throw new Error(detail ?? 'Invalid email or password')
      }
    },
    [handleAuthResponse],
  )

  const loginWithGoogle = useCallback(
    async (idToken: string): Promise<{ mfaRequired: boolean }> => {
      const res = await apiClient.post('/auth/login/google', {
        id_token: idToken,
      })
      return handleAuthResponse(res.data)
    },
    [handleAuthResponse],
  )

  const completeMfa = useCallback(
    async (code: string, method: string) => {
      const res = await apiClient.post('/auth/mfa/verify', {
        code,
        method,
        mfa_token: mfaSessionToken,
      })
      handleAuthResponse(res.data)
    },
    [mfaSessionToken, handleAuthResponse],
  )

  const completeFirebaseMfa = useCallback(
    async (firebaseIdToken: string) => {
      const res = await apiClient.post('/auth/mfa/firebase-verify', {
        mfa_token: mfaSessionToken,
        firebase_id_token: firebaseIdToken,
      })
      handleAuthResponse(res.data)
    },
    [mfaSessionToken, handleAuthResponse],
  )

  const logout = useCallback(async () => {
    try {
      await apiClient.post('/auth/logout')
    } finally {
      setAccessToken(null)
      setUser(null)
      setMfaPending(false)
      setMfaSessionToken(null)
      setMfaMethods([])
      setMfaDefaultMethod(null)
      // Clear any persisted portal selection so the selector is shown next
      // start (a manual logout ends the chosen-portal session entirely).
      await clearPortalSelection()
      setActivePortal(null)
      setPortalSelection(null)
      setPortalUser(null)
      setPortalError(null)
    }
  }, [])

  const clearPortalError = useCallback(() => {
    setPortalError(null)
  }, [])

  const switchPortal = useCallback(async () => {
    const active = getActivePortal()
    // R11.7 — end any active session (cookie-portal or org) before returning
    // to the selector. Logout routes to the active portal's base via the client.
    try {
      await apiClient.post('/auth/logout')
    } catch {
      /* best-effort — proceed to clear local state regardless */
    }
    if (!active || !isCookiePortal(active.portal_type)) {
      setAccessToken(null)
      setUser(null)
    }
    await clearPortalSelection()
    setActivePortal(null)
    setPortalSelection(null)
    setPortalUser(null)
    setPortalError(null)
  }, [])

  const refreshProfile = useCallback(async () => {
    try {
      const res = await apiClient.get('/auth/me')
      const p = res.data
      const fullName = [p.first_name, p.last_name].filter(Boolean).join(' ')
      setUser((prev) =>
        prev ? { ...prev, name: fullName || prev.name } : prev,
      )
    } catch {
      /* ignore */
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: !!user,
      isLoading,
      mfaPending,
      mfaSessionToken,
      mfaMethods,
      mfaDefaultMethod,
      login,
      loginWithGoogle,
      logout,
      completeMfa,
      completeFirebaseMfa,
      refreshProfile,
      isGlobalAdmin: user?.role === 'global_admin' || user?.role === 'admin',
      isOrgAdmin: user?.role === 'org_admin' || user?.role === 'owner',
      isBranchAdmin: user?.role === 'branch_admin' || user?.role === 'manager',
      isSalesperson: user?.role === 'salesperson',
      isKiosk: user?.role === 'kiosk',
      portalSelection,
      portalUser,
      isCookiePortalActive: isCookiePortal(portalSelection?.portal_type),
      portalError,
      clearPortalError,
      switchPortal,
    }),
    [
      user,
      isLoading,
      mfaPending,
      mfaSessionToken,
      mfaMethods,
      mfaDefaultMethod,
      login,
      loginWithGoogle,
      logout,
      completeMfa,
      completeFirebaseMfa,
      refreshProfile,
      portalSelection,
      portalUser,
      portalError,
      clearPortalError,
      switchPortal,
    ],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
