import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

interface UnreadCountResponse {
  count: number
}

const POLL_INTERVAL_MS = 10_000

/**
 * Small red badge showing the unread notification count.
 * Polls /notifications/inbox/unread-count every 30s and refetches on window focus.
 * Returns null when count is 0 so no badge renders.
 *
 * Validates: Requirements 6.1.1, 6.1.2, 6.1.7
 */
export default function InboxBellBadge() {
  const [count, setCount] = useState(0)

  const fetchCount = useCallback(async (signal: AbortSignal) => {
    try {
      const res = await apiClient.get<UnreadCountResponse>(
        '/notifications/inbox/unread-count',
        { signal },
      )
      setCount(res.data?.count ?? 0)
    } catch {
      // Silently ignore aborted requests and network errors —
      // the badge stays at its previous value.
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()

    // Initial fetch
    fetchCount(controller.signal)

    // Poll every 30s
    const intervalId = setInterval(() => {
      fetchCount(controller.signal)
    }, POLL_INTERVAL_MS)

    // Refetch on window focus
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

  if (count === 0) return null

  const displayCount = count > 99 ? '99+' : String(count)

  return (
    <span
      className="absolute -top-1 -right-1 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-500 px-1 text-[11px] font-bold leading-none text-white"
      aria-label={`${count} unread notification${count === 1 ? '' : 's'}`}
    >
      {displayCount}
    </span>
  )
}
