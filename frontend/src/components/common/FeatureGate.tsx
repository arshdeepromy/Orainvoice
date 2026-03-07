import type { ReactNode } from 'react'
import { useFlag } from '@/contexts/FeatureFlagContext'

interface FeatureGateProps {
  /** Feature flag key that must be true for children to render */
  flag: string
  /** Content to render when the flag is enabled */
  children: ReactNode
  /** Optional fallback to render when the flag is disabled */
  fallback?: ReactNode
}

export function FeatureGate({ flag, children, fallback = null }: FeatureGateProps) {
  const isEnabled = useFlag(flag)

  if (!isEnabled) {
    return <>{fallback}</>
  }

  return <>{children}</>
}
