import { Suspense } from 'react'
import type { ReactNode } from 'react'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { FeatureGate } from '@/components/common/FeatureGate'
import { ErrorBoundaryWithRetry } from '@/components/common/ErrorBoundaryWithRetry'
import { ToastContainer } from '@/components/ui/Toast'
import { Spinner } from '@/components/ui'

interface ModulePageWrapperProps {
  /** Module slug checked against ModuleContext.enabledModules */
  moduleSlug: string
  /** Optional feature flag key — if provided, children are also gated behind this flag */
  flagKey?: string
  children: ReactNode
}

function LoadingFallback() {
  return (
    <div className="flex items-center justify-center p-8" data-testid="module-page-loading">
      <Spinner size="lg" label="Loading page" />
    </div>
  )
}

/**
 * Combines module guard, optional feature-flag gate, error boundary,
 * and Suspense into a single wrapper for module page routes.
 *
 * Usage:
 * ```tsx
 * <ModulePageWrapper moduleSlug="kitchen_display" flagKey="kitchen_display">
 *   <KitchenDisplay />
 * </ModulePageWrapper>
 * ```
 */
export function ModulePageWrapper({
  moduleSlug,
  flagKey,
  children,
}: ModulePageWrapperProps) {
  const { isAllowed, isLoading, toasts, dismissToast } = useModuleGuard(moduleSlug)

  // While contexts are loading, show spinner
  if (isLoading) {
    return <LoadingFallback />
  }

  // If module is disabled the hook already triggered a redirect,
  // render toasts so the user sees the warning before navigation completes
  if (!isAllowed) {
    return <ToastContainer toasts={toasts} onDismiss={dismissToast} />
  }

  const content = (
    <ErrorBoundaryWithRetry>
      <Suspense fallback={<LoadingFallback />}>
        {children}
      </Suspense>
    </ErrorBoundaryWithRetry>
  )

  return (
    <>
      {flagKey ? (
        <FeatureGate flag={flagKey} fallback={<LoadingFallback />}>
          {content}
        </FeatureGate>
      ) : (
        content
      )}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </>
  )
}
