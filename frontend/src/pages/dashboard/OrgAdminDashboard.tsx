import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { useTenant } from '@/contexts/TenantContext'
import { useBranch } from '@/contexts/BranchContext'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Button } from '@/components/ui/Button'
import { WidgetGrid } from './widgets/WidgetGrid'
import { useAuth } from '@/contexts/AuthContext'

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

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()
    async function fetchDashboard() {
      try {
        const params: Record<string, string> = {}
        if (selectedBranchId) params.branch_id = selectedBranchId
        const [revenueRes, outstandingRes, storageRes] =
          await Promise.all([
            apiClient.get<OrgAdminData['revenue_summary']>('/reports/revenue', { params, signal: controller.signal }),
            apiClient.get<OrgAdminData['outstanding']>('/reports/outstanding', { params, signal: controller.signal }),
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
  }, [selectedBranchId])

  // Fetch branch metrics
  useEffect(() => {
    const controller = new AbortController()
    const fetchBranchMetrics = async () => {
      try {
        const params: Record<string, string> = {}
        if (selectedBranchId) params.branch_id = selectedBranchId
        const res = await apiClient.get<BranchMetricsData>(
          '/dashboard/branch-metrics',
          { params, signal: controller.signal },
        )
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
        const res = await apiClient.get<BranchComparisonData>(
          '/dashboard/branch-comparison',
          { params: { branch_ids: selectedCompare.join(',') }, signal: controller.signal },
        )
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
  if (error) return <AlertBanner variant="error">{error}</AlertBanner>
  if (!data) return null

  const storageUsedGb = data.storage ? data.storage.used_bytes / (1024 * 1024 * 1024) : 0
  const storageQuotaGb = data.storage ? data.storage.quota_gb : 0
  const storagePercent = data.storage?.usage_percent || 0
  const storageBarColor =
    storagePercent >= 90 ? 'bg-red-500' : storagePercent >= 80 ? 'bg-amber-500' : 'bg-blue-500'

  // Count overdue invoices from outstanding data
  const overdueCount = data.outstanding?.invoices?.filter(inv => inv.days_overdue > 0).length || 0

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-gray-900">
        {settings?.branding.name ?? 'Organisation'} Dashboard
      </h1>

      {/* Storage alert - only show when usage is 80% or higher */}
      {data.storage && storagePercent >= 80 && (
        <AlertBanner variant={storagePercent >= 100 ? 'error' : 'warning'}>
          {storagePercent >= 100
            ? 'Storage quota exceeded. Please upgrade your plan or delete files.'
            : `Storage usage at ${Math.round(storagePercent)}%. Consider upgrading your plan.`}
        </AlertBanner>
      )}

      {/* KPI cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {data.revenue_summary && (
          <KpiCard
            label="Revenue (This Period)"
            value={`$${Number(data.revenue_summary.total_inclusive).toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`}
            subtitle={`${data.revenue_summary.invoice_count} invoices`}
          />
        )}
        {data.outstanding && (
          <KpiCard
            label="Outstanding Total"
            value={`$${Number(data.outstanding.total_outstanding).toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`}
            subtitle={`${data.outstanding.count} invoices`}
          />
        )}
        <KpiCard
          label="Overdue Invoices"
          value={overdueCount}
          variant={overdueCount > 0 ? 'error' : undefined}
        />
        {data.storage && (
          <div className="rounded-lg border border-gray-200 bg-white p-5">
            <p className="text-sm font-medium text-gray-500">Storage Usage</p>
            <p className="mt-1 text-2xl font-semibold text-gray-900">
              {storageUsedGb.toFixed(1)} / {storageQuotaGb.toFixed(1)} GB
            </p>
            <div
              className="mt-2 h-2 w-full overflow-hidden rounded-full bg-gray-200"
              role="progressbar"
              aria-valuenow={Math.round(storagePercent)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`Storage usage: ${Math.round(storagePercent)}%`}
            >
              <div
                className={`h-full rounded-full transition-all ${storageBarColor}`}
                style={{ width: `${Math.min(storagePercent, 100)}%` }}
              />
            </div>
            <p className="mt-1 text-xs text-gray-500">{Math.round(storagePercent)}% used</p>
          </div>
        )}
      </div>

      {/* Branch metrics section */}
      {branchMetrics && (branchMetrics.metrics ?? []).length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-medium text-gray-900">
              {selectedBranchId ? 'Branch Metrics' : 'Branch Performance Summary'}
            </h2>
            {!selectedBranchId && (branches ?? []).length > 1 && (
              <Button size="sm" variant="secondary" onClick={() => setCompareMode(!compareMode)}>
                {compareMode ? 'Exit Compare' : 'Compare Branches'}
              </Button>
            )}
          </div>

          {!compareMode && (
            <div className="overflow-x-auto rounded-lg border border-gray-200">
              <table className="min-w-full divide-y divide-gray-200" role="grid">
                <caption className="sr-only">Branch performance metrics</caption>
                <thead className="bg-gray-50">
                  <tr>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Branch</th>
                    <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Revenue</th>
                    <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Invoices</th>
                    <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Customers</th>
                    <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Staff</th>
                    <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Expenses</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 bg-white">
                  {(branchMetrics.metrics ?? []).map((m) => (
                    <tr key={m.branch_id} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{m.branch_name ?? '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-900">${(m.revenue ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2 })}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{m.invoice_count ?? 0}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{m.customer_count ?? 0}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{m.staff_count ?? 0}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">${(m.expenses ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2 })}</td>
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
                      onClick={() => {
                        setSelectedCompare((prev) =>
                          isSelected ? prev.filter((x) => x !== b.id) : [...prev, b.id],
                        )
                      }}
                      className={`rounded-full px-3 py-1 text-sm font-medium border transition-colors ${
                        isSelected
                          ? 'bg-blue-100 border-blue-400 text-blue-800'
                          : 'bg-gray-100 border-gray-300 text-gray-600 hover:bg-gray-200'
                      }`}
                    >
                      {b.name}
                    </button>
                  )
                })}
              </div>
              {selectedCompare.length < 2 && (
                <p className="text-sm text-gray-500">Select at least 2 branches to compare.</p>
              )}
              {comparison && (comparison.branches ?? []).length >= 2 && (
                <div className="overflow-x-auto rounded-lg border border-gray-200">
                  <table className="min-w-full divide-y divide-gray-200" role="grid">
                    <caption className="sr-only">Branch comparison</caption>
                    <thead className="bg-gray-50">
                      <tr>
                        <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Metric</th>
                        {(comparison.branches ?? []).map((b) => (
                          <th key={b.branch_id} scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">{b.branch_name}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200 bg-white">
                      {(['revenue', 'invoice_count', 'customer_count', 'staff_count', 'expenses'] as const).map((metric) => {
                        const values = (comparison.branches ?? []).map((b) => (b[metric] ?? 0) as number)
                        const maxVal = Math.max(...values)
                        const minVal = Math.min(...values)
                        const label = metric.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
                        const isCurrency = metric === 'revenue' || metric === 'expenses'
                        return (
                          <tr key={metric} className="hover:bg-gray-50">
                            <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{label}</td>
                            {(comparison.branches ?? []).map((b) => {
                              const val = (b[metric] ?? 0) as number
                              const isMax = val === maxVal && values.filter((v) => v === maxVal).length === 1
                              const isMin = val === minVal && values.filter((v) => v === minVal).length === 1
                              return (
                                <td key={b.branch_id} className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums">
                                  <span className={isMax ? 'text-green-700 font-semibold' : isMin ? 'text-red-600' : 'text-gray-900'}>
                                    {isCurrency ? `$${val.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}` : val.toLocaleString()}
                                  </span>
                                </td>
                              )
                            })}
                          </tr>
                        )
                      })}
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
        <WidgetGrid userId={user.id} branchId={selectedBranchId ?? null} />
      )}
    </div>
  )
}

function KpiCard({
  label,
  value,
  subtitle,
  variant,
}: {
  label: string
  value: number | string
  subtitle?: string
  variant?: 'error'
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <p className="text-sm font-medium text-gray-500">{label}</p>
      <p
        className={`mt-1 text-2xl font-semibold ${
          variant === 'error' ? 'text-red-600' : 'text-gray-900'
        }`}
      >
        {value}
      </p>
      {subtitle && (
        <p className="mt-1 text-xs text-gray-500">{subtitle}</p>
      )}
    </div>
  )
}
