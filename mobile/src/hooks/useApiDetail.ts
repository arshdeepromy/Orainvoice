import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '@/api/client'

export interface UseApiDetailOptions {
  /** API endpoint path (e.g. '/invoices/123') */
  endpoint: string
  /** Whether to fetch immediately (default: true). Set false to defer. */
  enabled?: boolean
}

export interface UseApiDetailResult<T> {
  data: T | null
  isLoading: boolean
  error: string | null
  refetch: () => Promise<void>
}

export function useApiDetail<T>(
  options: UseApiDetailOptions,
): UseApiDetailResult<T> {
  const { endpoint, enabled = true } = options

  const [data, setData] = useState<T | null>(null)
  const [isLoading, setIsLoading] = useState(enabled)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(
    async (signal: AbortSignal) => {
      setIsLoading(true)
      setError(null)

      try {
        const res = await apiClient.get<T>(endpoint, { signal })
        // Safe API Pattern: guard against null/undefined response
        setData(res.data ?? null)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load data')
        }
      } finally {
        setIsLoading(false)
      }
    },
    [endpoint],
  )

  useEffect(() => {
    if (!enabled) {
      setIsLoading(false)
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    fetchData(controller.signal)

    return () => controller.abort()
  }, [enabled, fetchData])

  const refetch = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    await fetchData(controller.signal)
  }, [fetchData])

  return { data, isLoading, error, refetch }
}
