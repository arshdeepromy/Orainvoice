/**
 * ShiftSwapBadge — sidebar red dot counter for managers showing the
 * number of `awaiting_manager` shift-swap requests (G8).
 *
 * The badge is hidden when:
 *   - the count is zero, or
 *   - the user is not a manager (org_admin / branch_admin).
 *
 * Backend: queries `/api/v2/shift-swaps?status=awaiting_manager&limit=1`
 * and reads `total` from the `{ items, total }` response shape.
 *
 * Refs: Phase 3 G8 / D7.
 */

import { useEffect, useState } from 'react'

import apiClient from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'

interface ShiftSwapListResponse {
  items?: unknown[]
  total?: number | null
}

const MANAGER_ROLES = new Set(['org_admin', 'branch_admin'])

export default function ShiftSwapBadge() {
  const { user } = useAuth()
  const isManager = MANAGER_ROLES.has(user?.role ?? '')
  const [count, setCount] = useState<number>(0)

  useEffect(() => {
    if (!isManager) {
      setCount(0)
      return
    }
    const controller = new AbortController()
    const load = async () => {
      try {
        const res = await apiClient.get<ShiftSwapListResponse>(
          '/api/v2/shift-swaps',
          {
            params: { status: 'awaiting_manager', offset: 0, limit: 1 },
            signal: controller.signal,
          },
        )
        if (controller.signal.aborted) return
        setCount(res.data?.total ?? 0)
      } catch {
        if (!controller.signal.aborted) setCount(0)
      }
    }
    void load()
    return () => controller.abort()
  }, [isManager])

  if (!isManager || count <= 0) return null

  return (
    <span
      className="ml-auto inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-500 px-1.5 text-xs font-semibold leading-none text-white"
      aria-label={`${count} shift swap${count === 1 ? '' : 's'} awaiting your approval`}
      data-testid="shift-swap-sidebar-badge"
    >
      {count}
    </span>
  )
}
