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

export interface ModuleInfo {
  slug: string
  display_name: string
  description: string
  category: string
  is_core: boolean
  is_enabled: boolean
}

interface ModuleContextValue {
  modules: ModuleInfo[]
  enabledModules: string[]
  isLoading: boolean
  error: string | null
  isEnabled: (slug: string) => boolean
  refetch: () => Promise<void>
}

const ModuleContext = createContext<ModuleContextValue | null>(null)

export function useModules(): ModuleContextValue {
  const ctx = useContext(ModuleContext)
  if (!ctx) {
    // Return a safe default when used outside ModuleProvider (e.g. in tests)
    return {
      modules: [],
      enabledModules: [],
      isLoading: false,
      error: null,
      isEnabled: () => true,
      refetch: async () => {},
    }
  }
  return ctx
}

export function ModuleProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, user } = useAuth()
  const [modules, setModules] = useState<ModuleInfo[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchModules = useCallback(async (signal?: AbortSignal) => {
    setIsLoading(true)
    setError(null)
    try {
      // Modules endpoint is on v2 — use absolute path to bypass apiClient baseURL
      const res = await apiClient.get<{ modules: ModuleInfo[]; total: number }>('/modules', { 
        baseURL: '/api/v2',
        signal 
      })
      // API returns { modules: [...], total: number }
      setModules(Array.isArray(res.data.modules) ? res.data.modules : [])
    } catch (err: any) {
      if (err.name !== 'CanceledError') {
        setError('Failed to load modules')
      }
      setModules([]) // Set empty array on error
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
    () => (modules || []).filter((m) => m.is_enabled).map((m) => m.slug),
    [modules],
  )

  const isEnabled = useCallback(
    (slug: string) => enabledModules.includes(slug),
    [enabledModules],
  )

  const value = useMemo<ModuleContextValue>(
    () => ({ modules, enabledModules, isLoading, error, isEnabled, refetch: fetchModules }),
    [modules, enabledModules, isLoading, error, isEnabled, fetchModules],
  )

  return (
    <ModuleContext.Provider value={value}>
      {children}
    </ModuleContext.Provider>
  )
}
