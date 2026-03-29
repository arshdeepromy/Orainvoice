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

/* ── Types ── */

export interface OrgBranding {
  name: string
  logo_url: string | null
  primary_colour: string
  secondary_colour: string
  address: string | null
  phone: string | null
  email: string | null
  sidebar_display_mode: 'icon_and_name' | 'icon_only' | 'name_only'
}

export interface GstSettings {
  gst_number: string | null
  gst_percentage: number
  gst_inclusive: boolean
}

export interface InvoiceSettings {
  prefix: string
  default_due_days: number
  payment_terms_text: string | null
  terms_and_conditions: string | null
}

export interface TenantSettings {
  branding: OrgBranding
  gst: GstSettings
  invoice: InvoiceSettings
}

interface TenantContextValue {
  settings: TenantSettings | null
  isLoading: boolean
  error: string | null
  refetch: () => Promise<void>
  /** Trade family slug from the org's trade category (e.g. 'automotive-transport', 'plumbing-gas'). Null if not set. */
  tradeFamily: string | null
  /** Trade category slug (e.g. 'general-automotive', 'plumber'). Null if not set. */
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

/* ── CSS custom property helpers ── */

function applyBrandingCssVars(branding: OrgBranding) {
  const root = document.documentElement
  root.style.setProperty('--color-primary', branding.primary_colour || DEFAULT_PRIMARY)
  root.style.setProperty('--color-secondary', branding.secondary_colour || DEFAULT_SECONDARY)
}

function clearBrandingCssVars() {
  const root = document.documentElement
  root.style.removeProperty('--color-primary')
  root.style.removeProperty('--color-secondary')
}

/* ── Provider ── */

export function TenantProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, user } = useAuth()
  const [settings, setSettings] = useState<TenantSettings | null>(null)
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
        logo_url: string | null
        primary_colour: string | null
        secondary_colour: string | null
        address: string | null
        phone: string | null
        email: string | null
        gst_number: string | null
        gst_percentage: number
        gst_inclusive: boolean
        invoice_prefix: string
        default_due_days: number
        payment_terms_text: string | null
        terms_and_conditions: string | null
        trade_family: string | null
        trade_category: string | null
      }>('/org/settings', { signal })

      const data = res.data
      const tenant: TenantSettings = {
        branding: {
          name: data.org_name || data.name || '',
          logo_url: data.logo_url,
          primary_colour: data.primary_colour || DEFAULT_PRIMARY,
          secondary_colour: data.secondary_colour || DEFAULT_SECONDARY,
          address: data.address,
          phone: data.phone,
          email: data.email,
          sidebar_display_mode: data.sidebar_display_mode || 'icon_and_name',
        },
        gst: {
          gst_number: data.gst_number,
          gst_percentage: data.gst_percentage,
          gst_inclusive: data.gst_inclusive,
        },
        invoice: {
          prefix: data.invoice_prefix,
          default_due_days: data.default_due_days,
          payment_terms_text: data.payment_terms_text,
          terms_and_conditions: data.terms_and_conditions,
        },
      }

      setSettings(tenant)
      applyBrandingCssVars(tenant.branding)
      setTradeFamily(data.trade_family ?? null)
      setTradeCategory(data.trade_category ?? null)
    } catch (err: any) {
      if (err.name !== 'CanceledError') {
        setError('Failed to load organisation settings')
      }
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Fetch settings when user authenticates with an org (skip for global_admin without org context)
  useEffect(() => {
    if (isAuthenticated && user?.org_id && user?.role !== 'global_admin') {
      const controller = new AbortController()
      fetchSettings(controller.signal)
      return () => controller.abort()
    } else {
      setSettings(null)
      setTradeFamily(null)
      setTradeCategory(null)
      clearBrandingCssVars()
    }
  }, [isAuthenticated, user?.org_id, user?.role, fetchSettings])

  const value = useMemo<TenantContextValue>(
    () => ({ settings, isLoading, error, refetch: fetchSettings, tradeFamily, tradeCategory }),
    [settings, isLoading, error, fetchSettings, tradeFamily, tradeCategory],
  )

  return (
    <TenantContext.Provider value={value}>{children}</TenantContext.Provider>
  )
}
