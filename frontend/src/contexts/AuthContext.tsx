import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from 'react'
import type { ReactNode } from 'react'
import apiClient, { setAccessToken, isAccessTokenValid, getAccessToken, doTokenRefresh } from '@/api/client'

export type UserRole = 'global_admin' | 'org_admin' | 'salesperson'

export interface AuthUser {
  id: string
  email: string
  name: string
  role: UserRole
  org_id: string | null
}

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
  loginWithPasskey: () => Promise<{ mfaRequired: boolean }>
  logout: () => Promise<void>
  completeMfa: (code: string, method: string) => Promise<void>
  completeFirebaseMfa: (firebaseIdToken: string) => Promise<void>
  refreshProfile: () => Promise<void>
  isGlobalAdmin: boolean
  isOrgAdmin: boolean
  isSalesperson: boolean
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


  // On mount, try to restore session via refresh token.
  // Skip on public pages (login, signup) where no session is expected.
  useEffect(() => {
    let cancelled = false

    async function restore() {
      // If we already have a valid access token, just decode it
      if (isAccessTokenValid()) {
        const existing = getAccessToken()
        if (existing && !cancelled) {
          const decoded = userFromToken(existing)
          if (decoded) {
            setUser(decoded)
            // Fetch full profile name in background
            apiClient.get('/auth/me').then(res => {
              if (cancelled) return
              const p = res.data
              const fullName = [p.first_name, p.last_name].filter(Boolean).join(' ')
              setUser(prev => prev ? { ...prev, name: fullName || prev.name } : prev)
            }).catch(() => {})
            setIsLoading(false)
            return
          }
        }
      }

      // Skip refresh attempt on public auth pages — no session expected
      const path = window.location.pathname
      if (path === '/login' || path === '/signup' || path === '/forgot-password' || path === '/mfa-verify') {
        if (!cancelled) setIsLoading(false)
        return
      }

      try {
        // Token missing or expired — use the global refresh mutex.
        // doTokenRefresh deduplicates: even if StrictMode causes two calls,
        // only one HTTP request fires and both callers get the same promise.
        // We intentionally do NOT use AbortController here because aborting
        // the request client-side doesn't undo the server-side token rotation.
        // If we abort + retry, the second request sends the old (now-revoked)
        // cookie, triggering reuse detection and killing the entire session.
        const newToken = await doTokenRefresh()
        if (!cancelled && newToken) {
          const decoded = userFromToken(newToken)
          if (decoded) {
            setUser(decoded)
            // Fetch full profile name in background
            apiClient.get('/auth/me').then(res => {
              if (cancelled) return
              const p = res.data
              const fullName = [p.first_name, p.last_name].filter(Boolean).join(' ')
              setUser(prev => prev ? { ...prev, name: fullName || prev.name } : prev)
            }).catch(() => {})
          } else {
            // Token was returned but couldn't be decoded — force logout
            setAccessToken(null)
          }
        } else if (!cancelled) {
          // Refresh failed — no valid session. Clear state and let
          // RequireAuth redirect to /login.
          setAccessToken(null)
          setUser(null)
        }
      } catch {
        // No valid session — stay logged out
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

  const handleAuthResponse = useCallback(
    (data: {
      access_token?: string
      refresh_token?: string
      user?: AuthUser
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
        // Backend MFAChallengeResponse uses "methods", MFARequiredResponse uses "mfa_methods"
        setMfaMethods(data.methods ?? data.mfa_methods ?? [])
        setMfaDefaultMethod(data.default_method ?? null)
        return { mfaRequired: true }
      }
      if (data.access_token) {
        setAccessToken(data.access_token)
        // Refresh token is now stored as httpOnly cookie by the server
        // Extract user from JWT payload
        const decoded = userFromToken(data.access_token)
        if (decoded) {
          setUser(decoded)
          // Fetch full profile (first/last name) in background
          apiClient.get('/auth/me').then(res => {
            const p = res.data
            const fullName = [p.first_name, p.last_name].filter(Boolean).join(' ')
            setUser(prev => prev ? { ...prev, name: fullName || prev.name } : prev)
          }).catch(() => { /* keep JWT-derived name */ })
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
        // Extract the backend's detail message so callers get a useful error
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

  const loginWithPasskey = useCallback(async (): Promise<{ mfaRequired: boolean }> => {
    // Step 1: get challenge from server
    const optionsRes = await apiClient.post('/auth/login/passkey/options')
    const options = optionsRes.data

    // Step 2: call WebAuthn browser API
    const credential = await navigator.credentials.get({
      publicKey: { ...options, rpId: window.location.hostname },
    })

    // Step 3: send assertion to server
    const res = await apiClient.post('/auth/login/passkey', {
      credential,
    })
    return handleAuthResponse(res.data)
  }, [handleAuthResponse])

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
    }
  }, [])

  const refreshProfile = useCallback(async () => {
    try {
      const res = await apiClient.get('/auth/me')
      const p = res.data
      const fullName = [p.first_name, p.last_name].filter(Boolean).join(' ')
      setUser(prev => prev ? { ...prev, name: fullName || prev.name } : prev)
    } catch { /* ignore */ }
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
      loginWithPasskey,
      logout,
      completeMfa,
      completeFirebaseMfa,
      refreshProfile,
      isGlobalAdmin: user?.role === 'global_admin',
      isOrgAdmin: user?.role === 'org_admin',
      isSalesperson: user?.role === 'salesperson',
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
      loginWithPasskey,
      logout,
      completeMfa,
      completeFirebaseMfa,
      refreshProfile,
    ],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
