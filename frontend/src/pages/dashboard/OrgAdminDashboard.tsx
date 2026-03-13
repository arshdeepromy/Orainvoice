import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { useTenant } from '@/contexts/TenantContext'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'

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

export function OrgAdminDashboard() {
  const { settings } = useTenant()
  const [data, setData] = useState<OrgAdminData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function fetchDashboard() {
      try {
        const [revenueRes, outstandingRes, storageRes] =
          await Promise.all([
            apiClient.get<OrgAdminData['revenue_summary']>('/reports/revenue'),
            apiClient.get<OrgAdminData['outstanding']>('/reports/outstanding'),
            apiClient.get<OrgAdminData['storage']>('/reports/storage'),
          ])
        if (!cancelled) {
          setData({
            revenue_summary: revenueRes.data,
            outstanding: outstandingRes.data,
            storage: storageRes.data,
          })
        }
      } catch (err) {
        if (!cancelled) {
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
    }
  }, [])

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

      {/* Recent overdue invoices */}
      {data.outstanding && data.outstanding.invoices && data.outstanding.invoices.length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-medium text-gray-900">Outstanding Invoices</h2>
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    Invoice
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    Customer
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                    Amount Due
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                    Days Overdue
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {data.outstanding.invoices.slice(0, 10).map((inv) => (
                  <tr key={inv.invoice_id} className={inv.days_overdue > 0 ? 'bg-red-50' : ''}>
                    <td className="px-4 py-3 text-sm text-gray-900">
                      {inv.invoice_number || inv.invoice_id}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-900">{inv.customer_name}</td>
                    <td className="px-4 py-3 text-sm text-gray-900 text-right">
                      ${Number(inv.balance_due).toLocaleString('en-NZ', { minimumFractionDigits: 2 })}
                    </td>
                    <td className="px-4 py-3 text-sm text-right">
                      {inv.days_overdue > 0 ? (
                        <span className="text-red-600 font-medium">{inv.days_overdue} days</span>
                      ) : (
                        <span className="text-gray-500">-</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
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
