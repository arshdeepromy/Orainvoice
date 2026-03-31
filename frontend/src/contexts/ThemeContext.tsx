import { createContext, useContext, useEffect, useMemo } from 'react'
import type { ReactNode } from 'react'
import { usePlatformBranding } from './PlatformBrandingContext'
import { DEFAULT_THEME, THEMES } from '@/themes/registry'

interface ThemeContextValue {
  theme: string
}

const ThemeContext = createContext<ThemeContextValue>({ theme: DEFAULT_THEME })

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext)
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const { branding } = usePlatformBranding()

  // Read theme from branding — falls back to classic
  const theme = useMemo(() => {
    const raw = branding?.platform_theme
    if (raw && THEMES.some(t => t.id === raw)) return raw
    return DEFAULT_THEME
  }, [branding])

  // Apply data-theme attribute to <html> element
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  const value = useMemo(() => ({ theme }), [theme])

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  )
}
