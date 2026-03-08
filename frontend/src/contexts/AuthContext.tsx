import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from 'react'
import type { ReactNode } from 'react'
import apiClient, { setAccessToken } from '@/api/client'

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
  return {
    id: payload.user_id as string,
    email: payload.email as string,
    name: (payload.email as string).split('@')[0],
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
  login: (creds: LoginCredentials) => Promise<void>
  loginWithGoogle: (idToken: string) => Promise<void>
  loginWithPasskey: () => Promise<void>
  logout: () => Promise<void>
  completeMfa: (code: string, method: string) => Promise<void>
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

  // On mount, try to restore session via refresh token
  useEffect(() => {
    let cancelled = false
    async function restore() {
      try {
        // Attempt to restore session — refresh token is sent via httpOnly cookie
        const res = await apiClient.post<{
          access_token: string
        }>('/auth/token/refresh', {})
        if (!cancelled) {
          setAccessToken(res.data.access_token)
          const decoded = userFromToken(res.data.access_token)
          if (decoded) {
            setUser(decoded)
          }
        }
      } catch {
        // No valid session — stay logged out
        setAccessToken(null)
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
    }) => {
      if (data.mfa_required && (data.mfa_token || data.mfa_session_token)) {
        setMfaPending(true)
        setMfaSessionToken(data.mfa_token ?? data.mfa_session_token ?? null)
        return
      }
      if (data.access_token) {
        setAccessToken(data.access_token)
        // Refresh token is now stored as httpOnly cookie by the server
        // Extract user from JWT payload
        const decoded = userFromToken(data.access_token)
        if (decoded) {
          setUser(decoded)
        }
        setMfaPending(false)
        setMfaSessionToken(null)
      }
    },
    [],
  )

  const login = useCallback(
    async (creds: LoginCredentials) => {
      const res = await apiClient.post('/auth/login', {
        email: creds.email,
        password: creds.password,
        remember_me: creds.remember ?? false,
      })
      handleAuthResponse(res.data)
    },
    [handleAuthResponse],
  )

  const loginWithGoogle = useCallback(
    async (idToken: string) => {
      const res = await apiClient.post('/auth/login/google', {
        id_token: idToken,
      })
      handleAuthResponse(res.data)
    },
    [handleAuthResponse],
  )

  const loginWithPasskey = useCallback(async () => {
    // Step 1: get challenge from server
    const optionsRes = await apiClient.post('/auth/login/passkey/options')
    const options = optionsRes.data

    // Step 2: call WebAuthn browser API
    const credential = await navigator.credentials.get({
      publicKey: options,
    })

    // Step 3: send assertion to server
    const res = await apiClient.post('/auth/login/passkey', {
      credential,
    })
    handleAuthResponse(res.data)
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

  const logout = useCallback(async () => {
    try {
      await apiClient.post('/auth/logout')
    } finally {
      setAccessToken(null)
      setUser(null)
      setMfaPending(false)
      setMfaSessionToken(null)
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: !!user,
      isLoading,
      mfaPending,
      mfaSessionToken,
      login,
      loginWithGoogle,
      loginWithPasskey,
      logout,
      completeMfa,
      isGlobalAdmin: user?.role === 'global_admin',
      isOrgAdmin: user?.role === 'org_admin',
      isSalesperson: user?.role === 'salesperson',
    }),
    [
      user,
      isLoading,
      mfaPending,
      mfaSessionToken,
      login,
      loginWithGoogle,
      loginWithPasskey,
      logout,
      completeMfa,
    ],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
