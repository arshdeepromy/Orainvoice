/**
 * Hook used by the rebuilt Reports landing (`ReportsPage.tsx`, design §E1) to
 * fetch the KPI row + Revenue-by-month + Revenue-by-category panels for the
 * selected range.
 *
 * Range options: 7D, 30D, QTR (last quarter ≈ 90 days), YR (last 365 days).
 *
 * Backend sources:
 *   - `GET /reports/revenue`      → Revenue, Average invoice KPIs + monthly_breakdown
 *   - `GET /reports/top-services` → Revenue-by-category (grouped Labour/Parts/Tyres/Other)
 *
 * KPIs whose source is not yet implemented (`gross_profit`, `jobs_completed`)
 * are returned as `null` so the caller can render the design's "—" placeholder
 * (R15.3, R19.5).
 *
 * Patterns:
 *   - Single AbortController per fetch cycle (R14.1, R19.x).
 *   - Typed generics on every `apiClient.get<T>(...)` call.
 *   - All array reads use `?? []`; all numeric reads use `?? 0`.
 *   - Refetches on `range` and `selectedBranchId` changes.
 *
 * Requirements: 15.5, 19.1, 19.2, 19.3, 14.1
 * Design: §"E1 — Rebuilt ReportsPage landing", §"Component map"
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import apiClient from '@/api/client'
import { useBranch } from '@/contexts/BranchContext'

export type ReportsRange = '7D' | '30D' | 'QTR' | 'YR'

export interface ReportsOverviewKpis {
  /** Total revenue (GST-inclusive) for the period in NZD; null when unavailable. */
  revenue: number | null
  /** Gross profit for the period in NZD; null when source is unavailable. */
  gross_profit: number | null
  /** Average invoice value for the period in NZD; null when unavailable. */
  average_invoice: number | null
  /** Number of jobs completed in the period; null when source is unavailable. */
  jobs_completed: number | null
}

export interface MonthlyRevenuePoint {
  month: string // YYYY-MM
  revenue: number
}

export interface RevenueCategoryPoint {
  category: string
  revenue: number
}

export interface UseReportsOverviewResult {
  range: ReportsRange
  setRange: (range: ReportsRange) => void
  kpis: ReportsOverviewKpis
  monthly: MonthlyRevenuePoint[]
  categories: RevenueCategoryPoint[]
  loading: boolean
  error: string | null
  refetch: () => void
}

// Backend response shapes (typed defensively — every field optional).
interface RevenueResponse {
  total_revenue?: number
  total_gst?: number
  total_inclusive?: number
  invoice_count?: number
  total_invoices?: number
  average_invoice?: number
  monthly_breakdown?: { month?: string; revenue?: number }[]
}

interface TopServiceRow {
  description?: string
  count?: number
  total_revenue?: number
}

interface TopServicesResponse {
  services?: TopServiceRow[]
}

/**
 * Convert a range token to a `[start_date, end_date]` pair (YYYY-MM-DD).
 * The end date is always "today" in the user's local timezone; the start
 * date is computed by stepping back the range's window.
 */
function rangeToDates(range: ReportsRange): { start_date: string; end_date: string } {
  const end = new Date()
  const start = new Date(end)
  switch (range) {
    case '7D':
      start.setDate(start.getDate() - 6) // inclusive 7-day window
      break
    case '30D':
      start.setDate(start.getDate() - 29)
      break
    case 'QTR':
      start.setMonth(start.getMonth() - 3)
      break
    case 'YR':
      start.setFullYear(start.getFullYear() - 1)
      break
  }
  const iso = (d: Date) => d.toISOString().slice(0, 10)
  return { start_date: iso(start), end_date: iso(end) }
}

/**
 * Group top-services rows into the four design categories
 * (Labour, Parts, Tyres, Other) by simple keyword match on the description.
 * Falls back to "Other" when no keyword matches. Returns an empty list when
 * no services were returned.
 */
function groupServicesByCategory(services: TopServiceRow[]): RevenueCategoryPoint[] {
  if (services.length === 0) return []

  const totals: Record<string, number> = {
    Labour: 0,
    Parts: 0,
    Tyres: 0,
    Other: 0,
  }

  for (const row of services) {
    const desc = (row?.description ?? '').toLowerCase()
    const revenue = row?.total_revenue ?? 0
    if (/\btyre|\btire/.test(desc)) {
      totals.Tyres += revenue
    } else if (/\blabou?r|\bservic|\brepair|\bdiagnos|\binstall/.test(desc)) {
      totals.Labour += revenue
    } else if (/\bpart|\bfilter|\bbattery|\bbrake|\boil|\bfluid/.test(desc)) {
      totals.Parts += revenue
    } else {
      totals.Other += revenue
    }
  }

  // Preserve canonical display order; drop empty buckets so the panel only
  // renders progress bars for categories with revenue.
  return (['Labour', 'Parts', 'Tyres', 'Other'] as const)
    .map((category) => ({ category, revenue: totals[category] ?? 0 }))
    .filter((row) => row.revenue > 0)
}

const EMPTY_KPIS: ReportsOverviewKpis = {
  revenue: null,
  gross_profit: null,
  average_invoice: null,
  jobs_completed: null,
}

export function useReportsOverview(initialRange: ReportsRange = '30D'): UseReportsOverviewResult {
  const { selectedBranchId } = useBranch()
  const [range, setRange] = useState<ReportsRange>(initialRange)
  const [kpis, setKpis] = useState<ReportsOverviewKpis>(EMPTY_KPIS)
  const [monthly, setMonthly] = useState<MonthlyRevenuePoint[]>([])
  const [categories, setCategories] = useState<RevenueCategoryPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const fetchOverview = useCallback(async () => {
    // Cancel any in-flight request before starting a new one.
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError(null)

    const { start_date, end_date } = rangeToDates(range)
    const params: Record<string, string> = { start_date, end_date }
    if (selectedBranchId) params.branch_id = selectedBranchId

    try {
      const [revenueRes, servicesRes] = await Promise.all([
        apiClient.get<RevenueResponse>('/reports/revenue', {
          params,
          signal: controller.signal,
        }),
        apiClient.get<TopServicesResponse>('/reports/top-services', {
          params,
          signal: controller.signal,
        }),
      ])

      if (controller.signal.aborted) return

      const revenue = revenueRes.data ?? {}
      const services = servicesRes.data?.services ?? []

      const monthlyPoints: MonthlyRevenuePoint[] = (revenue.monthly_breakdown ?? []).map((m) => ({
        month: m?.month ?? '',
        revenue: Number(m?.revenue ?? 0),
      }))

      const categoryPoints = groupServicesByCategory(services)

      setKpis({
        revenue: Number(revenue.total_inclusive ?? 0),
        // Gross profit + jobs completed have no backend source yet; return
        // null so the caller renders the "—" fallback (R15.3).
        gross_profit: null,
        average_invoice: Number(revenue.average_invoice ?? 0),
        jobs_completed: null,
      })
      setMonthly(monthlyPoints)
      setCategories(categoryPoints)
    } catch (err: unknown) {
      // Swallow cancellation — both AbortController name and axios CanceledError.
      if (controller.signal.aborted) return
      const name = (err as { name?: string })?.name
      if (name === 'CanceledError' || name === 'AbortError') return
      setError('Failed to load reports overview.')
      setKpis(EMPTY_KPIS)
      setMonthly([])
      setCategories([])
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }, [range, selectedBranchId])

  useEffect(() => {
    fetchOverview()
    return () => {
      abortRef.current?.abort()
    }
  }, [fetchOverview])

  return {
    range,
    setRange,
    kpis,
    monthly,
    categories,
    loading,
    error,
    refetch: fetchOverview,
  }
}

export default useReportsOverview
