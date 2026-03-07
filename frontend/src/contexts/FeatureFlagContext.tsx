import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from 'react'
import type { ReactNode } from 'react'
import apiClient from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'

type FlagMap = Record<string, boolean>

interface FeatureFlagContextValue {
  flags: FlagMap
  isLoading: boolean
  error: string | null
  refetch: () => Promise<void>
}

const FeatureFlagContext = createContext<FeatureFlagContextValue | null>(null)

export function useFeatureFlags(): FeatureFlagContextValue {
  const ctx = useContext(FeatureFlagContext)
  if (!ctx) throw new Error('useFeatureFlags must be used within FeatureFlagProvider')
  return ctx
}

export function useFlag(flagKey: string): boolean {
  const ctx = useContext(FeatureFlagContext)
  if (!ctx) return false
  return ctx.flags[flagKey] ?? false
}

export function FeatureFlagProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, user } = useAuth()
  const [flags, setFlags] = useState<FlagMap>({})
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchFlags = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<FlagMap>('/v2/flags')
      setFlags(res.data)
    } catch {
      setError('Failed to load feature flags')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isAuthenticated && user?.org_id) {
      fetchFlags()
    } else {
      setFlags({})
    }
  }, [isAuthenticated, user?.org_id, fetchFlags])

  const value = useMemo<FeatureFlagContextValue>(
    () => ({ flags, isLoading, error, refetch: fetchFlags }),
    [flags, isLoading, error, fetchFlags],
  )

  return (
    <FeatureFlagContext.Provider value={value}>
      {children}
    </FeatureFlagContext.Provider>
  )
}
