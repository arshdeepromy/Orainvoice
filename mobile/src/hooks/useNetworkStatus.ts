import { useState, useEffect } from 'react'

/**
 * Check if we're running inside a native Capacitor shell.
 */
function isNativePlatform(): boolean {
  return !!(window as any).Capacitor?.isNativePlatform?.()
}

export interface UseNetworkStatusResult {
  /** Whether the device is currently online */
  isOnline: boolean
}

/**
 * Monitors network connectivity via @capacitor/network.
 * Shows online by default. On native, listens for status changes.
 * On web, falls back to navigator.onLine.
 *
 * Requirements: 53.1, 53.2, 53.3, 53.4
 */
export function useNetworkStatus(): UseNetworkStatusResult {
  const [isOnline, setIsOnline] = useState(true)

  useEffect(() => {
    let cleanup: (() => void) | null = null

    async function setup() {
      if (isNativePlatform()) {
        try {
          const { Network } = await import('@capacitor/network')
          const status = await Network.getStatus()
          setIsOnline(status.connected)

          const listener = await Network.addListener('networkStatusChange', (s) => {
            setIsOnline(s.connected)
          })
          cleanup = () => listener.remove()
        } catch {
          // Plugin not available — assume online
          setIsOnline(true)
        }
      } else {
        // Web fallback
        setIsOnline(navigator.onLine)
        const handleOnline = () => setIsOnline(true)
        const handleOffline = () => setIsOnline(false)
        window.addEventListener('online', handleOnline)
        window.addEventListener('offline', handleOffline)
        cleanup = () => {
          window.removeEventListener('online', handleOnline)
          window.removeEventListener('offline', handleOffline)
        }
      }
    }

    setup()
    return () => cleanup?.()
  }, [])

  return { isOnline }
}
