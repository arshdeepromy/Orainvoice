/**
 * React hook for fetching customer claims with summary statistics.
 *
 * Requirements: 9.1, 9.2, 9.3
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '../api/client'
import type { ClaimListItem } from './useClaims'

export interface CustomerClaimsSummary {
  total_claims: number
  open_claims: number
  total_cost_to_business: number | string
  claims: ClaimListItem[]
}

export function useCustomerClaims(customerId: string | undefined) {
  const [data, setData] = useState<CustomerClaimsSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController>(undefined)

  const fetch = useCallback(async () => {
    if (!customerId) return
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<CustomerClaimsSummary>(
        `/customers/${customerId}/claims`,
        { signal: controller.signal },
      )
      setData({
        total_claims: res.data?.total_claims ?? 0,
        open_claims: res.data?.open_claims ?? 0,
        total_cost_to_business: res.data?.total_cost_to_business ?? 0,
        claims: res.data?.claims ?? [],
      })
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setError('Failed to load customer claims.')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [customerId])

  useEffect(() => {
    fetch()
    return () => { abortRef.current?.abort() }
  }, [fetch])

  return { data, loading, error, refetch: fetch }
}
