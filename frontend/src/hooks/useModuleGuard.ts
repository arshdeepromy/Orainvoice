import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useModules } from '@/contexts/ModuleContext'
import { useToast } from '@/components/ui/Toast'

interface ModuleGuardResult {
  isAllowed: boolean
  isLoading: boolean
  toasts: ReturnType<typeof useToast>['toasts']
  dismissToast: ReturnType<typeof useToast>['dismissToast']
}

/**
 * Hook that checks whether a module is enabled via ModuleContext.
 * If the module is disabled (and context has finished loading),
 * it redirects to /dashboard with a warning toast.
 */
export function useModuleGuard(moduleSlug: string): ModuleGuardResult {
  const { modules, isEnabled, isLoading, error } = useModules()
  const navigate = useNavigate()
  const { toasts, addToast, dismissToast } = useToast()
  const hasRedirected = useRef(false)
  // Track whether we've ever seen modules load (to avoid acting on initial empty state)
  const [hasInitialised, setHasInitialised] = useState(false)

  useEffect(() => {
    // Mark as initialised once modules have been fetched at least once
    // (modules array is populated, or loading finished with an error, or loading completed)
    if (!hasInitialised && !isLoading && (modules.length > 0 || error)) {
      setHasInitialised(true)
    }
  }, [isLoading, modules.length, error, hasInitialised])

  const allowed = isEnabled(moduleSlug)

  useEffect(() => {
    if (hasInitialised && !isLoading && !allowed && !hasRedirected.current) {
      hasRedirected.current = true
      addToast('warning', 'Module not available')
      navigate('/dashboard', { replace: true })
    }
  }, [hasInitialised, isLoading, allowed, navigate, addToast])

  return {
    isAllowed: allowed,
    isLoading: isLoading || !hasInitialised,
    toasts,
    dismissToast,
  }
}
