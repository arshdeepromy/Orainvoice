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
import { useTenant } from '@/contexts/TenantContext'
import type { ModuleInfo } from '@shared/types/module'

interface ModuleContextValue {
  modules: ModuleInfo[]
  enabledModules: string[]
  isLoading: boolean
  error: string | null
  isModuleEnabled: (slug: string) => boolean
  tradeFamily: string | null
  refetch: () => Promise<void>
}

const ModuleContext = createContext<ModuleContextValue | null>(null)

export function useModules(): ModuleContextValue {
  const ctx = useContext(ModuleContext)
  if (!ctx) {
    // Safe default when used outside ModuleProvider (e.g. in tests)
    return {
      modules: [],
      enabledModules: [],
      isLoading: false,
      error: null,
      isModuleEnabled: () => true,
      tradeFamily: null,
      refetch: async () => {},
    }
  }
  return ctx
}

export function ModuleProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, user } = useAuth()
  const { tradeFamily } = useTenant()
  const [modules, setModules] = useState<ModuleInfo[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchModules = useCallback(async (signal?: AbortSignal) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<{ modules: ModuleInfo[]; total: number }>(
        '/modules',
        { baseURL: '/api/v2', signal },
      )
      setModules(Array.isArray(res.data?.modules) ? res.data.modules : [])
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== 'CanceledError') {
        setError('Failed to load modules')
      }
      setModules([])
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isAuthenticated && user?.org_id && user?.role !== 'global_admin') {
      const controller = new AbortController()
      fetchModules(controller.signal)
      return () => controller.abort()
    } else {
      setModules([])
    }
  }, [isAuthenticated, user?.org_id, user?.role, fetchModules])

  const enabledModules = useMemo(
    () => (modules ?? []).filter((m) => m.is_enabled).map((m) => m.slug),
    [modules],
  )

  const isModuleEnabled = useCallback(
    (slug: string) => enabledModules.includes(slug),
    [enabledModules],
  )

  const value = useMemo<ModuleContextValue>(
    () => ({
      modules,
      enabledModules,
      isLoading,
      error,
      isModuleEnabled,
      tradeFamily,
      refetch: fetchModules,
    }),
    [modules, enabledModules, isLoading, error, isModuleEnabled, tradeFamily, fetchModules],
  )

  return (
    <ModuleContext.Provider value={value}>{children}</ModuleContext.Provider>
  )
}
