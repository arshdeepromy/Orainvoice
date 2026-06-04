import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { useTenant } from '@/contexts/TenantContext'
import { useBranch } from '@/contexts/BranchContext'
import { useAuth } from '@/contexts/AuthContext'
import { Spinner, AlertBanner, Button, cx } from '@/components/ui'
import { WidgetGrid } from './widgets/WidgetGrid'
import {
  DASHBOARD_RANGE_CONFIG,
  DASHBOARD_RANGE_ORDER,
  type DashboardRange,
} from './widgets/types'

/* ============================================================
   OrgAdminDashboard (Task 17) — the org / branch admin dashboard.
   ------------------------------------------------------------
   Logic source: frontend/src/pages/dashboard/OrgAdminDashboard.tsx.
   ALL data logic is copied VERBATIM (FR-1 / FR-2c):
     • Primary KPIs — parallel fetch (one AbortController + cancelled
       guard), branch-scoped via `branch_id` when a branch is selected:
         GET /reports/revenue       (revenue summary)
         GET /reports/outstanding   (outstanding + overdue derivation)
         GET /reports/storage       (storage usage gauge)
     • Branch metrics — GET /dashboard/branch-metrics (its own effect +
       AbortController, branch-scoped, silent-fail).
     • Compare branches — GET /dashboard/branch-comparison?branch_ids=…
       (only when compareMode && ≥2 selected; clears otherwise).
     • Storage gauge colour thresholds (≥90 red / ≥80 amber / else blue),
       the ≥80% storage alert banner, the overdue-invoice count derivation,
       and the compare-table max/min highlighting — all unchanged.
     • The automotive WidgetGrid gate:
         (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
       && user?.id  → <WidgetGrid userId branchId> (widgets owned by Task 18;
       a stub stands in until then — see widgets/WidgetGrid.tsx).

   Design (FR-2): restyled onto the redesign tokens with MainDashboard's
   patterns — `.page` + `.page-head`, KPI cards, Card-style sections, the
   storage gauge re-drawn with token colours, segmented compare chips, and
   `.mono` for every number/money. The original `secondary` Button variant
   maps onto the new `ghost` variant.
   ============================================================ */

interface OrgAdminData {
  revenue_summary?: {
    total_revenue: number
    total_gst: number
    total_inclusive: number
    invoice_count: number
    average_invoice: number
    period_start: string
    period_end: string
  }
  outstanding?: {
    total_outstanding: number
    count: number
    invoices: Array<{
      invoice_id: string
      invoice_number: string | null
      customer_name: string
      days_overdue: number
      balance_due: number
    }>
  }
  storage?: {
    used_bytes: number
    used_gb: number
    quota_gb: number
    usage_percent: number
  }
}

interface BranchMetric {
  branch_id: string
  branch_name: string
  revenue: number
  invoice_count: number
  invoice_value: number
  customer_count: number
  staff_count: number
  expenses: number
}

interface BranchMetricsData {
  metrics: BranchMetric[]
  totals: BranchMetric | null
}

interface BranchComparisonData {
  branches: BranchMetric[]
}

export function OrgAdminDashboard() {
  const { settings, tradeFamily } = useTenant()
  const { user } = useAuth()
  const { selectedBranchId, branches } = useBranch()
  const [data, setData] = useState<OrgAdminData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [branchMetrics, setBranchMetrics] = useState<BranchMetricsData | null>(null)
  const [compareMode, setCompareMode] = useState(false)
  const [selectedCompare, setSelectedCompare] = useState<string[]>([])
  const [comparison, setComparison] = useState<BranchComparisonData | null>(null)
  // Page-level range filter (prototype `.seg`): drives the revenue preset here
  // and the cash-flow widget period/window via WidgetGrid.
  const [range, setRange] = useState<DashboardRange>('30D')

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()
    async function fetchDashboard() {
      try {
        const params: Record<string, string> = {}
        if (selectedBranchId) params.branch_id = selectedBranchId
        const revenueParams = { ...params, preset: DASHBOARD_RANGE_CONFIG[range].preset }
        const [revenueRes, outstandingRes, storageRes] = await Promise.all([
          apiClient.get<OrgAdminData['revenue_summary']>('/reports/revenue', {
            params: revenueParams,
            signal: controller.signal,
          }),
          apiClient.get<OrgAdminData['outstanding']>('/reports/outstanding', {
            params,
            signal: controller.signal,
          }),
          apiClient.get<OrgAdminData['storage']>('/reports/storage', { signal: controller.signal }),
        ])
        if (!cancelled) {
          setData({
            revenue_summary: revenueRes.data,
            outstanding: outstandingRes.data,
            storage: storageRes.data,
          })
        }
      } catch (err) {
        if (!cancelled && !(err as { name?: string })?.name?.includes('Cancel')) {
          console.error('Dashboard error:', err)
          setError('Failed to load dashboard data')
        }
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    fetchDashboard()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [selectedBranchId, range])

  // Fetch branch metrics
  useEffect(() => {
    const controller = new AbortController()
    const fetchBranchMetrics = async () => {
      try {
        const params: Record<string, string> = {}
        if (selectedBranchId) params.branch_id = selectedBranchId
        const res = await apiClient.get<BranchMetricsData>('/dashboard/branch-metrics', {
          params,
          signal: controller.signal,
        })
        setBranchMetrics(res.data ?? null)
      } catch (err: unknown) {
        if (!(err as { name?: string })?.name?.includes('Cancel')) {
          // Silently fail
        }
      }
    }
    fetchBranchMetrics()
    return () => controller.abort()
  }, [selectedBranchId])

  // Fetch comparison data
  useEffect(() => {
    if (!compareMode || selectedCompare.length < 2) {
      setComparison(null)
      return
    }
    const controller = new AbortController()
    const fetchComparison = async () => {
      try {
        const res = await apiClient.get<BranchComparisonData>('/dashboard/branch-comparison', {
          params: { branch_ids: selectedCompare.join(',') },
          signal: controller.signal,
        })
        setComparison(res.data ?? null)
      } catch (err: unknown) {
        if (!(err as { name?: string })?.name?.includes('Cancel')) {
          // Silently fail
        }
      }
    }
    fetchComparison()
    return () => controller.abort()
  }, [compareMode, selectedCompare])

  if (isLoading) return <Spinner size="lg" label="Loading dashboard" className="py-20" />
  if (error) {
    return (
      <div className="page">
        <AlertBanner variant="error">{error}</AlertBanner>
      </div>
    )
  }
  if (!data) return null

  const storageUsedGb = data.storage ? data.storage.used_bytes / (1024 * 1024 * 1024) : 0
  const storageQuotaGb = data.storage ? data.storage.quota_gb : 0
  const storagePercent = data.storage?.usage_percent || 0
  const storageBarColor =
    storagePercent >= 90 ? 'bg-danger' : storagePercent >= 80 ? 'bg-warn' : 'bg-accent'

  // Count overdue invoices from outstanding data
  const overdueCount = data.outstanding?.invoices?.filter((inv) => inv.days_overdue > 0).length || 0

  return (
    <div className="page space-y-6">
      <div className="page-head">
        <div>
          <div className="eyebrow">Overview</div>
          <h1>{settings?.branding.name ?? 'Organisation'} Dashboard</h1>
        </div>
        <div
          className="inline-flex gap-0.5 rounded-ctl border border-border bg-card p-[3px]"
          role="group"
          aria-label="Date range"
        >
          {DASHBOARD_RANGE_ORDER.map((r) => (
            <button
              key={r}
              type="button"
              aria-pressed={range === r}
              onClick={() => setRange(r)}
              className={cx(
                'mono rounded-[7px] px-[13px] py-1.5 text-[12.5px] font-medium transition-colors',
                range === r ? 'bg-accent-soft text-accent' : 'text-muted hover:text-text',
              )}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* Storage alert - only show when usage is 80% or higher */}
      {data.storage && storagePercent >= 80 && (
        <AlertBanner variant={storagePercent >= 100 ? 'error' : 'warning'}>
          {storagePercent >= 100
            ? 'Storage quota exceeded. Please upgrade your plan or delete files.'
            : `Storage usage at ${Math.round(storagePercent)}%. Consider upgrading your plan.`}
        </AlertBanner>
      )}

      {/* KPI cards */}
      <div className="grid grid-cols-1 gap-gap sm:grid-cols-2 lg:grid-cols-4">
        {data.revenue_summary && (
          <KpiCard
            label="Revenue (This Period)"
            value={Number(data.revenue_summary.total_inclusive ?? 0).toLocaleString('en-NZ', {
              minimumFractionDigits: 2,
            })}
            money
            subtitle={`${data.revenue_summary.invoice_count ?? 0} invoices`}
          />
        )}
        {data.outstanding && (
          <KpiCard
            label="Outstanding Total"
            value={Number(data.outstanding.total_outstanding ?? 0).toLocaleString('en-NZ', {
              minimumFractionDigits: 2,
            })}
            money
            subtitle={`${data.outstanding.count ?? 0} invoices`}
          />
        )}
        <KpiCard label="Overdue Invoices" value={String(overdueCount)} variant={overdueCount > 0 ? 'error' : undefined} />
        {data.storage && (
          <div className="rounded-card border border-border bg-card p-5 shadow-card">
            <p className="text-[12.5px] font-medium text-muted">Storage Usage</p>
            <p className="mono mt-1.5 text-[22px] font-semibold leading-none text-text">
              {storageUsedGb.toFixed(1)} / {storageQuotaGb.toFixed(1)} GB
            </p>
            <div
              className="mt-3 h-2 w-full overflow-hidden rounded-full bg-canvas"
              role="progressbar"
              aria-valuenow={Math.round(storagePercent)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`Storage usage: ${Math.round(storagePercent)}%`}
            >
              <div
                className={cx('h-full rounded-full transition-all', storageBarColor)}
                style={{ width: `${Math.min(storagePercent, 100)}%` }}
              />
            </div>
            <p className="mono mt-1.5 text-[12px] text-muted-2">{Math.round(storagePercent)}% used</p>
          </div>
        )}
      </div>

      {/* Branch metrics section */}
      {branchMetrics && (branchMetrics.metrics ?? []).length > 0 && (
        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[15px] font-semibold text-text">
              {selectedBranchId ? 'Branch Metrics' : 'Branch Performance Summary'}
            </h2>
            {!selectedBranchId && (branches ?? []).length > 1 && (
              <Button size="sm" variant="ghost" onClick={() => setCompareMode(!compareMode)}>
                {compareMode ? 'Exit Compare' : 'Compare Branches'}
              </Button>
            )}
          </div>

          {!compareMode && (
            <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
              <table className="w-full border-collapse" role="grid">
                <caption className="sr-only">Branch performance metrics</caption>
                <thead>
                  <tr>
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Branch</th>
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Revenue</th>
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Invoices</th>
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Customers</th>
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Staff</th>
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Expenses</th>
                  </tr>
                </thead>
                <tbody>
                  {(branchMetrics.metrics ?? []).map((m) => (
                    <tr key={m.branch_id} className="border-b border-border transition-colors last:border-b-0 hover:bg-canvas">
                      <td className="px-5 py-3 text-[13.5px] font-medium text-text">{m.branch_name ?? '—'}</td>
                      <td className="mono px-5 py-3 text-right text-[13.5px] text-text">${(m.revenue ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2 })}</td>
                      <td className="mono px-5 py-3 text-right text-[13.5px] text-muted">{m.invoice_count ?? 0}</td>
                      <td className="mono px-5 py-3 text-right text-[13.5px] text-muted">{m.customer_count ?? 0}</td>
                      <td className="mono px-5 py-3 text-right text-[13.5px] text-muted">{m.staff_count ?? 0}</td>
                      <td className="mono px-5 py-3 text-right text-[13.5px] text-muted">${(m.expenses ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2 })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Compare Branches mode */}
          {compareMode && (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2">
                {(branches ?? []).map((b) => {
                  const isSelected = selectedCompare.includes(b.id)
                  return (
                    <button
                      key={b.id}
                      type="button"
                      onClick={() => {
                        setSelectedCompare((prev) =>
                          isSelected ? prev.filter((x) => x !== b.id) : [...prev, b.id],
                        )
                      }}
                      className={cx(
                        'rounded-full border px-3 py-1 text-[13px] font-medium transition-colors',
                        isSelected
                          ? 'border-accent bg-accent-soft text-accent'
                          : 'border-border bg-card text-muted hover:bg-canvas hover:text-text',
                      )}
                    >
                      {b.name}
                    </button>
                  )
                })}
              </div>
              {selectedCompare.length < 2 && (
                <p className="text-[13px] text-muted">Select at least 2 branches to compare.</p>
              )}
              {comparison && (comparison.branches ?? []).length >= 2 && (
                <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
                  <table className="w-full border-collapse" role="grid">
                    <caption className="sr-only">Branch comparison</caption>
                    <thead>
                      <tr>
                        <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Metric</th>
                        {(comparison.branches ?? []).map((b) => (
                          <th key={b.branch_id} scope="col" className="mono border-b border-border px-5 py-[11px] text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                            {b.branch_name}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(['revenue', 'invoice_count', 'customer_count', 'staff_count', 'expenses'] as const).map(
                        (metric) => {
                          const values = (comparison.branches ?? []).map((b) => (b[metric] ?? 0) as number)
                          const maxVal = Math.max(...values)
                          const minVal = Math.min(...values)
                          const label = metric.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
                          const isCurrency = metric === 'revenue' || metric === 'expenses'
                          return (
                            <tr key={metric} className="border-b border-border transition-colors last:border-b-0 hover:bg-canvas">
                              <td className="px-5 py-3 text-[13.5px] font-medium text-text">{label}</td>
                              {(comparison.branches ?? []).map((b) => {
                                const val = (b[metric] ?? 0) as number
                                const isMax = val === maxVal && values.filter((v) => v === maxVal).length === 1
                                const isMin = val === minVal && values.filter((v) => v === minVal).length === 1
                                return (
                                  <td key={b.branch_id} className="mono px-5 py-3 text-right text-[13.5px]">
                                    <span
                                      className={
                                        isMax
                                          ? 'font-semibold text-ok'
                                          : isMin
                                            ? 'text-danger'
                                            : 'text-text'
                                      }
                                    >
                                      {isCurrency
                                        ? `$${val.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`
                                        : val.toLocaleString()}
                                    </span>
                                  </td>
                                )
                              })}
                            </tr>
                          )
                        },
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {/* Automotive Dashboard Widgets — only for automotive-transport orgs */}
      {(tradeFamily ?? 'automotive-transport') === 'automotive-transport' && user?.id && (
        <WidgetGrid userId={user.id} branchId={selectedBranchId ?? null} range={range} />
      )}
    </div>
  )
}

/* ── KPI card — label / big mono value / optional sub ── */

function KpiCard({
  label,
  value,
  subtitle,
  variant,
  money,
}: {
  label: string
  value: string
  subtitle?: string
  variant?: 'error'
  money?: boolean
}) {
  return (
    <div className="rounded-card border border-border bg-card p-5 shadow-card">
      <p className="text-[12.5px] font-medium text-muted">{label}</p>
      <p
        className={cx(
          'mono mt-1.5 text-[27px] font-semibold leading-none tracking-[-0.02em]',
          variant === 'error' ? 'text-danger' : 'text-text',
        )}
      >
        {money && <span className="text-[17px] text-muted-2">$</span>}
        {value}
      </p>
      {subtitle && <p className="mono mt-2.5 text-[12px] font-medium text-muted-2">{subtitle}</p>}
    </div>
  )
}

export default OrgAdminDashboard
