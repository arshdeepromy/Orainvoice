import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Pure extraction functions — exported for property-based testing     */
/* ------------------------------------------------------------------ */

/**
 * Safely extract an array from an API response object using the given key.
 * Falls back to the 'items' key, then to an empty array.
 *
 * **Validates: Requirements 13.1**
 */
export function safeExtractItems<T>(
  responseData: unknown,
  dataKey: string,
): T[] {
  if (responseData === null || responseData === undefined || typeof responseData !== 'object') {
    return []
  }
  const data = responseData as Record<string, unknown>
  const byKey = data[dataKey]
  if (Array.isArray(byKey)) return byKey as T[]
  const byItems = data['items']
  if (Array.isArray(byItems)) return byItems as T[]
  return []
}

/**
 * Safely extract a total count from an API response object.
 * Falls back to 0.
 *
 * **Validates: Requirements 13.1**
 */
export function safeExtractTotal(responseData: unknown): number {
  if (responseData === null || responseData === undefined || typeof responseData !== 'object') {
    return 0
  }
  const data = responseData as Record<string, unknown>
  const total = data['total']
  if (typeof total === 'number' && !isNaN(total)) return total
  return 0
}

/**
 * Safely extract a single resource from an API response.
 * Returns null if the data is null/undefined.
 *
 * **Validates: Requirements 13.1**
 */
export function safeExtractDetail<T>(responseData: unknown): T | null {
  if (responseData === null || responseData === undefined) return null
  return responseData as T
}

export interface UseApiListOptions {
  /** API endpoint path (e.g. '/invoices') */
  endpoint: string
  /** Key in the response object that contains the array (e.g. 'items', 'invoices') */
  dataKey: string
  /** Number of items per page (default: 20) */
  pageSize?: number
  /** Query parameter name for search (default: 'search') */
  searchParam?: string
  /** Initial filter key-value pairs sent as query params */
  initialFilters?: Record<string, string>
}

export interface UseApiListResult<T> {
  items: T[]
  total: number
  isLoading: boolean
  isRefreshing: boolean
  error: string | null
  hasMore: boolean
  search: string
  setSearch: (value: string) => void
  refresh: () => Promise<void>
  loadMore: () => void
  filters: Record<string, string>
  setFilters: (filters: Record<string, string>) => void
}

export function useApiList<T>(
  options: UseApiListOptions,
): UseApiListResult<T> {
  const {
    endpoint,
    dataKey,
    pageSize = 20,
    searchParam = 'search',
    initialFilters = {},
  } = options

  const [items, setItems] = useState<T[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>(initialFilters)
  const [page, setPage] = useState(1)

  const abortRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(
    async (
      currentPage: number,
      isRefresh: boolean,
      signal: AbortSignal,
    ) => {
      if (isRefresh) {
        setIsRefreshing(true)
      } else if (currentPage === 1) {
        setIsLoading(true)
      }
      setError(null)

      try {
        const params: Record<string, string | number> = {
          skip: (currentPage - 1) * pageSize,
          limit: pageSize,
          ...filters,
        }
        if (search.trim()) {
          params[searchParam] = search.trim()
        }

        const res = await apiClient.get<Record<string, unknown>>(endpoint, {
          params,
          signal,
        })

        // Safe API Pattern: use optional chaining + nullish coalescing
        const responseData = res.data ?? {}
        const newItems = safeExtractItems<T>(responseData, dataKey)
        const newTotal = safeExtractTotal(responseData)

        if (currentPage === 1 || isRefresh) {
          setItems(newItems)
        } else {
          setItems((prev) => [...prev, ...newItems])
        }
        setTotal(newTotal)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load data')
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [endpoint, dataKey, pageSize, searchParam, search, filters],
  )

  // Fetch on mount and when search/filters change (reset to page 1)
  useEffect(() => {
    // Abort any in-flight request
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setPage(1)
    fetchData(1, false, controller.signal)

    return () => controller.abort()
  }, [fetchData])

  const refresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setPage(1)
    await fetchData(1, true, controller.signal)
  }, [fetchData])

  const loadMore = useCallback(() => {
    if (isLoading || isRefreshing) return
    if (items.length >= total) return

    const nextPage = page + 1
    setPage(nextPage)

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    fetchData(nextPage, false, controller.signal)
  }, [isLoading, isRefreshing, items.length, total, page, fetchData])

  const hasMore = items.length < total

  return {
    items,
    total,
    isLoading,
    isRefreshing,
    error,
    hasMore,
    search,
    setSearch,
    refresh,
    loadMore,
    filters,
    setFilters,
  }
}
