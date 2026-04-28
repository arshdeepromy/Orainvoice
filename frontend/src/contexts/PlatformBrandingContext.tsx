import { createContext, useContext, useState, useEffect, useMemo } from 'react'
import type { ReactNode } from 'react'
import apiClient from '@/api/client'

export interface PlatformBranding {
  platform_name: string
  logo_url: string | null
  dark_logo_url: string | null
  favicon_url: string | null
  primary_colour: string
  secondary_colour: string
  support_email: string | null
  terms_url: string | null
  website_url: string | null
  platform_theme: string
}

const DEFAULTS: PlatformBranding = {
  platform_name: 'OraInvoice',
  logo_url: null,
  dark_logo_url: null,
  favicon_url: null,
  primary_colour: '#2563EB',
  secondary_colour: '#1E40AF',
  support_email: null,
  terms_url: null,
  website_url: null,
  platform_theme: 'classic',
}

interface PlatformBrandingContextValue {
  branding: PlatformBranding
  isLoading: boolean
}

const PlatformBrandingContext = createContext<PlatformBrandingContextValue>({
  branding: DEFAULTS,
  isLoading: true,
})

export function usePlatformBranding(): PlatformBrandingContextValue {
  return useContext(PlatformBrandingContext)
}

export function PlatformBrandingProvider({ children }: { children: ReactNode }) {
  const [branding, setBranding] = useState<PlatformBranding>(DEFAULTS)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    apiClient
      .get<PlatformBranding>('/public/branding')
      .then((res) => {
        if (!cancelled) setBranding(res.data)
      })
      .catch(() => {
        // Use defaults on failure
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  const value = useMemo(() => ({ branding, isLoading }), [branding, isLoading])

  return (
    <PlatformBrandingContext.Provider value={value}>
      {children}
    </PlatformBrandingContext.Provider>
  )
}
