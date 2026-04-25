import type { ReactNode } from 'react'
import { useModules } from '@/contexts/ModuleContext'
import { useAuth } from '@/contexts/AuthContext'
import type { UserRole } from '@shared/types/auth'

export interface ModuleGateProps {
  /** Module slug that must be enabled. Use '*' or empty string to skip module check. */
  moduleSlug: string
  /** Trade family that must match the org's trade family. Omit to skip. */
  tradeFamily?: string
  /** Roles allowed to see the children. Omit or empty to allow all roles. */
  roles?: UserRole[]
  /** Content to render when the gate passes. */
  children: ReactNode
  /** Content to render when the gate fails. Defaults to null (hidden). */
  fallback?: ReactNode
}

/**
 * Wrapper component that shows or hides children based on:
 * 1. Whether the required module is enabled for the organisation
 * 2. Whether the org's trade family matches (if specified)
 * 3. Whether the user's role is in the allowed list (if specified)
 *
 * Requirements: 5.2, 5.3, 5.4, 5.5
 */
export function ModuleGate({
  moduleSlug,
  tradeFamily,
  roles,
  children,
  fallback = null,
}: ModuleGateProps) {
  const { isModuleEnabled, tradeFamily: currentTradeFamily } = useModules()
  const { user } = useAuth()

  // Module gate: if a non-wildcard slug is provided, the module must be enabled
  if (moduleSlug && moduleSlug !== '*' && !isModuleEnabled(moduleSlug)) {
    return <>{fallback}</>
  }

  // Trade family gate: if specified, must match the org's trade family
  if (tradeFamily && tradeFamily !== currentTradeFamily) {
    return <>{fallback}</>
  }

  // Role gate: if roles are specified and non-empty, user must have one of them
  if (roles && roles.length > 0) {
    const userRole = user?.role
    if (!userRole || !roles.includes(userRole as UserRole)) {
      return <>{fallback}</>
    }
  }

  return <>{children}</>
}
