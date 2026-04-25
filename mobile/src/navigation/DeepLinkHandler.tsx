import { useEffect, useRef } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import { useDeepLink } from '@/hooks/useDeepLink'

/**
 * DeepLinkHandler — listens for incoming deep links via Capacitor App plugin.
 * If the user is unauthenticated, stores the target URL and navigates after login.
 *
 * Requirements: 39.2, 42.5
 */
export function DeepLinkHandler() {
  const { isAuthenticated, isLoading } = useAuth()
  const { handleDeepLink } = useDeepLink()
  const pendingUrl = useRef<string | null>(null)

  // Listen for deep links from Capacitor
  useEffect(() => {
    // Use the runtime global — avoids bundler issues with require()
    const isNative = !!(window as any).Capacitor?.isNativePlatform?.()
    if (!isNative) return

    let listener: { remove: () => void } | null = null

    async function setup() {
      try {
        const { App } = await import('@capacitor/app')
        const l = await App.addListener('appUrlOpen', (data) => {
          if (!data.url) return

          if (isAuthenticated) {
            handleDeepLink(data.url)
          } else {
            // Store for after auth completes
            pendingUrl.current = data.url
          }
        })
        listener = l
      } catch {
        // Not in Capacitor environment — no-op
      }
    }

    setup()
    return () => {
      listener?.remove()
    }
  }, [isAuthenticated, handleDeepLink])

  // Process pending deep link after authentication
  useEffect(() => {
    if (!isLoading && isAuthenticated && pendingUrl.current) {
      const url = pendingUrl.current
      pendingUrl.current = null
      handleDeepLink(url)
    }
  }, [isAuthenticated, isLoading, handleDeepLink])

  return null
}
