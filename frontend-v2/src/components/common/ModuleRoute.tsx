import type { ReactNode } from 'react'
import { useModules } from '@/contexts/ModuleContext'
import { Spinner } from '@/components/ui'
import FeatureNotAvailable from '@/pages/common/FeatureNotAvailable'

/**
 * ModuleRoute — Task 21 port of frontend/src/components/common/ModuleRoute.tsx.
 *
 * Route-level guard that blocks access to disabled modules. Logic copied
 * VERBATIM:
 *   - Loading → spinner (prevents content flash)
 *   - Enabled → renders children
 *   - Disabled → renders FeatureNotAvailable
 *
 * When used outside ModuleProvider (e.g. global admin), useModules() returns
 * isEnabled: () => true, so children render. The original `prop: moduleSlug`
 * contract is preserved so the App.tsx quote routes mirror the real router.
 */
interface ModuleRouteProps {
  /** Module slug that must be enabled for the route to render */
  moduleSlug: string
  /** The route's page component */
  children: ReactNode
}

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

export default ModuleRoute
