import { useState, useEffect, useCallback } from 'react'

export interface OfflineState {
  /** Whether the browser currently has network connectivity */
  isOnline: boolean
  /** Whether the app was previously offline and just came back online */
  justReconnected: boolean
  /** Clear the justReconnected flag after handling it */
  clearReconnected: () => void
}

/**
 * Hook for detecting online/offline status using navigator.onLine
 * and the browser online/offline events.
 *
 * Validates: Requirements 77.1, 77.2, 77.3
 */
export function useOffline(): OfflineState {
  const [isOnline, setIsOnline] = useState(() =>
    typeof navigator !== 'undefined' ? navigator.onLine : true,
  )
  const [justReconnected, setJustReconnected] = useState(false)

  useEffect(() => {
    function handleOnline() {
      setIsOnline(true)
      setJustReconnected(true)
    }

    function handleOffline() {
      setIsOnline(false)
      setJustReconnected(false)
    }

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  const clearReconnected = useCallback(() => {
    setJustReconnected(false)
  }, [])

  return { isOnline, justReconnected, clearReconnected }
}
