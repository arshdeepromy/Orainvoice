/**
 * React hooks for Claims API integration.
 *
 * Requirements: 1.1-1.8, 2.1-2.7, 3.1-3.8, 6.1-6.5, 7.1-7.5
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '../api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface ClaimListItem {
  id: string
  customer_id: string
  customer_name: string | null
  claim_type: string
  status: string
  description: string
  cost_to_business: number | string
  branch_id: string | null
  created_at: string
}

export interface ClaimListResponse {
  items: ClaimListItem[]
  total: number
}

export interface ClaimActionEntry {
  id: string
  action_type: string
  from_status: string | null
  to_status: string | null
  action_data: Record<string, unknown>
  notes: string | null
  performed_by: string
  performed_by_name: string | null
  performed_at: string
}

export interface CostBreakdown {
  labour_cost: number
  parts_cost: number
  write_off_cost: number
}

export interface ClaimDetail {
  id: string
  org_id: string
  branch_id: string | null
  customer_id: string
  customer: {
    id: string
    first_name: string
    last_name: string
    email: string | null
    phone: string | null
    company_name: string | null
  } | null
  invoice_id: string | null
  invoice: {
    id: string
    invoice_number: string | null
    total: number | string | null
    status: string | null
  } | null
  job_card_id: string | null
  job_card: {
    id: string
    description: string | null
    status: string | null
    vehicle_rego: string | null
  } | null
  line_item_ids: string[]
  claim_type: string
  status: string
  description: string
  resolution_type: string | null
  resolution_amount: number | string | null
  resolution_notes: string | null
  resolved_at: string | null
  resolved_by: string | null
  refund_id: string | null
  credit_note_id: string | null
  return_movement_ids: string[]
  warranty_job_id: string | null
  cost_to_business: number | string
  cost_breakdown: CostBreakdown
  created_by: string
  created_at: string
  updated_at: string
  actions: ClaimActionEntry[]
}

export interface ClaimFilters {
  status?: string
  claim_type?: string
  date_from?: string
  date_to?: string
  search?: string
  customer_id?: string
  branch_id?: string
}

/* ------------------------------------------------------------------ */
/*  useClaimsList                                                      */
/* ------------------------------------------------------------------ */

export function useClaimsList(filters: ClaimFilters = {}, limit = 25, offset = 0) {
  const [data, setData] = useState<ClaimListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController>()

  const fetch = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, string | number> = { limit, offset }
      if (filters.status) params.status = filters.status
      if (filters.claim_type) params.claim_type = filters.claim_type
      if (filters.date_from) params.date_from = filters.date_from
      if (filters.date_to) params.date_to = filters.date_to
      if (filters.search) params.search = filters.search
      if (filters.customer_id) params.customer_id = filters.customer_id
      if (filters.branch_id) params.branch_id = filters.branch_id

      const res = await apiClient.get<ClaimListResponse>('/claims', {
        params,
        signal: controller.signal,
      })
      setData({
        items: res.data?.items ?? [],
        total: res.data?.total ?? 0,
      })
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setError('Failed to load claims.')
      setData({ items: [], total: 0 })
    } finally {
      setLoading(false)
    }
  }, [filters.status, filters.claim_type, filters.date_from, filters.date_to, filters.search, filters.customer_id, filters.branch_id, limit, offset])

  useEffect(() => {
    fetch()
    return () => { abortRef.current?.abort() }
  }, [fetch])

  return { data, loading, error, refetch: fetch }
}

/* ------------------------------------------------------------------ */
/*  useClaimDetail                                                     */
/* ------------------------------------------------------------------ */

export function useClaimDetail(claimId: string | undefined) {
  const [claim, setClaim] = useState<ClaimDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetch = useCallback(async () => {
    if (!claimId) return
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<ClaimDetail>(`/claims/${claimId}`)
      setClaim(res.data ?? null)
    } catch {
      setError('Failed to load claim details.')
      setClaim(null)
    } finally {
      setLoading(false)
    }
  }, [claimId])

  useEffect(() => {
    fetch()
  }, [fetch])

  return { claim, loading, error, refetch: fetch }
}

/* ------------------------------------------------------------------ */
/*  useUpdateClaimStatus                                               */
/* ------------------------------------------------------------------ */

export function useUpdateClaimStatus() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const updateStatus = useCallback(async (claimId: string, newStatus: string, notes?: string) => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.patch<ClaimDetail>(`/claims/${claimId}/status`, {
        new_status: newStatus,
        notes: notes || undefined,
      })
      return res.data
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to update claim status.')
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  return { updateStatus, loading, error }
}

/* ------------------------------------------------------------------ */
/*  useResolveClaim                                                    */
/* ------------------------------------------------------------------ */

export function useResolveClaim() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const resolve = useCallback(async (
    claimId: string,
    payload: {
      resolution_type: string
      resolution_amount?: number | null
      resolution_notes?: string | null
      return_stock_item_ids?: string[]
    },
  ) => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.post<ClaimDetail>(`/claims/${claimId}/resolve`, payload)
      return res.data
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to resolve claim.')
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  return { resolve, loading, error }
}

/* ------------------------------------------------------------------ */
/*  useAddClaimNote                                                    */
/* ------------------------------------------------------------------ */

export function useAddClaimNote() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const addNote = useCallback(async (claimId: string, notes: string) => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.post<ClaimDetail>(`/claims/${claimId}/notes`, { notes })
      return res.data
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to add note.')
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  return { addNote, loading, error }
}

/* ------------------------------------------------------------------ */
/*  useCreateClaim                                                     */
/* ------------------------------------------------------------------ */

export function useCreateClaim() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const create = useCallback(async (payload: {
    customer_id: string
    claim_type: string
    description: string
    invoice_id?: string | null
    job_card_id?: string | null
    line_item_ids?: string[]
    branch_id?: string | null
  }) => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.post<ClaimDetail>('/claims', payload)
      return res.data
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to create claim.')
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  return { create, loading, error }
}
