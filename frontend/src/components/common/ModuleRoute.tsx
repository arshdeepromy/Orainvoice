import type { ReactNode } from 'react'
import { useModules } from '@/contexts/ModuleContext'
import { Spinner } from '@/components/ui'
import FeatureNotAvailable from '@/pages/common/FeatureNotAvailable'

interface ModuleRouteProps {
  /** Module slug that must be enabled for the route to render */
  moduleSlug: string
  /** The route's page component */
  children: ReactNode
}

/**
 * Route-level guard that blocks access to disabled modules.
 *
 * - Loading → spinner (prevents content flash)
 * - Enabled → renders children
 * - Disabled → renders FeatureNotAvailable
 *
 * When used outside ModuleProvider (e.g. global admin),
 * useModules() returns isEnabled: () => true, so children render.
 */
export function ModuleRoute({ moduleSlug, children }: ModuleRouteProps) {
  const { isEnabled, isLoading } = useModules()

  if (isLoading) {
    return <Spinner size="lg" label="Checking module access" />
  }

  if (!isEnabled(moduleSlug)) {
    return <FeatureNotAvailable />
  }

  return <>{children}</>
}
