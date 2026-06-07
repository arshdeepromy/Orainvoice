import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

interface UnreadCountResponse {
  count: number
}

const POLL_INTERVAL_MS = 10_000

/**
 * Poll the unread in-app notification count for the top-bar bell badge.
 *
 * Backend: GET /api/v1/notifications/inbox/unread-count → { count }
 * (app/modules/in_app_notifications/router.py). Cheap, indexed COUNT query
 * designed for short-interval polling. The endpoint 403s for global admins and
 * when no org context is present; those errors are swallowed so the count just
 * stays at 0 (no badge), matching the original frontend behaviour.
 *
 * Ported from frontend/src/components/notifications/InboxBellBadge.tsx — same
 * 10s poll + refetch-on-window-focus, returned as a number so the presentational
 * TopBar badge can render it (TopBar hides the badge at 0).
 */
export function useUnreadNotificationCount(): number {
  const [count, setCount] = useState(0)

  const fetchCount = useCallback(async (signal: AbortSignal) => {
    try {
      const res = await apiClient.get<UnreadCountResponse>(
        '/notifications/inbox/unread-count',
        { signal },
      )
      setCount(res.data?.count ?? 0)
    } catch {
      // Silently ignore aborted requests, 403s (global admin / no org context)
      // and network errors — the badge keeps its previous value.
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()

    // Initial fetch.
    fetchCount(controller.signal)

    // Poll on an interval.
    const intervalId = setInterval(() => {
      fetchCount(controller.signal)
    }, POLL_INTERVAL_MS)

    // Refetch when the window regains focus so the badge is fresh on return.
    const handleFocus = () => {
      fetchCount(controller.signal)
    }
    window.addEventListener('focus', handleFocus)

    return () => {
      controller.abort()
      clearInterval(intervalId)
      window.removeEventListener('focus', handleFocus)
    }
  }, [fetchCount])

  return count
}
