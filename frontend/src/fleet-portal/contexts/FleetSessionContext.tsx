/**
 * FleetSessionContext — holds the authenticated portal user and the
 * lifecycle methods consumed by the SPA.
 *
 * The context state mirrors the staff `AuthContext` pattern so the
 * fleet portal feels familiar to maintainers: a single hook returns
 * `{ user, login, logout, refresh }` and a guard component reads
 * `user` to drive route gating.
 *
 * Implements: B2B Fleet Portal task 14.1 — Requirements 19.1, 19.5, 19.6.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import {
  getCurrentUser,
  loginFleet,
  logoutFleet,
  MfaChallengeRequired,
  verifyMfa,
} from '../api/endpoints'
import type { CurrentUser } from '../api/types'
import type { MfaChallengeResponse } from '../api/types'

interface FleetSessionContextValue {
  user: CurrentUser | null
  loading: boolean
  mfaChallenge: MfaChallengeResponse | null
  login: (email: string, password: string) => Promise<CurrentUser>
  verifyMfaCode: (code: string, method?: 'totp' | 'sms' | 'backup_codes') => Promise<CurrentUser>
  clearMfaChallenge: () => void
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const FleetSessionContext = createContext<FleetSessionContextValue | null>(null)

export function FleetSessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [mfaChallenge, setMfaChallenge] = useState<MfaChallengeResponse | null>(null)

  const refresh = useCallback(async () => {
    const u = await getCurrentUser()
    setUser(u)
  }, [])

  useEffect(() => {
    let cancelled = false
    const init = async () => {
      try {
        const u = await getCurrentUser()
        if (!cancelled) setUser(u)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    init()
    return () => {
      cancelled = true
    }
  }, [])

  // Listen for the 401 broadcast emitted by the API client.
  useEffect(() => {
    const onExpired = () => setUser(null)
    window.addEventListener('fleet:session-expired', onExpired)
    return () => window.removeEventListener('fleet:session-expired', onExpired)
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    try {
      const u = await loginFleet(email, password)
      setUser(u)
      setMfaChallenge(null)
      return u
    } catch (err) {
      if (err instanceof MfaChallengeRequired) {
        setMfaChallenge(err.challenge)
        throw err
      }
      throw err
    }
  }, [])

  const verifyMfaCode = useCallback(async (code: string, method: 'totp' | 'sms' | 'backup_codes' = 'totp') => {
    if (!mfaChallenge) throw new Error('No MFA challenge active')
    const u = await verifyMfa(mfaChallenge.mfa_token, code, method)
    setUser(u)
    setMfaChallenge(null)
    return u
  }, [mfaChallenge])

  const clearMfaChallenge = useCallback(() => {
    setMfaChallenge(null)
  }, [])

  const logout = useCallback(async () => {
    try {
      await logoutFleet()
    } finally {
      setUser(null)
      setMfaChallenge(null)
    }
  }, [])

  const value = useMemo<FleetSessionContextValue>(
    () => ({ user, loading, mfaChallenge, login, verifyMfaCode, clearMfaChallenge, logout, refresh }),
    [user, loading, mfaChallenge, login, verifyMfaCode, clearMfaChallenge, logout, refresh],
  )

  return <FleetSessionContext.Provider value={value}>{children}</FleetSessionContext.Provider>
}

export function useFleetSession(): FleetSessionContextValue {
  const ctx = useContext(FleetSessionContext)
  if (ctx === null) {
    throw new Error('useFleetSession must be used inside <FleetSessionProvider>')
  }
  return ctx
}
