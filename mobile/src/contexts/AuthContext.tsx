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
} from '@/api/client'
import type { UserRole } from '@shared/types/auth'

export interface AuthUser {
  id: string
  email: string
  name: string
  role: UserRole
  org_id: string | null
  branch_ids?: string[]
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
    branch_ids: (payload.branch_ids as string[] | undefined) ?? undefined,
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

  // On mount, try to restore session via refresh token
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
      if (
        path === '/mobile/login' ||
        path === '/mobile/forgot-password' ||
        path === '/mobile/mfa-verify'
      ) {
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
    }
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
    ],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
