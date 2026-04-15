/**
 * React hooks for Claims Reports API integration.
 *
 * Requirements: 10.1-10.6
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '../api/client'

/* ------------------------------------------------------------------ */
/*  Types matching backend Pydantic schemas exactly                    */
/* ------------------------------------------------------------------ */

export interface ClaimsByPeriodItem {
  period: string | null
  claim_count: number
  total_cost: number | string
  average_resolution_hours: number
}

export interface ClaimsByPeriodResponse {
  periods: ClaimsByPeriodItem[]
}

export interface CostOverheadResponse {
  total_refunds: number | string
  total_credit_notes: number | string
  total_write_offs: number | string
  total_labour_cost: number | string
}

export interface SupplierQualityItem {
  product_id: string
  product_name: string
  sku: string | null
  return_count: number
}

export interface SupplierQualityResponse {
  items: SupplierQualityItem[]
}

export interface ServiceQualityItem {
  staff_id: string
  staff_name: string
  redo_count: number
}

export interface ServiceQualityResponse {
  items: ServiceQualityItem[]
}

export interface ReportFilters {
  date_from?: string
  date_to?: string
  branch_id?: string
}


/* ------------------------------------------------------------------ */
/*  useClaimsByPeriodReport                                            */
/* ------------------------------------------------------------------ */

export function useClaimsByPeriodReport(filters: ReportFilters = {}) {
  const [data, setData] = useState<ClaimsByPeriodResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController>(undefined)

  const fetch = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, string> = {}
      if (filters.date_from) params.date_from = filters.date_from
      if (filters.date_to) params.date_to = filters.date_to
      if (filters.branch_id) params.branch_id = filters.branch_id

      const res = await apiClient.get<ClaimsByPeriodResponse>(
        '/claims/reports/by-period',
        { params, signal: controller.signal },
      )
      setData({ periods: res.data?.periods ?? [] })
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setError('Failed to load claims by period report.')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [filters.date_from, filters.date_to, filters.branch_id])

  useEffect(() => {
    fetch()
    return () => { abortRef.current?.abort() }
  }, [fetch])

  return { data, loading, error, refetch: fetch }
}

/* ------------------------------------------------------------------ */
/*  useCostOverheadReport                                              */
/* ------------------------------------------------------------------ */

export function useCostOverheadReport(filters: ReportFilters = {}) {
  const [data, setData] = useState<CostOverheadResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController>(undefined)

  const fetch = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, string> = {}
      if (filters.date_from) params.date_from = filters.date_from
      if (filters.date_to) params.date_to = filters.date_to
      if (filters.branch_id) params.branch_id = filters.branch_id

      const res = await apiClient.get<CostOverheadResponse>(
        '/claims/reports/cost-overhead',
        { params, signal: controller.signal },
      )
      setData({
        total_refunds: res.data?.total_refunds ?? 0,
        total_credit_notes: res.data?.total_credit_notes ?? 0,
        total_write_offs: res.data?.total_write_offs ?? 0,
        total_labour_cost: res.data?.total_labour_cost ?? 0,
      })
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setError('Failed to load cost overhead report.')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [filters.date_from, filters.date_to, filters.branch_id])

  useEffect(() => {
    fetch()
    return () => { abortRef.current?.abort() }
  }, [fetch])

  return { data, loading, error, refetch: fetch }
}

/* ------------------------------------------------------------------ */
/*  useSupplierQualityReport                                           */
/* ------------------------------------------------------------------ */

export function useSupplierQualityReport(filters: ReportFilters = {}) {
  const [data, setData] = useState<SupplierQualityResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController>(undefined)

  const fetch = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, string> = {}
      if (filters.date_from) params.date_from = filters.date_from
      if (filters.date_to) params.date_to = filters.date_to
      if (filters.branch_id) params.branch_id = filters.branch_id

      const res = await apiClient.get<SupplierQualityResponse>(
        '/claims/reports/supplier-quality',
        { params, signal: controller.signal },
      )
      setData({ items: res.data?.items ?? [] })
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setError('Failed to load supplier quality report.')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [filters.date_from, filters.date_to, filters.branch_id])

  useEffect(() => {
    fetch()
    return () => { abortRef.current?.abort() }
  }, [fetch])

  return { data, loading, error, refetch: fetch }
}

/* ------------------------------------------------------------------ */
/*  useServiceQualityReport                                            */
/* ------------------------------------------------------------------ */

export function useServiceQualityReport(filters: ReportFilters = {}) {
  const [data, setData] = useState<ServiceQualityResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController>(undefined)

  const fetch = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, string> = {}
      if (filters.date_from) params.date_from = filters.date_from
      if (filters.date_to) params.date_to = filters.date_to
      if (filters.branch_id) params.branch_id = filters.branch_id

      const res = await apiClient.get<ServiceQualityResponse>(
        '/claims/reports/service-quality',
        { params, signal: controller.signal },
      )
      setData({ items: res.data?.items ?? [] })
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setError('Failed to load service quality report.')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [filters.date_from, filters.date_to, filters.branch_id])

  useEffect(() => {
    fetch()
    return () => { abortRef.current?.abort() }
  }, [fetch])

  return { data, loading, error, refetch: fetch }
}
