import { useState, useEffect, useCallback, useRef } from 'react'
import { getUnreadCount } from '@/api/inbox'

const POLL_INTERVAL_MS = 30_000

export interface UseInboxBadgeResult {
  /** Current unread notification count */
  count: number
}

/**
 * Polls the unread notification count every 30 seconds.
 * Uses AbortController cleanup on unmount to prevent stale updates.
 * HTTP polling is universal — no Capacitor isNative guard needed.
 *
 * Requirements: 7.3
 */
export function useInboxBadge(): UseInboxBadgeResult {
  const [count, setCount] = useState(0)
  const controllerRef = useRef<AbortController | null>(null)

  const fetchCount = useCallback(async (signal: AbortSignal) => {
    try {
      const unread = await getUnreadCount(signal)
      setCount(unread)
    } catch {
      // Silently ignore aborted requests and network errors —
      // keep the last-known badge count.
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    controllerRef.current = controller

    // Initial fetch
    fetchCount(controller.signal)

    // Poll every 30s
    const intervalId = setInterval(() => {
      fetchCount(controller.signal)
    }, POLL_INTERVAL_MS)

    return () => {
      controller.abort()
      clearInterval(intervalId)
      controllerRef.current = null
    }
  }, [fetchCount])

  return { count }
}
