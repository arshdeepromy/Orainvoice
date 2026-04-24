import { useEffect, useState } from 'react'
import apiClient from '@/api/client'

interface BadgeCountResponse {
  count: number
}

interface NotificationBadgeProps {
  /** Change this value to trigger a re-fetch (e.g. increment on navigation) */
  refreshKey?: number
}

export default function NotificationBadge({ refreshKey }: NotificationBadgeProps) {
  const [count, setCount] = useState(0)

  useEffect(() => {
    const controller = new AbortController()

    const fetchBadgeCount = async () => {
      try {
        const res = await apiClient.get<BadgeCountResponse>(
          '/api/v2/compliance-docs/badge-count',
          { signal: controller.signal },
        )
        setCount(res.data?.count ?? 0)
      } catch {
        // Silently ignore aborted requests and network errors —
        // the badge simply stays at its previous value.
        if (!controller.signal.aborted) {
          setCount(0)
        }
      }
    }

    fetchBadgeCount()

    return () => controller.abort()
  }, [refreshKey])

  if (count === 0) return null

  return (
    <span
      className="ml-auto inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-500 px-1.5 text-xs font-semibold leading-none text-white"
      aria-label={`${count} compliance document${count === 1 ? '' : 's'} need attention`}
    >
      {count}
    </span>
  )
}
