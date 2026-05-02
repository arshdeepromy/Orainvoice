import { createContext, useContext } from 'react'

/**
 * Provides the portal locale (e.g. 'en-NZ', 'mi-NZ') to all portal sub-components.
 * Defaults to 'en-NZ' when no language is configured in org branding.
 */
const PortalLocaleContext = createContext<string>('en-NZ')

export const PortalLocaleProvider = PortalLocaleContext.Provider

export function usePortalLocale(): string {
  return useContext(PortalLocaleContext)
}
