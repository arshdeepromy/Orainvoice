import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { useTenant } from '@/contexts/TenantContext'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'

interface OrgAdminData {
  revenue_summary: {
    current_period: number
    previous_period: number
    change_percent: number
  }
  outstanding_total: number
  overdue_count: number
  storage: {
    used_bytes: number
    quota_gb: number
  }
  activity_feed: ActivityItem[]
  system_alerts: SystemAlert[]
}

interface ActivityItem {
  id: string
  message: string
  timestamp: string
  user_name: string
}

interface SystemAlert {
  id: string
  type: 'storage_warning' | 'billing_issue' | 'general'
  severity: 'info' | 'warning' | 'error'
  message: string
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
        const [revenueRes, outstandingRes, storageRes, activityRes] =
          await Promise.all([
            apiClient.get<OrgAdminData['revenue_summary']>('/reports/revenue'),
            apiClient.get<{ total: number; overdue_count: number }>(
              '/reports/outstanding',
            ),
            apiClient.get<{ used_bytes: number; quota_gb: number }>(
              '/reports/storage',
            ),
            apiClient.get<{
              activity: ActivityItem[]
              alerts: SystemAlert[]
            }>('/reports/activity'),
          ])
        if (!cancelled) {
          setData({
            revenue_summary: revenueRes.data,
            outstanding_total: outstandingRes.data.total,
            overdue_count: outstandingRes.data.overdue_count,
            storage: storageRes.data,
            activity_feed: activityRes.data.activity,
            system_alerts: activityRes.data.alerts,
          })
        }
      } catch {
        if (!cancelled) setError('Failed to load dashboard data')
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

  const storageUsedGb = data.storage.used_bytes / (1024 * 1024 * 1024)
  const storagePercent = data.storage.quota_gb > 0
    ? Math.min((storageUsedGb / data.storage.quota_gb) * 100, 100)
    : 0
  const storageBarColor =
    storagePercent >= 90 ? 'bg-red-500' : storagePercent >= 80 ? 'bg-amber-500' : 'bg-blue-500'

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-gray-900">
        {settings?.branding.name ?? 'Organisation'} Dashboard
      </h1>

      {/* System alerts */}
      {data.system_alerts.map((alert) => (
        <AlertBanner key={alert.id} variant={alert.severity === 'error' ? 'error' : 'warning'}>
          {alert.message}
        </AlertBanner>
      ))}

      {/* KPI cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          label="Revenue (This Period)"
          value={`$${data.revenue_summary.current_period.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`}
          change={data.revenue_summary.change_percent}
        />
        <KpiCard
          label="Outstanding Total"
          value={`$${data.outstanding_total.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`}
        />
        <KpiCard
          label="Overdue Invoices"
          value={data.overdue_count}
          variant={data.overdue_count > 0 ? 'error' : undefined}
        />
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <p className="text-sm font-medium text-gray-500">Storage Usage</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900">
            {storageUsedGb.toFixed(1)} / {data.storage.quota_gb} GB
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
              style={{ width: `${storagePercent}%` }}
            />
          </div>
          <p className="mt-1 text-xs text-gray-500">{Math.round(storagePercent)}% used</p>
        </div>
      </div>

      {/* Activity feed */}
      <section>
        <h2 className="mb-3 text-lg font-medium text-gray-900">Recent Activity</h2>
        {data.activity_feed.length === 0 ? (
          <p className="text-sm text-gray-500">No recent activity</p>
        ) : (
          <div className="space-y-2">
            {data.activity_feed.map((item) => (
              <div
                key={item.id}
                className="flex items-start justify-between rounded-lg border border-gray-200 bg-white p-4"
              >
                <div>
                  <p className="text-sm text-gray-900">{item.message}</p>
                  <p className="text-xs text-gray-500">{item.user_name}</p>
                </div>
                <time className="shrink-0 text-xs text-gray-400">
                  {new Date(item.timestamp).toLocaleString('en-NZ')}
                </time>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function KpiCard({
  label,
  value,
  change,
  variant,
}: {
  label: string
  value: number | string
  change?: number
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
      {change !== undefined && (
        <Badge variant={change >= 0 ? 'success' : 'error'} className="mt-2">
          {change >= 0 ? '+' : ''}
          {change.toFixed(1)}% vs last period
        </Badge>
      )}
    </div>
  )
}
