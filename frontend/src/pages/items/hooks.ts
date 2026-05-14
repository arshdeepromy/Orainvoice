import { useState, useEffect, useRef, useCallback } from 'react'
import apiClient from '../../api/client'
import type {
  PackageCostResponse,
  PartSearchResult,
  FluidSearchResult,
} from './types'

/* ------------------------------------------------------------------ */
/*  usePackageCosts — resolve live costs for a package item            */
/* ------------------------------------------------------------------ */

interface UsePackageCostsResult {
  data: PackageCostResponse | null
  loading: boolean
  error: string | null
  refetch: () => void
}

/**
 * Fetches live cost resolution for all components of a package item.
 * Calls GET /catalogue/items/:id/package-costs.
 *
 * Validates: Requirements 5.1, 5.6
 */
export function usePackageCosts(itemId: string | null): UsePackageCostsResult {
  const [data, setData] = useState<PackageCostResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [trigger, setTrigger] = useState(0)

  const refetch = useCallback(() => setTrigger((t) => t + 1), [])

  useEffect(() => {
    if (!itemId) {
      setData(null)
      setLoading(false)
      setError(null)
      return
    }

    const controller = new AbortController()
    const fetchCosts = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await apiClient.get<PackageCostResponse>(
          `/catalogue/items/${itemId}/package-costs`,
          { signal: controller.signal }
        )
        setData({
          components: res.data?.components ?? [],
          total_cost: res.data?.total_cost,
          sell_price: res.data?.sell_price,
          profit: res.data?.profit,
        })
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          const message =
            (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            'Failed to load package costs.'
          setError(message)
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }
    fetchCosts()
    return () => controller.abort()
  }, [itemId, trigger])

  return { data, loading, error, refetch }
}

/* ------------------------------------------------------------------ */
/*  usePartsSearch — debounced search for parts/tyres                  */
/* ------------------------------------------------------------------ */

interface UsePartsSearchResult {
  items: PartSearchResult[]
  loading: boolean
  error: string | null
}

/**
 * Searches the parts catalogue with debounced input.
 * Calls GET /catalogue/parts/search?q=...&part_type=part|tyre.
 *
 * Validates: Requirements 4.1, 4.5
 */
export function usePartsSearch(query: string, partType: 'part' | 'tyre'): UsePartsSearchResult {
  const [items, setItems] = useState<PartSearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    // Clear previous debounce
    if (debounceRef.current) {
      clearTimeout(debounceRef.current)
    }

    // Don't search for very short queries
    if (!query || query.trim().length < 2) {
      setItems([])
      setLoading(false)
      setError(null)
      return
    }

    const controller = new AbortController()
    setLoading(true)

    debounceRef.current = setTimeout(async () => {
      try {
        const res = await apiClient.get<{ items: PartSearchResult[] }>(
          '/catalogue/parts/search',
          {
            params: { q: query.trim(), part_type: partType, limit: 20 },
            signal: controller.signal,
          }
        )
        setItems(res.data?.items ?? [])
        setError(null)
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          const message =
            (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            'Failed to search parts.'
          setError(message)
          setItems([])
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }, 300)

    return () => {
      controller.abort()
      if (debounceRef.current) {
        clearTimeout(debounceRef.current)
      }
    }
  }, [query, partType])

  return { items, loading, error }
}

/* ------------------------------------------------------------------ */
/*  useFluidsSearch — debounced search for fluids                      */
/* ------------------------------------------------------------------ */

interface UseFluidsSearchResult {
  items: FluidSearchResult[]
  loading: boolean
  error: string | null
}

/**
 * Searches the fluids catalogue with debounced input.
 * Calls GET /catalogue/fluids/search?q=...&fluid_type=...&oil_type=...
 *
 * Validates: Requirements 3.3, 3.5
 */
export function useFluidsSearch(
  query: string,
  fluidType?: string,
  oilType?: string
): UseFluidsSearchResult {
  const [items, setItems] = useState<FluidSearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    // Clear previous debounce
    if (debounceRef.current) {
      clearTimeout(debounceRef.current)
    }

    // Don't search for very short queries (but allow empty query when filters are set)
    if (!query && !fluidType && !oilType) {
      setItems([])
      setLoading(false)
      setError(null)
      return
    }

    const controller = new AbortController()
    setLoading(true)

    debounceRef.current = setTimeout(async () => {
      try {
        const params: Record<string, string | number> = { limit: 20 }
        if (query.trim()) params.q = query.trim()
        if (fluidType) params.fluid_type = fluidType
        if (oilType) params.oil_type = oilType

        const res = await apiClient.get<{ items: FluidSearchResult[] }>(
          '/catalogue/fluids/search',
          { params, signal: controller.signal }
        )
        setItems(res.data?.items ?? [])
        setError(null)
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          const message =
            (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            'Failed to search fluids.'
          setError(message)
          setItems([])
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }, 300)

    return () => {
      controller.abort()
      if (debounceRef.current) {
        clearTimeout(debounceRef.current)
      }
    }
  }, [query, fluidType, oilType])

  return { items, loading, error }
}
