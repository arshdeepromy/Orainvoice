import { useEffect, useState } from 'react'
import apiClient from '@/api/client'

interface BadgeCountResponse {
  count: number
}

/**
 * Poll the compliance "needs attention" badge count for the sidebar.
 *
 * Backend: GET /api/v2/compliance-docs/badge-count → { count } — the number of
 * expired + expiring-soon compliance documents for the org
 * (app/modules/compliance_docs/router.py, registered at /api/v2/compliance-docs).
 *
 * Ported from frontend/src/pages/compliance/NotificationBadge.tsx. Only fetches
 * when `enabled` (the compliance_docs module is on for this org) so we don't hit
 * the endpoint for orgs without the module. Refetches on window focus so the
 * count stays fresh after the user resolves documents elsewhere. Errors are
 * swallowed — the badge keeps its previous value.
 */
export function useComplianceBadgeCount(enabled: boolean): number {
  const [count, setCount] = useState(0)

  useEffect(() => {
    if (!enabled) {
      setCount(0)
      return
    }

    const controller = new AbortController()

    const fetchCount = async () => {
      try {
        const res = await apiClient.get<BadgeCountResponse>(
          '/api/v2/compliance-docs/badge-count',
          { signal: controller.signal },
        )
        if (!controller.signal.aborted) setCount(res.data?.count ?? 0)
      } catch {
        // Silently ignore aborted requests and network errors.
      }
    }

    fetchCount()

    const handleFocus = () => {
      fetchCount()
    }
    window.addEventListener('focus', handleFocus)

    return () => {
      controller.abort()
      window.removeEventListener('focus', handleFocus)
    }
  }, [enabled])

  return count
}
