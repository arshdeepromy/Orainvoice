import { useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { resolveDeepLink, screenToPath } from '@/navigation/DeepLinkConfig'

/* ------------------------------------------------------------------ */
/* Capacitor App plugin types (stubbed for web/test environments)     */
/* ------------------------------------------------------------------ */

interface AppUrlOpen {
  url: string
}

interface AppPlugin {
  addListener: (
    event: string,
    callback: (data: AppUrlOpen) => void,
  ) => Promise<{ remove: () => void }>
}

/**
 * Check if we're running inside a native Capacitor shell (not plain web).
 * Uses the runtime global injected by Capacitor — avoids bundler issues
 * with require() / static imports that Vite resolves at build time.
 */
function isNativePlatform(): boolean {
  return !!(window as any).Capacitor?.isNativePlatform?.()
}

/**
 * Safely get the App plugin from Capacitor.
 * Returns null in web/test environments.
 */
async function getAppPlugin(): Promise<AppPlugin | null> {
  if (!isNativePlatform()) return null
  try {
    const mod = await import('@capacitor/app')
    return (mod.App ?? null) as AppPlugin | null
  } catch {
    return null
  }
}

/* ------------------------------------------------------------------ */
/* Hook                                                               */
/* ------------------------------------------------------------------ */

/**
 * Deep link URL handler that resolves patterns to screen navigation.
 *
 * Listens for incoming deep link URLs via Capacitor's App plugin and
 * navigates to the resolved screen.
 *
 * Requirements: 42.1, 42.2, 42.3, 42.4, 42.5
 */
export function useDeepLink(): {
  handleDeepLink: (url: string) => void
} {
  const navigate = useNavigate()

  const handleDeepLink = useCallback(
    (url: string) => {
      // Extract the path from the URL
      let path: string
      try {
        const parsed = new URL(url)
        path = parsed.pathname
      } catch {
        // If URL parsing fails, treat the input as a path directly
        path = url
      }

      // Strip /mobile prefix if present
      if (path.startsWith('/mobile')) {
        path = path.slice('/mobile'.length) || '/'
      }

      const result = resolveDeepLink(path)
      const routePath = screenToPath(result)
      navigate(routePath)
    },
    [navigate],
  )

  // Listen for deep links from Capacitor App plugin
  useEffect(() => {
    let listener: { remove: () => void } | null = null
    let cancelled = false

    async function setup() {
      const plugin = await getAppPlugin()
      if (!plugin || cancelled) return

      try {
        const l = await plugin.addListener('appUrlOpen', (data: AppUrlOpen) => {
          if (data.url) {
            handleDeepLink(data.url)
          }
        })
        if (!cancelled) listener = l
        else l.remove()
      } catch {
        // Listener setup failed — no-op
      }
    }

    setup()

    return () => {
      cancelled = true
      listener?.remove()
    }
  }, [handleDeepLink])

  return { handleDeepLink }
}
