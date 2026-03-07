import type { ReactNode } from 'react'
import { useModules } from '@/contexts/ModuleContext'

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
