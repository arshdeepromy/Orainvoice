import type { ReactNode } from 'react'
import { useModules } from '@/contexts/ModuleContext'

/**
 * ModuleGate — Task 20 port of frontend/src/components/common/ModuleGate.tsx.
 *
 * Logic copied VERBATIM: renders children only when `module` is enabled,
 * otherwise the optional `fallback`. No visual surface (it's a conditional
 * wrapper), so there is nothing to restyle. Used by InvoiceCreate / InvoiceDetail
 * to gate the vehicles section.
 */
interface ModuleGateProps {
  /** Module slug that must be enabled for children to render */
  module: string
  /** Content to render when the module is enabled */
  children: ReactNode
  /** Optional fallback to render when the module is disabled */
  fallback?: ReactNode
}

export function ModuleGate({ module, children, fallback = null }: ModuleGateProps) {
  const { isEnabled } = useModules()

  if (!isEnabled(module)) {
    return <>{fallback}</>
  }

  return <>{children}</>
}

export default ModuleGate
