/**
 * Hook to fetch all dashboard widget data in a single API call.
 *
 * Requirements: 15.1, 15.2, 15.3, 15.4
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '@/api/client'
import type { DashboardWidgetData } from './types'

interface UseDashboardWidgetsResult {
  data: DashboardWidgetData | null
  isLoading: boolean
  error: string | null
  refetch: () => void
}

function normaliseDashboardData(raw: DashboardWidgetData | undefined | null): DashboardWidgetData | null {
  if (!raw) return null
  return {
    recent_customers: {
      items: raw.recent_customers?.items ?? [],
      total: raw.recent_customers?.total ?? 0,
    },
    todays_bookings: {
      items: raw.todays_bookings?.items ?? [],
      total: raw.todays_bookings?.total ?? 0,
    },
    public_holidays: {
      items: raw.public_holidays?.items ?? [],
      total: raw.public_holidays?.total ?? 0,
    },
    inventory_overview: {
      items: raw.inventory_overview?.items ?? [],
      total: raw.inventory_overview?.total ?? 0,
    },
    cash_flow: {
      items: raw.cash_flow?.items ?? [],
      total: raw.cash_flow?.total ?? 0,
    },
    recent_claims: {
      items: raw.recent_claims?.items ?? [],
      total: raw.recent_claims?.total ?? 0,
    },
    active_staff: {
      items: raw.active_staff?.items ?? [],
      total: raw.active_staff?.total ?? 0,
    },
    expiry_reminders: {
      items: raw.expiry_reminders?.items ?? [],
      total: raw.expiry_reminders?.total ?? 0,
    },
    reminder_config: {
      wof_days: raw.reminder_config?.wof_days ?? 30,
      service_days: raw.reminder_config?.service_days ?? 30,
    },
  }
}

export function useDashboardWidgets(): UseDashboardWidgetsResult {
  const [data, setData] = useState<DashboardWidgetData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController>(undefined)

  const fetchWidgets = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setIsLoading(true)
    setError(null)

    try {
      const res = await apiClient.get<DashboardWidgetData>(
        '/dashboard/widgets',
        { signal: controller.signal },
      )
      setData(normaliseDashboardData(res.data))
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setError('Failed to load dashboard widgets.')
      setData(null)
    } finally {
      if (!controller.signal.aborted) {
        setIsLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    fetchWidgets()
    return () => {
      abortRef.current?.abort()
    }
  }, [fetchWidgets])

  return { data, isLoading, error, refetch: fetchWidgets }
}
