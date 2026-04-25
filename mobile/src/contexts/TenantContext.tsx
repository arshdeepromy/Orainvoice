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

export interface OrgBranding {
  name: string
  logo_url: string | null
  primary_colour: string
  secondary_colour: string
}

interface TenantContextValue {
  branding: OrgBranding | null
  isLoading: boolean
  error: string | null
  refetch: () => Promise<void>
  tradeFamily: string | null
  tradeCategory: string | null
}

const DEFAULT_PRIMARY = '#2563eb'
const DEFAULT_SECONDARY = '#1e40af'

const TenantContext = createContext<TenantContextValue | null>(null)

export function useTenant(): TenantContextValue {
  const ctx = useContext(TenantContext)
  if (!ctx) throw new Error('useTenant must be used within TenantProvider')
  return ctx
}

export function TenantProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, user } = useAuth()
  const [branding, setBranding] = useState<OrgBranding | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tradeFamily, setTradeFamily] = useState<string | null>(null)
  const [tradeCategory, setTradeCategory] = useState<string | null>(null)

  const fetchSettings = useCallback(async (signal?: AbortSignal) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<{
        name: string
        org_name?: string
        logo_url: string | null
        primary_colour: string | null
        secondary_colour: string | null
        trade_family: string | null
        trade_category: string | null
      }>('/org/settings', { signal })

      const data = res.data
      setBranding({
        name: data?.org_name || data?.name || '',
        logo_url: data?.logo_url ?? null,
        primary_colour: data?.primary_colour || DEFAULT_PRIMARY,
        secondary_colour: data?.secondary_colour || DEFAULT_SECONDARY,
      })
      setTradeFamily(data?.trade_family ?? null)
      setTradeCategory(data?.trade_category ?? null)
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== 'CanceledError') {
        setError('Failed to load organisation settings')
      }
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isAuthenticated && user?.org_id && user?.role !== 'global_admin') {
      const controller = new AbortController()
      fetchSettings(controller.signal)
      return () => controller.abort()
    } else {
      setBranding(null)
      setTradeFamily(null)
      setTradeCategory(null)
    }
  }, [isAuthenticated, user?.org_id, user?.role, fetchSettings])

  const value = useMemo<TenantContextValue>(
    () => ({
      branding,
      isLoading,
      error,
      refetch: fetchSettings,
      tradeFamily,
      tradeCategory,
    }),
    [branding, isLoading, error, fetchSettings, tradeFamily, tradeCategory],
  )

  return (
    <TenantContext.Provider value={value}>{children}</TenantContext.Provider>
  )
}
