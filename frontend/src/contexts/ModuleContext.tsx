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
  if (!ctx) throw new Error('useModules must be used within ModuleProvider')
  return ctx
}

export function ModuleProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, user } = useAuth()
  const [modules, setModules] = useState<ModuleInfo[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchModules = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<ModuleInfo[]>('/v2/modules')
      setModules(res.data)
    } catch {
      setError('Failed to load modules')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isAuthenticated && user?.org_id) {
      fetchModules()
    } else {
      setModules([])
    }
  }, [isAuthenticated, user?.org_id, fetchModules])

  const enabledModules = useMemo(
    () => modules.filter((m) => m.is_enabled).map((m) => m.slug),
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
