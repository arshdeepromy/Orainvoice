import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { DataTable, type Column } from '@/components/ui/DataTable'

interface GlobalAdminData {
  platform_mrr?: number
  active_orgs?: number
  total_orgs?: number
  churn_rate?: number
  error_counts?: ErrorCounts
  integration_health?: IntegrationStatus[]
  billing_issues?: BillingIssue[]
}

interface ErrorCounts {
  info: number
  warning: number
  error: number
  critical: number
}

interface IntegrationStatus {
  name: string
  status: 'healthy' | 'degraded' | 'down'
  last_checked: string
}

interface BillingIssue {
  id: string
  org_name: string
  issue_type: string
  amount: number
  created_at: string
}

interface IntegrationCostCard {
  name: string
  status: string
  total_cost_nzd: number
  total_usage: number
  usage_label: string
  breakdown: Record<string, unknown>
  balance?: number | null
  balance_currency?: string | null
  last_checked?: string | null
}

interface IntegrationCosts {
  period: string
  carjam: IntegrationCostCard
  sms: IntegrationCostCard
  smtp: IntegrationCostCard
  stripe: IntegrationCostCard
}

type Row = Record<string, unknown>

const billingColumns: Column<Row>[] = [
  { key: 'org_name', header: 'Organisation', sortable: true },
  { key: 'issue_type', header: 'Issue', sortable: true },
  {
    key: 'amount',
    header: 'Amount',
    sortable: true,
    render: (row) => `${Number(row.amount).toFixed(2)}`,
  },
  {
    key: 'created_at',
    header: 'Date',
    sortable: true,
    render: (row) => new Date(String(row.created_at)).toLocaleDateString('en-NZ'),
  },
]

const integrationStatusVariant: Record<IntegrationStatus['status'], 'success' | 'warning' | 'error'> = {
  healthy: 'success',
  degraded: 'warning',
  down: 'error',
}

const defaultErrorCounts: ErrorCounts = { info: 0, warning: 0, error: 0, critical: 0 }

/** Fetch a single endpoint, returning fallback on any error */
async function safeFetch<T>(url: string, fallback: T, params?: Record<string, unknown>): Promise<T> {
  try {
    const res = await apiClient.get<T>(url, params ? { params } : undefined)
    return res.data
  } catch {
    return fallback
  }
}

export function GlobalAdminDashboard() {
  const [data, setData] = useState<GlobalAdminData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [integrationCosts, setIntegrationCosts] = useState<IntegrationCosts | null>(null)
  const [costPeriod, setCostPeriod] = useState<'daily' | 'weekly' | 'monthly'>('monthly')

  useEffect(() => {
    let cancelled = false
    async function fetchDashboard() {
      const [analyticsOverview, mrrData, errorDashboard, integrations, billing] =
        await Promise.all([
          safeFetch<{ total_orgs?: number; active_orgs?: number; mrr?: number; churn_rate?: number }>(
            '/api/v2/admin/analytics/overview', {}
          ),
          safeFetch<{ total_mrr_nzd?: number; mrr?: number }>('/admin/reports/mrr', {}),
          safeFetch<{ by_severity?: Array<{ label: string; count_1h?: number; count_24h?: number; count_7d?: number; count?: number }>; total_24h?: number }>(
            '/admin/errors/dashboard', {}
          ),
          safeFetch<IntegrationStatus[]>('/admin/integrations', []).then((val) =>
            Array.isArray(val) ? val : []
          ),
          safeFetch<BillingIssue[]>('/admin/reports/billing-issues', []).then((val) =>
            Array.isArray(val) ? val : []
          ),
        ])

      if (cancelled) return

      const errorCounts = { ...defaultErrorCounts }
      if (errorDashboard.by_severity && Array.isArray(errorDashboard.by_severity)) {
        for (const item of errorDashboard.by_severity) {
          const key = item.label?.toLowerCase() as keyof ErrorCounts
          if (key in errorCounts) {
            errorCounts[key] = item.count_24h ?? item.count ?? 0
          }
        }
      }

      setData({
        platform_mrr: mrrData.total_mrr_nzd ?? analyticsOverview.mrr ?? 0,
        active_orgs: analyticsOverview.active_orgs ?? analyticsOverview.total_orgs ?? 0,
        total_orgs: analyticsOverview.total_orgs ?? 0,
        churn_rate: analyticsOverview.churn_rate ?? 0,
        error_counts: errorCounts,
        integration_health: integrations,
        billing_issues: billing,
      })
      setIsLoading(false)
    }
    fetchDashboard()
    const interval = setInterval(fetchDashboard, 60_000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [])

  // Fetch integration costs separately (with period filter)
  useEffect(() => {
    let cancelled = false
    async function fetchCosts() {
      const costs = await safeFetch<IntegrationCosts>(
        '/admin/dashboard/integration-costs',
        null as unknown as IntegrationCosts,
        { period: costPeriod },
      )
      if (!cancelled && costs) setIntegrationCosts(costs)
    }
    fetchCosts()
    const interval = setInterval(fetchCosts, 60_000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [costPeriod])

  if (isLoading) return <Spinner size="lg" label="Loading admin dashboard" className="py-20" />
  if (!data) return null

  const errorCounts = data.error_counts || { info: 0, warning: 0, error: 0, critical: 0 }
  const totalErrors = errorCounts.info + errorCounts.warning + errorCounts.error + errorCounts.critical

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-gray-900">Platform Dashboard</h1>

      {errorCounts.critical > 0 && (
        <AlertBanner variant="error" title="Critical Errors">
          {errorCounts.critical} critical error
          {errorCounts.critical !== 1 ? 's' : ''} detected. Review the error log immediately.
        </AlertBanner>
      )}

      {/* KPI cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {data.platform_mrr != null && (
          <KpiCard
            label="Platform MRR"
            value={`$${data.platform_mrr.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`}
          />
        )}
        {data.active_orgs != null && (
          <KpiCard
            label="Active Organisations"
            value={data.active_orgs}
            subtitle={data.total_orgs && data.total_orgs > data.active_orgs ? `${data.total_orgs} total` : undefined}
          />
        )}
        <KpiCard label="Total Errors (24h)" value={totalErrors} variant={totalErrors > 0 ? 'warning' : undefined} />
        <KpiCard label="Billing Issues" value={data.billing_issues?.length || 0} variant={(data.billing_issues?.length || 0) > 0 ? 'error' : undefined} />
      </div>

      {data.churn_rate != null && data.churn_rate > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          30-day churn rate: <span className="font-semibold">{data.churn_rate}%</span>
        </div>
      )}

      {/* Error counts by severity */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-medium text-gray-900">Errors by Severity</h2>
          <Link to="/admin/errors" className="text-sm text-blue-600 hover:underline">View error log →</Link>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <SeverityCard label="Critical" count={errorCounts.critical} variant="error" />
          <SeverityCard label="Error" count={errorCounts.error} variant="error" />
          <SeverityCard label="Warning" count={errorCounts.warning} variant="warning" />
          <SeverityCard label="Info" count={errorCounts.info} variant="info" />
        </div>
      </section>

      {/* Integration health */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-medium text-gray-900">Integration Health</h2>
          <Link to="/admin/integrations" className="text-sm text-blue-600 hover:underline">Manage integrations →</Link>
        </div>
        {!data.integration_health || data.integration_health.length === 0 ? (
          <p className="text-sm text-gray-500">No integrations configured</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {data.integration_health.map((integration) => (
              <div
                key={integration.name}
                className="flex items-center justify-between rounded-lg border border-gray-200 bg-white p-4"
              >
                <div>
                  <p className="font-medium capitalize text-gray-900">{integration.name}</p>
                  <p className="text-xs text-gray-500">
                    {integration.last_checked
                      ? `Checked ${new Date(integration.last_checked).toLocaleTimeString('en-NZ')}`
                      : 'Not configured'}
                  </p>
                </div>
                <Badge variant={integrationStatusVariant[integration.status]}>
                  {integration.status}
                </Badge>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Billing issues */}
      <section>
        <h2 className="mb-3 text-lg font-medium text-gray-900">Billing Issues</h2>
        <DataTable
          columns={billingColumns}
          data={data.billing_issues as unknown as Row[]}
          keyField="id"
          caption="Organisations with billing issues"
        />
      </section>

      {/* Integration Costs */}
      {integrationCosts && (
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-medium text-gray-900">Integration Costs &amp; Usage</h2>
            <div className="flex gap-1">
              {(['daily', 'weekly', 'monthly'] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => setCostPeriod(p)}
                  className={`px-3 py-1 text-xs rounded-md capitalize ${
                    costPeriod === p
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <IntegrationCostCardView card={integrationCosts.carjam} />
            <IntegrationCostCardView card={integrationCosts.sms} />
            <IntegrationCostCardView card={integrationCosts.smtp} />
            <IntegrationCostCardView card={integrationCosts.stripe} />
          </div>
        </section>
      )}
    </div>
  )
}

function KpiCard({
  label,
  value,
  variant,
  subtitle,
}: {
  label: string
  value: number | string
  variant?: 'error' | 'warning'
  subtitle?: string
}) {
  const textColor =
    variant === 'error'
      ? 'text-red-600'
      : variant === 'warning'
        ? 'text-amber-600'
        : 'text-gray-900'
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <p className="text-sm font-medium text-gray-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${textColor}`}>{value}</p>
      {subtitle && <p className="mt-0.5 text-xs text-gray-400">{subtitle}</p>}
    </div>
  )
}

function SeverityCard({
  label,
  count,
  variant,
}: {
  label: string
  count: number
  variant: 'error' | 'warning' | 'info'
}) {
  const bgColor =
    variant === 'error'
      ? 'bg-red-50 border-red-200'
      : variant === 'warning'
        ? 'bg-amber-50 border-amber-200'
        : 'bg-blue-50 border-blue-200'
  const textColor =
    variant === 'error'
      ? 'text-red-700'
      : variant === 'warning'
        ? 'text-amber-700'
        : 'text-blue-700'

  return (
    <div className={`rounded-lg border p-4 ${bgColor}`}>
      <p className={`text-sm font-medium ${textColor}`}>{label}</p>
      <p className={`mt-1 text-xl font-semibold ${textColor}`}>{count}</p>
    </div>
  )
}


const statusColors: Record<string, { bg: string; text: string; badge: 'success' | 'warning' | 'error' }> = {
  healthy: { bg: 'border-green-200', text: 'text-green-700', badge: 'success' },
  degraded: { bg: 'border-amber-200', text: 'text-amber-700', badge: 'warning' },
  down: { bg: 'border-red-200', text: 'text-red-700', badge: 'error' },
  not_configured: { bg: 'border-gray-200', text: 'text-gray-400', badge: 'warning' },
}

function IntegrationCostCardView({ card }: { card: IntegrationCostCard }) {
  const colors = statusColors[card.status] || statusColors.not_configured
  const fmt = (v: number) => `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  const breakdown = card.breakdown || {}

  return (
    <div className={`rounded-lg border bg-white p-4 ${colors.bg}`}>
      <div className="flex items-center justify-between mb-3">
        <p className="font-semibold text-gray-900">{card.name}</p>
        <Badge variant={colors.badge}>{card.status}</Badge>
      </div>

      <div className="space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">Cost</span>
          <span className="font-semibold text-gray-900">{fmt(card.total_cost_nzd)}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">Usage</span>
          <span className="font-medium text-gray-700">
            {card.total_usage.toLocaleString()} {card.usage_label}
          </span>
        </div>

        {card.balance != null && (
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">Balance</span>
            <span className="font-medium text-blue-600">
              {fmt(card.balance)} {card.balance_currency || 'NZD'}
            </span>
          </div>
        )}
      </div>

      {/* Breakdown details */}
      {Object.keys(breakdown).length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-100 space-y-1">
          {Object.entries(breakdown).map(([key, value]) => (
            <div key={key} className="flex justify-between text-xs">
              <span className="text-gray-400 capitalize">{key.replace(/_/g, ' ')}</span>
              <span className="text-gray-600">
                {typeof value === 'number'
                  ? key.includes('cost') || key.includes('fee') || key.includes('volume')
                    ? fmt(value)
                    : value.toLocaleString()
                  : String(value)}
              </span>
            </div>
          ))}
        </div>
      )}

      {card.last_checked && (
        <p className="mt-2 text-xs text-gray-400">
          Updated {new Date(card.last_checked).toLocaleString('en-NZ')}
        </p>
      )}
    </div>
  )
}
