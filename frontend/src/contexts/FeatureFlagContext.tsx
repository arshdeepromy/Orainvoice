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

export function FeatureGate({
  flagKey,
  fallback,
  children,
}: {
  flagKey: string
  fallback?: ReactNode
  children: ReactNode
}): ReactNode {
  const { flags, isLoading } = useFeatureFlags()
  if (isLoading) return null
  if (flags[flagKey]) return children
  return fallback ?? null
}

export function FeatureFlagProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, user } = useAuth()
  const [flags, setFlags] = useState<FlagMap>({})
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchFlags = useCallback(async (signal?: AbortSignal) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await apiClient.get('/api/v2/flags', { signal })
      // API returns { flags: [{ key, enabled }, ...] } — transform to flat map
      const data = res.data
      if (data && Array.isArray(data.flags)) {
        const map: FlagMap = {}
        for (const f of data.flags) {
          if (f.key) map[f.key] = Boolean(f.enabled)
        }
        setFlags(map)
      } else if (data && typeof data === 'object' && !Array.isArray(data)) {
        // Already a flat map (backwards compat)
        setFlags(data as FlagMap)
      }
    } catch (err: any) {
      if (err.name !== 'CanceledError') {
        setError('Failed to load feature flags')
      }
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isAuthenticated && user?.org_id) {
      const controller = new AbortController()
      fetchFlags(controller.signal)
      return () => controller.abort()
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
