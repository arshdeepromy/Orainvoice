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

  // On mount, try to restore session via refresh token cookie
  useEffect(() => {
    let cancelled = false
    async function restore() {
      try {
        const res = await apiClient.post<{
          access_token: string
          user: AuthUser
        }>('/auth/token/refresh')
        if (!cancelled) {
          setAccessToken(res.data.access_token)
          setUser(res.data.user)
        }
      } catch {
        // No valid session — stay logged out
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
      user?: AuthUser
      mfa_required?: boolean
      mfa_session_token?: string
    }) => {
      if (data.mfa_required && data.mfa_session_token) {
        setMfaPending(true)
        setMfaSessionToken(data.mfa_session_token)
        return
      }
      if (data.access_token && data.user) {
        setAccessToken(data.access_token)
        setUser(data.user)
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
        remember: creds.remember ?? false,
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
        mfa_session_token: mfaSessionToken,
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
